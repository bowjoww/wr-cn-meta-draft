"""FastAPI router for the Broadcaster tab."""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.broadcaster_db import list_broadcaster_matches, save_broadcaster_match
from app.fetch_openseries_full import get_full_openseries_data
from app.fetch_openseries import get_openseries_data

logger = logging.getLogger(__name__)

router = APIRouter()

BROADCASTER_PIN = os.environ.get("BROADCASTER_PIN", "1234")


def _check_pin(x_broadcaster_pin: str | None) -> None:
    if x_broadcaster_pin != BROADCASTER_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.get("/api/openseries/teams")
def get_teams():
    data = get_full_openseries_data()
    return data.get("teams", [])


@router.get("/api/openseries/standings")
def get_standings():
    data = get_full_openseries_data()
    return data.get("standings", {"groups": []})


@router.get("/api/openseries/rankings")
def get_rankings():
    data = get_full_openseries_data()
    return data.get("rankings", {"player_rankings": [], "team_rankings": []})


@router.get("/api/openseries/overview")
def get_overview():
    data = get_full_openseries_data()
    return data.get("overview", {})


@router.get("/api/openseries/champions")
def get_champions():
    return get_openseries_data()


# ---------------------------------------------------------------------------
# PIN-protected endpoints
# ---------------------------------------------------------------------------

class PinRequest(BaseModel):
    pin: str


@router.post("/api/broadcaster/verify-pin")
def verify_pin(body: PinRequest):
    if body.pin != BROADCASTER_PIN:
        raise HTTPException(status_code=401, detail="Invalid PIN")
    return {"ok": True}


class MatchRequest(BaseModel):
    team_a: str
    team_b: str
    winner: str | None = None
    blue_side: str | None = None
    red_side: str | None = None
    match_notes: str | None = None
    draft: Any = None


@router.post("/api/broadcaster/match")
def create_match(
    body: MatchRequest,
    x_broadcaster_pin: str | None = Header(default=None),
):
    _check_pin(x_broadcaster_pin)
    new_id = save_broadcaster_match(
        team_a=body.team_a,
        team_b=body.team_b,
        winner=body.winner,
        blue_side=body.blue_side,
        red_side=body.red_side,
        match_notes=body.match_notes,
        draft=body.draft,
    )
    return {"id": new_id}


@router.get("/api/broadcaster/matches")
def get_matches(x_broadcaster_pin: str | None = Header(default=None)):
    _check_pin(x_broadcaster_pin)
    return list_broadcaster_matches()
