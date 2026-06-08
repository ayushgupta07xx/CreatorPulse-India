"""Build the seed channel list for CreatorPulse India.

Reads curated handles from data/seed_handles.csv, resolves each to a channel_id
with statistics via the official YouTube Data API v3 (channels.list), applies
Indian-creator filters, and writes data/seed_channels.csv.

- Source lib: `requests` against the documented REST endpoint (1 quota unit per
  channels.list call). pyyoutube is used for the richer ingest client on Day 2.
- Resumable: re-runs skip handles already present in seed_channels.csv.
- Safe: handles that do not resolve are logged and dropped, never fabricated.

Run (venv active, YOUTUBE_API_KEY in .env):
    python scripts/build_seed_list.py --min-subs 10000
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

API = "https://www.googleapis.com/youtube/v3/channels"
PART = "snippet,statistics,contentDetails"
ROOT = Path(__file__).resolve().parents[1]
HANDLES_CSV = ROOT / "data" / "seed_handles.csv"
OUT_CSV = ROOT / "data" / "seed_channels.csv"
FIELDS = [
    "channel_id",
    "handle",
    "title",
    "niche",
    "country",
    "default_language",
    "subscriber_count",
    "view_count",
    "video_count",
    "uploads_playlist_id",
    "fetched_at",
    "source",
]


class Quota:
    def __init__(self) -> None:
        self.units = 0

    def charge(self, n: int) -> None:
        self.units += n

    def report(self) -> str:
        return f"{self.units} units (~{self.units / 10000:.1%} of 10,000/day free quota)"


def load_handles() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with HANDLES_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            handle = row["handle"].strip().lstrip("@")
            if handle:
                rows.append((handle, row["niche"].strip()))
    return rows


def load_existing() -> tuple[list[dict], set[str]]:
    if not OUT_CSV.exists():
        return [], set()
    with OUT_CSV.open(newline="", encoding="utf-8") as fh:
        existing = list(csv.DictReader(fh))
    done = {r["handle"].lower() for r in existing}
    return existing, done


def resolve(handle: str, key: str, quota: Quota, session: requests.Session) -> dict | None:
    params = {"part": PART, "forHandle": f"@{handle}", "key": key}
    resp = session.get(API, params=params, timeout=20)
    quota.charge(1)
    if resp.status_code == 403:
        print(f"  ! 403 from API on @{handle}: {resp.json().get('error', {}).get('message', '')}")
        # quota/key error is fatal: stop so we don't burn the whole quota on errors
        if "quota" in resp.text.lower() or "disabled" in resp.text.lower():
            raise SystemExit("API key/quota error — fix .env YOUTUBE_API_KEY and retry.")
        return None
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    return items[0]


def to_row(item: dict, handle: str, niche: str) -> dict:
    snip = item.get("snippet", {})
    stats = item.get("statistics", {})
    uploads = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
    return {
        "channel_id": item.get("id", ""),
        "handle": handle,
        "title": snip.get("title", ""),
        "niche": niche,
        "country": snip.get("country", ""),
        "default_language": snip.get("defaultLanguage", ""),
        "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
        "view_count": int(stats.get("viewCount", 0) or 0),
        "video_count": int(stats.get("videoCount", 0) or 0),
        "uploads_playlist_id": uploads,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "seed",
    }


def keep(row: dict, min_subs: int) -> bool:
    # Curated list is Indian; keep if country is IN or unset, and subs meet the floor.
    country_ok = row["country"] in ("IN", "")
    return country_ok and row["subscriber_count"] >= min_subs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-subs", type=int, default=10000)
    parser.add_argument("--limit", type=int, default=0, help="cap handles processed (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="resolve but do not write")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        print("ERROR: YOUTUBE_API_KEY not set. Copy .env.example to .env and add the key.")
        return 1

    handles = load_handles()
    existing, done = load_existing()
    pending = [(h, n) for h, n in handles if h.lower() not in done]
    if args.limit:
        pending = pending[: args.limit]
    print(
        f"{len(handles)} handles in seed file; {len(done)} already resolved; "
        f"processing {len(pending)} now."
    )

    quota = Quota()
    kept: list[dict] = []
    dropped: list[str] = []
    with requests.Session() as session:
        for i, (handle, niche) in enumerate(pending, 1):
            item = resolve(handle, key, quota, session)
            if item is None:
                dropped.append(f"@{handle} (unresolved)")
                print(f"  [{i}/{len(pending)}] @{handle:<28} DROP unresolved")
                continue
            row = to_row(item, handle, niche)
            if keep(row, args.min_subs):
                kept.append(row)
                print(
                    f"  [{i}/{len(pending)}] @{handle:<28} OK  "
                    f"{row['subscriber_count']:>10,} subs  {row['niche']}"
                )
            else:
                dropped.append(
                    f"@{handle} (filtered: country={row['country'] or 'NA'}, "
                    f"subs={row['subscriber_count']})"
                )
                print(f"  [{i}/{len(pending)}] @{handle:<28} DROP filtered")
            time.sleep(0.05)

    all_rows = existing + kept
    print(
        f"\nResolved+kept this run: {len(kept)} | dropped: {len(dropped)} | "
        f"total in file: {len(all_rows)}"
    )
    print(f"Quota used: {quota.report()}")

    if args.dry_run:
        print("Dry run — not writing.")
        return 0

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Wrote {OUT_CSV.relative_to(ROOT)} ({len(all_rows)} channels).")
    if dropped:
        print("Dropped:")
        for d in dropped:
            print(f"  - {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
