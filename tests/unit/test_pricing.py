"""Unit tests for the reach-first integration-cost proxy (apps/ml/pricing.py).

Torch-free and DB-free. Tests the live reach-first model (cost = reach x niche
sponsored-CPM x format, floored by audience, capped) by its contract, plus the
unchanged AdSense CPM table and the retained legacy helper.
"""

from apps.ml.pricing import (
    CPM,
    CPM_DEFAULT,
    SPONSORED_CPM_BAND,
    integration_cost_point,
    integration_cost_range,
    sponsored_cost,
)

CAP = 5_000_000.0  # Rs50L ceiling


def test_cpm_tables_match_spec():
    assert CPM["Finance"] == 80
    assert CPM["Tech"] == 40
    assert CPM_DEFAULT == 25
    assert SPONSORED_CPM_BAND["Comedy"] == (300, 800)


def test_reach_drives_cost_not_subscribers():
    # Active small channel (high views) outprices a dead large one (low views).
    active = integration_cost_point(800_000, "Comedy", subscriber_count=500_000)
    dead = integration_cost_point(20_000, "Comedy", subscriber_count=5_000_000)
    assert active > dead


def test_cost_monotonic_in_reach():
    base = integration_cost_point(100_000, "Comedy", subscriber_count=1_000_000)
    more = integration_cost_point(1_000_000, "Comedy", subscriber_count=1_000_000)
    assert more > base


def test_premium_niche_costs_more_at_equal_reach():
    fin = integration_cost_point(500_000, "Finance")
    ent = integration_cost_point(500_000, "Entertainment")
    assert fin > ent


def test_capped_at_ceiling_for_mega_reach():
    lo, hi = integration_cost_range(50_000_000, "Finance", subscriber_count=20_000_000)
    assert hi <= CAP
    assert lo <= CAP


def test_subscriber_floor_sets_a_base_for_large_dormant_channel():
    # A 5M-sub channel with near-zero reach still gets its audience-size base.
    lo, hi = integration_cost_range(1_000, "Comedy", subscriber_count=5_000_000)
    assert lo >= 75_000.0
    assert hi >= 75_000.0


def test_shorts_format_discounts():
    long_form = integration_cost_point(
        1_000_000, "Comedy", subscriber_count=100_000, duration_seconds=600
    )
    shorts = integration_cost_point(
        1_000_000, "Comedy", subscriber_count=100_000, duration_seconds=30
    )
    assert shorts < long_form


def test_range_low_le_high_and_point_between():
    lo, hi = integration_cost_range(500_000, "Beauty", subscriber_count=300_000)
    point = integration_cost_point(500_000, "Beauty", subscriber_count=300_000)
    assert lo <= point <= hi


def test_nan_safe_and_returns_float():
    val = integration_cost_point(None, "Comedy", subscriber_count=None)
    assert isinstance(val, float)
    assert val >= 5_000.0  # floor min
    assert isinstance(integration_cost_point(float("nan"), None), float)


def test_unknown_niche_uses_default_band():
    known = integration_cost_point(500_000, "Devotional")  # not in band -> default
    assert known > 0


def test_legacy_sponsored_cost_returns_float():
    assert isinstance(sponsored_cost(100_000, "Beauty"), float)
