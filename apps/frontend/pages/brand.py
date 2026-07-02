"""CreatorPulse India — Brand persona: brief to ranked, fraud-screened shortlist."""

import json
import sys
import uuid
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(FRONTEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from components import analytics, data  # noqa: E402
from components.about import render_about_sidebar  # noqa: E402

st.set_page_config(page_title="CreatorPulse — Brands", page_icon="📊", layout="wide")
from components.ui import apply_theme  # noqa: E402

apply_theme()

MAX_SHORTLIST = 5
SAMPLE_BRIEF = (
    "Vegan skincare D2C launching nationwide, ₹15 lakh budget, " "women 22–35 metro tier-1"
)
FEATURE_LABELS = {
    "mean_to_median_er_ratio": "Engagement spikiness (mean/median ER)",
    "engagement_rate_gini": "Engagement inequality (Gini)",
    "std_subscriber_growth_pct": "Subscriber-growth volatility",
    "mean_inter_video_days": "Posting-gap irregularity",
    "engagement_cv": "Engagement variability (CV)",
    "mean_comment_to_like_ratio": "Comment-to-like ratio",
}


@st.cache_data(show_spinner=False)
def top_fraud_signals(k: int = 3) -> list[str]:
    """Global top-k SHAP features from the fraud model's eval baseline."""
    path = REPO_ROOT / "evaluation" / "baselines" / "fraud_classifier.json"
    try:
        imp = json.loads(path.read_text())["feature_importance_mean_abs_shap"]
    except (OSError, KeyError, json.JSONDecodeError):
        return []
    ranked = sorted(imp.items(), key=lambda kv: -kv[1])[:k]
    return [FEATURE_LABELS.get(name, name) for name, _ in ranked]


@st.cache_data(show_spinner="Matching creators to the brief…")
def run_match(
    brief: str, budget_lakh: float, top_k: int, rerank: bool = True, niche_filter: str | None = None
) -> pd.DataFrame:
    # Lazy import: apps.ml.match pulls sentence-transformers/torch, so keeping
    # it inside the handler means torch only loads on the first real search.
    from apps.ml import match as match_engine

    return match_engine.match(
        brief, budget_lakh=budget_lakh, top_k=top_k, rerank=rerank, niche_filter=niche_filter
    )


@st.cache_resource(show_spinner=False)
def ensure_shortlist_table() -> bool:
    """Idempotent DDL for the app-managed shortlist (ADR-0016)."""
    eng = data.get_engine()
    with eng.begin() as conn:
        conn.execute(text("create schema if not exists app"))
        conn.execute(
            text(
                "create table if not exists app.brand_shortlist ("
                "session_id text not null, channel_id text not null, "
                "brief text, added_at timestamptz default now(), "
                "primary key (session_id, channel_id))"
            )
        )
    return True


def shortlist_ids(session_id: str) -> list[str]:
    eng = data.get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "select channel_id from app.brand_shortlist "
                "where session_id = :s order by added_at"
            ),
            {"s": session_id},
        ).fetchall()
    return [r[0] for r in rows]


def add_to_shortlist(session_id: str, channel_id: str, brief: str) -> bool:
    if len(shortlist_ids(session_id)) >= MAX_SHORTLIST:
        return False
    eng = data.get_engine()
    with eng.begin() as conn:
        conn.execute(
            text(
                "insert into app.brand_shortlist (session_id, channel_id, brief) "
                "values (:s, :c, :b) on conflict do nothing"
            ),
            {"s": session_id, "c": channel_id, "b": brief},
        )
    return True


def remove_from_shortlist(session_id: str, channel_id: str) -> None:
    eng = data.get_engine()
    with eng.begin() as conn:
        conn.execute(
            text("delete from app.brand_shortlist " "where session_id = :s and channel_id = :c"),
            {"s": session_id, "c": channel_id},
        )


def fraud_badge(risk: float) -> str:
    if risk < 0.33:
        return "🟢 Low fraud risk"
    if risk < 0.66:
        return "🟡 Medium fraud risk"
    return "🔴 High fraud risk"


def score_radar(row: pd.Series) -> go.Figure:
    cats = ["Semantic match", "Niche overlap", "Authenticity", "Budget fit"]
    vals = [
        float(row["cosine"]),
        float(row["niche_overlap"]),
        1.0 - float(row["fraud_risk"]),
        float(row["budget_fit"]),
    ]
    fig = go.Figure(go.Scatterpolar(r=[*vals, vals[0]], theta=[*cats, cats[0]], fill="toself"))
    fig.update_layout(
        polar={"radialaxis": {"range": [0, 1], "visible": True}},
        showlegend=False,
        height=260,
        margin={"l": 30, "r": 30, "t": 20, "b": 20},
    )
    return fig


def overlap_sankey(rows: pd.DataFrame) -> go.Figure:
    creators = rows["title"].fillna(rows["channel_id"]).tolist()
    niches = sorted(rows["niche"].dropna().unique().tolist())
    archetypes = sorted(rows["archetype"].dropna().unique().tolist())
    labels = [*creators, *niches, *archetypes]
    idx = {name: i for i, name in enumerate(labels)}
    src: list[int] = []
    tgt: list[int] = []
    for _, r in rows.iterrows():
        cname = r["title"] if pd.notna(r["title"]) else r["channel_id"]
        if pd.notna(r["niche"]):
            src.append(idx[cname])
            tgt.append(idx[r["niche"]])
            if pd.notna(r["archetype"]):
                src.append(idx[r["niche"]])
                tgt.append(idx[r["archetype"]])
    fig = go.Figure(
        go.Sankey(
            node={"label": labels, "pad": 14, "thickness": 14},
            link={"source": src, "target": tgt, "value": [1] * len(src)},
        )
    )
    fig.update_layout(height=320, margin={"l": 10, "r": 10, "t": 10, "b": 10})
    return fig


render_about_sidebar()
ensure_shortlist_table()

if "brand_session_id" not in st.session_state:
    st.session_state["brand_session_id"] = uuid.uuid4().hex
session_id = st.session_state["brand_session_id"]
analytics.capture_once("persona_brand", "persona_selected", {"persona": "brand"})

st.title("📊 Find creators for your campaign")
st.markdown(
    "Describe your campaign. CreatorPulse ranks Indian YouTube creators by "
    "semantic fit, niche overlap, authenticity, and budget fit — with "
    "engagement-fraud screening applied before you shortlist."
)
creators_df = data.load_creators_df()
niche_opts = ["Any", *sorted(creators_df["niche"].dropna().unique().tolist())]
st.warning(
    f"Indexed dataset: {len(creators_df):,} Indian YouTube creators. Matches can "
    "surface off-niche, and fraud/earnings figures are model estimates (validated "
    "against a simulated cohort), not platform-verified.",
    icon="⚠️",
)

with st.container(border=True):
    brief = st.text_area("Campaign brief", value=SAMPLE_BRIEF, height=100)
    c1, c2 = st.columns([1, 1])
    with c1:
        niche = st.selectbox("Niche focus (optional)", niche_opts, index=0)
    with c2:
        budget_lakh = st.slider("Budget (₹ lakh)", 1.0, 50.0, 15.0, step=1.0)
    search = st.button("🔎 Find creators", type="primary")

if search and brief.strip():
    query = brief.strip()
    niche_filter = None if niche == "Any" else niche
    variant = analytics.match_variant()
    analytics.capture(
        "brief_composed",
        {"brief_length": len(query), "niche": niche, "budget_lakh": float(budget_lakh)},
    )
    matched = run_match(
        query, float(budget_lakh), 20, rerank=(variant == "test"), niche_filter=niche_filter
    )
    top_score = float(matched["final_score"].iloc[0]) if not matched.empty else 0.0
    analytics.capture(
        "match_requested",
        {
            "brief_id": session_id,
            "top_match_score": top_score,
            "num_results": int(len(matched)),
            "$feature/match_rerank_v2": variant,
        },
    )
    st.session_state["brand_results"] = matched.to_dict("records")
    st.session_state["brand_brief"] = query
    st.session_state["brand_variant"] = variant

results = st.session_state.get("brand_results")
brief_used = st.session_state.get("brand_brief", "")

if results:
    res = pd.DataFrame(results)
    join_cols = ["channel_id", "thumbnail_url", "subscriber_count", "mean_views"]
    res = res.merge(creators_df[join_cols], on="channel_id", how="left")
    signals = top_fraud_signals(3)
    current_short = shortlist_ids(session_id)

    st.subheader(f"Top {len(res)} creators")
    for pos, (_, row) in enumerate(res.iterrows()):
        with st.container(border=True):
            left, mid, right = st.columns([2, 1.4, 1.2])
            with left:
                name = row["title"] if pd.notna(row["title"]) else row["channel_id"]
                st.markdown(f"**{name}**  ·  {row['niche']} · _{row['archetype']}_")
                subs = int(row["subscriber_count"]) if pd.notna(row["subscriber_count"]) else 0
                avg_views = int(row["mean_views"]) if pd.notna(row["mean_views"]) else 0
                st.caption(f"Reach: {subs:,} subscribers · ~{avg_views:,} avg views/video")
                st.markdown(
                    f"**Match score: {row['final_score']:.2f}**  ·  "
                    f"{fraud_badge(float(row['fraud_risk']))}"
                )
                est = int(row["est_cost_inr"]) if pd.notna(row["est_cost_inr"]) else 0
                st.caption(
                    f"Est. sponsored-video cost ≈ ₹{est:,} — reach-based proxy "
                    "(typical views × sponsored CPM): what a brand integration costs, "
                    "not the creator's AdSense income."
                )
                if signals:
                    st.caption("Top fraud signals weighed: " + ", ".join(signals))
            with mid:
                st.plotly_chart(
                    score_radar(row),
                    width="stretch",
                    key=f"radar_{row['channel_id']}",
                )
                if st.button("🔍 Why this match?", key=f"why_{row['channel_id']}"):
                    wkey = f"_why_{row['channel_id']}"
                    st.session_state[wkey] = not st.session_state.get(wkey, False)
                    analytics.capture(
                        "match_explained",
                        {"channel_id": row["channel_id"], "match_score": float(row["final_score"])},
                    )
                    analytics.capture(
                        "fraud_report_viewed",
                        {"channel_id": row["channel_id"], "fraud_score": float(row["fraud_risk"])},
                    )
                if st.session_state.get(f"_why_{row['channel_id']}"):
                    st.markdown(
                        "**Score components**\n\n"
                        f"- Semantic match: {float(row['cosine']):.2f}\n"
                        f"- Niche overlap: {float(row['niche_overlap']):.2f}\n"
                        f"- Authenticity (1 - fraud): {1 - float(row['fraud_risk']):.2f}\n"
                        f"- Budget fit: {float(row['budget_fit']):.2f}\n"
                        f"- Composite score: {float(row['final_score']):.2f}"
                    )
            with right:
                if row["channel_id"] in current_short:
                    st.success("In shortlist")
                elif len(current_short) >= MAX_SHORTLIST:
                    st.button(
                        "Shortlist full",
                        key=f"add_{row['channel_id']}",
                        disabled=True,
                    )
                elif st.button("➕ Add to shortlist", key=f"add_{row['channel_id']}"):
                    analytics.capture(
                        "creator_shortlisted",
                        {
                            "channel_id": row["channel_id"],
                            "position_in_results": int(pos),
                            "$feature/match_rerank_v2": st.session_state.get(
                                "brand_variant", "control"
                            ),
                        },
                    )
                    add_to_shortlist(session_id, row["channel_id"], brief_used)
                    st.rerun()

st.divider()
st.subheader("📋 Shortlist")
short = shortlist_ids(session_id)
if len(short) >= 2:
    analytics.capture_once(
        f"compared_{len(short)}",
        "comparison_viewed",
        {"shortlist_size": len(short)},
    )
if not short:
    st.caption("No creators shortlisted yet. Add up to 5 from the results above.")
else:
    sdf = creators_df[creators_df["channel_id"].isin(short)].copy()
    if results:
        rmap = pd.DataFrame(results).set_index("channel_id")
        sdf["match_score"] = sdf["channel_id"].map(rmap["final_score"])
        sdf["fraud_risk"] = sdf["channel_id"].map(rmap["fraud_risk"])
        sdf["est_cost_inr"] = sdf["channel_id"].map(rmap["est_cost_inr"])
    comp = pd.DataFrame(
        {
            "Creator": sdf["title"].fillna(sdf["channel_id"]),
            "Niche": sdf["niche"],
            "Archetype": sdf["archetype"],
            "Subscribers": sdf["subscriber_count"],
            "Est. ₹/video": sdf.get("est_cost_inr"),
            "Fraud risk": sdf.get("fraud_risk"),
            "Match": sdf.get("match_score"),
        }
    )
    st.dataframe(comp, width="stretch", hide_index=True)
    if st.download_button(
        "⬇️ Export shortlist (CSV)",
        comp.to_csv(index=False).encode("utf-8"),
        file_name="creatorpulse_shortlist.csv",
        mime="text/csv",
        key="export_shortlist",
    ):
        analytics.capture("dashboard_exported", {"format": "csv", "rows": int(len(comp))})
    st.plotly_chart(overlap_sankey(sdf), width="stretch")
    st.caption(
        "Composition view (creator → niche → archetype). True audience overlap "
        "needs panel data — scoped to v2."
    )
    rm = st.selectbox("Remove from shortlist", ["—", *short], index=0)
    if rm != "—":
        remove_from_shortlist(session_id, rm)
        st.rerun()
