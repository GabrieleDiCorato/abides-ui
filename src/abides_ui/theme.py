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

/* ── Font overrides (native theme has no font-family control) ─────────── */
html, body, .stApp {
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stWidgetLabel"], label {
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
}
input, textarea, code, pre, [data-testid="stCode"],
.stDataFrame, [data-testid="stDataFrame"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
}
.mono-value {
    font-family: 'JetBrains Mono', monospace !important;
}

/* ── Layout tweaks ────────────────────────────────────────────────────── */
.stApp > header { background-color: transparent !important; }
.block-container, [data-testid="stMainBlockContainer"] {
    padding-top: 1rem !important;
    padding-bottom: 0.5rem !important;
    max-width: 100% !important;
}

/* ── Sidebar border ───────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    border-right: 1px solid #1C2128 !important;
}

/* ── Tabs (Streamlit native theme doesn't style these well) ──────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 0;
    background: #0B0E14;
    border-bottom: 1px solid #1C2128;
    border-radius: 6px 6px 0 0;
    padding: 0 0.5rem;
}
.stTabs [data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.8rem !important;
    font-weight: 500;
    color: #6B7280 !important;
    padding: 0.6rem 1.2rem !important;
    border-radius: 4px 4px 0 0;
    border: none !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: #0070FF !important;
    border-bottom: 2px solid #0070FF !important;
    background: rgba(0, 112, 255, 0.06) !important;
}

/* ── Expander cosmetics ───────────────────────────────────────────────── */
details[data-testid="stExpander"] {
    border: 1px solid #1C2128 !important;
    border-radius: 6px !important;
}

/* ── Dividers ─────────────────────────────────────────────────────────── */
hr { border-color: #1C2128 !important; opacity: 0.5; }

/* ── Scrollbar (native theme has no scrollbar control) ────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #05070A; }
::-webkit-scrollbar-thumb { background: #1C2128; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #6B7280; }

/* ── Hide Streamlit chrome ────────────────────────────────────────────── */
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
