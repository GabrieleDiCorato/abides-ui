"""Smoke tests for abides-ui.

These tests verify the core code paths without launching Streamlit:
  - Library registry discovery (agents, templates)
  - JSON Schema type resolution (including Pydantic v2 anyOf nullable)
  - SimulationConfig construction
  - End-to-end simulation run
  - CLI entry-point importability
"""

from __future__ import annotations

import pytest
from abides_markets.config_system import (
    AgentGroupConfig,
    ExchangeConfig,
    MarketConfig,
    SimulationConfig,
    SimulationMeta,
    SparseMeanRevertingOracleConfig,
    list_agent_types,
    list_templates,
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
        param_type = next((t for t in types if t != "null"), "string")
    else:
        raw_type = schema.get("type", "string")
        if isinstance(raw_type, list):
            nullable = "null" in raw_type
            param_type = next((t for t in raw_type if t != "null"), "string")
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
        pt, nullable = resolve_type({
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "default": None,
        })
        assert pt == "integer"
        assert nullable is True

    def test_anyof_non_nullable(self):
        pt, nullable = resolve_type({
            "anyOf": [{"type": "string"}],
        })
        assert pt == "string"
        assert nullable is False

    def test_no_type_defaults_to_string(self):
        pt, nullable = resolve_type({})
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


# ── CLI entry point ───────────────────────────────────────────────────────────

class TestCLI:
    def test_cli_module_importable(self):
        from abides_ui._cli import main
        assert callable(main)
