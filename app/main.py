from __future__ import annotations

import json
import logging
from math import sqrt
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.fetch_cn_meta import (
    CACHE_TTL_SECONDS,
    CN_PAGE_URL,
    build_cn_rows_from_payload,
    cache_age_seconds,
    fetch_cn_payload,
    fetch_hero_map_from_gtimg,
    get_cached_meta,
    hero_map_cache_age_seconds,
    is_cache_fresh,
    read_cache,
    summarize_cn_positions,
    update_cache,
)
from app.scoring import EPSILON, power_score, priority_score, zscore

app = FastAPI(title="WR CN Meta Viewer")
logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_cn_meta.json"
STATIC_INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"

Role = Literal["top", "jungle", "mid", "adc", "support"]
Tier = Literal["diamond", "master", "challenger"]
Source = Literal["auto", "sample", "cn"]
NameLang = Literal["global", "cn"]
View = Literal["draft", "power"]
SortField = Literal["champion", "win", "pick", "ban", "draft_score", "power_score"]
SortDir = Literal["asc", "desc"]


def _load_meta_data() -> list[dict]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _score_rows(filtered: list[dict]) -> list[dict]:
    avg_winrate = sum(row["winrate"] for row in filtered) / len(filtered)
    strengths = [row["winrate"] - avg_winrate for row in filtered]
    contests = [(0.6 * row["banrate"]) + (0.4 * row["pickrate"]) for row in filtered]

    strength_mean = sum(strengths) / len(strengths)
    contest_mean = sum(contests) / len(contests)

    strength_variance = sum((value - strength_mean) ** 2 for value in strengths) / len(strengths)
    contest_variance = sum((value - contest_mean) ** 2 for value in contests) / len(contests)

    strength_std = sqrt(strength_variance)
    contest_std = sqrt(contest_variance)

    scored: list[dict] = []
    for row, strength, contest in zip(filtered, strengths, contests):
        row_copy = dict(row)
        row_copy["priority_score"] = priority_score(
            winrate=row_copy["winrate"],
            pickrate=row_copy["pickrate"],
            banrate=row_copy["banrate"],
        )
        row_copy["power_score"] = power_score(
            winrate=row_copy["winrate"],
            pickrate=row_copy["pickrate"],
            banrate=row_copy["banrate"],
            avg_winrate=avg_winrate,
            eps=EPSILON,
        )
        row_copy["draft_score"] = zscore(strength, strength_mean, strength_std) + zscore(contest, contest_mean, contest_std)
        scored.append(row_copy)

    return scored


def _sort_rows(rows: list[dict], sort: SortField, direction: SortDir) -> list[dict]:
    sort_key_map = {
        "champion": lambda item: str(item.get("champion", "")).lower(),
        "win": lambda item: item.get("winrate", 0.0),
        "pick": lambda item: item.get("pickrate", 0.0),
        "ban": lambda item: item.get("banrate", 0.0),
        "draft_score": lambda item: item.get("draft_score", 0.0),
        "power_score": lambda item: item.get("power_score", 0.0),
    }
    return sorted(rows, key=sort_key_map[sort], reverse=direction == "desc")


def _filter_and_score(rows: list[dict], role: Role, tier: Tier, sort: SortField, direction: SortDir) -> list[dict]:
    filtered = [row for row in rows if row["role"] == role and row["tier"] == tier]
    if not filtered:
        raise HTTPException(status_code=404, detail="No meta data found for requested role/tier")

    scored = _score_rows(filtered)
    return _sort_rows(scored, sort=sort, direction=direction)


def _resolve_champion_name(row: dict, name_lang: NameLang) -> str:
    hero_id = str(row.get("hero_id", "")).strip()
    if name_lang == "cn":
        return row.get("hero_name_cn") or row.get("hero_name_global") or row.get("champion") or f"hero_{hero_id}"
    return row.get("hero_name_global") or row.get("hero_name_cn") or row.get("champion") or f"hero_{hero_id}"


def _with_champion_lang(rows: list[dict], name_lang: NameLang) -> list[dict]:
    localized: list[dict] = []
    for row in rows:
        row_copy = dict(row)
        row_copy["champion"] = _resolve_champion_name(row_copy, name_lang)
        localized.append(row_copy)
    return localized


def _load_cn_with_cache(role: Role, tier: Tier) -> tuple[list[dict] | None, str | None]:
    cached_rows = get_cached_meta(role=role, tier=tier)
    if cached_rows:
        return cached_rows, "cn_cache"

    payload = fetch_cn_payload(tier=tier)
    hero_map = fetch_hero_map_from_gtimg()
    rows = build_cn_rows_from_payload(payload=payload, role=role, tier=tier, hero_map=hero_map)
    update_cache(tier=tier, source_url=CN_PAGE_URL, raw_payload=payload)
    return rows, "cn_cache"


def _cached_cn_last_fetch() -> str | None:
    cache_payload = read_cache()
    if not cache_payload:
        return None
    return cache_payload.get("fetched_at")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_INDEX_PATH)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta(
    role: Role,
    tier: Tier,
    source: Source = "auto",
    name_lang: NameLang = "global",
    view: View = "draft",
    sort: SortField | None = None,
    dir: SortDir = "desc",
) -> dict[str, Any]:
    sort_field: SortField = sort or ("draft_score" if view == "draft" else "power_score")

    if source == "sample":
        rows = _filter_and_score(_load_meta_data(), role=role, tier=tier, sort=sort_field, direction=dir)
        return {"items": _with_champion_lang(rows, name_lang=name_lang), "source": "sample", "last_fetch": None}

    if source == "cn":
        try:
            cn_rows, used_source = _load_cn_with_cache(role=role, tier=tier)
            if not cn_rows:
                raise RuntimeError("CN source returned empty data")
            selected_position = {"top": 2, "jungle": 5, "mid": 1, "adc": 3, "support": 4}[role]
            preview = [
                {"hero_id": row.get("hero_id"), "position": row.get("position")}
                for row in cn_rows[:3]
            ]
            logger.info(
                "CN meta debug role=%s selected_position=%s first_entries=%s",
                role,
                selected_position,
                preview,
            )
            rows = _filter_and_score(cn_rows, role=role, tier=tier, sort=sort_field, direction=dir)
            return {
                "items": _with_champion_lang(rows, name_lang=name_lang),
                "source": used_source or "cn_cache",
                "last_fetch": _cached_cn_last_fetch(),
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"CN source unavailable: {exc}") from exc

    try:
        cn_rows, used_source = _load_cn_with_cache(role=role, tier=tier)
        if cn_rows:
            selected_position = {"top": 2, "jungle": 5, "mid": 1, "adc": 3, "support": 4}[role]
            preview = [
                {"hero_id": row.get("hero_id"), "position": row.get("position")}
                for row in cn_rows[:3]
            ]
            logger.info(
                "CN meta debug role=%s selected_position=%s first_entries=%s",
                role,
                selected_position,
                preview,
            )
            rows = _filter_and_score(cn_rows, role=role, tier=tier, sort=sort_field, direction=dir)
            return {
                "items": _with_champion_lang(rows, name_lang=name_lang),
                "source": used_source or "cn_cache",
                "last_fetch": _cached_cn_last_fetch(),
            }
    except Exception:
        pass

    rows = _filter_and_score(_load_meta_data(), role=role, tier=tier, sort=sort_field, direction=dir)
    return {"items": _with_champion_lang(rows, name_lang=name_lang), "source": "sample", "last_fetch": None}


@app.get("/meta/source")
def meta_source() -> dict[str, str | int | bool | None]:
    hero_map_age = hero_map_cache_age_seconds()
    cache_payload = read_cache()
    if not cache_payload:
        return {
            "source": "sample",
            "cache_age_seconds": 0,
            "cache_ttl_seconds": CACHE_TTL_SECONDS,
            "last_fetch": None,
            "source_url": None,
            "hero_map_available": hero_map_age is not None,
            "hero_map_age_seconds": hero_map_age,
            "cn_cache_has_positions": False,
        }

    age = cache_age_seconds(cache_payload)
    source_label = "cn_cache" if is_cache_fresh(cache_payload) else "sample"
    return {
        "source": source_label,
        "cache_age_seconds": age,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "last_fetch": cache_payload.get("fetched_at"),
        "source_url": cache_payload.get("source_url"),
        "hero_map_available": hero_map_age is not None,
        "hero_map_age_seconds": hero_map_age,
        "cn_cache_has_positions": bool(cache_payload.get("raw_payload_by_tier")),
    }


@app.get("/meta/debug/cn_positions")
def meta_debug_cn_positions(tier: Tier) -> dict[str, dict | str]:
    try:
        summary = summarize_cn_positions(tier=tier)
        return summary
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"CN source unavailable: {exc}") from exc
