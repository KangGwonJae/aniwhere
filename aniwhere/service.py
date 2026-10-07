"""화면이 부르는 입구. 요청·응답 형식은 docs/meetings/2026-10-07_구현범위-역할분담.md의 "프론트와 백엔드 사이 약속"을 따릅니다.

여기에는 판단 로직을 두지 않습니다. DB 연결과 LLM을 준비해서 agent·retrieval·records를 부르고 결과를 그대로 돌려줍니다.
응답은 모두 JSON으로 바꿀 수 있는 dict·list입니다(날짜는 문자열).

| 기능 | 함수 |
|---|---|
| 01 취향 인터뷰 추천 | recommend(likes) |
| 05·06 기억으로 작품·회차 찾기 | find(question, history) |
| 07 시청처 안내 | where_to_watch(series_id) |
| 08 회차 기준 인물·용어 사전 | dictionary(series_id, seen_ep) |
| 09 맞춤 복습 | review(series_id, seen_ep, mode, question) |
| 13 시청 기록장 | save_record / get_record / list_records / delete_record |
| 11 스포일러 차단 | 위 모든 함수에 적용 (aniwhere/retrieval/search.py) |
"""
from aniwhere import records
from aniwhere.agent import find as _find
from aniwhere.agent import recommend as _recommend
from aniwhere.agent import review as _review
from aniwhere.agent.llm import get_llm
from aniwhere.db import connect
from aniwhere.retrieval import catalog
from aniwhere.retrieval import dictionary as _dictionary

USER = records.LOCAL_USER
_db = None


def db():
    global _db
    if _db is None or _db.closed:
        _db = connect()
    return _db


def _plain(value):
    """날짜·시각을 문자열로 바꿔 JSON으로 보낼 수 있게 함."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value.isoformat() if hasattr(value, "isoformat") else value


def find(question: str, history: list[dict] | None = None, *, user_id=USER) -> dict:
    """→ {status, answer, candidates[{series_id, title, abs_ep?, label?, score?}], follow_up?, sources[]}"""
    return _plain(_find.find(db(), question, history, llm=get_llm(), user_id=user_id))


def where_to_watch(series_id: str) -> dict:
    """→ {series_id, title, seasons[{name, providers[], checked_at, link}], attribution}"""
    info = catalog.series_info(db(), series_id)
    if not info:
        raise ValueError(f"모르는 작품입니다: {series_id}")
    return _plain({"series_id": series_id, "title": info["name"], "seasons": catalog.streaming(db(), series_id),
                   "attribution": "시청처 정보: JustWatch (TMDB 제공). 구독형 제공처만 표시합니다."})


def review(series_id: str, seen_ep: int | None = None, mode: str = "summary", question: str | None = None, *,
           user_id=USER) -> dict:
    """→ {answer, seen_ep, sources[{text, abs_ep, url, license}], follow_up?}. seen_ep가 없으면 기록장에서 읽고,
    기록도 없으면 검색하지 않고 follow_up으로 되묻습니다."""
    return _plain(_review.review(db(), series_id, seen_ep, mode, question, llm=get_llm(), user_id=user_id))


def dictionary(series_id: str, seen_ep: int | None = None, *, user_id=USER) -> dict:
    """→ {seen_ep, entries[{kind, name, text, first_ep, url, ...}], follow_up?}"""
    if seen_ep is None:
        record = records.get(db(), series_id, user_id=user_id)
        seen_ep = record["seen_ep"] if record else None
    if seen_ep is None:
        return {"seen_ep": None, "entries": [], "follow_up": _review.ASK_SEEN}
    return _plain({"seen_ep": seen_ep, "entries": _dictionary.dictionary(db(), series_id, seen_ep=seen_ep),
                   "follow_up": None})


def recommend(likes: str, *, user_id=USER) -> dict:
    """→ {mood, picks[{series_id, title, reason, poster_url, genres}], follow_up?}"""
    return _plain(_recommend.recommend(db(), likes, llm=get_llm(), user_id=user_id))


def save_record(series_id: str, seen_ep: int, rating: float | None = None, *, user_id=USER) -> dict:
    """→ 저장된 기록 {series_id, name, seen_ep, total_episodes, rating, updated_at}"""
    return _plain(records.save(db(), series_id, seen_ep, rating, user_id=user_id))


def get_record(series_id: str, *, user_id=USER) -> dict | None:
    return _plain(records.get(db(), series_id, user_id=user_id))


def list_records(*, user_id=USER) -> list[dict]:
    return _plain(records.list_all(db(), user_id=user_id))


def delete_record(series_id: str, *, user_id=USER) -> bool:
    return records.delete(db(), series_id, user_id=user_id)


def search_series(query: str | None = None, limit: int = 50) -> list[dict]:
    """작품 선택 목록 → [{series_id, name, title, total_episodes}]"""
    return _plain(catalog.list_series(db(), query, limit))


def series(series_id: str) -> dict | None:
    return _plain(catalog.series_info(db(), series_id))
