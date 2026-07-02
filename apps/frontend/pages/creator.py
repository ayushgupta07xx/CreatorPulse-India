"""Creator-persona page: profile, growth, engagement, niche demand, peers, tips."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_FRONTEND = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_REPO_ROOT), str(_FRONTEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from components import analytics, data  # noqa: E402
from components.about import render_about_sidebar  # noqa: E402

from apps.ml.pricing import sponsored_cost  # noqa: E402

st.set_page_config(page_title="CreatorPulse — Creator", page_icon="📈", layout="wide")
from components.ui import apply_theme, plotly_theme  # noqa: E402

apply_theme()


@st.cache_data(show_spinner=False, ttl=3600)
def _fetch_avatar(url: str) -> bytes | None:
    """Proxy the channel avatar server-side; yt3 hotlinks fail in the browser but a
    server GET usually succeeds. Returns None on failure (caller shows a letter)."""
    try:
        import requests

        r = requests.get(url, timeout=4)
        if r.ok and r.headers.get("content-type", "").startswith("image"):
            return r.content
    except Exception:  # noqa: BLE001
        return None
    return None


st.title("📈 Creator Intelligence")
analytics.capture_once("persona_creator", "persona_selected", {"persona": "creator"})

creators = data.load_creators_df()
if creators.empty:
    st.error("No creators loaded — check the warehouse is up and DATABASE_URL is set.")
    st.stop()

titles = creators[["channel_id", "title"]].dropna(subset=["title"]).sort_values("title")
choice = st.selectbox(
    "Search a creator",
    titles["title"],
    index=None,
    placeholder="Start typing a channel name…",
)
if not choice:
    st.info("Pick a channel to see its CreatorPulse profile.")
    st.stop()

row = creators[creators["title"] == choice].iloc[0]
peers_all = creators[creators["cluster_id"] == row["cluster_id"]]
nb = data.load_niche_forecast()
fc = nb["forecasts"].get(row["niche"])
_cid = row["channel_id"]
if st.session_state.get("_ph_last_creator") != _cid:
    st.session_state["_ph_last_creator"] = _cid
    analytics.capture("creator_searched", {"query": choice, "results_count": 1})
    analytics.capture("creator_profile_viewed", {"channel_id": _cid, "niche": row["niche"]})
    analytics.capture("niche_demand_chart_viewed", {"niche": row["niche"]})
    analytics.capture("peer_benchmark_opened", {"channel_id": _cid})

# ---- header ----
h1, h2 = st.columns([1, 4])
with h1:
    thumb = row.get("thumbnail_url")
    avatar = _fetch_avatar(thumb) if isinstance(thumb, str) and thumb else None
    if avatar:
        st.image(avatar, width=120)
    else:
        st.markdown(f"## {choice[:1].upper()}")
with h2:
    st.subheader(choice)
    st.markdown(f"Niche **{row['niche']}** · Archetype `{row['archetype']}`")
    a, b, c, d = st.columns(4)
    a.metric("Subscribers", f"{int(row['subscriber_count']):,}")
    b.metric("Total views", f"{int(row['view_count']):,}")
    c.metric("Videos", f"{int(row['video_count']):,}")
    mv = row.get("mean_views")
    d.metric("Avg views/video", f"{int(mv):,}" if pd.notna(mv) else "—")

st.divider()

# ---- estimated value ----
_rate = sponsored_cost(row.get("mean_views"), row["niche"])
st.markdown("### Estimated value")
st.metric("Est. sponsored-video rate", f"₹{int(_rate):,}")
st.caption(
    "Reach-based proxy (typical views × sponsored CPM) — what a brand could pay "
    "for one integration, not your AdSense income. Scales with average views."
)

# ---- growth ----
st.markdown("### Growth")
today = pd.Timestamp.today().normalize()
fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=[today],
        y=[row["subscriber_count"]],
        mode="markers",
        name="current (measured)",
        marker={"size": 13, "color": "#54E0CE"},
    )
)
if fc is not None:
    f = fc.sort_values("ds")
    future = f.tail(nb["horizon"])
    base = float(future["yhat"].iloc[0]) or 1.0
    mult = future["yhat"].to_numpy(dtype=float) / base
    proj_dates = pd.date_range(today, periods=len(future), freq="W")
    fig.add_trace(
        go.Scatter(
            x=proj_dates,
            y=row["subscriber_count"] * mult,
            mode="lines",
            name="niche-trend projection",
            line={"dash": "dot", "color": "#9C8BFF"},
        )
    )
fig.update_layout(height=320, yaxis_title="subscribers", margin={"t": 10, "b": 10})
st.plotly_chart(plotly_theme(fig), width="stretch")
st.caption(
    "Solid point = current measured subscribers. Dotted line = a 12-week projection "
    "scaled from the (simulated) niche-demand trend — not measured channel history. "
    "Per-channel longitudinal tracking accrues from the first daily snapshot onward."
)

# ---- engagement quality ----
st.markdown("### Engagement quality")
er = float(row["mean_engagement_rate"]) if pd.notna(row["mean_engagement_rate"]) else np.nan
peer_er = pd.to_numeric(peers_all["mean_engagement_rate"], errors="coerce").dropna()
pct = float((peer_er < er).mean() * 100) if (pd.notna(er) and len(peer_er) > 1) else np.nan
e1, e2 = st.columns(2)
e1.metric("Mean engagement rate", f"{er:.4f}" if pd.notna(er) else "—")
e2.metric(
    f"Percentile in archetype (n={len(peer_er)})",
    f"{pct:.0f}th" if pd.notna(pct) else "—",
)
st.caption(
    "Engagement rate = (likes + comments) / views, averaged over observed videos. "
    "Percentile is within this creator's archetype cluster — a thin cohort, so read it "
    "as directional."
)

# ---- niche demand ----
st.markdown("### Niche demand")
if fc is not None:
    f = fc.sort_values("ds")
    split = len(f) - nb["horizon"]
    nfig = go.Figure()
    nfig.add_trace(
        go.Scatter(x=f["ds"], y=f["hi80"], mode="lines", line={"width": 0}, showlegend=False)
    )
    nfig.add_trace(
        go.Scatter(
            x=f["ds"],
            y=f["lo80"],
            mode="lines",
            fill="tonexty",
            line={"width": 0},
            name="80% interval",
            fillcolor="rgba(84,224,206,0.15)",
        )
    )
    nfig.add_trace(
        go.Scatter(
            x=f["ds"],
            y=f["yhat"],
            mode="lines",
            name="weekly views",
            line={"color": "#54E0CE"},
        )
    )
    if 0 < split < len(f):
        nfig.add_vline(x=f["ds"].iloc[split], line_dash="dash", line_color="#8A8AA0")
    nfig.update_layout(height=300, yaxis_title="weekly views", margin={"t": 10, "b": 10})
    st.plotly_chart(plotly_theme(nfig), width="stretch")
    slope = nb["slopes"].get(row["niche"]) or 0.0
    direction = "accelerating" if slope > 0 else "declining"
    st.caption(
        f"Niche **{row['niche']}** is {direction} "
        "(size-weighted absolute trend slope). "
        "The series is a simulated weekly history (no real demand history yet); "
        "the forecast is the 12 weeks right of the dashed line, with the 80% "
        "interval shaded."
    )
else:
    st.info(f"No niche forecast available for '{row['niche']}'.")

# ---- peer benchmark ----
st.markdown("### Peer benchmark — closest in archetype by subscribers")
peers = peers_all[peers_all["channel_id"] != row["channel_id"]].copy()
peers["sub_gap"] = (peers["subscriber_count"] - row["subscriber_count"]).abs()
peer_cols = {
    "title": "Creator",
    "niche": "Niche",
    "subscriber_count": "Subscribers",
    "view_count": "Total views",
    "mean_engagement_rate": "Engagement rate",
}
peer_tbl = peers.nsmallest(10, "sub_gap")[list(peer_cols)].rename(columns=peer_cols)
st.dataframe(peer_tbl, width="stretch", hide_index=True)

# ---- optimization suggestions (rule-based) ----
st.markdown("### Optimization suggestions")
tips = []
cad = row["mean_inter_video_days"]
cad_med = pd.to_numeric(peers_all["mean_inter_video_days"], errors="coerce").median()
if pd.notna(cad) and pd.notna(cad_med) and cad > cad_med:
    tips.append(
        f"Upload gap (~{cad:.0f} days) is wider than the archetype median "
        f"(~{cad_med:.0f} days) — tightening cadence tends to lift reach."
    )
er_med = peer_er.median()
if pd.notna(er) and pd.notna(er_med) and er < er_med:
    tips.append(
        "Engagement rate is below the archetype median — stronger hooks, CTAs, and "
        "community posts can help."
    )
dslu = row["days_since_last_upload"]
if pd.notna(dslu) and dslu > 30:
    tips.append(f"Last upload was ~{int(dslu)} days ago — consistency keeps the algorithm warm.")
if not tips:
    tips.append("Cadence and engagement are at or above the archetype median — keep it up.")
for tip in tips:
    st.markdown(f"- {tip}")

# ---- what's working in your niche ----
st.markdown("### What's working in your archetype")
ids = tuple(peers_all["channel_id"].tolist())
window, vids = 30, data.top_videos_in_cluster(ids, 30)
if vids.empty:
    window, vids = 90, data.top_videos_in_cluster(ids, 90)
if vids.empty:
    window, vids = 36500, data.top_videos_in_cluster(ids, 36500)
label = {30: "last 30 days", 90: "last 90 days"}.get(window, "all time")
st.caption(f"Most-viewed videos across this archetype ({label}).")
if not vids.empty:
    vcols = {
        "title": "Video",
        "view_count": "Views",
        "engagement_rate": "Engagement rate",
        "published_at": "Published",
    }
    st.dataframe(
        vids[list(vcols)].rename(columns=vcols),
        width="stretch",
        hide_index=True,
    )
else:
    st.info("No videos found for this archetype.")

render_about_sidebar()
