from __future__ import annotations

from pathlib import Path

from app.fetch_cn_meta import _extract_hero_map, extract_cn_entries, fetch_cn_meta


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
                "1": [
                    {
                        "hero_id": hero_id,
                        "position": "1",
                        "win_rate": 0.51,
                        "appear_rate": 0.12,
                        "forbid_rate": 0.09,
                    }
                ]
            }
        },
    }


def _stats_payload_by_position(position_to_hero_id: dict[str, int]) -> dict:
    return {
        "result": 0,
        "data": {
            "1": {
                "hero_rank_list": {
                    "grouped": {
                        position: {
                            "entries": [
                                {
                                    "hero_id": hero_id,
                                    "position": position,
                                    "win_rate": 0.51,
                                    "appear_rate": 0.12,
                                    "forbid_rate": 0.09,
                                }
                            ]
                        }
                        for position, hero_id in position_to_hero_id.items()
                    }
                }
            }
        },
    }


def _nested_stats_payload_with_mixed_positions() -> dict:
    return {
        "result": 0,
        "data": {
            "1": {
                "segment_a": {
                    "items": [
                        {"hero_id": 10001, "position": "1", "win_rate": 0.51, "appear_rate": 0.12, "forbid_rate": 0.09},
                        {"hero_id": 10002, "position": "2", "win_rate": 0.52, "appear_rate": 0.13, "forbid_rate": 0.08},
                    ]
                },
                "segment_b": {
                    "deep": {
                        "list": [
                            {"hero_id": 10003, "position": "3", "win_rate": 0.53, "appear_rate": 0.14, "forbid_rate": 0.07},
                            {"hero_id": 10004, "position": "4", "win_rate": 0.54, "appear_rate": 0.15, "forbid_rate": 0.06},
                            {"hero_id": 10005, "position": "5", "win_rate": 0.55, "appear_rate": 0.16, "forbid_rate": 0.05},
                        ]
                    }
                },
                "metadata": {"version": 2},
            }
        },
    }




def test_extract_cn_entries_from_nested_payload():
    payload = {
        "result": 0,
        "data": {
            "3": {
                "blocks": {
                    "0": [
                        {"hero_id": 10010, "position": "3", "win_rate": 0.51, "appear_rate": 0.12, "forbid_rate": 0.09},
                        {"hero_id": 10010, "position": "2", "win_rate": 0.48, "appear_rate": 0.08, "forbid_rate": 0.02},
                    ],
                    "1": {
                        "rows": [
                            {"hero_id": 10011, "position": "3", "win_rate_percent": "53.63", "appear_rate_percent": "11.00", "forbid_rate_percent": "2.40"},
                            {"foo": "bar"},
                        ]
                    },
                }
            }
        },
    }

    rows = extract_cn_entries(payload)

    assert len(rows) == 3
    assert {str(row["hero_id"]) for row in rows} == {"10010", "10011"}


def test_fetch_cn_meta_uses_gtimg_hero_map(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {"10001": {"hero_name_cn": "安妮", "hero_name_global": "Annie"}})
    monkeypatch.setattr("app.fetch_cn_meta._request_with_rate_limit", lambda url: DummyResponse(_stats_payload(10001)))

    rows = fetch_cn_meta(role="mid", tier="diamond")

    assert rows
    assert rows[0]["champion"] == "Annie"


def test_fetch_cn_meta_fallbacks_to_hero_id_when_missing_in_map(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr("app.fetch_cn_meta._request_with_rate_limit", lambda url: DummyResponse(_stats_payload(19999)))

    rows = fetch_cn_meta(role="mid", tier="diamond")

    assert rows
    assert rows[0]["champion"] == "hero_19999"


def test_extract_hero_map_from_js_fixture():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "hero_list_sample.js"
    js_text = fixture_path.read_text(encoding="utf-8")

    hero_map = _extract_hero_map(js_text)

    assert hero_map["10001"]["hero_name_cn"] == "蛮王"
    assert hero_map["10001"]["hero_name_global"] == "Tryndamere"


def test_fetch_cn_meta_role_position_mapping_mid_adc_support(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: DummyResponse(
            _stats_payload_by_position(
                {
                    "1": 10001,
                    "2": 10002,
                    "3": 10003,
                    "4": 10004,
                    "5": 10005,
                }
            )
        ),
    )

    mid_rows = fetch_cn_meta(role="mid", tier="diamond")
    adc_rows = fetch_cn_meta(role="adc", tier="diamond")
    support_rows = fetch_cn_meta(role="support", tier="diamond")

    assert mid_rows[0]["hero_id"] == "10001"
    assert adc_rows[0]["hero_id"] == "10003"
    assert support_rows[0]["hero_id"] == "10004"


def test_fetch_cn_meta_role_filtering_uses_row_position_without_rotation(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: DummyResponse(_nested_stats_payload_with_mixed_positions()),
    )

    assert fetch_cn_meta(role="top", tier="diamond")[0]["hero_id"] == "10002"
    assert fetch_cn_meta(role="jungle", tier="diamond")[0]["hero_id"] == "10005"
    assert fetch_cn_meta(role="mid", tier="diamond")[0]["hero_id"] == "10001"
    assert fetch_cn_meta(role="adc", tier="diamond")[0]["hero_id"] == "10003"
    assert fetch_cn_meta(role="support", tier="diamond")[0]["hero_id"] == "10004"


def test_fetch_cn_meta_filters_multilane_duplicates_by_position(monkeypatch):
    monkeypatch.setattr("app.fetch_cn_meta.fetch_hero_map_from_gtimg", lambda: {})
    monkeypatch.setattr(
        "app.fetch_cn_meta._request_with_rate_limit",
        lambda url: DummyResponse(
            {
                "result": 0,
                "data": {
                    "1": {
                        "mixed": [
                            {"hero_id": 10099, "position": "2", "win_rate": 0.5, "appear_rate": 0.1, "forbid_rate": 0.01},
                            {"hero_id": 10099, "position": "3", "win_rate": 0.6, "appear_rate": 0.2, "forbid_rate": 0.02},
                            {"hero_id": 10100, "position": "3", "win_rate": 0.55, "appear_rate": 0.11, "forbid_rate": 0.03},
                        ]
                    }
                },
            }
        ),
    )

    adc_rows = fetch_cn_meta(role="adc", tier="diamond")

    assert {row["hero_id"] for row in adc_rows} == {"10099", "10100"}
    assert all(row["position"] == 3 for row in adc_rows)




def test_summarize_cn_positions_groups_lane_distribution(monkeypatch):
    monkeypatch.setattr(
        "app.fetch_cn_meta.get_cached_raw_payload",
        lambda tier: {
            "result": 0,
            "data": {
                "3": {
                    "rows": [
                        {"hero_id": 10001, "position": "1", "win_rate": 0.51, "appear_rate": 0.10, "forbid_rate": 0.30},
                        {"hero_id": 10002, "position": "1", "win_rate": 0.52, "appear_rate": 0.10, "forbid_rate": 0.20},
                        {"hero_id": 10003, "position": "2", "win_rate": 0.53, "appear_rate": 0.10, "forbid_rate": 0.10},
                    ]
                }
            },
        },
    )
    monkeypatch.setattr(
        "app.fetch_cn_meta.fetch_hero_map_from_gtimg",
        lambda: {
            "10001": {"hero_name_global": "Aatrox", "lane": "单人路"},
            "10002": {"hero_name_global": "Graves", "lane": "打野;单人路"},
            "10003": {"hero_name_global": "Ahri", "lane": "中路"},
        },
    )

    from app.fetch_cn_meta import summarize_cn_positions

    payload = summarize_cn_positions(tier="challenger")

    assert payload["tier"] == "challenger"
    assert payload["positions"]["1"]["count"] == 2
    assert payload["positions"]["1"]["lane_dist"]["单人路"]["count"] == 2
    assert payload["positions"]["1"]["top_bans"][0]["hero_id"] == "10001"
    assert payload["positions"]["2"]["dominant_lanes"] == ["中路"]
