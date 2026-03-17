"""FastAPI routes for the Scrim Tracker."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from pydantic import BaseModel, field_validator

from app.scrim_db import (
    delete_match,
    get_champion_stats,
    get_duos,
    get_match,
    get_matchups,
    get_opponents,
    get_patches,
    get_pick_priority,
    get_stat_summary,
    insert_match,
    list_matches,
    update_match,
)
from app.fetch_cn_meta import DISPLAY_NAME_OVERRIDES, HERO_MAP_CACHE_PATH, fetch_hero_map_from_gtimg

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_ROLES = {"top", "jungle", "mid", "bot", "support"}
VALID_SIDES = {"blue", "red"}
VALID_RESULTS = {"win", "loss"}
VALID_TEAMS = {"ours", "theirs"}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PlayerInput(BaseModel):
    role: str
    team: str
    champion: str
    pick_order: int | None = None
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    kp_percent: float | None = None
    damage_dealt: float | None = None
    damage_taken: float | None = None
    gold_earned: float | None = None
    is_mvp: bool = False
    is_svp: bool = False

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of {VALID_ROLES}")
        return v

    @field_validator("team")
    @classmethod
    def validate_team(cls, v: str) -> str:
        if v not in VALID_TEAMS:
            raise ValueError(f"team must be one of {VALID_TEAMS}")
        return v


class BanInput(BaseModel):
    champion: str
    team: str
    ban_order: int

    @field_validator("team")
    @classmethod
    def validate_team(cls, v: str) -> str:
        if v not in VALID_TEAMS:
            raise ValueError(f"team must be one of {VALID_TEAMS}")
        return v


class MatchInput(BaseModel):
    patch: str
    date: str
    opponent: str
    side: str
    result: str
    duration: str | None = None
    notes: str | None = None
    players: list[PlayerInput] = []
    bans: list[BanInput] = []

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in VALID_SIDES:
            raise ValueError(f"side must be one of {VALID_SIDES}")
        return v

    @field_validator("result")
    @classmethod
    def validate_result(cls, v: str) -> str:
        if v not in VALID_RESULTS:
            raise ValueError(f"result must be one of {VALID_RESULTS}")
        return v


# ---------------------------------------------------------------------------
# Champions endpoint (reuses hero map)
# ---------------------------------------------------------------------------

@router.get("/api/champions")
def api_champions() -> list[dict[str, str]]:
    """Return the list of Wild Rift champions from the hero map cache."""
    # Try cache first without network call
    if HERO_MAP_CACHE_PATH.exists():
        try:
            with HERO_MAP_CACHE_PATH.open("r", encoding="utf-8") as f:
                cache = json.load(f)
            hero_map = cache.get("items", {})
            if hero_map:
                return _hero_map_to_list(hero_map)
        except Exception:
            pass

    # Fetch fresh
    try:
        hero_map = fetch_hero_map_from_gtimg()
        return _hero_map_to_list(hero_map)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load champion list: {exc}") from exc


@router.get("/api/champions/refresh")
def api_champions_refresh() -> dict[str, Any]:
    """Force refresh the hero map cache and return updated champion list."""
    try:
        hero_map = fetch_hero_map_from_gtimg(force_refresh=True)
        champions = _hero_map_to_list(hero_map)
        return {"message": f"Refreshed {len(champions)} champions", "champions": champions}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {exc}") from exc


def _hero_map_to_list(hero_map: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    champions = []
    for hero_id, data in hero_map.items():
        raw_name = data.get("hero_name_global") or data.get("hero_name_cn") or f"hero_{hero_id}"
        name_global = DISPLAY_NAME_OVERRIDES.get(raw_name, raw_name)
        champions.append({
            "hero_id": hero_id,
            "name": name_global,
            "name_cn": data.get("hero_name_cn", ""),
            "avatar_url": data.get("avatar_url", ""),
            "card_url": data.get("card_url", ""),
            "poster_url": data.get("poster_url", ""),
        })
    champions.sort(key=lambda c: c["name"].lower())
    return champions


# ---------------------------------------------------------------------------
# Match CRUD
# ---------------------------------------------------------------------------

@router.post("/api/scrims/matches")
def create_match(body: MatchInput) -> dict[str, Any]:
    data = body.model_dump()
    match_id = insert_match(data)
    return {"id": match_id, "message": "Match created"}


@router.get("/api/scrims/matches")
def api_list_matches(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
    side: str | None = None,
    result: str | None = None,
) -> list[dict[str, Any]]:
    return list_matches(
        opponent=opponent,
        date_from=date_from,
        date_to=date_to,
        patch=patch,
        side=side,
        result=result,
    )


@router.get("/api/scrims/matches/{match_id}")
def api_get_match(match_id: int) -> dict[str, Any]:
    match = get_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.put("/api/scrims/matches/{match_id}")
def api_update_match(match_id: int, body: MatchInput) -> dict[str, str]:
    data = body.model_dump()
    if not update_match(match_id, data):
        raise HTTPException(status_code=404, detail="Match not found")
    return {"message": "Match updated"}


@router.delete("/api/scrims/matches/{match_id}")
def api_delete_match(match_id: int) -> dict[str, str]:
    if not delete_match(match_id):
        raise HTTPException(status_code=404, detail="Match not found")
    return {"message": "Match deleted"}


# ---------------------------------------------------------------------------
# Aggregation endpoints
# ---------------------------------------------------------------------------

@router.get("/api/scrims/stats")
def api_scrim_stats(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> dict[str, Any]:
    return get_stat_summary(
        opponent=opponent, date_from=date_from, date_to=date_to, patch=patch
    )


@router.get("/api/scrims/champion-stats")
def api_champion_stats(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    return get_champion_stats(
        opponent=opponent, date_from=date_from, date_to=date_to, patch=patch
    )


@router.get("/api/scrims/matchups")
def api_matchups(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    return get_matchups(opponent=opponent, date_from=date_from, date_to=date_to, patch=patch)


@router.get("/api/scrims/duos")
def api_duos(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    return get_duos(opponent=opponent, date_from=date_from, date_to=date_to, patch=patch)


@router.get("/api/scrims/pick-priority")
def api_pick_priority(
    opponent: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    patch: str | None = None,
) -> list[dict[str, Any]]:
    return get_pick_priority(opponent=opponent, date_from=date_from, date_to=date_to, patch=patch)


@router.get("/api/scrims/filters")
def api_scrim_filters() -> dict[str, list[str]]:
    """Return available filter values (opponents, patches)."""
    return {
        "opponents": get_opponents(),
        "patches": get_patches(),
    }


# ---------------------------------------------------------------------------
# OCR endpoint (placeholder – implemented in ocr_service.py)
# ---------------------------------------------------------------------------

@router.post("/api/scrims/ocr")
async def api_ocr(
    files: list[UploadFile] = File(...),
    our_side: str | None = Form(None),
) -> dict[str, Any]:
    if our_side and our_side not in VALID_SIDES:
        raise HTTPException(status_code=400, detail="our_side must be 'blue' or 'red'")

    try:
        from app.ocr_service import extract_match_data
    except ImportError:
        raise HTTPException(status_code=501, detail="OCR service not available")

    images = []
    for f in files:
        content = await f.read()
        images.append({
            "data": content,
            "content_type": f.content_type or "image/png",
        })

    try:
        result = extract_match_data(images, our_side=our_side)
        return result
    except Exception as exc:
        logger.exception("OCR extraction failed")
        raise HTTPException(status_code=500, detail=f"OCR failed: {exc}") from exc
