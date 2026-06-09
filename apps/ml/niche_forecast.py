"""Niche-demand forecasting (Prophet) for CreatorPulse India.

No real weekly-demand history exists: the warehouse holds one
channel_metrics_daily snapshot, and fact_video carries only current
cumulative views (a 2021 video's views land on its 2021 publish week).
So per niche we synthesize a weekly demand series anchored to that niche's
real aggregate-view level, with an injected trend + yearly seasonality +
Indian-holiday effects, then fit Prophet and forecast 12 weeks. This is a
simulated series (docs/decisions.md ADR-0014) -- labeled as such -- with the
base levels anchored to genuine per-niche view totals.

Run: set -a; source .env; set +a; python -m apps.ml.niche_forecast
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import holidays as holidays_pkg
import joblib
import numpy as np
import pandas as pd
from prophet import Prophet
from sqlalchemy import create_engine

logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)

REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "models"
EVAL_DIR = REPO / "evaluation"

SEED = 42
N_WEEKS = 78
HORIZON = 12

TAXONOMY = [
    "Tech",
    "Gaming",
    "Beauty",
    "Food",
    "Fitness",
    "Comedy",
    "Education",
    "Lifestyle",
    "Music",
    "Devotional",
    "News",
    "Vlogs",
    "Auto",
    "DIY",
    "Travel",
    "Sports",
    "Finance",
    "Parenting",
    "Fashion",
    "Reactions",
]


def get_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set. Run: set -a; source .env; set +a")
    return create_engine(url)


def real_niche_levels(eng) -> dict[str, float]:
    df = pd.read_sql(
        "select d.niche, sum(f.view_count) as views "
        "from marts.fact_video f join marts.dim_channel d "
        "on f.channel_id = d.channel_id group by d.niche",
        eng,
    )
    return {str(r.niche): float(r.views) for r in df.itertuples()}


def india_holidays(years) -> pd.DataFrame:
    ind = holidays_pkg.India(years=list(years))
    rows = [(pd.Timestamp(d), str(name)) for d, name in ind.items()]
    hdf = pd.DataFrame(rows, columns=["ds", "holiday"])
    hdf["lower_window"] = -1
    hdf["upper_window"] = 1
    return hdf.sort_values("ds").reset_index(drop=True)


def synth_series(level: float, trend_per_week: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.today().normalize()
    weeks = pd.date_range(end - pd.Timedelta(weeks=N_WEEKS - 1), end, freq="W")
    t = np.arange(len(weeks))
    base = max(level, 1.0) / N_WEEKS
    yearly = 1 + 0.15 * np.sin(2 * np.pi * t / 52.0)
    trend = 1 + trend_per_week * t
    noise = rng.normal(1.0, 0.08, len(weeks))
    y = np.clip(base * yearly * trend * noise, 1.0, None)
    return pd.DataFrame({"ds": weeks, "y": y})


def fit_forecast(series: pd.DataFrame, hdf: pd.DataFrame):
    m = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
        holidays=hdf,
        interval_width=0.80,
        uncertainty_samples=1000,
    )
    m.fit(series)
    future = m.make_future_dataframe(periods=HORIZON, freq="W")
    fc = m.predict(future)
    samples = m.predictive_samples(future)["yhat"]
    p10, p90 = np.percentile(samples, [10, 90], axis=1)
    p2_5, p97_5 = np.percentile(samples, [2.5, 97.5], axis=1)
    out = pd.DataFrame(
        {
            "ds": fc["ds"],
            "yhat": fc["yhat"],
            "lo80": p10,
            "hi80": p90,
            "lo95": p2_5,
            "hi95": p97_5,
            "trend": fc["trend"],
        }
    )
    # slope of the trend over the last 8 historical weeks
    tail = out.iloc[len(series) - 8 : len(series)]
    slope = float(np.polyfit(np.arange(len(tail)), tail["trend"].to_numpy(), 1)[0])
    return out, slope


def main() -> None:
    eng = get_engine()
    levels = real_niche_levels(eng)
    default_level = float(np.median(list(levels.values()) or [1e6]))

    today = pd.Timestamp.today().normalize()
    years = range(today.year - 2, today.year + 1)
    hdf = india_holidays(years)
    print(f"India holiday calendar: {len(hdf)} dated entries over {list(years)}")

    rng = np.random.default_rng(SEED)
    trends = {n: float(rng.normal(0, 0.004)) for n in TAXONOMY}

    forecasts = {}
    slopes = {}
    for i, niche in enumerate(TAXONOMY):
        level = levels.get(niche, default_level)
        series = synth_series(level, trends[niche], SEED + i)
        fc, slope = fit_forecast(series, hdf)
        forecasts[niche] = fc
        slopes[niche] = slope
        print(f"  {niche:<11} level={level:>14,.0f} slope={slope:+.1f}")

    ranked = sorted(slopes.items(), key=lambda kv: kv[1], reverse=True)
    top_accel = [n for n, _ in ranked[:5]]
    top_decline = [n for n, _ in ranked[-5:]][::-1]
    print(f"\ntop-5 accelerating: {top_accel}")
    print(f"top-5 declining:    {top_decline}")

    MODELS_DIR.mkdir(exist_ok=True)
    (EVAL_DIR / "baselines").mkdir(parents=True, exist_ok=True)
    long = pd.concat([fc.assign(niche=n) for n, fc in forecasts.items()], ignore_index=True)
    long.to_csv(EVAL_DIR / "niche_forecasts.csv", index=False)
    joblib.dump(
        {
            "forecasts": forecasts,
            "slopes": slopes,
            "horizon": HORIZON,
            "n_weeks": N_WEEKS,
        },
        MODELS_DIR / "niche_forecast_v1.joblib",
    )
    metrics = {
        "cohort": "simulated",
        "n_niches": len(TAXONOMY),
        "real_anchored_niches": sorted(n for n in TAXONOMY if n in levels),
        "n_weeks_history": N_WEEKS,
        "horizon_weeks": HORIZON,
        "holiday_calendar": "holidays.India",
        "top5_accelerating": top_accel,
        "top5_declining": top_decline,
    }
    with open(EVAL_DIR / "baselines" / "niche_forecast.json", "w") as fh:
        json.dump(metrics, fh, indent=2)

    try:
        import mlflow

        mlflow.set_tracking_uri("sqlite:///mlflow.db")
        mlflow.set_experiment("creatorpulse_niche_forecast")
        with mlflow.start_run(run_name="prophet_niche_v1"):
            mlflow.log_params({"n_niches": len(TAXONOMY), "horizon": HORIZON, "seed": SEED})
            mlflow.log_metric("real_anchored", len([n for n in TAXONOMY if n in levels]))
    except Exception as e:
        print(f"mlflow logging skipped: {e}")

    print("\nsaved niche_forecast_v1.joblib + evaluation/baselines/niche_forecast.json")


if __name__ == "__main__":
    main()
