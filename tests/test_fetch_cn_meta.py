from __future__ import annotations

from pathlib import Path

from app.fetch_cn_meta import _extract_hero_map, fetch_cn_meta


class DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


def _stats_payload(hero_id: int) -> dict:
    return {
        "result": 0,
        "data": {
            "1": {
                "2": [
                    {
                        "hero_id": hero_id,
                        "win_rate": 0.51,
                        "appear_rate": 0.12,
                        "forbid_rate": 0.09,
                    }
                ]
            }
        },
    }


def test_fetch_cn_meta_uses_gtimg_hero_map(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {"10001": {"hero_name_cn": "安妮", "hero_name_global": "Annie"}})
    monkeypatch.setattr("app.fetch_cn_meta._request_with_rate_limit", lambda url: DummyResponse(_stats_payload(10001)))

    rows = fetch_cn_meta(role="top", tier="diamond")

    assert rows
    assert rows[0]["champion"] == "Annie"


def test_fetch_cn_meta_fallbacks_to_hero_id_when_missing_in_map(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr("app.fetch_cn_meta._request_with_rate_limit", lambda url: DummyResponse(_stats_payload(19999)))

    rows = fetch_cn_meta(role="top", tier="diamond")

    assert rows
    assert rows[0]["champion"] == "hero_19999"


def test_extract_hero_map_from_js_fixture():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "hero_list_sample.js"
    js_text = fixture_path.read_text(encoding="utf-8")

    hero_map = _extract_hero_map(js_text)

    assert hero_map["10001"]["hero_name_cn"] == "蛮王"
    assert hero_map["10001"]["hero_name_global"] == "Tryndamere"
