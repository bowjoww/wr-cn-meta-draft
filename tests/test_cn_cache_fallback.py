from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_meta_auto_uses_stale_cn_cache_when_live_fetch_fails(monkeypatch):
    stale_items = [
        {
            "champion": "hero_10138",
            "role": "top",
            "tier": "diamond",
            "winrate": 0.55,
            "pickrate": 0.12,
            "banrate": 0.33,
        }
    ]

    monkeypatch.setattr("app.main.fetch_cn_payload", lambda tier: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("app.main.get_cached_meta", lambda role, tier: None)
    monkeypatch.setattr("app.main.get_stale_cached_meta", lambda role, tier: stale_items)

    response = client.get("/meta", params={"role": "top", "tier": "diamond", "source": "auto"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "cn_stale_cache"
    assert payload["items"]


def test_meta_source_reports_stale_cn_cache_when_payload_exists(tmp_path, monkeypatch):
    cache_payload = {
        "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat(),
        "source_url": "https://lolm.qq.com/act/a20220818raider/index.html",
        "raw_payload_by_tier": {
            "diamond": {
                "result": 0,
                "data": {
                    "0": {
                        "1": [
                            {
                                "hero_id": 101,
                                "position": "1",
                                "win_rate": 0.51,
                                "appear_rate": 0.10,
                                "forbid_rate": 0.01,
                            }
                        ]
                    }
                },
            }
        },
    }
    cache_file = tmp_path / "cn_meta_cache.json"
    cache_file.write_text(json.dumps(cache_payload), encoding="utf-8")

    monkeypatch.setattr("app.fetch_cn_meta.CACHE_PATH", cache_file)

    response = client.get("/meta/source")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "cn_stale_cache"
    assert body["cn_cache_has_positions"] is True


def test_fetch_hero_map_uses_stale_cache_when_refresh_fails(tmp_path, monkeypatch):
    cache_file = tmp_path / "cn_hero_map.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
                "source_url": "https://game.gtimg.cn/images/lgamem/act/lrlib/js/heroList/hero_list.js",
                "items": {"10001": {"hero_name_global": "Tryndamere"}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("app.fetch_cn_meta.HERO_MAP_CACHE_PATH", cache_file)
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    from app.fetch_cn_meta import fetch_hero_map_from_gtimg

    hero_map = fetch_hero_map_from_gtimg()

    assert hero_map["10001"]["hero_name_global"] == "Tryndamere"
