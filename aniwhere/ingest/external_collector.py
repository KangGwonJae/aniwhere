from __future__ import annotations

import html
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

from aniwhere.ingest.catalog import ROOT
from aniwhere.settings import load_env

try:
    import certifi
except ImportError:  # pragma: no cover - system trust store is the fallback
    certifi = None

ANILIST_URL = "https://graphql.anilist.co"
TMDB_URL = "https://api.themoviedb.org/3"
OUTPUT_PATH = ROOT / "data" / "raw" / "anime.json"
REPORT_PATH = ROOT / "data" / "raw" / "collection_report.json"

ANILIST_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, format_in: [TV, TV_SHORT, ONA], sort: POPULARITY_DESC, isAdult: false) {
      id idMal format status episodes seasonYear
      title { romaji english native }
      synonyms description genres
      coverImage { extraLarge large color }
      characters(perPage: 8, sort: [ROLE, RELEVANCE, ID]) {
        edges { role node { id name { full native alternative } description image { large } } }
      }
    }
  }
}
"""


def request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
                 payload: dict | None = None, timeout: int = 30) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("User-Agent", "AniWhere-Educational-Demo/1.0")
    request.add_header("Accept", "application/json")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def strip_markup(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


class ExternalCollector:
    def __init__(self) -> None:
        load_env(ROOT / ".env")
        self.tmdb_token = os.getenv("TMDB_READ_ACCESS_TOKEN", "").strip()
        if not self.tmdb_token:
            raise RuntimeError(".env에 TMDB_READ_ACCESS_TOKEN이 없습니다.")
        self.headers = {"Authorization": f"Bearer {self.tmdb_token}"}
        self.report: dict[str, Any] = {"collected": [], "skipped": [], "errors": []}
        self.seen_tmdb_ids: set[int] = set()

    def collect(self, target: int = 20, page_size: int = 30) -> list[dict]:
        anilist = request_json(
            ANILIST_URL, method="POST",
            payload={"query": ANILIST_QUERY, "variables": {"page": 1, "perPage": page_size}},
        )["data"]["Page"]["media"]
        imported = []
        for media in anilist:
            try:
                normalized = self._normalize(media)
                if normalized:
                    tmdb_id = normalized["external_ids"]["tmdb"]
                    if tmdb_id in self.seen_tmdb_ids:
                        self.report["skipped"].append({"title": self._preferred_title(media), "reason": "duplicate TMDB series"})
                        continue
                    self.seen_tmdb_ids.add(tmdb_id)
                    imported.append(normalized)
                    self.report["collected"].append({
                        "title": normalized["title"], "anilist_id": media["id"],
                        "tmdb_id": normalized["external_ids"].get("tmdb"),
                        "episodes": len(normalized["events"]),
                    })
                    print(f"[{len(imported):02}/{target}] {normalized['title']} · characters {len(normalized['characters'])} · episodes {len(normalized['events'])}")
                if len(imported) >= target:
                    break
                time.sleep(.08)
            except (urllib.error.URLError, KeyError, ValueError) as error:
                title = self._preferred_title(media)
                self.report["errors"].append({"title": title, "error": type(error).__name__})
                print(f"[skip] {title}: {type(error).__name__}")

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(imported, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report["summary"] = {"requested": target, "collected": len(imported), "failed": len(self.report["errors"])}
        REPORT_PATH.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
        return imported

    def _normalize(self, media: dict) -> dict | None:
        preferred = self._preferred_title(media)
        tmdb = self._find_tmdb(media)
        if not tmdb:
            self.report["skipped"].append({"title": preferred, "reason": "TMDB match not found"})
            return None

        tmdb_id = tmdb["id"]
        detail = self._tmdb(f"/tv/{tmdb_id}", language="ko-KR")
        if not detail.get("overview"):
            english_detail = self._tmdb(f"/tv/{tmdb_id}", language="en-US")
        else:
            english_detail = detail

        title = detail.get("name") or preferred
        summary = detail.get("overview") or strip_markup(media.get("description")) or english_detail.get("overview") or "줄거리 정보가 아직 없습니다."
        season = self._first_regular_season(detail)
        events = self._episodes(tmdb_id, season) if season is not None else []
        providers = self._providers(tmdb_id)
        characters = self._characters(media)
        accent = media.get("coverImage", {}).get("color") or ["#f06b4f", "#ed9b40", "#d85b57"][media["id"] % 3]

        return {
            "id": f"anilist-{media['id']}",
            "title": title,
            "title_en": media["title"].get("english") or media["title"].get("romaji") or title,
            "accent": accent,
            "initial": title[:1],
            "genres": (media.get("genres") or [])[:4],
            "summary": summary,
            "world": summary,
            "characters": characters,
            "events": events,
            "terms": [],
            "streaming": {
                "providers": providers,
                "checked_at": time.strftime("%Y-%m-%d"),
                "note": "TMDB/JustWatch 제공 정보입니다. 실제 편성은 각 서비스에서 확인하세요.",
            },
            "external_ids": {"anilist": media["id"], "mal": media.get("idMal"), "tmdb": tmdb_id},
            "poster_url": self._poster_url(detail, media),
            "data_tier": "basic",
            "source": "AniList + TMDB",
        }

    def _find_tmdb(self, media: dict) -> dict | None:
        candidates = [media["title"].get("english"), media["title"].get("romaji"), *(media.get("synonyms") or [])[:3]]
        candidates = [title for title in candidates if title]
        scored: list[tuple[float, dict]] = []
        for title in candidates:
            result = self._tmdb("/search/tv", language="en-US", query=title, include_adult="false")
            for item in result.get("results", [])[:8]:
                if "JP" not in item.get("origin_country", []):
                    continue
                names = [item.get("name", ""), item.get("original_name", "")]
                similarity = max(
                    self._title_similarity(source, found)
                    for source in candidates for found in names if found
                )
                scored.append((similarity, item))
        if not scored:
            return None
        similarity, best = max(scored, key=lambda pair: (pair[0], pair[1].get("popularity", 0)))
        if similarity < .58:
            self.report["skipped"].append({
                "title": self._preferred_title(media), "reason": "low TMDB title similarity",
                "best_match": best.get("name"), "similarity": round(similarity, 3),
            })
            return None
        return best

    @staticmethod
    def _title_similarity(left: str, right: str) -> float:
        normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
        a, b = normalize(left), normalize(right)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return min(len(a), len(b)) / max(len(a), len(b)) + .2
        return SequenceMatcher(None, a, b).ratio()

    def _episodes(self, tmdb_id: int, season_number: int) -> list[dict]:
        data = self._tmdb(f"/tv/{tmdb_id}/season/{season_number}", language="ko-KR")
        if not any(item.get("overview") for item in data.get("episodes", [])):
            data = self._tmdb(f"/tv/{tmdb_id}/season/{season_number}", language="en-US")
        events = []
        for episode in data.get("episodes", [])[:16]:
            overview = episode.get("overview", "").strip()
            if not overview:
                continue
            number = episode.get("episode_number", 0)
            events.append({
                "season": season_number, "episode": number, "global_episode": number,
                "title": episode.get("name") or f"{number}화", "text": overview,
                "air_date": episode.get("air_date"), "source": "TMDB",
            })
        return events

    def _providers(self, tmdb_id: int) -> list[str]:
        data = self._tmdb(f"/tv/{tmdb_id}/watch/providers")
        korea = data.get("results", {}).get("KR", {})
        items = [*korea.get("flatrate", []), *korea.get("free", []), *korea.get("ads", [])]
        return list(dict.fromkeys(item["provider_name"] for item in items))

    @staticmethod
    def _characters(media: dict) -> list[dict]:
        characters = []
        for edge in media.get("characters", {}).get("edges", []):
            node = edge["node"]
            name = node["name"].get("full") or node["name"].get("native")
            description = strip_markup(node.get("description"))
            if not name:
                continue
            characters.append({
                "name": name, "aliases": (node["name"].get("alternative") or [])[:4],
                "text": description or f"{edge.get('role', '주요')} 캐릭터 {name}.",
                "traits": [edge.get("role", "주요 캐릭터")],
                "image_url": (node.get("image") or {}).get("large"),
            })
        return characters

    @staticmethod
    def _preferred_title(media: dict) -> str:
        title = media["title"]
        return title.get("english") or title.get("romaji") or title.get("native")

    @staticmethod
    def _first_regular_season(detail: dict) -> int | None:
        seasons = [item["season_number"] for item in detail.get("seasons", []) if item.get("season_number", 0) > 0]
        return min(seasons) if seasons else None

    @staticmethod
    def _poster_url(detail: dict, media: dict) -> str | None:
        if detail.get("poster_path"):
            return f"https://image.tmdb.org/t/p/w500{detail['poster_path']}"
        return (media.get("coverImage") or {}).get("extraLarge")

    def _tmdb(self, path: str, **params: str) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{TMDB_URL}{path}{'?' + query if query else ''}"
        return request_json(url, headers=self.headers)
