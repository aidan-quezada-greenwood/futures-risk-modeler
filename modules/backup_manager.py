"""
Backup Manager — centralized backup creation with throttling and retention.

Policy:
  - mandatory (force=True):  migration, delete, bulk edit
  - throttled (force=False): standard single-field edits — at most once
    per calendar day per (source file, reason) pair
  - retention: keep the most recent MAX_BACKUPS files across data/backups/,
    oldest pruned first (by modification time)
"""
import glob
import os
import shutil
from datetime import datetime

BACKUPS_DIR  = os.path.join("data", "backups")
MAX_BACKUPS  = 30


def backup_file(source_path: str, reason: str, force: bool = False) -> str:
    """
    Copy source_path into data/backups/ with a reason + timestamp suffix.

    If force is False and a backup with this (basename, reason) pair already
    exists for today, no new backup is written and "" is returned.

    Returns the backup file path, or "" if no backup was created
    (source missing, or already backed up today under a throttled reason).
    """
    if not os.path.exists(source_path):
        return ""

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    base      = os.path.splitext(os.path.basename(source_path))[0]
    today_str = datetime.now().strftime("%Y%m%d")

    if not force:
        pattern = os.path.join(BACKUPS_DIR, f"{base}_{reason}_{today_str}_*")
        if glob.glob(pattern):
            return ""  # already have a throttled backup for this reason today

    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext  = os.path.splitext(source_path)[1] or ".csv"
    dest = os.path.join(BACKUPS_DIR, f"{base}_{reason}_{ts}{ext}")
    shutil.copy2(source_path, dest)

    prune_backups()
    return dest


def prune_backups(keep: int = MAX_BACKUPS) -> int:
    """
    Delete oldest backup files beyond `keep` most recent (by mtime).
    Returns the number of files removed.
    """
    if not os.path.isdir(BACKUPS_DIR):
        return 0
    files = sorted(
        glob.glob(os.path.join(BACKUPS_DIR, "*")),
        key=os.path.getmtime,
        reverse=True,
    )
    removed = 0
    for f in files[keep:]:
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    return removed


def list_backups() -> list:
    """Return backup file metadata, most recent first."""
    if not os.path.isdir(BACKUPS_DIR):
        return []
    files = sorted(
        glob.glob(os.path.join(BACKUPS_DIR, "*")),
        key=os.path.getmtime,
        reverse=True,
    )
    return [
        {
            "path":  f,
            "name":  os.path.basename(f),
            "mtime": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(),
            "size":  os.path.getsize(f),
        }
        for f in files
    ]
