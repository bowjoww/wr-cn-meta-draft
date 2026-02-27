from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.scoring import priority_score

app = FastAPI(title="WR CN Meta Viewer")

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_cn_meta.json"
STATIC_INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"

Role = Literal["top", "jungle", "mid", "adc", "support"]
Tier = Literal["diamond", "master", "challenger"]


def _load_meta_data() -> list[dict]:
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_INDEX_PATH)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/meta")
def meta(role: Role, tier: Tier) -> dict[str, list[dict]]:
    rows = _load_meta_data()

    filtered = [row for row in rows if row["role"] == role and row["tier"] == tier]
    if not filtered:
        raise HTTPException(status_code=404, detail="No meta data found for requested role/tier")

    for row in filtered:
        row["priority_score"] = priority_score(
            winrate=row["winrate"],
            pickrate=row["pickrate"],
            banrate=row["banrate"],
        )

    ordered = sorted(filtered, key=lambda item: item["priority_score"], reverse=True)
    return {"items": ordered}
