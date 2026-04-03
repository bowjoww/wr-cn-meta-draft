"""Owner/Manager dashboard API routes."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth_db import (
    get_team,
    get_team_members,
    update_user_plan,
)
from app.auth_middleware import require_plan
from app.scrim_db import get_stat_summary, list_matches

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# ---------------------------------------------------------------------------
# Helpers — per-player stats from player_matches (scrims.db)
# ---------------------------------------------------------------------------

import sqlite3
from pathlib import Path

_SCRIMS_DB = Path(__file__).resolve().parent.parent / "data" / "scrims.db"


def _connect_scrims() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_SCRIMS_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _player_stats_for_user(user_id: int) -> dict[str, Any]:
    """Compute aggregate player stats for a single user from player_matches."""
    with _connect_scrims() as conn:
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
        overall = dict(overall) if overall else {}

        if overall.get("total_games", 0) > 0:
            overall["winrate"] = round(
                overall["wins"] / overall["total_games"] * 100, 1
            )
            overall["kda"] = round(
                (overall["avg_kills"] + overall["avg_assists"])
                / max(overall["avg_deaths"] or 1, 1),
                2,
            )
        else:
            overall["winrate"] = 0
            overall["kda"] = 0

        # Most played role
        top_role_row = conn.execute(
            """SELECT role, COUNT(*) as cnt FROM player_matches
               WHERE user_id = ? GROUP BY role ORDER BY cnt DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        overall["top_role"] = top_role_row["role"] if top_role_row else None

        # Most played champion
        top_champ_row = conn.execute(
            """SELECT champion, COUNT(*) as cnt FROM player_matches
               WHERE user_id = ? GROUP BY champion ORDER BY cnt DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        overall["top_champion"] = top_champ_row["champion"] if top_champ_row else None

        # Last 10 WR trend
        recent = conn.execute(
            """SELECT result FROM player_matches WHERE user_id = ?
               ORDER BY date DESC, id DESC LIMIT 10""",
            (user_id,),
        ).fetchall()
        if recent:
            wins_recent = sum(1 for r in recent if r["result"] == "win")
            overall["recent10_winrate"] = round(wins_recent / len(recent) * 100, 1)
        else:
            overall["recent10_winrate"] = None

    return overall


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/summary")
def team_summary(user: dict = Depends(require_plan("owner"))) -> dict[str, Any]:
    """Aggregate team scrim stats + team metadata (owner only)."""
    team_id = user.get("team_id")
    if not team_id:
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")

    team = get_team(team_id)
    members = get_team_members(team_id)

    # Scrim aggregate stats for this team
    scrim_stats = get_stat_summary(team_id=team_id)
    overall = scrim_stats.get("overall", {})

    # Blue/Red side breakdown from matches
    matches = list_matches(team_id=team_id, limit=500)
    blue_total = sum(1 for m in matches if m.get("side") == "blue")
    blue_wins = sum(1 for m in matches if m.get("side") == "blue" and m.get("result") == "win")
    red_total = sum(1 for m in matches if m.get("side") == "red")
    red_wins = sum(1 for m in matches if m.get("side") == "red" and m.get("result") == "win")

    blue_wr = round(blue_wins / blue_total * 100, 1) if blue_total > 0 else None
    red_wr = round(red_wins / red_total * 100, 1) if red_total > 0 else None

    # Recent trend: last 10 scrims
    recent = matches[:10]
    recent_wins = sum(1 for m in recent if m.get("result") == "win")
    recent_wr = round(recent_wins / len(recent) * 100, 1) if recent else None

    return {
        "team": team,
        "member_count": len(members),
        "scrims": {
            "total": overall.get("total_games", 0),
            "wins": overall.get("total_wins", 0),
            "winrate": overall.get("winrate", 0),
            "recent10_winrate": recent_wr,
            "blue_side_winrate": blue_wr,
            "blue_side_games": blue_total,
            "red_side_winrate": red_wr,
            "red_side_games": red_total,
        },
    }


@router.get("/players")
def player_cards(user: dict = Depends(require_plan("owner"))) -> list[dict[str, Any]]:
    """Per-player performance cards for all team members (owner only)."""
    team_id = user.get("team_id")
    if not team_id:
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")

    members = get_team_members(team_id)
    cards = []
    for member in members:
        stats = _player_stats_for_user(member["id"])
        cards.append({
            "user_id": member["id"],
            "display_name": member["display_name"],
            "email": member["email"],
            "plan": member["plan"],
            "stats": stats,
        })

    # Sort by total games desc
    cards.sort(key=lambda c: c["stats"].get("total_games", 0), reverse=True)
    return cards


@router.get("/roster")
def roster(user: dict = Depends(require_plan("owner"))) -> dict[str, Any]:
    """Team roster with member details (owner only)."""
    team_id = user.get("team_id")
    if not team_id:
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")

    team = get_team(team_id)
    members = get_team_members(team_id)
    return {"team": team, "members": members}


class UpdatePlanInput(BaseModel):
    plan: str


@router.patch("/roster/{target_user_id}/plan")
def update_member_plan(
    target_user_id: int,
    body: UpdatePlanInput,
    user: dict = Depends(require_plan("owner")),
) -> dict[str, str]:
    """Change a team member's plan (owner only)."""
    allowed = {"free", "player", "coach", "owner"}
    if body.plan not in allowed:
        raise HTTPException(status_code=400, detail=f"Plano invalido. Opcoes: {allowed}")

    team_id = user.get("team_id")
    if not team_id:
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")

    # Verify target is in the same team
    members = get_team_members(team_id)
    member_ids = {m["id"] for m in members}
    if target_user_id not in member_ids:
        raise HTTPException(status_code=404, detail="Membro nao encontrado no seu time")

    update_user_plan(target_user_id, body.plan)
    return {"message": f"Plano atualizado para '{body.plan}'"}


@router.delete("/roster/{target_user_id}")
def remove_member(
    target_user_id: int,
    user: dict = Depends(require_plan("owner")),
) -> dict[str, str]:
    """Remove a member from the team (owner only). Cannot remove yourself."""
    if target_user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Voce nao pode remover a si mesmo")

    team_id = user.get("team_id")
    if not team_id:
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")

    members = get_team_members(team_id)
    member_ids = {m["id"] for m in members}
    if target_user_id not in member_ids:
        raise HTTPException(status_code=404, detail="Membro nao encontrado no seu time")

    from app.auth_db import update_user_team
    update_user_team(target_user_id, None)
    update_user_plan(target_user_id, "free")
    return {"message": "Membro removido do time"}


@router.get("/export")
def export_report(user: dict = Depends(require_plan("owner"))) -> StreamingResponse:
    """Export team stats as CSV (owner only)."""
    team_id = user.get("team_id")
    if not team_id:
        raise HTTPException(status_code=400, detail="Voce nao pertence a nenhum time")

    team = get_team(team_id)
    team_name = team["name"] if team else "team"

    members = get_team_members(team_id)
    scrim_stats = get_stat_summary(team_id=team_id)
    overall = scrim_stats.get("overall", {})

    output = io.StringIO()
    writer = csv.writer(output)

    # Header block
    writer.writerow(["ScrimVault — Team Report"])
    writer.writerow(["Team", team_name])
    writer.writerow(["Members", len(members)])
    writer.writerow(["Total Scrims", overall.get("total_games", 0)])
    writer.writerow(["Scrim Winrate (%)", overall.get("winrate", 0)])
    writer.writerow([])

    # Per-player section
    writer.writerow(["Player", "Plan", "Games", "Wins", "Winrate (%)", "Avg KDA",
                     "Avg K", "Avg D", "Avg A", "MVPs", "SVPs", "Top Role", "Top Champion",
                     "Last 10 WR (%)"])

    for member in members:
        s = _player_stats_for_user(member["id"])
        writer.writerow([
            member["display_name"],
            member["plan"],
            s.get("total_games", 0),
            s.get("wins", 0),
            s.get("winrate", 0),
            s.get("kda", 0),
            s.get("avg_kills", 0),
            s.get("avg_deaths", 0),
            s.get("avg_assists", 0),
            s.get("total_mvp", 0),
            s.get("total_svp", 0),
            s.get("top_role", ""),
            s.get("top_champion", ""),
            s.get("recent10_winrate", ""),
        ])

    output.seek(0)
    filename = f"scrimvault_{team_name.replace(' ', '_').lower()}_report.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
