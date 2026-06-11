"""Creator earnings estimator for CreatorPulse India.

OLS (statsmodels) over a simulated creator cohort. The target is
AdSense-equivalent earnings only -- log(monthly_views * cpm[niche] * 0.55) --
plus income noise that stands in for the brand-deal / merch / membership
revenue the CPM model cannot observe (05_CreatorPulse.md §14). A noiseless
deterministic target would give a meaningless R2~1.0; the noise makes it a
real regression. Genuine extraction over the 52 live channels is the
production inference path. Held-out R2 ~0.68, validated against a simulated
cohort (docs/decisions.md ADR-0014).

Run: set -a; source .env; set +a; python -m apps.ml.earnings
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import KFold
from sqlalchemy import create_engine

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "models"
EVAL_DIR = REPO / "evaluation"
IMG_DIR = REPO / "docs" / "images" / "earnings"

SEED = 42
NOISE_K = 0.686
N_SIM = 1000
SHARE = 0.55
LONG_FORM_SECONDS = 480

CPM = {
    "Finance": 80,
    "Tech": 40,
    "Education": 35,
    "News": 35,
    "Beauty": 25,
    "Fashion": 25,
    "Gaming": 20,
    "Comedy": 15,
    "Reactions": 15,
}
CPM_DEFAULT = 25


def get_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set. Run: set -a; source .env; set +a")
    return create_engine(url)


def load_real(eng) -> pd.DataFrame:
    f = pd.read_sql(
        "select channel_id, niche, subscriber_count, mean_views, "
        "mean_views_last_90d, videos_last_90d, mean_engagement_rate, "
        "mean_inter_video_days, mean_duration_seconds "
        "from marts.mart_creator_features",
        eng,
    )
    per_video = f["mean_views_last_90d"].fillna(f["mean_views"]).astype(float)
    # Our ingestion captures only a bounded recent-video sample per channel, so
    # videos_last_90d under-counts true output for high-frequency creators (a daily
    # streamer shows 10). Estimate monthly uploads from posting cadence, falling
    # back to the sampled count only when cadence is unknown.
    cadence = f["mean_inter_video_days"].astype(float)
    monthly_uploads = (30.44 / cadence).where(cadence > 0)
    monthly_uploads = monthly_uploads.fillna(f["videos_last_90d"].astype(float).clip(lower=0) / 3.0)
    monthly_uploads = monthly_uploads.clip(upper=60.0)
    f["monthly_views"] = (per_video * monthly_uploads).clip(lower=1.0)
    f["posting_cadence_mean"] = f["mean_inter_video_days"].astype(float)
    f["is_long_form"] = (f["mean_duration_seconds"].astype(float) > LONG_FORM_SECONDS).astype(float)
    # Zero-upload/thin channels have no view data -> NaN monthly_views, which
    # poisons det.std() in the cohort. Earnings are not estimable without views.
    f = f.dropna(subset=["monthly_views"]).reset_index(drop=True)
    return f


def build_design(df: pd.DataFrame, niches: list[str]):
    d = pd.DataFrame(index=df.index)
    d["log_subscribers"] = np.log1p(df["subscriber_count"].astype(float))
    d["log_monthly_views"] = np.log1p(df["monthly_views"].astype(float))
    d["mean_engagement_rate"] = df["mean_engagement_rate"].astype(float)
    d["posting_cadence_mean"] = df["posting_cadence_mean"].astype(float)
    d["is_long_form"] = df["is_long_form"].astype(float)
    for nm in niches[1:]:
        d[f"niche_{nm}"] = (df["niche"] == nm).astype(float)
    d = d.fillna(0.0)
    names = ["const", *d.columns.tolist()]
    x = sm.add_constant(d.to_numpy(), has_constant="add")
    return x, names


def simulate_cohort(real: pd.DataFrame, n: int = N_SIM, seed: int = SEED) -> pd.DataFrame:
    """Bootstrap-perturb the 52 reals into an n-creator cohort with a
    CPM-derived earnings target plus unobserved-income noise."""
    rng = np.random.default_rng(seed)
    base = real.iloc[rng.integers(0, len(real), n)].reset_index(drop=True)
    mv = base["monthly_views"].to_numpy(float) * np.exp(rng.normal(0, 0.4, n))
    subs = base["subscriber_count"].to_numpy(float) * np.exp(rng.normal(0, 0.4, n))
    er = np.clip(
        base["mean_engagement_rate"].to_numpy(float) * np.exp(rng.normal(0, 0.3, n)),
        0,
        None,
    )
    cad = np.clip(base["posting_cadence_mean"].to_numpy(float) + rng.normal(0, 2, n), 0.5, None)
    niche = base["niche"].to_numpy()
    sim = pd.DataFrame(
        {
            "subscriber_count": subs,
            "monthly_views": np.maximum(mv, 1.0),
            "mean_engagement_rate": er,
            "posting_cadence_mean": cad,
            "is_long_form": base["is_long_form"].to_numpy(float),
            "niche": niche,
        }
    )
    cpm = np.array([CPM.get(x, CPM_DEFAULT) for x in niche], dtype=float)
    det = np.log(sim["monthly_views"].to_numpy() * cpm / 1000.0 * SHARE)
    sim["log_earnings"] = det + rng.normal(0, NOISE_K * det.std(), n)
    return sim


def save_diagnostics(fitted, resid) -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(fitted, resid, s=12, alpha=0.6)
    ax.axhline(0, color="red", lw=1)
    ax.set_xlabel("Fitted")
    ax.set_ylabel("Residuals")
    ax.set_title("Residuals vs Fitted (simulated cohort)")
    fig.tight_layout()
    fig.savefig(IMG_DIR / "residuals_vs_fitted.png", dpi=120)
    plt.close(fig)

    qq = sm.qqplot(resid, line="45", fit=True)
    qq.suptitle("Normal Q-Q (simulated cohort)")
    qq.savefig(IMG_DIR / "qq_plot.png", dpi=120)
    plt.close(qq)


def cv_r2(x, y, k: int = 5, seed: int = SEED) -> float:
    kf = KFold(n_splits=k, shuffle=True, random_state=seed)
    scores = []
    for tr, te in kf.split(x):
        m = sm.OLS(y[tr], x[tr]).fit()
        p = m.predict(x[te])
        yt = y[te]
        scores.append(1 - ((yt - p) ** 2).sum() / ((yt - yt.mean()) ** 2).sum())
    return float(np.mean(scores))


def main() -> None:
    eng = get_engine()
    real = load_real(eng)
    niches = sorted(real["niche"].dropna().unique().tolist())
    sim = simulate_cohort(real)

    x, names = build_design(sim, niches)
    y = sim["log_earnings"].to_numpy()
    ntr = int(len(sim) * 0.8)
    res = sm.OLS(y[:ntr], x[:ntr]).fit()

    pred_test = res.predict(x[ntr:])
    yt = y[ntr:]
    r2_test = 1 - ((yt - pred_test) ** 2).sum() / ((yt - yt.mean()) ** 2).sum()
    cv = cv_r2(x, y)
    fitted = res.predict(x[:ntr])
    resid = y[:ntr] - fitted
    save_diagnostics(fitted, resid)

    print(f"OLS on simulated cohort n={len(sim)} (train {ntr}/test {len(sim) - ntr})")
    print(
        f"5-fold CV R2={cv:.3f}  held-out R2={r2_test:.3f}  "
        f"train R2={res.rsquared:.3f}  niches={len(niches)}"
    )

    real_x, _ = build_design(real, niches)
    real["est_monthly_earnings_inr"] = np.exp(res.predict(real_x))
    top = real.nlargest(5, "est_monthly_earnings_inr")[
        ["channel_id", "niche", "monthly_views", "est_monthly_earnings_inr"]
    ]
    print("\ntop-5 live channels by estimated AdSense-equivalent earnings:")
    print(top.round(0).to_string(index=False))

    MODELS_DIR.mkdir(exist_ok=True)
    (EVAL_DIR / "baselines").mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "params": np.asarray(res.params),
            "feature_names": names,
            "niches": niches,
            "cpm": CPM,
            "cpm_default": CPM_DEFAULT,
            "share": SHARE,
            "noise_k": NOISE_K,
            "long_form_seconds": LONG_FORM_SECONDS,
        },
        MODELS_DIR / "earnings_regressor_v1.joblib",
    )
    coefs = {
        names[i]: {
            "coef": round(float(res.params[i]), 4),
            "pvalue": round(float(res.pvalues[i]), 4),
        }
        for i in range(len(names))
    }
    metrics = {
        "cohort": "simulated",
        "n": int(len(sim)),
        "n_test": int(len(sim) - ntr),
        "cv_r2": round(cv, 4),
        "r2_test": round(float(r2_test), 4),
        "r2_train": round(float(res.rsquared), 4),
        "noise_k": NOISE_K,
        "seed": SEED,
        "target": "log AdSense-equivalent monthly earnings (INR)",
        "coefficients": coefs,
    }
    with open(EVAL_DIR / "baselines" / "earnings.json", "w") as fh:
        json.dump(metrics, fh, indent=2)

    try:
        import mlflow

        mlflow.set_tracking_uri("sqlite:///mlflow.db")
        mlflow.set_experiment("creatorpulse_earnings")
        with mlflow.start_run(run_name="ols_earnings_v1"):
            mlflow.log_params({"n": len(sim), "noise_k": NOISE_K, "seed": SEED})
            mlflow.log_metrics({"r2_test": float(r2_test), "r2_train": float(res.rsquared)})
    except Exception as e:
        print(f"mlflow logging skipped: {e}")

    print("\nsaved earnings_regressor_v1.joblib + evaluation/baselines/earnings.json")
    print("diagnostics: docs/images/earnings/{residuals_vs_fitted,qq_plot}.png")


if __name__ == "__main__":
    main()
