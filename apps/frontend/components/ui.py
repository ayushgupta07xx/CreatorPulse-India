"""Central CreatorPulse Streamlit theming — one apply_theme() per page.

Matches the Next.js/Vercel brand: dark petrol base, teal accent, Manrope type.
Does NOT touch data/logic. Import and call apply_theme() once right after
st.set_page_config on every page; use plotly_theme() as the figure template and
RISK_COLORS for the fraud badges (thresholds mirror brand.py: <0.33 / <0.66).
"""

from __future__ import annotations

import streamlit as st

# --- Brand tokens (exact, from apps/web/tailwind.config.ts) -------------------
BG = "#07070B"
SURFACE = "#111C20"
SURFACE2 = "#16151F"
LINE = "#1B1B26"
INK = "#ECECF2"
MUTED = "#8A8AA0"
TEAL = "#54E0CE"
VIOLET = "#9C8BFF"
PINK = "#FF5FA8"
RISK_LOW = "#7DE9CE"
RISK_MID = "#E6C27E"
RISK_HIGH = "#FF7A8A"

# Fraud-badge colors keyed to brand.py thresholds (<0.33 low, <0.66 mid, else high)
RISK_COLORS = {"low": RISK_LOW, "mid": RISK_MID, "high": RISK_HIGH}


def risk_color(risk: float) -> str:
    """Map a 0..1 fraud-risk score to the brand risk color (same cuts as fraud_badge)."""
    if risk < 0.33:
        return RISK_LOW
    if risk < 0.66:
        return RISK_MID
    return RISK_HIGH


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap');

:root {{
  --bg: {BG}; --surface: {SURFACE}; --surface2: {SURFACE2}; --line: {LINE};
  --ink: {INK}; --muted: {MUTED}; --teal: {TEAL}; --violet: {VIOLET};
}}

/* Base canvas + type */
html, body, [class*="css"], .stApp {{
  font-family: 'Manrope', -apple-system, BlinkMacSystemFont, sans-serif !important;
}}
.stApp {{ background: {BG}; color: {INK}; }}

/* Kill Streamlit chrome (default header bar, footer, menu, deploy button) */
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] {{ visibility: hidden; }}

/* Headings — Manrope, tight, ink */
h1, h2, h3, h4 {{ font-family: 'Manrope', sans-serif !important; color: {INK};
  font-weight: 700; letter-spacing: -0.01em; }}
h1 {{ font-weight: 800; }}
p, span, label, li, div {{ color: {INK}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {MUTED} !important; }}

/* Sidebar */
section[data-testid="stSidebar"] {{ background: {SURFACE}; border-right: 1px solid {LINE}; }}
section[data-testid="stSidebar"] * {{ color: {INK}; }}
section[data-testid="stSidebar"] a {{ color: {TEAL}; text-decoration: none; }}

/* Bordered containers → brand cards with a subtle teal-lit bottom bloom */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background:
    radial-gradient(120% 80% at 50% 120%, rgba(84,224,206,0.08), transparent 60%),
    {SURFACE};
  border: 1px solid {LINE} !important;
  border-radius: 14px;
  padding: 4px 2px;
}}

/* Metrics */
[data-testid="stMetric"] {{
  background: {SURFACE}; border: 1px solid {LINE}; border-radius: 12px;
  padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{ color: {TEAL}; font-weight: 700; }}
[data-testid="stMetricLabel"] {{ color: {MUTED}; }}

/* Buttons + page links → teal outline, teal fill on hover */
.stButton > button, [data-testid="stPageLink"] a {{
  background: transparent; color: {TEAL};
  border: 1px solid rgba(84,224,206,0.4); border-radius: 10px;
  font-weight: 600; transition: all .18s ease;
}}
.stButton > button:hover, [data-testid="stPageLink"] a:hover {{
  background: rgba(84,224,206,0.12); border-color: {TEAL};
  transform: scale(0.99);
}}

/* Inputs */
.stTextInput input, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div,
.stTextArea textarea {{
  background: {SURFACE2} !important; color: {INK} !important;
  border: 1px solid {LINE} !important; border-radius: 10px !important;
}}

/* Dataframe */
[data-testid="stDataFrame"] {{ border: 1px solid {LINE}; border-radius: 12px; }}

/* Dividers + tighter default padding */
hr {{ border-color: {LINE}; }}
.block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
</style>
"""


def apply_theme() -> None:
    """Inject the CreatorPulse brand CSS. Call once per page after set_page_config."""
    st.markdown(_CSS, unsafe_allow_html=True)


def plotly_theme(fig):
    """Apply the brand palette to a Plotly figure: transparent bg, Manrope, teal grid.

    Returns the same figure for chaining. Per-trace colors set at call sites
    (teal markers, violet forecast) are preserved; this styles the frame.
    """
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Manrope, sans-serif", "color": INK},
        colorway=[TEAL, VIOLET, PINK, RISK_MID],
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        legend={"bgcolor": "rgba(0,0,0,0)"},
    )
    fig.update_xaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, zerolinecolor=LINE, linecolor=LINE)
    return fig
