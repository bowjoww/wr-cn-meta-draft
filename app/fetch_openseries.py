"""Scraper for openseries.com.br/campeoes/ champion stats."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

OPENSERIES_URL = "https://openseries.com.br/campeoes/"
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "openseries_cache.json"
CACHE_TTL_SECONDS = 3600 * 6  # 6 hours


class OpenSeriesChampion(TypedDict):
    champion: str
    picks: int
    pick_rate: float
    bans: int
    ban_rate: float
    win_rate: float
    wins: int
    losses: int
    kda: float
    avg_kills: float
    avg_deaths: float
    avg_assists: float
    avg_gold: float


def _parse_float(text: str) -> float:
    """Parse a float from a string, stripping % and commas."""
    cleaned = text.strip().replace("%", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int(text: str) -> int:
    try:
        return int(text.strip().replace(",", ""))
    except ValueError:
        return 0


def _parse_kda_breakdown(text: str) -> tuple[float, float, float]:
    """Parse 'K/D/A MÉDIOS' cell like '2.8/2.5/4.8' into (k, d, a)."""
    parts = text.strip().split("/")
    if len(parts) == 3:
        return _parse_float(parts[0]), _parse_float(parts[1]), _parse_float(parts[2])
    return 0.0, 0.0, 0.0


def _parse_win_loss(text: str) -> tuple[int, int]:
    """Parse win/loss record from 'W/L' cell like '20W 15L' or '20/15'."""
    # Try pattern: "20W 15L" or "20w15l"
    m = re.search(r"(\d+)[Ww]\s*(\d+)[Ll]", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Try "20/15"
    parts = text.strip().split("/")
    if len(parts) == 2:
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            pass
    return 0, 0


def scrape_openseries() -> list[OpenSeriesChampion]:
    """Fetch and parse champion stats from openseries.com.br/campeoes/."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    resp = requests.get(OPENSERIES_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return _parse_html(resp.text)


def _parse_html(html: str) -> list[OpenSeriesChampion]:
    soup = BeautifulSoup(html, "html.parser")

    # Find the main table
    table = soup.find("table", class_=lambda c: c and "os-table" in c.split())
    if not table:
        # Fallback: find any table with these headers
        table = soup.find("table")
    if not table:
        logger.warning("No table found on openseries page")
        return []

    # Map column headers to indices
    header_row = table.find("tr")
    if not header_row:
        return []

    headers = [th.get_text(strip=True).upper() for th in header_row.find_all("th")]
    logger.info("OpenSeries table headers: %s", headers)

    # Find column indices
    col = {}
    for i, h in enumerate(headers):
        if "CAMPE" in h:
            col["champion"] = i
        elif h == "PICKS" or h == "PICK":
            col["picks"] = i
        elif "PICK RATE" in h or "PICKRATE" in h:
            col["pick_rate"] = i
        elif h == "BANS" or h == "BAN":
            col["bans"] = i
        elif "BAN RATE" in h or "BANRATE" in h:
            col["ban_rate"] = i
        elif "WIN RATE" in h or "WINRATE" in h:
            col["win_rate"] = i
        elif h == "KDA":
            col["kda"] = i
        elif "K/D/A" in h or "MÉDIOS" in h or "MEDIOS" in h:
            col["kda_breakdown"] = i
        elif "GOLD" in h:
            col["avg_gold"] = i

    logger.info("Column mapping: %s", col)

    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr")

    champions: list[OpenSeriesChampion] = []
    for row in rows:
        cells = row.find_all("td")
        if not cells or len(cells) < 5:
            continue

        def cell_val(key: str) -> str:
            idx = col.get(key)
            if idx is None or idx >= len(cells):
                return ""
            # Prefer data-value attribute for numeric fields
            dv = cells[idx].get("data-value", "")
            if dv:
                return dv
            return cells[idx].get_text(separator=" ", strip=True)

        # Champion name: strip rank number prefix if present
        champion_raw = cell_val("champion")
        # Remove leading digits/rank like "1 Renekton" or just "Renekton"
        champion = re.sub(r"^\d+\s*", "", champion_raw).strip()
        if not champion:
            continue

        pick_rate_raw = cell_val("pick_rate")
        ban_rate_raw = cell_val("ban_rate")
        win_rate_raw = cell_val("win_rate")

        # data-value may already be a decimal (e.g. "0.515") or percent ("51.5")
        def to_rate(raw: str) -> float:
            val = _parse_float(raw)
            # If value > 1, it's a percentage — normalize
            if val > 1.0:
                val /= 100.0
            return round(val, 4)

        kda_text = cell_val("kda_breakdown")
        avg_k, avg_d, avg_a = _parse_kda_breakdown(kda_text)

        # Try to extract W/L from win_rate cell text (may contain "20W 15L")
        win_rate_cell_idx = col.get("win_rate")
        wins, losses = 0, 0
        if win_rate_cell_idx is not None and win_rate_cell_idx < len(cells):
            full_text = cells[win_rate_cell_idx].get_text(separator=" ", strip=True)
            wins, losses = _parse_win_loss(full_text)

        gold_raw = cell_val("avg_gold")
        avg_gold = _parse_float(gold_raw)
        # If stored as whole number like 11842, leave as-is
        # If stored as 11.842 (thousands), that's the display format

        champ: OpenSeriesChampion = {
            "champion": champion,
            "picks": _parse_int(cell_val("picks")),
            "pick_rate": to_rate(pick_rate_raw),
            "bans": _parse_int(cell_val("bans")),
            "ban_rate": to_rate(ban_rate_raw),
            "win_rate": to_rate(win_rate_raw),
            "wins": wins,
            "losses": losses,
            "kda": _parse_float(cell_val("kda")),
            "avg_kills": avg_k,
            "avg_deaths": avg_d,
            "avg_assists": avg_a,
            "avg_gold": avg_gold,
        }
        champions.append(champ)

    logger.info("Parsed %d champions from OpenSeries", len(champions))
    return champions


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def read_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_cache(champions: list[OpenSeriesChampion]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": OPENSERIES_URL,
        "champions": champions,
    }
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def cache_age_seconds(cache: dict) -> float:
    fetched_at = cache.get("fetched_at", "")
    if not fetched_at:
        return float("inf")
    try:
        dt = datetime.fromisoformat(fetched_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return float("inf")


def is_cache_fresh(cache: dict) -> bool:
    return cache_age_seconds(cache) < CACHE_TTL_SECONDS


def get_openseries_data(force_refresh: bool = False) -> list[OpenSeriesChampion]:
    """Return Open Series champion stats, using cache when fresh."""
    if not force_refresh:
        cache = read_cache()
        if cache and is_cache_fresh(cache):
            return cache["champions"]

    champions = scrape_openseries()
    if champions:
        write_cache(champions)
    return champions


def get_openseries_map(force_refresh: bool = False) -> dict[str, OpenSeriesChampion]:
    """Return a dict keyed by lowercase champion name for cross-reference lookups."""
    data = get_openseries_data(force_refresh=force_refresh)
    return {c["champion"].lower(): c for c in data}
