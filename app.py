"""Futures Risk Modeler: Streamlit dashboard for risk and trade journaling.

Run with ``streamlit run app.py`` from the repository root.
"""
import os
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ── Run migration on startup (before anything reads data files) ────────────────
from modules.migration import run_all as _run_migration
_migration_result = _run_migration()

# ── Module imports ─────────────────────────────────────────────────────────────
from modules.instruments        import INSTRUMENTS
from modules.position_sizer     import calculate
from modules.pre_trade_checker  import check, PROCEED, WARN, REDUCE, BLOCK
from modules.prop_firm          import FirmConfig, compute as firm_compute
from modules.analytics          import core as analytics_core, by_field
from modules.journal             import (
    load, add, update as journal_update, remove, get_by_id,
    SESSIONS, EMOTIONS, GRADES,
    HTF_BIAS_OPTIONS, MARKET_COND_OPTIONS, VOLATILITY_OPTIONS,
    DIRECTION_OPTIONS, YN_OPTIONS, YNP_OPTIONS, YNA_OPTIONS,
)
from modules.setup_manager      import (
    get_setup_names, load_setups, add_setup, update_setup,
    archive_setup, restore_setup, delete_setup,
)
from modules.library_manager    import (
    get_mistake_names, get_mistakes, add_mistake, update_mistake,
    archive_mistake, restore_mistake, delete_mistake,
    get_confluence_names, get_confluences, add_confluence, update_confluence,
    archive_confluence, restore_confluence, delete_confluence,
)
from modules.media_manager      import (
    save_image, get_images, delete_image, delete_all_images_for_trade,
    find_orphaned_image_records, purge_orphaned_records, CATEGORIES,
)
from modules.daily_journal      import load as load_daily, save_day, get_day
from modules.validation         import validate_trade
from modules.tags               import serialize_tags, deserialize_tags

NOT_SET = "— Not set —"

# ─────────────────────────────────────────────────────────────────────────────
# Page config and CSS
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Futures Risk Modeler", page_icon="📊", layout="wide")

st.markdown("""
<style>
.banner-proceed{background:#0a2e1a;border:1px solid #1d7a45;border-radius:8px;
    padding:14px 18px;color:#4ade80;font-weight:700;font-size:1.15em;}
.banner-warn   {background:#2e1f00;border:1px solid #7a5500;border-radius:8px;
    padding:14px 18px;color:#fbbf24;font-weight:700;font-size:1.15em;}
.banner-reduce {background:#160e30;border:1px solid #5b3eb8;border-radius:8px;
    padding:14px 18px;color:#a78bfa;font-weight:700;font-size:1.15em;}
.banner-block  {background:#2e0808;border:1px solid #991b1b;border-radius:8px;
    padding:14px 18px;color:#f87171;font-weight:700;font-size:1.15em;}
.msg-block{border-left:3px solid #f87171;background:#1a0808;
    padding:6px 10px;margin:3px 0;border-radius:3px;font-size:.88em;color:#f87171;}
.msg-warn {border-left:3px solid #fbbf24;background:#1a1000;
    padding:6px 10px;margin:3px 0;border-radius:3px;font-size:.88em;color:#fbbf24;}
.trade-card{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:18px;}
.section-label{font-size:.75em;font-weight:600;color:#64748b;text-transform:uppercase;
    letter-spacing:.06em;margin-bottom:4px;}
.field-hint{font-size:.78em;color:#64748b;margin-top:-6px;margin-bottom:8px;}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — Global Config
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Settings")
    st.subheader("Account")
    account_size     = st.number_input("Account Size ($)", min_value=100.0, value=5_000.0, step=500.0)
    default_risk_pct = st.number_input("Default Risk (%)", min_value=0.1, max_value=5.0, value=0.5, step=0.1)
    default_instr    = st.selectbox("Default Instrument", list(INSTRUMENTS.keys()), key="sidebar_instr")
    st.divider()
    st.subheader("Risk Rules")
    max_trades_day = st.number_input("Max Trades / Day", min_value=0, max_value=30, value=3, help="0 = no limit enforced.")
    min_rr = st.number_input("Min R:R Ratio", min_value=0.5, max_value=10.0, value=1.5, step=0.1)
    st.divider()
    with st.expander("🏦 Prop Firm / Account Rules"):
        firm_name    = st.text_input("Firm Name", value="Custom")
        acct_type    = st.selectbox("Account Type", ["Evaluation", "Funded", "Personal"])
        start_bal    = st.number_input("Starting Balance ($)", min_value=0.0, value=50_000.0, step=1_000.0)
        profit_tgt   = st.number_input("Profit Target ($)", min_value=0.0, value=3_000.0, step=100.0)
        max_dd       = st.number_input("Max Drawdown ($)", min_value=0.0, value=2_500.0, step=100.0)
        daily_limit  = st.number_input("Daily Loss Limit ($)", min_value=0.0, value=1_000.0, step=50.0)
        dd_type      = st.radio("Drawdown Type", ["static", "trailing"], horizontal=True)
        curr_bal     = st.number_input("Current Balance ($)", min_value=0.0, value=start_bal, step=100.0)
        realized_pnl = st.number_input("Realized P/L ($)", value=0.0, step=10.0)
        hwm          = curr_bal
        if dd_type == "trailing":
            hwm = st.number_input("High Water Mark ($)", min_value=0.0, value=float(curr_bal), step=100.0)
        min_days   = st.number_input("Min Trading Days", min_value=0, max_value=90, value=0)
        cons_rule  = st.checkbox("Consistency Rule")
        cons_thresh = 0.40
        if cons_rule:
            cons_thresh = st.slider("Max single-day % of total profit", 10, 100, 40) / 100.0

    pf_config = FirmConfig(
        firm_name=firm_name, account_type=acct_type, starting_balance=start_bal,
        profit_target=profit_tgt, max_drawdown=max_dd, daily_loss_limit=daily_limit,
        drawdown_type=dd_type, min_trading_days=min_days,
        consistency_rule=cons_rule, consistency_threshold=cons_thresh,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Main tabs
# ─────────────────────────────────────────────────────────────────────────────
(tab_calc, tab_check, tab_journal,
 tab_analytics, tab_daily, tab_library) = st.tabs([
    "📐  Risk Calculator", "✅  Pre-Trade Check", "📓  Trade Journal",
    "📊  Analytics", "📅  Daily Journal", "📚  Library",
])

# ═══════════════════════════════════════════════════════════════════
# TAB 1 — Risk Calculator
# ═══════════════════════════════════════════════════════════════════
with tab_calc:
    st.header("Position Sizer")
    col_in, col_out = st.columns(2, gap="large")
    with col_in:
        st.subheader("Inputs")
        instr_key = st.selectbox("Instrument", list(INSTRUMENTS.keys()),
                                  index=list(INSTRUMENTS.keys()).index(default_instr), key="calc_instr")
        instr = INSTRUMENTS[instr_key]
        st.caption(f"**{instr['name']}** — tick: {instr['tick_size']} pts = ${instr['tick_value']:.2f} | "
                   f"point value: ${instr['point_value']:.2f} | margin ~${instr['margin_estimate']}")
        risk_pct   = st.number_input("Risk (%)", min_value=0.1, max_value=5.0, value=default_risk_pct, step=0.1, key="calc_risk")
        stop_ticks = st.number_input("Stop Loss (ticks)", min_value=1, max_value=500, value=6, key="calc_stop")
        comm       = st.number_input("Commission / side ($)", min_value=0.0, value=instr["default_commission"], step=0.05, key="calc_comm")
        slip       = st.number_input("Slippage (ticks)", min_value=0.0, max_value=5.0, value=0.5, step=0.25, key="calc_slip")
        st.session_state["_instr_key"]  = instr_key
        st.session_state["_stop_ticks"] = int(stop_ticks)
        st.session_state["_comm"]       = comm
        st.session_state["_risk_pct"]   = risk_pct
    with col_out:
        st.subheader("Result")
        size = calculate(account_size=account_size, risk_pct=risk_pct, instrument=instr,
                         stop_ticks=int(stop_ticks), commission_per_side=comm, slippage_ticks=slip)
        st.session_state["_cost_per_contr"] = size.cost_per_contract
        m1, m2 = st.columns(2)
        m1.metric("Dollar Risk",   f"${size.dollar_risk:.2f}", help=f"{risk_pct}% of ${account_size:,.0f}")
        m2.metric("Max Contracts", size.max_contracts)
        m3, m4 = st.columns(2)
        m3.metric("Stop Cost / Contract",  f"${size.stop_cost:.2f}")
        m4.metric("Friction / Contract",   f"${size.friction_cost:.2f}", help="2× commission + 2× slippage")
        st.metric("Total Cost / Contract", f"${size.cost_per_contract:.2f}")
        pts = int(stop_ticks) * instr["tick_size"]
        st.caption(f"{int(stop_ticks)} ticks = {pts:.2f} pts  |  Cost: ${size.stop_cost:.2f} stop + ${size.friction_cost:.2f} friction")
        for w in size.warnings:
            st.markdown(f'<div class="msg-warn">⚠️ {w}</div>', unsafe_allow_html=True)
    st.divider()
    st.caption("Instrument reference")
    ref_rows = [{"": k, "Name": v["name"], "Tick Size": v["tick_size"], "Tick Value": f"${v['tick_value']:.2f}",
                 "Point Value": f"${v['point_value']:.2f}", "Margin ~": f"${v['margin_estimate']}",
                 "Comm/Side": f"${v['default_commission']:.2f}"} for k, v in INSTRUMENTS.items()]
    st.dataframe(pd.DataFrame(ref_rows), hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 2 — Pre-Trade Check
# ═══════════════════════════════════════════════════════════════════
with tab_check:
    st.header("Pre-Trade Check")
    col_sess, col_trade, col_decision = st.columns([1, 1, 1], gap="large")
    with col_sess:
        st.subheader("Session State")
        daily_pnl    = st.number_input("Today's P/L ($)", value=0.0, step=10.0)
        trades_today = st.number_input("Trades Taken Today", min_value=0, max_value=100, value=0)
        st.divider()
        cost_for_pf = st.session_state.get("_cost_per_contr", 10.0)
        pf = firm_compute(config=pf_config, current_balance=curr_bal, high_water_mark=hwm,
                          realized_pnl=realized_pnl, cost_per_contract=cost_for_pf)
        icon = {"ON TRACK": "🟢", "CAUTION": "🟡", "DANGER": "🟠", "FAILED": "🔴"}
        st.metric("Account Status",   f"{icon.get(pf.status, '')} {pf.status}")
        st.metric("Remaining Buffer", f"${pf.remaining_buffer:,.0f}", delta=f"{pf.buffer_pct:.0f}% of max DD")
        st.metric("Losses Until Failure", pf.losses_to_failure)
        if pf.wins_to_target:
            st.metric("Wins to Target", pf.wins_to_target)
        if pf.consistency_warning:
            st.warning("Consistency rule at risk — one day dominates your total profit.")
    with col_trade:
        st.subheader("Proposed Trade")
        default_key = st.session_state.get("_instr_key", default_instr)
        check_key   = st.selectbox("Instrument", list(INSTRUMENTS.keys()),
                                    index=list(INSTRUMENTS.keys()).index(default_key), key="check_instr")
        check_instr = INSTRUMENTS[check_key]
        p_stop      = st.number_input("Stop (ticks)", min_value=1, max_value=500,
                                       value=st.session_state.get("_stop_ticks", 6), key="p_stop")
        p_target    = st.number_input("Target (ticks)", min_value=0, max_value=2000, value=12, key="p_target")
        p_contracts = st.number_input("Contracts", min_value=1, max_value=100, value=1, key="p_contr")
        p_comm      = st.number_input("Commission / side ($)", min_value=0.0,
                                       value=float(st.session_state.get("_comm", check_instr["default_commission"])),
                                       step=0.05, key="p_comm")
        if p_stop > 0 and p_target > 0:
            rr_display = p_target / p_stop
            color = "normal" if rr_display >= min_rr else "inverse"
            st.metric("R:R Ratio", f"{rr_display:.2f}", delta=f"min {min_rr:.1f}", delta_color=color)
        p_cost = (p_stop * check_instr["tick_value"]) + (p_comm * 2) + (0.5 * check_instr["tick_value"] * 2)
        size_check = calculate(account_size=account_size,
                               risk_pct=st.session_state.get("_risk_pct", default_risk_pct),
                               instrument=check_instr, stop_ticks=int(p_stop),
                               commission_per_side=p_comm, slippage_ticks=0.5)
    with col_decision:
        st.subheader("Decision")
        result = check(daily_pnl=daily_pnl, trades_today=int(trades_today),
                       daily_loss_limit=daily_limit, max_trades_per_day=int(max_trades_day),
                       proposed_stop_ticks=int(p_stop), proposed_target_ticks=int(p_target),
                       proposed_contracts=int(p_contracts), max_contracts=size_check.max_contracts,
                       max_stop_ticks=check_instr.get("max_stop_ticks", 20), min_rr_ratio=min_rr,
                       prop_firm_buffer=pf.remaining_buffer, cost_per_contract=p_cost)
        banner_cls = {PROCEED:"banner-proceed",WARN:"banner-warn",REDUCE:"banner-reduce",BLOCK:"banner-block"}.get(result.status,"banner-warn")
        banner_txt = {PROCEED:"✅  PROCEED",WARN:"⚠️  PROCEED WITH CAUTION",REDUCE:"⬇️  REDUCE SIZE",BLOCK:"🚫  DO NOT TRADE"}.get(result.status,result.status)
        st.markdown(f'<div class="{banner_cls}">{banner_txt}</div>', unsafe_allow_html=True)
        if result.status == REDUCE:
            st.info(f"Suggested contracts: **{result.suggested_contracts}**")
        for b in result.blocks:
            st.markdown(f'<div class="msg-block">🚫 {b}</div>', unsafe_allow_html=True)
        for w in result.warnings:
            st.markdown(f'<div class="msg-warn">⚠️ {w}</div>', unsafe_allow_html=True)
        st.divider()
        dm1, dm2 = st.columns(2)
        dm1.metric("Trade Risk $",     f"${result.dollar_risk_total:.2f}")
        dm2.metric("Projected Loss Limit Used", f"{result.daily_limit_pct_used:.0f}%")
        loss_used = max(0.0, -daily_pnl)
        used_frac = min(loss_used / max(daily_limit, 1), 1.0) if daily_limit > 0 else 0.0
        st.caption(f"Realized P/L: ${daily_pnl:+,.0f} | Daily loss limit: ${daily_limit:,.0f}")
        st.caption("Current realized-loss usage")
        st.progress(used_frac)


# ═══════════════════════════════════════════════════════════════════
# TAB 3 — Trade Journal
# ═══════════════════════════════════════════════════════════════════
with tab_journal:
    st.header("Trade Journal")

    # Surface orphaned image warning (non-blocking, read-only check)
    _all_valid_ids = set(str(int(i)) for i in load()["id"].dropna()) if not load().empty else set()
    _orphans = find_orphaned_image_records(_all_valid_ids)
    if _orphans:
        st.caption(f"⚠️ {len(_orphans)} orphaned image record(s) found (images with no matching trade). "
                   "Clean these up in the Library tab → Data Integrity.")

    jrnl_log, jrnl_view = st.tabs(["📝 Log / Edit Trade", "📋 Trade Log"])

    # ── Log / Edit sub-tab ────────────────────────────────────────────────────
    with jrnl_log:
        edit_id   = st.session_state.get("_edit_trade_id")
        edit_data = get_by_id(edit_id) if edit_id else None

        def _v(key, default=""):
            if edit_data and key in edit_data and edit_data[key] is not None:
                v = edit_data[key]
                return "" if (isinstance(v, float) and pd.isna(v)) else v
            return default

        def _vi(key, default=0):
            try:    return int(float(_v(key, default)))
            except: return default

        def _vf(key, default=0.0):
            try:    return float(_v(key, default))
            except: return default

        def _opt_idx(options, key, default_val="—"):
            val = _v(key, default_val)
            try:    return options.index(str(val))
            except: return 0

        if edit_id:
            st.info(f"✏️ Editing Trade #{edit_id}")
            if st.button("✕ Cancel Edit", key="cancel_edit"):
                del st.session_state["_edit_trade_id"]
                st.rerun()

        mode = st.radio("Journal mode", ["⚡ Fast", "🔬 Detailed"], horizontal=True, key="jrnl_mode",
                        help="Fast: 10 essential fields. Detailed: full structured entry.")
        st.divider()

        setup_names = get_setup_names() or []
        confluence_names = get_confluence_names()
        mistake_names = get_mistake_names()

        # ════════════════════════════════════════════════════════════════
        # CORE FIELDS
        # ════════════════════════════════════════════════════════════════
        c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
        _default_date = date.today()
        if edit_data and _v("date"):
            try: _default_date = pd.to_datetime(_v("date")).date()
            except Exception: pass
        f_date  = c1.date_input("Date *", value=_default_date)
        f_instr = c2.selectbox("Instrument *", list(INSTRUMENTS.keys()),
                                index=list(INSTRUMENTS.keys()).index(_v("instrument", default_instr))
                                if _v("instrument", default_instr) in INSTRUMENTS else 0, key="jrnl_instr")
        f_sess  = c3.selectbox("Session", SESSIONS, index=_opt_idx(SESSIONS, "session", SESSIONS[0]))
        f_dir   = c4.selectbox("Direction", DIRECTION_OPTIONS, index=_opt_idx(DIRECTION_OPTIONS, "direction", "—"), key="jrnl_dir")
        st.markdown('<p class="field-hint">* Instrument and date are required. A result also needs '
                    'Result (R), P/L ($), or both Entry and Exit prices filled in.</p>', unsafe_allow_html=True)

        # ── Setup model: primary_setup / setup_tags / confluence_tags — kept distinct ──
        st.markdown('<p class="section-label">Setup</p>', unsafe_allow_html=True)
        sp1, sp2 = st.columns([1, 1])
        primary_options = [NOT_SET] + setup_names
        _default_primary = _v("primary_setup") or _v("setup_type") or NOT_SET
        primary_idx = primary_options.index(_default_primary) if _default_primary in primary_options else 0
        f_primary_setup = sp1.selectbox(
            "Primary Setup", primary_options, index=primary_idx, key="jrnl_primary_setup",
            help="The main strategy used for this trade.",
        )
        tag_options = [s for s in setup_names if s != f_primary_setup]
        f_setup_tags = sp2.multiselect(
            "Additional Setup Tags", tag_options,
            default=[t for t in deserialize_tags(_v("setup_tags")) if t in tag_options],
            key="jrnl_setup_tags",
            help="Optional variations or sub-patterns combined with the primary setup.",
        )
        f_custom_setup = st.text_input(
            "Custom / temporary setup tag (optional)", value="", key="jrnl_custom_setup",
            placeholder="Not in your library yet? Add it here — it's saved as an extra setup tag.",
        )

        f_confluence_tags = st.multiselect(
            "Confluence Tags (supporting evidence)", confluence_names,
            default=[t for t in deserialize_tags(_v("confluence_tags")) if t in confluence_names],
            key="jrnl_conf_tags",
        )

        # Price levels
        pc1, pc2, pc3, pc4 = st.columns(4)
        f_entry  = pc1.number_input("Entry",  value=_vf("entry"),  step=0.01, format="%.2f", key="jrnl_entry")
        f_stop   = pc2.number_input("Stop",   value=_vf("stop"),   step=0.01, format="%.2f", key="jrnl_stop")
        f_target = pc3.number_input("Target", value=_vf("target"), step=0.01, format="%.2f", key="jrnl_target")
        f_exit   = pc4.number_input("Exit",   value=_vf("exit"),   step=0.01, format="%.2f", key="jrnl_exit")

        pr1, pr2, pr3 = st.columns(3)
        f_contr    = pr1.number_input("Contracts", min_value=1, value=max(1, _vi("contracts", 1)), key="jrnl_contr")
        f_result_r = pr2.number_input("Result (R)", value=_vf("result_r"), step=0.1,
                                       help="+1.5 = won 1.5R  /  -1.0 = lost 1R", key="jrnl_rr")
        f_pnl      = pr3.number_input("P/L ($)", value=_vf("dollar_pnl"), step=1.0, key="jrnl_pnl")

        st.markdown('<p class="section-label">Pre-Trade Thoughts</p>', unsafe_allow_html=True)
        f_pre_thoughts = st.text_area(
            "What am I seeing and thinking right now?", value=_v("pre_trade_thoughts"), height=140,
            placeholder="Write freely — what do you see in price action, your thesis, what you're "
                        "uncertain about, how you're feeling, why this interests you...",
            key="jrnl_pre_thoughts",
        )

        st.markdown('<p class="section-label">Post-Trade Reflection</p>', unsafe_allow_html=True)
        f_post_reflection = st.text_area(
            "What happened, what did I notice, and what am I thinking now?",
            value=_v("post_trade_reflection"), height=120,
            placeholder="Write freely — what actually happened vs what you expected, "
                        "what the market taught you, how you feel about the trade...",
            key="jrnl_post_reflection",
        )

        qg1, qg2 = st.columns(2)
        f_grade = qg1.selectbox("Quality Grade", GRADES, index=_opt_idx(GRADES, "quality_grade", "B"), key="jrnl_grade")
        f_notes = qg2.text_input("Quick notes", value=_v("notes"), key="jrnl_notes")

        # ════════════════════════════════════════════════════════════════
        # DETAILED SECTIONS
        # ════════════════════════════════════════════════════════════════
        f_htf_bias = f_mkt_cond = f_volatility = "—"
        f_near_news = False; f_news_mins = 0
        f_key_level = f_thesis = f_entry_trigger = f_invalidation = ""
        f_confidence_level = 3; f_planned_rr = 0.0
        f_emotion_tags = []; f_feeling_notes = ""
        f_focus = f_energy = f_urge = f_conf_setup = 3
        f_following_plan = "—"; f_trade_quality = "A"
        f_entry_time = f_exit_time = ""
        f_planned_risk = f_comm_paid = f_slip_paid = f_mfe = f_mae = 0.0
        f_followed_stop = f_moved_stop = f_took_partials = "—"
        f_exited_early = f_held_beyond = f_added = f_reduced = f_emotional_int = "—"
        f_mgmt_notes = ""
        f_followed_plan_post = f_thesis_correct = f_execution_good = f_worth_taking = "—"
        f_did_well = f_improve = f_market_taught = f_do_differently = f_key_lesson = ""
        f_process_score = f_exec_score = f_disc_score = 5
        f_mistake_tags = []

        if mode == "🔬 Detailed":
            with st.expander("📍 Market Context", expanded=False):
                mc1, mc2, mc3 = st.columns(3)
                f_htf_bias   = mc1.selectbox("HTF Bias", HTF_BIAS_OPTIONS, index=_opt_idx(HTF_BIAS_OPTIONS, "htf_bias"), key="jrnl_htf")
                f_mkt_cond   = mc2.selectbox("Market Condition", MARKET_COND_OPTIONS, index=_opt_idx(MARKET_COND_OPTIONS, "market_condition"), key="jrnl_mktcond")
                f_volatility = mc3.selectbox("Volatility", VOLATILITY_OPTIONS, index=_opt_idx(VOLATILITY_OPTIONS, "volatility"), key="jrnl_vol")
                nn1, nn2 = st.columns(2)
                f_near_news = nn1.checkbox("Major news nearby?", value=str(_v("near_news")) == "True", key="jrnl_news")
                f_news_mins = nn2.number_input("Minutes before/after news", min_value=0, value=_vi("news_minutes", 0), key="jrnl_newsmins")

            with st.expander("🧠 Trade Thesis", expanded=False):
                f_key_level     = st.text_input("Key level / area of interest", value=_v("key_level"), key="jrnl_keylevel")
                f_thesis        = st.text_area("Why do I believe an opportunity exists?", value=_v("thesis"), height=80, key="jrnl_thesis")
                f_entry_trigger = st.text_input("Entry trigger", value=_v("entry_trigger"), key="jrnl_trigger")
                f_invalidation  = st.text_input("Invalidation condition", value=_v("invalidation_criteria"), key="jrnl_invalid")
                tt1, tt2 = st.columns(2)
                f_planned_rr       = tt1.number_input("Planned R:R", min_value=0.0, value=_vf("planned_rr"), step=0.1, key="jrnl_planrr")
                f_confidence_level = tt2.slider("Confidence in setup (1-5)", 1, 5, _vi("confidence_level", 3), key="jrnl_conf")

            with st.expander("💭 Pre-Trade Psychology", expanded=False):
                saved_emo = [e for e in deserialize_tags(_v("emotion_tags")) if e in EMOTIONS]
                f_emotion_tags = st.multiselect("Emotional state (pick all that apply)", EMOTIONS, default=saved_emo, key="jrnl_emotions")
                f_feeling_notes = st.text_area("What am I feeling right now? (optional)", value=_v("feeling_notes"), height=70, key="jrnl_feeling")
                ps1, ps2, ps3, ps4 = st.columns(4)
                f_focus      = ps1.slider("Focus (1-5)",        1, 5, _vi("focus_level", 3),     key="jrnl_focus")
                f_energy     = ps2.slider("Energy (1-5)",       1, 5, _vi("energy_level", 3),    key="jrnl_energy")
                f_urge       = ps3.slider("Urge to trade (1-5)",1, 5, _vi("urge_to_trade", 3),   key="jrnl_urge")
                f_conf_setup = ps4.slider("Setup confidence (1-5)", 1, 5, _vi("confidence_setup", 3), key="jrnl_confsetup")
                pq1, pq2 = st.columns(2)
                f_following_plan = pq1.selectbox("Following my plan?", YNP_OPTIONS, index=_opt_idx(YNP_OPTIONS, "following_plan"), key="jrnl_followplan")
                f_trade_quality  = pq2.selectbox("Trade quality tier", ["A+","A","B","C","Impulsive"],
                                                  index=_opt_idx(["A+","A","B","C","Impulsive"], "trade_quality", "B"), key="jrnl_tq")

            with st.expander("⚙️ Execution Detail", expanded=False):
                ex1, ex2, ex3 = st.columns(3)
                f_entry_time   = ex1.text_input("Entry time (HH:MM)", value=_v("entry_time"), placeholder="09:32", key="jrnl_etime")
                f_exit_time    = ex2.text_input("Exit time (HH:MM)",  value=_v("exit_time"),  placeholder="09:45", key="jrnl_xtime")
                f_planned_risk = ex3.number_input("Planned risk ($)", min_value=0.0, value=_vf("planned_risk_dollars"), step=1.0, key="jrnl_planrisk")
                ef1, ef2, ef3 = st.columns(3)
                f_comm_paid = ef1.number_input("Commission paid ($)", min_value=0.0, value=_vf("commission_paid"), step=0.01, key="jrnl_comm")
                f_slip_paid = ef2.number_input("Slippage paid ($)",   min_value=0.0, value=_vf("slippage_paid"),  step=0.01, key="jrnl_slip")
                f_mfe       = ef3.number_input("Max Favorable Excursion (R)", value=_vf("mfe_r"), step=0.1, key="jrnl_mfe")
                f_mae = st.number_input("Max Adverse Excursion (R)", value=_vf("mae_r"), step=0.1, key="jrnl_mae")

            with st.expander("🎛️ Trade Management", expanded=False):
                mg1, mg2, mg3 = st.columns(3)
                f_followed_stop = mg1.selectbox("Followed original stop?", YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"followed_stop"), key="jrnl_mgstop")
                f_moved_stop    = mg2.selectbox("Moved the stop?",          YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"moved_stop"),    key="jrnl_mgmov")
                f_took_partials = mg3.selectbox("Took partial profits?",    YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"took_partials"),  key="jrnl_mgpart")
                mg4, mg5, mg6 = st.columns(3)
                f_exited_early  = mg4.selectbox("Exited early?",             YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"exited_early"),      key="jrnl_mgearly")
                f_held_beyond   = mg5.selectbox("Held beyond target?",       YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"held_beyond_target"), key="jrnl_mgheld")
                f_added         = mg6.selectbox("Added to position?",        YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"added_to_position"),  key="jrnl_mgadd")
                mg7, mg8 = st.columns(2)
                f_reduced       = mg7.selectbox("Reduced size?",             YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"reduced_size"),        key="jrnl_mgred")
                f_emotional_int = mg8.selectbox("Emotional interference?",   YNA_OPTIONS, index=_opt_idx(YNA_OPTIONS,"emotional_interference"), key="jrnl_mgemo")
                f_mgmt_notes = st.text_area("Management notes", value=_v("management_notes"), height=70, key="jrnl_mgnotes")

            with st.expander("📋 Post-Trade Structured Review", expanded=False):
                prc1, prc2, prc3, prc4 = st.columns(4)
                f_followed_plan_post = prc1.selectbox("Followed plan?",  YNP_OPTIONS, index=_opt_idx(YNP_OPTIONS,"followed_plan_post"), key="jrnl_ptfp")
                f_thesis_correct     = prc2.selectbox("Thesis correct?", YNP_OPTIONS, index=_opt_idx(YNP_OPTIONS,"thesis_correct"),     key="jrnl_pttc")
                f_execution_good     = prc3.selectbox("Execution good?", YNP_OPTIONS, index=_opt_idx(YNP_OPTIONS,"execution_good"),     key="jrnl_pteg")
                f_worth_taking       = prc4.selectbox("Worth taking?",   YN_OPTIONS,  index=_opt_idx(YN_OPTIONS, "worth_taking"),      key="jrnl_ptwt")
                f_did_well       = st.text_input("What did I do well?",           value=_v("did_well"),        key="jrnl_ptdw")
                f_improve        = st.text_input("What could I improve?",         value=_v("improve"),         key="jrnl_ptimp")
                f_market_taught  = st.text_input("What did the market teach me?",  value=_v("market_taught"),   key="jrnl_ptmt")
                f_do_differently = st.text_input("What would I do differently?",  value=_v("do_differently"),  key="jrnl_ptdd")
                f_key_lesson     = st.text_input("Key lesson",                     value=_v("key_lesson"),      key="jrnl_ptkl")
                sc1, sc2, sc3 = st.columns(3)
                f_process_score = sc1.slider("Process score (1-10)",    1, 10, _vi("process_score",    5), key="jrnl_ptscore")
                f_exec_score    = sc2.slider("Execution score (1-10)",  1, 10, _vi("execution_score",  5), key="jrnl_exscore")
                f_disc_score    = sc3.slider("Discipline score (1-10)", 1, 10, _vi("discipline_score", 5), key="jrnl_discscore")

            with st.expander("⚠️ Mistake Tags", expanded=False):
                saved_mistakes = [m for m in deserialize_tags(_v("mistake_tags", _v("mistake_tag",""))) if m in mistake_names]
                f_mistake_tags = st.multiselect("What mistakes were made? (select all that apply)",
                                                 mistake_names, default=saved_mistakes, key="jrnl_mistakes")

        # ── Image uploads ─────────────────────────────────────────────────────
        with st.expander("📸 Screenshots", expanded=bool(edit_id)):
            if edit_id:
                existing_imgs = get_images(int(edit_id))
                if existing_imgs:
                    st.caption(f"{len(existing_imgs)} image record(s) attached:")
                    img_cols = st.columns(min(len(existing_imgs), 3))
                    for i, img_rec in enumerate(existing_imgs):
                        with img_cols[i % 3]:
                            if os.path.exists(img_rec["path"]):
                                st.image(img_rec["path"], caption=f"{img_rec['category']} — {img_rec['caption']}", use_container_width=True)
                            else:
                                st.caption(f"⚠️ File missing on disk: {img_rec['filename']}")
                            if st.button("🗑️ Delete", key=f"del_img_{img_rec['filename']}"):
                                delete_image(int(edit_id), img_rec["filename"])
                                st.success("Image deleted.")
                                st.rerun()

            uploaded_files = st.file_uploader(
                "Upload screenshots (PNG, JPG, JPEG, WEBP — max 10 MB each)",
                type=["png","jpg","jpeg","webp"], accept_multiple_files=True, key="jrnl_uploads",
            )
            img_categories, img_captions = [], []
            if uploaded_files:
                for i, uf in enumerate(uploaded_files):
                    ic1, ic2 = st.columns([1, 2])
                    cat = ic1.selectbox(f"Category — {uf.name[:20]}", CATEGORIES, key=f"img_cat_{i}")
                    cap = ic2.text_input(f"Caption — {uf.name[:20]}", key=f"img_cap_{i}", placeholder="e.g. 5-min chart at entry")
                    img_categories.append(cat); img_captions.append(cap)

        # ── Save button — validate FIRST, then trade, then images ────────────
        st.divider()
        btn_label = "💾 Save Changes" if edit_id else "➕ Log Trade"
        if st.button(btn_label, type="primary", use_container_width=True, key="jrnl_save"):

            # Build the effective setup_tags list: multiselect + optional custom text
            effective_setup_tags = list(f_setup_tags)
            if f_custom_setup.strip():
                effective_setup_tags.append(f_custom_setup.strip())

            primary_setup_value = "" if f_primary_setup == NOT_SET else f_primary_setup
            # setup_type mirrors primary_setup for backward-compatible analytics grouping
            setup_type_value = primary_setup_value or (effective_setup_tags[0] if effective_setup_tags else "")

            payload = {
                "date":                  str(f_date),
                "session":               f_sess,
                "instrument":            f_instr,
                "direction":             f_dir,
                "primary_setup":         primary_setup_value,
                "setup_type":            setup_type_value,
                "setup_tags":            serialize_tags(effective_setup_tags),
                "confluence_tags":       serialize_tags(f_confluence_tags),
                "entry":                 f_entry, "stop": f_stop, "target": f_target, "exit": f_exit,
                "contracts":             f_contr,
                "result_r":              f_result_r,
                "dollar_pnl":            f_pnl,
                "quality_grade":         f_grade,
                "notes":                 f_notes,
                "pre_trade_thoughts":    f_pre_thoughts,
                "post_trade_reflection": f_post_reflection,
            }

            if mode == "🔬 Detailed":
                payload.update({
                    "htf_bias": f_htf_bias, "market_condition": f_mkt_cond, "volatility": f_volatility,
                    "near_news": str(f_near_news), "news_minutes": f_news_mins,
                    "key_level": f_key_level, "thesis": f_thesis,
                    "entry_trigger": f_entry_trigger, "invalidation_criteria": f_invalidation,
                    "planned_rr": f_planned_rr, "confidence_level": f_confidence_level,
                    "emotion_tag": (f_emotion_tags[0] if f_emotion_tags else ""),   # legacy mirror
                    "emotion_tags": serialize_tags(f_emotion_tags),
                    "feeling_notes": f_feeling_notes,
                    "focus_level": f_focus, "energy_level": f_energy,
                    "urge_to_trade": f_urge, "confidence_setup": f_conf_setup,
                    "following_plan": f_following_plan, "trade_quality": f_trade_quality,
                    "entry_time": f_entry_time, "exit_time": f_exit_time,
                    "planned_risk_dollars": f_planned_risk,
                    "commission_paid": f_comm_paid, "slippage_paid": f_slip_paid,
                    "mfe_r": f_mfe, "mae_r": f_mae,
                    "followed_stop": f_followed_stop, "moved_stop": f_moved_stop,
                    "took_partials": f_took_partials, "exited_early": f_exited_early,
                    "held_beyond_target": f_held_beyond, "added_to_position": f_added,
                    "reduced_size": f_reduced, "emotional_interference": f_emotional_int,
                    "management_notes": f_mgmt_notes,
                    "followed_plan_post": f_followed_plan_post, "thesis_correct": f_thesis_correct,
                    "execution_good": f_execution_good, "worth_taking": f_worth_taking,
                    "did_well": f_did_well, "improve": f_improve,
                    "market_taught": f_market_taught, "do_differently": f_do_differently,
                    "key_lesson": f_key_lesson,
                    "process_score": f_process_score, "execution_score": f_exec_score,
                    "discipline_score": f_disc_score,
                    "mistake_tag": (f_mistake_tags[0] if f_mistake_tags else ""),   # legacy mirror
                    "mistake_tags": serialize_tags(f_mistake_tags),
                })

            # ── STEP 1: VALIDATE ──────────────────────────────────────────────
            is_valid, validation_errors = validate_trade(payload)

            if not is_valid:
                for err in validation_errors:
                    st.error(f"⚠️ {err}")
            else:
                # ── STEP 2: SAVE THE TRADE (trade_id is now known) ────────────
                trade_id_for_imgs = None
                if edit_id:
                    ok = journal_update(int(edit_id), payload)
                    if ok:
                        trade_id_for_imgs = int(edit_id)
                        st.success(f"Trade #{edit_id} updated ✓")
                        del st.session_state["_edit_trade_id"]
                    else:
                        st.error("Could not find trade to update — it may have been deleted.")
                else:
                    df_new = add(payload)
                    ids = df_new["id"].dropna()
                    trade_id_for_imgs = int(ids.max()) if not ids.empty else None
                    st.success(f"Trade #{trade_id_for_imgs} logged ✓")

                # ── STEP 3: ONLY NOW SAVE IMAGES (trade already persisted) ────
                if trade_id_for_imgs and uploaded_files:
                    saved, img_errors = [], []
                    for i, uf in enumerate(uploaded_files):
                        cat = img_categories[i] if i < len(img_categories) else "Other"
                        cap = img_captions[i]  if i < len(img_captions)  else ""
                        try:
                            save_image(trade_id_for_imgs, uf.read(), uf.name, category=cat, caption=cap)
                            saved.append(uf.name)
                        except Exception as e:
                            img_errors.append(f"{uf.name}: {e}")

                    if saved:
                        st.success(f"📸 {len(saved)} image(s) saved.")
                    if img_errors:
                        st.warning(
                            f"Trade #{trade_id_for_imgs} was saved successfully, but "
                            f"{len(img_errors)} image(s) failed to upload: "
                            f"{'; '.join(img_errors)}. The trade is not affected — "
                            "you can retry the upload by editing this trade."
                        )

                st.rerun()

    # ── Trade Log sub-tab ─────────────────────────────────────────────────────
    with jrnl_view:
        df = load()
        if df.empty:
            st.info("No trades yet. Use the 'Log / Edit Trade' tab to add your first trade.")
        else:
            ff1, ff2, ff3, ff4 = st.columns(4)
            sess_opts    = sorted(df["session"].dropna().unique().tolist()) if "session" in df.columns else []
            instr_opts   = sorted(df["instrument"].dropna().unique().tolist()) if "instrument" in df.columns else []
            grade_opts   = sorted(df["quality_grade"].dropna().unique().tolist()) if "quality_grade" in df.columns else []
            primary_opts = sorted(df["primary_setup"].dropna().unique().tolist()) if "primary_setup" in df.columns else []
            primary_opts = [p for p in primary_opts if p]

            f_filt_sess    = ff1.multiselect("Session",       sess_opts,    default=[], key="filt_sess")
            f_filt_instr   = ff2.multiselect("Instrument",    instr_opts,   default=[], key="filt_instr")
            f_filt_grade   = ff3.multiselect("Grade",         grade_opts,   default=[], key="filt_grade")
            f_filt_primary = ff4.multiselect("Primary Setup", primary_opts, default=[], key="filt_primary")

            fdf = df.copy()
            if f_filt_sess:    fdf = fdf[fdf["session"].isin(f_filt_sess)]
            if f_filt_instr:   fdf = fdf[fdf["instrument"].isin(f_filt_instr)]
            if f_filt_grade:   fdf = fdf[fdf["quality_grade"].isin(f_filt_grade)]
            if f_filt_primary: fdf = fdf[fdf["primary_setup"].isin(f_filt_primary)]

            # Display-only fallback: old rows have setup_type but not primary_setup
            fdf = fdf.copy()
            if "primary_setup" in fdf.columns and "setup_type" in fdf.columns:
                fdf["Primary Setup"] = fdf["primary_setup"].where(
                    fdf["primary_setup"].notna() & (fdf["primary_setup"] != ""), fdf["setup_type"])
            elif "setup_type" in fdf.columns:
                fdf["Primary Setup"] = fdf["setup_type"]

            show_cols = [c for c in ["id","date","session","instrument","direction",
                                      "Primary Setup","result_r","dollar_pnl",
                                      "quality_grade","trade_quality"] if c in fdf.columns]

            def _highlight(row):
                styles = [""] * len(row)
                if "result_r" in row.index:
                    try:
                        v = float(row["result_r"]); idx = row.index.get_loc("result_r")
                        if v > 0:   styles[idx] = "background-color:#0a1f12;color:#4ade80"
                        elif v < 0: styles[idx] = "background-color:#1f0a0a;color:#f87171"
                    except: pass
                return styles

            st.dataframe(fdf[show_cols].style.apply(_highlight, axis=1), use_container_width=True, height=340)

            dl_col, del_col = st.columns(2)
            dl_col.download_button("⬇️ Export CSV", df.to_csv(index=False), "trades.csv", "text/csv", use_container_width=True)

            if "id" in df.columns and not df.empty:
                _ids = df["id"].dropna()
                if not _ids.empty:
                    act_id = del_col.number_input("Trade ID", min_value=int(_ids.min()), max_value=int(_ids.max()),
                                                   value=int(_ids.min()), step=1, key="del_id")
                    da, db = st.columns(2)
                    if da.button("✏️ Edit this trade", use_container_width=True, key="btn_edit"):
                        st.session_state["_edit_trade_id"] = int(act_id)
                        st.rerun()
                    if db.button("🗑️ Delete this trade", use_container_width=True, key="btn_del"):
                        st.session_state["_confirm_delete_id"] = int(act_id)
                        st.rerun()

                    # Two-step delete confirmation — asks about associated images
                    if st.session_state.get("_confirm_delete_id") == int(act_id):
                        imgs_for_trade = get_images(int(act_id))
                        n_imgs = len(imgs_for_trade)
                        st.warning(f"Delete Trade #{act_id}? A backup of trades.csv is kept in data/backups/, "
                                   "but this action cannot be undone from within the app.")
                        delete_imgs_too = True
                        if n_imgs > 0:
                            delete_imgs_too = st.checkbox(
                                f"Also delete {n_imgs} associated image(s)?", value=True,
                                key=f"delimgs_{act_id}",
                                help="If unchecked, the image files and metadata are kept "
                                     "(they'll show up as orphaned records).",
                            )
                        cc1, cc2 = st.columns(2)
                        if cc1.button("✅ Confirm Delete", type="primary", key="confirm_del_btn"):
                            remove(int(act_id))
                            if delete_imgs_too and n_imgs > 0:
                                delete_all_images_for_trade(int(act_id))
                            del st.session_state["_confirm_delete_id"]
                            st.success(f"Trade #{act_id} deleted"
                                       + (f" along with {n_imgs} image(s)." if delete_imgs_too and n_imgs else "."))
                            st.rerun()
                        if cc2.button("✕ Cancel", key="cancel_del_btn"):
                            del st.session_state["_confirm_delete_id"]
                            st.rerun()

            # Trade review card
            st.divider()
            view_ids = df["id"].dropna().astype(int).tolist()
            if view_ids:
                sel_view = st.selectbox(
                    "View trade details:", options=view_ids,
                    format_func=lambda x: f"Trade #{x} — {df[df['id']==x]['date'].iloc[0] if not df[df['id']==x].empty else ''}",
                    key="view_sel",
                )
                if sel_view:
                    tr = get_by_id(int(sel_view))
                    if tr:
                        st.markdown('<div class="trade-card">', unsafe_allow_html=True)
                        tc1, tc2, tc3, tc4 = st.columns(4)
                        tc1.metric("Instrument", tr.get("instrument","—"))
                        tc2.metric("Direction",  tr.get("direction","—"))
                        tc3.metric("Result R",   f"{tr.get('result_r',0):+.2f}R" if tr.get("result_r") is not None else "—")
                        tc4.metric("P/L $",      f"${tr.get('dollar_pnl',0):,.2f}" if tr.get("dollar_pnl") is not None else "—")

                        if tr.get("pre_trade_thoughts"):
                            st.markdown("**Pre-Trade Thoughts**"); st.info(tr["pre_trade_thoughts"])
                        if tr.get("post_trade_reflection"):
                            st.markdown("**Post-Trade Reflection**"); st.success(tr["post_trade_reflection"])

                        # Setup / confluence — shown as distinct fields, never merged
                        setup_col1, setup_col2, setup_col3 = st.columns(3)
                        primary_display = tr.get("primary_setup") or tr.get("setup_type") or "—"
                        setup_col1.markdown(f"**Primary Setup**\n\n{primary_display}")
                        tags_display = ", ".join(deserialize_tags(tr.get("setup_tags"))) or "—"
                        setup_col2.markdown(f"**Setup Tags**\n\n{tags_display}")
                        conf_display = ", ".join(deserialize_tags(tr.get("confluence_tags"))) or "—"
                        setup_col3.markdown(f"**Confluence**\n\n{conf_display}")

                        det_fields = {
                            "HTF Bias": tr.get("htf_bias"), "Condition": tr.get("market_condition"),
                            "Thesis": tr.get("thesis"), "Key Level": tr.get("key_level"),
                            "Entry Trigger": tr.get("entry_trigger"), "Invalidation": tr.get("invalidation_criteria"),
                            "Grade": tr.get("quality_grade"), "Process": tr.get("process_score"),
                            "Execution": tr.get("execution_score"), "Discipline": tr.get("discipline_score"),
                            "Key Lesson": tr.get("key_lesson"),
                            "Mistakes": ", ".join(deserialize_tags(tr.get("mistake_tags"))) or tr.get("mistake_tag"),
                            "Emotions": ", ".join(deserialize_tags(tr.get("emotion_tags"))) or tr.get("emotion_tag"),
                        }
                        non_empty = {k: v for k, v in det_fields.items() if v and str(v) not in ("—","nan","None","")}
                        if non_empty:
                            with st.expander("Full trade details", expanded=False):
                                for k, v in non_empty.items():
                                    st.write(f"**{k}:** {v}")

                        imgs = get_images(int(sel_view))
                        if imgs:
                            with st.expander(f"📸 {len(imgs)} screenshot(s)", expanded=True):
                                img_cols2 = st.columns(min(len(imgs), 3))
                                for i, img in enumerate(imgs):
                                    with img_cols2[i % 3]:
                                        if os.path.exists(img["path"]):
                                            st.image(img["path"], caption=f"{img['category']} — {img['caption']}", use_container_width=True)
                                        else:
                                            st.caption(f"⚠️ File missing on disk: {img['filename']}")
                        st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 4 — Analytics
# ═══════════════════════════════════════════════════════════════════
with tab_analytics:
    st.header("Analytics")
    df = load()

    if df.empty or "result_r" not in df.columns:
        st.info("Log trades with R-multiples to see performance analytics.")
    else:
        m = analytics_core(df)
        if not m or m.get("n_trades", 0) == 0:
            st.warning("No valid R-multiple values are available for analytics.")
        else:
            n = m["n_trades"]
            st.subheader("Core Metrics")
            a1, a2, a3, a4, a5, a6 = st.columns(6)
            a1.metric("Trades",        n)
            a2.metric("Win Rate",      f"{m['win_rate']:.1%}")
            a3.metric("Expectancy",    f"{m['expectancy']:+.2f}R")
            pf_val = m["profit_factor"]
            a4.metric("Profit Factor", f"{pf_val:.2f}" if pf_val != float("inf") else "∞")
            a5.metric("Max DD (R)",    f"{m['max_dd_r']:.2f}R")
            a6.metric("Max Streak",    f"-{m['max_losing_streak']} L")
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Avg Win",  f"+{m['avg_win_r']:.2f}R")
            b2.metric("Avg Loss", f"−{m['avg_loss_r']:.2f}R")
            b3.metric("Wins",     m["n_wins"])
            b4.metric("Losses",   m["n_losses"])
            if m.get("pnl_total") is not None:
                st.metric("Total P/L $", f"${m['pnl_total']:,.2f}")

            tier_fn = {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}
            tier_fn.get(m["edge_tier"], st.info)(m["edge_label"])
            if n < 30:
                st.caption(f"{n} trades logged. Small samples are especially uncertain.")

            st.divider()
            st.subheader("Equity Curve (Cumulative R)")
            cum_r = m["cum_r"]
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(x=list(range(1, len(cum_r)+1)), y=cum_r, mode="lines",
                                         line=dict(color="#4ade80", width=2), fill="tozeroy",
                                         fillcolor="rgba(74,222,128,0.07)"))
            fig_eq.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.2)")
            fig_eq.update_layout(template="plotly_dark", height=260, margin=dict(l=0,r=0,t=10,b=0),
                                  xaxis_title="Trade #", yaxis_title="R")
            st.plotly_chart(fig_eq, use_container_width=True)

            st.divider()
            st.subheader("Breakdowns")
            st.caption("Grouped by **Primary Setup** — the main strategy used, not setup tags or confluences.")

            MIN_N = 5  # flag small groups; five trades do not establish significance

            def render_seg(title, field, col):
                seg = by_field(df, field)
                with col:
                    st.caption(f"**{title}**")
                    if seg is not None and not seg.empty:
                        seg = seg.rename(columns={field: title, "trades":"N", "avg_r":"Avg R",
                                                   "total_r":"Total R", "win_pct":"Win %"})
                        seg["Avg R"]   = seg["Avg R"].round(2)
                        seg["Total R"] = seg["Total R"].round(2)
                        seg["Win %"]   = (seg["Win %"]*100).round(1)
                        st.dataframe(seg, hide_index=True, use_container_width=True)
                        small = seg[seg["N"] < MIN_N]
                        if not small.empty:
                            st.caption(f"⚠️ {len(small)} group(s) with <{MIN_N} trades — interpret cautiously.")
                    else:
                        st.caption("—")

            ca, cb = st.columns(2)
            render_seg("Session",        "session",       ca)
            render_seg("Primary Setup",  "setup_type",    cb)   # setup_type mirrors primary_setup on every new save
            render_seg("Grade",          "quality_grade", ca)
            render_seg("Direction",      "direction",     cb)

            if "market_condition" in df.columns and df["market_condition"].notna().any():
                cc, cd = st.columns(2)
                render_seg("Market Condition", "market_condition", cc)
                if "volatility" in df.columns and df["volatility"].notna().any():
                    render_seg("Volatility", "volatility", cd)

            if "trade_quality" in df.columns and df["trade_quality"].notna().any():
                ce, cf = st.columns(2)
                render_seg("Trade Quality", "trade_quality", ce)
                if "followed_plan_post" in df.columns and df["followed_plan_post"].notna().any():
                    render_seg("Followed Plan?", "followed_plan_post", cf)

            st.divider()
            st.subheader("R Distribution")
            r_vals = df["result_r"].dropna().astype(float)
            fig_hist = go.Figure()
            fig_hist.add_trace(go.Histogram(x=r_vals, nbinsx=20,
                                             marker_color=["#4ade80" if v >= 0 else "#f87171" for v in r_vals]))
            fig_hist.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.35)")
            if len(r_vals) > 0:
                fig_hist.add_vline(x=float(r_vals.mean()), line_dash="dot", line_color="#fbbf24",
                                    annotation_text=f"mean {r_vals.mean():.2f}R", annotation_position="top right")
            fig_hist.update_layout(template="plotly_dark", height=220, margin=dict(l=0,r=0,t=10,b=0),
                                    xaxis_title="R", yaxis_title="Trades", showlegend=False)
            st.plotly_chart(fig_hist, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 5 — Daily Journal
# ═══════════════════════════════════════════════════════════════════
with tab_daily:
    st.header("Daily Journal")
    dj_today, dj_history = st.tabs(["📝 Today's Session", "📅 Session History"])

    with dj_today:
        dj_date = st.date_input("Session date", value=date.today(), key="dj_date")
        existing_day = get_day(dj_date)

        def _dv(key, default=""):
            if existing_day and key in existing_day and existing_day[key] is not None:
                v = existing_day[key]
                if isinstance(v, float) and pd.isna(v): return default
                return v
            return default

        def _dvi(key, default=3):
            try: return int(float(_dv(key, default)))
            except: return default

        pre_col, post_col = st.columns(2, gap="large")

        with pre_col:
            st.subheader("Before the Session")
            ps1, ps2, ps3 = st.columns(3)
            d_sleep  = ps1.slider("Sleep quality (1-5)", 1, 5, _dvi("sleep_quality"), key="dj_sleep")
            d_energy = ps2.slider("Energy (1-5)",        1, 5, _dvi("energy"),        key="dj_energy")
            d_focus  = ps3.slider("Focus (1-5)",         1, 5, _dvi("focus"),         key="dj_focus")
            d_emotion_pre = st.text_input("Emotional state", value=str(_dv("emotional_state","")), key="dj_emo")
            d_events  = st.text_input("Economic events today", value=str(_dv("economic_events","")), key="dj_events")
            d_bias    = st.text_input("Daily directional bias", value=str(_dv("daily_bias","")), key="dj_bias")
            d_maxloss = st.number_input("Max daily loss ($)", min_value=0.0, value=float(_dv("max_daily_loss",0) or 0), step=50.0, key="dj_maxloss")
            d_maxtrades = st.number_input("Max trades today", min_value=0, max_value=50, value=int(_dv("max_trades",3) or 3), key="dj_maxt")
            d_main_focus = st.text_input("Main thing I want to execute well today", value=str(_dv("main_focus","")), key="dj_mainf")
            d_pre_thoughts = st.text_area(
                "What am I thinking and noticing before today's session?",
                value=str(_dv("pre_session_thoughts","")), height=140, key="dj_prethoughts",
                placeholder="Market context, expectations, things to watch for, mental state...",
            )

        with post_col:
            st.subheader("After the Session")
            pp1, pp2, pp3 = st.columns(3)
            d_total_trades = pp1.number_input("Total trades",  min_value=0, value=int(_dv("total_trades",0) or 0), key="dj_tt")
            d_total_pnl    = pp2.number_input("Total P/L ($)", value=float(_dv("total_pnl",0) or 0), step=1.0, key="dj_pnl")
            d_total_r      = pp3.number_input("Total R",       value=float(_dv("total_r",0) or 0), step=0.1, key="dj_r")
            d_followed_plan = st.selectbox("Did I follow my plan?", ["—","Yes","Mostly","No","Unsure"], index=0, key="dj_fp")
            d_best    = st.text_input("Best decision today",    value=str(_dv("best_decision","")), key="dj_best")
            d_worst   = st.text_input("Worst decision today",   value=str(_dv("worst_decision","")), key="dj_worst")
            d_lesson  = st.text_input("Biggest lesson",         value=str(_dv("biggest_lesson","")), key="dj_lesson")
            d_pattern = st.text_input("Pattern I noticed",      value=str(_dv("pattern_noticed","")), key="dj_pat")
            d_next    = st.text_input("Focus for next session", value=str(_dv("next_session_focus","")), key="dj_next")
            d_post_thoughts = st.text_area(
                "What am I thinking and feeling after today's session?",
                value=str(_dv("post_session_thoughts","")), height=140, key="dj_postthoughts",
                placeholder="How did the session go, what did you learn, how do you feel...",
            )

        if st.button("💾 Save Daily Journal", type="primary", use_container_width=True, key="dj_save"):
            save_day(dj_date, {
                "sleep_quality": d_sleep, "energy": d_energy, "focus": d_focus,
                "emotional_state": d_emotion_pre, "economic_events": d_events,
                "daily_bias": d_bias, "max_daily_loss": d_maxloss, "max_trades": d_maxtrades,
                "main_focus": d_main_focus, "pre_session_thoughts": d_pre_thoughts,
                "total_trades": d_total_trades, "total_pnl": d_total_pnl, "total_r": d_total_r,
                "followed_plan_daily": d_followed_plan,
                "best_decision": d_best, "worst_decision": d_worst,
                "biggest_lesson": d_lesson, "pattern_noticed": d_pattern,
                "next_session_focus": d_next, "post_session_thoughts": d_post_thoughts,
            })
            st.success(f"Daily journal saved for {dj_date} ✓")
            st.rerun()

    with dj_history:
        st.subheader("Recent Sessions")
        dj_df = load_daily()
        if dj_df.empty:
            st.info("No daily journal entries yet.")
        else:
            show = dj_df.sort_values("date", ascending=False).head(30)
            show_cols = [c for c in ["date","sleep_quality","energy","focus","emotional_state",
                                      "total_trades","total_pnl","total_r","followed_plan_daily",
                                      "biggest_lesson"] if c in show.columns]
            st.dataframe(show[show_cols], use_container_width=True, hide_index=True)
            st.download_button("⬇️ Export Daily Journal CSV", dj_df.to_csv(index=False), "daily_journal.csv", "text/csv")


# ═══════════════════════════════════════════════════════════════════
# TAB 6 — Library Manager (setup/mistake/confluence CRUD + data integrity)
# ═══════════════════════════════════════════════════════════════════
with tab_library:
    st.header("Library Manager")
    lib_setups, lib_mistakes, lib_confluences, lib_integrity = st.tabs(
        ["🔧 Setup Library", "⚠️ Mistake Library", "🔗 Confluence Tags", "🧹 Data Integrity"]
    )

    # ── Setup Library ─────────────────────────────────────────────────────────
    with lib_setups:
        st.subheader("Setup Library")
        st.caption("Setups here populate the journal's Primary Setup and Setup Tags fields. "
                   "Archiving hides a setup from new trades but never alters historical trades "
                   "that already used it.")

        all_setups = load_setups(include_inactive=True)
        if all_setups:
            for setup in all_setups:
                active = setup.get("active", True)
                with st.expander(f"{'✅' if active else '💤'} {setup['name']}", expanded=False):
                    new_name  = st.text_input("Name", value=setup["name"], key=f"s_name_{setup['id']}")
                    new_desc  = st.text_area("Description", value=setup.get("description",""), height=60, key=f"s_desc_{setup['id']}")
                    new_entry = st.text_area("Entry criteria", value=setup.get("entry_criteria",""), height=60, key=f"s_entry_{setup['id']}")
                    new_mkt   = st.text_area("Ideal market conditions", value=setup.get("market_conditions",""), height=60, key=f"s_mkt_{setup['id']}")
                    new_inv   = st.text_area("Invalidation criteria", value=setup.get("invalidation",""), height=60, key=f"s_inv_{setup['id']}")
                    new_notes = st.text_area("Notes", value=setup.get("notes",""), height=60, key=f"s_notes_{setup['id']}")
                    bc1, bc2, bc3 = st.columns(3)
                    if bc1.button("💾 Save", key=f"s_save_{setup['id']}"):
                        update_setup(setup["id"], {"name":new_name,"description":new_desc,
                                                    "entry_criteria":new_entry,"market_conditions":new_mkt,
                                                    "invalidation":new_inv,"notes":new_notes})
                        st.success("Saved ✓"); st.rerun()
                    if active:
                        if bc2.button("💤 Archive", key=f"s_arch_{setup['id']}"):
                            archive_setup(setup["id"]); st.rerun()
                    else:
                        if bc2.button("✅ Restore", key=f"s_rest_{setup['id']}"):
                            restore_setup(setup["id"]); st.rerun()
                    if bc3.button("🗑️ Delete", key=f"s_del_{setup['id']}"):
                        delete_setup(setup["id"])
                        st.info("Setup removed from the library. Historical trades that used "
                                "this setup keep their original data unchanged.")
                        st.rerun()

        st.divider()
        st.subheader("Add New Setup")
        with st.form("add_setup_form", clear_on_submit=True):
            ns_name  = st.text_input("Setup name *", placeholder="e.g. Opening Drive")
            ns_desc  = st.text_area("Description", height=60)
            ns_entry = st.text_area("Entry criteria", height=60)
            ns_mkt   = st.text_area("Ideal market conditions", height=60)
            ns_inv   = st.text_area("Invalidation criteria", height=60)
            ns_notes = st.text_area("Notes", height=60)
            if st.form_submit_button("➕ Add Setup", type="primary"):
                if not ns_name.strip():
                    st.error("Setup name is required.")
                else:
                    try:
                        add_setup(ns_name, ns_desc, ns_entry, ns_mkt, ns_inv, ns_notes)
                        st.success(f"'{ns_name}' added ✓"); st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    # ── Shared render helper for mistake/confluence libraries ──────────────────
    def _render_simple_lib(get_all_fn, add_fn, update_fn, archive_fn, restore_fn, delete_fn, key_prefix):
        items = get_all_fn(include_inactive=True)
        for item in items:
            active = item.get("active", True)
            with st.expander(f"{'✅' if active else '💤'} {item['name']}", expanded=False):
                new_name = st.text_input("Name", value=item["name"], key=f"{key_prefix}_name_{item['id']}")
                bc1, bc2, bc3 = st.columns(3)
                if bc1.button("💾 Save", key=f"{key_prefix}_save_{item['id']}"):
                    update_fn(item["id"], {"name": new_name}); st.success("Saved ✓"); st.rerun()
                if active:
                    if bc2.button("💤 Archive", key=f"{key_prefix}_arch_{item['id']}"):
                        archive_fn(item["id"]); st.rerun()
                else:
                    if bc2.button("✅ Restore", key=f"{key_prefix}_rest_{item['id']}"):
                        restore_fn(item["id"]); st.rerun()
                if bc3.button("🗑️ Delete", key=f"{key_prefix}_del_{item['id']}"):
                    delete_fn(item["id"]); st.rerun()

    # ── Mistake Library ───────────────────────────────────────────────────────
    with lib_mistakes:
        st.subheader("Mistake Library")
        _render_simple_lib(get_mistakes, add_mistake, update_mistake, archive_mistake, restore_mistake, delete_mistake, "mist")
        st.divider()
        with st.form("add_mistake_form", clear_on_submit=True):
            nm_name = st.text_input("New mistake tag name *")
            if st.form_submit_button("➕ Add Mistake Tag", type="primary"):
                if nm_name.strip():
                    try:
                        add_mistake(nm_name); st.success(f"'{nm_name}' added ✓"); st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                else:
                    st.error("Name required.")

    # ── Confluence Tags ───────────────────────────────────────────────────────
    with lib_confluences:
        st.subheader("Confluence Tags")
        _render_simple_lib(get_confluences, add_confluence, update_confluence,
                            archive_confluence, restore_confluence, delete_confluence, "conf")
        st.divider()
        with st.form("add_conf_form", clear_on_submit=True):
            nc_name = st.text_input("New confluence tag name *")
            if st.form_submit_button("➕ Add Confluence Tag", type="primary"):
                if nc_name.strip():
                    try:
                        add_confluence(nc_name); st.success(f"'{nc_name}' added ✓"); st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                else:
                    st.error("Name required.")

    # ── Data Integrity ────────────────────────────────────────────────────────
    with lib_integrity:
        st.subheader("Data Integrity")
        st.caption("Orphaned image records point to a trade_id that no longer exists — "
                   "usually because a trade was deleted without also removing its images. "
                   "Nothing here is deleted automatically; review before purging.")

        _current_df = load()
        _valid_ids = set(str(int(i)) for i in _current_df["id"].dropna()) if not _current_df.empty else set()
        _orphan_records = find_orphaned_image_records(_valid_ids)

        if not _orphan_records:
            st.success("No orphaned image records found.")
        else:
            total_orphan_files = sum(len(v) for v in _orphan_records.values())
            st.warning(f"Found {len(_orphan_records)} orphaned trade-id group(s), "
                       f"{total_orphan_files} image file(s) total.")
            for tid, records in _orphan_records.items():
                st.write(f"**Trade ID {tid}** (no matching trade) — {len(records)} image(s)")
                for r in records:
                    exists = "✓ file present" if os.path.exists(r["path"]) else "⚠️ file missing"
                    st.caption(f"  · {r['filename']} — {r['category']} ({exists})")
            if st.button("🗑️ Purge all orphaned image records", type="primary", key="purge_orphans"):
                purged = purge_orphaned_records(_valid_ids)
                st.success(f"Purged {purged} orphaned group(s).")
                st.rerun()
