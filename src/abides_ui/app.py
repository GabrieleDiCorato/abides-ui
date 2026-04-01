from __future__ import annotations

import json
import time
from importlib.metadata import version as _pkg_version
from itertools import groupby as _groupby
from typing import Any

import pandas as pd
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

from abides_ui import charts, metrics

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

    # ── Import from JSON ──────────────────────────────────────────────────────
    with st.expander("📂 Import from JSON", expanded=False):
        uploaded_file = st.file_uploader(
            "Upload config file",
            type=["json"],
            key="_config_upload",
            help="Upload a previously exported ABIDES config JSON file.",
        )
        pasted_json = st.text_area(
            "Or paste JSON config",
            height=120,
            key="_config_paste",
            help="Paste a full ABIDES simulation config JSON.",
        )

        if st.button("📥 Load Config", key="_load_config_btn"):
            raw_json: str | None = None
            if uploaded_file is not None:
                raw_json = uploaded_file.read().decode("utf-8")
            elif pasted_json.strip():
                raw_json = pasted_json.strip()

            if raw_json:
                try:
                    imported = json.loads(raw_json)
                    if not isinstance(imported, dict):
                        st.error("Invalid config: expected a JSON object.")
                    elif "market" not in imported and "agents" not in imported:
                        st.error("Invalid config: must contain 'market' or 'agents' keys.")
                    else:
                        st.session_state["_imported_config"] = imported
                        # Clear widget states so the imported values apply
                        for k in list(st.session_state):
                            if k.startswith(("enabled_", "count_", "param_")):
                                del st.session_state[k]
                        st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
            else:
                st.warning("Upload a file or paste JSON first.")

    # Show active import indicator
    _imported_cfg: dict[str, Any] | None = st.session_state.get("_imported_config")
    if _imported_cfg is not None:
        st.success("✅ Using imported config")
        if st.button("✖ Clear import", key="_clear_import_btn"):
            del st.session_state["_imported_config"]
            for k in list(st.session_state):
                if k.startswith(("enabled_", "count_", "param_")):
                    del st.session_state[k]
            st.rerun()

    # Load template defaults when selected (imported config takes priority)
    if _imported_cfg is not None:
        tpl_market = _imported_cfg.get("market", {})
        _raw_oracle = tpl_market.get("oracle")
        tpl_oracle = _raw_oracle if isinstance(_raw_oracle, dict) else {}
        tpl_agents = _imported_cfg.get("agents", {})
        tpl_sim = _imported_cfg.get("simulation", {})
    elif selected_template != "None":
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

    # Reset agent widget states when template changes so new defaults apply
    _source_key = json.dumps(_imported_cfg, sort_keys=True) if _imported_cfg else selected_template
    if st.session_state.get("_prev_template") != _source_key:
        st.session_state["_prev_template"] = _source_key
        for k in list(st.session_state):
            if k.startswith(("enabled_", "count_", "param_")):
                del st.session_state[k]
        st.rerun()

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

    # ── Result profile ────────────────────────────────────────────────────────
    include_raw_logs = st.toggle(
        "Include raw agent logs",
        value=False,
        help="Enable to include per-agent order logs (slower). Needed for Order Flow tab.",
    )

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
        mean_reversion_half_life = st.text_input(
            "Mean-reversion half-life",
            value=tpl_oracle.get("mean_reversion_half_life", "48d"),
            help="Duration string (e.g. '48d', '1152h'). Time for the fundamental price to revert halfway to r_bar.",
        )

        with st.expander("Megashock parameters"):
            megashock_mean_interval = st.text_input(
                "Mean interval between shocks",
                value=tpl_oracle.get("megashock_mean_interval", "100000h") or "",
                help="Duration string (e.g. '100000h' ≈ 11.4 years). Leave empty to disable megashocks.",
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

    st.divider()
    _hasufel_version = _pkg_version("abides-hasufel")
    st.caption(f"Powered by [abides-hasufel v{_hasufel_version}](https://github.com/GabrieleDiCorato/abides-hasufel)")

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
    "order_rate_window",
}

# Collect agent configs from UI
agent_configs: dict[str, AgentGroupConfig] = {}

# Group agents by category and sort categories by importance (sort_order)
_sorted_agents = sorted(
    agent_types,
    key=lambda a: category_meta.get(a["category"], {}).get("sort_order", 99),
)
_grouped_agents: list[tuple[str, list[dict[str, Any]]]] = [(cat, list(grp)) for cat, grp in _groupby(_sorted_agents, key=lambda a: a["category"])]

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

        # Read live widget state for the expander label badge
        _live_enabled = st.session_state.get(f"enabled_{agent_name}", tpl_enabled)
        _live_count = st.session_state.get(f"count_{agent_name}", max(tpl_count, 1))
        _badge = f" · ✅ ×{_live_count}" if _live_enabled else ""

        with col, st.expander(f"**{agent_name}**{_badge}", expanded=tpl_enabled):
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

            count_default = max(tpl_count, 1)
            if typical_count and tpl_count == 0:
                count_default = typical_count[0]
            # Number input for precise agent count selection
            _count_max = (typical_count[1] * 3) if typical_count else 1000
            _count_max = max(_count_max, count_default * 3, 10)
            count = st.number_input(
                "Count",
                min_value=1,
                max_value=_count_max,
                value=count_default,
                step=1,
                key=f"count_{agent_name}",
                label_visibility="collapsed",
                help=f"Typical range: {typical_count[0]}–{typical_count[1]}" if typical_count else None,
            )

            # Render per-agent parameter inputs in a collapsible section
            agent_params: dict[str, Any] = {}
            visible_params = {k: v for k, v in param_schema.items() if k not in HIDDEN_PARAMS}

            if visible_params:
                with st.expander("⚙️ Parameters", expanded=False):
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

                        elif param_type == "array":
                            arr_default = ", ".join(str(v) for v in default) if isinstance(default, list) else (str(default) if default is not None else "")
                            raw = val_col.text_input(
                                display_label,
                                value=arr_default,
                                key=widget_key,
                                label_visibility="collapsed",
                                help="Comma-separated values" + (f" — {field_help}" if field_help else ""),
                            )
                            if raw.strip():
                                items_schema = schema.get("items", {})
                                item_type = items_schema.get("type", "string")
                                try:
                                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                                    if item_type == "number":
                                        agent_params[param_name] = [float(p) for p in parts]
                                    elif item_type == "integer":
                                        agent_params[param_name] = [int(p) for p in parts]
                                    else:
                                        agent_params[param_name] = parts
                                except ValueError:
                                    agent_params[param_name] = raw
                            elif not nullable:
                                agent_params[param_name] = []

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

            if enabled:
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
            mean_reversion_half_life=mean_reversion_half_life,
            fund_vol=fund_vol,
            megashock_mean_interval=megashock_mean_interval if megashock_mean_interval.strip() else None,
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
        _profile = ResultProfile.FULL if include_raw_logs else ResultProfile.QUANT
        result: SimulationResult = run_simulation(config, profile=_profile)
        wall_time = time.perf_counter() - t0
    st.session_state["result"] = result
    st.session_state["wall_time"] = wall_time
    st.session_state["ticker"] = ticker
    st.session_state["config_json"] = config.model_dump_json(indent=2)

# ── Display results ───────────────────────────────────────────────────────────

result: SimulationResult | None = st.session_state.get("result")

if result is None:
    st.info("Configure agents above and click **Run Simulation** to start.")
    st.stop()

ticker_key = st.session_state["ticker"]
wall_time: float = st.session_state["wall_time"]
market = result.markets[ticker_key]

# ── Pre-compute derived data ──────────────────────────────────────────────────

l1: metrics.L1Derived | None = None
if market.l1_series is not None:
    l1 = metrics.derive_l1(market.l1_series.as_dataframe())

order_df = metrics.extract_order_log(result)

# ── Summary header ────────────────────────────────────────────────────────────

st.subheader("Results")

summary = result.summary_dict()
sm = metrics.compute_summary(market, l1)

m_cols = st.columns(7)
m_cols[0].metric("Mid Price", f"${sm.mid_close:,.2f}" if sm.mid_close is not None else "N/A", help="Midpoint of the best bid and ask at market close: (Bid + Ask) / 2.")
m_cols[1].metric(
    "Bid-Ask Spread", f"${sm.spread_close:,.2f}" if sm.spread_close is not None else "N/A", help="Difference between the best ask and best bid at close. Tighter spreads indicate higher liquidity."
)
m_cols[2].metric(
    "VWAP", f"${sm.vwap:,.2f}" if sm.vwap is not None else "N/A", help="Volume-Weighted Average Price: Σ(price × qty) / Σ(qty) across all executed trades. Represents the average price paid per share."
)
m_cols[3].metric("Volume", f"{sm.volume:,}", help="Total number of shares exchanged during the simulation (sum of all executed order quantities).")
m_cols[4].metric(
    "Realized Vol (σ)", f"{sm.realized_vol:.6f}" if sm.realized_vol is not None else "N/A", help="Standard deviation of log-returns of the mid-price series. Measures intra-session price volatility."
)
m_cols[5].metric(
    "Price Range", f"${sm.price_range:,.2f}" if sm.price_range is not None else "N/A", help="Difference between the highest and lowest mid-price observed during the session (High − Low)."
)
m_cols[6].metric("Wall-clock", f"{wall_time:.1f}s", help="Real-world elapsed time to run the simulation.")

summary_warnings = summary.get("warnings", [])
if summary_warnings:
    with st.expander(f"⚠️ Simulation warnings ({len(summary_warnings)})"):
        for w in summary_warnings:
            st.warning(w)

# ── Tabbed analytics ─────────────────────────────────────────────────────────

tab_overview, tab_micro, tab_flow, tab_agents, tab_exec, tab_config = st.tabs(
    ["📊 Market Overview", "🔬 Microstructure", "📋 Order Flow", "👥 Agent Analytics", "⚡ Execution Analytics", "📄 Config Log"]
)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: MARKET OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════

with tab_overview:
    if l1 is not None:
        st.plotly_chart(charts.price_series(l1.time, l1.bid, l1.ask, l1.mid), width="stretch")

        _mean = l1.spread.mean()
        avg_spread = float(_mean) if pd.notna(_mean) else 0.0
        st.plotly_chart(charts.spread_over_time(l1.time, l1.spread, avg_spread), width="stretch")

        with st.expander("Raw L1 data"):
            st.dataframe(l1.l1_df, width="stretch")
    else:
        st.warning("L1 price series not available.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: MICROSTRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

with tab_micro:
    if l1 is not None:
        # ── Spread statistics ─────────────────────────────────────────────
        st.markdown("#### Spread Statistics")
        ss = metrics.compute_spread_stats(l1.spread, l1.mid)

        sp_cols = st.columns(6)
        sp_cols[0].metric("Mean Spread", f"${ss.mean:.4f}" if ss.mean is not None else "N/A", help="Average bid-ask spread over two-sided L1 snapshots. Lower values indicate tighter markets.")
        sp_cols[1].metric("Median Spread", f"${ss.median:.4f}" if ss.median is not None else "N/A", help="Median bid-ask spread. Less sensitive to outlier spikes than the mean.")
        sp_cols[2].metric("Max Spread", f"${ss.max:.4f}" if ss.max is not None else "N/A", help="Widest bid-ask spread observed. Large values may indicate liquidity gaps or stressed conditions.")
        sp_cols[3].metric("Spread Std", f"${ss.std:.4f}" if ss.std is not None else "N/A", help="Standard deviation of the spread series. Measures how stable or volatile the spread is over time.")
        sp_cols[4].metric(
            "Mean Spread %",
            f"{ss.mean_pct:.4f}%" if ss.mean_pct is not None else "N/A",
            help="Average spread as a percentage of mid-price: (Ask − Bid) / Mid × 100. Normalizes spread relative to price level.",
        )
        sp_cols[5].metric(
            "Median Spread %", f"{ss.median_pct:.4f}%" if ss.median_pct is not None else "N/A", help="Median spread as a percentage of mid-price. Robust measure of relative transaction cost."
        )
        if ss.n_one_sided > 0:
            st.caption(
                f"⚠️ {ss.n_one_sided} of {ss.n_total} L1 ticks ({ss.n_one_sided / ss.n_total * 100:.1f}%) had a one-sided book (no bid or no ask). Spread statistics above reflect only two-sided intervals."
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
        rv = metrics.compute_rolling_vol(l1.log_returns)
        if rv is not None:
            st.markdown("#### Realized Volatility")
            rolling_vol_series, window = rv
            ret_time = l1.time.iloc[l1.log_returns.index]
            st.plotly_chart(charts.rolling_volatility(ret_time, rolling_vol_series, window), width="stretch")

        # ── Book pressure ─────────────────────────────────────────────────
        st.markdown("#### Book Pressure")
        pressure = metrics.compute_book_pressure(l1.l1_df)
        st.plotly_chart(charts.book_pressure(l1.time, pressure), width="stretch")

        # ── Returns distribution ──────────────────────────────────────────
        rs = metrics.compute_return_stats(l1.log_returns)
        if rs is not None:
            st.markdown("#### Mid-Price Returns Distribution")
            ret_cols = st.columns(4)
            ret_cols[0].metric("Mean Return", f"{rs.mean:.8f}")
            ret_cols[1].metric("Std Dev", f"{rs.std:.6f}")
            ret_cols[2].metric("Skewness", f"{rs.skewness:.4f}")
            ret_cols[3].metric("Excess Kurtosis", f"{rs.kurtosis:.4f}")
            st.plotly_chart(charts.returns_histogram(l1.log_returns), width="stretch")

    # ── Trade attribution (outside L1 guard — uses market.trades) ─────
    if market.trades is not None and len(market.trades) > 0:
        st.divider()
        st.markdown("#### Trade Attribution")
        attr_df = metrics.build_trade_attribution_df(market.trades, result.agents)
        mts = metrics.compute_maker_taker_summary(attr_df)

        ta_cols = st.columns(3)
        ta_cols[0].metric("Total Trades", f"{mts.total_trades:,}", help="Number of individual trade executions with causal attribution.")
        maker_types = len(mts.maker_volume_by_type)
        taker_types = len(mts.taker_volume_by_type)
        ta_cols[1].metric("Maker Types", f"{maker_types}", help="Number of distinct agent types acting as passive (maker) side.")
        ta_cols[2].metric("Taker Types", f"{taker_types}", help="Number of distinct agent types acting as aggressive (taker) side.")

        st.plotly_chart(charts.maker_taker_volume(mts.maker_volume_by_type, mts.taker_volume_by_type), width="stretch")
        st.plotly_chart(charts.trade_price_scatter(attr_df), width="stretch")

        with st.expander("Raw trade attribution data"):
            st.dataframe(attr_df, width="stretch")

    if l1 is None and (market.trades is None or len(market.trades) == 0):
        st.warning("L1 series data is required for microstructure analysis.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: ORDER FLOW
# ══════════════════════════════════════════════════════════════════════════════

with tab_flow:
    if order_df is not None and len(order_df) > 0:
        # ── Summary metrics ───────────────────────────────────────────────
        st.markdown("#### Order Flow Summary")
        ofs = metrics.compute_order_flow_stats(order_df)

        of_cols = st.columns(5)
        of_cols[0].metric("Total Orders Submitted", f"{ofs.total_submitted:,}", help="Number of ORDER_SUBMITTED events. Each represents a new order entering the book.")
        of_cols[1].metric("Executions", f"{ofs.executed:,}", help="Number of ORDER_EXECUTED events (full or partial fills). Each represents a trade.")
        of_cols[2].metric("Cancellations", f"{ofs.cancelled:,}", help="Number of cancelled or partially cancelled orders that were removed before execution.")
        of_cols[3].metric("Fill Rate", f"{ofs.fill_rate:.1f}%", help="Executions / Submitted × 100. Measures what fraction of orders resulted in a trade.")
        of_cols[4].metric("Cancel Rate", f"{ofs.cancel_rate:.1f}%", help="Cancellations / Submitted × 100. High cancel rates are typical of market-making strategies.")

        st.divider()

        # ── Order type breakdown ──────────────────────────────────────────
        if "EventType" in order_df.columns:
            st.markdown("#### Event Type Breakdown")
            event_counts = order_df["EventType"].value_counts()

            c1, c2 = st.columns([1, 1])
            with c1:
                st.plotly_chart(charts.event_type_pie(event_counts), width="stretch")
            with c2:
                if "side" in order_df.columns:
                    submitted = order_df[order_df["EventType"] == "ORDER_SUBMITTED"]
                    side_counts = submitted["side"].value_counts()
                    st.plotly_chart(charts.side_balance(side_counts), width="stretch")

        # ── Cumulative order flow imbalance ───────────────────────────────
        imb_df = metrics.compute_cumulative_imbalance(order_df)
        if imb_df is not None:
            st.markdown("#### Cumulative Order Flow Imbalance")
            flow_time = pd.to_datetime(imb_df["EventTime"], unit="ns")
            st.plotly_chart(charts.cumulative_imbalance(flow_time, imb_df["cum_imbalance"]), width="stretch")

        # ── Volume by agent type ──────────────────────────────────────────
        if "agent_type" in order_df.columns:
            st.markdown("#### Activity by Agent Type")
            exec_df = order_df[order_df["EventType"] == "ORDER_EXECUTED"]
            if len(exec_df) > 0 and "quantity" in exec_df.columns:
                vol_by_type = exec_df.groupby("agent_type")["quantity"].sum().sort_values(ascending=True)
                st.plotly_chart(charts.volume_by_agent_type(vol_by_type), width="stretch")

        with st.expander("Raw order logs"):
            st.dataframe(order_df, width="stretch")
    else:
        st.warning("Order log data not available. Enable **Include raw agent logs** in the sidebar to populate this tab.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4: AGENT ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_agents:
    if result.agents:
        agent_df = metrics.build_agent_dataframe(result)

        # ── Aggregate metrics ─────────────────────────────────────────────
        st.markdown("#### Performance by Agent Type")
        agg = metrics.compute_agent_performance(agent_df)
        st.dataframe(agg, width="stretch", hide_index=True)

        st.divider()

        # ── P&L distribution box plot ─────────────────────────────────────
        st.markdown("#### P&L Distribution by Type")
        st.plotly_chart(charts.pnl_box_plot(agent_df), width="stretch")

        # ── Holdings breakdown ────────────────────────────────────────────
        hold_agg = metrics.build_holdings_table(result)
        if hold_agg is not None:
            st.markdown("#### Holdings by Agent Type")
            st.dataframe(hold_agg, width="stretch", hide_index=True)

        # ── Agent leaderboard ─────────────────────────────────────────────
        st.markdown("#### Agent Leaderboard")
        st.dataframe(metrics.build_leaderboard(agent_df), width="stretch")
    else:
        st.info("No agent data available.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5: EXECUTION ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_exec:
    exec_agents = metrics.get_execution_agents(result)

    if exec_agents:
        exec_summary = metrics.compute_execution_summary(exec_agents)

        # ── Hero metrics row ──────────────────────────────────────────────
        st.markdown("#### Execution Quality Overview")
        if exec_summary is not None:
            ex_cols = st.columns(5)
            ex_cols[0].metric("Execution Agents", f"{len(exec_agents)}", help="Number of agents with execution analytics (POV, TWAP, VWAP).")
            ex_cols[1].metric("Total Filled", f"{exec_summary.total_filled:,} / {exec_summary.total_target:,}", help="Total shares filled vs target across all execution agents.")
            ex_cols[2].metric("Avg Fill Rate", f"{exec_summary.avg_fill_rate:.1f}%", help="Average fill rate across execution agents.")
            ex_cols[3].metric("Avg VWAP Slippage", f"{exec_summary.avg_vwap_slippage_bps:.2f} bps", help="Average slippage relative to market VWAP, in basis points. Negative means better than VWAP.")
            if exec_summary.max_drawdown_cents is not None:
                ex_cols[4].metric("Max Drawdown", f"${exec_summary.max_drawdown_cents / 100:,.2f}", help="Largest peak-to-trough NAV decline across all execution agents.")
            else:
                ex_cols[4].metric("Max Drawdown", "N/A", help="No equity curve data available.")

        st.divider()

        # ── Per-agent detail sections ─────────────────────────────────────
        for agent in exec_agents:
            with st.expander(f"**{agent.agent_name}** ({agent.agent_type})", expanded=len(exec_agents) <= 3):
                detail_df = metrics.build_execution_detail_df(agent)
                if len(detail_df) > 0:
                    st.dataframe(detail_df, width="stretch", hide_index=True)

                ec_df = metrics.build_equity_curve_df(agent)
                if ec_df is not None:
                    st.plotly_chart(charts.equity_curve(ec_df, agent.agent_name), width="stretch")
                else:
                    st.caption("No equity curve data for this agent.")

        # ── Comparative slippage chart ────────────────────────────────────
        if len(exec_agents) > 1:
            st.divider()
            st.markdown("#### Slippage Comparison")
            slip_data = [
                {
                    "name": a.agent_name,
                    "vwap_slippage_bps": a.execution_metrics.vwap_slippage_bps or 0.0,  # type: ignore[union-attr]
                }
                for a in exec_agents
            ]
            st.plotly_chart(charts.slippage_comparison(slip_data), width="stretch")
    else:
        st.info("No execution agents in this simulation. Add a POV, TWAP, or VWAP execution agent to see analytics.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6: CONFIG LOG
# ══════════════════════════════════════════════════════════════════════════════

with tab_config:
    config_json: str | None = st.session_state.get("config_json")
    if config_json:
        st.markdown("#### Simulation Configuration")
        st.caption("This is the exact configuration used to produce the results above.")

        config_dict = json.loads(config_json)

        # ── Structured overview ───────────────────────────────────────────────
        _cfg_market = config_dict.get("market", {})
        _cfg_oracle = _cfg_market.get("oracle")
        _cfg_agents = config_dict.get("agents", {})
        _cfg_sim = config_dict.get("simulation", {})

        # Market settings
        with st.expander("🏦 Market Settings", expanded=True):
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Ticker", _cfg_market.get("ticker", "—"))
            mc2.metric("Date", _cfg_market.get("date", "—"))
            mc3.metric("Open", _cfg_market.get("start_time", "—"))
            mc4.metric("Close", _cfg_market.get("end_time", "—"))
            if _cfg_market.get("opening_price") is not None:
                st.metric("Opening Price", f"${_cfg_market['opening_price'] / 100:,.2f}")

        # Oracle settings
        with st.expander("🔮 Oracle Settings", expanded=True):
            if _cfg_oracle and isinstance(_cfg_oracle, dict):
                oc = st.columns(3)
                r_bar = _cfg_oracle.get("r_bar")
                if r_bar is not None:
                    oc[0].metric("r̄ (fundamental)", f"${r_bar / 100:,.2f}")
                fund_vol_cfg = _cfg_oracle.get("fund_vol")
                if fund_vol_cfg is not None:
                    oc[1].metric("Fundamental vol", f"{fund_vol_cfg:.1e}")
                hl = _cfg_oracle.get("mean_reversion_half_life")
                if hl is not None:
                    oc[2].metric("Half-life", str(hl))
                # Megashock params
                ms_interval = _cfg_oracle.get("megashock_mean_interval")
                if ms_interval:
                    ms_cols = st.columns(3)
                    ms_cols[0].metric("Megashock interval", str(ms_interval))
                    ms_mean = _cfg_oracle.get("megashock_mean")
                    if ms_mean is not None:
                        ms_cols[1].metric("Megashock mean", f"{ms_mean:,.0f}")
                    ms_var = _cfg_oracle.get("megashock_var")
                    if ms_var is not None:
                        ms_cols[2].metric("Megashock var", f"{ms_var:,.0f}")
            else:
                st.info("No oracle (LOB-only mode)")

        # Agent composition
        with st.expander("👥 Agent Composition", expanded=True):
            _agent_rows = []
            for aname, acfg in _cfg_agents.items():
                if isinstance(acfg, dict) and acfg.get("enabled", False):
                    _agent_rows.append({
                        "Agent": aname,
                        "Count": acfg.get("count", 0),
                        "Parameters": ", ".join(f"{k}={v}" for k, v in acfg.get("params", {}).items()) or "defaults",
                    })
            if _agent_rows:
                st.dataframe(
                    pd.DataFrame(_agent_rows),
                    use_container_width=True,
                    hide_index=True,
                )
                _total_agents = sum(r["Count"] for r in _agent_rows)
                st.caption(f"**Total: {_total_agents} agents** (+ 1 Exchange)")
            else:
                st.info("No agents configured.")

        # Simulation metadata
        if _cfg_sim:
            with st.expander("⚙️ Simulation Metadata", expanded=False):
                for k, v in _cfg_sim.items():
                    st.text(f"{k}: {v}")

        st.divider()

        # Download + raw JSON toggle
        dl_col, _ = st.columns([1, 3])
        with dl_col:
            st.download_button(
                "⬇️ Download config.json",
                data=config_json,
                file_name="abides_config.json",
                mime="application/json",
            )

        with st.expander("📝 Raw JSON", expanded=False):
            st.code(config_json, language="json")
    else:
        st.info("No configuration recorded.")
