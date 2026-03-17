"""SQLite database layer for the Scrim Tracker."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "scrims.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
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
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing in older databases."""
    cursor = conn.execute("PRAGMA table_info(match_players)")
    existing = {row["name"] for row in cursor.fetchall()}
    if "is_mvp" not in existing:
        conn.execute("ALTER TABLE match_players ADD COLUMN is_mvp INTEGER NOT NULL DEFAULT 0")
    if "is_svp" not in existing:
        conn.execute("ALTER TABLE match_players ADD COLUMN is_svp INTEGER NOT NULL DEFAULT 0")


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
        return cur.rowcount > 0


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
            ROUND(AVG(p.kp_percent), 1) as avg_kp
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

    return {"roles": result, "overall": overall}


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
            ROUND(AVG(p.kp_percent), 1) as avg_kp
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
            }

        cd = champ_data[champ]
        cd["total_games"] += r["games"]
        cd["total_wins"] += r["wins"]
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
