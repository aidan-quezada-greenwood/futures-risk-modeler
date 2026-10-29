"""
Migration utilities — run on every app startup before any tab renders.

Responsibilities:
  1. Ensure required directories exist.
  2. Create JSON library files with defaults if they don't exist.
  3. Detect and migrate trades.csv schema (add new columns, never delete old ones).
  4. Create backup of trades.csv before any schema change.

Never modifies existing data values — only adds blank columns.
"""
import json
import os
from datetime import datetime

import pandas as pd

from modules.backup_manager import backup_file

DATA_DIR            = "data"
BACKUPS_DIR         = os.path.join(DATA_DIR, "backups")
IMAGES_DIR          = os.path.join(DATA_DIR, "trade_images")
TRADES_FILE         = os.path.join(DATA_DIR, "trades.csv")
SETUP_TYPES_FILE    = os.path.join(DATA_DIR, "setup_types.json")
MISTAKE_FILE        = os.path.join(DATA_DIR, "mistake_types.json")
CONFLUENCE_FILE     = os.path.join(DATA_DIR, "confluence_types.json")
IMAGES_META_FILE    = os.path.join(DATA_DIR, "trade_images.json")
DAILY_FILE          = os.path.join(DATA_DIR, "daily_journal.csv")
SCHEMA_VERSION_FILE = os.path.join(DATA_DIR, "schema_version.json")

CURRENT_SCHEMA_VERSION = 2

# ── Trade journal schema ──────────────────────────────────────────────────────
# Original 16 columns are listed first so migration never reorders them.
ORIGINAL_COLUMNS = [
    "id", "date", "session", "instrument", "setup_type",
    "entry", "stop", "target", "exit",
    "contracts", "result_r", "dollar_pnl",
    "mistake_tag", "emotion_tag", "quality_grade", "notes",
]

NEW_COLUMNS = [
    # Market context
    "trade_time", "direction", "htf_bias", "market_condition",
    "volatility", "near_news", "news_minutes",
    # Pre-trade psychology (free-form + structured)
    "pre_trade_thoughts", "feeling_notes",
    "emotion_tags", "focus_level", "energy_level",
    "urge_to_trade", "confidence_setup", "following_plan", "trade_quality",
    # Setup / confluence — primary_setup is the single authoritative "main
    # strategy" field; setup_tags holds optional variations/sub-patterns
    # (JSON array); confluence_tags holds supporting evidence (JSON array).
    "primary_setup", "setup_tags", "confluence_tags", "key_level", "thesis",
    "entry_trigger", "invalidation_criteria", "planned_rr", "confidence_level",
    # Execution detail
    "entry_time", "exit_time", "trade_duration",
    "planned_risk_dollars", "commission_paid", "slippage_paid", "mfe_r", "mae_r",
    # Trade management
    "followed_stop", "moved_stop", "took_partials", "exited_early",
    "held_beyond_target", "added_to_position", "reduced_size",
    "emotional_interference", "management_notes",
    # Post-trade
    "post_trade_reflection", "followed_plan_post", "thesis_correct",
    "execution_good", "worth_taking", "did_well", "improve",
    "market_taught", "do_differently", "key_lesson",
    "process_score", "execution_score", "discipline_score",
    # Multi-select tags (comma-separated strings)
    "mistake_tags",
]

ALL_COLUMNS = ORIGINAL_COLUMNS + NEW_COLUMNS

DAILY_COLUMNS = [
    "date",
    # Pre-session
    "sleep_quality", "energy", "focus", "emotional_state",
    "market_expectations", "economic_events", "daily_bias",
    "max_daily_loss", "max_trades", "main_focus", "pre_session_thoughts",
    # Post-session
    "total_trades", "total_pnl", "total_r", "followed_plan_daily",
    "best_decision", "worst_decision", "biggest_lesson",
    "pattern_noticed", "next_session_focus", "post_session_thoughts",
]

# ── Default JSON content for library files ─────────────────────────────────────
DEFAULT_SETUPS = {
    "setups": [
        {"id": "vwap_bounce",        "name": "VWAP Bounce",           "description": "Price pulls back to VWAP and reclaims it with momentum.", "entry_criteria": "", "market_conditions": "Trending or ranging with clear VWAP respect", "invalidation": "Price closes below VWAP on volume", "notes": "", "active": True},
        {"id": "vwap_rejection",     "name": "VWAP Rejection",        "description": "Price approaches VWAP from below/above and is rejected.", "entry_criteria": "", "market_conditions": "", "invalidation": "", "notes": "", "active": True},
        {"id": "sr_break",           "name": "SR Break",              "description": "Break and retest of key support/resistance level.", "entry_criteria": "", "market_conditions": "", "invalidation": "", "notes": "", "active": True},
        {"id": "sr_rejection",       "name": "SR Rejection",          "description": "Price reaches key S/R and reverses.", "entry_criteria": "", "market_conditions": "", "invalidation": "", "notes": "", "active": True},
        {"id": "ema_pullback",       "name": "EMA Pullback",          "description": "Pullback to key EMA (9, 20, 50) in a trending market.", "entry_criteria": "", "market_conditions": "Trending", "invalidation": "", "notes": "", "active": True},
        {"id": "liquidity_sweep",    "name": "Liquidity Sweep",       "description": "Price sweeps a liquidity pool (equal highs/lows) and reverses.", "entry_criteria": "", "market_conditions": "", "invalidation": "", "notes": "", "active": True},
        {"id": "orb",                "name": "Opening Range Break",   "description": "Break of the first 5/15/30-minute opening range.", "entry_criteria": "", "market_conditions": "Directional days", "invalidation": "", "notes": "", "active": True},
        {"id": "trend_continuation", "name": "Trend Continuation",    "description": "Pullback entry in the direction of the higher-timeframe trend.", "entry_criteria": "", "market_conditions": "Trending", "invalidation": "", "notes": "", "active": True},
        {"id": "mean_reversion",     "name": "Mean Reversion",        "description": "Fade an extended move back toward mean (VWAP/EMA).", "entry_criteria": "", "market_conditions": "Ranging or overextended", "invalidation": "", "notes": "", "active": True},
        {"id": "other",              "name": "Other / Custom",        "description": "Trade doesn't fit a named setup.", "entry_criteria": "", "market_conditions": "", "invalidation": "", "notes": "", "active": True},
    ]
}

DEFAULT_MISTAKES = {
    "mistakes": [
        {"id": "no_mistake",           "name": "No Mistake",                    "active": True},
        {"id": "fomo_entry",           "name": "FOMO Entry",                    "active": True},
        {"id": "revenge_trade",        "name": "Revenge Trade",                 "active": True},
        {"id": "overtrading",          "name": "Overtrading",                   "active": True},
        {"id": "entered_too_early",    "name": "Entered Too Early",             "active": True},
        {"id": "entered_too_late",     "name": "Entered Too Late",              "active": True},
        {"id": "chased_price",         "name": "Chased Price",                  "active": True},
        {"id": "ignored_invalidation", "name": "Ignored Invalidation",          "active": True},
        {"id": "moved_stop_emotional", "name": "Moved Stop Emotionally",        "active": True},
        {"id": "oversized",            "name": "Oversized Position",            "active": True},
        {"id": "exited_winner_early",  "name": "Exited Winner Too Early",       "active": True},
        {"id": "held_loser_long",      "name": "Held Loser Too Long",           "active": True},
        {"id": "poor_conditions",      "name": "Traded in Poor Conditions",     "active": True},
        {"id": "no_confirmation",      "name": "Traded Without Confirmation",   "active": True},
        {"id": "ignored_htf",          "name": "Ignored Higher Timeframe",      "active": True},
        {"id": "ignored_news",         "name": "Ignored News",                  "active": True},
        {"id": "broke_daily_limit",    "name": "Broke Daily Loss Limit",        "active": True},
        {"id": "other_mistake",        "name": "Other",                         "active": True},
    ]
}

DEFAULT_CONFLUENCES = {
    "confluences": [
        {"id": "market_structure",  "name": "Market Structure",         "active": True},
        {"id": "support_resistance","name": "Support / Resistance",     "active": True},
        {"id": "liquidity_sweep",   "name": "Liquidity Sweep",          "active": True},
        {"id": "pdh_pdl",           "name": "Previous Day High/Low",    "active": True},
        {"id": "session_hl",        "name": "Session High/Low",         "active": True},
        {"id": "vwap",              "name": "VWAP",                     "active": True},
        {"id": "ema",               "name": "EMA",                      "active": True},
        {"id": "fibonacci",         "name": "Fibonacci",                "active": True},
        {"id": "volume",            "name": "Volume",                   "active": True},
        {"id": "momentum",          "name": "Momentum",                 "active": True},
        {"id": "htf_level",         "name": "Higher Timeframe Level",   "active": True},
        {"id": "break_retest",      "name": "Break and Retest",         "active": True},
        {"id": "supply_demand",     "name": "Supply / Demand",          "active": True},
        {"id": "other_confluence",  "name": "Other",                    "active": True},
    ]
}


# ── Public API ─────────────────────────────────────────────────────────────────

def ensure_data_dirs() -> None:
    """Create required directories if they don't exist."""
    for d in [DATA_DIR, BACKUPS_DIR, IMAGES_DIR]:
        os.makedirs(d, exist_ok=True)


def ensure_json_defaults() -> None:
    """Create JSON library files with defaults if they don't already exist."""
    defaults = {
        SETUP_TYPES_FILE:  DEFAULT_SETUPS,
        MISTAKE_FILE:      DEFAULT_MISTAKES,
        CONFLUENCE_FILE:   DEFAULT_CONFLUENCES,
        IMAGES_META_FILE:  {},
    }
    for path, content in defaults.items():
        if not os.path.exists(path):
            _write_json(path, content)


def backup_trades(reason: str = "auto", force: bool = True) -> str:
    """
    Copy trades.csv to backups/ with a timestamp suffix, via backup_manager
    (which also enforces the 30-file retention policy).
    Migration backups are always forced — schema changes are infrequent
    enough that throttling would defeat the purpose.
    """
    return backup_file(TRADES_FILE, reason, force=force)


def migrate_trades_schema() -> bool:
    """
    Add any missing columns to trades.csv with empty string defaults.
    Backs up the file first (mandatory, unthrottled). Returns True if
    migration was performed, False if the schema was already current.
    Never modifies existing cell values — only appends blank columns.
    """
    if not os.path.exists(TRADES_FILE):
        return False

    df = pd.read_csv(TRADES_FILE, dtype=str, keep_default_na=False)
    missing = [c for c in ALL_COLUMNS if c not in df.columns]
    if not missing:
        return False  # already up to date

    backup_trades("schema_migration", force=True)
    for col in missing:
        df[col] = ""
    # Reorder: original columns first, then new columns, then any unexpected extras
    existing_extras = [c for c in df.columns if c not in ALL_COLUMNS]
    ordered = [c for c in ALL_COLUMNS if c in df.columns] + existing_extras
    df = df[ordered]
    df.to_csv(TRADES_FILE, index=False)
    return True


def ensure_daily_journal() -> None:
    """Create daily_journal.csv with headers if it doesn't exist."""
    if not os.path.exists(DAILY_FILE):
        pd.DataFrame(columns=DAILY_COLUMNS).to_csv(DAILY_FILE, index=False)


def get_schema_version() -> int:
    """Return the recorded schema version, defaulting to 1 (legacy/no file)."""
    if os.path.exists(SCHEMA_VERSION_FILE):
        try:
            with open(SCHEMA_VERSION_FILE, encoding="utf-8") as f:
                return int(json.load(f).get("version", 1))
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return 1
    return 1


def set_schema_version(version: int) -> None:
    """Record the current schema version, keeping a short migration history."""
    existing = {}
    if os.path.exists(SCHEMA_VERSION_FILE):
        try:
            with open(SCHEMA_VERSION_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}
    history = existing.get("history", [])
    now = datetime.now().isoformat()
    history.append({"version": version, "migrated_at": now})
    _write_json(SCHEMA_VERSION_FILE, {
        "version": version,
        "updated_at": now,
        "history": history,
    })


def run_all() -> dict:
    """
    Run the full migration sequence. Call once on app startup.
    Returns a dict describing what was done.
    """
    ensure_data_dirs()
    ensure_json_defaults()
    migrated = migrate_trades_schema()   # idempotent — safe to call every run

    old_version = get_schema_version()
    if old_version < CURRENT_SCHEMA_VERSION:
        set_schema_version(CURRENT_SCHEMA_VERSION)

    ensure_daily_journal()
    return {
        "schema_migrated": migrated,
        "schema_version": get_schema_version(),
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _write_json(path: str, content) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)
