"""Trade-performance summaries and exploratory statistical diagnostics."""

from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy.stats import t as student_t


def core(df: pd.DataFrame) -> Dict:
    """Summarize valid R-multiple observations from the trade journal.

    The t-test is exploratory, assumes independent observations, and does not
    adjust for testing several trading strategies or repeatedly checking results.
    """
    if df.empty or "result_r" not in df.columns:
        return {}

    numeric_r = pd.to_numeric(df["result_r"], errors="coerce")
    r = numeric_r.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    n = len(r)
    if n == 0:
        return {"n_trades": 0}

    wins = r[r > 0]
    losses = r[r < 0]
    win_rate = len(wins) / n
    avg_win_r = float(wins.mean()) if not wins.empty else 0.0
    avg_loss_r = float(abs(losses.mean())) if not losses.empty else 0.0

    # The sample mean handles winning, losing AND break-even trades correctly.
    mean_r = float(r.mean())
    expectancy = mean_r
    gross_wins = float(wins.sum())
    gross_losses = float(abs(losses.sum()))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    # A one-sided Student t-test for H1: population mean R > 0.
    # Degrees of freedom, n - 1, matter for the critical threshold.
    std_r = float(r.std(ddof=1)) if n > 1 else 0.0
    t_stat = mean_r * np.sqrt(n) / std_r if std_r > 0 else None
    p_value = float(student_t.sf(t_stat, df=n - 1)) if t_stat is not None else None

    if n < 20:
        edge_label = f"Only {n} valid trades — collect more observations before testing the mean."
        edge_tier = "info"
    elif p_value is None:
        edge_label = "No variation in R outcomes — a t-test cannot be computed."
        edge_tier = "info"
    elif mean_r > 0 and p_value < 0.05:
        edge_label = (
            f"Exploratory evidence of positive mean R (one-sided p = {p_value:.3g}, "
            f"t = {t_stat:.2f}). Not proof of a repeatable trading edge."
        )
        edge_tier = "success"
    elif mean_r > 0:
        edge_label = (
            f"Positive sample mean, but insufficient evidence from this t-test "
            f"(one-sided p = {p_value:.3g})."
        )
        edge_tier = "warning"
    else:
        edge_label = "No positive sample mean R. Review the strategy and collect more trades."
        edge_tier = "info"

    cum_r = r.cumsum().reset_index(drop=True)
    max_dd_r = float((cum_r - cum_r.cummax().clip(lower=0)).min())

    streak = max_streak = 0
    for value in r:
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)

    pnl_total: Optional[float] = None
    if "dollar_pnl" in df.columns:
        dollar_values = pd.to_numeric(df["dollar_pnl"], errors="coerce")
        pnl_total = float(dollar_values.replace([np.inf, -np.inf], np.nan).sum())

    return {
        "n_trades": n,
        "n_wins": int(len(wins)),
        "n_losses": int(len(losses)),
        "win_rate": win_rate,
        "avg_win_r": avg_win_r,
        "avg_loss_r": avg_loss_r,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_dd_r": max_dd_r,
        "max_losing_streak": max_streak,
        "t_stat": t_stat,
        "p_value": p_value,
        "edge_label": edge_label,
        "edge_tier": edge_tier,
        "cum_r": cum_r.tolist(),
        "pnl_total": pnl_total,
    }


def by_field(df: pd.DataFrame, field: str) -> Optional[pd.DataFrame]:
    """Summarize trade outcomes by setup, session, grade, or another category."""
    if df.empty or field not in df.columns or "result_r" not in df.columns:
        return None

    valid = df[[field, "result_r"]].copy()
    valid["result_r"] = pd.to_numeric(valid["result_r"], errors="coerce")
    valid["result_r"] = valid["result_r"].replace([np.inf, -np.inf], np.nan)
    valid = valid.dropna(subset=["result_r"])
    if valid.empty:
        return None

    summary = (
        valid.groupby(field)["result_r"]
        .agg(trades="count", avg_r="mean", total_r="sum")
        .reset_index()
    )
    win_rates = (
        valid.groupby(field)["result_r"]
        .apply(lambda results: (results > 0).mean())
        .reset_index(name="win_pct")
    )
    return summary.merge(win_rates, on=field).sort_values("avg_r", ascending=False)
