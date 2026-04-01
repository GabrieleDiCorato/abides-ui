"""Carbon Dark theme: CSS injection, Plotly theming, and color palette.

Centralizes all visual constants so the rest of the app stays
presentation-agnostic.
"""

from __future__ import annotations

import plotly.graph_objects as go

# ── Color palette ─────────────────────────────────────────────────────────────

PALETTE: dict[str, str] = {
    "hft": "#FF3B3F",
    "institutional": "#0070FF",
    "market": "#00C805",
    "warning": "#FFA500",
    "neutral": "#6B7280",
    "text": "#E0E0E0",
    "text_secondary": "#A0A8B4",
    "text_dim": "#6B7280",
    "bg": "#05070A",
    "surface": "#0B0E14",
    "surface_raised": "#111519",
    "border": "#1C2128",
}

# Categorical colors for multi-series charts (agent types, etc.)
SERIES_COLORS: list[str] = [
    "#0070FF",  # institutional blue
    "#FF3B3F",  # hft red
    "#00C805",  # market green
    "#FFA500",  # warning orange
    "#9467bd",  # purple
    "#17becf",  # cyan
    "#e377c2",  # pink
    "#8c564b",  # brown
]

# ── Chart height constants ────────────────────────────────────────────────────

HEIGHT_PRIMARY = 380  # full-width hero charts
HEIGHT_SECONDARY = 320  # half-width / supporting charts

# ── Global CSS ────────────────────────────────────────────────────────────────

CARBON_DARK_CSS: str = """
/* ── Google Fonts ─────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap');

/* ── Root variables ───────────────────────────────────────────────────── */
:root {
    --bg: #05070A;
    --surface: #0B0E14;
    --surface-raised: #111519;
    --border: #1C2128;
    --border-subtle: rgba(255, 255, 255, 0.06);
    --text: #E0E0E0;
    --text-secondary: #A0A8B4;
    --text-dim: #6B7280;
    --accent-blue: #0070FF;
    --accent-red: #FF3B3F;
    --accent-green: #00C805;
}

/* ── Global resets ────────────────────────────────────────────────────── */
html, body, .stApp {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', sans-serif !important;
}
/* Kill ALL default white/light backgrounds from BaseWeb & Streamlit */
.stApp div, .stApp section, .stApp span, .stApp p {
    border-color: var(--border) !important;
}

.stApp > header { background-color: transparent !important; }

.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: 1rem !important;
    padding-bottom: 0.5rem !important;
    max-width: 100% !important;
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] label {
    color: var(--text) !important;
}

/* ── All labels & text ────────────────────────────────────────────────── */
label, .stSelectbox label, .stTextInput label, .stNumberInput label,
.stDateInput label, .stTimeInput label, [data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p {
    color: var(--text-secondary) !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
}
[data-testid="stMarkdownContainer"] h5,
[data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] h3 {
    color: var(--text) !important;
}
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
.stCaption, small, caption {
    color: var(--text-dim) !important;
}

/* ── Tabs ──────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    border-radius: 6px 6px 0 0;
    padding: 0 0.5rem;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.8rem !important;
    font-weight: 500;
    color: var(--text-dim) !important;
    padding: 0.6rem 1.2rem !important;
    border-radius: 4px 4px 0 0;
    border: none !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: var(--accent-blue) !important;
    border-bottom: 2px solid var(--accent-blue) !important;
    background: rgba(0, 112, 255, 0.06) !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 0.6rem !important;
}

/* ── Expanders ────────────────────────────────────────────────────────── */
details[data-testid="stExpander"] {
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    background: var(--surface) !important;
}
details[data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] {
    color: var(--text) !important;
    font-family: 'Inter', sans-serif !important;
}

/* ══ ALL INPUT FIELDS ═════════════════════════════════════════════════ */
/* Broadest possible: every <input> and every BaseWeb input wrapper */
.stApp input[type="text"],
.stApp input[type="number"],
.stApp input[type="password"],
.stApp input[type="email"],
.stApp input[type="tel"],
.stApp input:not([type]),
.stApp textarea {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    caret-color: var(--accent-blue) !important;
}
/* BaseWeb input root + inner wrappers */
[data-baseweb="input"],
[data-baseweb="input"] > div,
[data-baseweb="input"] > div > div {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
}
/* Number input entire container (Streamlit wraps it in nested divs) */
.stNumberInput > div,
.stNumberInput > div > div,
.stNumberInput [data-baseweb="input"],
.stNumberInput [data-baseweb="input"] div {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
}
/* Focus ring */
[data-baseweb="input"]:focus-within,
.stNumberInput [data-baseweb="input"]:focus-within,
.stTextInput [data-baseweb="input"]:focus-within {
    border-color: var(--accent-blue) !important;
    box-shadow: 0 0 0 1px rgba(0, 112, 255, 0.25) !important;
}

/* Number input +/- stepper buttons */
.stNumberInput button,
[data-testid="stNumberInput"] button,
.stNumberInput [data-testid="stNumberInputStepUp"],
.stNumberInput [data-testid="stNumberInputStepDown"] {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
    color: var(--text-secondary) !important;
}
.stNumberInput button:hover {
    background-color: rgba(0, 112, 255, 0.12) !important;
    border-color: var(--accent-blue) !important;
    color: var(--accent-blue) !important;
}

/* ── Select / Dropdown ────────────────────────────────────────────────── */
[data-baseweb="select"],
[data-baseweb="select"] > div,
[data-baseweb="select"] > div > div {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
}
[data-baseweb="select"] span {
    color: var(--text) !important;
}
/* Dropdown menu */
[data-baseweb="popover"] > div,
[data-baseweb="menu"],
[data-baseweb="menu"] ul,
[role="listbox"],
[role="listbox"] li {
    background-color: var(--surface) !important;
    color: var(--text) !important;
}
[role="listbox"] li:hover,
[data-baseweb="menu"] li:hover,
[role="option"]:hover,
[data-highlighted="true"] {
    background-color: var(--surface-raised) !important;
}

/* Date / Time input containers */
.stDateInput > div > div,
.stDateInput [data-baseweb="input"],
.stTimeInput > div > div,
.stTimeInput [data-baseweb="input"] {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
}
/* Date picker calendar popup */
[data-baseweb="calendar"],
[data-baseweb="calendar"] > div {
    background-color: var(--surface) !important;
    color: var(--text) !important;
}
/* Time picker popup */
[data-baseweb="time-picker"],
[data-baseweb="select"] [role="listbox"] {
    background-color: var(--surface) !important;
}

/* ══ TOGGLE / SWITCH ═════════════════════════════════════════════════ */
/* Target every possible toggle/switch element across Streamlit versions */
/* Off track */
.stToggle [role="checkbox"],
[data-testid="stToggle"] [role="checkbox"],
div[data-baseweb="toggle"] > div:first-child,
[role="checkbox"][aria-checked="false"] {
    background-color: #2D333B !important;
    border-color: #3D444D !important;
}
/* On track */
.stToggle [role="checkbox"][aria-checked="true"],
[data-testid="stToggle"] [role="checkbox"][aria-checked="true"],
div[data-baseweb="toggle"] > div[aria-checked="true"]:first-child {
    background-color: var(--accent-blue) !important;
    border-color: var(--accent-blue) !important;
}
/* Toggle label text */
.stToggle p,
.stToggle span,
.stToggle label,
[data-testid="stToggle"] p {
    color: var(--text-secondary) !important;
}

/* ══ CHECKBOX ════════════════════════════════════════════════════════ */
/* Unchecked box — visible gray border on dark */
.stCheckbox [role="checkbox"],
[data-testid="stCheckbox"] [role="checkbox"],
[data-baseweb="checkbox"] [role="checkbox"] {
    border-color: #3D444D !important;
    background-color: var(--surface-raised) !important;
    border-width: 2px !important;
}
/* Checked box — blue fill */
.stCheckbox [role="checkbox"][aria-checked="true"],
[data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"],
[data-baseweb="checkbox"] [role="checkbox"][aria-checked="true"] {
    background-color: var(--accent-blue) !important;
    border-color: var(--accent-blue) !important;
}
/* Checkmark icon inside — white */
.stCheckbox [role="checkbox"] svg,
[data-baseweb="checkbox"] svg {
    fill: white !important;
    color: white !important;
}
/* Checkbox label */
.stCheckbox label span:last-child,
.stCheckbox label p,
[data-testid="stCheckbox"] label p {
    color: var(--text-secondary) !important;
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
.stButton > button[kind="primary"],
button[kind="primary"] {
    background: var(--accent-blue) !important;
    border: none !important;
    color: white !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600;
}
/* Secondary buttons */
.stButton > button:not([kind="primary"]),
.stDownloadButton > button {
    background: var(--surface-raised) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-secondary) !important;
}
.stButton > button:not([kind="primary"]):hover,
.stDownloadButton > button:hover {
    border-color: var(--accent-blue) !important;
    color: var(--accent-blue) !important;
}

/* ── File uploader ────────────────────────────────────────────────────── */
[data-testid="stFileUploader"],
[data-testid="stFileUploader"] section,
[data-testid="stFileUploader"] > div {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
}

/* ── Text area ────────────────────────────────────────────────────────── */
.stTextArea textarea,
[data-testid="stTextArea"] textarea {
    background: var(--surface-raised) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
    font-family: 'JetBrains Mono', monospace !important;
}

/* ── Warning / Info / Error / Success alerts ──────────────────────────── */
[data-testid="stAlert"],
.stAlert {
    background-color: var(--surface-raised) !important;
    border-color: var(--border) !important;
}

/* ── Data tables ──────────────────────────────────────────────────────── */
[data-testid="stDataFrame"],
.stDataFrame {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
}

/* ── Metric widget ────────────────────────────────────────────────────── */
[data-testid="stMetric"] label {
    color: var(--text-dim) !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: var(--text) !important;
}

/* ── Tooltip / help icon ──────────────────────────────────────────────── */
[data-testid="stTooltipIcon"] {
    color: var(--text-dim) !important;
}

/* ── Dividers ─────────────────────────────────────────────────────────── */
hr {
    border-color: var(--border) !important;
    opacity: 0.5;
}

/* ── Code blocks ──────────────────────────────────────────────────────── */
pre, code, [data-testid="stCode"] {
    background-color: var(--surface-raised) !important;
    color: var(--text) !important;
}

/* ── Scrollbar ────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-dim); }

/* ── Typography numerics ──────────────────────────────────────────────── */
.mono-value {
    font-family: 'JetBrains Mono', monospace !important;
}

/* ── Hide default Streamlit footer + hamburger ────────────────────────── */
footer { visibility: hidden; }
#MainMenu { visibility: hidden; }
"""

# ── Plotly theme ──────────────────────────────────────────────────────────────


def apply_fin_theme(fig: go.Figure) -> go.Figure:
    """Apply institutional-grade dark theme to any Plotly figure."""
    _grid = "rgba(255, 255, 255, 0.07)"
    _spike = "#6B7280"

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "JetBrains Mono, monospace", "color": "#E0E0E0", "size": 11},
        title_font={"family": "Inter, sans-serif", "color": "#E0E0E0", "size": 13},
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "rgba(11, 14, 20, 0.92)",
            "bordercolor": "#1C2128",
            "font": {"family": "JetBrains Mono, monospace", "size": 11, "color": "#E0E0E0"},
        },
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "bgcolor": "rgba(11, 14, 20, 0.6)",
            "bordercolor": "rgba(255, 255, 255, 0.06)",
            "borderwidth": 1,
            "font": {"size": 10, "color": "#8A919B"},
        },
        margin={"l": 50, "r": 16, "t": 44, "b": 32},
    )

    # Axes: faint grid + spike crosshairs
    _axis_common = {
        "gridcolor": _grid,
        "gridwidth": 1,
        "zerolinecolor": "rgba(255, 255, 255, 0.12)",
        "zerolinewidth": 1,
        "showspikes": True,
        "spikemode": "across",
        "spikethickness": 1,
        "spikedash": "dot",
        "spikecolor": _spike,
        "spikesnap": "cursor",
        "title_font": {"family": "Inter, sans-serif", "size": 11, "color": "#8A919B"},
        "tickfont": {"family": "JetBrains Mono, monospace", "size": 10, "color": "#8A919B"},
    }
    fig.update_xaxes(**_axis_common)
    fig.update_yaxes(**_axis_common)

    return fig
