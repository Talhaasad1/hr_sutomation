"""
backup.py
Automated MongoDB backup for the ATS Portal.

Preferred method: shells out to `mongodump` (the official MongoDB tool) if
it's available on the host/container — this is the most complete and
reliable way to back up MongoDB.

Fallback: if `mongodump` isn't installed, does a pure-Python export of every
collection to JSON using pymongo (no extra binary required). Less complete
than mongodump (e.g. no exact BSON type fidelity for edge cases), but good
enough to recover the app's data in an emergency.

Old backups are automatically rotated out (keeps the most recent N by
default) so backups don't silently fill up the disk.

Usage:
    python backup.py                  # run once
    python backup.py --keep 14        # keep the last 14 backups instead of 7

Schedule it with cron (Linux/macOS), e.g. daily at 2 AM:
    0 2 * * * cd /path/to/ats_portal && /path/to/venv/bin/python backup.py >> backup.log 2>&1

Or Windows Task Scheduler running the same command daily.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, date

import config
import db

BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")


def _json_default(obj):
    """Handle MongoDB ObjectId / datetime when dumping to JSON."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def backup_with_mongodump(target_dir: str) -> bool:
    if shutil.which("mongodump") is None:
        return False
    try:
        subprocess.run(
            ["mongodump", "--uri", config.MONGO_URI, "--db", config.DB_NAME, "--out", target_dir],
            check=True, capture_output=True, text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[backup] mongodump failed, falling back to JSON export: {e.stderr}")
        return False


def backup_with_json_export(target_dir: str):
    os.makedirs(target_dir, exist_ok=True)
    collections = [
        "users", "departments", "jobs", "candidates", "applications", "interviews",
        "email_templates", "emails", "notifications", "offers", "system_logs",
        "settings", "sessions", "employees", "background_tasks",
    ]
    for name in collections:
        docs = list(db.db[name].find())
        out_path = os.path.join(target_dir, f"{name}.json")
        with open(out_path, "w") as f:
            json.dump(docs, f, default=_json_default, indent=2)
    print(f"[backup] JSON export of {len(collections)} collections written to {target_dir}")


def rotate_old_backups(keep: int):
    if not os.path.isdir(BACKUP_DIR):
        return
    entries = sorted(
        (os.path.join(BACKUP_DIR, d) for d in os.listdir(BACKUP_DIR)
         if os.path.isdir(os.path.join(BACKUP_DIR, d))),
        key=os.path.getmtime,
    )
    while len(entries) > keep:
        oldest = entries.pop(0)
        shutil.rmtree(oldest, ignore_errors=True)
        print(f"[backup] Removed old backup: {oldest}")


def main():
    parser = argparse.ArgumentParser(description="Back up the ATS Portal MongoDB database.")
    parser.add_argument("--keep", type=int, default=7, help="Number of recent backups to retain (default: 7)")
    args = parser.parse_args()

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = os.path.join(BACKUP_DIR, timestamp)

    print(f"[backup] Starting backup at {timestamp} ...")
    used_mongodump = backup_with_mongodump(target_dir)
    if used_mongodump:
        print(f"[backup] mongodump completed successfully -> {target_dir}")
    else:
        print("[backup] mongodump not available/failed — using pure-Python JSON export instead.")
        backup_with_json_export(target_dir)

    rotate_old_backups(args.keep)
    print("[backup] Done.")


if __name__ == "__main__":
    sys.exit(main())
