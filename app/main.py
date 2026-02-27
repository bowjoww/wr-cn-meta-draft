from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.fetch_cn_meta import (
    CACHE_TTL_SECONDS,
    CN_PAGE_URL,
    cache_age_seconds,
    fetch_cn_meta,
    get_cached_meta,
    hero_map_cache_age_seconds,
    is_cache_fresh,
    read_cache,
    update_cache,
)
from app.scoring import priority_score

app = FastAPI(title="WR CN Meta Viewer")

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_cn_meta.json"
STATIC_INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"

Role = Literal["top", "jungle", "mid", "adc", "support"]
Tier = Literal["diamond", "master", "challenger"]
Source = Literal["auto", "sample", "cn"]


def _load_meta_data() -> list[dict]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _filter_and_score(rows: list[dict], role: Role, tier: Tier) -> list[dict]:
    filtered = [row for row in rows if row["role"] == role and row["tier"] == tier]
    if not filtered:
        raise HTTPException(status_code=404, detail="No meta data found for requested role/tier")

    for row in filtered:
        row["priority_score"] = priority_score(
            winrate=row["winrate"],
            pickrate=row["pickrate"],
            banrate=row["banrate"],
        )

    return sorted(filtered, key=lambda item: item["priority_score"], reverse=True)


def _load_cn_with_cache(role: Role, tier: Tier) -> tuple[list[dict] | None, str | None]:
    cached_rows = get_cached_meta(role=role, tier=tier)
    if cached_rows:
        return cached_rows, "cn_cache"

    rows = fetch_cn_meta(role=role, tier=tier)
    update_cache(role=role, tier=tier, rows=rows, source_url=CN_PAGE_URL)
    return rows, "cn_cache"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_INDEX_PATH)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta(role: Role, tier: Tier, source: Source = "auto") -> dict[str, list[dict] | str]:
    if source == "sample":
        rows = _filter_and_score(_load_meta_data(), role=role, tier=tier)
        return {"items": rows, "source": "sample"}

    if source == "cn":
        try:
            cn_rows, used_source = _load_cn_with_cache(role=role, tier=tier)
            if not cn_rows:
                raise RuntimeError("CN source returned empty data")
            return {"items": _filter_and_score(cn_rows, role=role, tier=tier), "source": used_source or "cn_cache"}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"CN source unavailable: {exc}") from exc

    try:
        cn_rows, used_source = _load_cn_with_cache(role=role, tier=tier)
        if cn_rows:
            return {"items": _filter_and_score(cn_rows, role=role, tier=tier), "source": used_source or "cn_cache"}
    except Exception:
        pass

    rows = _filter_and_score(_load_meta_data(), role=role, tier=tier)
    return {"items": rows, "source": "sample"}


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
    }
