"""
Library Manager — persistent CRUD for mistake-tag and confluence-tag libraries.

Both libraries follow the same pattern as setup_manager but are simpler
(no description/criteria sub-fields, just id/name/active).

Files:
  data/mistake_types.json
  data/confluence_types.json
"""
import json
import os
import re
from datetime import datetime
from typing import Dict, List

MISTAKE_FILE    = os.path.join("data", "mistake_types.json")
CONFLUENCE_FILE = os.path.join("data", "confluence_types.json")


# ── Generic helpers ────────────────────────────────────────────────────────────

def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(path: str, data: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())


def _get_names(path: str, key: str, include_inactive: bool = False) -> List[str]:
    data = _load(path)
    items = data.get(key, [])
    if not include_inactive:
        items = [i for i in items if i.get("active", True)]
    return sorted(i["name"] for i in items)


def _get_all(path: str, key: str, include_inactive: bool = False) -> List[Dict]:
    data = _load(path)
    items = data.get(key, [])
    if not include_inactive:
        items = [i for i in items if i.get("active", True)]
    return items


def _add(path: str, key: str, name: str) -> Dict:
    data = _load(path)
    items = data.get(key, [])
    if name.lower() in [i["name"].lower() for i in items]:
        raise ValueError(f"'{name}' already exists.")
    uid = _slug(name)
    existing_ids = {i["id"] for i in items}
    counter = 2
    base_uid = uid
    while uid in existing_ids:
        uid = f"{base_uid}_{counter}"
        counter += 1
    new_item = {"id": uid, "name": name.strip(), "active": True,
                "created_at": datetime.now().isoformat()}
    items.append(new_item)
    data[key] = items
    _save(path, data)
    return new_item


def _update(path: str, key: str, item_id: str, updates: Dict) -> bool:
    data = _load(path)
    for item in data.get(key, []):
        if item["id"] == item_id:
            for k, v in updates.items():
                if k not in ("id", "created_at"):
                    item[k] = v
            _save(path, data)
            return True
    return False


def _delete(path: str, key: str, item_id: str) -> bool:
    data = _load(path)
    before = len(data.get(key, []))
    data[key] = [i for i in data.get(key, []) if i["id"] != item_id]
    if len(data[key]) < before:
        _save(path, data)
        return True
    return False


# ── Mistakes ───────────────────────────────────────────────────────────────────

def get_mistake_names(include_inactive: bool = False) -> List[str]:
    return _get_names(MISTAKE_FILE, "mistakes", include_inactive)


def get_mistakes(include_inactive: bool = False) -> List[Dict]:
    return _get_all(MISTAKE_FILE, "mistakes", include_inactive)


def add_mistake(name: str) -> Dict:
    return _add(MISTAKE_FILE, "mistakes", name)


def update_mistake(item_id: str, updates: Dict) -> bool:
    return _update(MISTAKE_FILE, "mistakes", item_id, updates)


def archive_mistake(item_id: str) -> bool:
    return _update(MISTAKE_FILE, "mistakes", item_id, {"active": False})


def restore_mistake(item_id: str) -> bool:
    return _update(MISTAKE_FILE, "mistakes", item_id, {"active": True})


def delete_mistake(item_id: str) -> bool:
    return _delete(MISTAKE_FILE, "mistakes", item_id)


# ── Confluences ────────────────────────────────────────────────────────────────

def get_confluence_names(include_inactive: bool = False) -> List[str]:
    return _get_names(CONFLUENCE_FILE, "confluences", include_inactive)


def get_confluences(include_inactive: bool = False) -> List[Dict]:
    return _get_all(CONFLUENCE_FILE, "confluences", include_inactive)


def add_confluence(name: str) -> Dict:
    return _add(CONFLUENCE_FILE, "confluences", name)


def update_confluence(item_id: str, updates: Dict) -> bool:
    return _update(CONFLUENCE_FILE, "confluences", item_id, updates)


def archive_confluence(item_id: str) -> bool:
    return _update(CONFLUENCE_FILE, "confluences", item_id, {"active": False})


def restore_confluence(item_id: str) -> bool:
    return _update(CONFLUENCE_FILE, "confluences", item_id, {"active": True})


def delete_confluence(item_id: str) -> bool:
    return _delete(CONFLUENCE_FILE, "confluences", item_id)
