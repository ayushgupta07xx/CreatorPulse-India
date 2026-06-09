"""Cached data-access layer for the CreatorPulse Streamlit app.

Reads the warehouse/operational Postgres and the committed model bundles.
The cluster derivation mirrors ``apps.ml.match.load_creators`` (ADR-0013) so the
frontend stays torch-free (no sentence-transformers pulled into the deploy); keep
the two in sync if the Day-6 clustering pipeline changes. Clusters are derived
from the committed joblib, never the gitignored evaluation CSV, so the deployed
app reproduces them without the eval artifacts.
"""

from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import bindparam, create_engine, text

load_dotenv()

MODELS_DIR = Path(__file__).resolve().parents[3] / "models"

# numeric columns coerced to float (psycopg2 returns NUMERIC as Decimal)
NUM_COLS = [
    "subscriber_count",
    "view_count",
    "video_count",
    "days_since_last_upload",
    "mean_views",
    "median_views",
    "mean_engagement_rate",
    "median_engagement_rate",
    "mean_like_rate",
    "mean_comment_rate",
    "mean_comment_to_like_ratio",
    "mean_inter_video_days",
    "std_inter_video_days",
    "engagement_cv",
    "videos_last_30d",
    "videos_last_90d",
    "mean_views_last_90d",
    "mean_engagement_rate_last_90d",
]


@st.cache_resource(show_spinner=False)
def get_engine():
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


@st.cache_resource(show_spinner=False)
def load_cluster_bundle() -> dict:
    return joblib.load(MODELS_DIR / "cluster_assignments_v1.joblib")


@st.cache_resource(show_spinner=False)
def load_niche_forecast() -> dict:
    return joblib.load(MODELS_DIR / "niche_forecast_v1.joblib")


def _parse_vec(v) -> np.ndarray:
    if isinstance(v, list | tuple | np.ndarray):
        return np.asarray(v, dtype=float)
    return np.fromstring(str(v).strip("[]"), sep=",")


@st.cache_data(show_spinner="Loading creators…")
def load_creators_df() -> pd.DataFrame:
    """All creators with predicted ``cluster_id`` + ``archetype``, features, and dim.

    Mirrors ``apps.ml.match.load_creators`` for the cluster step (ADR-0013).
    """
    eng = get_engine()
    bundle = load_cluster_bundle()

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

    dim = pd.read_sql(
        "select distinct on (c.channel_id) c.channel_id, c.title, s.thumbnail_url "
        "from marts.dim_channel c "
        "left join staging.channels s on s.channel_id = c.channel_id "
        "order by c.channel_id, c.effective_from desc",
        eng,
    )
    df = df.merge(dim, on="channel_id", how="left")

    for col in NUM_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.drop(columns=["embedding", "vec"])


@st.cache_data(show_spinner=False)
def top_videos_in_cluster(channel_ids: tuple[str, ...], days: int, limit: int = 10) -> pd.DataFrame:
    """Most-viewed videos across the given channels within a recency window."""
    eng = get_engine()
    q = text(
        "select f.video_id, v.title, f.channel_id, f.view_count, "
        "f.engagement_rate, f.published_at "
        "from marts.fact_video f "
        "join (select distinct on (video_id) video_id, title "
        "      from staging.videos order by video_id) v on v.video_id = f.video_id "
        "where f.channel_id in :ids "
        "  and f.published_at >= now() - (:days * interval '1 day') "
        "order by f.view_count desc limit :limit"
    ).bindparams(bindparam("ids", expanding=True))
    with eng.connect() as cx:
        return pd.read_sql(q, cx, params={"ids": list(channel_ids), "days": days, "limit": limit})
