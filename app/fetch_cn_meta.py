from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

CN_PAGE_URL = "https://lolm.qq.com/act/a20220818raider/index.html"
CACHE_TTL_SECONDS = 6 * 60 * 60
RATE_LIMIT_SECONDS = 10
MAX_RETRIES = 3
BACKOFF_SECONDS = [2, 4, 8]

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cn_meta_cache.json"

ROLE_TO_CN_POSITION = {
    "top": "2",
    "jungle": "5",
    "mid": "3",
    "adc": "4",
    "support": "6",
}

TIER_TO_CN_TIER = {
    "diamond": "1",
    "master": "2",
    "challenger": "3",
}


_rate_limit_lock = threading.Lock()
_last_qq_request_ts = 0.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_with_rate_limit(url: str) -> requests.Response:
    global _last_qq_request_ts

    with _rate_limit_lock:
        elapsed = time.monotonic() - _last_qq_request_ts
        if elapsed < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - elapsed)

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Referer": CN_PAGE_URL,
    }

    for attempt in range(MAX_RETRIES):
        response = requests.get(url, headers=headers, timeout=20)
        with _rate_limit_lock:
            _last_qq_request_ts = time.monotonic()

        if response.status_code not in (429, 503):
            response.raise_for_status()
            return response

        if attempt >= MAX_RETRIES - 1:
            response.raise_for_status()

        time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])

    raise RuntimeError("Unexpected request loop termination")


def _extract_script_urls(html_text: str) -> list[str]:
    script_urls = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE)
    return [urljoin(CN_PAGE_URL, src) for src in script_urls]


def discover_endpoints() -> dict[str, Any]:
    html = _request_with_rate_limit(CN_PAGE_URL).text
    script_urls = _extract_script_urls(html)

    api_urls: set[str] = set()
    for script_url in script_urls:
        if "lolm.qq.com/act/a20220818raider/js/" not in script_url:
            continue
        try:
            script_text = _request_with_rate_limit(script_url).text
        except requests.RequestException:
            continue

        for found in re.findall(r'getJSON\(["\']([^"\']+)["\']', script_text):
            api_urls.add(urljoin(CN_PAGE_URL, found))

    return {
        "page_url": CN_PAGE_URL,
        "script_urls": script_urls,
        "api_urls": sorted(api_urls),
    }


def _normalize_cn_row(row: dict[str, Any], role: str, tier: str) -> dict[str, Any]:
    hero_id = str(row.get("hero_id", "")).strip()
    champion = row.get("hero_name") or row.get("hero_title") or f"hero_{hero_id}"

    return {
        "champion": champion,
        "role": role,
        "tier": tier,
        "winrate": float(row.get("win_rate", 0.0)),
        "pickrate": float(row.get("appear_rate", 0.0)),
        "banrate": float(row.get("forbid_rate", 0.0)),
    }


def fetch_cn_meta(role: str, tier: str) -> list[dict[str, Any]]:
    if role not in ROLE_TO_CN_POSITION:
        raise ValueError(f"Unsupported role: {role}")
    if tier not in TIER_TO_CN_TIER:
        raise ValueError(f"Unsupported tier: {tier}")

    endpoints = discover_endpoints()
    list_url = next((u for u in endpoints.get("api_urls", []) if "hero_rank_list_v2" in u), None)
    if not list_url:
        list_url = "https://mlol.qt.qq.com/go/lgame_battle_info/hero_rank_list_v2"

    payload = _request_with_rate_limit(list_url).json()
    if payload.get("result") != 0:
        raise RuntimeError("CN API returned non-zero result")

    data = payload.get("data") or {}
    tier_bucket = data.get(TIER_TO_CN_TIER[tier]) or {}
    rows = tier_bucket.get(ROLE_TO_CN_POSITION[role]) or []

    normalized = [_normalize_cn_row(row, role=role, tier=tier) for row in rows]
    normalized = [row for row in normalized if row["champion"]]
    if not normalized:
        raise RuntimeError("CN API returned empty payload for requested role/tier")

    return normalized


def read_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None

    with CACHE_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def cache_age_seconds(cache_payload: dict[str, Any]) -> int:
    fetched_at = cache_payload.get("fetched_at")
    if not fetched_at:
        return 10**9

    parsed = datetime.fromisoformat(fetched_at)
    return int((datetime.now(timezone.utc) - parsed).total_seconds())


def is_cache_fresh(cache_payload: dict[str, Any]) -> bool:
    return cache_age_seconds(cache_payload) <= CACHE_TTL_SECONDS


def get_cached_meta(role: str, tier: str) -> list[dict[str, Any]] | None:
    cache_payload = read_cache()
    if not cache_payload or not is_cache_fresh(cache_payload):
        return None

    key = f"{role}:{tier}"
    rows = (cache_payload.get("items") or {}).get(key)
    if not rows:
        return None

    return rows


def update_cache(role: str, tier: str, rows: list[dict[str, Any]], source_url: str) -> None:
    payload = read_cache() or {"items": {}}
    payload["fetched_at"] = _iso_now()
    payload["source_url"] = source_url
    payload.setdefault("items", {})[f"{role}:{tier}"] = rows

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
