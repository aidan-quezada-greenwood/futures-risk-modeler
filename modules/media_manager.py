"""
Media Manager — save, retrieve, and delete trade screenshot images.

Correct sequencing (enforced by the caller in app.py, not by this module):
  1. trade is validated and saved FIRST, producing a trade_id
  2. only then is save_image() called, using that trade_id
This module never creates image records for a trade_id that doesn't exist
in the caller's context — but it also doesn't verify against trades.csv
directly (kept decoupled); use find_orphaned_image_records() for that.

Storage layout:
  data/trade_images/{trade_id}/{uuid_prefix}_{safe_filename}

Metadata index:
  data/trade_images.json  ->  { "trade_id_str": [ {record}, ... ] }
"""
import json
import os
import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Set

IMAGES_DIR  = os.path.join("data", "trade_images")
META_FILE   = os.path.join("data", "trade_images.json")
MAX_BYTES   = 10 * 1024 * 1024   # 10 MB
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

CATEGORIES = [
    "Pre-trade", "Entry", "During Trade", "Management",
    "Exit", "Post-trade", "Higher Timeframe", "Other",
]


# ── Internal helpers ───────────────────────────────────────────────────────────

def _load_meta() -> dict:
    try:
        with open(META_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_meta(meta: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def _safe_name(original: str) -> str:
    base = os.path.basename(original)
    base = re.sub(r"[^\w.\-]", "_", base)
    root, ext = os.path.splitext(base)
    return root[:60] + ext.lower()


# ── Public API ─────────────────────────────────────────────────────────────────

def validate_file(filename: str, size_bytes: int) -> Optional[str]:
    """Return an error message if the file is invalid, else None."""
    ext = os.path.splitext(filename)[-1].lower()
    if ext not in ALLOWED_EXT:
        return f"Unsupported file type '{ext}'. Allowed: PNG, JPG, JPEG, WEBP."
    if size_bytes > MAX_BYTES:
        mb = size_bytes / 1024 / 1024
        return f"File is {mb:.1f} MB. Maximum allowed is 10 MB."
    return None


def ensure_trade_image_dir(trade_id: int) -> str:
    """Create (if needed) and return the image directory for a trade."""
    trade_dir = os.path.join(IMAGES_DIR, str(trade_id))
    os.makedirs(trade_dir, exist_ok=True)
    return trade_dir


def save_image(
    trade_id: int,
    file_bytes: bytes,
    original_filename: str,
    category: str = "Other",
    caption: str = "",
) -> Dict:
    """
    Save image bytes to disk and record metadata for an EXISTING trade_id.
    Caller is responsible for ensuring the trade was already saved.
    Raises ValueError if the file fails validation (caller should catch this
    per-file so one bad image doesn't block the others).
    """
    err = validate_file(original_filename, len(file_bytes))
    if err:
        raise ValueError(err)

    prefix    = uuid.uuid4().hex[:8]
    safe      = _safe_name(original_filename)
    filename  = f"{prefix}_{safe}"
    trade_dir = ensure_trade_image_dir(trade_id)
    rel_path  = os.path.join(trade_dir, filename)

    with open(rel_path, "wb") as f:
        f.write(file_bytes)

    record = {
        "filename":    filename,
        "path":        rel_path,
        "category":    category,
        "caption":     caption,
        "uploaded_at": datetime.now().isoformat(),
    }

    meta = _load_meta()
    key  = str(trade_id)
    meta.setdefault(key, []).append(record)
    _save_meta(meta)
    return record


def get_images(trade_id: int) -> List[Dict]:
    """
    Return ALL image metadata records for a trade, including ones whose
    file is missing from disk. Callers must check os.path.exists(record["path"])
    before rendering — this keeps missing-file handling visible rather than
    silently hiding the record.
    """
    meta = _load_meta()
    return list(meta.get(str(trade_id), []))


def update_image(trade_id: int, filename: str, updates: Dict) -> bool:
    """Update category/caption for an existing image record."""
    meta = _load_meta()
    key  = str(trade_id)
    for record in meta.get(key, []):
        if record["filename"] == filename:
            for k, v in updates.items():
                if k in ("category", "caption"):
                    record[k] = v
            _save_meta(meta)
            return True
    return False


def delete_image(trade_id: int, filename: str) -> bool:
    """Delete both the image file and its metadata record."""
    meta = _load_meta()
    key  = str(trade_id)
    records = meta.get(key, [])
    to_delete = [r for r in records if r["filename"] == filename]
    if not to_delete:
        return False

    for r in to_delete:
        try:
            os.remove(r["path"])
        except FileNotFoundError:
            pass  # already gone — still remove the metadata record below

    meta[key] = [r for r in records if r["filename"] != filename]
    if not meta[key]:
        del meta[key]
    _save_meta(meta)
    return True


def delete_all_images_for_trade(trade_id: int) -> int:
    """
    Delete all images (files + metadata) for a trade, then remove the
    now-empty trade image directory. Returns the count of images deleted.
    Used when a trade is deleted and the user opts to also remove its images.
    """
    records = get_images(trade_id)
    count = 0
    for r in records:
        if delete_image(trade_id, r["filename"]):
            count += 1

    trade_dir = os.path.join(IMAGES_DIR, str(trade_id))
    try:
        if os.path.isdir(trade_dir) and not os.listdir(trade_dir):
            os.rmdir(trade_dir)
    except OSError:
        pass
    return count


def find_orphaned_image_records(valid_trade_ids: Set[str]) -> Dict[str, List[Dict]]:
    """
    Return image metadata entries whose trade_id is not present in
    valid_trade_ids. Never deletes anything — purely diagnostic, so the
    caller can surface it and let the user decide whether to clean up.
    """
    meta = _load_meta()
    return {k: v for k, v in meta.items() if k not in valid_trade_ids}


def purge_orphaned_records(valid_trade_ids: Set[str]) -> int:
    """
    Explicitly remove orphaned metadata entries AND their files.
    This is a destructive, user-initiated action — never called automatically.
    Returns the number of trade-id groups purged.
    """
    orphans = find_orphaned_image_records(valid_trade_ids)
    meta = _load_meta()
    for trade_id_key, records in orphans.items():
        for r in records:
            try:
                os.remove(r["path"])
            except FileNotFoundError:
                pass
        meta.pop(trade_id_key, None)
        trade_dir = os.path.join(IMAGES_DIR, trade_id_key)
        try:
            if os.path.isdir(trade_dir) and not os.listdir(trade_dir):
                os.rmdir(trade_dir)
        except OSError:
            pass
    _save_meta(meta)
    return len(orphans)
