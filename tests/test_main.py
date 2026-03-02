from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


def _cn_payload_positions() -> dict:
    return {
        "result": 0,
        "data": {
            "0": {
                "1": [{"hero_id": 101, "position": "1", "win_rate": 0.51, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "2": [{"hero_id": 102, "position": "2", "win_rate": 0.52, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "3": [{"hero_id": 103, "position": "3", "win_rate": 0.53, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "4": [{"hero_id": 104, "position": "4", "win_rate": 0.54, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "5": [{"hero_id": 105, "position": "5", "win_rate": 0.55, "appear_rate": 0.10, "forbid_rate": 0.01}],
            }
        },
    }


def _cn_payload_positions_named() -> dict:
    return {
        "result": 0,
        "data": {
            "0": {
                "1": [{"hero_id": 401, "hero_name": "MID_HERO", "position": 1, "win_rate": 0.51, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "2": [{"hero_id": 402, "hero_name": "TOP_HERO", "position": "2", "win_rate": 0.52, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "3": [{"hero_id": 403, "hero_name": "ADC_HERO", "position": 3, "win_rate": 0.53, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "4": [{"hero_id": 404, "hero_name": "SUP_HERO", "position": "4", "win_rate": 0.54, "appear_rate": 0.10, "forbid_rate": 0.01}],
                "5": [{"hero_id": 405, "hero_name": "JG_HERO", "position": 5, "win_rate": 0.55, "appear_rate": 0.10, "forbid_rate": 0.01}],
            }
        },
    }


def _cn_payload_with_duplicates() -> dict:
    return {
        "result": 0,
        "data": {
            "0": {
                "1": [
                    {"hero_id": 201, "position": "2", "win_rate": 0.50, "appear_rate": 0.10, "forbid_rate": 0.20},
                    {"hero_id": 201, "position": "2", "win_rate": 0.55, "appear_rate": 0.11, "forbid_rate": 0.25},
                    {"hero_id": 202, "position": "2", "win_rate": 0.52, "appear_rate": 0.09, "forbid_rate": 0.10},
                ],
                "2": [
                    {"hero_id": 301, "position": "1", "win_rate": 0.51, "appear_rate": 0.12, "forbid_rate": 0.13}
                ],
            }
        },
    }


def test_meta_auto_fallbacks_to_sample_when_cn_fails(monkeypatch):
    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "sample"
    assert payload["items"]


def test_meta_cn_returns_502_when_cn_fails(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: (_ for _ in ()).throw(RuntimeError("boom")))

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "cn"})

    assert response.status_code == 502
    assert "CN source unavailable" in response.json()["detail"]


def test_cn_cache_within_ttl_skips_network_fetch(monkeypatch):
    cached_items = [
        {
            "champion": "hero_10138",
            "role": "top",
            "tier": "diamond",
            "winrate": 0.55,
            "pickrate": 0.12,
            "banrate": 0.33,
        }
    ]

    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: cached_items)

    called = {"fetch": False}

    def fake_fetch(tier: str):
        called["fetch"] = True
        return _cn_payload_positions()

    monkeypatch.setattr("app.main.fetch_cn_payload", fake_fetch)

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "cn_cache"
    assert called["fetch"] is False




def test_meta_cn_response_includes_last_fetch(monkeypatch):
    cached_items = [
        {
            "champion": "hero_10138",
            "role": "top",
            "tier": "diamond",
            "winrate": 0.55,
            "pickrate": 0.12,
            "banrate": 0.33,
        }
    ]

    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: cached_items)
    monkeypatch.setattr("app.main.read_cache", lambda: {"fetched_at": "2026-01-02T03:04:05+00:00"})

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "cn"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "cn_cache"
    assert payload["last_fetch"] == "2026-01-02T03:04:05+00:00"

def test_meta_name_lang_global_uses_global_champion_name(monkeypatch):
    cached_items = [
        {
            "hero_id": "23",
            "hero_name_cn": "蛮王",
            "hero_name_global": "Tryndamere",
            "champion": "蛮王",
            "role": "top",
            "tier": "diamond",
            "winrate": 0.55,
            "pickrate": 0.12,
            "banrate": 0.33,
        }
    ]

    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: cached_items)

    response = client.get(
        "/meta",
        params={"role": "top", "tier": "diamond", "source": "cn", "name_lang": "global"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["champion"] == "Tryndamere"


def test_meta_name_lang_cn_uses_chinese_champion_name(monkeypatch):
    cached_items = [
        {
            "hero_id": "23",
            "hero_name_cn": "蛮王",
            "hero_name_global": "Tryndamere",
            "champion": "Tryndamere",
            "role": "top",
            "tier": "diamond",
            "winrate": 0.55,
            "pickrate": 0.12,
            "banrate": 0.33,
        }
    ]

    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: cached_items)

    response = client.get(
        "/meta",
        params={"role": "top", "tier": "diamond", "source": "cn", "name_lang": "cn"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["champion"] == "蛮王"

def test_meta_source_returns_cn_cache_when_fresh(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    cache_payload = {
        "fetched_at": (now - timedelta(minutes=30)).isoformat(),
        "source_url": "https://lolm.qq.com/act/a20220818raider/index.html",
        "items": {},
    }
    cache_file = tmp_path / "cn_meta_cache.json"
    cache_file.write_text(json.dumps(cache_payload), encoding="utf-8")

    monkeypatch.setattr("app.fetch_cn_meta.CACHE_PATH", cache_file)

    response = client.get("/meta/source")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "cn_cache"
    assert body["cache_age_seconds"] >= 0
    assert body["cn_cache_has_positions"] is False


def test_meta_source_reports_hero_map_status(monkeypatch):
    monkeypatch.setattr("app.main.read_cache", lambda: None)
    monkeypatch.setattr("app.main.hero_map_cache_age_seconds", lambda: 42)

    response = client.get("/meta/source")

    assert response.status_code == 200
    body = response.json()
    assert body["hero_map_available"] is True
    assert body["hero_map_age_seconds"] == 42
    assert body["cn_cache_has_positions"] is False


def test_meta_cn_role_to_position_mapping_for_all_roles(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.update_cache", lambda tier, source_url, raw_payload: None)
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr("app.main.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: _DummyResponse(_cn_payload_positions()),
    )

    expected = {
        "top": "2",
        "jungle": "5",
        "mid": "1",
        "adc": "3",
        "support": "4",
    }

    for role, position in expected.items():
        response = client.get(
            "/meta",
            params={"role": role, "tier": "challenger", "source": "cn"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"]
        assert all(item["role"] == role for item in payload["items"])
        assert all(item["hero_id"] == str(100 + int(position)) for item in payload["items"])


def test_meta_cn_support_does_not_return_jungle(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.update_cache", lambda tier, source_url, raw_payload: None)
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr("app.main.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: _DummyResponse(_cn_payload_positions()),
    )

    response = client.get(
        "/meta",
        params={"role": "support", "tier": "challenger", "source": "cn"},
    )

    assert response.status_code == 200
    payload = response.json()
    hero_ids = {item["hero_id"] for item in payload["items"]}
    assert "104" in hero_ids
    assert "105" not in hero_ids


def test_meta_cn_dedup_by_hero_id_keeps_best_score(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.update_cache", lambda tier, source_url, raw_payload: None)
    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: _cn_payload_with_duplicates())
    monkeypatch.setattr("app.main.fetch_hero_map_from_gtimg", lambda: {})

    response = client.get("/meta", params={"role": "top", "tier": "challenger", "source": "cn"})

    assert response.status_code == 200
    payload = response.json()
    hero_ids = [item["hero_id"] for item in payload["items"]]
    assert hero_ids.count("201") == 1
    assert set(hero_ids) == {"201", "202"}
    best_201 = next(item for item in payload["items"] if item["hero_id"] == "201")
    assert best_201["banrate"] == 0.25


def test_cache_filter_per_request_does_not_shift_roles(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: _cn_payload_positions())
    monkeypatch.setattr("app.main.fetch_hero_map_from_gtimg", lambda: {})

    cached_payload: dict = {}

    def _capture_cache(tier, source_url, raw_payload):
        cached_payload["payload"] = raw_payload

    monkeypatch.setattr("app.main.update_cache", _capture_cache)

    response_top = client.get("/meta", params={"role": "top", "tier": "challenger", "source": "cn"})
    assert response_top.status_code == 200
    assert response_top.json()["items"][0]["hero_id"] == "102"

    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: (_ for _ in ()).throw(RuntimeError("should not fetch")))
    monkeypatch.setattr(
        "app.main.get_cached_meta",
        lambda role, tier: __import__("app.main", fromlist=["build_cn_rows_from_payload"]).build_cn_rows_from_payload(
            payload=cached_payload["payload"],
            role=role,
            tier=tier,
            hero_map={},
        ),
    )

    response_jungle = client.get("/meta", params={"role": "jungle", "tier": "challenger", "source": "cn"})

    assert response_jungle.status_code == 200
    assert response_jungle.json()["items"][0]["hero_id"] == "105"
    assert response_top.json()["items"][0]["hero_id"] != response_jungle.json()["items"][0]["hero_id"]


def test_meta_cn_uses_fixed_role_position_mapping_with_named_payload(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.update_cache", lambda tier, source_url, raw_payload: None)
    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: _cn_payload_positions_named())
    monkeypatch.setattr("app.main.fetch_hero_map_from_gtimg", lambda: {})

    expected_champion_by_role = {
        "top": "TOP_HERO",
        "jungle": "JG_HERO",
        "mid": "MID_HERO",
        "adc": "ADC_HERO",
        "support": "SUP_HERO",
    }

    for role, champion in expected_champion_by_role.items():
        response = client.get("/meta", params={"role": role, "tier": "challenger", "source": "cn"})
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["champion"] == champion


def test_meta_cn_cached_raw_payload_filters_per_request_with_fixed_mapping(monkeypatch):
    monkeypatch.setattr("app.main.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: _cn_payload_positions_named())
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)

    cached_payload: dict = {}

    def _capture_cache(tier, source_url, raw_payload):
        cached_payload["payload"] = raw_payload

    monkeypatch.setattr("app.main.update_cache", _capture_cache)

    top_response = client.get("/meta", params={"role": "top", "tier": "challenger", "source": "cn"})
    assert top_response.status_code == 200
    assert top_response.json()["items"][0]["champion"] == "TOP_HERO"

    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: (_ for _ in ()).throw(RuntimeError("should not fetch")))
    monkeypatch.setattr(
        "app.main.get_cached_meta",
        lambda role, tier: __import__("app.main", fromlist=["build_cn_rows_from_payload"]).build_cn_rows_from_payload(
            payload=cached_payload["payload"],
            role=role,
            tier=tier,
            hero_map={},
        ),
    )

    mid_response = client.get("/meta", params={"role": "mid", "tier": "challenger", "source": "cn"})
    assert mid_response.status_code == 200
    assert mid_response.json()["items"][0]["champion"] == "MID_HERO"
    assert top_response.json()["items"][0]["champion"] != mid_response.json()["items"][0]["champion"]


def test_meta_debug_cn_positions(monkeypatch):
    monkeypatch.setattr(
        "app.main.summarize_cn_positions",
        lambda tier: {
            "tier": tier,
            "positions": {
                "1": {"count": 1, "lane_dist": {"单人路": {"count": 1, "percent": 100.0}}, "dominant_lanes": ["单人路"], "top_bans": [{"hero_id": "103", "champion": "hero_103", "banrate": 0.2}]}
            },
        },
    )

    response = client.get("/meta/debug/cn_positions", params={"tier": "challenger"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tier"] == "challenger"
    assert payload["positions"]["1"]["count"] == 1
    assert payload["positions"]["1"]["top_bans"][0]["hero_id"] == "103"


def test_meta_returns_power_and_draft_scores():
    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "sample"})

    assert response.status_code == 200
    first = response.json()["items"][0]
    assert "priority_score" in first
    assert "power_score" in first
    assert "draft_score" in first


def test_meta_sorting_by_draft_and_power_score(monkeypatch):
    rows = [
        {"champion": "C", "role": "top", "tier": "diamond", "winrate": 0.53, "pickrate": 0.12, "banrate": 0.08},
        {"champion": "A", "role": "top", "tier": "diamond", "winrate": 0.50, "pickrate": 0.18, "banrate": 0.25},
        {"champion": "B", "role": "top", "tier": "diamond", "winrate": 0.57, "pickrate": 0.09, "banrate": 0.03},
    ]
    monkeypatch.setattr("app.main._load_meta_data", lambda: rows)

    draft_desc = client.get(
        "/meta",
        params={"role": "top", "tier": "diamond", "source": "sample", "sort": "draft_score", "dir": "desc"},
    )
    draft_asc = client.get(
        "/meta",
        params={"role": "top", "tier": "diamond", "source": "sample", "sort": "draft_score", "dir": "asc"},
    )
    power_desc = client.get(
        "/meta",
        params={"role": "top", "tier": "diamond", "source": "sample", "sort": "power_score", "dir": "desc"},
    )

    assert draft_desc.status_code == 200
    assert draft_asc.status_code == 200
    assert power_desc.status_code == 200

    draft_desc_champs = [item["champion"] for item in draft_desc.json()["items"]]
    draft_asc_champs = [item["champion"] for item in draft_asc.json()["items"]]
    power_desc_champs = [item["champion"] for item in power_desc.json()["items"]]

    assert draft_desc_champs == list(reversed(draft_asc_champs))
    assert power_desc_champs != draft_desc_champs


def test_meta_view_changes_default_sort(monkeypatch):
    rows = [
        {"champion": "C", "role": "top", "tier": "diamond", "winrate": 0.53, "pickrate": 0.12, "banrate": 0.08},
        {"champion": "A", "role": "top", "tier": "diamond", "winrate": 0.50, "pickrate": 0.18, "banrate": 0.25},
        {"champion": "B", "role": "top", "tier": "diamond", "winrate": 0.57, "pickrate": 0.09, "banrate": 0.03},
    ]
    monkeypatch.setattr("app.main._load_meta_data", lambda: rows)

    draft_view = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "sample", "view": "draft"})
    power_view = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "sample", "view": "power"})

    assert draft_view.status_code == 200
    assert power_view.status_code == 200

    draft_items = draft_view.json()["items"]
    power_items = power_view.json()["items"]

    assert draft_items[0]["draft_score"] == max(item["draft_score"] for item in draft_items)
    assert power_items[0]["power_score"] == max(item["power_score"] for item in power_items)
