"""SQLite database layer for the Scrim Tracker."""

from __future__ import annotations

import atexit
import os
import sqlite3
from pathlib import Path
from typing import Any

_default_db = Path(__file__).resolve().parent.parent / "data" / "scrims.db"
DB_PATH = Path(os.environ.get("DB_PATH", str(_default_db)))

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patch       TEXT NOT NULL,
    date        TEXT NOT NULL,
    opponent    TEXT NOT NULL,
    side        TEXT NOT NULL CHECK(side IN ('blue','red')),
    result      TEXT NOT NULL CHECK(result IN ('win','loss')),
    duration    TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS match_players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK(role IN ('top','jungle','mid','bot','support')),
    team        TEXT NOT NULL CHECK(team IN ('ours','theirs')),
    champion    TEXT NOT NULL,
    pick_order  INTEGER,
    kills       INTEGER NOT NULL DEFAULT 0,
    deaths      INTEGER NOT NULL DEFAULT 0,
    assists     INTEGER NOT NULL DEFAULT 0,
    kp_percent  REAL,
    damage_dealt REAL,
    damage_taken REAL,
    gold_earned  REAL
);

CREATE TABLE IF NOT EXISTS bans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    champion    TEXT NOT NULL,
    team        TEXT NOT NULL CHECK(team IN ('ours','theirs')),
    ban_order   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS team_rosters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name   TEXT NOT NULL,
    player_nick TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(team_name, player_nick)
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _checkpoint() -> None:
    """Force WAL checkpoint so all data is written to the main DB file."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception:
        pass


# Checkpoint WAL on process exit to prevent data loss
atexit.register(_checkpoint)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing in older databases."""
    cursor = conn.execute("PRAGMA table_info(match_players)")
    existing = {row["name"] for row in cursor.fetchall()}
    if "is_mvp" not in existing:
        conn.execute("ALTER TABLE match_players ADD COLUMN is_mvp INTEGER NOT NULL DEFAULT 0")
    if "is_svp" not in existing:
        conn.execute("ALTER TABLE match_players ADD COLUMN is_svp INTEGER NOT NULL DEFAULT 0")
    # Normalize champion names (e.g. MonkeyKing -> Wukong)
    conn.execute("UPDATE match_players SET champion = 'Wukong' WHERE champion = 'MonkeyKing'")
    conn.execute("UPDATE bans SET champion = 'Wukong' WHERE champion = 'MonkeyKing'")
    # Correct patch versions by date range — guarded so it only runs once.
    # Without the guard the open-ended WHERE date >= '2026-03-25' would overwrite
    # future patches (e.g. 7.1) every time init_db() is called.
    already_ran = conn.execute(
        "SELECT 1 FROM migrations WHERE name = 'patch_correction_7.0fg'"
    ).fetchone()
    if not already_ran:
        conn.execute(
            "UPDATE matches SET patch = '7.0f' "
            "WHERE date >= '2026-03-18' AND date <= '2026-03-24'"
        )
        conn.execute(
            "UPDATE matches SET patch = '7.0g' "
            "WHERE date >= '2026-03-25'"
        )
        conn.execute(
            "INSERT INTO migrations (name) VALUES ('patch_correction_7.0fg')"
        )


def init_db() -> None:
    """Create tables if they don't exist, then run migrations."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


# ---------------------------------------------------------------------------
# CRUD – matches
# ---------------------------------------------------------------------------

def insert_match(data: dict[str, Any]) -> int:
    """Insert a match with players and bans. Returns the new match id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO matches (patch, date, opponent, side, result, duration, notes)
               VALUES (:patch, :date, :opponent, :side, :result, :duration, :notes)""",
            {
                "patch": data["patch"],
                "date": data["date"],
                "opponent": data["opponent"],
                "side": data["side"],
                "result": data["result"],
                "duration": data.get("duration"),
                "notes": data.get("notes"),
            },
        )
        match_id = cur.lastrowid

        _insert_players(conn, match_id, data.get("players", []))
        _insert_bans(conn, match_id, data.get("bans", []))
    _checkpoint()
    return match_id


def _insert_players(conn: sqlite3.Connection, match_id: int, players: list[dict]) -> None:
    for p in players:
        conn.execute(
            """INSERT INTO match_players
               (match_id, role, team, champion, pick_order, kills, deaths, assists,
                kp_percent, damage_dealt, damage_taken, gold_earned, is_mvp, is_svp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                match_id,
                p["role"],
                p["team"],
                p["champion"],
                p.get("pick_order"),
                p.get("kills", 0),
                p.get("deaths", 0),
                p.get("assists", 0),
                p.get("kp_percent"),
                p.get("damage_dealt"),
                p.get("damage_taken"),
                p.get("gold_earned"),
                1 if p.get("is_mvp") else 0,
                1 if p.get("is_svp") else 0,
            ),
        )


def _insert_bans(conn: sqlite3.Connection, match_id: int, bans: list[dict]) -> None:
    for b in bans:
        conn.execute(
            """INSERT INTO bans (match_id, champion, team, ban_order)
               VALUES (?, ?, ?, ?)""",
            (match_id, b["champion"], b["team"], b["ban_order"]),
        )


def get_match(match_id: int) -> dict[str, Any] | None:
    """Return a single match with its players and bans."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not row:
            return None

        match = dict(row)
        match["players"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM match_players WHERE match_id = ? ORDER BY team, role",
                (match_id,),
            ).fetchall()
        ]
        match["bans"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM bans WHERE match_id = ? ORDER BY team, ban_order",
                (match_id,),
            ).fetchall()
        ]
        return match


def delete_match(match_id: int) -> bool:
    """Delete a match and cascade to players/bans. Returns True if deleted."""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
        deleted = cur.rowcount > 0
    if deleted:
        _checkpoint()
    return deleted


def update_match(match_id: int, data: dict[str, Any]) -> bool:
    """Replace a match's data. Returns True if the match existed."""
    with _connect() as conn:
        existing = conn.execute("SELECT id FROM matches WHERE id = ?", (match_id,)).fetchone()
        if not existing:
            return False

        conn.execute(
            """UPDATE matches SET patch=:patch, date=:date, opponent=:opponent,
               side=:side, result=:result, duration=:duration, notes=:notes
               WHERE id=:id""",
            {
                "id": match_id,
                "patch": data["patch"],
                "date": data["date"],
                "opponent": data["opponent"],
                "side": data["side"],
                "result": data["result"],
                "duration": data.get("duration"),
                "notes": data.get("notes"),
            },
        )

        conn.execute("DELETE FROM match_players WHERE match_id = ?", (match_id,))
        conn.execute("DELETE FROM bans WHERE match_id = ?", (match_id,))

        _insert_players(conn, match_id, data.get("players", []))
        _insert_bans(conn, match_id, data.get("bans", []))
    _checkpoint()
    return True


def list_matches(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
    side: str | None = None,
    result: str | None = None,
) -> list[dict[str, Any]]:
    """List matches with optional filters. Returns matches with nested players/bans."""
    clauses: list[str] = []
    params: list[Any] = []

    if opponent:
        clauses.append("opponent = ?")
        params.append(opponent)
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    if patch:
        clauses.append("patch = ?")
        params.append(patch)
    if side:
        clauses.append("side = ?")
        params.append(side)
    if result:
        clauses.append("result = ?")
        params.append(result)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    query = f"SELECT * FROM matches{where} ORDER BY date DESC, id DESC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        matches = []
        for row in rows:
            m = dict(row)
            m["players"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM match_players WHERE match_id = ? ORDER BY team, role",
                    (m["id"],),
                ).fetchall()
            ]
            m["bans"] = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM bans WHERE match_id = ? ORDER BY team, ban_order",
                    (m["id"],),
                ).fetchall()
            ]
            matches.append(m)
        return matches


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------

def _build_where(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if opponent:
        clauses.append("m.opponent = ?")
        params.append(opponent)
    if date_from:
        clauses.append("m.date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("m.date <= ?")
        params.append(date_to)
    if patch:
        clauses.append("m.patch = ?")
        params.append(patch)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


def get_stat_summary(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> dict[str, Any]:
    """Aggregated stats per role for our team: top champion, games, winrate, KDA, KP%."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)

    query = f"""
        SELECT
            p.role,
            p.champion,
            COUNT(*) as games,
            SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(p.gold_earned), 0) as avg_gold,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE p.team = 'ours'{extra_where}
        GROUP BY p.role, p.champion
        ORDER BY p.role, games DESC
    """

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    result: dict[str, list[dict]] = {}
    for row in rows:
        r = dict(row)
        r["winrate"] = round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0
        r["kda"] = round(
            (r["avg_kills"] + r["avg_assists"]) / max(r["avg_deaths"], 1), 2
        )
        role = r.pop("role")
        result.setdefault(role, []).append(r)

    # Overall stats
    overall_query = f"""
        SELECT
            COUNT(*) as total_games,
            SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) as total_wins
        FROM matches m
        WHERE 1=1{extra_where}
    """
    with _connect() as conn:
        overall = dict(conn.execute(overall_query, params).fetchone())

    overall["winrate"] = (
        round(overall["total_wins"] / overall["total_games"] * 100, 1)
        if overall["total_games"] > 0
        else 0
    )

    # Side stats (blue/red winrate)
    side_query = f"""
        SELECT
            m.side,
            COUNT(*) as games,
            SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) as wins
        FROM matches m
        WHERE m.side IS NOT NULL{extra_where}
        GROUP BY m.side
    """
    with _connect() as conn:
        side_rows = conn.execute(side_query, params).fetchall()

    side_stats: dict[str, dict] = {}
    for row in side_rows:
        r = dict(row)
        side = r["side"]
        r["winrate"] = round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0
        side_stats[side] = r

    # Duration averages by result
    duration_query = f"""
        SELECT
            AVG(CASE WHEN m.result = 'win' AND m.duration IS NOT NULL AND m.duration LIKE '%:%'
                THEN CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS INTEGER) * 60
                   + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS INTEGER)
                END) as avg_win_duration_s,
            AVG(CASE WHEN m.result = 'loss' AND m.duration IS NOT NULL AND m.duration LIKE '%:%'
                THEN CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS INTEGER) * 60
                   + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS INTEGER)
                END) as avg_loss_duration_s
        FROM matches m
        WHERE 1=1{extra_where}
    """
    with _connect() as conn:
        dur = dict(conn.execute(duration_query, params).fetchone())

    overall["avg_win_duration_s"] = round(dur["avg_win_duration_s"]) if dur["avg_win_duration_s"] is not None else None
    overall["avg_loss_duration_s"] = round(dur["avg_loss_duration_s"]) if dur["avg_loss_duration_s"] is not None else None

    return {"roles": result, "overall": overall, "side_stats": side_stats}


def get_role_averages(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate stats per role (across all champions) for our team."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p.role,
            COUNT(*) as games,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(p.gold_earned), 0) as avg_gold,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm,
            ROUND(AVG(p.damage_dealt), 0) as avg_damage_dealt,
            ROUND(AVG(p.damage_taken), 0) as avg_damage_taken,
            ROUND(AVG(
                CASE WHEN td.total_dmg > 0 AND p.damage_dealt IS NOT NULL
                THEN p.damage_dealt * 100.0 / td.total_dmg
                END
            ), 1) as avg_dmg_share
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        JOIN (
            SELECT match_id, SUM(damage_dealt) as total_dmg
            FROM match_players
            WHERE team = 'ours'
            GROUP BY match_id
        ) td ON p.match_id = td.match_id
        WHERE p.team = 'ours'{extra_where}
        GROUP BY p.role
        ORDER BY p.role
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["kda"] = round(
            (r["avg_kills"] + r["avg_assists"]) / max(r["avg_deaths"], 1), 2
        )
        result.append(r)
    return result


def get_all_champions_by_role(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Stats per champion per role for ALL teams (ours + theirs)."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p.role,
            p.champion,
            COUNT(*) as games,
            SUM(CASE
                WHEN p.team = 'ours' AND m.result = 'win' THEN 1
                WHEN p.team = 'theirs' AND m.result = 'loss' THEN 1
                ELSE 0
            END) as wins,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE 1=1{extra_where}
        GROUP BY p.role, p.champion
        ORDER BY p.role, games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        r = dict(row)
        r["winrate"] = round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0
        r["kda"] = round(
            (r["avg_kills"] + r["avg_assists"]) / max(r["avg_deaths"], 1), 2
        )
        role = r.pop("role")
        result.setdefault(role, []).append(r)
    return result


def get_enemy_champions_by_role(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Stats per champion per role for the enemy team (theirs) only."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p.role,
            p.champion,
            COUNT(*) as games,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE p.team = 'theirs'{extra_where}
        GROUP BY p.role, p.champion
        ORDER BY p.role, games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        r = dict(row)
        r["winrate"] = round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0
        r["kda"] = round(
            (r["avg_kills"] + r["avg_assists"]) / max(r["avg_deaths"], 1), 2
        )
        role = r.pop("role")
        result.setdefault(role, []).append(r)
    return result


def get_enemy_champions_general(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Stats per champion across all roles for enemy team only (general enemy tier list)."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p.champion,
            COUNT(*) as games,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) as wins,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE p.team = 'theirs'{extra_where}
        GROUP BY p.champion
        ORDER BY games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["winrate"] = round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0
        r["kda"] = round(
            (r["avg_kills"] + r["avg_assists"]) / max(r["avg_deaths"], 1), 2
        )
        result.append(r)
    return result


def get_all_champions_general(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Stats per champion across ALL roles and ALL teams (general tier list)."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p.champion,
            COUNT(*) as games,
            SUM(CASE
                WHEN p.team = 'ours' AND m.result = 'win' THEN 1
                WHEN p.team = 'theirs' AND m.result = 'loss' THEN 1
                ELSE 0
            END) as wins,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE 1=1{extra_where}
        GROUP BY p.champion
        ORDER BY games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        r = dict(row)
        r["winrate"] = round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0
        r["kda"] = round(
            (r["avg_kills"] + r["avg_assists"]) / max(r["avg_deaths"], 1), 2
        )
        result.append(r)
    return result


def get_champion_stats(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Per-champion aggregated stats across all roles."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)

    query = f"""
        SELECT
            p.champion,
            p.team,
            p.role,
            COUNT(*) as games,
            SUM(CASE
                WHEN p.team = 'ours' AND m.result = 'win' THEN 1
                WHEN p.team = 'theirs' AND m.result = 'loss' THEN 1
                ELSE 0
            END) as wins,
            ROUND(AVG(p.kills), 1) as avg_kills,
            ROUND(AVG(p.deaths), 1) as avg_deaths,
            ROUND(AVG(p.assists), 1) as avg_assists,
            ROUND(AVG(p.kp_percent), 1) as avg_kp,
            ROUND(AVG(p.gold_earned), 0) as avg_gold,
            ROUND(AVG(
                CASE WHEN m.duration IS NOT NULL AND p.gold_earned IS NOT NULL
                THEN p.gold_earned / (
                    CAST(SUBSTR(m.duration, 1, INSTR(m.duration, ':') - 1) AS REAL)
                    + CAST(SUBSTR(m.duration, INSTR(m.duration, ':') + 1) AS REAL) / 60.0
                )
                END
            ), 0) as avg_gpm
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE 1=1{extra_where}
        GROUP BY p.champion, p.team, p.role
        ORDER BY p.champion, p.team, p.role
    """

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    # Also get ban counts
    ban_query = f"""
        SELECT b.champion, b.team, COUNT(*) as ban_count
        FROM bans b
        JOIN matches m ON b.match_id = m.id
        WHERE 1=1{extra_where}
        GROUP BY b.champion, b.team
    """
    with _connect() as conn:
        ban_rows = conn.execute(ban_query, params).fetchall()

    ban_map: dict[str, dict[str, int]] = {}
    for br in ban_rows:
        b = dict(br)
        ban_map.setdefault(b["champion"], {})[b["team"]] = b["ban_count"]

    # Total matches for presence calculation
    total_query = f"""
        SELECT COUNT(*) as total FROM matches m WHERE 1=1{extra_where}
    """
    with _connect() as conn:
        total_matches = conn.execute(total_query, params).fetchone()["total"]

    # Aggregate by champion
    champ_data: dict[str, dict] = {}
    for row in rows:
        r = dict(row)
        champ = r["champion"]
        if champ not in champ_data:
            champ_data[champ] = {
                "champion": champ,
                "total_games": 0,
                "total_wins": 0,
                "our_picks": 0,
                "their_picks": 0,
                "our_bans": ban_map.get(champ, {}).get("ours", 0),
                "their_bans": ban_map.get(champ, {}).get("theirs", 0),
                "by_role": {},
                "_gpm_sum": 0,
                "_gpm_count": 0,
            }

        cd = champ_data[champ]
        cd["total_games"] += r["games"]
        cd["total_wins"] += r["wins"]
        if r["avg_gpm"]:
            cd["_gpm_sum"] += r["avg_gpm"] * r["games"]
            cd["_gpm_count"] += r["games"]
        if r["team"] == "ours":
            cd["our_picks"] += r["games"]
        else:
            cd["their_picks"] += r["games"]

        role_key = f"{r['team']}_{r['role']}"
        cd["by_role"][role_key] = {
            "games": r["games"],
            "wins": r["wins"],
            "winrate": round(r["wins"] / r["games"] * 100, 1) if r["games"] > 0 else 0,
            "avg_kills": r["avg_kills"],
            "avg_deaths": r["avg_deaths"],
            "avg_assists": r["avg_assists"],
            "avg_kp": r["avg_kp"],
        }

    result = []
    for cd in champ_data.values():
        cd["winrate"] = (
            round(cd["total_wins"] / cd["total_games"] * 100, 1)
            if cd["total_games"] > 0
            else 0
        )
        total_bans = cd["our_bans"] + cd["their_bans"]
        cd["presence"] = (
            round((cd["total_games"] + total_bans) / max(total_matches, 1) * 100, 1)
        )
        cd["avg_gpm"] = (
            round(cd["_gpm_sum"] / cd["_gpm_count"]) if cd["_gpm_count"] > 0 else None
        )
        del cd["_gpm_sum"]
        del cd["_gpm_count"]
        result.append(cd)

    result.sort(key=lambda x: x["total_games"], reverse=True)
    return result


def get_opponents() -> list[str]:
    """Return list of distinct opponent names."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT opponent FROM matches ORDER BY opponent"
        ).fetchall()
        return [r["opponent"] for r in rows]


def get_patches() -> list[str]:
    """Return list of distinct patches."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT patch FROM matches ORDER BY patch DESC"
        ).fetchall()
        return [r["patch"] for r in rows]


# ---------------------------------------------------------------------------
# Advanced stats
# ---------------------------------------------------------------------------

def get_matchups(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Return matchup records: our champion vs their champion per role."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            ours.role,
            ours.champion AS our_champion,
            theirs.champion AS their_champion,
            COUNT(*) AS games,
            SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses
        FROM match_players ours
        JOIN match_players theirs
            ON ours.match_id = theirs.match_id
            AND ours.role = theirs.role
            AND ours.team = 'ours'
            AND theirs.team = 'theirs'
        JOIN matches m ON ours.match_id = m.id
        WHERE 1=1{extra_where}
        GROUP BY ours.role, ours.champion, theirs.champion
        ORDER BY games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["winrate"] = round(d["wins"] / d["games"] * 100, 1) if d["games"] > 0 else 0
        result.append(d)
    return result


def get_duos(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Return duo records: pairs of our champions with W/L."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p1.role AS role1,
            p1.champion AS champion1,
            p2.role AS role2,
            p2.champion AS champion2,
            COUNT(*) AS games,
            SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses
        FROM match_players p1
        JOIN match_players p2
            ON p1.match_id = p2.match_id
            AND p1.team = 'ours'
            AND p2.team = 'ours'
            AND p1.role < p2.role
        JOIN matches m ON p1.match_id = m.id
        WHERE 1=1{extra_where}
        GROUP BY p1.role, p1.champion, p2.role, p2.champion
        ORDER BY games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["winrate"] = round(d["wins"] / d["games"] * 100, 1) if d["games"] > 0 else 0
        result.append(d)
    return result


def get_mvp_svp_summary(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> dict[str, Any]:
    """Count MVP and SVP awards per role and per champion for our team."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    role_query = f"""
        SELECT
            p.role,
            SUM(p.is_mvp) as mvp_count,
            SUM(p.is_svp) as svp_count,
            SUM(p.is_mvp + p.is_svp) as total_awards,
            COUNT(*) as games
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE p.team = 'ours'{extra_where}
        GROUP BY p.role
        ORDER BY total_awards DESC
    """
    champ_query = f"""
        SELECT
            p.champion,
            p.role,
            SUM(p.is_mvp) as mvp_count,
            SUM(p.is_svp) as svp_count,
            COUNT(*) as games
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE p.team = 'ours'{extra_where}
        GROUP BY p.champion, p.role
        HAVING (mvp_count + svp_count) > 0
        ORDER BY (mvp_count + svp_count) DESC, mvp_count DESC
    """
    with _connect() as conn:
        role_rows = [dict(r) for r in conn.execute(role_query, params).fetchall()]
        champ_rows = [dict(r) for r in conn.execute(champ_query, params).fetchall()]
    return {"by_role": role_rows, "by_champion": champ_rows}


def get_pick_priority(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    """Return stats by pick order and side."""
    extra_where, params = _build_where(opponent, date_from, date_to, patch)
    query = f"""
        SELECT
            p.pick_order,
            m.side,
            p.champion,
            p.role,
            COUNT(*) AS games,
            SUM(CASE WHEN m.result = 'win' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN m.result = 'loss' THEN 1 ELSE 0 END) AS losses
        FROM match_players p
        JOIN matches m ON p.match_id = m.id
        WHERE p.team = 'ours' AND p.pick_order IS NOT NULL{extra_where}
        GROUP BY p.pick_order, m.side, p.champion, p.role
        ORDER BY p.pick_order, games DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["winrate"] = round(d["wins"] / d["games"] * 100, 1) if d["games"] > 0 else 0
        result.append(d)
    return result


# ---------- Team Rosters ---------- #


def upsert_team_roster(team_name: str, players: list[str]) -> None:
    """Replace all players for a team."""
    with _connect() as conn:
        conn.execute("DELETE FROM team_rosters WHERE team_name = ?", (team_name,))
        for nick in players:
            nick = nick.strip()
            if nick:
                conn.execute(
                    "INSERT INTO team_rosters (team_name, player_nick) VALUES (?, ?)",
                    (team_name, nick),
                )
        conn.commit()


def get_all_rosters() -> dict[str, list[str]]:
    """Return {team_name: [player_nick, ...]}."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT team_name, player_nick FROM team_rosters ORDER BY team_name, player_nick"
        ).fetchall()
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["team_name"], []).append(r["player_nick"])
    return result


def find_teams_by_players(nicks: list[str]) -> list[tuple[str, int]]:
    """Find teams matching given player nicks. Returns [(team_name, match_count)] sorted by matches desc.

    Matching strategy (in order):
    1. Exact match (case-insensitive)
    2. Match without #TAG (e.g. "Dokja" matches "Dokja#123")
    3. Nick contains or is contained in roster entry (partial match)
    """
    if not nicks:
        return []

    # Load all rosters
    with _connect() as conn:
        all_rows = conn.execute(
            "SELECT team_name, player_nick FROM team_rosters"
        ).fetchall()

    if not all_rows:
        return []

    # Build lookup: team -> set of normalized nicks (with and without tag)
    from collections import Counter
    team_matches: Counter[str] = Counter()

    # Normalize input nicks
    input_nicks = [n.strip().lower() for n in nicks if n and n.strip()]
    # Also strip #TAG from input nicks
    input_nicks_base = []
    for n in input_nicks:
        input_nicks_base.append(n.split("#")[0].strip() if "#" in n else n)

    for row in all_rows:
        team = row["team_name"]
        roster_nick = row["player_nick"].strip().lower()
        roster_base = roster_nick.split("#")[0].strip() if "#" in roster_nick else roster_nick

        for i, inp in enumerate(input_nicks):
            inp_base = input_nicks_base[i]
            # Exact match (full nick with tag)
            if inp == roster_nick:
                team_matches[team] += 1
                break
            # Base name match (without #TAG)
            if inp_base and roster_base and inp_base == roster_base:
                team_matches[team] += 1
                break
            # Partial match: input contains roster base or vice versa (min 3 chars)
            if len(inp_base) >= 3 and len(roster_base) >= 3:
                if inp_base in roster_base or roster_base in inp_base:
                    team_matches[team] += 1
                    break

    return team_matches.most_common()
