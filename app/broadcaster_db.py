"""SQLite database layer for the Broadcaster tab."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_default_db = Path(__file__).resolve().parent.parent / "data" / "broadcaster.db"
BROADCASTER_DB_PATH = Path(os.environ.get("BROADCASTER_DB_PATH", str(_default_db)))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS broadcaster_matches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    team_a       TEXT NOT NULL,
    team_b       TEXT NOT NULL,
    winner       TEXT,
    blue_side    TEXT,
    red_side     TEXT,
    match_notes  TEXT,
    draft_json   TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    BROADCASTER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(BROADCASTER_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_broadcaster_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def save_broadcaster_match(
    team_a: str,
    team_b: str,
    winner: str | None = None,
    blue_side: str | None = None,
    red_side: str | None = None,
    match_notes: str | None = None,
    draft: Any = None,
) -> int:
    """Insert a broadcaster match record. Returns new row id."""
    draft_json = json.dumps(draft, ensure_ascii=False) if draft is not None else None
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO broadcaster_matches (team_a, team_b, winner, blue_side, red_side, match_notes, draft_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (team_a, team_b, winner, blue_side, red_side, match_notes, draft_json),
        )
        return cur.lastrowid


def list_broadcaster_matches(limit: int = 100) -> list[dict]:
    """Return recent broadcaster matches, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM broadcaster_matches ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if d.get("draft_json"):
            try:
                d["draft"] = json.loads(d["draft_json"])
            except Exception:
                d["draft"] = None
        else:
            d["draft"] = None
        del d["draft_json"]
        result.append(d)
    return result
