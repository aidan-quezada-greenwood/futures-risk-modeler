"""
Trade validation — enforce the minimum viable trade record before saving.

Required, always:
  - instrument
  - date
  - AND at least one of:
      - result_r  (non-zero)
      - dollar_pnl (non-zero)
      - entry AND exit both present (non-zero) — enough to derive a result

trade_id is auto-generated on save and is never part of validation input.

Design note: entry/stop/exit price fields default to 0.0 in the Streamlit
number_input widgets, and 0.0 is never a realistic MES/MGC price — so 0.0
safely means "not entered" for those fields. result_r and dollar_pnl use
the same convention (0.0 = not entered) which means a genuine break-even
trade logged as exactly 0 must also have entry/exit filled in to pass
validation. This is a deliberate, documented trade-off to keep the
"blank form" check simple and reliable.
"""
from typing import Any, Dict, List, Optional, Tuple


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s in ("—", "None", "nan", "NaT")


def validate_trade(payload: Dict) -> Tuple[bool, List[str]]:
    """
    Validate a trade payload before it is written to storage.
    Returns (is_valid, list_of_error_messages).
    An empty error list means the trade may be saved.
    """
    errors: List[str] = []

    if _is_blank(payload.get("instrument")):
        errors.append("Instrument is required.")

    if _is_blank(payload.get("date")):
        errors.append("Date is required.")

    result_r   = _to_float(payload.get("result_r"))
    dollar_pnl = _to_float(payload.get("dollar_pnl"))
    entry      = _to_float(payload.get("entry"))
    exit_price = _to_float(payload.get("exit"))

    has_result_r   = result_r is not None and result_r != 0.0
    has_dollar_pnl = dollar_pnl is not None and dollar_pnl != 0.0
    has_price_data = (entry is not None and entry != 0.0) and \
                      (exit_price is not None and exit_price != 0.0)

    if not (has_result_r or has_dollar_pnl or has_price_data):
        errors.append(
            "Provide at least one of: Result (R), P/L ($), or both Entry and Exit "
            "prices, so a result can be calculated."
        )

    return (len(errors) == 0, errors)
