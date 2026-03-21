"""OCR service using OpenAI Vision API to extract match data from Wild Rift screenshots."""

from __future__ import annotations

import base64
import difflib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """You are analyzing Wild Rift (League of Legends: Wild Rift) post-game screenshots.
This screenshot is from SPECTATOR PERSPECTIVE, so it does NOT indicate which team belongs to the user.
{our_side_instruction}

Extract the match data and return ONLY valid JSON with this structure:

{{
  "side": "blue" or "red" (which side OUR team is on),
  "result": "win" or "loss" (result from OUR team's perspective),
  "duration": "MM:SS" (game duration — look for it near "Wild Rift" text in the top-left corner, below the game mode name like "ALTERNADA PARA TORNEIOS" or "ESCOLHAS ÀS CEGAS"),
  "players": [
    {{
      "role": "top"|"jungle"|"mid"|"bot"|"support",
      "team": "ours"|"theirs",
      "champion": "Champion Name",
      "player_name": "player nickname or null",
      "kills": 0,
      "deaths": 0,
      "assists": 0,
      "kp_percent": null,
      "damage_dealt": null,
      "damage_taken": null,
      "gold_earned": null,
      "is_mvp": false,
      "is_svp": false
    }}
  ]
}}

Rules:
- The BLUE team is always on the LEFT side of the scoreboard, RED team on the RIGHT
- Player order top-to-bottom typically follows: Top, Jungle, Mid, Bot, Support
- Extract kills, deaths, assists from the K/D/A columns
- If you see damage stats, include them
- Gold earned: look for a number near each player (often labeled "Patrimônio Líquido", "Ouro Total", or just a plain number like 8945 or 11.7k). This is the total gold earned by that player. Convert "k" values to full numbers (e.g., 11.7k = 11700). Always return as an integer.
- The MVP badge (crown/star icon) appears on the best player of the winning team; set is_mvp=true for that player
- The SVP badge appears on the best player of the losing team; set is_svp=true for that player
- Use English champion names (e.g., "Garen" not "盖伦"). If you cannot identify a champion, use null — NEVER use "Champion Name", "Unknown", or any placeholder text
- Common name mappings: MonkeyKing → Wukong, Xin Zhao (not Zhao Yun), Nunu & Willump → Nunu
- If the screenshot says "VITÓRIA" (victory), the team shown prominently won
- "Equipe Azul" = Blue Team, "Equipe Vermelha" = Red Team
- Return ONLY the JSON, no markdown or extra text
- Extract player nicknames/summoner names shown next to or above each champion portrait. These appear as text like "PlayerName#TAG". Include the full name with tag if visible.
- Game duration (MM:SS format) is in the top-left area of the screen, typically below the game mode name (e.g., "ALTERNADA PARA TORNEIOS", "ESCOLHAS ÀS CEGAS") and near the "Wild Rift" text
- If you cannot determine a field, use null (do NOT guess or use placeholder text)
{champion_list_instruction}
"""


def extract_match_data(
    images: list[dict[str, Any]],
    our_side: str | None = None,
    known_champions: list[str] | None = None,
) -> dict[str, Any]:
    """Extract match data from screenshot images using OpenAI Vision API.

    Args:
        images: List of dicts with 'data' (bytes) and 'content_type' (str).
        our_side: "blue" or "red" - which side the user's team is on.
        known_champions: List of valid champion names for fuzzy matching.

    Returns:
        Parsed match data dict.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable not set")

    if our_side:
        side_instruction = (
            f'The user has indicated that THEIR team is the {our_side.upper()} side '
            f'({"LEFT" if our_side == "blue" else "RIGHT"} side of the scoreboard). '
            f'Players on the {our_side} side should have team="ours", '
            f'players on the other side should have team="theirs". '
            f'Set "side" to "{our_side}".'
        )
    else:
        side_instruction = (
            "The user did NOT specify which team is theirs. "
            "Try to determine from context (victory/defeat banner), "
            "but if unclear, assign the blue (left) team as 'ours'."
        )

    if known_champions:
        champ_list_str = ", ".join(sorted(known_champions))
        champion_list_instruction = (
            f"\nIMPORTANT: Use ONLY champion names from this list (exact spelling): {champ_list_str}"
        )
    else:
        champion_list_instruction = ""

    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        our_side_instruction=side_instruction,
        champion_list_instruction=champion_list_instruction,
    )

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    content: list[dict] = [{"type": "text", "text": prompt}]

    for img in images:
        b64 = base64.b64encode(img["data"]).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['content_type']};base64,{b64}",
                "detail": "high",
            },
        })

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": content}],
        max_tokens=2000,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse OCR response: %s", raw[:500])
        raise RuntimeError(f"Could not parse OCR response as JSON: {exc}") from exc

    # Post-process: fuzzy-match champion names against known list
    if known_champions:
        _fuzzy_fix_champions(data, known_champions)

    return data


def _fuzzy_fix_champions(data: dict[str, Any], known: list[str]) -> None:
    """Fix champion names in OCR output via fuzzy matching against known list."""
    from app.fetch_cn_meta import DISPLAY_NAME_OVERRIDES

    known_lower = {n.lower(): n for n in known}

    def _fix(name: str | None) -> str | None:
        if not name:
            return name
        # Apply display name overrides first (e.g. MonkeyKing -> Wukong)
        name = DISPLAY_NAME_OVERRIDES.get(name, name)
        # Exact match (case-insensitive)
        if name.lower() in known_lower:
            return known_lower[name.lower()]
        # Fuzzy match
        matches = difflib.get_close_matches(name.lower(), known_lower.keys(), n=1, cutoff=0.6)
        if matches:
            corrected = known_lower[matches[0]]
            logger.info("OCR fuzzy-matched '%s' -> '%s'", name, corrected)
            return corrected
        return name

    for p in data.get("players", []):
        p["champion"] = _fix(p.get("champion"))
    for b in data.get("bans", []):
        b["champion"] = _fix(b.get("champion"))
