"""Build data/seed_channels.csv from the open 1M-channel dataset.

Filters the ODC-By Kaggle dataset (asaniczka/2024-youtube-channels-1-million,
credited in LEGAL.md) to India, takes the top-N by 2024 subscriber_count as a
seed (IDs only -- every stat the product shows is re-fetched live by
static_ingest), classifies each into the 20-niche taxonomy via BGE-small
embeddings, unions the hand-curated bootstrap niches, and writes channel_id,niche.

    python -m apps.ingest.seed_from_dataset --top 13000

Channel embeddings are cached (data/raw_seed/.seed_emb_cache.npz) so re-running
after tuning the niche exemplars re-classifies instantly without re-embedding.
The 2024 vintage only decides which channels seed the directory; channel_ids are
permanent and all metrics are fetched live via the YouTube API.
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed")

RAW_DIR = Path("data/raw_seed")
SEED_CSV = Path("data/seed_channels.csv")
TAXONOMY_CSV = Path("data/niche_taxonomy.csv")
EMB_CACHE = RAW_DIR / ".seed_emb_cache.npz"
MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Canonical 20-niche taxonomy (matches the names in data/niche_taxonomy.csv and
# the curated bootstrap) with descriptive exemplars -- bare labels embed poorly,
# phrases sharpen the nearest-niche match.
NICHE_EXEMPLARS = {
    "Tech": "technology gadgets smartphone laptop electronics reviews unboxing",
    "Gaming": "video game gameplay walkthrough esports live gaming stream",
    "Beauty": "beauty makeup tutorial skincare cosmetics grooming",
    "Food": "cooking recipe food kitchen culinary street food eating",
    "Fitness": "fitness workout gym bodybuilding yoga weight loss health",
    "Comedy": "comedy sketch standup humor funny prank parody",
    "Education": "education tutorial learning exam preparation lecture study",
    "Lifestyle": "lifestyle daily life wellness home decor personal",
    "Music": "music song singing cover musician band album playback",
    "Devotional": "devotional bhajan spiritual religious mantra prayer aarti",
    "News": "news current affairs politics journalism breaking report",
    "Vlogs": "vlog daily vlog personal vlogging lifestyle diary",
    "Auto": "cars automobile bike motorcycle vehicle auto review",
    "DIY": "diy craft handmade how to project tutorial homemade",
    "Travel": "travel tourism destination adventure trip places explore",
    "Sports": "sports cricket football kabaddi athletics match highlights",
    "Finance": "finance stock market investing money business economy trading",
    "Parenting": "parenting kids baby motherhood family children toddler",
    "Fashion": "fashion style clothing outfit apparel designer trend",
    "Reactions": "reaction reacting commentary watch along review response",
}


def find_raw() -> Path:
    direct = RAW_DIR / "youtube_channels_1M_clean.csv"
    if direct.exists():
        return direct
    hits = sorted(RAW_DIR.glob("*.csv"))
    if not hits:
        raise SystemExit(f"no CSV in {RAW_DIR} -- download the dataset first")
    return hits[0]


def load_taxonomy() -> dict[str, str]:
    """Return the canonical 20-niche exemplars. data/niche_taxonomy.csv is the
    spec's source of truth for the names; we sanity-check against it (any column)
    but classify with the hardcoded phrases, since the CSV carries no exemplars."""
    if TAXONOMY_CSV.exists():
        try:
            df = pd.read_csv(TAXONOMY_CSV)
            csv_vals = {str(v).strip() for c in df.columns for v in df[c].dropna()}
            missing = [n for n in NICHE_EXEMPLARS if n not in csv_vals]
            if missing:
                logger.warning("niches not found verbatim in %s: %s", TAXONOMY_CSV, missing)
        except (OSError, pd.errors.ParserError) as exc:
            logger.warning("could not read %s (%s)", TAXONOMY_CSV, exc)
    logger.info("taxonomy: %d canonical niches", len(NICHE_EXEMPLARS))
    return NICHE_EXEMPLARS


def embed_channels(ids: list[str], texts: list[str], model: SentenceTransformer) -> np.ndarray:
    if EMB_CACHE.exists():
        try:
            cached = np.load(EMB_CACHE)
            if cached["ids"].tolist() == ids:
                logger.info("using cached channel embeddings (%d)", len(ids))
                return cached["vecs"]
            logger.info("cache present but channel set changed; re-embedding")
        except (OSError, KeyError, ValueError):
            pass
    logger.info("embedding %d channels (cache miss; this is the slow step) ...", len(ids))
    vecs = np.asarray(
        model.encode(texts, normalize_embeddings=True, batch_size=128, show_progress_bar=True)
    )
    np.savez(EMB_CACHE, ids=np.array(ids), vecs=vecs)
    return vecs


def assign_niches(
    ch_vecs: np.ndarray, niches: dict[str, str], model: SentenceTransformer
) -> list[str]:
    labels = list(niches)
    niche_vecs = np.asarray(
        model.encode(
            [niches[n] for n in labels], normalize_embeddings=True, show_progress_bar=False
        )
    )
    sims = ch_vecs @ niche_vecs.T
    return [labels[i] for i in sims.argmax(axis=1)]


def load_curated() -> dict[str, str]:
    """Preserve the hand-curated bootstrap niches (their labels win on union)."""
    if not SEED_CSV.exists():
        return {}
    out: dict[str, str] = {}
    with SEED_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("channel_id") or "").strip()
            niche = (row.get("niche") or "").strip()
            if cid and niche:
                out[cid] = niche
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="seed_from_dataset")
    ap.add_argument("--top", type=int, default=13000, help="top-N India channels by subs")
    args = ap.parse_args()

    raw = find_raw()
    curated = load_curated()
    # only the genuine hand-curated bootstrap (52); ignore a prior bad run that
    # may have written numeric niches over the seed.
    curated = {cid: n for cid, n in curated.items() if n in NICHE_EXEMPLARS}
    if curated:
        backup = SEED_CSV.with_name("seed_channels.bootstrap.csv")
        if not backup.exists():
            backup.write_bytes(SEED_CSV.read_bytes())
            logger.info("backed up curated rows -> %s", backup)

    logger.info("reading %s ...", raw)
    df = pd.read_csv(
        raw,
        usecols=[
            "channel_id",
            "channel_name",
            "subscriber_count",
            "description",
            "keywords",
            "country",
        ],
    )
    df = df[df["country"] == "India"].copy()
    df["subscriber_count"] = pd.to_numeric(df["subscriber_count"], errors="coerce").fillna(0)
    df = df.drop_duplicates(subset="channel_id")
    df = df.sort_values("subscriber_count", ascending=False).head(args.top)
    logger.info("India channels selected: %d (top by 2024 subs)", len(df))

    text = (
        (
            df["channel_name"].fillna("").astype(str)
            + ". "
            + df["description"].fillna("").astype(str)
            + " "
            + df["keywords"].fillna("").astype(str)
        )
        .str.slice(0, 600)
        .tolist()
    )
    ids = df["channel_id"].astype(str).tolist()

    logger.info("loading %s ...", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)
    ch_vecs = embed_channels(ids, text, model)
    niches = load_taxonomy()
    assigned = assign_niches(ch_vecs, niches, model)

    seed = dict(zip(ids, assigned, strict=True))
    seed.update(curated)  # curated bootstrap niches win
    logger.info("writing %d channels (incl. %d curated) -> %s", len(seed), len(curated), SEED_CSV)

    with SEED_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["channel_id", "niche"])
        for cid, niche in seed.items():
            w.writerow([cid, niche])

    dist = pd.Series(list(seed.values())).value_counts()
    logger.info("niche distribution:\n%s", dist.to_string())


if __name__ == "__main__":
    main()
