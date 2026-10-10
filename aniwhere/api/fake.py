"""DB·LLM 없이 API 서버를 띄우기 위한 가짜 서비스. service.py와 같은 함수 이름·인자·응답 형식을 지킵니다.

쓰는 곳: (1) 프론트엔드 개발 — `make api FAKE=1`, (2) tests/test_api.py, (3) 응답 형식의 실행 가능한 예시.
데이터는 frontend/app.js의 mock과 맞춘 나의 히어로 아카데미아 하나와, 기록이 없는 진격의 거인 하나입니다.
기록장은 메모리에 두므로 서버를 다시 켜면 처음 상태로 돌아갑니다.
"""
MODE = "fake"

import datetime as dt

from aniwhere.retrieval.catalog import UnknownSeries

HERO, TITAN = "tmdb:65930", "tmdb:1429"
USER = "local"

SERIES = {
    HERO: {"series_id": HERO, "name": "나의 히어로 아카데미아", "title": "My Hero Academia", "total_episodes": 138,
           "poster_url": None, "genres": ["Action", "Comedy", "School"]},
    TITAN: {"series_id": TITAN, "name": "진격의 거인", "title": "Attack on Titan", "total_episodes": 89,
            "poster_url": None, "genres": ["Action", "Drama", "Mystery"]},
}
SOURCE = {"text": "미도리야는 올마이트에게서 원 포 올을 물려받는다.", "abs_ep": 2,
          "url": "https://bokunoheroacademia.fandom.com/wiki/Episode_2", "license": "CC BY-SA 3.0"}
ASK_SEEN = "어디까지 봤어요? 마지막으로 본 회차를 알려 주세요."
MODES = ("summary", "characters", "last", "ask")

_records: dict[str, dict] = {}


def reset():
    """기록장을 처음 상태로 되돌림 (테스트가 매번 부름)."""
    _records.clear()
    _records[HERO] = {"seen_ep": 49, "rating": None, "updated_at": "2026-10-05T21:00:00+09:00"}


reset()


def _series(series_id):
    info = SERIES.get(series_id)
    if not info:
        raise UnknownSeries(f"모르는 작품입니다: {series_id}")
    return info


def _seen(series_id, seen_ep):
    if seen_ep is None and series_id in _records:
        return _records[series_id]["seen_ep"]
    return seen_ep


TITAN_SOURCE = {"text": "리바이가 입체기동으로 거인을 벤다.", "abs_ep": 1,
                "url": "https://attackontitan.fandom.com/wiki/Episode_1", "license": "CC BY-SA 3.0"}


def find(question: str, history: list[dict] | None = None, *, user_id=USER) -> dict:
    """status는 질문의 낱말로 고름 — 화면 네 갈래를 모두 만들어 볼 수 있게:
    "헷갈" → ambiguous(후보 둘 + follow_up), "없는" → none, "작품" → series, 그 외 → episode."""
    ep1 = {"series_id": TITAN, "title": "진격의 거인", "abs_ep": 1, "label": "1기 1화", "score": 0.91}
    ep2 = {"series_id": TITAN, "title": "진격의 거인", "abs_ep": 2, "label": "1기 2화", "score": 0.90}
    if "헷갈" in question:
        return {"status": "ambiguous", "answer": None, "candidates": [ep1, ep2],
                "follow_up": "거인이 벽을 부순 직후였나요, 아니면 피난 장면이었나요?", "sources": [TITAN_SOURCE]}
    if "없는" in question:
        return {"status": "none", "answer": "말씀하신 장면을 찾지 못했어요. 인물 이름이나 배경을 더 알려 주세요.",
                "candidates": [], "follow_up": None, "sources": []}
    if "작품" in question:
        return {"status": "series", "answer": "진격의 거인 같아요. 어느 회차인지는 장면을 더 알려 주세요.",
                "candidates": [{"series_id": TITAN, "title": "진격의 거인", "score": 0.88}], "follow_up": None,
                "sources": [TITAN_SOURCE]}
    return {"status": "episode", "answer": "진격의 거인 1기 1화 〈2000년 후의 너에게〉 같아요.",
            "candidates": [ep1], "follow_up": None, "sources": [TITAN_SOURCE]}


def where_to_watch(series_id: str) -> dict:
    info = _series(series_id)
    return {"series_id": series_id, "title": info["name"],
            "seasons": [{"name": "시즌 3", "providers": ["Laftel", "Netflix"], "checked_at": "2026-10-05",
                         "link": "https://www.justwatch.com/kr"}],
            "attribution": "시청처 정보: JustWatch (TMDB 제공). 구독형 제공처만 표시합니다."}


def review(series_id: str, seen_ep: int | None = None, mode: str = "summary", question: str | None = None, *,
           user_id=USER) -> dict:
    _series(series_id)
    if mode not in MODES:
        raise ValueError(f"mode는 {list(MODES)} 중 하나여야 합니다: {mode!r}")
    if mode == "ask" and not (question or "").strip():
        raise ValueError("직접 질문 모드에는 질문이 필요합니다")
    seen_ep = _seen(series_id, seen_ep)
    if seen_ep is None:
        return {"answer": None, "seen_ep": None, "sources": [], "follow_up": ASK_SEEN}
    return {"answer": f"{seen_ep}화까지의 요약입니다. 미도리야는 올마이트의 힘을 물려받았어요 [1].",
            "seen_ep": seen_ep, "sources": [SOURCE], "follow_up": None}


def dictionary(series_id: str, seen_ep: int | None = None, *, user_id=USER) -> dict:
    _series(series_id)
    seen_ep = _seen(series_id, seen_ep)
    if seen_ep is None:
        return {"seen_ep": None, "entries": [], "follow_up": ASK_SEEN}
    return {"seen_ep": seen_ep, "follow_up": None, "entries": [
        {"kind": "character", "name": "미도리야 이즈쿠", "text": "올마이트에게 힘을 물려받은 학생.", "first_ep": 1, "url": None},
        {"kind": "character", "name": "올마이트", "text": "평화의 상징이라 불리는 히어로.", "first_ep": 1, "url": None},
        {"kind": "term", "name": "원 포 올", "text": "힘을 축적해 다음 계승자에게 전달하는 개성.", "first_ep": 2, "url": None},
    ]}


def recommend(likes: str, *, user_id=USER) -> dict:
    return {"mood": "반전과 긴장감", "follow_up": None,
            "picks": [{"series_id": TITAN, "title": "진격의 거인", "reason": "매 화 뒤집히는 전개가 비슷해요.",
                       "poster_url": None, "genres": SERIES[TITAN]["genres"]}]}


def save_record(series_id: str, seen_ep: int, rating: float | None = None, *, user_id=USER) -> dict:
    info = _series(series_id)
    if not isinstance(seen_ep, int) or seen_ep < 0 or seen_ep > info["total_episodes"]:
        raise ValueError(f"본 회차는 0부터 {info['total_episodes']}까지의 정수여야 합니다: {seen_ep!r}")
    if rating is not None and not 0.5 <= rating <= 5:
        raise ValueError(f"평점은 0.5부터 5까지입니다: {rating!r}")
    old = _records.get(series_id, {})
    _records[series_id] = {"seen_ep": seen_ep, "rating": rating if rating is not None else old.get("rating"),
                           "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    return get_record(series_id)


def get_record(series_id: str, *, user_id=USER) -> dict | None:
    r = _records.get(series_id)
    if not r:
        return None
    info = SERIES[series_id]
    return {"series_id": series_id, "name": info["name"], "total_episodes": info["total_episodes"], **r}


def list_records(*, user_id=USER) -> list[dict]:
    return [get_record(sid) for sid in _records]


def delete_record(series_id: str, *, user_id=USER) -> bool:
    return _records.pop(series_id, None) is not None


def search_series(query: str | None = None, limit: int = 50) -> list[dict]:
    rows = [{k: v for k, v in s.items() if k in ("series_id", "name", "title", "total_episodes")} for s in SERIES.values()]
    if query:
        q = query.lower()
        rows = [r for r in rows if q in r["name"].lower() or q in r["title"].lower()]
    return rows[:limit]


def series(series_id: str) -> dict | None:
    return SERIES.get(series_id)
