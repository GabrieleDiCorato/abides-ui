"""Plotly figure builders for the dashboard.

Each function accepts pre-computed data (Series, DataFrames, scalars) and
returns a ``plotly.graph_objects.Figure``.  No Streamlit imports here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# ── Market Overview ───────────────────────────────────────────────────────────


def price_series(time: pd.Series, bid: pd.Series, ask: pd.Series, mid: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time, y=bid, mode="lines", name="Best Bid", line={"color": "#2ca02c", "width": 1}))
    fig.add_trace(go.Scatter(x=time, y=ask, mode="lines", name="Best Ask", line={"color": "#d62728", "width": 1}))
    fig.add_trace(go.Scatter(x=time, y=mid, mode="lines", name="Mid Price", line={"color": "#1f77b4", "width": 2}))
    fig.update_layout(
        title="Price Series (Bid / Ask / Mid)",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
        height=450,
    )
    return fig


def spread_over_time(time: pd.Series, spread: pd.Series, avg_spread: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=time,
            y=spread,
            mode="lines",
            name="Spread",
            fill="tozeroy",
            line={"color": "#ff7f0e", "width": 1},
            fillcolor="rgba(255, 127, 14, 0.2)",
        )
    )
    fig.add_hline(y=avg_spread, line_dash="dash", line_color="gray", annotation_text=f"Mean: ${avg_spread:.4f}")
    fig.update_layout(
        title="Bid-Ask Spread Over Time",
        xaxis_title="Time",
        yaxis_title="Spread ($)",
        hovermode="x unified",
        height=300,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


# ── Microstructure ────────────────────────────────────────────────────────────


def rolling_volatility(ret_time: pd.Series, rolling_vol: pd.Series, window: int) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ret_time,
            y=rolling_vol,
            mode="lines",
            name=f"Rolling σ ({window}-tick)",
            line={"color": "#9467bd", "width": 1.5},
        )
    )
    fig.update_layout(
        title=f"Rolling Realized Volatility ({window}-tick window)",
        xaxis_title="Time",
        yaxis_title="σ (log returns)",
        hovermode="x unified",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


def book_pressure(time: pd.Series, pressure: pd.Series) -> go.Figure:
    colors = ["#2ca02c" if v >= 0 else "#d62728" for v in pressure]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=time, y=pressure, name="Bid − Ask Qty", marker_color=colors))
    fig.update_layout(
        title="Order Book Pressure (Bid Qty − Ask Qty)",
        xaxis_title="Time",
        yaxis_title="Qty Imbalance",
        hovermode="x unified",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


def returns_histogram(log_returns: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=log_returns, nbinsx=50, name="Log Returns", marker_color="#1f77b4", opacity=0.7))
    fig.update_layout(
        title="Distribution of Log Returns (Mid-Price)",
        xaxis_title="Log Return",
        yaxis_title="Frequency",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


# ── Order Flow ────────────────────────────────────────────────────────────────


def event_type_pie(event_counts: pd.Series) -> go.Figure:
    fig = go.Figure(data=[go.Pie(labels=event_counts.index.tolist(), values=event_counts.values.tolist(), hole=0.4)])
    fig.update_layout(title="Order Event Types", height=350, margin={"l": 20, "r": 20, "t": 60, "b": 20})
    return fig


def side_balance(side_counts: pd.Series) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Bar(
                x=side_counts.index.tolist(),
                y=side_counts.values.tolist(),
                marker_color=["#2ca02c" if "BID" in s else "#d62728" for s in side_counts.index],
            )
        ]
    )
    fig.update_layout(
        title="Order Side Balance (Submitted)",
        xaxis_title="Side",
        yaxis_title="Count",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


def cumulative_imbalance(flow_time: pd.Series, cum_imbalance: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=flow_time,
            y=cum_imbalance,
            mode="lines",
            name="Cumulative Imbalance",
            line={"color": "#17becf", "width": 1.5},
            fill="tozeroy",
            fillcolor="rgba(23, 190, 207, 0.15)",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="Cumulative Order Flow Imbalance (Buy − Sell)",
        xaxis_title="Time",
        yaxis_title="Cumulative Imbalance",
        hovermode="x unified",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


def volume_by_agent_type(vol_by_type: pd.Series) -> go.Figure:
    fig = go.Figure(data=[go.Bar(x=vol_by_type.values.tolist(), y=vol_by_type.index.tolist(), orientation="h", marker_color="#636efa")])
    fig.update_layout(
        title="Executed Volume by Agent Type",
        xaxis_title="Total Quantity Executed",
        yaxis_title="Agent Type",
        height=max(250, len(vol_by_type) * 50),
        margin={"l": 150, "r": 20, "t": 60, "b": 40},
    )
    return fig


# ── Agent Analytics ───────────────────────────────────────────────────────────


_BOX_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]


def pnl_box_plot(agent_df: pd.DataFrame) -> go.Figure:
    agent_type_list = sorted(agent_df["Type"].unique())
    fig = go.Figure()
    for i, atype in enumerate(agent_type_list):
        subset = agent_df[agent_df["Type"] == atype]["P&L ($)"]
        fig.add_trace(go.Box(y=subset, name=atype, marker_color=_BOX_COLORS[i % len(_BOX_COLORS)], boxmean="sd"))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="P&L Distribution by Agent Type",
        yaxis_title="P&L ($)",
        height=400,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


# ── Execution Analytics (v2.5.0) ─────────────────────────────────────────────


def equity_curve(ec_df: pd.DataFrame, agent_name: str) -> go.Figure:
    """NAV over time with peak watermark and drawdown shading."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ec_df["time"],
            y=ec_df["Peak NAV ($)"],
            mode="lines",
            name="Peak NAV",
            line={"color": "rgba(100,100,100,0.4)", "width": 1, "dash": "dot"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ec_df["time"],
            y=ec_df["NAV ($)"],
            mode="lines",
            name="NAV",
            line={"color": "#1f77b4", "width": 2},
            fill="tonexty",
            fillcolor="rgba(255, 0, 0, 0.08)",
        )
    )
    fig.update_layout(
        title=f"Equity Curve — {agent_name}",
        xaxis_title="Time",
        yaxis_title="NAV ($)",
        hovermode="x unified",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return fig


def slippage_comparison(exec_agents_data: list[dict]) -> go.Figure:
    """Bar chart comparing VWAP slippage across execution agents."""
    names = [d["name"] for d in exec_agents_data]
    slippages = [d["vwap_slippage_bps"] for d in exec_agents_data]
    colors = ["#2ca02c" if s <= 0 else "#d62728" for s in slippages]
    fig = go.Figure(data=[go.Bar(x=names, y=slippages, marker_color=colors)])
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title="VWAP Slippage by Execution Agent",
        xaxis_title="Agent",
        yaxis_title="Slippage (bps)",
        height=350,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
    )
    return fig


# ── Trade Attribution (v2.5.0) ────────────────────────────────────────────────


def maker_taker_volume(maker_vol: pd.Series, taker_vol: pd.Series) -> go.Figure:
    """Grouped bar chart: maker vs taker volume by agent type."""
    all_types = sorted(set(maker_vol.index) | set(taker_vol.index))
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=all_types,
            y=[int(maker_vol.get(t, 0)) for t in all_types],
            name="Maker (passive)",
            marker_color="#2ca02c",
        )
    )
    fig.add_trace(
        go.Bar(
            x=all_types,
            y=[int(taker_vol.get(t, 0)) for t in all_types],
            name="Taker (aggressive)",
            marker_color="#d62728",
        )
    )
    fig.update_layout(
        title="Trade Volume: Maker vs Taker by Agent Type",
        xaxis_title="Agent Type",
        yaxis_title="Volume (shares)",
        barmode="group",
        height=400,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return fig


def trade_price_scatter(attr_df: pd.DataFrame) -> go.Figure:
    """Scatter of trade prices over time, colored by side."""
    buys = attr_df[attr_df["side"].str.upper().str.contains("BID|BUY")]
    sells = attr_df[~attr_df.index.isin(buys.index)]
    fig = go.Figure()
    if len(buys) > 0:
        fig.add_trace(
            go.Scattergl(
                x=buys["time"],
                y=buys["price ($)"],
                mode="markers",
                name="Buy",
                marker={"color": "#2ca02c", "size": 3, "opacity": 0.6},
            )
        )
    if len(sells) > 0:
        fig.add_trace(
            go.Scattergl(
                x=sells["time"],
                y=sells["price ($)"],
                mode="markers",
                name="Sell",
                marker={"color": "#d62728", "size": 3, "opacity": 0.6},
            )
        )
    fig.update_layout(
        title="Trade Prices Over Time (by Side)",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        hovermode="x unified",
        height=400,
        margin={"l": 60, "r": 20, "t": 60, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return fig
