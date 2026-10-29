"""
Tag serialization — multi-select fields are stored as JSON arrays inside a
single CSV cell, e.g.  ["Liquidity Sweep", "VWAP Reclaim"]

deserialize_tags() also accepts the legacy comma-separated format
(e.g. "Liquidity Sweep, VWAP Reclaim") so old data keeps working without
a forced rewrite.
"""
import json
from typing import Any, List

import pandas as pd


def serialize_tags(tags: List[str]) -> str:
    """JSON-encode a list of tags for storage in a single CSV cell."""
    clean = [str(t).strip() for t in (tags or []) if str(t).strip()]
    return json.dumps(clean, ensure_ascii=False)


def deserialize_tags(raw: Any) -> List[str]:
    """
    Parse a tags cell back into a list of strings.

    Handles, in order:
      - None / NaN                          -> []
      - already a list                      -> cleaned list
      - JSON array string  '["A","B"]'      -> ["A", "B"]
      - legacy comma string 'A, B'          -> ["A", "B"]
      - single bare value 'A'               -> ["A"]
      - empty string                        -> []
    """
    if raw is None:
        return []
    if isinstance(raw, float) and pd.isna(raw):
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]

    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return []

    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except json.JSONDecodeError:
            pass  # fall through — treat as legacy comma-separated

    return [t.strip() for t in text.split(",") if t.strip()]
