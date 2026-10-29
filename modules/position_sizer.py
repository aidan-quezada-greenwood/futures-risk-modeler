"""
Position sizing math for futures contracts.

  dollar_risk         = account_size x (risk_pct / 100)
  stop_cost           = stop_ticks x tick_value
  friction            = (commission x 2) + (slippage_ticks x tick_value x 2)
  cost_per_contract   = stop_cost + friction
  max_contracts       = floor(dollar_risk / cost_per_contract)
"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class SizeResult:
    dollar_risk:        float
    stop_cost:          float
    friction_cost:      float
    cost_per_contract:  float
    max_contracts:      int
    effective_risk_pct: float
    warnings:           List[str] = field(default_factory=list)


def calculate(
    account_size:        float,
    risk_pct:            float,       # e.g. 0.5 means 0.5%
    instrument:          Dict,
    stop_ticks:          int,
    commission_per_side: float,
    slippage_ticks:      float = 0.5,
) -> SizeResult:
    tick_value  = instrument["tick_value"]
    dollar_risk = account_size * (risk_pct / 100.0)
    stop_cost   = stop_ticks * tick_value
    friction    = (commission_per_side * 2) + (slippage_ticks * tick_value * 2)
    cost_per    = stop_cost + friction

    max_contracts = int(dollar_risk / cost_per) if cost_per > 0 else 0
    effective     = (max_contracts * cost_per / account_size * 100) if account_size > 0 else 0.0

    warnings: List[str] = []
    if risk_pct > 2.0:
        warnings.append(
            f"Risk of {risk_pct:.1f}% is high; consider a smaller risk budget."
        )
    if stop_ticks > instrument.get("max_stop_ticks", 20):
        warnings.append(
            f"Stop of {stop_ticks} ticks is wider than typical for "
            f"{instrument.get('name', 'this instrument')}."
        )
    if max_contracts == 0:
        warnings.append(
            f"Cannot size even 1 contract. Need ${cost_per:.2f}/contract "
            f"but risk budget is ${dollar_risk:.2f}. "
            "Reduce risk per contract or leave the trade; do not exceed the risk budget."
        )

    return SizeResult(
        dollar_risk=dollar_risk,
        stop_cost=stop_cost,
        friction_cost=friction,
        cost_per_contract=cost_per,
        max_contracts=max_contracts,
        effective_risk_pct=effective,
        warnings=warnings,
    )
