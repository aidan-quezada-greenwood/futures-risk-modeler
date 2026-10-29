"""Pre-trade risk checks for a proposed futures position."""

from dataclasses import dataclass, field
import math
from typing import List

PROCEED = "PROCEED"
WARN = "WARN"
REDUCE = "REDUCE"
BLOCK = "BLOCK"


@dataclass
class CheckResult:
    status: str
    blocks: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rr_ratio: float = 0.0
    dollar_risk_total: float = 0.0
    daily_limit_pct_used: float = 0.0
    suggested_contracts: int = 0


def check(
    daily_pnl: float,
    trades_today: int,
    daily_loss_limit: float,
    max_trades_per_day: int,
    proposed_stop_ticks: int,
    proposed_target_ticks: int,
    proposed_contracts: int,
    max_contracts: int,
    max_stop_ticks: int,
    min_rr_ratio: float,
    prop_firm_buffer: float,
    cost_per_contract: float,
) -> CheckResult:
    """Classify a trade and return the maximum size allowed by hard risk limits.

    A zero daily-loss limit disables that particular limit. The prop-firm
    buffer, in contrast, must be positive because this application computes
    it from an account's drawdown floor.
    """
    blocks: List[str] = []
    warnings: List[str] = []

    if proposed_contracts <= 0:
        blocks.append("The proposed position must contain at least one contract.")
    if proposed_stop_ticks <= 0:
        blocks.append("Stop distance must be positive.")
    if not math.isfinite(cost_per_contract) or cost_per_contract <= 0:
        blocks.append("Cost per contract must be a positive, finite number.")
    if max_contracts <= 0:
        blocks.append("Risk budget does not permit even one contract.")
    if prop_firm_buffer <= 0:
        blocks.append("No drawdown buffer remains; trading is blocked.")
    if daily_loss_limit > 0 and daily_pnl <= -daily_loss_limit:
        blocks.append("Daily loss limit already hit. No more trades today.")
    if max_trades_per_day > 0 and trades_today >= max_trades_per_day:
        blocks.append(f"Max trades per day ({max_trades_per_day}) already reached.")

    total_risk = max(0, proposed_contracts) * max(0.0, cost_per_contract) if math.isfinite(cost_per_contract) else 0.0
    rr = proposed_target_ticks / proposed_stop_ticks if proposed_stop_ticks > 0 and proposed_target_ticks > 0 else 0.0
    # Projected daily loss if the proposed stop is hit, after realized P/L.
    projected_loss = max(0.0, total_risk - daily_pnl)
    limit_pct = min(100.0, 100 * projected_loss / daily_loss_limit) if daily_loss_limit > 0 else 0.0

    allowed = max(0, max_contracts)
    if cost_per_contract > 0 and math.isfinite(cost_per_contract):
        if daily_loss_limit > 0:
            remaining_daily = max(0.0, daily_loss_limit + daily_pnl)
            # At the specified limit (equal to the floor), don't breach it.
            allowed_daily = max(0, math.floor((remaining_daily + 1e-9) / cost_per_contract))
            allowed = min(allowed, allowed_daily)
        if prop_firm_buffer > 0:
            # Risk must stay strictly below the remaining failure buffer.
            allowed_buffer = max(0, math.ceil(prop_firm_buffer / cost_per_contract) - 1)
            allowed = min(allowed, allowed_buffer)

    if proposed_contracts > allowed and not blocks:
        if allowed == 0:
            blocks.append("Insufficient daily-loss or drawdown buffer for one contract.")
        else:
            warnings.append(f"Reduce position to {allowed} contract(s) to respect risk limits.")

    if proposed_stop_ticks > max_stop_ticks:
        warnings.append(f"Stop of {proposed_stop_ticks} ticks exceeds your max of {max_stop_ticks}.")
    if proposed_target_ticks > 0 and rr < min_rr_ratio:
        warnings.append(f"R:R of {rr:.2f} is below your minimum of {min_rr_ratio:.1f}.")
    if prop_firm_buffer > 0 and total_risk > 0 and prop_firm_buffer < 3 * total_risk:
        warnings.append("Remaining drawdown buffer is less than 3× the proposed trade risk.")

    if blocks:
        status, suggested = BLOCK, 0
    elif proposed_contracts > allowed:
        status, suggested = REDUCE, allowed
    elif warnings:
        status, suggested = WARN, proposed_contracts
    else:
        status, suggested = PROCEED, proposed_contracts

    return CheckResult(
        status=status,
        blocks=blocks,
        warnings=warnings,
        rr_ratio=rr,
        dollar_risk_total=total_risk,
        daily_limit_pct_used=limit_pct,
        suggested_contracts=suggested,
    )
