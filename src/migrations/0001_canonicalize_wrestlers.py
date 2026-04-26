"""
Phase 1f migration: re-canonicalize wrestlers.canonical_name and merge duplicates.

Applies the updated _canonicalize_name parser logic to every existing
wrestlers row, groups rows that collapse to the same cleaned name, picks
the lowest-id row as the keeper, re-points match_participants.wrestler_id
to the keeper, and deletes the merged-away + Type-3-dropped rows.

Idempotent. Running twice after success is a no-op.

Safety: refuses to run unless data/wrestling.db.pre-1f.bak exists. The
project root's apply procedure is responsible for creating that backup
before invoking this script.

Run from project root:
    .venv/bin/python src/migrations/0001_canonicalize_wrestlers.py
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fandom_scraper import _canonicalize_name  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "wrestling.db"
BACKUP_PATH = PROJECT_ROOT / "data" / "wrestling.db.pre-1f.bak"


def migrate(db_path: Path = DB_PATH, backup_path: Path = BACKUP_PATH) -> None:
    if not backup_path.exists():
        raise SystemExit(
            f"refusing to run: backup not found at {backup_path}\n"
            f"create it first:  cp {db_path} {backup_path}"
        )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    rows = cur.execute("SELECT id, canonical_name FROM wrestlers").fetchall()
    before_count = len(rows)

    proposed: dict[int, str] = {}
    drops: list[int] = []
    for r in rows:
        new_name = _canonicalize_name(r["canonical_name"])
        if not new_name:
            drops.append(r["id"])
        else:
            proposed[r["id"]] = new_name

    by_canonical: dict[str, list[int]] = defaultdict(list)
    for old_id, new_name in proposed.items():
        by_canonical[new_name].append(old_id)

    merge_map: dict[int, int] = {}
    rename_count = 0
    for new_name, ids in by_canonical.items():
        keeper = min(ids)
        for old_id in ids:
            if old_id != keeper:
                merge_map[old_id] = keeper

    # Order matters for the wrestlers.canonical_name UNIQUE constraint.
    # Delete merged-away + dropped rows BEFORE updating keepers, so a keeper
    # whose new canonical_name matches a soon-to-be-deleted row's existing
    # name doesn't violate UNIQUE during the UPDATE.
    with con:
        for old_id, keeper_id in merge_map.items():
            con.execute(
                "UPDATE match_participants SET wrestler_id = ? WHERE wrestler_id = ?",
                (keeper_id, old_id),
            )
        for old_id in drops:
            con.execute(
                "UPDATE match_participants SET wrestler_id = NULL WHERE wrestler_id = ?",
                (old_id,),
            )
        for old_id in merge_map:
            con.execute("DELETE FROM wrestlers WHERE id = ?", (old_id,))
        for old_id in drops:
            con.execute("DELETE FROM wrestlers WHERE id = ?", (old_id,))
        for new_name, ids in by_canonical.items():
            keeper = min(ids)
            cur2 = con.execute(
                "SELECT canonical_name FROM wrestlers WHERE id = ?", (keeper,)
            )
            current = cur2.fetchone()[0]
            if current != new_name:
                con.execute(
                    "UPDATE wrestlers SET canonical_name = ? WHERE id = ?",
                    (new_name, keeper),
                )
                rename_count += 1

    after_count = cur.execute("SELECT COUNT(*) FROM wrestlers").fetchone()[0]
    con.close()

    print(f"backup verified: {backup_path}")
    print(f"before: {before_count} wrestler rows")
    print(f"renamed: {rename_count} keepers (canonical_name changed)")
    print(f"merged: {len(merge_map)} rows (re-pointed to a keeper)")
    print(f"dropped: {len(drops)} rows (Type-3 junk, wrestler_id set NULL)")
    print(f"after: {after_count} wrestler rows")


if __name__ == "__main__":
    migrate()
