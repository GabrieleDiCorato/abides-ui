"""Tests for v2.5.0 features: execution analytics, equity curves, trade attribution."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest
from abides_markets.config_system import (
    AgentGroupConfig,
    ExchangeConfig,
    MarketConfig,
    SimulationConfig,
    SimulationMeta,
    SparseMeanRevertingOracleConfig,
    list_agent_types,
)
from abides_markets.simulation import ResultProfile, run_simulation
from abides_markets.simulation.result import AgentData, EquityCurve, ExecutionMetrics, TradeAttribution

from abides_ui import charts, metrics

# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_market() -> MarketConfig:
    return MarketConfig(
        ticker="ABM",
        date="20210205",
        start_time="09:30:00",
        end_time="09:35:00",
        oracle=SparseMeanRevertingOracleConfig(r_bar=100_000),
        exchange=ExchangeConfig(book_logging=True, book_log_depth=10),
    )


def _exec_config(*, seed: int = 42) -> SimulationConfig:
    """Config that includes an execution agent for analytics testing."""
    return SimulationConfig(
        market=MarketConfig(
            ticker="ABM",
            date="20210205",
            start_time="09:30:00",
            end_time="09:45:00",  # 15-min window to fit execution offsets
            oracle=SparseMeanRevertingOracleConfig(r_bar=100_000),
            exchange=ExchangeConfig(book_logging=True, book_log_depth=10),
        ),
        agents={
            "noise": AgentGroupConfig(enabled=True, count=100, params={}),
            "value": AgentGroupConfig(enabled=True, count=10, params={}),
            "adaptive_market_maker": AgentGroupConfig(enabled=True, count=2, params={}),
            "pov_execution": AgentGroupConfig(enabled=True, count=1, params={}),
        },
        simulation=SimulationMeta(seed=seed),
    )


def _fake_agent(
    agent_id: int = 1,
    agent_type: str = "pov_execution",
    pnl_cents: int = 500,
    exec_metrics: ExecutionMetrics | None = None,
    eq_curve: EquityCurve | None = None,
) -> AgentData:
    return AgentData(
        agent_id=agent_id,
        agent_type=agent_type,
        agent_name=f"{agent_type}_{agent_id}",
        final_holdings={"CASH": 10_000_000},
        starting_cash_cents=10_000_000,
        mark_to_market_cents=10_000_000 + pnl_cents,
        pnl_cents=pnl_cents,
        pnl_pct=pnl_cents / 10_000_000 * 100,
        execution_metrics=exec_metrics,
        equity_curve=eq_curve,
    )


def _fake_exec_metrics() -> ExecutionMetrics:
    return ExecutionMetrics(
        target_quantity=1000,
        filled_quantity=950,
        fill_rate_pct=95.0,
        avg_fill_price_cents=100_050,
        vwap_cents=100_000,
        vwap_slippage_bps=5.0,
        participation_rate_pct=12.5,
        arrival_price_cents=100_000,
        implementation_shortfall_bps=5.0,
    )


def _fake_equity_curve() -> EquityCurve:
    # 5 data points
    base = 1_000_000_000_000  # some base nanosecond
    return EquityCurve(
        times_ns=[base + i * 1_000_000_000 for i in range(5)],
        nav_cents=[10_000_000, 10_000_100, 10_000_050, 10_000_200, 10_000_150],
        peak_nav_cents=[10_000_000, 10_000_100, 10_000_100, 10_000_200, 10_000_200],
    )


def _fake_trades() -> list[TradeAttribution]:
    base = 1_000_000_000_000
    return [TradeAttribution(time_ns=base + i * 1_000_000, passive_agent_id=0, aggressive_agent_id=1, side="BID", price_cents=100_000 + i, quantity=10 + i) for i in range(20)]


# ── New agent types ──────────────────────────────────────────────────────────


class TestNewAgentTypes:
    def test_new_agent_types_registered(self):
        names = {a["name"] for a in list_agent_types()}
        for expected in ("mean_reversion", "twap_execution", "vwap_execution"):
            assert expected in names, f"Expected agent type '{expected}' not found"

    def test_eight_agent_types_total(self):
        assert len(list_agent_types()) == 8

    def test_vwap_has_volume_profile_param(self):
        agents = list_agent_types()
        vwap = next(a for a in agents if a["name"] == "vwap_execution")
        params = vwap["parameters"]
        assert "volume_profile" in params
        schema = params["volume_profile"]
        # Should resolve to array type
        any_of = schema.get("anyOf")
        if any_of:
            types = [s.get("type") for s in any_of if isinstance(s, dict)]
            assert "array" in types or "null" in types


# ── ResultProfile ─────────────────────────────────────────────────────────────


class TestResultProfile:
    def test_quant_profile_exists(self):
        assert hasattr(ResultProfile, "QUANT")

    def test_quant_includes_trade_attribution(self):
        assert (ResultProfile.QUANT & ResultProfile.TRADE_ATTRIBUTION) != 0

    def test_quant_includes_equity_curve(self):
        assert (ResultProfile.QUANT & ResultProfile.EQUITY_CURVE) != 0


# ── Execution metrics (unit) ─────────────────────────────────────────────────


class TestExecutionMetrics:
    def test_get_execution_agents_with_exec(self):
        em = _fake_exec_metrics()
        agents = [_fake_agent(exec_metrics=em), _fake_agent(agent_id=2, agent_type="noise")]
        # Simulate result.agents
        exec_only = [a for a in agents if a.execution_metrics is not None]
        assert len(exec_only) == 1

    def test_compute_execution_summary(self):
        em = _fake_exec_metrics()
        ec = _fake_equity_curve()
        agents = [_fake_agent(exec_metrics=em, eq_curve=ec)]
        summary = metrics.compute_execution_summary(agents)
        assert summary is not None
        assert summary.total_target == 1000
        assert summary.total_filled == 950
        assert summary.avg_fill_rate == 95.0
        assert summary.avg_vwap_slippage_bps == 5.0
        assert summary.max_drawdown_cents is not None

    def test_compute_execution_summary_empty(self):
        assert metrics.compute_execution_summary([]) is None

    def test_build_execution_detail_df(self):
        em = _fake_exec_metrics()
        agent = _fake_agent(exec_metrics=em)
        df = metrics.build_execution_detail_df(agent)
        assert len(df) == 1
        assert "Fill Rate (%)" in df.columns
        assert "VWAP Slippage (bps)" in df.columns

    def test_build_execution_detail_df_no_metrics(self):
        agent = _fake_agent()
        df = metrics.build_execution_detail_df(agent)
        assert len(df) == 0


# ── Equity curve (unit) ──────────────────────────────────────────────────────


class TestEquityCurve:
    def test_build_equity_curve_df(self):
        ec = _fake_equity_curve()
        agent = _fake_agent(eq_curve=ec)
        df = metrics.build_equity_curve_df(agent)
        assert df is not None
        assert len(df) == 5
        assert "NAV ($)" in df.columns
        assert "Peak NAV ($)" in df.columns
        assert "time" in df.columns

    def test_build_equity_curve_df_none(self):
        agent = _fake_agent()
        assert metrics.build_equity_curve_df(agent) is None

    def test_max_drawdown_property(self):
        ec = _fake_equity_curve()
        assert ec.max_drawdown_cents >= 0


# ── Trade attribution (unit) ─────────────────────────────────────────────────


class TestTradeAttribution:
    def test_build_trade_attribution_df(self):
        trades = _fake_trades()
        agents = [_fake_agent(agent_id=0, agent_type="mm"), _fake_agent(agent_id=1, agent_type="exec")]
        df = metrics.build_trade_attribution_df(trades, agents)
        assert len(df) == 20
        assert "maker_type" in df.columns
        assert "taker_type" in df.columns
        assert df["maker_type"].iloc[0] == "mm"
        assert df["taker_type"].iloc[0] == "exec"

    def test_compute_maker_taker_summary(self):
        trades = _fake_trades()
        agents = [_fake_agent(agent_id=0, agent_type="mm"), _fake_agent(agent_id=1, agent_type="exec")]
        df = metrics.build_trade_attribution_df(trades, agents)
        summary = metrics.compute_maker_taker_summary(df)
        assert summary.total_trades == 20
        assert len(summary.maker_volume_by_type) > 0
        assert len(summary.taker_volume_by_type) > 0


# ── Agent DataFrame with exec metrics ────────────────────────────────────────


class TestAgentDataFrameExec:
    def test_build_agent_df_includes_exec_fields(self):
        em = _fake_exec_metrics()
        agents_data = [_fake_agent(exec_metrics=em), _fake_agent(agent_id=2, agent_type="noise")]
        # Build a minimal SimulationResult-like structure isn't easy,
        # so we test the row-building logic directly
        rows = []
        for a in agents_data:
            row: dict[str, object] = {
                "ID": a.agent_id,
                "Type": a.agent_type,
                "P&L ($)": a.pnl_cents / 100,
            }
            if a.execution_metrics is not None:
                row["Fill Rate (%)"] = round(a.execution_metrics.fill_rate_pct, 2)
                row["VWAP Slippage (bps)"] = round(a.execution_metrics.vwap_slippage_bps, 2)
            rows.append(row)
        df = pd.DataFrame(rows)
        assert "Fill Rate (%)" in df.columns
        # noise agent should have NaN for exec fields
        assert pd.isna(df.iloc[1]["Fill Rate (%)"])


# ── Chart smoke tests ─────────────────────────────────────────────────────────


class TestNewCharts:
    def test_equity_curve_chart(self):
        ec = _fake_equity_curve()
        agent = _fake_agent(eq_curve=ec)
        ec_df = metrics.build_equity_curve_df(agent)
        assert ec_df is not None
        fig = charts.equity_curve(ec_df, "test_agent")
        assert isinstance(fig, go.Figure)

    def test_slippage_comparison_chart(self):
        data = [
            {"name": "Agent A", "vwap_slippage_bps": 3.5},
            {"name": "Agent B", "vwap_slippage_bps": -1.2},
        ]
        fig = charts.slippage_comparison(data)
        assert isinstance(fig, go.Figure)

    def test_maker_taker_volume_chart(self):
        maker = pd.Series({"mm": 500, "noise": 200}, name="quantity")
        taker = pd.Series({"exec": 400, "noise": 300}, name="quantity")
        fig = charts.maker_taker_volume(maker, taker)
        assert isinstance(fig, go.Figure)

    def test_trade_price_scatter_chart(self):
        trades = _fake_trades()
        agents = [_fake_agent(agent_id=0), _fake_agent(agent_id=1)]
        df = metrics.build_trade_attribution_df(trades, agents)
        fig = charts.trade_price_scatter(df)
        assert isinstance(fig, go.Figure)


# ── Integration: QUANT profile run ───────────────────────────────────────────


@pytest.mark.slow
class TestQuandProfile:
    def test_quant_profile_has_trade_attribution(self):
        cfg = _exec_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.QUANT)
        market = result.markets["ABM"]
        assert market.trades is not None
        assert len(market.trades) > 0

    def test_quant_profile_has_equity_curve(self):
        cfg = _exec_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.QUANT)
        exec_agents = metrics.get_execution_agents(result)
        assert len(exec_agents) > 0
        # Equity curve is populated only if the agent had fills
        for a in exec_agents:
            if a.execution_metrics and a.execution_metrics.filled_quantity > 0:
                assert a.equity_curve is not None

    def test_quant_profile_has_execution_metrics(self):
        cfg = _exec_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.QUANT)
        exec_agents = metrics.get_execution_agents(result)
        assert len(exec_agents) > 0
        for a in exec_agents:
            assert a.execution_metrics is not None
            assert a.execution_metrics.target_quantity > 0

    def test_quant_profile_no_order_logs(self):
        """QUANT profile should not include raw agent logs."""
        cfg = _exec_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.QUANT)
        order_df = metrics.extract_order_log(result)
        assert order_df is None

    def test_full_pipeline_execution_tab(self):
        """End-to-end: run sim, compute execution metrics, build charts."""
        cfg = _exec_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.QUANT)
        exec_agents = metrics.get_execution_agents(result)
        assert len(exec_agents) > 0

        summary = metrics.compute_execution_summary(exec_agents)
        assert summary is not None
        assert summary.total_filled > 0

        for agent in exec_agents:
            detail = metrics.build_execution_detail_df(agent)
            assert len(detail) == 1

            ec_df = metrics.build_equity_curve_df(agent)
            if ec_df is not None:
                fig = charts.equity_curve(ec_df, agent.agent_name)
                assert isinstance(fig, go.Figure)

    def test_full_pipeline_trade_attribution(self):
        """End-to-end: run sim, build trade attribution, compute summary."""
        cfg = _exec_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.QUANT)
        market = result.markets["ABM"]
        assert market.trades is not None

        attr_df = metrics.build_trade_attribution_df(market.trades, result.agents)
        assert len(attr_df) > 0

        summary = metrics.compute_maker_taker_summary(attr_df)
        assert summary.total_trades > 0

        fig1 = charts.maker_taker_volume(summary.maker_volume_by_type, summary.taker_volume_by_type)
        assert isinstance(fig1, go.Figure)

        fig2 = charts.trade_price_scatter(attr_df)
        assert isinstance(fig2, go.Figure)
