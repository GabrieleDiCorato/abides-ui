"""Smoke tests for abides-ui.

These tests verify the core code paths without launching Streamlit:
  - Library registry discovery (agents, templates)
  - JSON Schema type resolution (including Pydantic v2 anyOf nullable)
  - SimulationConfig construction
  - End-to-end simulation run
  - CLI entry-point importability
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from abides_markets.config_system import (
    AgentGroupConfig,
    ExchangeConfig,
    MarketConfig,
    SimulationConfig,
    SimulationMeta,
    SparseMeanRevertingOracleConfig,
    get_full_manifest,
    list_agent_types,
    list_templates,
    validate_config,
)
from abides_markets.config_system.templates import get_template
from abides_markets.simulation import ResultProfile, SimulationResult, run_simulation

# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_market() -> MarketConfig:
    return MarketConfig(
        ticker="ABM",
        date="20210205",
        start_time="09:30:00",
        end_time="09:35:00",  # short window for speed
        oracle=SparseMeanRevertingOracleConfig(r_bar=100_000),
        exchange=ExchangeConfig(book_logging=True, book_log_depth=10),
    )


def _minimal_agents() -> dict[str, AgentGroupConfig]:
    """Value + noise — smallest viable mix."""
    return {
        "noise": AgentGroupConfig(enabled=True, count=5, params={}),
        "value": AgentGroupConfig(enabled=True, count=5, params={}),
    }


def _minimal_config(*, seed: int = 42) -> SimulationConfig:
    return SimulationConfig(
        market=_default_market(),
        agents=_minimal_agents(),
        simulation=SimulationMeta(seed=seed),
    )


def resolve_type(schema: dict) -> tuple[str, bool]:
    """Replicate the type-resolution logic from app.py."""
    nullable = False
    any_of = schema.get("anyOf")
    if any_of:
        types = [s.get("type") for s in any_of if isinstance(s, dict)]
        nullable = "null" in types
        non_null = [t for t in types if t != "null"]
        param_type = non_null[0] if len(non_null) == 1 else "string"
    else:
        raw_type = schema.get("type", "string")
        if isinstance(raw_type, list):
            nullable = "null" in raw_type
            non_null = [t for t in raw_type if t != "null"]
            param_type = non_null[0] if len(non_null) == 1 else "string"
        else:
            param_type = raw_type
    return param_type, nullable


# ── Registry discovery ────────────────────────────────────────────────────────


class TestRegistry:
    def test_list_agent_types_returns_nonempty(self):
        agents = list_agent_types()
        assert isinstance(agents, list)
        assert len(agents) > 0

    def test_agent_type_structure(self):
        agents = list_agent_types()
        for a in agents:
            assert "name" in a
            assert "category" in a
            assert "description" in a
            assert "parameters" in a
            assert isinstance(a["parameters"], dict)

    def test_agent_type_v2_metadata(self):
        """v2.2.0: agent types carry oracle/count/dependency metadata."""
        agents = list_agent_types()
        for a in agents:
            assert "requires_oracle" in a, f"Missing requires_oracle on {a['name']}"
            assert isinstance(a["requires_oracle"], bool)
            if "typical_count_range" in a and a["typical_count_range"] is not None:
                assert len(a["typical_count_range"]) == 2

    def test_value_agent_requires_oracle(self):
        agents = list_agent_types()
        value = next(a for a in agents if a["name"] == "value")
        assert value["requires_oracle"] is True

    def test_noise_agent_does_not_require_oracle(self):
        agents = list_agent_types()
        noise = next(a for a in agents if a["name"] == "noise")
        assert noise["requires_oracle"] is False

    def test_known_agent_types_present(self):
        names = {a["name"] for a in list_agent_types()}
        for expected in ("noise", "value"):
            assert expected in names, f"Expected agent type '{expected}' not found"

    def test_list_templates_returns_nonempty(self):
        templates = list_templates()
        assert isinstance(templates, list)
        assert len(templates) > 0

    def test_template_structure(self):
        templates = list_templates()
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "is_overlay" in t

    def test_get_template_returns_dict(self):
        templates = list_templates()
        base = [t for t in templates if not t["is_overlay"]]
        assert len(base) > 0
        config = get_template(base[0]["name"])
        assert isinstance(config, dict)
        assert "market" in config or "agents" in config


# ── Manifest & validation (v2.2.0) ───────────────────────────────────────────


class TestManifest:
    def test_get_full_manifest_structure(self):
        m = get_full_manifest()
        assert "agent_types" in m
        assert "templates" in m
        assert "oracle_options" in m
        assert "categories" in m

    def test_manifest_oracle_options(self):
        m = get_full_manifest()
        oracle_types = [o.get("type") for o in m["oracle_options"]]
        assert "sparse_mean_reverting" in oracle_types
        assert None in oracle_types  # oracle-absent mode

    def test_manifest_categories_present(self):
        m = get_full_manifest()
        assert len(m["categories"]) > 0


class TestValidation:
    def test_validate_valid_config(self):
        cfg = _minimal_config()
        result = validate_config(cfg.model_dump())
        assert result.valid

    def test_validate_unknown_agent_is_error(self):
        cfg = SimulationConfig(
            market=_default_market(),
            agents={
                "nonexistent_agent": AgentGroupConfig(enabled=True, count=5, params={}),
            },
            simulation=SimulationMeta(seed=42),
        )
        result = validate_config(cfg.model_dump())
        assert not result.valid
        assert any("nonexistent_agent" in e.message for e in result.errors)

    def test_validation_issues_have_fields(self):
        cfg = _minimal_config()
        result = validate_config(cfg.model_dump())
        for issue in result.errors + result.warnings:
            assert hasattr(issue, "severity")
            assert hasattr(issue, "message")


# ── Type resolution (anyOf / nullable) ────────────────────────────────────────


class TestTypeResolution:
    """Verify the JSON Schema type-resolution logic handles both patterns."""

    def test_simple_type(self):
        pt, nullable = resolve_type({"type": "integer"})
        assert pt == "integer"
        assert nullable is False

    def test_simple_string(self):
        pt, nullable = resolve_type({"type": "string"})
        assert pt == "string"
        assert nullable is False

    def test_type_list_nullable(self):
        pt, nullable = resolve_type({"type": ["integer", "null"]})
        assert pt == "integer"
        assert nullable is True

    def test_anyof_nullable(self):
        """Pydantic v2 pattern for int | None."""
        pt, nullable = resolve_type(
            {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": None,
            }
        )
        assert pt == "integer"
        assert nullable is True

    def test_anyof_non_nullable(self):
        pt, nullable = resolve_type(
            {
                "anyOf": [{"type": "string"}],
            }
        )
        assert pt == "string"
        assert nullable is False

    def test_no_type_defaults_to_string(self):
        pt, nullable = resolve_type({})
        assert pt == "string"
        assert nullable is False

    def test_union_int_str_falls_back_to_string(self):
        """Union[int, str] (e.g. window_size) must resolve to string widget."""
        pt, nullable = resolve_type({"type": ["integer", "string"], "default": "adaptive"})
        assert pt == "string"
        assert nullable is False

    def test_anyof_union_int_str_falls_back_to_string(self):
        """anyOf with multiple non-null types must resolve to string widget."""
        pt, nullable = resolve_type(
            {
                "anyOf": [{"type": "integer"}, {"type": "string"}],
                "default": "adaptive",
            }
        )
        assert pt == "string"
        assert nullable is False

    def test_value_agent_sigma_n_is_nullable_integer(self):
        """sigma_n on ValueAgentConfig must be resolved as nullable integer."""
        agents = list_agent_types()
        value_agent = next(a for a in agents if a["name"] == "value")
        params = value_agent["parameters"]
        assert "sigma_n" in params, "sigma_n param missing from value agent"
        pt, nullable = resolve_type(params["sigma_n"])
        assert pt == "integer", f"Expected integer, got {pt}"
        assert nullable is True, "sigma_n should be nullable"


# ── Config construction ───────────────────────────────────────────────────────


class TestConfigConstruction:
    def test_minimal_config_creates(self):
        cfg = _minimal_config()
        assert isinstance(cfg, SimulationConfig)
        assert cfg.market.ticker == "ABM"

    def test_agents_in_config(self):
        cfg = _minimal_config()
        assert "noise" in cfg.agents
        assert "value" in cfg.agents
        assert cfg.agents["noise"].count == 5

    def test_oracle_config(self):
        cfg = _minimal_config()
        oracle = cfg.market.oracle
        assert isinstance(oracle, SparseMeanRevertingOracleConfig)
        assert oracle.r_bar == 100_000

    def test_agent_group_with_nullable_param_omitted(self):
        """Omitting sigma_n (nullable int) from params should be valid."""
        cfg = SimulationConfig(
            market=_default_market(),
            agents={
                "value": AgentGroupConfig(enabled=True, count=2, params={}),
                "noise": AgentGroupConfig(enabled=True, count=2, params={}),
            },
            simulation=SimulationMeta(seed=1),
        )
        assert cfg.agents["value"].params.get("sigma_n") is None

    def test_agent_group_with_nullable_param_set(self):
        """Explicitly setting sigma_n to an int should be valid."""
        cfg = SimulationConfig(
            market=_default_market(),
            agents={
                "value": AgentGroupConfig(enabled=True, count=2, params={"sigma_n": 1000}),
                "noise": AgentGroupConfig(enabled=True, count=2, params={}),
            },
            simulation=SimulationMeta(seed=1),
        )
        assert cfg.agents["value"].params["sigma_n"] == 1000

    def test_all_templates_produce_valid_configs(self):
        """Every base template should load without error."""
        templates = list_templates()
        base = [t for t in templates if not t["is_overlay"]]
        for t in base:
            config = get_template(t["name"])
            assert isinstance(config, dict), f"Template {t['name']} did not return dict"

    def test_oracle_absent_config(self):
        """Oracle-absent mode: oracle=None with opening_price."""
        cfg = SimulationConfig(
            market=MarketConfig(
                ticker="ABM",
                date="20210205",
                start_time="09:30:00",
                end_time="09:35:00",
                oracle=None,
                opening_price=100_000,
                exchange=ExchangeConfig(),
            ),
            agents={
                "noise": AgentGroupConfig(enabled=True, count=5, params={}),
            },
            simulation=SimulationMeta(seed=42),
        )
        assert cfg.market.oracle is None
        assert cfg.market.opening_price == 100_000

    def test_field_descriptions_present(self):
        """v2.2.0: agent parameter schemas carry descriptions."""
        agents = list_agent_types()
        for a in agents:
            for param_name, schema in a["parameters"].items():
                desc = schema.get("description")
                assert desc is not None and len(desc) > 0, f"Missing description for {a['name']}.{param_name}"


# ── Simulation run ────────────────────────────────────────────────────────────


@pytest.mark.slow
class TestSimulationRun:
    """End-to-end sim run. Marked slow — skipped by default, run with -m slow."""

    def test_run_minimal_simulation(self):
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY)
        assert isinstance(result, SimulationResult)

    def test_result_has_market_data(self):
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY)
        assert "ABM" in result.markets
        market = result.markets["ABM"]
        assert market.l1_close is not None
        assert market.liquidity is not None

    def test_result_has_agents(self):
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY)
        assert len(result.agents) > 0
        for a in result.agents:
            assert hasattr(a, "pnl_cents")
            assert hasattr(a, "agent_type")

    def test_result_with_l1_series(self):
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY | ResultProfile.L1_SERIES)
        market = result.markets["ABM"]
        assert market.l1_series is not None
        df = market.l1_series.as_dataframe()
        assert "time_ns" in df.columns
        assert "bid_price_cents" in df.columns
        assert len(df) > 0

    def test_sigma_n_omitted_does_not_crash(self):
        """Regression: sigma_n=None must not cause ValidationError."""
        cfg = SimulationConfig(
            market=_default_market(),
            agents={
                "value": AgentGroupConfig(enabled=True, count=2, params={}),
                "noise": AgentGroupConfig(enabled=True, count=2, params={}),
            },
            simulation=SimulationMeta(seed=99),
        )
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY)
        assert isinstance(result, SimulationResult)

    def test_full_profile_produces_order_logs(self):
        """ResultProfile.FULL should provide order logs."""
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.FULL)
        assert isinstance(result, SimulationResult)
        order_df = result.order_logs()
        assert order_df is not None
        assert len(order_df) > 0
        assert "EventType" in order_df.columns

    def test_summary_dict(self):
        """v2.2.0: summary_dict() returns structured data for widgets."""
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY)
        summary = result.summary_dict()
        assert isinstance(summary, dict)
        assert "metadata" in summary
        assert "markets" in summary
        assert "ABM" in summary["markets"]
        market_summary = summary["markets"]["ABM"]
        assert "vwap_cents" in market_summary
        assert "total_volume" in market_summary

    def test_vwap_from_liquidity_metrics(self):
        """v2.2.0: LiquidityMetrics carries vwap_cents directly."""
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.SUMMARY)
        market = result.markets["ABM"]
        assert hasattr(market.liquidity, "vwap_cents")

    def test_order_logs_have_expected_columns(self):
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.FULL)
        order_df = result.order_logs()
        for col in ["EventTime", "EventType", "agent_id"]:
            assert col in order_df.columns, f"Missing column {col}"

    def test_l1_derived_metrics(self):
        """Verify L1-derived quant metrics can be computed."""
        cfg = SimulationConfig(
            market=MarketConfig(
                ticker="ABM",
                date="20210205",
                start_time="09:30:00",
                end_time="09:35:00",
                oracle=SparseMeanRevertingOracleConfig(r_bar=100_000),
                exchange=ExchangeConfig(book_logging=True, book_log_depth=10),
            ),
            agents={
                "noise": AgentGroupConfig(enabled=True, count=100, params={}),
                "value": AgentGroupConfig(enabled=True, count=10, params={}),
                "adaptive_market_maker": AgentGroupConfig(enabled=True, count=2, params={}),
            },
            simulation=SimulationMeta(seed=42),
        )
        result = run_simulation(cfg, profile=ResultProfile.FULL)
        market = result.markets["ABM"]
        assert market.l1_series is not None

        df = market.l1_series.as_dataframe()
        bid = pd.to_numeric(df["bid_price_cents"], errors="coerce") / 100
        ask = pd.to_numeric(df["ask_price_cents"], errors="coerce") / 100
        mid = (bid + ask) / 2
        spread = ask - bid

        # Filter to rows where both bid and ask are present
        valid_mid = mid.dropna()
        valid_spread = spread.dropna()

        # Spread must be non-negative where both sides are quoted
        assert (valid_spread >= 0).all()

        if len(valid_mid) > 1:
            log_ret = np.log(valid_mid / valid_mid.shift(1)).dropna()
            log_ret = log_ret.replace([np.inf, -np.inf], np.nan).dropna()
            if len(log_ret) > 0:
                vol = log_ret.std()
                assert np.isfinite(vol)

    def test_agent_analytics_fields(self):
        """Verify agent data has all fields needed for agent analytics tab."""
        cfg = _minimal_config(seed=42)
        result = run_simulation(cfg, profile=ResultProfile.FULL)
        assert len(result.agents) > 0
        for a in result.agents:
            assert hasattr(a, "agent_name")
            assert hasattr(a, "final_holdings")
            assert isinstance(a.final_holdings, dict)
            assert hasattr(a, "mark_to_market_cents")


# ── CLI entry point ───────────────────────────────────────────────────────────


class TestCLI:
    def test_cli_module_importable(self):
        from abides_ui._cli import main

        assert callable(main)
