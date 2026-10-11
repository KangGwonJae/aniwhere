"""에이전트 대화 테스트용 대본 LLM. tests/test_chat.py(DB 없음)와 tests/test_app.py(DB 있음)가 함께 씁니다.

ScriptLLM.tools()는 불릴 때마다 대본의 다음 {content?, tool_calls?}를 돌려주고, 받은 messages를 깊은 복사로 모아 두며,
매 호출마다 OpenAI 메시지 순서(assistant tool_calls → id마다 tool 메시지 하나)를 검사합니다.
"""
import copy
import itertools
import json

_ids = itertools.count(1)


def call(name, **arguments):
    """대본의 tool_call 하나. id는 자동으로 붙음."""
    return {"id": f"call_{next(_ids)}", "name": name, "arguments": arguments}


def check_order(messages):
    """tool 메시지의 tool_call_id는 바로 앞 assistant의 tool_calls에 있어야 하고, 그 모든 id에 tool 메시지가 있어야 함."""
    pending = set()
    for m in messages:
        if m["role"] == "tool":
            assert m["tool_call_id"] in pending, f"짝 없는 tool 메시지: {m['tool_call_id']}"
            pending.discard(m["tool_call_id"])
        else:
            assert not pending, f"tool 메시지가 빠진 tool_call: {pending}"
            pending = {tc["id"] for tc in m.get("tool_calls") or []}
    assert not pending, f"tool 메시지가 빠진 tool_call: {pending}"
    assert messages[-1]["role"] in ("user", "tool"), "마지막 메시지는 user 또는 tool이어야 함"


class ScriptLLM:
    """allow_tools=False면 OpenAI처럼 tool_calls를 내지 않음(obey_allow=False로 끄면 어기는 LLM 흉내)."""

    def __init__(self, *replies, obey_allow=True):
        self.replies, self.calls, self.obey_allow = list(replies), [], obey_allow

    def tools(self, system, messages, tools, *, allow_tools=True):
        check_order(messages)
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools,
                           "allow_tools": allow_tools})
        reply = self.replies.pop(0) if self.replies else {"content": "대본이 끝났어요."}
        calls = list(reply.get("tool_calls") or [])
        if not allow_tools and self.obey_allow:
            calls = []
        raw = {"role": "assistant", "content": reply.get("content")}
        if calls:
            raw["tool_calls"] = [{"id": c["id"], "type": "function",
                                  "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                                 for c in calls]
        return {"content": reply.get("content"), "tool_calls": calls, "raw": raw}
