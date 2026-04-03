"""
Migration script: assign all unowned scrims to team "Fui sem TP".

Usage:
    python scripts/migrate_scrims_to_team.py [--dry-run] [--owner-email EMAIL]

Steps:
1. Ensures auth.db has the "Fui sem TP" team (creates it if absent).
2. Sets team_id on every match in scrims.db where team_id IS NULL.
3. Optionally assigns an existing user as owner of that team.

Safe to re-run: already-assigned matches are not touched.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTH_DB = REPO_ROOT / "data" / "auth.db"
SCRIMS_DB = REPO_ROOT / "data" / "scrims.db"
TEAM_NAME = "Fui sem TP"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_team(dry_run: bool) -> int:
    """Return team id for TEAM_NAME, creating it if necessary."""
    with _connect(AUTH_DB) as conn:
        row = conn.execute("SELECT id FROM teams WHERE name = ?", (TEAM_NAME,)).fetchone()
        if row:
            team_id = row["id"]
            print(f"[info] Team '{TEAM_NAME}' already exists (id={team_id})")
            return team_id

        if dry_run:
            print(f"[dry-run] Would create team '{TEAM_NAME}' in auth.db")
            return -1

        cursor = conn.execute("INSERT INTO teams (name) VALUES (?)", (TEAM_NAME,))
        team_id = cursor.lastrowid
        conn.commit()
        print(f"[info] Created team '{TEAM_NAME}' (id={team_id})")
        return team_id


def assign_owner(team_id: int, owner_email: str, dry_run: bool) -> None:
    with _connect(AUTH_DB) as conn:
        row = conn.execute(
            "SELECT id, plan FROM users WHERE email = ?", (owner_email.lower().strip(),)
        ).fetchone()
        if not row:
            print(f"[warn] User '{owner_email}' not found in auth.db — skipping owner assignment")
            return

        user_id = row["id"]
        if dry_run:
            print(f"[dry-run] Would set user {user_id} plan=owner, team_id={team_id}")
            return

        conn.execute(
            "UPDATE users SET plan = 'owner', team_id = ? WHERE id = ?",
            (team_id, user_id),
        )
        conn.commit()
        print(f"[info] Assigned user '{owner_email}' as owner of team id={team_id}")


def migrate_scrims(team_id: int, dry_run: bool) -> int:
    """Set team_id on unowned scrims. Returns count updated."""
    with _connect(SCRIMS_DB) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM matches WHERE team_id IS NULL"
        ).fetchone()
        count = rows["cnt"] if rows else 0

        if count == 0:
            print("[info] No unowned scrims found — nothing to migrate")
            return 0

        print(f"[info] Found {count} unowned scrims to assign to team_id={team_id}")

        if dry_run:
            print(f"[dry-run] Would UPDATE {count} matches SET team_id={team_id}")
            return count

        conn.execute(
            "UPDATE matches SET team_id = ? WHERE team_id IS NULL",
            (team_id,),
        )
        conn.commit()
        print(f"[info] Migrated {count} scrims to team '{TEAM_NAME}' (id={team_id})")
        return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate unowned scrims to team 'Fui sem TP'")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--owner-email", metavar="EMAIL", help="Assign this user as team owner")
    args = parser.parse_args()

    if not AUTH_DB.exists():
        print(f"[error] auth.db not found at {AUTH_DB}")
        print("        Start the app once to initialise auth.db, then re-run this script.")
        sys.exit(1)

    if not SCRIMS_DB.exists():
        print(f"[error] scrims.db not found at {SCRIMS_DB}")
        sys.exit(1)

    if args.dry_run:
        print("[dry-run mode] No changes will be written.\n")

    team_id = ensure_team(dry_run=args.dry_run)

    if args.owner_email and team_id != -1:
        assign_owner(team_id=team_id, owner_email=args.owner_email, dry_run=args.dry_run)

    if team_id != -1:
        migrate_scrims(team_id=team_id, dry_run=args.dry_run)

    print("\n[done]")


if __name__ == "__main__":
    main()
