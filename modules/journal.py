"""
Trade journal CRUD — CSV persistence.
Backward-compatible: keeps all original columns. New columns added by migration.py.

Backup policy (via backup_manager):
  - update() (standard single-trade edit) -> throttled, once per calendar day
  - bulk_update() (multi-trade edit)       -> mandatory, every call
  - remove()                               -> mandatory, every call
"""
import os
from typing import Optional

import pandas as pd

from modules.backup_manager import backup_file

DATA_DIR    = "data"
TRADES_FILE = os.path.join(DATA_DIR, "trades.csv")

# ── Static option lists (used in dropdowns across the app) ────────────────────
SESSIONS = [
    "New York AM", "New York PM", "London", "Overlap (London/NY)",
    "Asian", "Afternoon", "Other",
]

# Historical choices retained for existing journal records.
SETUPS = [
    "VWAP Bounce", "VWAP Rejection", "SR Break", "SR Rejection",
    "EMA Pullback", "Liquidity Sweep", "Opening Range Break",
    "Trend Continuation", "Mean Reversion", "Other",
]

MISTAKES = [
    "No Mistake", "FOMO Entry", "Revenge Trade", "Overtrading",
    "Entered Too Early", "Entered Too Late", "Chased Price",
    "Ignored Invalidation", "Moved Stop Emotionally", "Oversized Position",
    "Exited Winner Too Early", "Held Loser Too Long",
    "Traded in Poor Conditions", "Traded Without Confirmation",
    "Ignored Higher Timeframe", "Ignored News", "Broke Daily Loss Limit", "Other",
]

EMOTIONS = [
    "Calm", "Focused", "Confident", "Anxious", "Frustrated", "FOMO",
    "Revenge-minded", "Tired", "Distracted", "Excited", "Bored", "Other",
]

GRADES        = ["A+", "A", "B", "C", "D", "F"]
TRADE_QUALITY = ["A+", "A", "B", "C", "Impulsive"]

YN_OPTIONS  = ["—", "Yes", "No"]
YNP_OPTIONS = ["—", "Yes", "Mostly", "No", "Unsure"]
YNA_OPTIONS = ["—", "Yes", "No", "N/A"]

HTF_BIAS_OPTIONS    = ["—", "Bullish", "Bearish", "Neutral", "Unclear"]
MARKET_COND_OPTIONS = [
    "—", "Trending", "Ranging", "Breakout", "Reversal",
    "High Volatility", "Low Volatility", "Choppy", "Unclear",
]
VOLATILITY_OPTIONS = ["—", "Low", "Normal", "High", "Extreme"]
DIRECTION_OPTIONS  = ["—", "Long", "Short"]

ORIGINAL_COLUMNS = [
    "id", "date", "session", "instrument", "setup_type",
    "entry", "stop", "target", "exit",
    "contracts", "result_r", "dollar_pnl",
    "mistake_tag", "emotion_tag", "quality_grade", "notes",
]

NUMERIC_COLS = [
    "id", "result_r", "dollar_pnl", "entry", "stop", "target", "exit",
    "contracts", "planned_rr", "confidence_level", "planned_risk_dollars",
    "commission_paid", "slippage_paid", "mfe_r", "mae_r",
    "process_score", "execution_score", "discipline_score",
    "focus_level", "energy_level", "urge_to_trade", "confidence_setup",
    "news_minutes",
]


# ── CRUD ───────────────────────────────────────────────────────────────────────

def load() -> pd.DataFrame:
    """
    Load all trades. Returns empty DataFrame with ORIGINAL_COLUMNS if no file.

    Reads with dtype=str and keep_default_na=False deliberately: pandas infers
    a column's dtype from its content, and a text column that happens to be
    entirely blank so far (very common here — dozens of optional detailed
    fields stay unset in fast mode) would otherwise be inferred as float64
    (all-NaN). The first time a real string is written into such a column,
    pandas' dtype casting rejects it. Reading everything as string up front
    and then explicitly re-parsing the known numeric/date columns avoids
    that entirely, without changing numeric behavior (still NaN on blank).
    """
    if os.path.exists(TRADES_FILE):
        try:
            df = pd.read_csv(TRADES_FILE, dtype=str, keep_default_na=False)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            for col in NUMERIC_COLS:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=ORIGINAL_COLUMNS)


def get_by_id(trade_id: int) -> Optional[dict]:
    """Return a single trade as a dict, or None if not found."""
    df = load()
    if df.empty or "id" not in df.columns:
        return None
    match = df[df["id"] == trade_id]
    if match.empty:
        return None
    row = match.iloc[0].where(pd.notna(match.iloc[0]), other=None)
    return row.to_dict()


def add(trade: dict) -> pd.DataFrame:
    """
    Append a new trade. Caller (app.py) is responsible for calling
    modules.validation.validate_trade() first — this function does not
    re-validate, to keep the storage layer decoupled from UI-facing rules.
    Returns the updated DataFrame.
    """
    df  = load()
    ids = df["id"].dropna() if "id" in df.columns and not df.empty else pd.Series(dtype=float)
    next_id = int(ids.max()) + 1 if not ids.empty else 1
    trade["id"] = next_id
    df = pd.concat([df, pd.DataFrame([trade])], ignore_index=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(TRADES_FILE, index=False)
    return df


def update(trade_id: int, updates: dict) -> bool:
    """
    Update fields on an existing trade.
    Backup policy: throttled — at most one backup per calendar day for
    standard single-trade edits (force=False).
    Returns True on success, False if the trade_id doesn't exist.
    """
    df = load()
    if df.empty or "id" not in df.columns:
        return False
    mask = df["id"] == trade_id
    if not mask.any():
        return False

    backup_file(TRADES_FILE, "edit", force=False)

    for col, val in updates.items():
        if col == "id":
            continue
        if col not in df.columns:
            df[col] = None
        df.loc[mask, col] = val

    df.to_csv(TRADES_FILE, index=False)
    return True


def bulk_update(trade_ids: list, updates: dict) -> int:
    """
    Apply the same field updates to multiple trades at once (e.g. re-tagging
    a setup name across many historical trades). Always backs up first,
    regardless of how recently a backup was made.
    Returns the number of trades updated.
    """
    df = load()
    if df.empty or "id" not in df.columns or not trade_ids:
        return 0
    mask = df["id"].isin(trade_ids)
    n = int(mask.sum())
    if n == 0:
        return 0

    backup_file(TRADES_FILE, "bulk_edit", force=True)

    for col, val in updates.items():
        if col == "id":
            continue
        if col not in df.columns:
            df[col] = None
        df.loc[mask, col] = val

    df.to_csv(TRADES_FILE, index=False)
    return n


def remove(trade_id: int) -> pd.DataFrame:
    """Delete a trade by ID. Always backs up first (mandatory, unthrottled)."""
    backup_file(TRADES_FILE, "delete", force=True)
    df = load()
    df = df[df["id"] != trade_id].reset_index(drop=True)
    df.to_csv(TRADES_FILE, index=False)
    return df
