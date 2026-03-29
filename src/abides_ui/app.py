from __future__ import annotations

import time
from itertools import groupby as _groupby
from typing import Any

import numpy as np
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
    get_full_manifest,
    list_agent_types,
    list_templates,
    validate_config,
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


@st.cache_data
def load_manifest() -> dict[str, Any]:
    return get_full_manifest()


agent_types = load_agent_types()
templates = load_templates()
manifest = load_manifest()

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
    st.subheader("Oracle")

    # Build oracle option labels from manifest
    oracle_options_meta = manifest.get("oracle_options", [])
    oracle_type_labels: dict[str, str] = {}
    for opt in oracle_options_meta:
        key = opt.get("type")
        if key == "sparse_mean_reverting":
            oracle_type_labels["sparse_mean_reverting"] = "Sparse Mean-Reverting"
        elif key is None:
            oracle_type_labels["none"] = "No Oracle (LOB-only)"

    oracle_choices = list(oracle_type_labels.keys())

    tpl_oracle_type = "sparse_mean_reverting"
    if tpl_oracle == {} and tpl_market.get("oracle") is None and tpl_market.get("opening_price") is not None:
        tpl_oracle_type = "none"

    oracle_selection = st.selectbox(
        "Oracle type",
        oracle_choices,
        index=oracle_choices.index(tpl_oracle_type) if tpl_oracle_type in oracle_choices else 0,
        format_func=lambda x: oracle_type_labels.get(x, x),
        help="Oracle provides fundamental price dynamics. 'No Oracle' mode requires an explicit opening price.",
    )

    if oracle_selection == "none":
        opening_price_default = tpl_market.get("opening_price", 100_000)
        if opening_price_default is None:
            opening_price_default = 100_000
        opening_price_dollars = st.number_input(
            "Opening price ($)",
            min_value=0.01,
            value=opening_price_default / 100,
            step=10.0,
            format="%.2f",
            help="Seed price for the exchange when no oracle is used. Required in oracle-absent mode.",
        )
    else:
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

# Category descriptions from manifest
category_meta = manifest.get("categories", {})

# Common fields to hide from per-agent params (handled globally or not useful in UI)
HIDDEN_PARAMS = {
    "starting_cash",
    "log_orders",
    "computation_delay",
    "position_limit",
    "position_limit_clamp",
    "max_drawdown",
    "max_order_rate",
    "order_rate_window_ns",
}

# Collect agent configs from UI
agent_configs: dict[str, AgentGroupConfig] = {}

# Group agents by category and sort categories by importance (sort_order)
_sorted_agents = sorted(
    agent_types,
    key=lambda a: category_meta.get(a["category"], {}).get("sort_order", 99),
)
_grouped_agents: list[tuple[str, list[dict[str, Any]]]] = [
    (cat, list(grp))
    for cat, grp in _groupby(_sorted_agents, key=lambda a: a["category"])
]

for cat_key, cat_agents in _grouped_agents:
    cat_info = category_meta.get(cat_key, {})
    cat_label = cat_info.get("label", cat_key)
    cat_desc = cat_info.get("description", "")
    st.markdown(f"##### {cat_label}")
    if cat_desc:
        st.caption(cat_desc)

    cols_per_row = 2
    agent_cols = st.columns(cols_per_row)

    for idx, agent_info in enumerate(cat_agents):
        agent_name: str = agent_info["name"]
        category: str = agent_info["category"]
        description: str = agent_info["description"]
        param_schema: dict[str, Any] = agent_info["parameters"]
        requires_oracle: bool = agent_info.get("requires_oracle", False)
        typical_count: list[int] | None = agent_info.get("typical_count_range")
        recommended_with: list[str] = agent_info.get("recommended_with", [])

        # Template defaults for this agent
        tpl_agent = tpl_agents.get(agent_name, {})
        tpl_enabled = tpl_agent.get("enabled", False) if tpl_agents else False
        tpl_count = tpl_agent.get("count", 0)
        tpl_params = tpl_agent.get("params", {})

        col = agent_cols[idx % cols_per_row]

        with col, st.expander(f"**{agent_name}**", expanded=tpl_enabled):
            st.caption(description)

            # Show metadata badges
            badges: list[str] = []
            if requires_oracle:
                badges.append("🔮 Requires oracle")
            if typical_count:
                badges.append(f"📊 Typical: {typical_count[0]}–{typical_count[1]}")
            if recommended_with:
                badges.append(f"🤝 {', '.join(recommended_with)}")
            if badges:
                st.markdown(" · ".join(badges))

            # Warn if oracle-dependent agent is used without oracle
            if requires_oracle and oracle_selection == "none":
                st.warning("⚠️ This agent requires an oracle.")

            enabled = st.toggle("Enabled", value=tpl_enabled, key=f"enabled_{agent_name}")

            if enabled:
                count_default = max(tpl_count, 1)
                if typical_count and tpl_count == 0:
                    count_default = typical_count[0]
                count = st.number_input(
                    "Count",
                    min_value=1,
                    value=count_default,
                    step=1,
                    key=f"count_{agent_name}",
                    label_visibility="collapsed",
                    help=f"Typical range: {typical_count[0]}–{typical_count[1]}" if typical_count else None,
                )

                # Render per-agent parameter inputs in compact table layout
                agent_params: dict[str, Any] = {}
                visible_params = {k: v for k, v in param_schema.items() if k not in HIDDEN_PARAMS}

                if visible_params:
                    for param_name, schema in visible_params.items():
                        default = tpl_params.get(param_name, schema.get("default"))

                        # Extract rich metadata from schema
                        field_desc = schema.get("description")
                        field_unit = (schema.get("json_schema_extra") or {}).get("unit")
                        if field_unit and field_desc:
                            field_help = f"{field_desc} (unit: {field_unit})"
                        elif field_desc:
                            field_help = field_desc
                        else:
                            field_help = None

                        # Build display label with unit hint
                        display_label = param_name
                        if field_unit:
                            display_label = f"{param_name} ({field_unit})"

                        # Resolve type and nullability from JSON Schema
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

                        widget_key = f"param_{agent_name}_{param_name}"

                        # Compact row: label on left, widget on right
                        lbl_col, val_col = st.columns([2, 3])
                        lbl_col.markdown(
                            f"<div style='line-height:2.4rem;font-size:0.85rem' title='{field_help or ''}'>{display_label}</div>",
                            unsafe_allow_html=True,
                        )

                        if param_type == "boolean":
                            val = val_col.checkbox(
                                display_label,
                                value=bool(default) if default is not None else True,
                                key=widget_key,
                                label_visibility="collapsed",
                            )
                            agent_params[param_name] = val

                        elif param_type == "integer":
                            if nullable:
                                raw = val_col.text_input(
                                    display_label,
                                    value=str(default) if default is not None else "",
                                    key=widget_key,
                                    label_visibility="collapsed",
                                )
                                if raw.strip():
                                    agent_params[param_name] = int(raw)
                            else:
                                try:
                                    int_default = int(default) if default is not None else 0
                                except (ValueError, TypeError):
                                    int_default = 0
                                val = val_col.number_input(
                                    display_label,
                                    value=int_default,
                                    step=1,
                                    key=widget_key,
                                    label_visibility="collapsed",
                                )
                                agent_params[param_name] = val

                        elif param_type == "number":
                            if nullable:
                                raw = val_col.text_input(
                                    display_label,
                                    value=str(default) if default is not None else "",
                                    key=widget_key,
                                    label_visibility="collapsed",
                                )
                                if raw.strip():
                                    agent_params[param_name] = float(raw)
                            else:
                                float_default = float(default) if default is not None else 0.0
                                fmt = "%.2e" if abs(float_default) < 0.01 and float_default != 0 else "%.4f"
                                val = val_col.number_input(
                                    display_label,
                                    value=float_default,
                                    format=fmt,
                                    key=widget_key,
                                    label_visibility="collapsed",
                                )
                                agent_params[param_name] = val

                        elif param_type == "string":
                            str_default = str(default) if default is not None else ""
                            val = val_col.text_input(
                                display_label,
                                value=str_default,
                                key=widget_key,
                                label_visibility="collapsed",
                            )
                            if val or not nullable:
                                agent_params[param_name] = val

                        else:
                            str_default = str(default) if default is not None else ""
                            val = val_col.text_input(
                                display_label,
                                value=str_default,
                                key=widget_key,
                                label_visibility="collapsed",
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
run_clicked = st.button("🚀 Run Simulation", type="primary", width="stretch")


def build_config() -> SimulationConfig:
    if oracle_selection == "none":
        oracle_cfg = None
        opening_price_cents = int(opening_price_dollars * 100)
    else:
        oracle_cfg = SparseMeanRevertingOracleConfig(
            r_bar=int(r_bar_dollars * 100),
            kappa=kappa_oracle,
            fund_vol=fund_vol,
            megashock_lambda_a=megashock_lambda_a,
            megashock_mean=megashock_mean,
            megashock_var=megashock_var,
        )
        opening_price_cents = None

    return SimulationConfig(
        market=MarketConfig(
            ticker=ticker,
            date=sim_date.strftime("%Y%m%d"),
            start_time=start_time.strftime("%H:%M:%S"),
            end_time=end_time.strftime("%H:%M:%S"),
            oracle=oracle_cfg,
            opening_price=opening_price_cents,
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

    # Structured validation before running
    validation = validate_config(config.model_dump())
    if not validation.valid:
        for issue in validation.errors:
            msg = issue.message
            if issue.suggestion:
                msg += f"\n\n💡 **Suggestion:** {issue.suggestion}"
            st.error(msg)
        st.stop()
    for issue in validation.warnings:
        msg = issue.message
        if issue.suggestion:
            msg += f" — 💡 {issue.suggestion}"
        st.warning(msg)

    with st.spinner("Running simulation…"):
        t0 = time.perf_counter()
        result: SimulationResult = run_simulation(config, profile=ResultProfile.FULL)
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

# ── Pre-compute derived series from L1 ────────────────────────────────────────

l1_df: pd.DataFrame | None = None
bid_series: pd.Series | None = None
ask_series: pd.Series | None = None
mid_series: pd.Series | None = None
spread_series: pd.Series | None = None
log_returns: pd.Series | None = None
time_col: pd.Series | None = None

if market.l1_series is not None:
    l1_df = market.l1_series.as_dataframe()
    time_col = pd.to_datetime(l1_df["time_ns"], unit="ns")
    bid_series = pd.to_numeric(l1_df["bid_price_cents"], errors="coerce") / 100
    ask_series = pd.to_numeric(l1_df["ask_price_cents"], errors="coerce") / 100
    mid_series = (bid_series + ask_series) / 2
    spread_series = ask_series - bid_series
    ratio = mid_series / mid_series.shift(1)
    ratio = ratio[(ratio > 0) & ratio.notna()]
    log_returns = np.log(ratio)
    log_returns = log_returns.replace([np.inf, -np.inf], np.nan).dropna()

# ── Pre-compute order log data ────────────────────────────────────────────────

order_df: pd.DataFrame | None = None
try:
    order_df = result.order_logs()
    if order_df is not None and len(order_df) == 0:
        order_df = None
    if order_df is not None and "side" in order_df.columns:
        order_df["side"] = order_df["side"].astype(str)
except Exception:
    order_df = None

# ── Summary header ────────────────────────────────────────────────────────────

st.subheader("Results")

# Use structured summary from v2.2.0
summary = result.summary_dict()
summary_market = summary.get("markets", {}).get(ticker_key, {})

bid = market.l1_close.bid_price_cents
ask = market.l1_close.ask_price_cents
mid_close = ((bid + ask) / 2 / 100) if bid is not None and ask is not None else None
spread_close = ((ask - bid) / 100) if bid is not None and ask is not None else None
volume = market.liquidity.total_exchanged_volume

# VWAP from LiquidityMetrics (v2.2.0)
vwap_cents = market.liquidity.vwap_cents
vwap = vwap_cents / 100 if vwap_cents is not None else None

realized_vol = None
if log_returns is not None and len(log_returns) > 1:
    realized_vol = float(log_returns.std())

price_range = None
if mid_series is not None:
    valid_mid = mid_series.dropna()
    if len(valid_mid) > 0:
        price_range = float(valid_mid.max() - valid_mid.min())

m_cols = st.columns(7)
m_cols[0].metric("Mid Price", f"${mid_close:,.2f}" if mid_close is not None else "N/A", help="Midpoint of the best bid and ask at market close: (Bid + Ask) / 2.")
m_cols[1].metric(
    "Bid-Ask Spread", f"${spread_close:,.2f}" if spread_close is not None else "N/A", help="Difference between the best ask and best bid at close. Tighter spreads indicate higher liquidity."
)
m_cols[2].metric(
    "VWAP", f"${vwap:,.2f}" if vwap is not None else "N/A", help="Volume-Weighted Average Price: Σ(price × qty) / Σ(qty) across all executed trades. Represents the average price paid per share."
)
m_cols[3].metric("Volume", f"{volume:,}", help="Total number of shares exchanged during the simulation (sum of all executed order quantities).")
m_cols[4].metric(
    "Realized Vol (σ)", f"{realized_vol:.6f}" if realized_vol is not None else "N/A", help="Standard deviation of log-returns of the mid-price series. Measures intra-session price volatility."
)
m_cols[5].metric("Price Range", f"${price_range:,.2f}" if price_range is not None else "N/A", help="Difference between the highest and lowest mid-price observed during the session (High − Low).")
m_cols[6].metric("Wall-clock", f"{wall_time:.1f}s", help="Real-world elapsed time to run the simulation.")

# Show summary warnings from the simulation result
summary_warnings = summary.get("warnings", [])
if summary_warnings:
    with st.expander(f"⚠️ Simulation warnings ({len(summary_warnings)})"):
        for w in summary_warnings:
            st.warning(w)

# ── Tabbed analytics ─────────────────────────────────────────────────────────

tab_overview, tab_micro, tab_flow, tab_agents = st.tabs(["📊 Market Overview", "🔬 Microstructure", "📋 Order Flow", "👥 Agent Analytics"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: MARKET OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

with tab_overview:
    if l1_df is not None and time_col is not None:
        fig_price = go.Figure()
        fig_price.add_trace(
            go.Scatter(
                x=time_col,
                y=bid_series,
                mode="lines",
                name="Best Bid",
                line={"color": "#2ca02c", "width": 1},
            )
        )
        fig_price.add_trace(
            go.Scatter(
                x=time_col,
                y=ask_series,
                mode="lines",
                name="Best Ask",
                line={"color": "#d62728", "width": 1},
            )
        )
        fig_price.add_trace(
            go.Scatter(
                x=time_col,
                y=mid_series,
                mode="lines",
                name="Mid Price",
                line={"color": "#1f77b4", "width": 2},
            )
        )
        fig_price.update_layout(
            title="Price Series (Bid / Ask / Mid)",
            xaxis_title="Time",
            yaxis_title="Price ($)",
            hovermode="x unified",
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
            margin={"l": 60, "r": 20, "t": 60, "b": 40},
            height=450,
        )
        st.plotly_chart(fig_price, width="stretch")

        if spread_series is not None:
            fig_spread = go.Figure()
            fig_spread.add_trace(
                go.Scatter(
                    x=time_col,
                    y=spread_series,
                    mode="lines",
                    name="Spread",
                    fill="tozeroy",
                    line={"color": "#ff7f0e", "width": 1},
                    fillcolor="rgba(255, 127, 14, 0.2)",
                )
            )
            _mean = spread_series.mean()
            avg_spread = float(_mean) if pd.notna(_mean) else 0.0
            fig_spread.add_hline(y=avg_spread, line_dash="dash", line_color="gray", annotation_text=f"Mean: ${avg_spread:.4f}")
            fig_spread.update_layout(
                title="Bid-Ask Spread Over Time",
                xaxis_title="Time",
                yaxis_title="Spread ($)",
                hovermode="x unified",
                height=300,
                margin={"l": 60, "r": 20, "t": 60, "b": 40},
            )
            st.plotly_chart(fig_spread, width="stretch")

        with st.expander("Raw L1 data"):
            st.dataframe(l1_df, width="stretch")
    else:
        st.warning("L1 price series not available.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: MICROSTRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

with tab_micro:
    if l1_df is not None and spread_series is not None and mid_series is not None:
        # ── Spread statistics ─────────────────────────────────────────────
        st.markdown("#### Spread Statistics")
        valid_spread = spread_series.dropna()
        valid_mid_ms = mid_series.dropna()
        spread_pct = (valid_spread / valid_mid_ms * 100).dropna() if len(valid_mid_ms) > 0 else pd.Series(dtype=float)

        sp_cols = st.columns(6)
        sp_cols[0].metric("Mean Spread", f"${valid_spread.mean():.4f}" if len(valid_spread) > 0 else "N/A", help="Average bid-ask spread over all L1 snapshots. Lower values indicate tighter markets.")
        sp_cols[1].metric("Median Spread", f"${valid_spread.median():.4f}" if len(valid_spread) > 0 else "N/A", help="Median bid-ask spread. Less sensitive to outlier spikes than the mean.")
        sp_cols[2].metric(
            "Max Spread", f"${valid_spread.max():.4f}" if len(valid_spread) > 0 else "N/A", help="Widest bid-ask spread observed. Large values may indicate liquidity gaps or stressed conditions."
        )
        sp_cols[3].metric(
            "Spread Std", f"${valid_spread.std():.4f}" if len(valid_spread) > 1 else "N/A", help="Standard deviation of the spread series. Measures how stable or volatile the spread is over time."
        )
        sp_cols[4].metric(
            "Mean Spread %",
            f"{spread_pct.mean():.4f}%" if len(spread_pct) > 0 else "N/A",
            help="Average spread as a percentage of mid-price: (Ask − Bid) / Mid × 100. Normalizes spread relative to price level.",
        )
        sp_cols[5].metric(
            "Median Spread %", f"{spread_pct.median():.4f}%" if len(spread_pct) > 0 else "N/A", help="Median spread as a percentage of mid-price. Robust measure of relative transaction cost."
        )

        # ── Market quality ────────────────────────────────────────────────
        st.markdown("#### Market Quality")
        mq_cols = st.columns(4)
        mq_cols[0].metric("% Time No Bid", f"{market.liquidity.pct_time_no_bid:.1f}%", help="Percentage of session time with no bid quote in the book. High values signal poor buy-side liquidity.")
        mq_cols[1].metric("% Time No Ask", f"{market.liquidity.pct_time_no_ask:.1f}%", help="Percentage of session time with no ask quote in the book. High values signal poor sell-side liquidity.")
        both_sides = 100 - max(market.liquidity.pct_time_no_bid, market.liquidity.pct_time_no_ask)
        mq_cols[2].metric("% Time Two-Sided", f"{both_sides:.1f}%", help="Percentage of session time where both a bid and an ask were present. Higher is better — indicates a tradeable market.")
        last_trade = market.liquidity.last_trade_cents
        mq_cols[3].metric("Last Trade", f"${last_trade / 100:.2f}" if last_trade is not None else "N/A", help="Price of the last executed trade in the session.")

        st.divider()

        # ── Rolling volatility ────────────────────────────────────────────
        if log_returns is not None and len(log_returns) > 10:
            st.markdown("#### Realized Volatility")

            window = min(100, len(log_returns) // 3) if len(log_returns) > 30 else max(5, len(log_returns) // 3)
            rolling_vol = log_returns.rolling(window=window).std()

            fig_vol = go.Figure()
            ret_time = time_col.iloc[log_returns.index]
            fig_vol.add_trace(
                go.Scatter(
                    x=ret_time,
                    y=rolling_vol,
                    mode="lines",
                    name=f"Rolling σ ({window}-tick)",
                    line={"color": "#9467bd", "width": 1.5},
                )
            )
            fig_vol.update_layout(
                title=f"Rolling Realized Volatility ({window}-tick window)",
                xaxis_title="Time",
                yaxis_title="σ (log returns)",
                hovermode="x unified",
                height=350,
                margin={"l": 60, "r": 20, "t": 60, "b": 40},
            )
            st.plotly_chart(fig_vol, width="stretch")

        # ── Book pressure ─────────────────────────────────────────────────
        st.markdown("#### Book Pressure")
        bid_qty = pd.to_numeric(l1_df["bid_qty"], errors="coerce")
        ask_qty = pd.to_numeric(l1_df["ask_qty"], errors="coerce")
        pressure = bid_qty - ask_qty

        fig_pressure = go.Figure()
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in pressure.fillna(0)]
        fig_pressure.add_trace(
            go.Bar(
                x=time_col,
                y=pressure,
                name="Bid − Ask Qty",
                marker_color=colors,
            )
        )
        fig_pressure.update_layout(
            title="Order Book Pressure (Bid Qty − Ask Qty)",
            xaxis_title="Time",
            yaxis_title="Qty Imbalance",
            hovermode="x unified",
            height=350,
            margin={"l": 60, "r": 20, "t": 60, "b": 40},
        )
        st.plotly_chart(fig_pressure, width="stretch")

        # ── Returns distribution ──────────────────────────────────────────
        if log_returns is not None and len(log_returns) > 5:
            st.markdown("#### Mid-Price Returns Distribution")

            ret_cols = st.columns(4)
            ret_cols[0].metric("Mean Return", f"{log_returns.mean():.8f}")
            ret_cols[1].metric("Std Dev", f"{log_returns.std():.6f}")
            skew_val = float(log_returns.skew()) if len(log_returns) > 2 else 0.0
            kurt_val = float(log_returns.kurtosis()) if len(log_returns) > 3 else 0.0
            ret_cols[2].metric("Skewness", f"{skew_val:.4f}")
            ret_cols[3].metric("Excess Kurtosis", f"{kurt_val:.4f}")

            fig_hist = go.Figure()
            fig_hist.add_trace(
                go.Histogram(
                    x=log_returns,
                    nbinsx=50,
                    name="Log Returns",
                    marker_color="#1f77b4",
                    opacity=0.7,
                )
            )
            fig_hist.update_layout(
                title="Distribution of Log Returns (Mid-Price)",
                xaxis_title="Log Return",
                yaxis_title="Frequency",
                height=350,
                margin={"l": 60, "r": 20, "t": 60, "b": 40},
            )
            st.plotly_chart(fig_hist, width="stretch")
    else:
        st.warning("L1 series data is required for microstructure analysis.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: ORDER FLOW
# ══════════════════════════════════════════════════════════════════════════════

with tab_flow:
    if order_df is not None and len(order_df) > 0:
        # ── Summary metrics ───────────────────────────────────────────────
        st.markdown("#### Order Flow Summary")

        total_orders = len(order_df[order_df["EventType"] == "ORDER_SUBMITTED"]) if "EventType" in order_df.columns else 0
        executed = len(order_df[order_df["EventType"] == "ORDER_EXECUTED"]) if "EventType" in order_df.columns else 0
        cancelled = len(order_df[order_df["EventType"].isin(["ORDER_CANCELLED", "PARTIAL_CANCELLED"])]) if "EventType" in order_df.columns else 0

        fill_rate = (executed / total_orders * 100) if total_orders > 0 else 0
        cancel_rate = (cancelled / total_orders * 100) if total_orders > 0 else 0

        of_cols = st.columns(5)
        of_cols[0].metric("Total Orders Submitted", f"{total_orders:,}", help="Number of ORDER_SUBMITTED events. Each represents a new order entering the book.")
        of_cols[1].metric("Executions", f"{executed:,}", help="Number of ORDER_EXECUTED events (full or partial fills). Each represents a trade.")
        of_cols[2].metric("Cancellations", f"{cancelled:,}", help="Number of cancelled or partially cancelled orders that were removed before execution.")
        of_cols[3].metric("Fill Rate", f"{fill_rate:.1f}%", help="Executions / Submitted × 100. Measures what fraction of orders resulted in a trade.")
        of_cols[4].metric("Cancel Rate", f"{cancel_rate:.1f}%", help="Cancellations / Submitted × 100. High cancel rates are typical of market-making strategies.")

        st.divider()

        # ── Order type breakdown ──────────────────────────────────────────
        if "EventType" in order_df.columns:
            st.markdown("#### Event Type Breakdown")
            event_counts = order_df["EventType"].value_counts()

            c1, c2 = st.columns([1, 1])
            with c1:
                fig_events = go.Figure(
                    data=[
                        go.Pie(
                            labels=event_counts.index.tolist(),
                            values=event_counts.values.tolist(),
                            hole=0.4,
                        )
                    ]
                )
                fig_events.update_layout(
                    title="Order Event Types",
                    height=350,
                    margin={"l": 20, "r": 20, "t": 60, "b": 20},
                )
                st.plotly_chart(fig_events, width="stretch")

            with c2:
                if "side" in order_df.columns:
                    submitted = order_df[order_df["EventType"] == "ORDER_SUBMITTED"]
                    side_counts = submitted["side"].value_counts()
                    fig_sides = go.Figure(
                        data=[
                            go.Bar(
                                x=side_counts.index.tolist(),
                                y=side_counts.values.tolist(),
                                marker_color=["#2ca02c" if "BID" in s else "#d62728" for s in side_counts.index],
                            )
                        ]
                    )
                    fig_sides.update_layout(
                        title="Order Side Balance (Submitted)",
                        xaxis_title="Side",
                        yaxis_title="Count",
                        height=350,
                        margin={"l": 60, "r": 20, "t": 60, "b": 40},
                    )
                    st.plotly_chart(fig_sides, width="stretch")

        # ── Cumulative order flow imbalance ───────────────────────────────
        if "side" in order_df.columns and "EventTime" in order_df.columns:
            st.markdown("#### Cumulative Order Flow Imbalance")
            submitted = order_df[order_df["EventType"] == "ORDER_SUBMITTED"].copy()
            if len(submitted) > 0:
                submitted = submitted.sort_values("EventTime")
                submitted["flow_sign"] = submitted["side"].apply(lambda s: 1 if "BID" in s else (-1 if "ASK" in s else 0)).astype(int)
                submitted["cum_imbalance"] = submitted["flow_sign"].cumsum()
                flow_time = pd.to_datetime(submitted["EventTime"], unit="ns")

                fig_flow = go.Figure()
                fig_flow.add_trace(
                    go.Scatter(
                        x=flow_time,
                        y=submitted["cum_imbalance"],
                        mode="lines",
                        name="Cumulative Imbalance",
                        line={"color": "#17becf", "width": 1.5},
                        fill="tozeroy",
                        fillcolor="rgba(23, 190, 207, 0.15)",
                    )
                )
                fig_flow.add_hline(y=0, line_dash="dash", line_color="gray")
                fig_flow.update_layout(
                    title="Cumulative Order Flow Imbalance (Buy − Sell)",
                    xaxis_title="Time",
                    yaxis_title="Cumulative Imbalance",
                    hovermode="x unified",
                    height=350,
                    margin={"l": 60, "r": 20, "t": 60, "b": 40},
                )
                st.plotly_chart(fig_flow, width="stretch")

        # ── Volume by agent type ──────────────────────────────────────────
        if "agent_type" in order_df.columns:
            st.markdown("#### Activity by Agent Type")
            exec_df = order_df[order_df["EventType"] == "ORDER_EXECUTED"]
            if len(exec_df) > 0 and "quantity" in exec_df.columns:
                vol_by_type = exec_df.groupby("agent_type")["quantity"].sum().sort_values(ascending=True)
                fig_vol_type = go.Figure(
                    data=[
                        go.Bar(
                            x=vol_by_type.values.tolist(),
                            y=vol_by_type.index.tolist(),
                            orientation="h",
                            marker_color="#636efa",
                        )
                    ]
                )
                fig_vol_type.update_layout(
                    title="Executed Volume by Agent Type",
                    xaxis_title="Total Quantity Executed",
                    yaxis_title="Agent Type",
                    height=max(250, len(vol_by_type) * 50),
                    margin={"l": 150, "r": 20, "t": 60, "b": 40},
                )
                st.plotly_chart(fig_vol_type, width="stretch")

        with st.expander("Raw order logs"):
            st.dataframe(order_df, width="stretch")
    else:
        st.warning("Order log data not available. Ensure the simulation includes agent logs.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: AGENT ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_agents:
    if result.agents:
        agent_rows = [
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
        agent_df = pd.DataFrame(agent_rows)

        # ── Aggregate metrics ─────────────────────────────────────────────
        st.markdown("#### Performance by Agent Type")

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
        st.dataframe(agg, width="stretch", hide_index=True)

        st.divider()

        # ── P&L distribution box plot ─────────────────────────────────────
        st.markdown("#### P&L Distribution by Type")
        agent_type_list = sorted(agent_df["Type"].unique())
        fig_box = go.Figure()
        box_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]
        for i, atype in enumerate(agent_type_list):
            subset = agent_df[agent_df["Type"] == atype]["P&L ($)"]
            fig_box.add_trace(
                go.Box(
                    y=subset,
                    name=atype,
                    marker_color=box_colors[i % len(box_colors)],
                    boxmean="sd",
                )
            )
        fig_box.add_hline(y=0, line_dash="dash", line_color="gray")
        fig_box.update_layout(
            title="P&L Distribution by Agent Type",
            yaxis_title="P&L ($)",
            height=400,
            margin={"l": 60, "r": 20, "t": 60, "b": 40},
        )
        st.plotly_chart(fig_box, width="stretch")

        # ── Holdings breakdown ────────────────────────────────────────────
        holdings_data = []
        for a in result.agents:
            for asset, qty in a.final_holdings.items():
                if asset == "CASH":
                    continue
                holdings_data.append(
                    {
                        "Type": a.agent_type,
                        "Agent": a.agent_name,
                        "Asset": asset,
                        "Shares": qty,
                    }
                )
        if holdings_data:
            st.markdown("#### Holdings by Agent Type")
            hdf = pd.DataFrame(holdings_data)
            hold_agg = (
                hdf.groupby("Type")
                .agg(
                    **{"Total Shares": ("Shares", "sum")},
                    **{"Avg Shares": ("Shares", "mean")},
                    **{"Min Shares": ("Shares", "min")},
                    **{"Max Shares": ("Shares", "max")},
                )
                .reset_index()
            )
            st.dataframe(hold_agg, width="stretch", hide_index=True)

        # ── Agent leaderboard ─────────────────────────────────────────────
        st.markdown("#### Agent Leaderboard")
        leaderboard = agent_df.sort_values("P&L ($)", ascending=False).reset_index(drop=True)
        leaderboard.index = leaderboard.index + 1
        leaderboard.index.name = "Rank"
        st.dataframe(leaderboard, width="stretch")
    else:
        st.info("No agent data available.")
