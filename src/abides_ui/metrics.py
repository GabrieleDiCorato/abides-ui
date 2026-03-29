"""Pure financial computations on simulation results.

All functions accept pandas objects and return plain data (dataclasses, dicts,
Series).  No Streamlit or Plotly imports here — this module is independently
testable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from abides_markets.simulation import SimulationResult
from abides_markets.simulation.result import AgentData, TradeAttribution

# ── L1 series derivation ─────────────────────────────────────────────────────


@dataclass
class L1Derived:
    """Derived time-series from raw L1 snapshots."""

    l1_df: pd.DataFrame
    time: pd.Series
    bid: pd.Series
    ask: pd.Series
    mid: pd.Series
    spread: pd.Series
    log_returns: pd.Series


def derive_l1(l1_df: pd.DataFrame) -> L1Derived:
    """Convert raw L1 DataFrame into derived price/spread/return series.

    NaN in bid/ask represents an empty book side (no liquidity), **not** missing
    data.  NaNs propagate into mid and spread intentionally — they are preserved
    in charts as gaps and reported separately in statistics.
    """
    time = pd.to_datetime(l1_df["time_ns"], unit="ns")
    bid = pd.to_numeric(l1_df["bid_price_cents"], errors="coerce") / 100
    ask = pd.to_numeric(l1_df["ask_price_cents"], errors="coerce") / 100
    mid = (bid + ask) / 2
    spread = ask - bid

    ratio = mid / mid.shift(1)
    ratio = ratio[(ratio > 0) & ratio.notna()]
    log_returns = np.log(ratio)
    log_returns = log_returns.replace([np.inf, -np.inf], np.nan).dropna()

    return L1Derived(
        l1_df=l1_df,
        time=time,
        bid=bid,
        ask=ask,
        mid=mid,
        spread=spread,
        log_returns=log_returns,
    )


# ── Summary-header metrics ────────────────────────────────────────────────────


@dataclass
class SummaryMetrics:
    mid_close: float | None
    spread_close: float | None
    vwap: float | None
    volume: int
    realized_vol: float | None
    price_range: float | None


def compute_summary(market: object, l1: L1Derived | None) -> SummaryMetrics:
    """Top-level summary numbers shown above the tabs."""
    bid = market.l1_close.bid_price_cents  # type: ignore[union-attr]
    ask = market.l1_close.ask_price_cents  # type: ignore[union-attr]
    mid_close = ((bid + ask) / 2 / 100) if bid is not None and ask is not None else None
    spread_close = ((ask - bid) / 100) if bid is not None and ask is not None else None
    volume = market.liquidity.total_exchanged_volume  # type: ignore[union-attr]
    vwap_cents = market.liquidity.vwap_cents  # type: ignore[union-attr]
    vwap = vwap_cents / 100 if vwap_cents is not None else None

    realized_vol = None
    if l1 is not None and len(l1.log_returns) > 1:
        realized_vol = float(l1.log_returns.std())

    price_range = None
    if l1 is not None:
        valid_mid = l1.mid.dropna()
        if len(valid_mid) > 0:
            price_range = float(valid_mid.max() - valid_mid.min())

    return SummaryMetrics(
        mid_close=mid_close,
        spread_close=spread_close,
        vwap=vwap,
        volume=volume,
        realized_vol=realized_vol,
        price_range=price_range,
    )


# ── Spread statistics ─────────────────────────────────────────────────────────


@dataclass
class SpreadStats:
    n_total: int
    n_two_sided: int
    n_one_sided: int
    mean: float | None
    median: float | None
    max: float | None
    std: float | None
    mean_pct: float | None
    median_pct: float | None


def compute_spread_stats(spread: pd.Series, mid: pd.Series) -> SpreadStats:
    n_total = len(spread)
    two_sided = spread.dropna()
    n_two_sided = len(two_sided)
    n_one_sided = n_total - n_two_sided
    valid_mid = mid.dropna()
    spread_pct = (two_sided / valid_mid * 100).dropna() if len(valid_mid) > 0 else pd.Series(dtype=float)

    return SpreadStats(
        n_total=n_total,
        n_two_sided=n_two_sided,
        n_one_sided=n_one_sided,
        mean=float(two_sided.mean()) if n_two_sided > 0 else None,
        median=float(two_sided.median()) if n_two_sided > 0 else None,
        max=float(two_sided.max()) if n_two_sided > 0 else None,
        std=float(two_sided.std()) if n_two_sided > 1 else None,
        mean_pct=float(spread_pct.mean()) if len(spread_pct) > 0 else None,
        median_pct=float(spread_pct.median()) if len(spread_pct) > 0 else None,
    )


# ── Returns distribution stats ────────────────────────────────────────────────


@dataclass
class ReturnStats:
    mean: float
    std: float
    skewness: float
    kurtosis: float


def compute_return_stats(log_returns: pd.Series) -> ReturnStats | None:
    if len(log_returns) < 6:
        return None
    return ReturnStats(
        mean=float(log_returns.mean()),
        std=float(log_returns.std()),
        skewness=float(log_returns.skew()) if len(log_returns) > 2 else 0.0,
        kurtosis=float(log_returns.kurtosis()) if len(log_returns) > 3 else 0.0,
    )


# ── Book pressure ─────────────────────────────────────────────────────────────


def compute_book_pressure(l1_df: pd.DataFrame) -> pd.Series:
    """Bid depth minus ask depth.  NaN qty (empty side) is treated as zero."""
    bid_qty = pd.to_numeric(l1_df["bid_qty"], errors="coerce").fillna(0)
    ask_qty = pd.to_numeric(l1_df["ask_qty"], errors="coerce").fillna(0)
    return bid_qty - ask_qty


# ── Rolling volatility ───────────────────────────────────────────────────────


def compute_rolling_vol(log_returns: pd.Series) -> tuple[pd.Series, int] | None:
    if len(log_returns) <= 10:
        return None
    window = min(100, len(log_returns) // 3) if len(log_returns) > 30 else max(5, len(log_returns) // 3)
    return log_returns.rolling(window=window).std(), window


# ── Order flow statistics ─────────────────────────────────────────────────────


@dataclass
class OrderFlowStats:
    total_submitted: int
    executed: int
    cancelled: int
    fill_rate: float
    cancel_rate: float


def compute_order_flow_stats(order_df: pd.DataFrame) -> OrderFlowStats:
    if "EventType" not in order_df.columns:
        return OrderFlowStats(0, 0, 0, 0.0, 0.0)

    submitted = int((order_df["EventType"] == "ORDER_SUBMITTED").sum())
    executed = int((order_df["EventType"] == "ORDER_EXECUTED").sum())
    cancelled = int(order_df["EventType"].isin(["ORDER_CANCELLED", "PARTIAL_CANCELLED"]).sum())
    fill_rate = (executed / submitted * 100) if submitted > 0 else 0.0
    cancel_rate = (cancelled / submitted * 100) if submitted > 0 else 0.0

    return OrderFlowStats(
        total_submitted=submitted,
        executed=executed,
        cancelled=cancelled,
        fill_rate=fill_rate,
        cancel_rate=cancel_rate,
    )


# ── Cumulative order flow imbalance ──────────────────────────────────────────


def compute_cumulative_imbalance(order_df: pd.DataFrame) -> pd.DataFrame | None:
    """Return DataFrame with columns [EventTime, flow_sign, cum_imbalance]."""
    if "side" not in order_df.columns or "EventTime" not in order_df.columns:
        return None
    submitted = order_df[order_df["EventType"] == "ORDER_SUBMITTED"].copy()
    if len(submitted) == 0:
        return None
    submitted = submitted.sort_values("EventTime")
    submitted["flow_sign"] = submitted["side"].apply(lambda s: 1 if "BID" in s else (-1 if "ASK" in s else 0)).astype(int)
    submitted["cum_imbalance"] = submitted["flow_sign"].cumsum()
    return submitted


# ── Agent analytics ───────────────────────────────────────────────────────────


def build_agent_dataframe(result: SimulationResult) -> pd.DataFrame:
    rows = []
    for a in result.agents:
        row: dict[str, object] = {
            "ID": a.agent_id,
            "Type": a.agent_type,
            "Name": a.agent_name,
            "Starting Cash ($)": a.starting_cash_cents / 100,
            "Mark-to-Market ($)": a.mark_to_market_cents / 100,
            "P&L ($)": a.pnl_cents / 100,
            "P&L (%)": round(a.pnl_pct, 4),
        }
        if a.execution_metrics is not None:
            em = a.execution_metrics
            row["Fill Rate (%)"] = round(em.fill_rate_pct, 2) if em.fill_rate_pct is not None else None
            row["VWAP Slippage (bps)"] = round(em.vwap_slippage_bps, 2) if em.vwap_slippage_bps is not None else None
            row["Participation (%)"] = round(em.participation_rate_pct, 2) if em.participation_rate_pct is not None else None
            row["Impl. Shortfall (bps)"] = round(em.implementation_shortfall_bps, 2) if em.implementation_shortfall_bps is not None else None
        rows.append(row)
    return pd.DataFrame(rows)


def compute_agent_performance(agent_df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        agent_df.groupby("Type")
        .agg(
            Count=("ID", "count"),
            **{"Win Rate (%)": ("P&L ($)", lambda x: (x > 0).mean() * 100)},
            **{"Avg P&L ($)": ("P&L ($)", "mean")},
            **{"Total P&L ($)": ("P&L ($)", "sum")},
            **{"Std P&L ($)": ("P&L ($)", "std")},
            **{"Avg P&L (%)": ("P&L (%)", "mean")},
        )
        .reset_index()
    )
    agg["Info Ratio"] = agg.apply(
        lambda r: round(r["Avg P&L ($)"] / r["Std P&L ($)"], 4) if pd.notna(r["Std P&L ($)"]) and r["Std P&L ($)"] > 0 else 0.0,
        axis=1,
    )
    return agg


def build_holdings_table(result: SimulationResult) -> pd.DataFrame | None:
    rows = []
    for a in result.agents:
        for asset, qty in a.final_holdings.items():
            if asset == "CASH":
                continue
            rows.append({"Type": a.agent_type, "Agent": a.agent_name, "Asset": asset, "Shares": qty})
    if not rows:
        return None
    hdf = pd.DataFrame(rows)
    return (
        hdf.groupby("Type")
        .agg(
            **{"Total Shares": ("Shares", "sum")},
            **{"Avg Shares": ("Shares", "mean")},
            **{"Min Shares": ("Shares", "min")},
            **{"Max Shares": ("Shares", "max")},
        )
        .reset_index()
    )


def build_leaderboard(agent_df: pd.DataFrame) -> pd.DataFrame:
    lb = agent_df.sort_values("P&L ($)", ascending=False).reset_index(drop=True)
    lb.index = lb.index + 1
    lb.index.name = "Rank"
    return lb


# ── Order log extraction ─────────────────────────────────────────────────────


def extract_order_log(result: SimulationResult) -> pd.DataFrame | None:
    try:
        df = result.order_logs()
        if df is None or len(df) == 0:
            return None
        if "side" in df.columns:
            df["side"] = df["side"].astype(str)
        return df
    except Exception:
        return None


# ── Execution analytics (v2.5.0) ─────────────────────────────────────────────


def get_execution_agents(result: SimulationResult) -> list[AgentData]:
    """Return agents that have execution metrics (POV / TWAP / VWAP)."""
    return [a for a in result.agents if a.execution_metrics is not None]


@dataclass
class ExecutionSummary:
    total_target: int
    total_filled: int
    avg_fill_rate: float
    avg_vwap_slippage_bps: float
    max_drawdown_cents: int | None


def compute_execution_summary(exec_agents: list[AgentData]) -> ExecutionSummary | None:
    if not exec_agents:
        return None
    total_target = sum(a.execution_metrics.target_quantity for a in exec_agents)  # type: ignore[union-attr]
    total_filled = sum(a.execution_metrics.filled_quantity for a in exec_agents)  # type: ignore[union-attr]
    rates = [a.execution_metrics.fill_rate_pct for a in exec_agents if a.execution_metrics and a.execution_metrics.fill_rate_pct is not None]  # type: ignore[union-attr]
    slippages = [a.execution_metrics.vwap_slippage_bps for a in exec_agents if a.execution_metrics and a.execution_metrics.vwap_slippage_bps is not None]  # type: ignore[union-attr]
    drawdowns = [a.equity_curve.max_drawdown_cents for a in exec_agents if a.equity_curve is not None]
    return ExecutionSummary(
        total_target=total_target,
        total_filled=total_filled,
        avg_fill_rate=sum(rates) / len(rates) if rates else 0.0,
        avg_vwap_slippage_bps=sum(slippages) / len(slippages) if slippages else 0.0,
        max_drawdown_cents=max(drawdowns) if drawdowns else None,
    )


def build_execution_detail_df(agent: AgentData) -> pd.DataFrame:
    """Build a single-row DataFrame of execution quality metrics for one agent."""
    em = agent.execution_metrics
    if em is None:
        return pd.DataFrame()
    return pd.DataFrame(
        [
            {
                "Target Qty": em.target_quantity,
                "Filled Qty": em.filled_quantity,
                "Fill Rate (%)": round(em.fill_rate_pct, 2) if em.fill_rate_pct is not None else None,
                "Avg Fill Price ($)": em.avg_fill_price_cents / 100 if em.avg_fill_price_cents is not None else None,
                "VWAP ($)": em.vwap_cents / 100 if em.vwap_cents is not None else None,
                "VWAP Slippage (bps)": round(em.vwap_slippage_bps, 2) if em.vwap_slippage_bps is not None else None,
                "Participation (%)": round(em.participation_rate_pct, 2) if em.participation_rate_pct is not None else None,
                "Arrival Price ($)": em.arrival_price_cents / 100 if em.arrival_price_cents is not None else None,
                "Impl. Shortfall (bps)": round(em.implementation_shortfall_bps, 2) if em.implementation_shortfall_bps is not None else None,
            }
        ]
    )


def build_equity_curve_df(agent: AgentData) -> pd.DataFrame | None:
    """Convert an agent's EquityCurve to a time-indexed DataFrame."""
    ec = agent.equity_curve
    if ec is None or len(ec.times_ns) == 0:
        return None
    return pd.DataFrame(
        {
            "time": pd.to_datetime(ec.times_ns, unit="ns"),
            "NAV ($)": [c / 100 for c in ec.nav_cents],
            "Peak NAV ($)": [c / 100 for c in ec.peak_nav_cents],
        }
    )


# ── Trade attribution (v2.5.0) ────────────────────────────────────────────────


def build_trade_attribution_df(
    trades: list[TradeAttribution],
    agents: list[AgentData],
) -> pd.DataFrame:
    """Turn raw TradeAttribution list into an analytical DataFrame."""
    id_to_type = {a.agent_id: a.agent_type for a in agents}
    rows = [
        {
            "time": pd.Timestamp(t.time_ns, unit="ns"),
            "price ($)": t.price_cents / 100,
            "quantity": t.quantity,
            "side": t.side,
            "maker_id": t.passive_agent_id,
            "taker_id": t.aggressive_agent_id,
            "maker_type": id_to_type.get(t.passive_agent_id, "unknown"),
            "taker_type": id_to_type.get(t.aggressive_agent_id, "unknown"),
        }
        for t in trades
    ]
    return pd.DataFrame(rows)


@dataclass
class MakerTakerSummary:
    total_trades: int
    maker_volume_by_type: pd.Series
    taker_volume_by_type: pd.Series


def compute_maker_taker_summary(attr_df: pd.DataFrame) -> MakerTakerSummary:
    return MakerTakerSummary(
        total_trades=len(attr_df),
        maker_volume_by_type=attr_df.groupby("maker_type")["quantity"].sum().sort_values(ascending=False),
        taker_volume_by_type=attr_df.groupby("taker_type")["quantity"].sum().sort_values(ascending=False),
    )
