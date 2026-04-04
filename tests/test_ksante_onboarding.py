"""Tests for KSante Patch 7.1 onboarding (hero_id 10167)."""

from __future__ import annotations

import difflib
import json
from pathlib import Path


HERO_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "cn_hero_map.json"


def _load_hero_map() -> dict:
    with HERO_MAP_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _hero_map_to_champion_list(items: dict) -> list[dict]:
    from app.fetch_cn_meta import DISPLAY_NAME_OVERRIDES
    champions = []
    for hero_id, data in items.items():
        raw_name = data.get("hero_name_global") or data.get("hero_name_cn") or f"hero_{hero_id}"
        name_global = DISPLAY_NAME_OVERRIDES.get(raw_name, raw_name)
        champions.append({
            "hero_id": hero_id,
            "name": name_global,
            "name_cn": data.get("hero_name_cn", ""),
            "lane": data.get("lane", ""),
        })
    return champions


class TestKSanteHeroMap:
    def test_ksante_present_in_hero_map(self):
        data = _load_hero_map()
        items = data.get("items", {})
        assert "10167" in items, "KSante entry (hero_id 10167) not found in cn_hero_map.json"

    def test_ksante_global_name(self):
        data = _load_hero_map()
        entry = data["items"]["10167"]
        assert entry.get("hero_name_global") == "KSante"

    def test_ksante_cn_name(self):
        data = _load_hero_map()
        entry = data["items"]["10167"]
        assert entry.get("hero_name_cn") == "克烈"

    def test_ksante_lane_is_top(self):
        data = _load_hero_map()
        entry = data["items"]["10167"]
        assert "单人路" in entry.get("lane", ""), "KSante should have top lane (单人路)"

    def test_ksante_has_asset_urls(self):
        data = _load_hero_map()
        entry = data["items"]["10167"]
        assert entry.get("avatar_url"), "KSante should have avatar_url"
        assert entry.get("card_url"), "KSante should have card_url"
        assert entry.get("poster_url"), "KSante should have poster_url"


class TestKSanteChampionPicker:
    def test_ksante_in_champion_picker_list(self):
        data = _load_hero_map()
        items = data.get("items", {})
        champions = _hero_map_to_champion_list(items)
        names = [c["name"] for c in champions]
        assert "KSante" in names, f"KSante not found in champion picker list (got {len(names)} champions)"

    def test_champion_picker_total_count(self):
        data = _load_hero_map()
        items = data.get("items", {})
        assert len(items) >= 137, "Hero map should have at least 137 entries after KSante onboarding"


class TestKSanteOCRFuzzy:
    """Verify fuzzy matching resolves KSante variants correctly."""

    @staticmethod
    def _fuzzy_match(name: str, known: list[str]) -> str | None:
        from app.fetch_cn_meta import DISPLAY_NAME_OVERRIDES
        name = DISPLAY_NAME_OVERRIDES.get(name, name)
        known_lower = {n.lower(): n for n in known}
        if name.lower() in known_lower:
            return known_lower[name.lower()]
        matches = difflib.get_close_matches(name.lower(), known_lower.keys(), n=1, cutoff=0.6)
        return known_lower[matches[0]] if matches else None

    def _champion_names(self) -> list[str]:
        data = _load_hero_map()
        items = data.get("items", {})
        return [c["name"] for c in _hero_map_to_champion_list(items)]

    def test_exact_match(self):
        assert self._fuzzy_match("KSante", self._champion_names()) == "KSante"

    def test_lowercase(self):
        assert self._fuzzy_match("ksante", self._champion_names()) == "KSante"

    def test_apostrophe_variant(self):
        assert self._fuzzy_match("K'Sante", self._champion_names()) == "KSante"

    def test_space_variant(self):
        assert self._fuzzy_match("K Sante", self._champion_names()) == "KSante"

    def test_dash_variant(self):
        assert self._fuzzy_match("K-Sante", self._champion_names()) == "KSante"
