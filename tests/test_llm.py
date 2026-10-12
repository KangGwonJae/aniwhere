"""agent/llm.py의 LLM 래퍼 테스트. 가짜 OpenAI 클라이언트로 요청 인자와 응답 해석을 확인합니다 (네트워크 없음)."""
from types import SimpleNamespace as NS

from aniwhere.agent.llm import LLM

TOOLS = [{"type": "function", "function": {"name": "get_record", "parameters": {"type": "object", "properties": {}}}}]


def reply(content=None, tool_calls=()):
    return NS(choices=[NS(message=NS(role="assistant", content=content, tool_calls=list(tool_calls) or None))])


def tool_call(id, name, arguments, type="function"):
    return NS(id=id, type=type, function=NS(name=name, arguments=arguments))


class FakeClient:
    """client.chat.completions.create(**kw) 흉내: 받은 인자를 모으고 정해 둔 응답을 차례로 돌려줌.
    fail_on에 적은 인자가 들어오면 OpenAI처럼 예외를 냄 (받지 않는 인자 재시도 확인용)."""

    def __init__(self, *replies, fail_on=None):
        self.replies, self.requests, self.fail_on = list(replies), [], fail_on
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        if self.fail_on and self.fail_on in kw:
            raise RuntimeError(f"Unsupported parameter: '{self.fail_on}' is not supported with this model.")
        return self.replies.pop(0)


def test_tools_request_has_tools_and_no_response_format():
    client = FakeClient(reply("답"))
    out = LLM(client=client).tools("시스템", [{"role": "user", "content": "안녕"}], TOOLS)
    req = client.requests[0]
    assert req["tools"] == TOOLS and req["tool_choice"] == "auto" and req["parallel_tool_calls"] is False
    assert "response_format" not in req
    assert req["messages"] == [{"role": "system", "content": "시스템"}, {"role": "user", "content": "안녕"}]
    assert out == {"content": "답", "tool_calls": [], "raw": {"role": "assistant", "content": "답"}}


def test_allow_tools_false_sends_tool_choice_none_but_keeps_tools():
    client = FakeClient(reply("답"))
    LLM(client=client).tools("s", [{"role": "user", "content": "u"}], TOOLS, allow_tools=False)
    assert client.requests[0]["tool_choice"] == "none" and client.requests[0]["tools"] == TOOLS


def test_tool_call_arguments_are_parsed_and_raw_keeps_original_string():
    client = FakeClient(reply(None, [tool_call("c1", "get_record", '{"series_id": "tmdb:1"}')]))
    out = LLM(client=client).tools("s", [{"role": "user", "content": "u"}], TOOLS)
    assert out["content"] is None
    assert out["tool_calls"] == [{"id": "c1", "name": "get_record", "arguments": {"series_id": "tmdb:1"}}]
    assert out["raw"] == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "get_record", "arguments": '{"series_id": "tmdb:1"}'}}]}


def test_broken_or_non_object_arguments_become_empty():
    client = FakeClient(reply(None, [tool_call("c1", "a", '{"x": '), tool_call("c2", "b", "[1, 2]"), tool_call("c3", "c", "")]))
    out = LLM(client=client).tools("s", [{"role": "user", "content": "u"}], TOOLS)
    assert [c["arguments"] for c in out["tool_calls"]] == [{}, {}, {}]
    assert [c["function"]["arguments"] for c in out["raw"]["tool_calls"]] == ["{}", "{}", "{}"]


def test_non_function_tool_calls_are_dropped():
    client = FakeClient(reply(None, [tool_call("c1", "x", "{}", type="custom"), tool_call("c2", "get_record", "{}")]))
    out = LLM(client=client).tools("s", [{"role": "user", "content": "u"}], TOOLS)
    assert [c["id"] for c in out["tool_calls"]] == ["c2"] and [c["id"] for c in out["raw"]["tool_calls"]] == ["c2"]


def test_text_and_json_still_return_str_and_dict():
    llm = LLM(client=FakeClient(reply("  답  "), reply('{"a": 1}'), reply(None), reply("깨진")))
    assert llm.text("s", "u") == "답"
    assert llm.json("s", "u") == {"a": 1}
    assert llm.text("s", "u") == ""
    assert llm.json("s", "u") == {}


def test_unsupported_parallel_tool_calls_is_dropped_and_not_sent_again():
    client = FakeClient(reply("1"), reply("2"), fail_on="parallel_tool_calls")
    llm = LLM(client=client)
    llm.tools("s", [{"role": "user", "content": "u"}], TOOLS)
    assert "parallel_tool_calls" in client.requests[0] and "parallel_tool_calls" not in client.requests[1]
    llm.tools("s", [{"role": "user", "content": "u"}], TOOLS)
    assert "parallel_tool_calls" not in client.requests[2] and len(client.requests) == 3


def test_unsupported_temperature_is_dropped_and_not_sent_again():
    client = FakeClient(reply("1"), reply("2"), fail_on="temperature")
    llm = LLM(client=client)
    llm.temperature = 0
    assert llm.text("s", "u") == "1"
    assert "temperature" in client.requests[0] and "temperature" not in client.requests[1]
    llm.text("s", "u")
    assert "temperature" not in client.requests[2]
