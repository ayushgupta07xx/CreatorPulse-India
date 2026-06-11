"""Reach-based sponsored-video cost proxy.

Single source of truth for the campaign-cost / creator-rate estimate, shared by
the match engine (apps/ml/match.py) and the Streamlit frontend. Torch-free, so the
creator page can import it without pulling sentence-transformers.

A brand budgets for what an integration costs, which scales with a creator's typical
reach (mean_views). Per-channel monthly AdSense is not recoverable from a single
metrics snapshot, so this reach-based proxy is the live number; the OLS AdSense
regressor stays a methodology artifact.
"""

from __future__ import annotations

import pandas as pd

# Niche sponsorship CPM (INR per 1000 views), 05_CreatorPulse.md §14.
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
# Sponsored integrations command far higher CPMs than programmatic AdSense; this
# lifts the niche AdSense CPMs to a sponsored-rate scale (mean_views * CPM * factor
# / 1000 ~= a creator's per-video integration rate).
SPONSORED_CPM_FACTOR = 20


def sponsored_cost(mean_views, niche) -> float:
    """Estimated sponsored-video cost/rate for one creator (INR)."""
    v = 0.0 if mean_views is None or pd.isna(mean_views) else float(mean_views)
    cpm = CPM.get(niche, CPM_DEFAULT)
    return v * cpm * SPONSORED_CPM_FACTOR / 1000.0
