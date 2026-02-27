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


def test_meta_auto_fallbacks_to_sample_when_cn_fails(monkeypatch):
    def fake_fail_fetch(role: str, tier: str):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.fetch_cn_meta", fake_fail_fetch)
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "sample"
    assert payload["items"]


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

    def fake_fetch(role: str, tier: str):
        called["fetch"] = True
        return []

    monkeypatch.setattr("app.main.fetch_cn_meta", fake_fetch)

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "cn_cache"
    assert called["fetch"] is False




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


def test_meta_source_reports_hero_map_status(monkeypatch):
    monkeypatch.setattr("app.main.read_cache", lambda: None)
    monkeypatch.setattr("app.main.hero_map_cache_age_seconds", lambda: 42)

    response = client.get("/meta/source")

    assert response.status_code == 200
    body = response.json()
    assert body["hero_map_available"] is True
    assert body["hero_map_age_seconds"] == 42


def test_meta_cn_role_to_position_mapping_for_all_roles(monkeypatch):
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.update_cache", lambda role, tier, rows, source_url: None)
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: _DummyResponse(_cn_payload_positions()),
    )

    expected = {
        "top": "1",
        "jungle": "2",
        "mid": "3",
        "adc": "4",
        "support": "5",
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
    monkeypatch.setattr("app.main.update_cache", lambda role, tier, rows, source_url: None)
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
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
    assert "105" in hero_ids
    assert "102" not in hero_ids
