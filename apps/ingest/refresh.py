"""Recurring, tier-aware ingest runner -- the Airflow DAG entrypoint.

Distinct from the one-shot bootstrap (static_ingest): it reads the channel
universe from staging.channels (not the gitignored seed CSV), selects a tier
slice, and refreshes stats/metrics and/or recent videos. Records YouTube quota
units to the quota tracker. Runs inside the isolated /opt/ingest-venv in Airflow.

  python -m apps.ingest.refresh channels  --tier a
  python -m apps.ingest.refresh videos    --tier a --max-videos 10
  python -m apps.ingest.refresh discovery --max-new 50

Note: at the current 52-channel universe, tier A = all channels and tier B is
empty (the 500/4500 split is notional until the seed expands).
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import UTC, datetime
from typing import Any

import psycopg2
from dotenv import load_dotenv

from apps.ingest import normalizer, quota_tracker
from apps.ingest.youtube_client import YouTubeClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("refresh")

TIER_A_LIMIT = 500  # top-N by subs refreshed daily; at 52 channels this is "all"
TIER_B_ROTATION_DAYS = 7

_SELECT_TIER_SQL = """
    SELECT channel_id FROM (
        SELECT channel_id,
               row_number() OVER (ORDER BY subscriber_count DESC NULLS LAST) AS rn
        FROM staging.channels
    ) ranked
    WHERE (%(tier)s = 'a' AND rn <= %(limit)s)
       OR (%(tier)s = 'b' AND rn > %(limit)s
           AND ((rn - %(limit)s - 1) %% %(rot)s) = %(dow)s)
    ORDER BY rn
"""


def _connect() -> Any:
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _client() -> YouTubeClient:
    return YouTubeClient(os.environ["YOUTUBE_API_KEY"])


def _select_channel_ids(conn: Any, tier: str, dow: int | None) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            _SELECT_TIER_SQL,
            {
                "tier": tier,
                "limit": TIER_A_LIMIT,
                "rot": TIER_B_ROTATION_DAYS,
                "dow": dow if dow is not None else 0,
            },
        )
        return [r[0] for r in cur.fetchall()]


def cmd_channels(args: argparse.Namespace) -> None:
    load_dotenv()
    client = _client()
    conn = _connect()
    try:
        ids = _select_channel_ids(conn, args.tier, args.dow)
        logger.info("tier %s: %d channels (dow=%s)", args.tier, len(ids), args.dow)
        if not ids:
            return
        records = client.fetch_channels(ids)
        metric_date = datetime.now(UTC).date()
        raw_rows, staging_rows, metric_rows = normalizer.to_channel_rows(records, None, metric_date)
        with conn, conn.cursor() as cur:
            normalizer.load_channels(cur, raw_rows, staging_rows, metric_rows)
        logger.info("channels refreshed: %d (metrics %s)", len(records), metric_date)
    finally:
        conn.close()
        quota_tracker.record(client.units_used, source=f"channels_{args.tier}")


def cmd_videos(args: argparse.Namespace) -> None:
    load_dotenv()
    client = _client()
    conn = _connect()
    try:
        ids = _select_channel_ids(conn, args.tier, args.dow)
        logger.info("tier %s: %d channels for video fetch", args.tier, len(ids))
        if not ids:
            return
        records = client.fetch_channel_videos(ids, max_per_channel=args.max_videos)
        raw_rows, staging_rows = normalizer.to_video_rows(records)
        with conn, conn.cursor() as cur:
            normalizer.load_videos(cur, raw_rows, staging_rows)
        logger.info("videos ingested: %d", len(records))
    finally:
        conn.close()
        quota_tracker.record(client.units_used, source=f"videos_{args.tier}")


def cmd_discovery(args: argparse.Namespace) -> None:
    load_dotenv()
    client = _client()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT channel_id FROM staging.channels")
            existing = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT DISTINCT niche FROM staging.channels WHERE niche IS NOT NULL")
            niches = [r[0] for r in cur.fetchall()]
        logger.info("discovery: %d existing channels, %d niche queries", len(existing), len(niches))
        found: list[str] = []
        for niche in niches:
            if len(found) >= args.max_new:
                break
            for cid in client.search_channels(f"{niche} India", max_results=args.per_query):
                if cid not in existing and cid not in found:
                    found.append(cid)
        new_ids = found[: args.max_new]
        logger.info("discovery: %d new candidate channels", len(new_ids))
        if not new_ids:
            return
        records = client.fetch_channels(new_ids)
        metric_date = datetime.now(UTC).date()
        raw_rows, staging_rows, metric_rows = normalizer.to_channel_rows(records, None, metric_date)
        with conn, conn.cursor() as cur:
            normalizer.load_channels(cur, raw_rows, staging_rows, metric_rows)
        logger.info("discovery added: %d channels", len(records))
    finally:
        conn.close()
        quota_tracker.record(client.units_used, source="discovery")


_SELECT_UNBACKFILLED_SQL = """
    SELECT c.channel_id
    FROM staging.channels c
    LEFT JOIN (SELECT DISTINCT channel_id FROM staging.videos) v
      ON v.channel_id = c.channel_id
    WHERE v.channel_id IS NULL
      AND COALESCE(c.video_count, 1) > 0
    ORDER BY c.subscriber_count DESC NULLS LAST
    LIMIT %(limit)s
"""


def _select_unbackfilled_ids(conn: Any, limit: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(_SELECT_UNBACKFILLED_SQL, {"limit": limit})
        return [r[0] for r in cur.fetchall()]


def _chunks(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def cmd_backfill_videos(args: argparse.Namespace) -> None:
    """Resumable, quota-capped video backfill over channels lacking videos.

    Selects channels with no rows in staging.videos (skipping zero-upload
    channels), processes them biggest-first in batches, and stops gracefully
    once the day's remaining quota drops below --reserve. Re-running on a later
    quota-day resumes where it left off (the selection excludes done channels).
    """
    load_dotenv()
    client = _client()
    conn = _connect()
    processed = 0
    try:
        ids = _select_unbackfilled_ids(conn, args.limit)
        logger.info("backfill: %d channels missing videos", len(ids))
        if not ids:
            logger.info("backfill complete: every channel has videos")
            return
        base_remaining = quota_tracker.usage()["units_remaining"]
        logger.info("quota remaining today: %d (reserve %d)", base_remaining, args.reserve)
        for batch in _chunks(ids, args.batch):
            live_remaining = base_remaining - client.units_used
            if live_remaining < args.reserve:
                logger.info(
                    "near quota cap (~%d left); stopping at %d channels (resume next run)",
                    live_remaining,
                    processed,
                )
                break
            records = client.fetch_channel_videos(batch, max_per_channel=args.max_videos)
            raw_rows, staging_rows = normalizer.to_video_rows(records)
            with conn, conn.cursor() as cur:
                normalizer.load_videos(cur, raw_rows, staging_rows)
            processed += len(batch)
            logger.info(
                "backfilled %d/%d channels (%d videos this batch)",
                processed,
                len(ids),
                len(records),
            )
    finally:
        conn.close()
        quota_tracker.record(client.units_used, source="backfill_videos")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="refresh")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("channels", help="refresh channel stats + daily metrics snapshot")
    pc.add_argument("--tier", choices=["a", "b"], default="a")
    pc.add_argument("--dow", type=int, default=None, help="0-6, tier-b rotation slice")
    pc.set_defaults(func=cmd_channels)

    pv = sub.add_parser("videos", help="ingest recent videos for a tier's channels")
    pv.add_argument("--tier", choices=["a", "b"], default="a")
    pv.add_argument("--dow", type=int, default=None)
    pv.add_argument("--max-videos", type=int, default=10)
    pv.set_defaults(func=cmd_videos)

    pd = sub.add_parser("discovery", help="best-effort related-channel expansion (quota-heavy)")
    pd.add_argument("--max-new", type=int, default=50)
    pd.add_argument("--per-query", type=int, default=10)
    pd.set_defaults(func=cmd_discovery)

    pb = sub.add_parser("backfill-videos", help="resumable, quota-capped video backfill")
    pb.add_argument("--max-videos", type=int, default=10)
    pb.add_argument("--batch", type=int, default=50, help="channels per fetch+commit batch")
    pb.add_argument("--reserve", type=int, default=500, help="stop when remaining quota < this")
    pb.add_argument("--limit", type=int, default=20000, help="max channels to attempt this run")
    pb.set_defaults(func=cmd_backfill_videos)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
