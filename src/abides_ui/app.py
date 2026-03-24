from __future__ import annotations

import time
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
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

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="ABIDES Market Simulator", page_icon="📈", layout="wide")
st.title("📈 ABIDES Market Simulator")

# ── Load registry metadata (cached) ──────────────────────────────────────────


@st.cache_data
def load_agent_types() -> list[dict[str, Any]]:
    return list_agent_types()


@st.cache_data
def load_templates() -> list[dict[str, Any]]:
    return list_templates()


@st.cache_data
def load_template_config(name: str) -> dict[str, Any]:
    return get_template(name)


agent_types = load_agent_types()
templates = load_templates()

# ── Sidebar: template + market + oracle ───────────────────────────────────────

with st.sidebar:
    st.header("Simulation Configuration")

    # Template selector
    base_templates = [t for t in templates if not t["is_overlay"]]
    template_options = ["None"] + [t["name"] for t in base_templates]
    template_descriptions = {"None": "Start from scratch with defaults"}
    for t in base_templates:
        template_descriptions[t["name"]] = t["description"]

    selected_template = st.selectbox(
        "Template",
        template_options,
        index=0,
        help="Load a preset configuration from the library.",
    )
    if selected_template != "None":
        st.caption(template_descriptions[selected_template])

    # Load template defaults when selected
    if selected_template != "None":
        tpl = load_template_config(selected_template)
        tpl_market = tpl.get("market", {})
        tpl_oracle = tpl_market.get("oracle", {})
        tpl_agents = tpl.get("agents", {})
        tpl_sim = tpl.get("simulation", {})
    else:
        tpl_market = {}
        tpl_oracle = {}
        tpl_agents = {}
        tpl_sim = {}

    st.divider()

    # ── Market settings ───────────────────────────────────────────────────────
    st.subheader("Market")
    ticker = st.text_input("Ticker", value=tpl_market.get("ticker", "ABM"))
    sim_date = st.date_input("Date", value=pd.to_datetime(tpl_market.get("date", "20210205"), format="%Y%m%d"))
    col_t1, col_t2 = st.columns(2)
    start_time = col_t1.time_input("Open", value=pd.Timestamp(tpl_market.get("start_time", "09:30:00")).time())
    end_time = col_t2.time_input("Close", value=pd.Timestamp(tpl_market.get("end_time", "10:00:00")).time())

    seed_default = tpl_sim.get("seed", 42)
    if seed_default == "random":
        seed_default = 42
    seed = st.number_input("Random seed", min_value=0, value=seed_default, step=1)

    st.divider()

    # ── Oracle settings ───────────────────────────────────────────────────────
    st.subheader("Oracle (Mean-Reverting)")
    r_bar_cents_default = tpl_oracle.get("r_bar", 100_000)
    r_bar_dollars = st.number_input(
        "Mean fundamental price ($)",
        min_value=0.01,
        value=r_bar_cents_default / 100,
        step=10.0,
        format="%.2f",
    )
    fund_vol = st.number_input(
        "Fundamental volatility",
        min_value=0.0,
        value=tpl_oracle.get("fund_vol", 5e-5),
        step=1e-5,
        format="%.1e",
    )
    kappa_oracle = st.number_input(
        "Mean-reversion speed (κ)",
        min_value=0.0,
        value=tpl_oracle.get("kappa", 1.67e-16),
        step=1e-17,
        format="%.2e",
    )

    with st.expander("Megashock parameters"):
        megashock_lambda_a = st.number_input(
            "Arrival rate (λ)",
            min_value=0.0,
            value=tpl_oracle.get("megashock_lambda_a", 2.77778e-18),
            step=1e-19,
            format="%.5e",
        )
        megashock_mean = st.number_input(
            "Mean",
            min_value=0.0,
            value=float(tpl_oracle.get("megashock_mean", 1000)),
            step=100.0,
        )
        megashock_var = st.number_input(
            "Variance",
            min_value=0.0,
            value=float(tpl_oracle.get("megashock_var", 50_000)),
            step=1000.0,
        )

# ── Main area: agent boxes ───────────────────────────────────────────────────

st.subheader("Agent Composition")
st.caption("Enable agent types, set counts, and configure parameters. Agents are loaded dynamically from the library registry.")

# Common fields to hide from per-agent params (handled globally or not useful in UI)
HIDDEN_PARAMS = {"starting_cash", "log_orders", "computation_delay"}

# Collect agent configs from UI
agent_configs: dict[str, AgentGroupConfig] = {}

cols_per_row = 2
agent_cols = st.columns(cols_per_row)

for idx, agent_info in enumerate(agent_types):
    agent_name: str = agent_info["name"]
    category: str = agent_info["category"]
    description: str = agent_info["description"]
    param_schema: dict[str, Any] = agent_info["parameters"]

    # Template defaults for this agent
    tpl_agent = tpl_agents.get(agent_name, {})
    tpl_enabled = tpl_agent.get("enabled", False) if tpl_agents else False
    tpl_count = tpl_agent.get("count", 0)
    tpl_params = tpl_agent.get("params", {})

    col = agent_cols[idx % cols_per_row]

    with col:
        with st.expander(f"**{agent_name}**  `{category}`", expanded=tpl_enabled):
            st.caption(description)

            enabled = st.toggle("Enabled", value=tpl_enabled, key=f"enabled_{agent_name}")

            if enabled:
                count = st.number_input(
                    "Count",
                    min_value=1,
                    value=max(tpl_count, 1),
                    step=1,
                    key=f"count_{agent_name}",
                )

                # Render per-agent parameter inputs
                agent_params: dict[str, Any] = {}
                visible_params = {k: v for k, v in param_schema.items() if k not in HIDDEN_PARAMS}

                if visible_params:
                    for param_name, schema in visible_params.items():
                        default = tpl_params.get(param_name, schema.get("default"))

                        # Resolve type and nullability from JSON Schema
                        # Pydantic v2 uses anyOf: [{type: X}, {type: "null"}] for Optional
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

                        widget_key = f"param_{agent_name}_{param_name}"

                        if param_type == "boolean":
                            val = st.checkbox(
                                param_name,
                                value=bool(default) if default is not None else True,
                                key=widget_key,
                            )
                            agent_params[param_name] = val

                        elif param_type == "integer":
                            if nullable:
                                raw = st.text_input(
                                    param_name,
                                    value=str(default) if default is not None else "",
                                    key=widget_key,
                                    help="Leave empty for default (None)",
                                )
                                if raw.strip():
                                    agent_params[param_name] = int(raw)
                            else:
                                try:
                                    int_default = int(default) if default is not None else 0
                                except (ValueError, TypeError):
                                    int_default = 0
                                val = st.number_input(
                                    param_name,
                                    value=int_default,
                                    step=1,
                                    key=widget_key,
                                )
                                agent_params[param_name] = val

                        elif param_type == "number":
                            if nullable:
                                raw = st.text_input(
                                    param_name,
                                    value=str(default) if default is not None else "",
                                    key=widget_key,
                                    help="Leave empty for default (None)",
                                )
                                if raw.strip():
                                    agent_params[param_name] = float(raw)
                            else:
                                float_default = float(default) if default is not None else 0.0
                                # Use scientific format for very small numbers
                                fmt = "%.2e" if abs(float_default) < 0.01 and float_default != 0 else "%.4f"
                                val = st.number_input(
                                    param_name,
                                    value=float_default,
                                    format=fmt,
                                    key=widget_key,
                                )
                                agent_params[param_name] = val

                        elif param_type == "string":
                            str_default = str(default) if default is not None else ""
                            val = st.text_input(
                                param_name,
                                value=str_default,
                                key=widget_key,
                            )
                            if val or not nullable:
                                agent_params[param_name] = val

                        else:
                            # Fallback: text input
                            str_default = str(default) if default is not None else ""
                            val = st.text_input(
                                param_name,
                                value=str_default,
                                key=widget_key,
                            )
                            if val or not nullable:
                                agent_params[param_name] = val

                agent_configs[agent_name] = AgentGroupConfig(
                    enabled=True,
                    count=count,
                    params=agent_params,
                )

# Total agent count
total = sum(cfg.count for cfg in agent_configs.values())
st.caption(f"**Total agents: {total}** (+ 1 Exchange)")

# ── Run button ────────────────────────────────────────────────────────────────

st.divider()
run_clicked = st.button("🚀 Run Simulation", type="primary", use_container_width=True)


def build_config() -> SimulationConfig:
    return SimulationConfig(
        market=MarketConfig(
            ticker=ticker,
            date=sim_date.strftime("%Y%m%d"),
            start_time=start_time.strftime("%H:%M:%S"),
            end_time=end_time.strftime("%H:%M:%S"),
            oracle=SparseMeanRevertingOracleConfig(
                r_bar=int(r_bar_dollars * 100),
                kappa=kappa_oracle,
                fund_vol=fund_vol,
                megashock_lambda_a=megashock_lambda_a,
                megashock_mean=megashock_mean,
                megashock_var=megashock_var,
            ),
            exchange=ExchangeConfig(book_logging=True, book_log_depth=10),
        ),
        agents=agent_configs,
        simulation=SimulationMeta(seed=seed),
    )


if run_clicked:
    if not agent_configs:
        st.error("Enable at least one agent type before running.")
        st.stop()

    config = build_config()
    with st.spinner("Running simulation…"):
        t0 = time.perf_counter()
        result: SimulationResult = run_simulation(config, profile=ResultProfile.SUMMARY | ResultProfile.L1_SERIES)
        wall_time = time.perf_counter() - t0
    st.session_state["result"] = result
    st.session_state["wall_time"] = wall_time
    st.session_state["ticker"] = ticker

# ── Display results ───────────────────────────────────────────────────────────

result: SimulationResult | None = st.session_state.get("result")

if result is None:
    st.info("Configure agents above and click **Run Simulation** to start.")
    st.stop()

ticker_key = st.session_state["ticker"]
wall_time: float = st.session_state["wall_time"]
market = result.markets[ticker_key]

# Summary metrics
st.subheader("Summary")
metric_cols = st.columns(5)

bid = market.l1_close.bid_price_cents
ask = market.l1_close.ask_price_cents
mid = ((bid + ask) / 2 / 100) if bid is not None and ask is not None else None
spread = ((ask - bid) / 100) if bid is not None and ask is not None else None
vwap = market.liquidity.vwap_cents / 100 if market.liquidity.vwap_cents is not None else None
volume = market.liquidity.total_exchanged_volume

metric_cols[0].metric("Mid Price", f"${mid:,.2f}" if mid is not None else "N/A")
metric_cols[1].metric("Bid-Ask Spread", f"${spread:,.2f}" if spread is not None else "N/A")
metric_cols[2].metric("VWAP", f"${vwap:,.2f}" if vwap is not None else "N/A")
metric_cols[3].metric("Volume", f"{volume:,}")
metric_cols[4].metric("Wall-clock time", f"{wall_time:.1f}s")

# Price chart
st.subheader("Price Series")

if market.l1_series is not None:
    df = market.l1_series.as_dataframe()
    time_col = pd.to_datetime(df["time_ns"], unit="ns")

    bid_series = pd.to_numeric(df["bid_price_cents"], errors="coerce") / 100
    ask_series = pd.to_numeric(df["ask_price_cents"], errors="coerce") / 100
    mid_series = (bid_series + ask_series) / 2

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=time_col, y=bid_series, mode="lines", name="Best Bid", line={"color": "#2ca02c"}))
    fig.add_trace(go.Scatter(x=time_col, y=ask_series, mode="lines", name="Best Ask", line={"color": "#d62728"}))
    fig.add_trace(go.Scatter(x=time_col, y=mid_series, mode="lines", name="Mid Price", line={"color": "#1f77b4", "width": 2}))

    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Price ($)",
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 60, "r": 20, "t": 40, "b": 40},
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Raw L1 data"):
        st.dataframe(df, use_container_width=True)
else:
    st.warning("L1 price series not available.")

# Agent P&L summary
if result.agents:
    st.subheader("Agent P&L Summary")
    agent_rows = [
        {
            "ID": a.agent_id,
            "Type": a.agent_type,
            "Starting Cash ($)": a.starting_cash_cents / 100,
            "Mark-to-Market ($)": a.mark_to_market_cents / 100,
            "P&L ($)": a.pnl_cents / 100,
            "P&L (%)": round(a.pnl_pct, 4),
        }
        for a in result.agents
    ]
    agent_df = pd.DataFrame(agent_rows)

    agg = (
        agent_df.groupby("Type")
        .agg(
            Count=("ID", "count"),
            **{"Avg P&L ($)": ("P&L ($)", "mean")},
            **{"Total P&L ($)": ("P&L ($)", "sum")},
            **{"Avg P&L (%)": ("P&L (%)", "mean")},
        )
        .reset_index()
    )
    st.dataframe(agg, use_container_width=True, hide_index=True)

    with st.expander("Per-agent details"):
        st.dataframe(agent_df, use_container_width=True, hide_index=True)
