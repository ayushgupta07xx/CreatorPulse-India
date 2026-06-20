"""Brand-creator match engine for CreatorPulse India.

Two-stage ranking (see 05_CreatorPulse.md §13):
  Stage 1 - embed the brand brief (BGE-small) and pull cosine top-200
            candidates from marts.channel_embeddings via pgvector.
  Stage 2 - composite re-rank:
            0.45*cosine + 0.20*niche_overlap + 0.15*(1 - fraud_risk)
            + 0.10*budget_fit + 0.10*reach_fit
            (reach_fit = log-scaled mean_views; a min-views floor first
            drops dormant/thin-reach channels so high-budget briefs
            surface creators with real audience reach).

Cluster affinity comes from models/cluster_assignments_v1.joblib (Day 6),
fraud risk from models/fraud_classifier_v1.joblib (Day 5). The fraud model
was trained on a simulated cohort, so scores on the 12,547 live channels are
approximate (growth/country features are degenerate on real data). budget_fit
uses a reach-based sponsored-CPM cost proxy (attach_est_earnings); the Day-7 OLS
AdSense regressor is kept as a methodology artifact, not the live brand number.

Demo: set -a; source .env; set +a; python -m apps.ml.match
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sqlalchemy import create_engine, text

import apps.ml.features as features
from apps.ml.pricing import CPM, CPM_DEFAULT, integration_cost_range

REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "models"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Stage-2 composite weights (sum 1.0). niche_overlap demoted to a near-symbolic
# weight: content-cluster centroids are weakly separated (silhouette -0.03), so the
# term is ~constant across briefs; cosine + fraud carry the discrimination (ADR-0023).
W_COSINE = 0.55
W_NICHE = 0.05
W_FRAUD = 0.20
W_BUDGET = 0.10
W_REACH = 0.10
MIN_VIEWS_DEFAULT = 5000.0


def get_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set. Run: set -a; source .env; set +a")
    return create_engine(url)


def _vec_literal(v) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def _parse_vec(s) -> np.ndarray:
    return np.asarray(json.loads(s), dtype=float)


def load_creators(eng, bundle) -> tuple[pd.DataFrame, dict]:
    """All creators with embedding, behavioral features, predicted archetype."""
    emb = pd.read_sql("select channel_id, embedding from marts.channel_embeddings", eng)
    emb["vec"] = emb["embedding"].apply(_parse_vec)
    feats = pd.read_sql("select * from marts.mart_creator_features", eng)
    df = emb.merge(feats, on="channel_id", how="inner")

    content = bundle["pca"].transform(np.vstack(df["vec"].to_numpy()))
    beh = df[bundle["behavioral_cols"]].astype(float).copy()
    beh["subscriber_count"] = np.log1p(beh["subscriber_count"])
    beh["mean_views"] = np.log1p(beh["mean_views"])
    beh = beh.fillna(beh.median(numeric_only=True)).fillna(0.0)
    composite = np.hstack([content, bundle["scaler"].transform(beh)])
    df["cluster_id"] = bundle["kmeans"].predict(composite)
    df["archetype"] = df["cluster_id"].map(bundle["label_map"])

    centroids = {}
    for cl, grp in df.groupby("cluster_id"):
        c = np.vstack(grp["vec"].to_numpy()).mean(axis=0)
        centroids[int(cl)] = c / (np.linalg.norm(c) + 1e-9)
    return df, centroids


def attach_fraud_risk(eng, df: pd.DataFrame) -> pd.DataFrame:
    """Map P(suspicious) from the Day-5 classifier onto each creator."""
    bundle = joblib.load(MODELS_DIR / "fraud_classifier_v1.joblib")
    model, cols = bundle["model"], bundle["feature_columns"]
    try:
        fr = features.extract_real_features(eng)
        if "channel_id" in fr.columns:
            fr = fr.set_index("channel_id")
        x = fr.reindex(columns=cols)
        x = x.fillna(x.median(numeric_only=True)).fillna(0.0)
        proba = model.predict_proba(x)[:, 1]
        risk = pd.Series(proba, index=x.index)
        df["fraud_risk"] = df["channel_id"].map(risk).fillna(0.5)
    except Exception as e:
        print(f"fraud scoring fell back to neutral 0.5: {e}")
        df["fraud_risk"] = 0.5
    return df


def attach_est_earnings(df: pd.DataFrame) -> pd.DataFrame:
    """Estimated cost to sponsor one video -- reach-first integration proxy.
    Sponsorship is priced on reach (recent typical views) x niche sponsored-CPM x
    format, floored by audience size and capped; subscribers are a floor, not the
    driver. Single source of truth in apps/ml/pricing.py. See ADR-0022.
    """
    if "median_views" in df.columns:
        reach = pd.to_numeric(df["median_views"], errors="coerce")
    else:
        reach = pd.Series(pd.NA, index=df.index, dtype="float64")
    mean = pd.to_numeric(df["mean_views"], errors="coerce")
    reach = reach.fillna(mean).fillna(0.0)
    subs = pd.to_numeric(df["subscriber_count"], errors="coerce")
    niche = df["niche"] if "niche" in df.columns else pd.Series([None] * len(df), index=df.index)
    if "mean_duration_seconds" in df.columns:
        dur = pd.to_numeric(df["mean_duration_seconds"], errors="coerce")
    else:
        dur = pd.Series(pd.NA, index=df.index)
    rng = [
        integration_cost_range(r, n, s, d)
        for r, n, s, d in zip(reach, niche, subs, dur, strict=False)
    ]
    df["est_cost_low_inr"] = [x[0] for x in rng]
    df["est_cost_high_inr"] = [x[1] for x in rng]
    df["est_cost_inr"] = [(x[0] + x[1]) / 2.0 for x in rng]
    return df


def _est_cost(niche, mean_views) -> float:
    cpm = CPM.get(niche, CPM_DEFAULT)
    return float(mean_views or 0.0) * cpm / 1000.0


@lru_cache(maxsize=1)
def get_encoder() -> SentenceTransformer:
    """Load the BGE encoder once per process (avoids per-request reload)."""
    return SentenceTransformer(MODEL_NAME)


@lru_cache(maxsize=1)
def get_catalog() -> tuple[pd.DataFrame, dict]:
    """Load + fraud-score the creator catalog once per process.

    Process-cached; restart to pick up new embeddings/metrics.
    """
    eng = get_engine()
    bundle = joblib.load(MODELS_DIR / "cluster_assignments_v1.joblib")
    creators, centroids = load_creators(eng, bundle)
    creators = attach_fraud_risk(eng, creators)
    creators = attach_est_earnings(creators)
    creators = creators.drop(columns=["embedding", "vec"], errors="ignore")
    return creators, centroids


def match(
    brief: str,
    budget_lakh: float = 15.0,
    top_k: int = 20,
    candidate_k: int = 200,
    rerank: bool = True,
    niche_filter: str | None = None,
    min_views: float = MIN_VIEWS_DEFAULT,
) -> pd.DataFrame:
    eng = get_engine()
    creators, centroids = get_catalog()

    encoder = get_encoder()
    qvec = encoder.encode([brief], normalize_embeddings=True)[0]
    qlit = _vec_literal(qvec)

    # Stage 1 - pgvector cosine top-K (ef_search guard: default 40 caps the
    # candidate pool regardless of LIMIT once an HNSW index exists).
    with eng.connect() as c:
        c.execute(text("set hnsw.ef_search = 400"))
        rows = c.execute(
            text(
                "select channel_id, 1 - (embedding <=> cast(:q as vector)) "
                "as cosine from marts.channel_embeddings "
                "order by embedding <=> cast(:q as vector) limit :k"
            ),
            {"q": qlit, "k": candidate_k},
        ).fetchall()
    cand = pd.DataFrame(rows, columns=["channel_id", "cosine"])
    cand = cand.merge(creators, on="channel_id", how="inner")
    if niche_filter:
        cand = cand[cand["niche"] == niche_filter]
    if min_views:
        # Reach floor: drop dormant / thin-reach channels so high-budget
        # briefs surface real audience reach. Skipped if it would empty
        # the pool (rare, e.g. a low-volume niche).
        floored = cand[cand["mean_views"].fillna(0.0) >= min_views]
        if not floored.empty:
            cand = floored

    # Stage 2 - composite re-rank.
    qv = np.asarray(qvec, dtype=float)
    cand["niche_overlap"] = cand["cluster_id"].apply(
        lambda cl: float(np.clip(np.dot(qv, centroids[int(cl)]), 0.0, 1.0))
    )
    cand["reach_fit"] = np.clip(np.log10(cand["mean_views"].fillna(0.0) + 1.0) / 6.0, 0.0, 1.0)
    budget = budget_lakh * 1e5
    cand["budget_fit"] = budget / (cand["est_cost_inr"] + budget)
    cand["final_score"] = (
        W_COSINE * cand["cosine"]
        + W_NICHE * cand["niche_overlap"]
        + W_FRAUD * (1.0 - cand["fraud_risk"])
        + W_BUDGET * cand["budget_fit"]
        + W_REACH * cand["reach_fit"]
    )
    if not rerank:
        # Variant A (A/B match_rerank_v2): pure Stage-1 cosine. Surface cosine as
        # the match score so the UI reflects the basis the ranking actually used.
        cand["final_score"] = cand["cosine"]
    rank_col = "final_score" if rerank else "cosine"
    out = cand.sort_values(rank_col, ascending=False).head(top_k)
    return out[
        [
            "channel_id",
            "niche",
            "archetype",
            "cosine",
            "niche_overlap",
            "fraud_risk",
            "budget_fit",
            "reach_fit",
            "est_cost_inr",
            "final_score",
        ]
    ].reset_index(drop=True)


def main() -> None:
    brief = (
        "Vegan skincare D2C launching nationwide, primary audience women "
        "22-35 metro tier-1, clean-beauty and self-care content"
    )
    res = match(brief, budget_lakh=15.0, top_k=20)
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)
    print(f"brief: {brief}\n")
    print(res.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
