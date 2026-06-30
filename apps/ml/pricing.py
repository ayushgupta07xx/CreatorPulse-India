"""Sponsored-integration cost estimate.

Single source of truth for the brand/creator integration-rate estimate, shared by
the match engine (apps/ml/match.py) and the API. Torch-free.

LIVE MODEL -- reach-first. Sponsorship is priced on what a brand actually buys:
reach (recent typical views), not subscriber vanity. cost = median views x niche
sponsored-CPM / 1000 x format multiplier, floored by audience size (a large channel
commands some base even when dormant) and capped (mega-channels negotiate flat, not
per-view). Calibrated to published 2026 rate cards -- an integration reduces to
"recent average views x niche CPM x format multiplier"; Shorts pay ~40-60% of
long-form (0.5x midpoint). See 05_CreatorPulse.md s14, docs/decisions.md ADR-0022.

The AdSense CPM table (CPM) and the OLS earnings regressor are unchanged methodology
artifacts, not this number.
"""

from __future__ import annotations

import pandas as pd

# Niche AdSense CPM (INR per 1000 views) -- earnings methodology artifact. s14.
CPM = {
    "Finance": 80,
    "Tech": 40,
    "Education": 35,
    "News": 35,
    "Beauty": 25,
    "Fashion": 25,
    "Gaming": 20,
    "Comedy": 15,
    "Entertainment": 15,
    "Reactions": 15,
}
CPM_DEFAULT = 25

# --- LIVE: reach-first sponsored-integration pricing -----------------------------
# Sponsored-integration CPM band (INR per 1000 views), (low, high) per niche, from
# published Indian rate cards (~INR 300-3,000 / 1k; finance premium, entertainment floor).
SPONSORED_CPM_BAND = {
    "Finance": (1000, 3000),
    "Tech": (800, 2200),
    "Education": (500, 1400),
    "News": (450, 1200),
    "Beauty": (400, 1100),
    "Fashion": (400, 1100),
    "Gaming": (350, 1000),
    "Comedy": (300, 800),
    "Entertainment": (300, 800),
    "Reactions": (300, 800),
}
SPONSORED_CPM_BAND_DEFAULT = (400, 1000)

_CAP = 5_000_000.0  # Rs50L ceiling on one integration
_FLOOR_MIN = 5_000.0  # nobody is free
_MIN_VIDEOS_FOR_PRICING = 10  # <10 uploads -> no stable per-video reach; do not price
_SHORTS_FORMAT = 0.5  # Shorts pay ~40-60% of long-form; midpoint per 2026 IN rate cards
_SHORTS_MAX_SECONDS = 70.0
# Modest base floor by audience size: a large channel commands *some* base even when
# recent reach is low ("1M+ subs is a big deal"), but reach drives everything above it.
_SUB_FLOOR = [
    (15_000_000.0, 150_000.0),
    (5_000_000.0, 75_000.0),
    (1_000_000.0, 30_000.0),
]


def _sub_floor(subscriber_count) -> float:
    subs = 0.0 if subscriber_count is None or pd.isna(subscriber_count) else float(subscriber_count)
    for threshold, amount in _SUB_FLOOR:
        if subs >= threshold:
            return amount
    return 0.0


def _format_multiplier(duration_seconds) -> float:
    if duration_seconds is None or pd.isna(duration_seconds):
        return 1.0
    return _SHORTS_FORMAT if float(duration_seconds) < _SHORTS_MAX_SECONDS else 1.0


def integration_cost_range(
    reach, niche, subscriber_count=None, duration_seconds=None
) -> tuple[float, float]:
    """(low, high) INR for one sponsored integration.

    reach x niche sponsored-CPM / 1000 x format, floored by audience size, capped.
    """
    r = 0.0 if reach is None or pd.isna(reach) else float(reach)
    lo_cpm, hi_cpm = SPONSORED_CPM_BAND.get(niche, SPONSORED_CPM_BAND_DEFAULT)
    fmt = _format_multiplier(duration_seconds)
    floor = max(_sub_floor(subscriber_count), _FLOOR_MIN)
    lo = min(max(r * lo_cpm / 1000.0 * fmt, floor), _CAP)
    hi = min(max(r * hi_cpm / 1000.0 * fmt, floor), _CAP)
    return lo, hi


def integration_cost_point(reach, niche, subscriber_count=None, duration_seconds=None) -> float:
    """Midpoint INR estimate for one sponsored integration."""
    lo, hi = integration_cost_range(reach, niche, subscriber_count, duration_seconds)
    return (lo + hi) / 2.0


# --- LEGACY: raw reach x CPM (no floor/cap), retained for back-compat ------------
def integration_rate_range(reach, niche) -> tuple[float, float]:
    """LEGACY: uncapped (low, high) from the niche sponsored-CPM band."""
    v = 0.0 if reach is None or pd.isna(reach) else float(reach)
    lo_cpm, hi_cpm = SPONSORED_CPM_BAND.get(niche, SPONSORED_CPM_BAND_DEFAULT)
    return max(1.0, v * lo_cpm / 1000.0), max(1.0, v * hi_cpm / 1000.0)


def sponsored_cost(reach, niche) -> float:
    """LEGACY: midpoint of the uncapped niche-CPM-band range (INR)."""
    lo, hi = integration_rate_range(reach, niche)
    return (lo + hi) / 2.0
