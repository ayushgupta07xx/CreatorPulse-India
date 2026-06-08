"""Thin wrapper around the python-youtube (pyyoutube) Client.

Fetches static channel info, batching channels.list at 50 ids/call
(1 quota unit per call) with retry + exponential backoff on transient errors.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from pyyoutube import Client

try:
    from pyyoutube import PyYouTubeException
except ImportError:  # pragma: no cover
    from pyyoutube.error import PyYouTubeException

logger = logging.getLogger(__name__)

CHANNELS_BATCH = 50  # channels.list accepts up to 50 ids per call
CHANNEL_PARTS = ["snippet", "statistics"]


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ChannelRecord:
    channel_id: str
    title: str | None
    custom_url: str | None
    description: str | None
    country: str | None
    default_language: str | None
    published_at: str | None
    subscriber_count: int | None
    view_count: int | None
    video_count: int | None
    thumbnail_url: str | None
    raw: dict


class YouTubeClient:
    def __init__(self, api_key: str, *, max_retries: int = 4, backoff_base: float = 1.5) -> None:
        self._client = Client(api_key=api_key)
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    def _channels_list(self, ids: list[str]):
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.channels.list(channel_id=ids, parts=CHANNEL_PARTS)
            except PyYouTubeException as exc:
                last_exc = exc
                sleep_s = self._backoff_base**attempt
                logger.warning(
                    "channels.list failed (attempt %d/%d): %s; backing off %.1fs",
                    attempt + 1,
                    self._max_retries,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _thumbnail_url(snippet: Any) -> str | None:
        thumbs = getattr(snippet, "thumbnails", None)
        for size in ("high", "medium", "default"):
            t = getattr(thumbs, size, None) if thumbs else None
            if t and getattr(t, "url", None):
                return t.url
        return None

    @staticmethod
    def _raw_payload(item: Any) -> dict:
        try:
            return item.to_dict()
        except Exception:  # noqa: BLE001 - fall back to a minimal dict
            return {"id": getattr(item, "id", None)}

    def fetch_channels(self, channel_ids: list[str]) -> list[ChannelRecord]:
        """Fetch static channel info for any number of ids, batching at 50/call."""
        records: list[ChannelRecord] = []
        for start in range(0, len(channel_ids), CHANNELS_BATCH):
            batch = channel_ids[start : start + CHANNELS_BATCH]
            resp = self._channels_list(batch)
            for item in resp.items or []:
                snip = item.snippet
                stats = item.statistics
                records.append(
                    ChannelRecord(
                        channel_id=item.id,
                        title=getattr(snip, "title", None),
                        custom_url=getattr(snip, "customUrl", None),
                        description=getattr(snip, "description", None),
                        country=getattr(snip, "country", None),
                        default_language=getattr(snip, "defaultLanguage", None),
                        published_at=getattr(snip, "publishedAt", None),
                        subscriber_count=_to_int(getattr(stats, "subscriberCount", None)),
                        view_count=_to_int(getattr(stats, "viewCount", None)),
                        video_count=_to_int(getattr(stats, "videoCount", None)),
                        thumbnail_url=self._thumbnail_url(snip),
                        raw=self._raw_payload(item),
                    )
                )
        return records
