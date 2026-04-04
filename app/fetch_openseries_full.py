"""Scrapers for openseries.com.br — teams, rankings, standings, overview."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "openseries_full_cache.json"
CACHE_TTL_SECONDS = 3600 * 6  # 6 hours

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


# ---------------------------------------------------------------------------
# Teams scraper — https://openseries.com.br/equipes/
# ---------------------------------------------------------------------------

def scrape_teams() -> list[dict]:
    """Scrape team rosters and group assignments from /equipes/."""
    resp = requests.get("https://openseries.com.br/equipes/", headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Build group map from .os-grupo-card elements
    group_map: dict[str, str] = {}  # team_name_lower -> group_name
    for grupo in soup.select(".os-grupo-card"):
        group_name_el = grupo.select_one(".os-grupo-nome")
        group_name = group_name_el.get_text(strip=True) if group_name_el else ""
        for col in grupo.select(".os-col-team"):
            team_name = col.get_text(strip=True)
            if team_name:
                group_map[team_name.lower()] = group_name

    teams: list[dict] = []
    for card in soup.select(".os-status-card"):
        name_el = card.select_one(".os-status-nome")
        name = name_el.get_text(strip=True) if name_el else ""
        if not name:
            continue

        players: list[dict] = []
        for li in card.select("ul > li"):
            ign_raw = li.get_text(strip=True)
            if "#" in ign_raw:
                parts = ign_raw.split("#", 1)
                players.append({"ign": parts[0].strip(), "tag": parts[1].strip()})
            elif ign_raw:
                players.append({"ign": ign_raw, "tag": ""})

        teams.append({
            "name": name,
            "group": group_map.get(name.lower(), ""),
            "players": players,
        })

    logger.info("Scraped %d teams from OpenSeries", len(teams))
    return teams


# ---------------------------------------------------------------------------
# Rankings scraper — https://openseries.com.br/rankings/
# ---------------------------------------------------------------------------

def _parse_float(text: str) -> float:
    cleaned = text.strip().replace("%", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int(text: str) -> int:
    try:
        return int(str(text).strip().replace(",", "").replace(".", ""))
    except ValueError:
        return 0


def _table_to_dicts(table) -> list[dict]:
    """Convert a BS4 table element to a list of dicts using th headers."""
    headers = [th.get_text(strip=True) for th in table.select("thead th, tr:first-child th")]
    if not headers:
        # Try first row as header
        first_row = table.find("tr")
        if first_row:
            headers = [td.get_text(strip=True) for td in first_row.find_all(["th", "td"])]

    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row: dict = {}
        for i, cell in enumerate(cells):
            key = headers[i] if i < len(headers) else str(i)
            # Prefer data-value attribute for numeric sortable cells
            val = cell.get("data-value") or cell.get_text(strip=True)
            row[key] = val
        rows.append(row)
    return rows


def scrape_rankings() -> dict:
    """Scrape player and team rankings from /rankings/."""
    resp = requests.get("https://openseries.com.br/rankings/", headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    player_table = None
    players_card = soup.select_one(".os-players-card")
    if players_card:
        player_table = players_card.find("table")

    team_table = None
    teams_card = soup.select_one(".os-teams-card")
    if teams_card:
        team_table = teams_card.find("table")

    player_rankings = _table_to_dicts(player_table) if player_table else []
    team_rankings = _table_to_dicts(team_table) if team_table else []

    # Include hidden rows (os-hidden-row) — they are already included by _table_to_dicts
    # since we select all tbody tr regardless of class.

    logger.info(
        "Scraped %d player rankings, %d team rankings",
        len(player_rankings), len(team_rankings)
    )
    return {"player_rankings": player_rankings, "team_rankings": team_rankings}


# ---------------------------------------------------------------------------
# Standings scraper — https://openseries.com.br/tabelas/
# ---------------------------------------------------------------------------

def _extract_nonce(html: str) -> str | None:
    """Extract openseriesData.nonce from inline JS."""
    m = re.search(r'openseriesData\s*=\s*\{[^}]*"nonce"\s*:\s*"([^"]+)"', html)
    if m:
        return m.group(1)
    m = re.search(r"openseriesData\.nonce\s*=\s*['\"]([^'\"]+)['\"]", html)
    if m:
        return m.group(1)
    return None


def _standings_from_wp_api(base_url: str, nonce: str) -> list[dict] | None:
    """Try fetching standings data from WordPress REST API."""
    groups = []
    for group_letter in ["A", "B", "C", "D"]:
        try:
            url = f"{base_url}/wp-json/openseries/v1/agenda"
            resp = requests.get(
                url,
                params={"group": group_letter},
                headers={**_HEADERS, "X-WP-Nonce": nonce},
                timeout=15,
            )
            if resp.status_code == 404:
                break
            if not resp.ok:
                continue
            data = resp.json()
            if not data:
                break

            # Build matches and standings from the API response
            matches = []
            wins: dict[str, int] = {}
            losses: dict[str, int] = {}

            items = data if isinstance(data, list) else data.get("matches", [])
            for item in items:
                home = item.get("home") or item.get("team_a") or ""
                away = item.get("away") or item.get("team_b") or ""
                home_score = item.get("home_score", item.get("score_a", 0))
                away_score = item.get("away_score", item.get("score_b", 0))
                matches.append({
                    "home": home, "away": away,
                    "home_score": home_score, "away_score": away_score,
                })
                # Only count completed matches
                if home_score is not None and away_score is not None:
                    try:
                        hs, as_ = int(home_score), int(away_score)
                        if hs > as_:
                            wins[home] = wins.get(home, 0) + 1
                            losses[away] = losses.get(away, 0) + 1
                        elif as_ > hs:
                            wins[away] = wins.get(away, 0) + 1
                            losses[home] = losses.get(home, 0) + 1
                    except (ValueError, TypeError):
                        pass

            all_teams = set(wins) | set(losses)
            for m in matches:
                all_teams.add(m["home"])
                all_teams.add(m["away"])
            all_teams.discard("")

            standings = sorted(
                [{"team": t, "wins": wins.get(t, 0), "losses": losses.get(t, 0)} for t in all_teams],
                key=lambda x: (-x["wins"], x["losses"]),
            )
            groups.append({"name": group_letter, "matches": matches, "standings": standings})
        except Exception as exc:
            logger.warning("WP API error for group %s: %s", group_letter, exc)
            continue

    return groups if groups else None


def scrape_standings() -> dict:
    """Scrape standings from /tabelas/. Tries WP REST API first."""
    resp = requests.get("https://openseries.com.br/tabelas/", headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text

    nonce = _extract_nonce(html)
    base_url = "https://openseries.com.br"

    if nonce:
        groups = _standings_from_wp_api(base_url, nonce)
        if groups:
            logger.info("Standings via WP API: %d groups", len(groups))
            return {"groups": groups}

    # Fallback: parse static HTML tables if rendered
    soup = BeautifulSoup(html, "html.parser")
    groups = []
    for table in soup.select("table"):
        rows = _table_to_dicts(table)
        if rows:
            groups.append({"name": "", "matches": [], "standings": rows})

    logger.info("Standings via static HTML: %d tables found", len(groups))
    return {"groups": groups}


# ---------------------------------------------------------------------------
# Overview scraper — https://openseries.com.br/estatisticas/
# ---------------------------------------------------------------------------

def scrape_overview(teams_data: list[dict] | None = None, rankings_data: dict | None = None) -> dict:
    """Scrape or compute overview stats."""
    try:
        resp = requests.get(
            "https://openseries.com.br/estatisticas/",
            headers=_HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Try to parse rendered stats cards
        blue_wr = red_wr = 0.0
        total_matches = 0
        unique_champions = 0
        avg_duration = ""

        for card in soup.select(".os-stat-card, .stat-card, [class*='stat']"):
            text = card.get_text(" ", strip=True).lower()
            val_el = card.select_one("[data-value], .stat-value, .os-stat-value")
            val_str = (val_el.get("data-value") or val_el.get_text(strip=True)) if val_el else ""

            if "azul" in text or "blue" in text:
                blue_wr = _parse_float(val_str) / 100 if _parse_float(val_str) > 1 else _parse_float(val_str)
            elif "vermelho" in text or "red" in text:
                red_wr = _parse_float(val_str) / 100 if _parse_float(val_str) > 1 else _parse_float(val_str)
            elif "partidas" in text or "matches" in text:
                total_matches = _parse_int(val_str)
            elif "campe" in text:
                unique_champions = _parse_int(val_str)
            elif "dura" in text or "duration" in text:
                avg_duration = val_str

        if blue_wr or red_wr or total_matches:
            return {
                "blue_wr": blue_wr,
                "red_wr": red_wr,
                "total_matches": total_matches,
                "unique_champions": unique_champions,
                "avg_duration": avg_duration,
            }
    except Exception as exc:
        logger.warning("Overview scrape failed: %s — computing from cached data", exc)

    # Compute from other scraped data if available
    return _compute_overview(teams_data, rankings_data)


def _compute_overview(teams_data: list[dict] | None, rankings_data: dict | None) -> dict:
    """Derive overview stats from teams/rankings data."""
    unique_champions = 0
    total_matches = 0

    if rankings_data:
        player_rows = rankings_data.get("player_rankings", [])
        champs = set()
        for row in player_rows:
            champ = row.get("Champion") or row.get("Campeão") or row.get("champion") or ""
            if champ:
                champs.add(champ)
        unique_champions = len(champs)

        for row in (rankings_data.get("team_rankings") or []):
            matches_val = row.get("Partidas") or row.get("matches") or "0"
            total_matches = max(total_matches, _parse_int(str(matches_val)))

    return {
        "blue_wr": 0.0,
        "red_wr": 0.0,
        "total_matches": total_matches,
        "unique_champions": unique_champions,
        "avg_duration": "",
    }


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def read_full_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_age_seconds(cache: dict) -> float:
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


def _is_cache_fresh(cache: dict) -> bool:
    return _cache_age_seconds(cache) < CACHE_TTL_SECONDS


def _write_full_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def get_full_openseries_data(force_refresh: bool = False) -> dict:
    """Return all full OpenSeries data sections, using cache when fresh."""
    if not force_refresh:
        cache = read_full_cache()
        if cache and _is_cache_fresh(cache):
            return {k: cache[k] for k in ("teams", "rankings", "standings", "overview") if k in cache}

    teams = scrape_teams()
    rankings = scrape_rankings()
    standings = scrape_standings()
    overview = scrape_overview(teams_data=teams, rankings_data=rankings)

    data = {
        "teams": teams,
        "rankings": rankings,
        "standings": standings,
        "overview": overview,
    }
    _write_full_cache(data)
    return data
