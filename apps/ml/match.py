"""Brand-creator match engine for CreatorPulse India.

Two-stage ranking (see 05_CreatorPulse.md §13):
  Stage 0 - expand/disambiguate the brief via Groq (apps/ml/query_expand;
            no-ops without GROQ_API_KEY) so short/polysemous briefs embed
            with the creator-economy sense (ADR-0026).
  Stage 1 - embed the (expanded) brief (BGE-small) and pull cosine top-200
            candidates from marts.channel_embeddings via pgvector.
  Stage 2 - composite re-rank:
            0.55*cosine + 0.05*niche_overlap + 0.20*(1 - fraud_risk)
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
import apps.ml.query_expand as query_expand
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
W_BRAND_PENALTY = 0.15  # soft demote for corporate/brand-owned channels (ADR-0029)
MIN_VIEWS_DEFAULT = 5000.0

_BRAND_TOKENS: list[str] | None = None


def _brand_tokens() -> list[str]:
    """Lowercase tokens from data/brand_channels.csv (committed registry)."""
    global _BRAND_TOKENS
    if _BRAND_TOKENS is None:
        import csv
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "data" / "brand_channels.csv"
        toks: list[str] = []
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                for row in csv.DictReader(r for r in fh if not r.startswith("#")):
                    t = (row.get("token") or "").strip().lower()
                    if t:
                        toks.append(t)
        _BRAND_TOKENS = toks
    return _BRAND_TOKENS


def _flag_brand(text_series: pd.Series) -> pd.Series:
    """True where any registry token appears on a word boundary in the text."""
    import re

    toks = _brand_tokens()
    if not toks:
        return pd.Series(False, index=text_series.index)
    pat = re.compile(r"\b(" + "|".join(re.escape(t) for t in toks) + r")\b")
    low = text_series.fillna("").str.lower()
    return low.apply(lambda s: bool(pat.search(s)))


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
    ident = pd.read_sql("select channel_id, title, custom_url from marts.dim_channel", eng)
    df = df.merge(ident, on="channel_id", how="left")
    df["is_brand_channel"] = _flag_brand(df["title"].fillna("") + " " + df["custom_url"].fillna(""))

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


@lru_cache(maxsize=1)
def _common_words() -> frozenset[str]:
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "data" / "common_words.txt"
    if not path.exists():
        return frozenset()
    return frozenset(
        ln.strip().lower()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    )


def _validate_brief(brief: str) -> str | None:
    """Return a reason string if the brief isn't real language, else None.

    Catches keysmash / nonsense so the matcher doesn't return confident matches
    for garbage. Three cheap, deterministic signals (no model):
      - any single token >= 16 chars (no human writes a 20-char unbroken word)
      - any token >=6 alpha with vowel ratio < 0.20 (y counts) -> keysmash
      (absence of a wordlist hit is NOT a reject signal — only positive gibberish is)
    """
    import re

    raw = (brief or "").strip()
    if len(raw) < 3:
        return "too_short"
    raw_tokens = re.findall(r"[A-Za-z0-9]+", raw)
    tokens = [t.lower() for t in raw_tokens]
    if not tokens:
        return "no_words"
    # Exemptions first: a real word, a capitalized token (brand/proper noun),
    # or a known brand makes the brief valid regardless of the heuristics below.
    vocab = _common_words()
    brands = set(_brand_tokens()) if "_brand_tokens" in globals() else set()
    if any(t in vocab for t in tokens):
        return None
    if any(t[:1].isupper() for t in raw_tokens):
        return None
    if any(t in brands for t in tokens):
        return None
    # Otherwise apply gibberish heuristics.
    if max((len(t) for t in tokens), default=0) >= 16:
        return "gibberish_token"
    # Per-token vowel ratio (y counts): averaging over the whole brief lets one
    # consonant-heavy keysmash token hide behind another's vowels, so check each
    # substantial token independently.
    for t in tokens:
        t_alpha = [c for c in t if c.isalpha()]
        if len(t_alpha) >= 6:
            vowels = sum(c in "aeiouy" for c in t_alpha)
            if vowels / len(t_alpha) < 0.20:
                return "low_vowel_ratio"
    # No gibberish signal fired. A 173-word list can't represent real language,
    # so absence of a wordlist hit is NOT evidence of nonsense — let it through to
    # query-expansion (ADR-0026), which exists precisely for thin/polysemous briefs.
    return None


_BRIEF_REJECT_MSG = (
    "That doesn't read like a campaign brief. Describe your product, audience, "
    'or goal — e.g. "vegan skincare for Gen-Z" or "fintech app for students".'
)


def match(
    brief: str,
    budget_lakh: float = 15.0,
    top_k: int = 20,
    candidate_k: int = 200,
    rerank: bool = True,
    niche_filter: str | None = None,
    min_views: float = MIN_VIEWS_DEFAULT,
    expand: bool = True,
    funnel: dict | None = None,
) -> pd.DataFrame:
    eng = get_engine()
    reject = _validate_brief(brief)
    if reject is not None:
        if funnel is not None:
            funnel["rejected"] = reject
            funnel["explainer"] = _BRIEF_REJECT_MSG
        return pd.DataFrame(
            columns=[
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
                "title",
                "is_brand_channel",
            ]
        )
    creators, centroids = get_catalog()

    encoder = get_encoder()
    search_text = query_expand.expand_brief(brief) if expand else brief
    qvec = encoder.encode([search_text], normalize_embeddings=True)[0]
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
    if funnel is not None:
        funnel["search_text"] = search_text
        funnel["niche_filter"] = niche_filter
        funnel["min_views"] = float(min_views or 0.0)
        funnel["candidates_cosine"] = int(len(cand))
        funnel["top_cosine"] = float(cand["cosine"].max()) if len(cand) else 0.0
    if niche_filter:
        cand = cand[cand["niche"] == niche_filter]
    if funnel is not None:
        funnel["after_niche"] = int(len(cand))
    if min_views:
        # Reach floor: drop dormant / thin-reach channels so high-budget
        # briefs surface real audience reach. Skipped if it would empty
        # the pool (rare, e.g. a low-volume niche).
        floored = cand[cand["mean_views"].fillna(0.0) >= min_views]
        if not floored.empty:
            cand = floored

    if funnel is not None:
        funnel["after_floor"] = int(len(cand))
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
        - W_BRAND_PENALTY * cand["is_brand_channel"].astype(float)
    )
    if not rerank:
        # Variant A (A/B match_rerank_v2): pure Stage-1 cosine. Surface cosine as
        # the match score so the UI reflects the basis the ranking actually used.
        cand["final_score"] = cand["cosine"]
    rank_col = "final_score" if rerank else "cosine"
    out = cand.sort_values(rank_col, ascending=False).head(top_k)
    if funnel is not None:
        funnel["returned"] = int(len(out))
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
            "title",
            "is_brand_channel",
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
