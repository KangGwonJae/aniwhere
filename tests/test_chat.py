"""에이전트 대화(aniwhere/agent/chat.py) 테스트. DB·LLM 없음: stub 도구 함수와 대본 LLM(tests/chat_script.py)으로 돕니다.

run()이 지키는 것: 도구 3번·LLM 4번 한도, OpenAI 메시지 순서, follow_up 즉시 종료, 스키마 밖 인자 버림,
save_record 코드 보호, review·dictionary에 seen_ep 못 넘김, 다음 행동 칩·context 규칙.
"""
import inspect

import pytest

from aniwhere import service
from aniwhere.agent import chat

A, B = "tmdb:1", "tmdb:2"
NAMES = {A: ("테스트 거인", "Test Titan"), B: ("테스트 칼날", "Test Blade")}
ASK_SEEN = "어디까지 봤어요? 마지막으로 본 회차를 알려 주세요."


# ───────────────────────── 도구 목록 ─────────────────────────

def test_tools_are_public_service_functions_without_delete_or_series():
    names = [t["function"]["name"] for t in chat.TOOLS]
    public = {n for n, f in inspect.getmembers(service, inspect.isfunction) if f.__module__ == service.__name__}
    assert set(names) <= public
    assert "delete_record" not in names and "series" not in names and "chat" not in names
    assert set(chat.LABELS) == set(names) and all(not v.endswith("…") for v in chat.LABELS.values())
    assert len(names) == len(set(names))


def test_review_and_dictionary_cannot_take_seen_ep():
    for name in ("review", "dictionary"):
        assert "seen_ep" not in chat.SCHEMAS[name]["properties"], name
    assert chat.SCHEMAS["find"]["properties"] == {}
    assert set(chat.SCHEMAS["save_record"]["required"]) == {"series_id", "seen_ep"}
    assert chat.SCHEMAS["review"]["properties"]["mode"]["enum"] == ["summary", "characters", "last", "ask"]


# ───────────────────────── as_result · slim ─────────────────────────

def test_as_result_wraps_list_and_none():
    assert chat.as_result({"a": 1}) == {"a": 1}
    assert chat.as_result([1, 2]) == {"items": [1, 2]}
    assert chat.as_result(None) == {"record": None}


def test_slim_drops_source_text_and_debug_without_touching_original():
    result = {"answer": "x", "sources": [{"n": 1, "text": "본문", "abs_ep": 1}], "debug": {"clues": {}}}
    assert chat.slim(result) == {"answer": "x", "sources": [{"n": 1, "abs_ep": 1}]}
    assert result["sources"][0]["text"] == "본문" and "debug" in result


# ───────────────────────── context_of · suggest ─────────────────────────

FIND_EP = {"status": "episode", "answer": "a", "follow_up": None, "sources": [],
           "candidates": [{"series_id": B, "title": "테스트 칼날", "abs_ep": 3, "label": "1기 3화"}]}
FIND_SERIES = {"status": "series", "answer": "a", "follow_up": "더 알려 주세요", "sources": [],
               "candidates": [{"series_id": B, "title": "테스트 칼날"}]}
FIND_AMB = {"status": "ambiguous", "answer": "a", "follow_up": "누가 나왔나요?", "sources": [],
            "candidates": [{"series_id": A, "title": "테스트 거인", "abs_ep": 1}, {"series_id": B, "title": "테스트 칼날"}]}
RECORD = {"series_id": A, "name": "테스트 거인", "seen_ep": 7, "total_episodes": 10, "rating": None,
          "updated_at": "t", "poster_url": None}


def labels(chips):
    return [(c["label"], c["message"]) for c in chips]


def test_context_and_suggest_for_find():
    ctx = chat.context_of("find", {}, FIND_EP)
    assert ctx == {"tool": "find", "series_id": B, "title": "테스트 칼날", "seen_ep": 3}
    assert labels(chat.suggest("find", FIND_EP, ctx)) == [("여기까지 봤어요", "테스트 칼날 3화까지 봤어"),
                                                          ("시청처 보기", "테스트 칼날 어디서 볼 수 있어?")]
    ctx = chat.context_of("find", {}, FIND_SERIES)
    assert ctx == {"tool": "find", "series_id": B, "title": "테스트 칼날"}
    assert chat.suggest("find", FIND_SERIES, ctx) == []                       # 되묻는 중이면 칩 없음
    no_follow = dict(FIND_SERIES, follow_up=None)
    assert labels(chat.suggest("find", no_follow, ctx)) == [("시청처 보기", "테스트 칼날 어디서 볼 수 있어?"),
                                                            ("인물·용어", "테스트 칼날 인물·용어 알려줘")]
    ctx = chat.context_of("find", {}, FIND_AMB)
    assert ctx == {"tool": "find"} and chat.suggest("find", FIND_AMB, ctx) == []


def test_context_and_suggest_for_records():
    saved = dict(RECORD, previous_seen_ep=3, previous_rating=None)
    ctx = chat.context_of("save_record", {"series_id": A, "seen_ep": 7}, saved)
    assert ctx == {"tool": "save_record", "series_id": A, "title": "테스트 거인", "seen_ep": 7}
    assert labels(chat.suggest("save_record", saved, ctx)) == [("3분 복습", "테스트 거인 지금까지 복습해줘"),
                                                               ("인물·용어", "테스트 거인 인물·용어 알려줘")]
    assert chat.context_of("get_record", {"series_id": A}, RECORD) == {"tool": "get_record", "series_id": A,
                                                                      "title": "테스트 거인", "seen_ep": 7}
    assert chat.suggest("get_record", RECORD, chat.context_of("get_record", {"series_id": A}, RECORD)) == []
    assert chat.context_of("get_record", {"series_id": A}, {"record": None}) == {"tool": "get_record"}
    assert chat.context_of("list_records", {}, {"items": [RECORD]}) == {"tool": "list_records"}
    assert chat.suggest("list_records", {"items": [RECORD]}, {"tool": "list_records"}) == []


def test_context_and_suggest_for_review_dictionary_where():
    review = {"answer": "요약", "seen_ep": 7, "sources": [], "follow_up": None}
    ctx = chat.context_of("review", {"series_id": A, "mode": "summary"}, review, title="테스트 거인")
    assert ctx == {"tool": "review", "series_id": A, "title": "테스트 거인", "seen_ep": 7}
    assert labels(chat.suggest("review", review, ctx)) == [("인물·용어", "테스트 거인 인물·용어 알려줘"),
                                                           ("시청처 보기", "테스트 거인 어디서 볼 수 있어?")]
    assert chat.suggest("review", review, chat.context_of("review", {"series_id": A}, review)) == []   # 제목 없으면 칩 뺌
    asking = {"answer": None, "seen_ep": None, "sources": [], "follow_up": ASK_SEEN}
    ctx = chat.context_of("review", {"series_id": A, "mode": "summary"}, asking, title="테스트 거인")
    assert ctx == {"tool": "review", "series_id": A, "title": "테스트 거인"} and chat.suggest("review", asking, ctx) == []

    dic = {"seen_ep": 7, "entries": [], "follow_up": None}
    ctx = chat.context_of("dictionary", {"series_id": A}, dic, title="테스트 거인")
    assert labels(chat.suggest("dictionary", dic, ctx)) == [("3분 복습", "테스트 거인 지금까지 복습해줘"),
                                                            ("시청처 보기", "테스트 거인 어디서 볼 수 있어?")]

    where = {"series_id": A, "title": "테스트 거인", "seasons": [], "attribution": ""}
    ctx = chat.context_of("where_to_watch", {"series_id": A}, where)          # 제목은 결과에서
    assert ctx == {"tool": "where_to_watch", "series_id": A, "title": "테스트 거인"}
    assert labels(chat.suggest("where_to_watch", where, ctx)) == [("3분 복습", "테스트 거인 지금까지 복습해줘"),
                                                                  ("인물·용어", "테스트 거인 인물·용어 알려줘")]


def test_context_and_suggest_for_search_and_recommend():
    one = {"items": [{"series_id": A, "name": "테스트 거인", "title": "Test Titan", "total_episodes": 10}]}
    two = {"items": one["items"] + [{"series_id": B, "name": "테스트 칼날", "title": "Test Blade", "total_episodes": 5}]}
    assert chat.context_of("search_series", {"query": "테스트"}, one) == {"tool": "search_series", "series_id": A,
                                                                        "title": "테스트 거인"}
    assert chat.context_of("search_series", {"query": "테스트"}, two) == {"tool": "search_series"}
    assert chat.suggest("search_series", one, chat.context_of("search_series", {}, one)) == []

    rec = {"mood": "m", "follow_up": None, "picks": [{"series_id": B, "title": "테스트 칼날", "reason": "r"}]}
    ctx = chat.context_of("recommend", {"likes": "x"}, rec)
    assert ctx == {"tool": "recommend", "series_id": B, "title": "테스트 칼날"}
    assert labels(chat.suggest("recommend", rec, ctx)) == [("시청처 보기", "테스트 칼날 어디서 볼 수 있어?"),
                                                           ("다른 추천", "다른 작품도 추천해줘")]
    empty = {"mood": "m", "follow_up": None, "picks": []}
    assert chat.context_of("recommend", {}, empty) == {"tool": "recommend"} and chat.suggest("recommend", empty, {"tool": "recommend"}) == []


# ───────────────────────── save_with_previous · confirmation · find_history ─────────────────────────

def test_save_with_previous_reads_old_record_first():
    calls = []
    fns = {"get_record": lambda **kw: calls.append(("get", kw)) or dict(RECORD, seen_ep=3, rating=4.0),
           "save_record": lambda **kw: calls.append(("save", kw)) or RECORD}
    saved = chat.save_with_previous(fns, A, 7)
    assert calls == [("get", {"series_id": A}), ("save", {"series_id": A, "seen_ep": 7, "rating": None})]
    assert saved["previous_seen_ep"] == 3 and saved["previous_rating"] == 4.0 and saved["seen_ep"] == 7
    assert chat.confirmation(saved) == "「테스트 거인」 7화까지로 저장했어요. (이전 3화)"
    fresh = chat.save_with_previous({"get_record": lambda **kw: None, "save_record": lambda **kw: RECORD}, A, 7)
    assert fresh["previous_seen_ep"] is None and chat.confirmation(fresh) == "「테스트 거인」 7화까지로 저장했어요."


def test_find_history_only_when_last_assistant_turn_was_find():
    find_turns = [{"role": "user", "content": "거인"}, {"role": "assistant", "content": "a", "context": {"tool": "find"}}]
    assert chat.find_history(find_turns) == find_turns
    other = [{"role": "user", "content": "거인"}, {"role": "assistant", "content": "a", "context": {"tool": "review"}}]
    assert chat.find_history(other) == []
    assert chat.find_history([{"role": "user", "content": "거인"}, {"role": "assistant", "content": "a"}]) == []
    assert chat.find_history([]) == []
