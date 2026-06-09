"""CreatorPulse India — Streamlit entry point (landing + About)."""

import streamlit as st

st.set_page_config(page_title="CreatorPulse India", page_icon="📊", layout="wide")

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
    st.caption("Brand view ships next.")

st.divider()

with st.sidebar:
    st.markdown("#### About")
    st.markdown(
        "**CreatorPulse India** — built by **Ayush Gupta**.  \n"
        "[GitHub](https://github.com/ayushgupta07xx) · [LinkedIn](https://www.linkedin.com/in/ayush-gupta-544a803a2)"
    )
    st.caption(
        "Data via the official YouTube Data API v3. Engagement and earnings "
        "figures are model estimates, not platform-verified."
    )
