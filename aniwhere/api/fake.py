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

# 키는 catalog.series_info와 같음 (name = title_ko가 있으면 title_ko, 없으면 title)
SERIES = {
    HERO: {"series_id": HERO, "title": "My Hero Academia", "title_ko": "나의 히어로 아카데미아",
           "overview_ko": "개성이 없던 소년 미도리야가 최고의 히어로를 꿈꾸며 유에이 고교에 들어간다.", "poster_url": None,
           "status": "Ended", "next_episode_at": None, "total_episodes": 138,
           "genres_ko": ["애니메이션", "액션 & 어드벤처", "코미디"], "first_air_date": "2016-04-03",
           "name": "나의 히어로 아카데미아"},
    TITAN: {"series_id": TITAN, "title": "Attack on Titan", "title_ko": "진격의 거인",
            "overview_ko": "거인에게 어머니를 잃은 엘런이 조사병단에 들어가 벽 밖의 비밀을 쫓는다.", "poster_url": None,
            "status": "Ended", "next_episode_at": None, "total_episodes": 89,
            "genres_ko": ["애니메이션", "액션 & 어드벤처", "드라마"], "first_air_date": "2013-04-07",
            "name": "진격의 거인"},
}
# agent/review.py의 근거 형식: 번호(n)와 짧게 자른 본문, 출처
SOURCE = {"n": 1, "text": "미도리야는 올마이트에게서 원 포 올을 물려받는다.", "abs_ep": 2,
          "url": "https://bokunoheroacademia.fandom.com/wiki/Episode_2", "license": "CC BY-SA 3.0", "name": "Fandom"}
ASK_SEEN = "어디까지 봤어요? 마지막으로 본 회차를 알려 주세요."           # agent/review.py ASK_SEEN
ASK_QUESTION = "무엇이 궁금한지 알려 주세요."                              # agent/review.py, ask인데 질문 없을 때
ASK_MORE = "기억나는 인물의 생김새나 이름, 장소, 그 장면 앞뒤에 있었던 일을 조금 더 알려 주세요."   # agent/find.py ASK_MORE
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


# agent/find.py의 근거 형식: 작품·회차와 출처 링크만. 줄거리 본문(text)은 넣지 않음 (아직 안 본 회차일 수 있음)
TITAN_SOURCE = {"series_id": TITAN, "abs_ep": 1, "name": "Fandom", "license": "CC BY-SA 3.0",
                "url": "https://attackontitan.fandom.com/wiki/Episode_1"}


def _found(status, answer, candidates=(), follow_up=None, sources=()):
    """agent/find.py의 _result와 같은 키. debug는 실제로는 단서·검색 순위를 담음."""
    return {"status": status, "answer": answer, "candidates": list(candidates), "follow_up": follow_up,
            "sources": list(sources), "debug": {"clues": {}, "ranked": []}}


def find(question: str, history: list[dict] | None = None, *, user_id=USER) -> dict:
    """status는 질문의 낱말로 고름 — 화면 네 갈래를 모두 만들어 볼 수 있게:
    "헷갈" → ambiguous(후보 둘 + follow_up), "없는" → none, "작품" → series, 그 외 → episode."""
    ep1 = {"series_id": TITAN, "title": "진격의 거인", "abs_ep": 1,
           "label": "1기 1화 (전체 1화) 〈2000년 후의 너에게〉", "score": 0.91}
    if "헷갈" in question:
        # 회차 후보와, 회차를 정하지 못한 작품 단위 후보(LLM 없는 경로·인물 설명으로 고른 후보)가 섞일 수 있음
        return _found("ambiguous", "비슷한 후보가 여러 개 있어요. 벽이 부서지는 장면이 두 작품에 다 있어요.",
                      [ep1, {"series_id": HERO, "title": "나의 히어로 아카데미아"}], ASK_MORE, [TITAN_SOURCE])
    if "없는" in question:
        return _found("none", "지금 단서로는 찾지 못했어요.", follow_up=ASK_MORE)
    if "작품" in question:
        return _found("series", "「진격의 거인」 같아요. 몇 화인지는 지금 단서만으로는 정하기 어려워요.",
                      [{"series_id": TITAN, "title": "진격의 거인"}],
                      "어떤 장면이었는지 조금 더 알려 주시면 회차도 찾아볼게요.", [TITAN_SOURCE])
    return _found("episode", "「진격의 거인」 1기 1화 (전체 1화) 〈2000년 후의 너에게〉 같아요.", [ep1], None, [TITAN_SOURCE])


def where_to_watch(series_id: str) -> dict:
    info = _series(series_id)
    return {"series_id": series_id, "title": info["name"],
            "seasons": [{"name": "시즌 3", "providers": ["Laftel", "Netflix"], "checked_at": "2026-10-05",
                         "link": "https://www.justwatch.com/kr"}],
            "attribution": "시청처 정보: JustWatch (TMDB 제공). 구독형 제공처만 표시합니다."}


def review(series_id: str, seen_ep: int | None = None, mode: str = "summary", question: str | None = None, *,
           user_id=USER) -> dict:
    # 확인 순서는 agent/review.py와 같음: mode → 작품 → 본 회차(없으면 기록장) → 질문
    if mode not in MODES:
        raise ValueError(f"mode는 {list(MODES)} 중 하나여야 합니다: {mode!r}")
    info = _series(series_id)
    seen_ep = _seen(series_id, seen_ep)
    if seen_ep is None:
        return {"answer": None, "seen_ep": None, "sources": [], "follow_up": ASK_SEEN}
    seen_ep = min(int(seen_ep), info["total_episodes"])
    if seen_ep <= 0:
        return {"answer": f"아직 「{info['name']}」을(를) 보기 전이라 복습할 내용이 없어요.", "seen_ep": 0,
                "sources": [], "follow_up": None}
    if mode == "ask" and not (question or "").strip():
        return {"answer": None, "seen_ep": seen_ep, "sources": [], "follow_up": ASK_QUESTION}
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
                       "poster_url": None, "genres": SERIES[TITAN]["genres_ko"]}]}


def save_record(series_id: str, seen_ep: int, rating: float | None = None, *, user_id=USER) -> dict:
    info = _series(series_id)
    if not isinstance(seen_ep, int) or isinstance(seen_ep, bool) or seen_ep < 0 or seen_ep > info["total_episodes"]:
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
    return {"series_id": series_id, "name": info["name"], "seen_ep": r["seen_ep"],
            "total_episodes": info["total_episodes"], "rating": r["rating"], "updated_at": r["updated_at"],
            "poster_url": info["poster_url"]}


def list_records(*, user_id=USER) -> list[dict]:
    """records.list_all처럼 최근에 저장한 기록이 먼저."""
    newest = sorted(_records, key=lambda sid: dt.datetime.fromisoformat(_records[sid]["updated_at"]), reverse=True)
    return [get_record(sid) for sid in newest]


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
