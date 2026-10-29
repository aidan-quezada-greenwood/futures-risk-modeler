"""
Setup Library — persistent CRUD for trade setup types.

All setups are stored in data/setup_types.json.
Deleting or archiving a setup never alters historical trades that used it.
"""
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

SETUP_FILE = os.path.join("data", "setup_types.json")


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_raw() -> dict:
    try:
        with open(SETUP_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"setups": []}


def _save_raw(data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(SETUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())


# ── Public API ─────────────────────────────────────────────────────────────────

def load_setups(include_inactive: bool = False) -> List[Dict]:
    """Return list of setup dicts. Optionally include archived/inactive."""
    data = _load_raw()
    setups = data.get("setups", [])
    if not include_inactive:
        setups = [s for s in setups if s.get("active", True)]
    return setups


def get_setup_names(include_inactive: bool = False) -> List[str]:
    """Return sorted list of setup names for use in dropdowns."""
    return sorted(s["name"] for s in load_setups(include_inactive))


def get_setup_by_name(name: str) -> Optional[Dict]:
    for s in load_setups(include_inactive=True):
        if s["name"] == name:
            return s
    return None


def add_setup(
    name: str,
    description: str = "",
    entry_criteria: str = "",
    market_conditions: str = "",
    invalidation: str = "",
    notes: str = "",
) -> Dict:
    """Add a new setup. Returns the created setup dict."""
    data = _load_raw()
    # Prevent duplicate names
    existing_names = [s["name"].lower() for s in data.get("setups", [])]
    if name.lower() in existing_names:
        raise ValueError(f"Setup '{name}' already exists.")

    new_setup = {
        "id":                _slug(name),
        "name":              name.strip(),
        "description":       description,
        "entry_criteria":    entry_criteria,
        "market_conditions": market_conditions,
        "invalidation":      invalidation,
        "notes":             notes,
        "active":            True,
        "created_at":        datetime.now().isoformat(),
    }
    # Ensure unique id
    existing_ids = {s["id"] for s in data.get("setups", [])}
    uid = new_setup["id"]
    counter = 2
    while uid in existing_ids:
        uid = f"{new_setup['id']}_{counter}"
        counter += 1
    new_setup["id"] = uid

    data.setdefault("setups", []).append(new_setup)
    _save_raw(data)
    return new_setup


def update_setup(setup_id: str, updates: Dict) -> bool:
    """Update fields on an existing setup. Returns True on success."""
    data = _load_raw()
    for setup in data.get("setups", []):
        if setup["id"] == setup_id:
            for k, v in updates.items():
                if k not in ("id", "created_at"):   # protect immutable fields
                    setup[k] = v
            setup["updated_at"] = datetime.now().isoformat()
            _save_raw(data)
            return True
    return False


def archive_setup(setup_id: str) -> bool:
    """Mark a setup as inactive (preserves all historical trade data)."""
    return update_setup(setup_id, {"active": False})


def restore_setup(setup_id: str) -> bool:
    """Re-activate an archived setup."""
    return update_setup(setup_id, {"active": True})


def delete_setup(setup_id: str) -> bool:
    """
    Permanently delete a setup from the library.
    Historical trades referencing this setup are NOT affected.
    """
    data = _load_raw()
    before = len(data.get("setups", []))
    data["setups"] = [s for s in data.get("setups", []) if s["id"] != setup_id]
    if len(data["setups"]) < before:
        _save_raw(data)
        return True
    return False
