from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "data" / "curated" / "anime.json"
IMPORTED_PATH = ROOT / "data" / "curated" / "demo_catalog.json"


def load_anime() -> list[dict]:
    curated = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if not IMPORTED_PATH.exists():
        return curated
    imported = json.loads(IMPORTED_PATH.read_text(encoding="utf-8"))
    imported_by_name = {
        value.casefold(): anime
        for anime in imported
        for value in (anime.get("title", ""), anime.get("title_en", ""))
        if value
    }
    # Keep verified text, but enrich curated records with safe visual/external fields.
    for anime in curated:
        match = imported_by_name.get(anime["title"].casefold()) or imported_by_name.get(anime.get("title_en", "").casefold())
        if match:
            anime["poster_url"] = match.get("poster_url")
            anime["external_ids"] = match.get("external_ids", {})
    curated_names = {
        value.casefold()
        for anime in curated
        for value in (anime["title"], anime.get("title_en", ""))
        if value
    }
    # Hand-verified records win over automatically collected basic records.
    unique_imported = [
        anime for anime in imported
        if anime["title"].casefold() not in curated_names
        and anime.get("title_en", "").casefold() not in curated_names
    ]
    return curated + unique_imported


def anime_catalog() -> list[dict]:
    return [
        {**{key: anime[key] for key in ("id", "title", "title_en", "accent", "initial", "genres", "summary")},
         "poster_url": anime.get("poster_url"), "data_tier": anime.get("data_tier", "detailed")}
        for anime in load_anime()
    ]
