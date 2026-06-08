"""Static ingest of seed channels: YouTube API -> raw + staging.

Reads data/seed_channels.csv (channel_id + niche), fetches static channel info
via the official YouTube Data API, lands the raw JSON in raw.youtube_channels,
and upserts normalized rows into staging.channels plus one daily snapshot row
into staging.channel_metrics_daily.

Run from the repo root:  python -m apps.ingest.static_ingest
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, execute_values

from apps.ingest.youtube_client import YouTubeClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("static_ingest")

SEED_CSV = Path("data/seed_channels.csv")


def load_seed() -> dict[str, str | None]:
    """Return {channel_id: niche} from the seed CSV."""
    niche_by_id: dict[str, str | None] = {}
    with SEED_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = (row.get("channel_id") or "").strip()
            if cid:
                niche_by_id[cid] = (row.get("niche") or "").strip() or None
    return niche_by_id


def main() -> None:
    load_dotenv()
    api_key = os.environ["YOUTUBE_API_KEY"]
    database_url = os.environ["DATABASE_URL"]

    niche_by_id = load_seed()
    channel_ids = list(niche_by_id)
    logger.info("seed channels: %d", len(channel_ids))

    client = YouTubeClient(api_key)
    records = client.fetch_channels(channel_ids)
    logger.info("API returned %d channels", len(records))

    metric_date = datetime.now(UTC).date()

    raw_rows = [(r.channel_id, Json(r.raw)) for r in records]
    channel_rows = [
        (
            r.channel_id,
            r.title,
            r.custom_url,
            r.description,
            r.country,
            r.default_language,
            niche_by_id.get(r.channel_id),
            r.published_at,
            r.subscriber_count,
            r.view_count,
            r.video_count,
            r.thumbnail_url,
        )
        for r in records
    ]
    metric_rows = [
        (r.channel_id, metric_date, r.subscriber_count, r.view_count, r.video_count)
        for r in records
    ]

    conn = psycopg2.connect(database_url)
    try:
        with conn, conn.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO raw.youtube_channels (channel_id, payload) VALUES %s",
                raw_rows,
            )
            execute_values(
                cur,
                """
                INSERT INTO staging.channels (
                    channel_id, title, custom_url, description, country,
                    default_language, niche, published_at, subscriber_count,
                    view_count, video_count, thumbnail_url
                ) VALUES %s
                ON CONFLICT (channel_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    custom_url = EXCLUDED.custom_url,
                    description = EXCLUDED.description,
                    country = EXCLUDED.country,
                    default_language = EXCLUDED.default_language,
                    niche = EXCLUDED.niche,
                    published_at = EXCLUDED.published_at,
                    subscriber_count = EXCLUDED.subscriber_count,
                    view_count = EXCLUDED.view_count,
                    video_count = EXCLUDED.video_count,
                    thumbnail_url = EXCLUDED.thumbnail_url,
                    updated_at = now()
                """,
                channel_rows,
            )
            execute_values(
                cur,
                """
                INSERT INTO staging.channel_metrics_daily (
                    channel_id, metric_date, subscriber_count, view_count, video_count
                ) VALUES %s
                ON CONFLICT (channel_id, metric_date) DO UPDATE SET
                    subscriber_count = EXCLUDED.subscriber_count,
                    view_count = EXCLUDED.view_count,
                    video_count = EXCLUDED.video_count,
                    captured_at = now()
                """,
                metric_rows,
            )
        logger.info(
            "ingest complete: raw=%d staging.channels=%d metrics(%s)=%d",
            len(raw_rows),
            len(channel_rows),
            metric_date,
            len(metric_rows),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
