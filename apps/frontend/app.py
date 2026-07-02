"""CreatorPulse India — Streamlit entry point (landing + About)."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = Path(__file__).resolve().parents[0]
for _p in (str(_REPO_ROOT), str(_FRONTEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st  # noqa: E402
from components.about import render_about_sidebar  # noqa: E402

st.set_page_config(page_title="CreatorPulse India", page_icon="📊", layout="wide")
from components.ui import apply_theme  # noqa: E402

apply_theme()

st.title("📊 CreatorPulse India")
st.markdown(
    "**The Creator Economy Intelligence Platform.** Analyze Indian YouTube creators, "
    "screen engagement quality, and forecast niche demand."
)

st.markdown("### Choose a view")
left, right = st.columns(2)
with left:
    st.markdown("#### 🎥 Creator")
    st.write("Profile, growth, engagement quality, niche demand, peers, and tips.")
    st.page_link("pages/creator.py", label="Open the creator view →")
with right:
    st.markdown("#### 🏷️ Brand")
    st.write("Find vetted creators for a campaign brief, with fraud screening.")
    st.page_link("pages/brand.py", label="Open the brand view →")

st.divider()

with st.sidebar:
    render_about_sidebar()
