"""
Prop firm / account rule engine.

Supports any firm configuration. Key outputs:
  - remaining_buffer      : how far from account failure
  - losses_to_failure     : how many more full losses before you bust
  - safe_risk_per_trade   : conservative per-trade cap (min of 0.5% and 10% of buffer)
  - status                : ON TRACK | CAUTION | DANGER | FAILED

Drawdown types:
  static   - floor = starting_balance - max_drawdown  (Topstep style)
  trailing - floor = high_water_mark - max_drawdown   (Apex style)
"""
from dataclasses import dataclass
from typing import List, Optional

ON_TRACK = "ON TRACK"
CAUTION  = "CAUTION"
DANGER   = "DANGER"
FAILED   = "FAILED"


@dataclass
class FirmConfig:
    firm_name:             str   = "Custom"
    account_type:          str   = "Evaluation"   # Evaluation | Funded | Personal
    starting_balance:      float = 50_000.0
    profit_target:         float = 3_000.0
    max_drawdown:          float = 2_500.0
    daily_loss_limit:      float = 1_000.0
    drawdown_type:         str   = "static"        # "static" | "trailing"
    min_trading_days:      int   = 0
    consistency_rule:      bool  = False
    consistency_threshold: float = 0.40            # max fraction of total profit in one day


@dataclass
class FirmStatus:
    floor_balance:       float
    remaining_buffer:    float
    buffer_pct:          float
    distance_to_target:  float
    safe_risk_per_trade: float
    safe_daily_risk:     float
    losses_to_failure:   int
    wins_to_target:      Optional[int]
    status:              str
    consistency_warning: bool = False


def compute(
    config:            FirmConfig,
    current_balance:   float,
    high_water_mark:   float,
    realized_pnl:      float,
    cost_per_contract: float,
    avg_win_dollars:   Optional[float] = None,
    daily_pnls:        Optional[List[float]] = None,
) -> FirmStatus:
    # Floor balance (the line you cannot cross)
    if config.drawdown_type == "trailing":
        floor = high_water_mark - config.max_drawdown
    else:
        floor = config.starting_balance - config.max_drawdown

    buffer      = current_balance - floor
    buffer_pct  = (buffer / config.max_drawdown * 100) if config.max_drawdown > 0 else 100.0
    dist_target = config.profit_target - realized_pnl

    # Conservative per-trade ceiling: never exceed 10% of remaining buffer in one trade
    safe_trade = min(current_balance * 0.005, buffer * 0.10) if buffer > 0 else 0.0
    safe_daily = min(config.daily_loss_limit, buffer * 0.25) if buffer > 0 else 0.0

    losses_to_fail = (
        int(buffer / cost_per_contract) if cost_per_contract > 0 and buffer > 0 else 0
    )
    wins_to_target: Optional[int] = None
    if avg_win_dollars and avg_win_dollars > 0 and dist_target > 0:
        wins_to_target = int(dist_target / avg_win_dollars) + 1

    # Status
    if buffer <= 0:
        status = FAILED
    elif buffer_pct < 10:
        status = DANGER
    elif buffer_pct < 30:
        status = CAUTION
    else:
        status = ON_TRACK

    # Consistency rule check
    consistency_warning = False
    if config.consistency_rule and daily_pnls and realized_pnl > 0:
        best_day = max(daily_pnls)
        if best_day / realized_pnl > config.consistency_threshold:
            consistency_warning = True

    return FirmStatus(
        floor_balance=floor,
        remaining_buffer=buffer,
        buffer_pct=buffer_pct,
        distance_to_target=dist_target,
        safe_risk_per_trade=safe_trade,
        safe_daily_risk=safe_daily,
        losses_to_failure=losses_to_fail,
        wins_to_target=wins_to_target,
        status=status,
        consistency_warning=consistency_warning,
    )
