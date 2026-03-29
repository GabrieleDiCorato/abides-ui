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
    rows = [
        {
            "ID": a.agent_id,
            "Type": a.agent_type,
            "Name": a.agent_name,
            "Starting Cash ($)": a.starting_cash_cents / 100,
            "Mark-to-Market ($)": a.mark_to_market_cents / 100,
            "P&L ($)": a.pnl_cents / 100,
            "P&L (%)": round(a.pnl_pct, 4),
        }
        for a in result.agents
    ]
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
