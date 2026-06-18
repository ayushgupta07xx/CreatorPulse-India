"""Unit tests for the integration-cost proxy (apps/ml/pricing.py).

Torch-free and DB-free: pure arithmetic over the committed tier bands + CPM table,
so this runs fast in CI without Postgres or sentence-transformers. Tests the LIVE
subscriber-tier model (integration_cost_*) by its contract/invariants, the unchanged
AdSense CPM table, and the retained legacy sponsored_cost helper.
"""

import pytest

from apps.ml.pricing import (
    CPM,
    CPM_DEFAULT,
    SUBSCRIBER_TIER_BANDS,
    integration_cost_point,
    integration_cost_range,
    sponsored_cost,
    tier_band,
)

CEILING = 5_000_000.0  # Rs50L top-tier cap


# --- AdSense CPM table (single-source methodology artifact; guard against drift) ---
def test_cpm_table_constants_match_spec():
    assert CPM["Finance"] == 80
    assert CPM["Tech"] == 40
    assert CPM_DEFAULT == 25


# --- LIVE: subscriber-tier integration bands ---------------------------------------
@pytest.mark.parametrize(
    "subs, expected",
    [
        (10_000, (15_000.0, 75_000.0)),
        (100_000, (50_000.0, 250_000.0)),
        (500_000, (150_000.0, 600_000.0)),
        (3_000_000, (400_000.0, 1_800_000.0)),
        (10_000_000, (1_000_000.0, 3_500_000.0)),
        (20_000_000, (1_500_000.0, 5_000_000.0)),
    ],
)
def test_tier_band_thresholds(subs, expected):
    assert tier_band(subs) == expected


def test_every_band_low_below_high_and_under_ceiling():
    for _ceiling, (lo, hi) in SUBSCRIBER_TIER_BANDS:
        assert lo < hi
        assert hi <= CEILING


def test_bands_never_decrease_with_subscribers():
    subs = [10_000, 100_000, 500_000, 3_000_000, 10_000_000, 20_000_000]
    bands = [tier_band(s) for s in subs]
    for prev, cur in zip(bands, bands[1:], strict=False):
        assert cur[0] >= prev[0]
        assert cur[1] >= prev[1]


def test_point_stays_within_its_tier_band():
    for subs in (10_000, 250_001, 4_000_000, 20_000_000):
        lo, hi = tier_band(subs)
        for reach in (0, subs, subs * 100):
            point = integration_cost_point(reach, subs)
            assert lo <= point <= hi


def test_point_clamps_to_ceiling_for_mega_channel():
    # Huge reach + huge subs can never exceed the Rs50L top-tier cap.
    assert integration_cost_point(2_000_000_000, 80_000_000) <= CEILING


def test_cost_monotonic_in_subscribers_at_equal_reach_ratio():
    # Same reach-per-subscriber, larger audience -> strictly more expensive.
    small = integration_cost_point(50_000, 100_000)
    big = integration_cost_point(10_000_000, 20_000_000)
    assert big > small


def test_range_brackets_the_point_and_stays_in_band():
    for subs in (80_000, 900_000, 12_000_000):
        lo, hi = tier_band(subs)
        for reach in (subs * 0.1, subs, subs * 50):
            point = integration_cost_point(reach, subs)
            low, high = integration_cost_range(reach, subs)
            assert lo <= low <= point <= high <= hi


def test_point_is_nan_safe_and_returns_float():
    # None/NaN inputs fall back to the first tier rather than crashing.
    val = integration_cost_point(None, None)
    assert isinstance(val, float)
    assert 15_000.0 <= val <= 75_000.0
    assert isinstance(integration_cost_point(float("nan"), float("nan")), float)


# --- LEGACY: niche CPM-band midpoint (retained, not the live brand number) ---------
def test_legacy_sponsored_cost_returns_float():
    assert isinstance(sponsored_cost(50_000, "Beauty"), float)


def test_legacy_higher_band_niche_costs_more_at_equal_reach():
    finance = sponsored_cost(1_000_000, "Finance")
    entertainment = sponsored_cost(1_000_000, "Entertainment")
    assert finance > entertainment
