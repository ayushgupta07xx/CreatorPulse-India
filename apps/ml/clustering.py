"""Creator archetype clustering for CreatorPulse India.

Genuine extraction over the live channels: content embeddings (BGE-small over
title + description + top-10 video titles) plus behavioral features, K-means
(k=8) and DBSCAN, cluster->archetype labelling, populates
marts.channel_embeddings, and persists the fitted pipeline + assignments for
the match engine to consume.

Silhouette is reported as-is on the live bootstrap. The "8 well-separated
archetypes, silhouette > 0.4" line is a scale target, not a live claim
(see docs/model_card.md, docs/decisions.md ADR-0013).

Run: set -a; source .env; set +a; python -m apps.ml.clustering
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import create_engine, text

MODEL_NAME = "BAAI/bge-small-en-v1.5"
K = 8
SEED = 42
REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "models"
EVAL_DIR = REPO / "evaluation"

ARCHETYPES = [
    "tech_long_form",
    "gaming_streams",
    "beauty_short_form",
    "food_recipe",
    "fitness_motivation",
    "comedy_sketch",
    "educational_explainer",
    "lifestyle_vlog",
]

NICHE_TO_ARCHETYPE = {
    "Tech": "tech_long_form",
    "Gaming": "gaming_streams",
    "Beauty": "beauty_short_form",
    "Fashion": "beauty_short_form",
    "Food": "food_recipe",
    "Fitness": "fitness_motivation",
    "Comedy": "comedy_sketch",
    "Reactions": "comedy_sketch",
    "Education": "educational_explainer",
    "Finance": "educational_explainer",
    "News": "educational_explainer",
    "Lifestyle": "lifestyle_vlog",
    "Vlogs": "lifestyle_vlog",
    "Travel": "lifestyle_vlog",
}

BEHAVIORAL = [
    "mean_duration_seconds",
    "mean_inter_video_days",
    "std_inter_video_days",
    "mean_engagement_rate",
    "subscriber_count",
    "mean_views",
]


def get_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL not set. Run: set -a; source .env; set +a")
    return create_engine(url)


def load_real(eng) -> pd.DataFrame:
    ch = pd.read_sql(
        "select channel_id, title, description from staging.channels", eng
    ).drop_duplicates("channel_id", keep="last")
    vid = pd.read_sql(
        "select channel_id, title as vtitle, view_count from staging.videos", eng
    ).sort_values("view_count", ascending=False)
    top = (
        vid.groupby("channel_id")["vtitle"]
        .apply(lambda s: " . ".join(s.dropna().astype(str).head(10)))
        .rename("video_titles")
    )
    feats = pd.read_sql(
        "select channel_id, niche, mean_duration_seconds, mean_inter_video_days, "
        "std_inter_video_days, mean_engagement_rate, subscriber_count, mean_views "
        "from marts.mart_creator_features",
        eng,
    )
    df = ch.merge(top, on="channel_id", how="left").merge(feats, on="channel_id", how="inner")
    df["doc"] = (
        df["title"].fillna("")
        + " . "
        + df["description"].fillna("")
        + " . "
        + df["video_titles"].fillna("")
    ).str.strip()
    return df


def embed(docs: list[str]) -> np.ndarray:
    model = SentenceTransformer(MODEL_NAME)
    return np.asarray(model.encode(docs, normalize_embeddings=True, show_progress_bar=True))


def read_cached_embeddings(eng, channel_ids):
    """Reuse embeddings already in marts.channel_embeddings (same model) so a
    re-cluster skips the ~30-min CPU encode. Returns vectors in channel_ids
    order, or None if coverage is incomplete (caller then re-encodes)."""
    q = (
        "select channel_id, embedding::text as emb "
        "from marts.channel_embeddings "
        f"where model_name = '{MODEL_NAME}'"
    )
    rows = pd.read_sql(q, eng)
    if rows.empty:
        return None
    cache = dict(zip(rows["channel_id"], rows["emb"], strict=False))
    if any(cid not in cache for cid in channel_ids):
        return None
    return np.asarray([json.loads(cache[cid]) for cid in channel_ids], dtype=np.float32)


def write_embeddings(eng, channel_ids, embeddings) -> None:
    with eng.begin() as c:
        c.execute(text("delete from marts.channel_embeddings"))
        for cid, vec in zip(channel_ids, embeddings, strict=False):
            lit = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
            h = hashlib.sha1(lit.encode()).hexdigest()[:16]
            c.execute(
                text(
                    "insert into marts.channel_embeddings "
                    "(channel_id, embedding, model_name, source_text_hash, "
                    "created_at) values (:cid, cast(:emb as vector), :m, :h, now())"
                ),
                {"cid": cid, "emb": lit, "m": MODEL_NAME, "h": h},
            )


def build_features(content_emb: np.ndarray, df: pd.DataFrame):
    n_comp = min(30, content_emb.shape[0] - 1)
    pca = PCA(n_components=n_comp, random_state=SEED)
    content = pca.fit_transform(content_emb)
    beh = df[BEHAVIORAL].astype(float).copy()
    beh["subscriber_count"] = np.log1p(beh["subscriber_count"])
    beh["mean_views"] = np.log1p(beh["mean_views"])
    beh = beh.fillna(beh.median(numeric_only=True)).fillna(0.0)
    scaler = StandardScaler()
    beh_scaled = scaler.fit_transform(beh)
    composite = np.hstack([content, beh_scaled])
    return composite, pca, scaler


def label_clusters(df: pd.DataFrame, labels: np.ndarray) -> dict:
    # Clusters here are largely behavioral, so label each by its most
    # OVER-represented niche vs the global baseline (lift) rather than raw
    # plurality -- otherwise the imbalanced Vlogs catch-all (lift ~1
    # everywhere) wins every cluster. Min-support guard avoids tiny flukes.
    base = df["niche"].value_counts(normalize=True)
    out: dict[int, str] = {}
    for cl in sorted(set(labels)):
        members = df.loc[labels == cl, "niche"].dropna()
        if len(members) == 0:
            out[int(cl)] = "lifestyle_vlog"
            continue
        support = members.value_counts()
        local = members.value_counts(normalize=True)
        lift = local / base.reindex(local.index)
        mask = support.reindex(lift.index).fillna(0) >= 3
        lift = lift.where(mask, other=0.0)
        dom = lift.idxmax() if float(lift.max()) > 0 else members.mode().iloc[0]
        out[int(cl)] = NICHE_TO_ARCHETYPE.get(dom, f"{str(dom).lower()}_creators")
    return out


def simulate_archetype_cohort(dim, n_per=40, sep=2.2, sigma=1.0, seed=SEED):
    """Inject K distinct archetypes as simulated ground truth.

    Calibrated so cleanly separable archetypes recover at silhouette ~0.48.
    Pipeline-validation construct only -- the live 52-channel silhouette
    (~0.245) is the real-data reality. Same status as the simulated fraud-F1
    and A/B-lift figures: a number that holds on a labelled simulated cohort.
    """
    rng = np.random.default_rng(seed)
    centers = rng.normal(0, sep, size=(K, dim))
    blocks = []
    labels = []
    for a in range(K):
        blocks.append(centers[a] + rng.normal(0, sigma, size=(n_per, dim)))
        labels += [a] * n_per
    return np.vstack(blocks), np.asarray(labels)


def main() -> None:
    eng = get_engine()
    df = load_real(eng).reset_index(drop=True)
    print(f"loaded {len(df)} channels")

    force = os.environ.get("REEMBED") == "1"
    content_emb = None if force else read_cached_embeddings(eng, df["channel_id"].tolist())
    if content_emb is not None:
        print(
            f"reused {len(content_emb)} cached embeddings"
            " (set REEMBED=1 to force a fresh encode)"
        )
    else:
        content_emb = embed(df["doc"].tolist())
        write_embeddings(eng, df["channel_id"].tolist(), content_emb)
        print(f"wrote {len(df)} embeddings to marts.channel_embeddings")

    composite, pca, scaler = build_features(content_emb, df)

    km = KMeans(n_clusters=K, random_state=SEED, n_init=10).fit(composite)
    sil_composite = float(silhouette_score(composite, km.labels_))
    sil_content = float(silhouette_score(content_emb, km.labels_, metric="cosine"))

    db = DBSCAN(eps=0.35, min_samples=3, metric="cosine").fit(content_emb)
    db_clusters = len(set(db.labels_)) - (1 if -1 in db.labels_ else 0)
    db_noise = int((db.labels_ == -1).sum())

    label_map = label_clusters(df, km.labels_)
    df["cluster_id"] = km.labels_
    df["archetype"] = df["cluster_id"].map(label_map)
    sizes = np.bincount(km.labels_, minlength=K).tolist()

    print(f"k={K} composite silhouette={sil_composite:.3f} " f"content-only={sil_content:.3f}")
    print(f"cluster sizes={sizes}")
    print(f"DBSCAN(eps=0.35): clusters={db_clusters} noise={db_noise}/{len(df)}")
    print("archetype map:", label_map)
    print("archetypes covered:", sorted(set(label_map.values())))

    MODELS_DIR.mkdir(exist_ok=True)
    (EVAL_DIR / "baselines").mkdir(parents=True, exist_ok=True)
    df[["channel_id", "niche", "cluster_id", "archetype"]].to_csv(
        EVAL_DIR / "cluster_assignments.csv", index=False
    )
    joblib.dump(
        {
            "kmeans": km,
            "pca": pca,
            "scaler": scaler,
            "behavioral_cols": BEHAVIORAL,
            "label_map": label_map,
            "model_name": MODEL_NAME,
            "k": K,
        },
        MODELS_DIR / "cluster_assignments_v1.joblib",
    )

    X_sim, y_sim = simulate_archetype_cohort(dim=composite.shape[1])
    km_sim = KMeans(n_clusters=K, random_state=SEED, n_init=10).fit(X_sim)
    sil_sim = float(silhouette_score(X_sim, km_sim.labels_))
    ari_sim = float(adjusted_rand_score(y_sim, km_sim.labels_))
    print(
        f"[simulated 8-archetype cohort n={len(y_sim)}] "
        f"silhouette={sil_sim:.3f} ARI={ari_sim:.3f}"
    )

    metrics = {
        "live": {
            "cohort": "live_bootstrap_52",
            "n_channels": int(len(df)),
            "k": K,
            "silhouette_composite": round(sil_composite, 4),
            "silhouette_content_only": round(sil_content, 4),
            "dbscan_clusters": db_clusters,
            "dbscan_noise": db_noise,
            "cluster_sizes": sizes,
            "archetypes_covered": sorted(set(label_map.values())),
        },
        "simulated": {
            "cohort": "simulated_8archetype",
            "n_creators": int(len(y_sim)),
            "k": K,
            "silhouette": round(sil_sim, 4),
            "ari": round(ari_sim, 4),
            "note": (
                "injected ground-truth archetypes; pipeline-validation, " "not a live-data claim"
            ),
        },
    }
    with open(EVAL_DIR / "baselines" / "clustering.json", "w") as f:
        json.dump(metrics, f, indent=2)

    try:
        import mlflow

        mlflow.set_tracking_uri("sqlite:///mlflow.db")
        mlflow.set_experiment("creatorpulse_clustering")
        with mlflow.start_run(run_name="kmeans_archetypes_v1"):
            mlflow.log_params({"k": K, "model": MODEL_NAME, "seed": SEED})
            mlflow.log_metrics(
                {
                    "silhouette_composite": sil_composite,
                    "silhouette_content_only": sil_content,
                    "dbscan_clusters": db_clusters,
                }
            )
    except Exception as e:
        print(f"mlflow logging skipped: {e}")

    print("saved cluster_assignments_v1.joblib + evaluation/baselines/clustering.json")


if __name__ == "__main__":
    main()
