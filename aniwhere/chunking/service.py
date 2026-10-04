from __future__ import annotations

from typing import Any


def metadata(anime: dict, chunk_type: str, **values: Any) -> dict:
    return {
        "anime_id": anime["id"], "anime_title": anime["title"],
        "chunk_type": chunk_type, "character_name": values.get("character_name"),
        "season": values.get("season"), "episode": values.get("episode"),
        "global_episode": values.get("global_episode"),
        "spoiler_until": values.get("spoiler_until", values.get("global_episode", 0)),
        "source": "manual_verified", "collected_at": "2026-10-01",
    }


def semantic_chunks(anime_list: list[dict]) -> list[dict]:
    chunks: list[dict] = []
    for anime in anime_list:
        chunks.append({
            "id": f"{anime['id']}:summary",
            "text": f"작품 {anime['title']} ({anime['title_en']}). 장르: {', '.join(anime['genres'])}. "
                    f"줄거리: {anime['summary']} 세계관: {anime['world']}",
            "metadata": metadata(anime, "anime_summary"),
        })
        for index, character in enumerate(anime["characters"]):
            chunks.append({
                "id": f"{anime['id']}:character:{index}",
                "text": f"작품 {anime['title']}의 캐릭터 {character['name']}. "
                        f"별칭: {', '.join(character['aliases'])}. {character['text']} "
                        f"기억 단서: {', '.join(character['traits'])}.",
                "metadata": metadata(anime, "character", character_name=character["name"]),
            })
        for event in anime["events"]:
            chunks.append({
                "id": f"{anime['id']}:event:{event['global_episode']}",
                "text": f"작품 {anime['title']} 시즌 {event['season']} {event['episode']}화, "
                        f"제목 {event['title']}. 주요 장면: {event['text']}",
                "metadata": metadata(anime, "event", season=event["season"], episode=event["episode"],
                                     global_episode=event["global_episode"]),
            })
        for index, term in enumerate(anime["terms"]):
            chunks.append({
                "id": f"{anime['id']}:term:{index}",
                "text": f"작품 {anime['title']}의 세계관 용어 {term['name']}. {term['text']}",
                "metadata": metadata(anime, "terminology"),
            })
        stream = anime["streaming"]
        chunks.append({
            "id": f"{anime['id']}:streaming",
            "text": f"작품 {anime['title']} 시청 가능 OTT: {', '.join(stream['providers'])}. "
                    f"확인일 {stream['checked_at']}. {stream['note']}",
            "metadata": metadata(anime, "streaming"),
        })
    return chunks


def document_chunks(anime_list: list[dict]) -> list[dict]:
    """Baseline: one large document per title, used for the comparison screen."""
    chunks = []
    for anime in anime_list:
        character_text = " ".join(f"{c['name']}: {c['text']}" for c in anime["characters"])
        event_text = " ".join(f"{e['season']}기 {e['episode']}화: {e['text']}" for e in anime["events"])
        chunks.append({
            "id": f"{anime['id']}:document",
            "text": f"{anime['title']} {anime['summary']} {anime['world']} {character_text} {event_text}",
            "metadata": metadata(anime, "whole_document"),
        })
    return chunks
