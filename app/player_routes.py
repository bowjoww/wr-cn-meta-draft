"""Player Tracker API routes — personal match history and stats."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.auth_middleware import require_plan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/player", tags=["player"])

VALID_ROLES = {"top", "jungle", "mid", "bot", "support"}
VALID_RESULTS = {"win", "loss"}
VALID_MODES = {"ranked", "normal", "custom", "scrim"}


# ---------------------------------------------------------------------------
# DB helpers (inline — uses auth.db for user data, scrims.db for player_matches)
# ---------------------------------------------------------------------------

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "scrims.db"

_PLAYER_SCHEMA = """
CREATE TABLE IF NOT EXISTS player_matches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    date        TEXT NOT NULL,
    patch       TEXT,
    game_mode   TEXT NOT NULL DEFAULT 'ranked',
    champion    TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('top','jungle','mid','bot','support')),
    kills       INTEGER NOT NULL DEFAULT 0,
    deaths      INTEGER NOT NULL DEFAULT 0,
    assists     INTEGER NOT NULL DEFAULT 0,
    gold_earned REAL,
    result      TEXT NOT NULL CHECK(result IN ('win','loss')),
    duration    TEXT,
    is_mvp      INTEGER NOT NULL DEFAULT 0,
    is_svp      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_player_db() -> None:
    with _connect() as conn:
        conn.executescript(_PLAYER_SCHEMA)


def _insert_player_match(user_id: int, data: dict) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO player_matches
               (user_id, date, patch, game_mode, champion, role, kills, deaths, assists,
                gold_earned, result, duration, is_mvp, is_svp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                data["date"],
                data.get("patch"),
                data.get("game_mode", "ranked"),
                data["champion"],
                data["role"],
                data.get("kills", 0),
                data.get("deaths", 0),
                data.get("assists", 0),
                data.get("gold_earned"),
                data["result"],
                data.get("duration"),
                1 if data.get("is_mvp") else 0,
                1 if data.get("is_svp") else 0,
            ),
        )
        conn.commit()
        return cur.lastrowid


def _list_player_matches(user_id: int, limit: int = 100) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM player_matches WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _delete_player_match(match_id: int, user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM player_matches WHERE id = ? AND user_id = ?",
            (match_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _compute_streaks(matches: list[dict]) -> dict[str, Any]:
    """Compute current and longest win/loss streaks. matches ordered DESC (most recent first)."""
    if not matches:
        return {"current_streak": 0, "current_streak_type": None, "longest_win": 0, "longest_loss": 0}

    # Walk from oldest to newest to find longest streaks
    ordered = list(reversed(matches))
    longest_win = 0
    longest_loss = 0
    cur_win = 0
    cur_loss = 0
    for m in ordered:
        if m["result"] == "win":
            cur_win += 1
            cur_loss = 0
            longest_win = max(longest_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            longest_loss = max(longest_loss, cur_loss)

    # Current streak = consecutive same result from the most recent game
    last_result = matches[0]["result"]
    current_streak = 0
    for m in matches:
        if m["result"] == last_result:
            current_streak += 1
        else:
            break

    return {
        "current_streak": current_streak,
        "current_streak_type": last_result,
        "longest_win": longest_win,
        "longest_loss": longest_loss,
    }


def _compute_personal_bests(matches: list[dict]) -> dict[str, Any]:
    """Return single-game personal records."""
    if not matches:
        return {}

    best_kda_val = -1.0
    best_kda_game: dict | None = None
    most_kills_val = -1
    most_kills_game: dict | None = None
    most_assists_val = -1
    most_assists_game: dict | None = None

    for m in matches:
        kda = round((m["kills"] + m["assists"]) / max(m["deaths"], 1), 2)
        if kda > best_kda_val:
            best_kda_val = kda
            best_kda_game = {**m, "kda": kda}
        if m["kills"] > most_kills_val:
            most_kills_val = m["kills"]
            most_kills_game = {**m, "kda": kda}
        if m["assists"] > most_assists_val:
            most_assists_val = m["assists"]
            most_assists_game = {**m, "kda": kda}

    return {
        "best_kda": best_kda_game,
        "most_kills": most_kills_game,
        "most_assists": most_assists_game,
    }


def _compute_trends(matches: list[dict]) -> dict[str, Any]:
    """Rolling averages over last 10/20 games vs overall."""
    def _avg(subset: list[dict]) -> dict:
        if not subset:
            return {}
        n = len(subset)
        wins = sum(1 for m in subset if m["result"] == "win")
        avg_k = round(sum(m["kills"] for m in subset) / n, 1)
        avg_d = round(sum(m["deaths"] for m in subset) / n, 1)
        avg_a = round(sum(m["assists"] for m in subset) / n, 1)
        return {
            "games": n,
            "winrate": round(wins / n * 100, 1),
            "avg_kills": avg_k,
            "avg_deaths": avg_d,
            "avg_assists": avg_a,
            "kda": round((avg_k + avg_a) / max(avg_d, 1), 2),
        }

    return {
        "last10": _avg(matches[:10]),
        "last20": _avg(matches[:20]),
        "all_time": _avg(matches),
    }


def _get_player_stats(user_id: int) -> dict[str, Any]:
    with _connect() as conn:
        overall = conn.execute(
            """SELECT
                COUNT(*) as total_games,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
                ROUND(AVG(kills), 1) as avg_kills,
                ROUND(AVG(deaths), 1) as avg_deaths,
                ROUND(AVG(assists), 1) as avg_assists,
                SUM(is_mvp) as total_mvp,
                SUM(is_svp) as total_svp
            FROM player_matches WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        overall = dict(overall)
        if overall["total_games"] > 0:
            overall["winrate"] = round(overall["wins"] / overall["total_games"] * 100, 1)
            overall["kda"] = round(
                (overall["avg_kills"] + overall["avg_assists"]) / max(overall["avg_deaths"], 1), 2
            )
        else:
            overall["winrate"] = 0
            overall["kda"] = 0

        # Per champion
        champ_rows = conn.execute(
            """SELECT
                champion,
                COUNT(*) as games,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
                ROUND(AVG(kills), 1) as avg_kills,
                ROUND(AVG(deaths), 1) as avg_deaths,
                ROUND(AVG(assists), 1) as avg_assists,
                SUM(is_mvp) as mvps
            FROM player_matches WHERE user_id = ?
            GROUP BY champion ORDER BY games DESC""",
            (user_id,),
        ).fetchall()
        champions = []
        for r in champ_rows:
            d = dict(r)
            d["winrate"] = round(d["wins"] / d["games"] * 100, 1) if d["games"] > 0 else 0
            d["kda"] = round((d["avg_kills"] + d["avg_assists"]) / max(d["avg_deaths"], 1), 2)
            champions.append(d)

        # Per role
        role_rows = conn.execute(
            """SELECT
                role,
                COUNT(*) as games,
                SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
                ROUND(AVG(kills), 1) as avg_kills,
                ROUND(AVG(deaths), 1) as avg_deaths,
                ROUND(AVG(assists), 1) as avg_assists
            FROM player_matches WHERE user_id = ?
            GROUP BY role ORDER BY games DESC""",
            (user_id,),
        ).fetchall()
        roles = []
        for r in role_rows:
            d = dict(r)
            d["winrate"] = round(d["wins"] / d["games"] * 100, 1) if d["games"] > 0 else 0
            d["kda"] = round((d["avg_kills"] + d["avg_assists"]) / max(d["avg_deaths"], 1), 2)
            roles.append(d)

        # Raw matches for streak / personal bests / trends (DESC order)
        raw = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM player_matches WHERE user_id = ? ORDER BY date DESC, id DESC",
                (user_id,),
            ).fetchall()
        ]

    return {
        "overall": overall,
        "champions": champions,
        "roles": roles,
        "streaks": _compute_streaks(raw),
        "personal_bests": _compute_personal_bests(raw),
        "trends": _compute_trends(raw),
    }


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PlayerMatchInput(BaseModel):
    date: str
    patch: str | None = None
    game_mode: str = "ranked"
    champion: str
    role: str
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    gold_earned: float | None = None
    result: str
    duration: str | None = None
    is_mvp: bool = False
    is_svp: bool = False

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")
        return v

    @field_validator("result")
    @classmethod
    def validate_result(cls, v: str) -> str:
        if v not in VALID_RESULTS:
            raise ValueError(f"result must be one of {VALID_RESULTS}")
        return v


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/matches")
def add_match(body: PlayerMatchInput, user: dict = Depends(require_plan("player", "coach", "owner"))) -> dict[str, Any]:
    match_id = _insert_player_match(user["id"], body.model_dump())
    return {"id": match_id, "message": "Partida registrada"}


@router.get("/matches")
def list_matches(user: dict = Depends(require_plan("player", "coach", "owner"))) -> list[dict[str, Any]]:
    return _list_player_matches(user["id"])


@router.delete("/matches/{match_id}")
def delete_match(match_id: int, user: dict = Depends(require_plan("player", "coach", "owner"))) -> dict[str, str]:
    if not _delete_player_match(match_id, user["id"]):
        raise HTTPException(status_code=404, detail="Partida nao encontrada")
    return {"message": "Partida removida"}


@router.get("/stats")
def player_stats(user: dict = Depends(require_plan("player", "coach", "owner"))) -> dict[str, Any]:
    return _get_player_stats(user["id"])


@router.get("/stats/comparison")
def player_comparison(user: dict = Depends(require_plan("player", "coach", "owner"))) -> dict[str, Any]:
    """Compare player's personal stats per role vs team scrim averages."""
    from app.scrim_db import get_role_averages

    player_stats_data = _get_player_stats(user["id"])
    player_by_role = {r["role"]: r for r in player_stats_data["roles"]}

    team_averages = get_role_averages()
    team_by_role = {r["role"]: r for r in team_averages}

    all_roles = sorted(set(list(player_by_role.keys()) + list(team_by_role.keys())))
    comparison = []
    for role in all_roles:
        p = player_by_role.get(role)
        t = team_by_role.get(role)
        comparison.append({
            "role": role,
            "player": p,
            "team": t,
        })

    return {"comparison": comparison}
