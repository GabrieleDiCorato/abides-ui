from __future__ import annotations

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
from abides_ui.components import agent_recipe_bar, execution_console, metric_row
from abides_ui.theme import CARBON_DARK_CSS

# ── Page config & theme injection ─────────────────────────────────────────────

st.set_page_config(page_title="ABIDES Terminal", layout="wide")
st.markdown(f"<style>{CARBON_DARK_CSS}</style>", unsafe_allow_html=True)

_hasufel_version = _pkg_version("abides-hasufel")
st.markdown(
    '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">'
    "<span style=\"font-family:'JetBrains Mono',monospace;font-size:1.1rem;font-weight:700;color:#E0E0E0;letter-spacing:0.08em\">ABIDES TERMINAL</span>"
    f"<span style=\"font-family:'JetBrains Mono',monospace;font-size:0.6rem;background:rgba(0,112,255,0.15);color:#0070FF;padding:2px 8px;border-radius:4px;border:1px solid rgba(0,112,255,0.25)\">v{_hasufel_version}</span>"
    "</div>",
    unsafe_allow_html=True,
)

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
    st.markdown(
        "<div style=\"font-family:'JetBrains Mono',monospace;font-size:0.75rem;font-weight:600;color:#8A919B;letter-spacing:0.1em;margin-bottom:12px\">PREPARATION DESK</div>",
        unsafe_allow_html=True,
    )

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
        # Show scenario description & regime tags from template metadata
        _sel_tpl = next((t for t in base_templates if t["name"] == selected_template), None)
        if _sel_tpl:
            _scenario_desc = _sel_tpl.get("scenario_description", "")
            _regime_tags = _sel_tpl.get("regime_tags", [])
            if _scenario_desc:
                st.markdown(
                    f"<div style=\"font-family:'Inter',sans-serif;font-size:0.72rem;color:#6B7280;margin:4px 0 6px 0\">{_scenario_desc}</div>",
                    unsafe_allow_html=True,
                )
            if _regime_tags:
                _tags_html = " ".join(
                    f'<span style="font-size:0.62rem;background:rgba(0,112,255,0.12);color:#0070FF;padding:1px 6px;border-radius:3px;margin-right:3px">{tag}</span>' for tag in _regime_tags
                )
                st.markdown(_tags_html, unsafe_allow_html=True)

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

    # Reset agent widget states when template changes so new defaults apply
    if st.session_state.get("_prev_template") != selected_template:
        st.session_state["_prev_template"] = selected_template
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
    st.caption(f"[abides-hasufel v{_hasufel_version}](https://github.com/GabrieleDiCorato/abides-hasufel)")

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
            # Slider for fast range adjustment; max derived from typical range
            _slider_max = (typical_count[1] * 3) if typical_count else 500
            _slider_max = max(_slider_max, count_default * 3, 10)
            count = st.slider(
                "Count",
                min_value=1,
                max_value=_slider_max,
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

# Market Recipe bar
if agent_configs:
    st.markdown(agent_recipe_bar(agent_configs), unsafe_allow_html=True)

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
                msg += f"\n\n**Suggestion:** {issue.suggestion}"
            st.error(msg)
        st.stop()

    _sim_warnings: list[str] = []
    for issue in validation.warnings:
        msg = issue.message
        if issue.suggestion:
            msg += f" — {issue.suggestion}"
        _sim_warnings.append(msg)

    with st.status("Executing simulation...", expanded=True) as _status:
        st.markdown(
            "<div style=\"font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#00C805;opacity:0.8\">"
            "Compiling agent configuration...<br>"
            f"Agents: {total} + 1 Exchange | Seed: {seed}<br>"
            "Kernel boot sequence initiated..."
            "</div>",
            unsafe_allow_html=True,
        )
        t0 = time.perf_counter()
        _profile = ResultProfile.FULL if include_raw_logs else ResultProfile.QUANT
        result: SimulationResult = run_simulation(config, profile=_profile)
        wall_time = time.perf_counter() - t0
        _status.update(label=f"Simulation complete — {wall_time:.2f}s", state="complete", expanded=False)

    # Build execution console log
    _log_lines = [
        f"Seed: {seed}",
        f"Profile: {_profile.name}",
        f"Agents compiled: {total} + 1 Exchange",
        "Kernel started",
        "Simulation running...",
        f"Simulation finished in {wall_time:.2f}s",
    ]
    _log_lines.extend(f"[WARN] {w}" for w in _sim_warnings)
    _log_lines.append("Results ready.")
    st.markdown(execution_console(_log_lines, wall_time), unsafe_allow_html=True)

    st.session_state["result"] = result
    st.session_state["wall_time"] = wall_time
    st.session_state["ticker"] = ticker
    st.session_state["config_json"] = config.model_dump_json(indent=2)

# ── Display results ───────────────────────────────────────────────────────────

result: SimulationResult | None = st.session_state.get("result")

if result is None:
    st.markdown(
        "<div style=\"text-align:center;padding:60px 20px;color:#6B7280;font-family:'Inter',sans-serif\">"
        '<div style="font-size:2rem;margin-bottom:8px;opacity:0.3">⬡</div>'
        '<div style="font-size:0.85rem">Configure agents in the Preparation Desk and execute a simulation.</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

ticker_key = st.session_state["ticker"]
wall_time: float = st.session_state["wall_time"]
market = result.markets[ticker_key]

# ── Pre-compute derived data ──────────────────────────────────────────────────

l1: metrics.L1Derived | None = None
if market.l1_series is not None:
    l1 = metrics.derive_l1(market.l1_series.as_dataframe())

order_df = metrics.extract_order_log(result)

# ── Summary KPI cards ─────────────────────────────────────────────────────────

summary = result.summary_dict()
sm = metrics.compute_summary(market, l1)

st.markdown(
    metric_row(
        [
            {"label": "Mid Price", "value": f"${sm.mid_close:,.2f}" if sm.mid_close is not None else "N/A"},
            {"label": "Bid-Ask Spread", "value": f"${sm.spread_close:,.2f}" if sm.spread_close is not None else "N/A"},
            {"label": "VWAP", "value": f"${sm.vwap:,.2f}" if sm.vwap is not None else "N/A"},
            {"label": "Volume", "value": f"{sm.volume:,}"},
            {"label": "Realized Vol (σ)", "value": f"{sm.realized_vol:.6f}" if sm.realized_vol is not None else "N/A"},
            {"label": "Price Range", "value": f"${sm.price_range:,.2f}" if sm.price_range is not None else "N/A"},
            {"label": "Wall-Clock", "value": f"{wall_time:.1f}s"},
        ]
    ),
    unsafe_allow_html=True,
)

summary_warnings = summary.get("warnings", [])
if summary_warnings:
    with st.expander(f"⚠ Simulation warnings ({len(summary_warnings)})"):
        for w in summary_warnings:
            st.warning(w)

# ── Config Log in sidebar expander ────────────────────────────────────────────

with st.sidebar:
    config_json: str | None = st.session_state.get("config_json")
    if config_json:
        with st.expander("Config JSON"):
            st.code(config_json, language="json")
            st.download_button(
                "Download config.json",
                data=config_json,
                file_name="abides_config.json",
                mime="application/json",
            )

# ── Tabbed analytics — 3-tab institutional layout ────────────────────────────

tab_micro, tab_alpha, tab_book = st.tabs(["Market Microstructure", "Agent Alpha", "Order Book Dynamics"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: MARKET MICROSTRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

with tab_micro:
    if l1 is not None:
        # ── Price series (full width) ─────────────────────────────────────
        st.plotly_chart(charts.price_series(l1.time, l1.bid, l1.ask, l1.mid), use_container_width=True)

        # ── Spread + Rolling volatility (side by side) ────────────────────
        _mean = l1.spread.mean()
        avg_spread = float(_mean) if pd.notna(_mean) else 0.0
        rv = metrics.compute_rolling_vol(l1.log_returns)

        mc1, mc2 = st.columns(2)
        with mc1:
            st.plotly_chart(charts.spread_over_time(l1.time, l1.spread, avg_spread), use_container_width=True)
        with mc2:
            if rv is not None:
                rolling_vol_series, window = rv
                ret_time = l1.time.iloc[l1.log_returns.index]
                st.plotly_chart(charts.rolling_volatility(ret_time, rolling_vol_series, window), use_container_width=True)

        # ── Book pressure + Returns histogram (side by side) ──────────────
        pressure = metrics.compute_book_pressure(l1.l1_df)
        rs = metrics.compute_return_stats(l1.log_returns)

        mc3, mc4 = st.columns(2)
        with mc3:
            st.plotly_chart(charts.book_pressure(l1.time, pressure), use_container_width=True)
        with mc4:
            if rs is not None:
                st.plotly_chart(charts.returns_histogram(l1.log_returns), use_container_width=True)

        # ── Spread statistics cards ───────────────────────────────────────
        ss = metrics.compute_spread_stats(l1.spread, l1.mid)
        st.markdown(
            metric_row(
                [
                    {"label": "Mean Spread", "value": f"${ss.mean:.4f}" if ss.mean is not None else "N/A"},
                    {"label": "Median Spread", "value": f"${ss.median:.4f}" if ss.median is not None else "N/A"},
                    {"label": "Max Spread", "value": f"${ss.max:.4f}" if ss.max is not None else "N/A"},
                    {"label": "Spread Std", "value": f"${ss.std:.4f}" if ss.std is not None else "N/A"},
                    {"label": "Mean Spread %", "value": f"{ss.mean_pct:.4f}%" if ss.mean_pct is not None else "N/A"},
                    {"label": "Median Spread %", "value": f"{ss.median_pct:.4f}%" if ss.median_pct is not None else "N/A"},
                ]
            ),
            unsafe_allow_html=True,
        )
        if ss.n_one_sided > 0:
            st.caption(f"⚠ {ss.n_one_sided} of {ss.n_total} L1 ticks ({ss.n_one_sided / ss.n_total * 100:.1f}%) had a one-sided book.")

        # ── Market quality cards ──────────────────────────────────────────
        both_sides = 100 - max(market.liquidity.pct_time_no_bid, market.liquidity.pct_time_no_ask)
        last_trade = market.liquidity.last_trade_cents
        st.markdown(
            metric_row(
                [
                    {"label": "% Time No Bid", "value": f"{market.liquidity.pct_time_no_bid:.1f}%"},
                    {"label": "% Time No Ask", "value": f"{market.liquidity.pct_time_no_ask:.1f}%"},
                    {"label": "% Time Two-Sided", "value": f"{both_sides:.1f}%"},
                    {"label": "Last Trade", "value": f"${last_trade / 100:.2f}" if last_trade is not None else "N/A"},
                ]
            ),
            unsafe_allow_html=True,
        )

        # ── Returns distribution stats ────────────────────────────────────
        if rs is not None:
            st.markdown(
                metric_row(
                    [
                        {"label": "Mean Return", "value": f"{rs.mean:.8f}"},
                        {"label": "Std Dev", "value": f"{rs.std:.6f}"},
                        {"label": "Skewness", "value": f"{rs.skewness:.4f}"},
                        {"label": "Excess Kurtosis", "value": f"{rs.kurtosis:.4f}"},
                    ]
                ),
                unsafe_allow_html=True,
            )

        # ── Advanced microstructure metrics (v2.5.3 Tier 1-3) ────────────
        micro = metrics.compute_microstructure_metrics(result, ticker_key)
        if micro is not None:
            _micro_cards: list[dict[str, str]] = []
            if micro.mean_spread_cents is not None:
                _micro_cards.append({"label": "Mean Spread (¢)", "value": f"{micro.mean_spread_cents:.2f}"})
            if micro.volatility_ann is not None:
                _micro_cards.append({"label": "Ann. Volatility", "value": f"{micro.volatility_ann:.4f}"})
            if micro.sharpe_ratio is not None:
                _micro_cards.append({"label": "Sharpe Ratio", "value": f"{micro.sharpe_ratio:.2f}"})
            if micro.avg_bid_liquidity is not None:
                _micro_cards.append({"label": "Avg Bid Depth", "value": f"{micro.avg_bid_liquidity:,.0f}"})
            if micro.avg_ask_liquidity is not None:
                _micro_cards.append({"label": "Avg Ask Depth", "value": f"{micro.avg_ask_liquidity:,.0f}"})
            if micro.lob_imbalance_mean is not None:
                _micro_cards.append({"label": "LOB Imbalance μ", "value": f"{micro.lob_imbalance_mean:+.4f}"})
            if micro.lob_imbalance_std is not None:
                _micro_cards.append({"label": "LOB Imbalance σ", "value": f"{micro.lob_imbalance_std:.4f}"})
            if micro.vpin is not None:
                _micro_cards.append({"label": "VPIN", "value": f"{micro.vpin:.4f}"})
            if micro.resilience_ns is not None:
                _resil_ms = micro.resilience_ns / 1e6
                _micro_cards.append({"label": "Resilience (ms)", "value": f"{_resil_ms:,.1f}"})
            if _micro_cards:
                st.markdown(
                    "<div style=\"font-family:'Inter',sans-serif;font-size:0.72rem;color:#6B7280;margin:12px 0 4px 0;text-transform:uppercase;letter-spacing:0.06em\">Advanced Microstructure</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(metric_row(_micro_cards), unsafe_allow_html=True)

        with st.expander("Raw L1 data"):
            st.dataframe(l1.l1_df, use_container_width=True)
    else:
        st.warning("L1 price series not available.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: AGENT ALPHA
# ══════════════════════════════════════════════════════════════════════════════

with tab_alpha:
    if result.agents:
        agent_df = metrics.build_agent_dataframe(result)
        exec_agents = metrics.get_execution_agents(result)

        # ── Agent category breakdown ──────────────────────────────────────
        _cat_counts = agent_df["Category"].value_counts()
        if len(_cat_counts) > 0:
            _cat_cards = [
                {"label": cat.title(), "value": str(count)}
                for cat, count in _cat_counts.items()
                if cat  # skip empty category strings
            ]
            if _cat_cards:
                st.markdown(metric_row(_cat_cards), unsafe_allow_html=True)

        # ── Execution summary cards (if any exec agents) ─────────────────
        if exec_agents:
            exec_summary = metrics.compute_execution_summary(exec_agents)
            if exec_summary is not None:
                _dd = f"${exec_summary.max_drawdown_cents / 100:,.2f}" if exec_summary.max_drawdown_cents is not None else "N/A"
                st.markdown(
                    metric_row(
                        [
                            {"label": "Exec Agents", "value": f"{len(exec_agents)}"},
                            {"label": "Total Filled", "value": f"{exec_summary.total_filled:,} / {exec_summary.total_target:,}"},
                            {"label": "Avg Fill Rate", "value": f"{exec_summary.avg_fill_rate:.1f}%"},
                            {"label": "Avg VWAP Slippage", "value": f"{exec_summary.avg_vwap_slippage_bps:.2f} bps"},
                            {"label": "Max Drawdown", "value": _dd},
                        ]
                    ),
                    unsafe_allow_html=True,
                )

        # ── Performance table ─────────────────────────────────────────────
        agg = metrics.compute_agent_performance(agent_df)
        st.dataframe(agg, use_container_width=True, hide_index=True)

        # ── P&L box plot + equity curves (side by side) ───────────────────
        if exec_agents:
            aa1, aa2 = st.columns(2)
            with aa1:
                st.plotly_chart(charts.pnl_box_plot(agent_df), use_container_width=True)
            with aa2:
                # Show equity curve for the first execution agent
                for agent in exec_agents[:1]:
                    ec_df = metrics.build_equity_curve_df(agent)
                    if ec_df is not None:
                        st.plotly_chart(charts.equity_curve(ec_df, agent.agent_name), use_container_width=True)
                    else:
                        st.caption("No equity curve data.")
        else:
            st.plotly_chart(charts.pnl_box_plot(agent_df), use_container_width=True)

        # ── Holdings breakdown ────────────────────────────────────────────
        hold_agg = metrics.build_holdings_table(result)
        if hold_agg is not None:
            st.dataframe(hold_agg, use_container_width=True, hide_index=True)

        # ── Slippage comparison ───────────────────────────────────────────
        if len(exec_agents) > 1:
            slip_data = [
                {
                    "name": a.agent_name,
                    "vwap_slippage_bps": a.execution_metrics.vwap_slippage_bps or 0.0,  # type: ignore[union-attr]
                }
                for a in exec_agents
            ]
            st.plotly_chart(charts.slippage_comparison(slip_data), use_container_width=True)

        # ── Per-agent execution details ───────────────────────────────────
        if exec_agents:
            with st.expander(f"Execution agent details ({len(exec_agents)})"):
                for agent in exec_agents:
                    detail_df = metrics.build_execution_detail_df(agent)
                    if len(detail_df) > 0:
                        st.caption(f"**{agent.agent_name}** ({agent.agent_type})")
                        st.dataframe(detail_df, use_container_width=True, hide_index=True)
                    ec_df = metrics.build_equity_curve_df(agent)
                    if ec_df is not None:
                        st.plotly_chart(charts.equity_curve(ec_df, agent.agent_name), use_container_width=True)

        # ── Leaderboard ───────────────────────────────────────────────────
        with st.expander("Agent Leaderboard"):
            st.dataframe(metrics.build_leaderboard(agent_df), use_container_width=True)
    else:
        st.info("No agent data available.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: ORDER BOOK DYNAMICS
# ══════════════════════════════════════════════════════════════════════════════

with tab_book:
    _has_orders = order_df is not None and len(order_df) > 0
    _has_trades = market.trades is not None and len(market.trades) > 0

    if _has_orders:
        # ── Order flow KPI cards ──────────────────────────────────────────
        ofs = metrics.compute_order_flow_stats(order_df)
        st.markdown(
            metric_row(
                [
                    {"label": "Orders Submitted", "value": f"{ofs.total_submitted:,}"},
                    {"label": "Executions", "value": f"{ofs.executed:,}"},
                    {"label": "Cancellations", "value": f"{ofs.cancelled:,}"},
                    {"label": "Fill Rate", "value": f"{ofs.fill_rate:.1f}%"},
                    {"label": "Cancel Rate", "value": f"{ofs.cancel_rate:.1f}%"},
                ]
            ),
            unsafe_allow_html=True,
        )

        # ── Event type pie + Side balance (side by side) ──────────────────
        if "EventType" in order_df.columns:
            event_counts = order_df["EventType"].value_counts()
            ob1, ob2 = st.columns(2)
            with ob1:
                st.plotly_chart(charts.event_type_pie(event_counts), use_container_width=True)
            with ob2:
                if "side" in order_df.columns:
                    submitted = order_df[order_df["EventType"] == "ORDER_SUBMITTED"]
                    side_counts = submitted["side"].value_counts()
                    st.plotly_chart(charts.side_balance(side_counts), use_container_width=True)

        # ── Cumulative imbalance (full width) ─────────────────────────────
        imb_df = metrics.compute_cumulative_imbalance(order_df)
        if imb_df is not None:
            flow_time = pd.to_datetime(imb_df["EventTime"], unit="ns")
            st.plotly_chart(charts.cumulative_imbalance(flow_time, imb_df["cum_imbalance"]), use_container_width=True)

        # ── Volume by agent type ──────────────────────────────────────────
        if "agent_type" in order_df.columns:
            exec_df = order_df[order_df["EventType"] == "ORDER_EXECUTED"]
            if len(exec_df) > 0 and "quantity" in exec_df.columns:
                vol_by_type = exec_df.groupby("agent_type")["quantity"].sum().sort_values(ascending=True)
                st.plotly_chart(charts.volume_by_agent_type(vol_by_type), use_container_width=True)

        with st.expander("Raw order logs"):
            st.dataframe(order_df, use_container_width=True)

    # ── Trade attribution section ─────────────────────────────────────────
    if _has_trades:
        attr_df = metrics.build_trade_attribution_df(market.trades, result.agents)
        mts = metrics.compute_maker_taker_summary(attr_df)

        if not _has_orders:
            # Show trade KPIs at top if no order flow cards above
            st.markdown(
                metric_row(
                    [
                        {"label": "Total Trades", "value": f"{mts.total_trades:,}"},
                        {"label": "Maker Types", "value": f"{len(mts.maker_volume_by_type)}"},
                        {"label": "Taker Types", "value": f"{len(mts.taker_volume_by_type)}"},
                    ]
                ),
                unsafe_allow_html=True,
            )

        # ── Maker/taker volume + Trade price scatter (side by side) ───────
        ob3, ob4 = st.columns(2)
        with ob3:
            st.plotly_chart(charts.maker_taker_volume(mts.maker_volume_by_type, mts.taker_volume_by_type), use_container_width=True)
        with ob4:
            st.plotly_chart(charts.trade_price_scatter(attr_df), use_container_width=True)

        with st.expander("Raw trade attribution data"):
            st.dataframe(attr_df, use_container_width=True)

    if not _has_orders and not _has_trades:
        st.warning("Order log data not available. Enable **Include raw agent logs** in the sidebar to populate this tab.")
