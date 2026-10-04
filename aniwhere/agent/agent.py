from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


class AniWhereAgent:
    def __init__(self, store, embeddings, anime_list: list[dict]) -> None:
        self.store = store
        self.embeddings = embeddings
        self.anime_by_id = {anime["id"]: anime for anime in anime_list}

    def analyze(self, query: str) -> dict[str, Any]:
        intent, tool = self._intent(query)
        clues = self._clues(query)
        query_vector = self.embeddings.encode([query])[0]
        allowed_types = {
            "anime": {"character", "event", "anime_summary", "terminology"},
            "episode": {"event", "character", "anime_summary"},
            "recap": {"event", "character", "anime_summary", "terminology"},
            "streaming": {"streaming"},
        }[intent]
        raw = [
            item for item in self.store.query("semantic", query_vector, limit=40)
            if item["metadata"]["chunk_type"] in allowed_types
        ][:10]
        mentioned_anime = self._mentioned_anime(query)
        if mentioned_anime:
            scoped = [item for item in raw if item["metadata"]["anime_id"] == mentioned_anime]
            # Query the named title directly if global top-40 did not retain enough of it.
            if len(scoped) < 3:
                scoped = [
                    item for item in self.store.query(
                        "semantic", query_vector, limit=30, filters={"anime_id": mentioned_anime}
                    ) if item["metadata"]["chunk_type"] in allowed_types
                ][:10]
            raw = scoped
        ranked = self._rank_titles(raw)
        top = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None
        ambiguous = bool(top and runner_up and top["score"] - runner_up["score"] < 0.055)
        confidence = "높음" if top and top["score"] >= .30 and not ambiguous else "보통" if top and top["score"] >= .14 else "낮음"

        question = None
        if ambiguous or confidence == "낮음":
            question = self._clarifying_question(query, ranked)

        episode = None
        if intent == "episode" and top:
            matching_events = [r for r in raw if r["metadata"]["anime_id"] == top["anime_id"] and r["metadata"]["chunk_type"] == "event"]
            if matching_events:
                best_event = max(matching_events, key=lambda item: item["score"])
                if best_event["score"] >= .32:
                    episode = {key: best_event["metadata"][key] for key in ("season", "episode", "global_episode")}
                    episode["title"] = self._episode_title(best_event["id"])

        if intent == "episode" and not episode:
            question = "그 장면에서 누가 무엇을 했는지, 또는 직전·직후에 일어난 일을 하나만 더 알려주세요."

        answer = self._answer(intent, top, episode, confidence, question)
        return {
            "query": query, "intent": intent, "tool": tool, "clues": clues,
            "answer": answer, "confidence": confidence, "needs_clarification": bool(question),
            "clarifying_question": question, "top_candidate": top, "candidates": ranked[:3],
            "episode": episode, "evidence": raw[:6], "model": self.embeddings.name,
            "pipeline": ["의도·단서 분석", tool, "Vector DB 유사도 검색", "후보 점수 집계", "근거 기반 응답"],
        }

    def recap(self, anime_id: str, until_episode: int) -> dict[str, Any]:
        anime = self.anime_by_id[anime_id]
        query = f"{anime['title']} 줄거리 인물 세계관 주요 사건"
        results = self.store.query(
            "semantic", self.embeddings.encode([query])[0], limit=40,
            filters={"anime_id": anime_id, "spoiler_until": {"lte": until_episode}},
        )
        safe_events = [event for event in anime["events"] if event["global_episode"] <= until_episode]
        people = [character["name"] for character in anime["characters"][:4]]
        recap_text = " ".join(event["text"] for event in safe_events)
        return {
            "anime": self._card(anime_id), "until_episode": until_episode,
            "summary": recap_text or anime["summary"], "characters": people,
            "world": anime["world"], "events": safe_events, "evidence": results[:8],
            "excluded_count": len([event for event in anime["events"] if event["global_episode"] > until_episode]),
            "safety_rule": f"global_episode ≤ {until_episode} 메타데이터 필터 적용",
        }

    def streaming(self, anime_id: str) -> dict:
        anime = self.anime_by_id[anime_id]
        return {"anime": self._card(anime_id), **anime["streaming"]}

    def compare(self, query: str) -> dict:
        vector = self.embeddings.encode([query])[0]
        whole = self.store.query("whole", vector, limit=3)
        semantic = self.store.query("semantic", vector, limit=5)
        return {
            "query": query, "whole": whole, "semantic": semantic,
            "insight": "의미 기반 청킹은 일치한 캐릭터·사건을 독립 근거로 반환해, 긴 문서보다 구체적인 설명과 회차 메타데이터를 제공합니다.",
        }

    def _rank_titles(self, results: list[dict]) -> list[dict]:
        grouped: dict[str, dict] = defaultdict(lambda: {"scores": [], "evidence": []})
        weights = {"character": 1.15, "event": 1.15, "anime_summary": .85, "terminology": .8, "streaming": .6}
        for result in results:
            group = grouped[result["metadata"]["anime_id"]]
            weighted = result["score"] * weights.get(result["metadata"]["chunk_type"], 1)
            group["scores"].append(weighted)
            group["evidence"].append(result)
        ranked = []
        for anime_id, group in grouped.items():
            scores = sorted(group["scores"], reverse=True)
            score = scores[0] + sum(scores[1:3]) * .18
            anime = self.anime_by_id[anime_id]
            best = max(group["evidence"], key=lambda item: item["score"])
            ranked.append({
                **self._card(anime_id), "anime_id": anime_id, "score": round(min(score, .99), 4),
                "match_type": best["metadata"]["chunk_type"],
                "character_name": best["metadata"].get("character_name"),
                "reason": best["text"],
            })
        return sorted(ranked, key=lambda item: item["score"], reverse=True)

    def _mentioned_anime(self, query: str) -> str | None:
        normalized = re.sub(r"[^0-9a-z가-힣]", "", query.casefold())
        aliases = {
            "귀칼": "demon-slayer", "나히아": "my-hero-academia",
            "히로아카": "my-hero-academia", "진격거": "attack-on-titan",
        }
        for alias, anime_id in aliases.items():
            if alias in normalized:
                return anime_id
        matches = []
        for anime_id, anime in self.anime_by_id.items():
            for title in (anime.get("title", ""), anime.get("title_en", "")):
                compact = re.sub(r"[^0-9a-z가-힣]", "", title.casefold())
                if len(compact) >= 3 and compact in normalized:
                    matches.append((len(compact), anime_id))
        return max(matches)[1] if matches else None

    def _card(self, anime_id: str) -> dict:
        anime = self.anime_by_id[anime_id]
        return {**{key: anime[key] for key in ("id", "title", "title_en", "accent", "initial", "genres", "summary")},
                "poster_url": anime.get("poster_url"), "data_tier": anime.get("data_tier", "detailed")}

    def _intent(self, query: str) -> tuple[str, str]:
        if any(word in query for word in ("어디서", "ott", "볼 수", "넷플릭스", "라프텔")):
            return "streaming", "get_streaming_info"
        if any(word in query for word in ("복습", "요약", "내용", "정리")):
            return "recap", "get_spoiler_safe_recap"
        if any(word in query for word in ("몇 화", "몇화", "장면까지", "어디까지", "싸우", "마지막")):
            return "episode", "search_episode"
        return "anime", "search_anime"

    @staticmethod
    def _clues(query: str) -> list[str]:
        vocabulary = ["노란 머리", "금발", "번개", "전기", "겁이 많", "바보", "검", "학생", "히어로",
                      "손가락", "카메라", "올마이트", "올 포 원", "거인", "벽", "목도리", "여동생", "대나무"]
        clues = [word for word in vocabulary if word.replace(" ", "") in query.replace(" ", "")]
        tokens = re.findall(r"[가-힣A-Za-z]{2,}", query)
        return (clues + [token for token in tokens if token not in clues])[:7]

    @staticmethod
    def _clarifying_question(query: str, ranked: list[dict]) -> str:
        if ("전기" in query or "번개" in query) and len(ranked) > 1:
            return "검을 사용하다 잠들면 강해졌나요, 아니면 히어로 학교 학생이고 능력을 쓰면 멍해졌나요?"
        names = " 또는 ".join(item["title"] for item in ranked[:2])
        return f"{names or '작품'} 중 어느 쪽에 가까운가요? 기억나는 복장이나 함께 나온 인물을 알려주세요."

    def _episode_title(self, chunk_id: str) -> str:
        anime_id, _, episode = chunk_id.split(":")
        for event in self.anime_by_id[anime_id]["events"]:
            if str(event["global_episode"]) == episode:
                return event["title"]
        return ""

    @staticmethod
    def _answer(intent: str, top: dict | None, episode: dict | None, confidence: str, question: str | None) -> str:
        if not top:
            return "현재 데이터에서 충분한 근거를 찾지 못했어요. 다른 장면이나 인물 특징을 알려주세요."
        if question and confidence == "낮음":
            return f"가장 가까운 후보는 {top['title']}이지만 아직 단정하기 어려워요."
        character = f"의 {top['character_name']}" if top.get("character_name") else ""
        if intent == "episode" and episode:
            return f"마지막으로 본 지점은 {top['title']} 시즌 {episode['season']} {episode['episode']}화로 추정돼요."
        if intent == "episode":
            return f"작품은 {top['title']}로 보이지만, 현재 근거만으로는 정확한 회차를 정하기 어려워요."
        return f"가장 유력한 작품은 {top['title']}{character}예요. 검색된 근거만 바탕으로 판단했어요."
