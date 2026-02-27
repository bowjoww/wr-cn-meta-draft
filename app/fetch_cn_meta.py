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

from app.scoring import priority_score

CN_PAGE_URL = "https://lolm.qq.com/act/a20220818raider/index.html"
HERO_MAP_URL = "https://game.gtimg.cn/images/lgamem/act/lrlib/js/heroList/hero_list.js"
HERO_STATS_URL = "https://mlol.qt.qq.com/go/lgame_battle_info/hero_rank_list_v2"
CACHE_TTL_SECONDS = 6 * 60 * 60
HERO_MAP_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
RATE_LIMIT_SECONDS = 10
MAX_RETRIES = 3
BACKOFF_SECONDS = [2, 4, 8]

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cn_meta_cache.json"
HERO_MAP_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "cn_hero_map.json"

ROLE_TO_POSITION = {
    "top": 1,
    "jungle": 2,
    "mid": 3,
    "adc": 4,
    "support": 5,
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

    api_urls.add(HERO_STATS_URL)
    return {
        "page_url": CN_PAGE_URL,
        "hero_map_url": HERO_MAP_URL,
        "script_urls": script_urls,
        "api_urls": sorted(api_urls),
    }


def _extract_hero_map(js_text: str) -> dict[str, dict[str, str]]:
    parse_errors: list[str] = []
    payload_candidates: list[tuple[str, str]] = []

    assignment_pattern = re.compile(
        r"(?:var\s+\w+|window\.\w+)\s*=\s*([\[{].*?[\]}])\s*;",
        flags=re.DOTALL,
    )
    for match in assignment_pattern.finditer(js_text):
        payload_candidates.append(("assignment_regex", match.group(1)))

    first_list = js_text.find("[")
    last_list = js_text.rfind("]")
    if 0 <= first_list < last_list:
        payload_candidates.append(("list_slice", js_text[first_list : last_list + 1]))
    else:
        parse_errors.append("list_slice: no valid '[' ... ']' segment found")

    first_object = js_text.find("{")
    last_object = js_text.rfind("}")
    if 0 <= first_object < last_object:
        payload_candidates.append(("object_slice", js_text[first_object : last_object + 1]))
    else:
        parse_errors.append("object_slice: no valid '{' ... '}' segment found")

    parsed_payload: Any | None = None
    for strategy, payload in payload_candidates:
        parsed_payload = _parse_json_like_payload(payload)
        if parsed_payload is not None:
            break
        parse_errors.append(f"{strategy}: failed to decode payload")

    if parsed_payload is None:
        detail = "; ".join(parse_errors) if parse_errors else "unknown parser error"
        raise RuntimeError(f"Could not parse hero map from hero_list.js ({detail})")

    hero_map = _build_hero_map(parsed_payload)
    if not hero_map:
        raise RuntimeError("Could not parse hero map from hero_list.js (no hero rows found)")
    return hero_map


def _parse_json_like_payload(payload: str) -> Any | None:
    payload = payload.strip().rstrip(";")
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        pass

    normalized = _normalize_json_like_payload(payload)
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        return None


def _normalize_json_like_payload(payload: str) -> str:
    normalized = re.sub(r",\s*([}\]])", r"\1", payload)
    normalized = re.sub(r'([\{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', normalized)

    def _replace_single_quote(match: re.Match[str]) -> str:
        content = match.group(1)
        content = content.replace('\\"', '"')
        content = content.replace('"', '\\"')
        return f'"{content}"'

    return re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", _replace_single_quote, normalized)


def _global_name_from_poster(poster: str | None) -> str | None:
    if not poster:
        return None
    basename = Path(str(poster).split("?", 1)[0]).name
    if not basename:
        return None

    normalized = re.sub(r"_\d+\.[^.]+$", "", basename)
    if not normalized:
        return None
    return normalized


def _build_hero_map(payload: Any) -> dict[str, dict[str, str]]:
    hero_map: dict[str, dict[str, str]] = {}

    def _visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                _visit(item)
            return

        if not isinstance(node, dict):
            return

        hero_id_value = None
        for hero_id_key in ("heroId", "hero_id", "id"):
            if hero_id_key in node:
                hero_id_value = node.get(hero_id_key)
                break

        hero_name_cn = None
        for name_key in ("name", "cname", "title"):
            if node.get(name_key):
                hero_name_cn = node.get(name_key)
                break

        hero_name_global = _global_name_from_poster(node.get("poster"))

        if hero_id_value is not None and (hero_name_cn or hero_name_global):
            try:
                hero_id = int(str(hero_id_value).strip())
            except ValueError:
                hero_id = None

            if hero_id is not None:
                row: dict[str, str] = {}
                if hero_name_cn:
                    row["hero_name_cn"] = str(hero_name_cn).strip()
                if hero_name_global:
                    row["hero_name_global"] = str(hero_name_global).strip()
                if row:
                    hero_map[str(hero_id)] = row

        for value in node.values():
            _visit(value)

    _visit(payload)
    return hero_map


def _read_json_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _cache_age_from_fetched_at(fetched_at: str | None) -> int:
    if not fetched_at:
        return 10**9
    parsed = datetime.fromisoformat(fetched_at)
    return int((datetime.now(timezone.utc) - parsed).total_seconds())


def fetch_hero_map_from_gtimg() -> dict[str, dict[str, str]]:
    cache_payload = _read_json_cache(HERO_MAP_CACHE_PATH)
    if cache_payload and _cache_age_from_fetched_at(cache_payload.get("fetched_at")) <= HERO_MAP_CACHE_TTL_SECONDS:
        return (cache_payload.get("items") or {})

    js_text = _request_with_rate_limit(HERO_MAP_URL).text
    hero_map = _extract_hero_map(js_text)
    payload = {
        "fetched_at": _iso_now(),
        "source_url": HERO_MAP_URL,
        "items": hero_map,
    }
    HERO_MAP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HERO_MAP_CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return hero_map


def hero_map_cache_age_seconds() -> int | None:
    cache_payload = _read_json_cache(HERO_MAP_CACHE_PATH)
    if not cache_payload:
        return None
    return _cache_age_from_fetched_at(cache_payload.get("fetched_at"))


def _normalize_cn_row(row: dict[str, Any], role: str, tier: str, hero_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    hero_id = str(row.get("hero_id", "")).strip()
    hero_data = hero_map.get(hero_id) or {}
    hero_name_cn = hero_data.get("hero_name_cn") or row.get("hero_name") or row.get("hero_title")
    hero_name_global = hero_data.get("hero_name_global")
    champion = (
        hero_name_global
        or hero_name_cn
        or f"hero_{hero_id}"
    )

    normalized = {
        "hero_id": hero_id,
        "hero_name_cn": hero_name_cn,
        "hero_name_global": hero_name_global,
        "champion": champion,
        "role": role,
        "tier": tier,
        "position": _safe_int(row.get("position")),
        "winrate": _rate_to_ratio(row, "win_rate", "win_rate_percent"),
        "pickrate": _rate_to_ratio(row, "appear_rate", "appear_rate_percent"),
        "banrate": _rate_to_ratio(row, "forbid_rate", "forbid_rate_percent"),
    }
    normalized["priority_score"] = priority_score(
        winrate=normalized["winrate"],
        pickrate=normalized["pickrate"],
        banrate=normalized["banrate"],
    )
    return normalized


def _collect_hero_entries(node: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def _visit(current: Any) -> None:
        if isinstance(current, list):
            for item in current:
                _visit(item)
            return

        if not isinstance(current, dict):
            return

        if current.get("hero_id") is not None:
            entries.append(current)

        for value in current.values():
            _visit(value)

    _visit(node)
    return entries


def _safe_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _rate_to_ratio(row: dict[str, Any], raw_key: str, percent_key: str) -> float:
    raw_value = _as_float(row.get(raw_key))
    if raw_value is not None:
        return raw_value / 100.0 if raw_value > 1 else raw_value

    percent_value = _as_float(row.get(percent_key))
    if percent_value is not None:
        return percent_value / 100.0
    return 0.0


def role_to_position(role: str) -> int:
    normalized = str(role).strip().lower()
    if normalized not in ROLE_TO_POSITION:
        raise ValueError(f"Unsupported role: {role}")
    return ROLE_TO_POSITION[normalized]


def _matches_position(entry: dict[str, Any], expected_position: int) -> bool:
    return _safe_int(entry.get("position")) == expected_position


def extract_cn_entries(payload: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def _visit(current: Any) -> None:
        if isinstance(current, list):
            for item in current:
                _visit(item)
            return

        if not isinstance(current, dict):
            return

        has_minimum_fields = (
            current.get("hero_id") is not None
            and current.get("position") is not None
            and (current.get("win_rate") is not None or current.get("win_rate_percent") is not None)
            and (current.get("appear_rate") is not None or current.get("appear_rate_percent") is not None)
            and (current.get("forbid_rate") is not None or current.get("forbid_rate_percent") is not None)
        )
        if has_minimum_fields:
            entries.append(current)

        for value in current.values():
            _visit(value)

    _visit(payload)
    return entries


def _tier_candidate_nodes(payload: dict[str, Any], tier: str) -> list[Any]:
    data = payload.get("data") or {}
    tier_key = TIER_TO_CN_TIER[tier]
    if not isinstance(data, dict):
        return [data]

    candidates: list[Any] = []
    for key in (tier_key, "0"):
        node = data.get(key)
        if node is not None:
            candidates.append(node)
    if not candidates:
        candidates.append(data)
    return candidates


def fetch_cn_payload(tier: str) -> dict[str, Any]:
    if tier not in TIER_TO_CN_TIER:
        raise ValueError(f"Unsupported tier: {tier}")

    payload = _request_with_rate_limit(HERO_STATS_URL).json()
    if payload.get("result") != 0:
        raise RuntimeError("CN API returned non-zero result")
    return payload


def build_cn_rows_from_payload(payload: dict[str, Any], role: str, tier: str, hero_map: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    position = role_to_position(role)
    all_entries: list[dict[str, Any]] = []
    for node in _tier_candidate_nodes(payload, tier):
        all_entries.extend(extract_cn_entries(node))

    entries = [entry for entry in all_entries if _matches_position(entry, position)]
    normalized = [_normalize_cn_row(entry, role=role, tier=tier, hero_map=hero_map) for entry in entries]
    normalized = [row for row in normalized if row["champion"]]
    deduped = dedup_rows_by_hero_id(normalized)
    if not deduped:
        raise RuntimeError("CN API returned empty payload for requested role/position")
    return deduped


def dedup_rows_by_hero_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners: dict[str, dict[str, Any]] = {}
    for row in rows:
        hero_id = str(row.get("hero_id", "")).strip()
        if not hero_id:
            continue
        current = winners.get(hero_id)
        if current is None or _is_row_better(row, current):
            winners[hero_id] = row
    return list(winners.values())


def _is_row_better(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
    candidate_key = (
        candidate.get("priority_score", 0.0),
        candidate.get("banrate", 0.0),
        candidate.get("pickrate", 0.0),
    )
    incumbent_key = (
        incumbent.get("priority_score", 0.0),
        incumbent.get("banrate", 0.0),
        incumbent.get("pickrate", 0.0),
    )
    return candidate_key > incumbent_key


def summarize_cn_positions(payload: dict[str, Any], tier: str, hero_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    counts: dict[str, int] = {str(pos): 0 for pos in range(1, 6)}
    top_by_position: dict[str, list[dict[str, Any]]] = {str(pos): [] for pos in range(1, 6)}

    all_entries: list[dict[str, Any]] = []
    for node in _tier_candidate_nodes(payload, tier):
        all_entries.extend(extract_cn_entries(node))

    for entry in all_entries:
        position = _safe_int(entry.get("position"))
        if position is None:
            continue
        key = str(position)
        if key not in counts:
            counts[key] = 0
            top_by_position[key] = []
        counts[key] += 1

        top_by_position[key].append(
            _normalize_cn_row(
                entry,
                role="debug",
                tier=tier,
                hero_map=hero_map,
            )
        )

    top3 = {
        key: sorted(rows, key=lambda item: item.get("banrate", 0.0), reverse=True)[:3]
        for key, rows in top_by_position.items()
    }
    return {"counts": counts, "top3_by_banrate": top3}


def fetch_cn_meta(role: str, tier: str) -> list[dict[str, Any]]:
    role_to_position(role)
    hero_map = fetch_hero_map_from_gtimg()
    payload = fetch_cn_payload(tier=tier)
    return build_cn_rows_from_payload(payload=payload, role=role, tier=tier, hero_map=hero_map)


def read_cache() -> dict[str, Any] | None:
    return _read_json_cache(CACHE_PATH)


def cache_age_seconds(cache_payload: dict[str, Any]) -> int:
    return _cache_age_from_fetched_at(cache_payload.get("fetched_at"))


def is_cache_fresh(cache_payload: dict[str, Any]) -> bool:
    return cache_age_seconds(cache_payload) <= CACHE_TTL_SECONDS


def get_cached_meta(role: str, tier: str) -> list[dict[str, Any]] | None:
    cache_payload = read_cache()
    if not cache_payload or not is_cache_fresh(cache_payload):
        return None

    raw_payload = (cache_payload.get("raw_payload_by_tier") or {}).get(tier)
    if raw_payload:
        hero_map = fetch_hero_map_from_gtimg()
        try:
            return build_cn_rows_from_payload(payload=raw_payload, role=role, tier=tier, hero_map=hero_map)
        except RuntimeError:
            return None

    # Backward compatibility with legacy cache shape storing role:tier lists.
    key = f"{role}:{tier}"
    rows = (cache_payload.get("items") or {}).get(key)
    return rows or None


def get_cached_raw_payload(tier: str) -> dict[str, Any] | None:
    cache_payload = read_cache()
    if not cache_payload or not is_cache_fresh(cache_payload):
        return None
    return (cache_payload.get("raw_payload_by_tier") or {}).get(tier)


def update_cache(tier: str, source_url: str, raw_payload: dict[str, Any]) -> None:
    payload = read_cache() or {}
    payload["fetched_at"] = _iso_now()
    payload["source_url"] = source_url
    payload.setdefault("raw_payload_by_tier", {})[tier] = raw_payload

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
