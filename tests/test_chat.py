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
    assert ctx == {"tool": "find", "series_id": B, "title": "테스트 칼날", "candidate_ep": 3}
    assert labels(chat.suggest("find", FIND_EP, ctx)) == [("여기까지 봤어요", "테스트 칼날 3화까지 봤어"),
                                                          ("시청처 보기", "테스트 칼날 어디서 볼 수 있어?")]
    ctx = chat.context_of("find", {}, FIND_SERIES)
    assert ctx == {"tool": "find", "series_id": B, "title": "테스트 칼날"}
    assert chat.suggest("find", FIND_SERIES, ctx) == []                       # 되묻는 중이면 칩 없음
    no_follow = dict(FIND_SERIES, follow_up=None)
    assert labels(chat.suggest("find", no_follow, ctx)) == [("시청처 보기", "테스트 칼날 어디서 볼 수 있어?"),
                                                            ("인물 사전", "테스트 칼날 인물 알려줘")]
    ctx = chat.context_of("find", {}, FIND_AMB)
    assert ctx == {"tool": "find"} and chat.suggest("find", FIND_AMB, ctx) == []


def test_context_and_suggest_for_records():
    saved = dict(RECORD, previous_seen_ep=3, previous_rating=None)
    ctx = chat.context_of("save_record", {"series_id": A, "seen_ep": 7}, saved)
    assert ctx == {"tool": "save_record", "series_id": A, "title": "테스트 거인", "seen_ep": 7}
    assert labels(chat.suggest("save_record", saved, ctx)) == [("3분 복습", "테스트 거인 지금까지 복습해줘"),
                                                               ("인물 사전", "테스트 거인 인물 알려줘")]
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
    assert labels(chat.suggest("review", review, ctx)) == [("인물 사전", "테스트 거인 인물 알려줘"),
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
                                                                  ("인물 사전", "테스트 거인 인물 알려줘")]


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


# ───────────────────────── run() 루프 ─────────────────────────

from chat_script import ScriptLLM, call  # noqa: E402  (tests/가 sys.path에 들어감)


class Stub:
    """service 함수 흉내. 받은 인자를 calls에 (이름, 위치 인자, 키워드 인자)로 적고 정해진 값을 돌려줌."""

    def __init__(self, records=None):
        self.records = dict(records or {})          # {series_id: (seen_ep, rating)}
        self.calls = []
        self.fns = {name: self._wrap(name) for name in (*chat.LABELS, "series")}

    def _wrap(self, name):
        def f(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return getattr(self, name)(*args, **kwargs)
        return f

    def names(self):
        return [n for n, _, _ in self.calls]

    def kwargs(self, name):
        return [kw for n, _, kw in self.calls if n == name]

    def record(self, sid):
        if sid not in self.records:
            return None
        seen_ep, rating = self.records[sid]
        return {"series_id": sid, "name": NAMES[sid][0], "seen_ep": seen_ep, "total_episodes": 10, "rating": rating,
                "updated_at": "2026-10-11T00:00:00", "poster_url": None}

    def search_series(self, query=None, **_):
        q = (query or "").lower()
        return [{"series_id": sid, "name": ko, "title": en, "total_episodes": 10}
                for sid, (ko, en) in NAMES.items() if q in ko.lower() or q in en.lower()]

    def list_records(self, **_):
        return [self.record(sid) for sid in self.records]

    def get_record(self, series_id, **_):
        return self.record(series_id)

    def save_record(self, series_id, seen_ep, rating=None, **_):
        if series_id not in NAMES:
            raise ValueError(f"모르는 작품입니다: {series_id}")
        if not isinstance(seen_ep, int) or isinstance(seen_ep, bool) or not 0 <= seen_ep <= 10:
            raise ValueError(f"본 회차는 0부터 10까지의 정수여야 합니다: {seen_ep!r}")
        old = self.records.get(series_id, (None, None))
        self.records[series_id] = (seen_ep, rating if rating is not None else old[1])
        return self.record(series_id)

    def find(self, question, history=None, **_):
        return dict(FIND_EP, debug={"clues": {}, "ranked": []})

    def review(self, series_id, seen_ep=None, mode="summary", question=None, **_):
        rec = self.record(series_id)
        if not rec:
            return {"answer": None, "seen_ep": None, "sources": [], "follow_up": ASK_SEEN}
        return {"answer": "요약이에요 [1]", "seen_ep": rec["seen_ep"], "follow_up": None,
                "sources": [{"n": 1, "text": "SECRET 본문", "abs_ep": 1, "url": "https://e.com", "license": "CC", "name": "Fandom"}]}

    def dictionary(self, series_id, seen_ep=None, **_):
        rec = self.record(series_id)
        if not rec:
            return {"seen_ep": None, "entries": [], "follow_up": ASK_SEEN}
        return {"seen_ep": rec["seen_ep"], "follow_up": None,
                "entries": [{"kind": "character", "name": "Hero", "text": "주인공", "first_ep": 1, "url": None}]}

    def where_to_watch(self, series_id, **_):
        if series_id not in NAMES:
            raise ValueError(f"모르는 작품입니다: {series_id}")
        return {"series_id": series_id, "title": NAMES[series_id][0], "attribution": "",
                "seasons": [{"name": "시즌 1", "providers": ["Netflix"], "checked_at": "2026-10-05", "link": "https://e.com"}]}

    def recommend(self, likes, **_):
        return {"mood": "복수극", "follow_up": None,
                "picks": [{"series_id": B, "title": "테스트 칼날", "reason": "비슷해요", "poster_url": None, "genres": []}]}

    def series(self, series_id, **_):
        if series_id not in NAMES:
            return None
        return {"series_id": series_id, "title": NAMES[series_id][1], "title_ko": NAMES[series_id][0], "name": NAMES[series_id][0]}


def run_chat(stub, message, *script, history=(), **llm_opts):
    llm = ScriptLLM(*script, **llm_opts)
    return llm, chat.run(llm, message, list(history), stub.fns)


def tool_messages(llm, i):
    return [m for m in llm.calls[i]["messages"] if m["role"] == "tool"]


def test_no_llm_returns_need_llm_without_running_tools():
    stub = Stub()
    r = chat.run(None, "히어로 11화까지 봤어", [], stub.fns)
    assert r["answer"] == r["follow_up"] == chat.NEED_LLM
    assert r["steps"] == [] and r["results"] == {} and r["suggestions"] == [] and r["context"] is None
    assert stub.calls == []


def test_text_reply_without_tools_is_the_answer():
    stub = Stub()
    llm, r = run_chat(stub, "안녕", {"content": "안녕하세요! 무엇을 도울까요?"})
    assert r["answer"] == "안녕하세요! 무엇을 도울까요?" and r["follow_up"] is None and r["steps"] == []
    assert r["context"] is None and r["suggestions"] == [] and len(llm.calls) == 1
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "안녕"}] and llm.calls[0]["tools"] is chat.TOOLS


def test_one_tool_at_a_time_stops_at_three_tools_and_four_llm_calls():
    stub = Stub(records={A: (3, None)})
    llm, r = run_chat(stub, "내 기록", *[{"tool_calls": [call("list_records")]} for _ in range(5)])
    assert len(r["steps"]) == 3 and all(s["ok"] for s in r["steps"]) and stub.names() == ["list_records"] * 3
    assert len(llm.calls) == 4 and [c["allow_tools"] for c in llm.calls] == [True, True, True, False]
    assert r["answer"] == chat.NO_ANSWER                                  # 글이 없으면 고정 문구


def test_llm_that_ignores_allow_tools_false_is_still_stopped():
    stub = Stub()
    llm, r = run_chat(stub, "내 기록", *[{"tool_calls": [call("list_records")]} for _ in range(6)], obey_allow=False)
    assert len(llm.calls) == 4 and len(r["steps"]) == 3 and stub.names() == ["list_records"] * 3


def test_five_calls_in_one_reply_run_three_and_answer_every_id():
    stub = Stub()
    llm, r = run_chat(stub, "내 기록", {"tool_calls": [call("list_records") for _ in range(5)]}, {"content": "끝"})
    assert len(r["steps"]) == 3 and len(llm.calls) == 2 and llm.calls[1]["allow_tools"] is False
    tools = tool_messages(llm, 1)
    assert len(tools) == 5 and sum("한도" in m["content"] for m in tools) == 2
    assert llm.calls[1]["messages"][1]["role"] == "assistant" and len(llm.calls[1]["messages"][1]["tool_calls"]) == 5


def test_unknown_tool_counts_toward_limit_but_not_steps():
    stub = Stub()
    llm, r = run_chat(stub, "x", *[{"tool_calls": [call("delete_record", series_id=A)]} for _ in range(4)])
    assert r["steps"] == [] and stub.calls == [] and len(llm.calls) == 4
    assert "없는 도구입니다: delete_record" in tool_messages(llm, 1)[0]["content"]


def test_missing_required_argument_is_an_error_step():
    stub = Stub()
    llm, r = run_chat(stub, "x", {"tool_calls": [call("get_record")]}, {"content": "끝"})
    assert r["steps"] == [{"tool": "get_record", "label": "시청 기록 확인 중", "ok": False, "args": {}}]
    assert "series_id" in tool_messages(llm, 1)[0]["content"] and stub.calls == []


def test_non_object_arguments_are_treated_as_empty():
    stub = Stub()
    llm, r = run_chat(stub, "x", {"tool_calls": [dict(call("get_record"), arguments=[1, 2])]}, {"content": "끝"})
    assert r["steps"][0]["ok"] is False and stub.calls == []


def test_arguments_outside_schema_are_dropped():
    stub = Stub(records={A: (3, None)})
    run_chat(stub, "x", {"tool_calls": [call("get_record", series_id=A, user_id="x")]},
             {"tool_calls": [call("search_series", query="테스트", limit=9999)]}, {"content": "끝"})
    assert stub.kwargs("get_record") == [{"series_id": A}]
    assert stub.kwargs("search_series") == [{"query": "테스트"}]


def test_review_and_dictionary_never_receive_seen_ep():
    stub = Stub(records={A: (3, None)})
    run_chat(stub, "x", {"tool_calls": [call("review", series_id=A, mode="summary", seen_ep=99)]},
             {"tool_calls": [call("dictionary", series_id=A, seen_ep=99)]}, {"content": "끝"})
    assert stub.kwargs("review") == [{"series_id": A, "mode": "summary"}]
    assert stub.kwargs("dictionary") == [{"series_id": A}]


def test_follow_up_ends_the_loop_immediately_with_the_tools_text():
    stub = Stub()                                                            # 기록 없음 → review가 되물음
    llm, r = run_chat(stub, "테스트 거인 복습해줘",
                      {"tool_calls": [call("review", series_id=A, mode="summary"), call("dictionary", series_id=A)]},
                      {"content": "불리면 안 됨"})
    assert len(llm.calls) == 1
    assert r["answer"] == r["follow_up"] == ASK_SEEN and r["suggestions"] == []
    assert r["context"] == {"tool": "review", "series_id": A, "title": "테스트 거인"}   # 제목은 fns["series"]에서
    assert [s["tool"] for s in r["steps"]] == ["review"] and stub.names() == ["review", "series"]


def test_value_error_from_tool_becomes_error_message_and_loop_continues():
    stub = Stub()
    llm, r = run_chat(stub, "테스트 거인 어디서 봐?", {"tool_calls": [call("where_to_watch", series_id="tmdb:0")]},
                      {"tool_calls": [call("where_to_watch", series_id=A)]}, {"content": "넷플릭스요."})
    assert [(s["tool"], s["ok"]) for s in r["steps"]] == [("where_to_watch", False), ("where_to_watch", True)]
    assert "모르는 작품" in tool_messages(llm, 1)[0]["content"]
    assert r["results"]["where_to_watch"]["series_id"] == A and r["answer"] == "넷플릭스요."
    assert r["context"]["title"] == "테스트 거인" and [c["label"] for c in r["suggestions"]] == ["3분 복습", "인물 사전"]


def test_other_exceptions_propagate():
    stub = Stub()
    stub.fns["list_records"] = lambda **kw: (_ for _ in ()).throw(ConnectionError("db down"))
    with pytest.raises(ConnectionError):
        run_chat(stub, "내 기록", {"tool_calls": [call("list_records")]})


def test_find_gets_original_message_and_history_only_after_find():
    stub = Stub()
    run_chat(stub, "키 작은 아저씨가 칼 들고 날아다녀", {"tool_calls": [call("find", question="바꿔 쓴 글")]}, {"content": "끝"})
    assert stub.calls[0] == ("find", ("키 작은 아저씨가 칼 들고 날아다녀", []), {})
    history = [{"role": "user", "content": "거인 나오는 거"},
               {"role": "assistant", "content": "어떤 장면이었나요?", "context": {"tool": "find"}}]
    stub = Stub()
    _, r = run_chat(stub, "벽을 부숴", {"tool_calls": [call("find")]}, {"content": "끝"}, history=history)
    assert stub.calls[0] == ("find", ("벽을 부숴", history), {})
    assert r["steps"][0]["args"] == {} and r["context"]["tool"] == "find"


def test_history_context_is_appended_as_a_line_for_the_llm():
    history = [{"role": "user", "content": "히어로 49화까지 봤어"},
               {"role": "assistant", "content": "저장했어요.",
                "context": {"tool": "save_record", "series_id": A, "title": "테스트 거인", "seen_ep": 49}},
               {"role": "user", "content": "복습"},
               {"role": "assistant", "content": "컨텍스트 없음"},
               {"role": "assistant", "content": "tool 없음", "context": {"series_id": A}}]
    llm, _ = run_chat(Stub(), "그거 어디서 봐?", {"content": "끝"}, history=history)
    sent = llm.calls[0]["messages"]
    assert sent[1] == {"role": "assistant", "content": "저장했어요.\n[직전 결과: tool=save_record, series_id=tmdb:1, 제목=테스트 거인, 회차=49]"}
    assert sent[3] == {"role": "assistant", "content": "컨텍스트 없음"} and sent[4]["content"] == "tool 없음"
    assert sent[-1] == {"role": "user", "content": "그거 어디서 봐?"} and all("context" not in m for m in sent)


def test_llm_gets_slim_results_but_screen_gets_full():
    stub = Stub(records={A: (3, None)})
    llm, r = run_chat(stub, "복습", {"tool_calls": [call("review", series_id=A, mode="summary")]}, {"content": "끝"})
    assert "SECRET" not in tool_messages(llm, 1)[0]["content"]
    assert r["results"]["review"]["sources"][0]["text"] == "SECRET 본문"
    stub = Stub()
    llm, r = run_chat(stub, "장면", {"tool_calls": [call("find")]}, {"content": "끝"})
    assert "debug" not in tool_messages(llm, 1)[0]["content"] and "debug" in r["results"]["find"]


def test_results_keep_last_success_per_tool():
    stub = Stub(records={A: (3, None), B: (2, None)})
    _, r = run_chat(stub, "x", {"tool_calls": [call("get_record", series_id=A)]},
                    {"tool_calls": [call("get_record", series_id=B)]}, {"content": "끝"})
    assert r["results"]["get_record"]["series_id"] == B and len(r["steps"]) == 2
    assert r["context"] == {"tool": "get_record", "series_id": B, "title": "테스트 칼날", "seen_ep": 2}


# ───────────────────────── save_record 보호 ─────────────────────────

SEARCH = {"tool_calls": [call("search_series", query="테스트")]}            # A·B 2건
SEARCH_ONE = {"tool_calls": [call("search_series", query="거인")]}          # A 1건


def save(sid=A, **kw):
    return {"tool_calls": [call("save_record", series_id=sid, seen_ep=kw.pop("seen_ep", 7), **kw)]}


def error_of(llm, i=1):
    return tool_messages(llm, i)[-1]["content"]


def test_save_requires_series_id_from_this_turn_or_history():
    stub = Stub()
    llm, r = run_chat(stub, "테스트 거인 7화까지 봤어", save(), {"content": "끝"})
    assert r["steps"] == [{"tool": "save_record", "label": "시청 기록 저장 중", "ok": False,
                           "args": {"series_id": A, "seen_ep": 7}}]
    assert "search_series 결과나 직전 결과" in error_of(llm) and stub.records == {}
    history = [{"role": "assistant", "content": ASK_SEEN, "context": {"tool": "review", "series_id": A, "title": "테스트 거인"}}]
    stub = Stub()
    _, r = run_chat(stub, "7화", save(), {"content": "끝"}, history=history)
    assert stub.records[A] == (7, None) and r["answer"].startswith("「테스트 거인」 7화까지로 저장했어요.")


def test_save_with_two_candidates_needs_the_name_in_the_message():
    stub = Stub()
    llm, _ = run_chat(stub, "그거 7화까지 봤어", SEARCH, save(), {"content": "끝"})
    assert "후보가 여러 개" in error_of(llm, 2) and stub.records == {}
    stub = Stub()
    run_chat(stub, "테스트 칼날 7화까지 봤어", SEARCH, save(B), {"content": "끝"})
    assert stub.records[B] == (7, None)
    stub = Stub()
    run_chat(stub, "test blade 7화까지 봤어", SEARCH, save(B), {"content": "끝"})       # 영문 title도 인정
    assert stub.records[B] == (7, None)


def test_save_skips_ambiguity_check_for_ids_from_find_record_or_context():
    stub = Stub()
    run_chat(stub, "방금 그거 3화까지 봤어", {"tool_calls": [call("find")]}, SEARCH, save(B, seen_ep=3), {"content": "끝"})
    assert stub.records[B] == (3, None)


def test_save_requires_the_episode_number_in_the_message():
    stub = Stub()
    llm, _ = run_chat(stub, "테스트 거인 다 봤어", SEARCH_ONE, save(seen_ep=10), {"content": "끝"})
    assert "회차 숫자" in error_of(llm, 2) and stub.records == {}
    stub = Stub()
    llm, _ = run_chat(stub, "테스트 거인 11화 아직 안 봤어", SEARCH_ONE, save(seen_ep=10), {"content": "끝"})
    assert "회차 숫자" in error_of(llm, 2) and stub.records == {}


def test_save_rejects_season_notation():
    stub = Stub()
    llm, _ = run_chat(stub, "테스트 거인 2기 3화까지 봤어", SEARCH_ONE, save(seen_ep=3), {"content": "끝"})
    assert "시즌 안 회차" in error_of(llm, 2) and stub.records == {}


def test_save_accepts_numeric_string_episode():
    stub = Stub()
    _, r = run_chat(stub, "테스트 거인 7화까지 봤어", SEARCH_ONE, save(seen_ep="7"), {"content": "끝"})
    assert stub.records[A] == (7, None) and r["steps"][1]["args"]["seen_ep"] == 7


def test_rating_only_when_user_said_a_score():
    stub = Stub()
    run_chat(stub, "테스트 거인 7화까지 봤어", SEARCH_ONE, save(rating=4), {"content": "끝"})
    assert stub.kwargs("save_record")[0]["rating"] is None
    stub = Stub()
    run_chat(stub, "테스트 거인 7화까지 봤어 4점", SEARCH_ONE, save(rating=4), {"content": "끝"})
    assert stub.kwargs("save_record")[0]["rating"] == 4 and stub.records[A] == (7, 4)
    stub = Stub()
    run_chat(stub, "테스트 거인 7화까지 봤어 별 4.5", SEARCH_ONE, save(rating=4.5), {"content": "끝"})
    assert stub.records[A] == (7, 4.5)
    stub = Stub()
    run_chat(stub, "테스트 거인 7화까지 봤어 4점", SEARCH_ONE, save(rating="4"), {"content": "끝"})   # 문자열 평점은 버림
    assert stub.kwargs("save_record")[0]["rating"] is None


def test_second_save_in_one_turn_is_refused():
    stub = Stub()
    llm, r = run_chat(stub, "테스트 거인 7화까지, 테스트 칼날 3화까지 봤어", SEARCH, save(A, seen_ep=7), save(B, seen_ep=3), {"content": "끝"})
    assert "한 턴에 한 작품만" in error_of(llm, 3) and stub.records == {A: (7, None)}
    assert [(s["tool"], s["ok"]) for s in r["steps"]] == [("search_series", True), ("save_record", True), ("save_record", False)]


def test_save_over_existing_record_reports_previous_value():
    stub = Stub(records={A: (3, 4.0)})
    _, r = run_chat(stub, "테스트 거인 7화까지 봤어", SEARCH_ONE, save(), {"content": "복습도 해 드릴까요?"})
    assert r["results"]["save_record"]["previous_seen_ep"] == 3 and r["results"]["save_record"]["previous_rating"] == 4.0
    assert r["answer"] == "「테스트 거인」 7화까지로 저장했어요. (이전 3화) 복습도 해 드릴까요?"
    assert stub.records[A] == (7, 4.0)                                       # 평점을 안 말하면 이전 평점 유지
    assert [n for n in stub.names() if n == "get_record"] == ["get_record"]  # 이전 값 조회는 steps에 없음
    assert [s["tool"] for s in r["steps"]] == ["search_series", "save_record"]
    assert r["context"] == {"tool": "save_record", "series_id": A, "title": "테스트 거인", "seen_ep": 7}


def test_rewinding_the_record_is_allowed():
    stub = Stub(records={A: (9, None)})
    _, r = run_chat(stub, "테스트 거인 7화까지 봤어", SEARCH_ONE, save(), {"content": "끝"})
    assert stub.records[A] == (7, None) and "(이전 9화)" in r["answer"]


def test_save_value_error_is_returned_to_llm():
    stub = Stub()
    llm, r = run_chat(stub, "테스트 거인 99화까지 봤어", SEARCH_ONE, save(seen_ep=99), {"content": "끝"})
    assert "0부터 10까지" in error_of(llm, 2) and r["steps"][1]["ok"] is False and stub.records == {}
    assert r["context"] == {"tool": "search_series", "series_id": A, "title": "테스트 거인"} and r["suggestions"] == []


# ───────────────────────── service.chat 연결 ─────────────────────────

def test_service_chat_passes_only_public_functions_and_calls_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "db", lambda: None)
    monkeypatch.setattr(service, "get_llm", lambda: "LLM")
    monkeypatch.setattr(service._chat, "run", lambda llm, message, history, fns: seen.update(
        llm=llm, message=message, history=history, fns=fns) or {"answer": "ok"})
    assert service.chat("안녕") == {"answer": "ok"}
    assert seen["llm"] == "LLM" and seen["message"] == "안녕" and seen["history"] == []
    assert set(seen["fns"]) == {t["function"]["name"] for t in chat.TOOLS} | {"series"}
    public = {n: f for n, f in inspect.getmembers(service, inspect.isfunction) if f.__module__ == service.__name__}
    assert all(seen["fns"][name] is public[name] for name in seen["fns"])


def test_service_chat_forwards_message_and_history_to_find(monkeypatch):
    got = {}
    monkeypatch.setattr(service, "db", lambda: None)
    monkeypatch.setattr(service, "get_llm", lambda: ScriptLLM({"tool_calls": [call("find", question="바꿈")]}, {"content": "끝"}))
    monkeypatch.setattr(service._find, "find", lambda db, question, history, **kw: got.update(
        question=question, history=history) or FIND_EP)
    history = [{"role": "user", "content": "거인"}, {"role": "assistant", "content": "?", "context": {"tool": "find"}}]
    r = service.chat("벽을 부숴", history)
    assert got == {"question": "벽을 부숴", "history": history}
    assert r["results"]["find"]["status"] == "episode" and r["context"]["series_id"] == B


# ───────────────────────── 검토 반영: 한국어 입력 보호 강화 ─────────────────────────

@pytest.mark.parametrize("message", ["테스트 거인 시즌 3 7화까지 봤어", "테스트 거인 Season 2 7화까지 봤어", "테스트 거인 2쿨 7화까지 봤어"])
def test_save_rejects_season_first_notation(message):
    stub = Stub()
    llm, _ = run_chat(stub, message, SEARCH_ONE, save(seen_ep=7), {"content": "끝"})
    assert "시즌 안 회차" in error_of(llm, 2) and stub.records == {}


def test_rating_needs_the_number_next_to_the_unit():
    stub = Stub()
    run_chat(stub, "테스트 거인 1화까지 봤어 별로였어", SEARCH_ONE, save(seen_ep=1, rating=1), {"content": "끝"})
    assert stub.kwargs("save_record")[0]["rating"] is None                  # "별로"의 별, "1화"의 1은 점수가 아님
    stub = Stub()
    run_chat(stub, "테스트 거인 10화까지 봤어 1점", SEARCH_ONE, save(seen_ep=10, rating=1), {"content": "끝"})
    assert stub.kwargs("save_record")[0]["rating"] == 1
    stub = Stub()
    run_chat(stub, "테스트 거인 10화까지 봤어 별 1개", SEARCH_ONE, save(seen_ep=10, rating=1), {"content": "끝"})
    assert stub.kwargs("save_record")[0]["rating"] == 1


def test_save_name_match_ignores_spaces_and_case():
    stub = Stub()
    run_chat(stub, "테스트칼날 7화까지 봤어", SEARCH, save(B), {"content": "끝"})
    assert stub.records[B] == (7, None)
    stub = Stub()
    run_chat(stub, "TestBlade 7화까지 봤어", SEARCH, save(B), {"content": "끝"})
    assert stub.records[B] == (7, None)


def test_save_takes_only_the_number_before_kkaji_when_present():
    stub = Stub()
    llm, _ = run_chat(stub, "테스트 거인 7화까지 봤는데 8화 내용 알려줘", SEARCH_ONE, save(seen_ep=8), {"content": "끝"})
    assert "회차 숫자" in error_of(llm, 2) and stub.records == {}           # 8화는 질문이지 본 회차가 아님
    stub = Stub()
    run_chat(stub, "테스트 거인 7화까지 봤는데 8화 내용 알려줘", SEARCH_ONE, save(seen_ep=7), {"content": "끝"})
    assert stub.records[A] == (7, None)
    stub = Stub()
    run_chat(stub, "테스트 거인 7화 봤어", SEARCH_ONE, save(seen_ep=7), {"content": "끝"})     # 까지가 없으면 아무 숫자
    assert stub.records[A] == (7, None)


def test_save_episode_number_may_come_from_previous_turn_after_clarifying_question():
    asked = [{"role": "user", "content": "테스트 7화까지 봤어"},
             {"role": "assistant", "content": "테스트 거인과 테스트 칼날 중 어느 작품인가요?", "context": {"tool": "search_series"}}]
    stub = Stub()
    _, r = run_chat(stub, "테스트 칼날", {"tool_calls": [call("search_series", query="칼날")]}, save(B), {"content": "끝"},
                    history=asked)
    assert stub.records[B] == (7, None) and r["answer"].startswith("「테스트 칼날」 7화까지로 저장했어요.")
    no_tool = [asked[0], {"role": "assistant", "content": "어느 작품인가요?"}]                 # 도구 없이 되물은 턴
    stub = Stub()
    run_chat(stub, "테스트 칼날", {"tool_calls": [call("search_series", query="칼날")]}, save(B), {"content": "끝"}, history=no_tool)
    assert stub.records[B] == (7, None)
    answered = [{"role": "user", "content": "11화가 뭐였지"},
                {"role": "assistant", "content": "11화는 …", "context": {"tool": "review", "series_id": A, "title": "테스트 거인"}}]
    stub = Stub()
    llm, _ = run_chat(stub, "테스트 거인 봤어", SEARCH_ONE, save(seen_ep=11), {"content": "끝"}, history=answered)
    assert "회차 숫자" in error_of(llm, 2) and stub.records == {}           # 되묻는 상태가 아니면 전 턴 숫자를 쓰지 않음
