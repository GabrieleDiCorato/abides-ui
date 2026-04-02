"""Plotly figure builders for the dashboard.

Each function accepts pre-computed data (Series, DataFrames, scalars) and
returns a ``plotly.graph_objects.Figure``.  No Streamlit imports here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from abides_ui.theme import HEIGHT_PRIMARY, HEIGHT_SECONDARY, PALETTE, SERIES_COLORS, apply_fin_theme

# ── Market Overview ───────────────────────────────────────────────────────────


def price_series(time: pd.Series, bid: pd.Series, ask: pd.Series, mid: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time, y=bid, mode="lines", name="Best Bid", line={"color": PALETTE["market"], "width": 1}))
    fig.add_trace(go.Scatter(x=time, y=ask, mode="lines", name="Best Ask", line={"color": PALETTE["hft"], "width": 1}))
    fig.add_trace(go.Scatter(x=time, y=mid, mode="lines", name="Mid Price", line={"color": PALETTE["institutional"], "width": 2}))
    fig.update_layout(
        title="Price Series (Bid / Ask / Mid)",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        height=HEIGHT_PRIMARY,
    )
    return apply_fin_theme(fig)


def spread_over_time(time: pd.Series, spread: pd.Series, avg_spread: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=time,
            y=spread,
            mode="lines",
            name="Spread",
            fill="tozeroy",
            line={"color": PALETTE["warning"], "width": 1},
            fillcolor="rgba(255, 165, 0, 0.12)",
        )
    )
    fig.add_hline(y=avg_spread, line_dash="dash", line_color=PALETTE["text_dim"], annotation_text=f"Mean: ${avg_spread:.4f}")
    fig.update_layout(
        title="Bid-Ask Spread Over Time",
        xaxis_title="Time",
        yaxis_title="Spread ($)",
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


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
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


def book_pressure(time: pd.Series, pressure: pd.Series) -> go.Figure:
    colors = [PALETTE["market"] if v >= 0 else PALETTE["hft"] for v in pressure]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=time, y=pressure, name="Bid − Ask Qty", marker_color=colors))
    fig.update_layout(
        title="Order Book Pressure (Bid Qty − Ask Qty)",
        xaxis_title="Time",
        yaxis_title="Qty Imbalance",
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


def returns_histogram(log_returns: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=log_returns, nbinsx=50, name="Log Returns", marker_color=PALETTE["institutional"], opacity=0.7))
    fig.update_layout(
        title="Distribution of Log Returns (Mid-Price)",
        xaxis_title="Log Return",
        yaxis_title="Frequency",
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


# ── Order Flow ────────────────────────────────────────────────────────────────


def event_type_pie(event_counts: pd.Series) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Pie(
                labels=event_counts.index.tolist(),
                values=event_counts.values.tolist(),
                hole=0.4,
                marker={"colors": SERIES_COLORS[: len(event_counts)]},
            )
        ]
    )
    fig.update_layout(title="Order Event Types", height=HEIGHT_SECONDARY)
    return apply_fin_theme(fig)


def side_balance(side_counts: pd.Series) -> go.Figure:
    fig = go.Figure(
        data=[
            go.Bar(
                x=side_counts.index.tolist(),
                y=side_counts.values.tolist(),
                marker_color=[PALETTE["market"] if "BID" in s else PALETTE["hft"] for s in side_counts.index],
            )
        ]
    )
    fig.update_layout(
        title="Order Side Balance (Submitted)",
        xaxis_title="Side",
        yaxis_title="Count",
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


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
            fillcolor="rgba(23, 190, 207, 0.10)",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["text_dim"])
    fig.update_layout(
        title="Cumulative Order Flow Imbalance (Buy − Sell)",
        xaxis_title="Time",
        yaxis_title="Cumulative Imbalance",
        height=HEIGHT_PRIMARY,
    )
    return apply_fin_theme(fig)


def volume_by_agent_type(vol_by_type: pd.Series) -> go.Figure:
    fig = go.Figure(data=[go.Bar(x=vol_by_type.values.tolist(), y=vol_by_type.index.tolist(), orientation="h", marker_color=PALETTE["institutional"])])
    fig.update_layout(
        title="Executed Volume by Agent Type",
        xaxis_title="Total Quantity Executed",
        yaxis_title="Agent Type",
        height=max(250, len(vol_by_type) * 50),
        margin={"l": 150, "r": 16, "t": 44, "b": 32},
    )
    return apply_fin_theme(fig)


# ── Agent Analytics ───────────────────────────────────────────────────────────


def pnl_box_plot(agent_df: pd.DataFrame) -> go.Figure:
    agent_type_list = sorted(agent_df["Type"].unique())
    fig = go.Figure()
    for i, atype in enumerate(agent_type_list):
        subset = agent_df[agent_df["Type"] == atype]["P&L ($)"]
        fig.add_trace(go.Box(y=subset, name=atype, marker_color=SERIES_COLORS[i % len(SERIES_COLORS)], boxmean="sd"))
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["text_dim"])
    fig.update_layout(
        title="P&L Distribution by Agent Type",
        yaxis_title="P&L ($)",
        height=HEIGHT_PRIMARY,
    )
    return apply_fin_theme(fig)


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
            line={"color": PALETTE["institutional"], "width": 2},
            fill="tonexty",
            fillcolor="rgba(255, 59, 63, 0.06)",
        )
    )
    fig.update_layout(
        title=f"Equity Curve — {agent_name}",
        xaxis_title="Time",
        yaxis_title="NAV ($)",
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


def slippage_comparison(exec_agents_data: list[dict]) -> go.Figure:
    """Bar chart comparing VWAP slippage across execution agents."""
    names = [d["name"] for d in exec_agents_data]
    slippages = [d["vwap_slippage_bps"] for d in exec_agents_data]
    colors = [PALETTE["market"] if s <= 0 else PALETTE["hft"] for s in slippages]
    fig = go.Figure(data=[go.Bar(x=names, y=slippages, marker_color=colors)])
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["text_dim"])
    fig.update_layout(
        title="VWAP Slippage by Execution Agent",
        xaxis_title="Agent",
        yaxis_title="Slippage (bps)",
        height=HEIGHT_SECONDARY,
    )
    return apply_fin_theme(fig)


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
            marker_color=PALETTE["market"],
        )
    )
    fig.add_trace(
        go.Bar(
            x=all_types,
            y=[int(taker_vol.get(t, 0)) for t in all_types],
            name="Taker (aggressive)",
            marker_color=PALETTE["hft"],
        )
    )
    fig.update_layout(
        title="Trade Volume: Maker vs Taker by Agent Type",
        xaxis_title="Agent Type",
        yaxis_title="Volume (shares)",
        barmode="group",
        height=HEIGHT_PRIMARY,
    )
    return apply_fin_theme(fig)


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
                marker={"color": PALETTE["market"], "size": 3, "opacity": 0.6},
            )
        )
    if len(sells) > 0:
        fig.add_trace(
            go.Scattergl(
                x=sells["time"],
                y=sells["price ($)"],
                mode="markers",
                name="Sell",
                marker={"color": PALETTE["hft"], "size": 3, "opacity": 0.6},
            )
        )
    fig.update_layout(
        title="Trade Prices Over Time (by Side)",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        height=HEIGHT_PRIMARY,
    )
    return apply_fin_theme(fig)


# ── L2 Order Book Depth (v2.5.5) ─────────────────────────────────────────────


def l2_depth_heatmap(l2_df: pd.DataFrame, mid: pd.Series | None = None) -> go.Figure:
    """Heatmap of order book depth over time.

    Expects a tidy L2 DataFrame with columns:
    time_ns, side, level, price_cents, qty.
    """
    bids = l2_df[l2_df["side"] == "bid"].copy()
    asks = l2_df[l2_df["side"] == "ask"].copy()

    for df in (bids, asks):
        df["time"] = pd.to_datetime(df["time_ns"], unit="ns")
        df["price ($)"] = df["price_cents"] / 100

    # Pivot into time × price grid
    bid_pivot = bids.pivot_table(index="price ($)", columns="time", values="qty", aggfunc="sum", fill_value=0)
    ask_pivot = asks.pivot_table(index="price ($)", columns="time", values="qty", aggfunc="sum", fill_value=0)

    fig = go.Figure()

    if len(bid_pivot) > 0:
        fig.add_trace(
            go.Heatmap(
                x=bid_pivot.columns,
                y=bid_pivot.index,
                z=bid_pivot.values,
                colorscale=[[0, "rgba(0,0,0,0)"], [1, PALETTE["market"]]],
                name="Bids",
                showscale=False,
                hovertemplate="Time: %{x}<br>Price: $%{y:.2f}<br>Qty: %{z}<extra>Bid</extra>",
            )
        )

    if len(ask_pivot) > 0:
        fig.add_trace(
            go.Heatmap(
                x=ask_pivot.columns,
                y=ask_pivot.index,
                z=ask_pivot.values,
                colorscale=[[0, "rgba(0,0,0,0)"], [1, PALETTE["hft"]]],
                name="Asks",
                showscale=False,
                hovertemplate="Time: %{x}<br>Price: $%{y:.2f}<br>Qty: %{z}<extra>Ask</extra>",
            )
        )

    if mid is not None and len(mid.dropna()) > 0:
        mid_time = pd.to_datetime(np.sort(l2_df["time_ns"].unique()), unit="ns")
        # Resample mid to match L2 timestamps
        mid_resampled = mid.iloc[: len(mid_time)] if len(mid) >= len(mid_time) else mid
        fig.add_trace(
            go.Scatter(
                x=mid_time[: len(mid_resampled)],
                y=mid_resampled.values,
                mode="lines",
                name="Mid Price",
                line={"color": PALETTE["institutional"], "width": 2},
            )
        )

    fig.update_layout(
        title="Order Book Depth Heatmap (L2)",
        xaxis_title="Time",
        yaxis_title="Price ($)",
        height=HEIGHT_PRIMARY + 80,
    )
    return apply_fin_theme(fig)


def l2_depth_profile(l2_df: pd.DataFrame) -> go.Figure:
    """Snapshot depth profile — average quantity at each price level."""
    bids = l2_df[l2_df["side"] == "bid"]
    asks = l2_df[l2_df["side"] == "ask"]

    bid_levels = bids.groupby("level")["qty"].mean().sort_index()
    ask_levels = asks.groupby("level")["qty"].mean().sort_index()

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[-v for v in bid_levels.values],
            y=[f"Bid L{i}" for i in bid_levels.index],
            orientation="h",
            name="Bid Depth",
            marker_color=PALETTE["market"],
        )
    )
    fig.add_trace(
        go.Bar(
            x=ask_levels.values.tolist(),
            y=[f"Ask L{i}" for i in ask_levels.index],
            orientation="h",
            name="Ask Depth",
            marker_color=PALETTE["hft"],
        )
    )
    fig.update_layout(
        title="Average Depth Profile by Level",
        xaxis_title="Avg Quantity (negative = bids)",
        yaxis_title="Book Level",
        height=HEIGHT_SECONDARY,
        barmode="relative",
    )
    return apply_fin_theme(fig)
