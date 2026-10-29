"""
Daily Journal — pre-session and post-session notes stored in daily_journal.csv.

One row per date. Calling save_day() with a date that already exists updates it.
"""
import os
from datetime import date, datetime
from typing import Dict, Optional

import pandas as pd

DAILY_FILE = os.path.join("data", "daily_journal.csv")

COLUMNS = [
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

NUMERIC_COLS = [
    "sleep_quality", "energy", "focus",
    "max_daily_loss", "max_trades",
    "total_trades", "total_pnl", "total_r",
]


def load() -> pd.DataFrame:
    """
    Load all daily journal entries. Returns empty DataFrame if file missing.

    Same dtype fix as journal.load(): read as string first so blank text
    columns (pre_session_thoughts, emotional_state, etc.) don't get
    inferred as float64 when every entry so far has been empty.
    """
    if os.path.exists(DAILY_FILE):
        try:
            df = pd.read_csv(DAILY_FILE, dtype=str, keep_default_na=False)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
            for col in NUMERIC_COLS:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except Exception:
            pass
    return pd.DataFrame(columns=COLUMNS)


def get_day(target_date: date) -> Optional[Dict]:
    """Return the journal entry for a specific date, or None if not found."""
    df = load()
    if df.empty or "date" not in df.columns:
        return None
    match = df[df["date"].dt.date == target_date]
    if match.empty:
        return None
    row = match.iloc[0].where(pd.notna(match.iloc[0]), other=None).to_dict()
    return row


def save_day(entry_date: date, data: Dict) -> None:
    """
    Upsert a daily journal entry. If a row for entry_date exists, update it.
    If not, append a new row. All fields are optional.
    """
    df = load()
    data["date"] = str(entry_date)

    if not df.empty and "date" in df.columns:
        mask = df["date"].dt.date == entry_date
        if mask.any():
            # Update existing row
            for col, val in data.items():
                if col in df.columns:
                    df.loc[mask, col] = val
                else:
                    df[col] = None
                    df.loc[mask, col] = val
            _persist(df)
            return

    # Append new row — fill missing columns with empty string
    new_row = {col: data.get(col, "") for col in COLUMNS}
    new_df  = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    _persist(new_df)


def get_recent(n: int = 7) -> pd.DataFrame:
    """Return the n most recent daily journal entries."""
    df = load()
    if df.empty:
        return df
    return df.sort_values("date", ascending=False).head(n)


def _persist(df: pd.DataFrame) -> None:
    os.makedirs("data", exist_ok=True)
    df.to_csv(DAILY_FILE, index=False)
