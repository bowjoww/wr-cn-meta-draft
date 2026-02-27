from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


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
