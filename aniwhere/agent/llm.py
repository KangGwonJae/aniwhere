"""LLM 호출 (OpenAI). 모델 이름은 config/settings.yaml의 llm, 키는 .env의 OPENAI_API_KEY.

키가 없으면 get_llm()이 None을 돌려주고, 각 기능은 LLM 없이 검색 결과만으로 동작합니다.
"""
import json
from pathlib import Path

from aniwhere.config import openai_api_key, section

PROMPTS = Path(__file__).resolve().parent / "prompts"


def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


class LLM:
    def __init__(self, client=None, model=None):
        cfg = section("llm")
        self.model = model or cfg.get("model")
        self.temperature = cfg.get("temperature")
        self.parallel_tool_calls = False       # tools()에서 한 번에 하나씩만 부르게 함. 받지 않는 모델이면 None
        if not self.model:
            raise RuntimeError("config/settings.yaml의 llm.model을 정하세요")
        if client is None:
            from openai import OpenAI
            if not openai_api_key().isascii():
                raise RuntimeError(".env의 OPENAI_API_KEY에 영문·숫자가 아닌 글자가 섞여 있습니다. 키 뒤에 붙은 글자를 지우세요")
            client = OpenAI(api_key=openai_api_key(), timeout=60, max_retries=2)
        self.client = client

    @staticmethod
    def _messages(system, user):
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _chat(self, messages, **extra):
        """chat.completions 1회 → 응답 message 객체 (content, tool_calls)."""
        args = {"model": self.model, "messages": messages, **extra}
        if self.temperature is not None:
            args["temperature"] = self.temperature
        try:
            reply = self.client.chat.completions.create(**args)
        except Exception as e:
            # 받지 않는 인자(temperature: 추론 모델 / parallel_tool_calls: 일부 모델)면 그것만 빼고 다시 부르고, 다음부터는 보내지 않음
            dropped = [k for k in ("temperature", "parallel_tool_calls") if k in args and k in str(e)]
            if not dropped:
                raise
            for k in dropped:
                del args[k]
            if "temperature" in dropped:
                self.temperature = None
            if "parallel_tool_calls" in dropped:
                self.parallel_tool_calls = None
            reply = self.client.chat.completions.create(**args)
        return reply.choices[0].message

    def text(self, system: str, user: str) -> str:
        return (self._chat(self._messages(system, user)).content or "").strip()

    def json(self, system: str, user: str) -> dict:
        """JSON 객체 하나로 답하게 함. 프롬프트에 'JSON'이라는 말과 형식이 적혀 있어야 합니다."""
        raw = self._chat(self._messages(system, user), response_format={"type": "json_object"}).content or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def tools(self, system: str, messages: list[dict], tools: list[dict], *, allow_tools=True) -> dict:
        """function calling 1회. → {content: str | None, tool_calls: [{id, name, arguments: dict}], raw: dict}
        raw는 다음 요청의 messages에 그대로 붙일 assistant 메시지(OpenAI 형식, arguments는 원문 문자열).
        arguments가 JSON 객체가 아니면 {}(raw에는 "{}"), type이 function이 아닌 호출은 버림.
        allow_tools=False면 tool_choice="none"으로 글만 받음(tools는 그대로 보냄)."""
        extra = {"tools": tools, "tool_choice": "auto" if allow_tools else "none"}
        if self.parallel_tool_calls is not None:
            extra["parallel_tool_calls"] = self.parallel_tool_calls
        msg = self._chat([{"role": "system", "content": system}, *messages], **extra)
        calls, raw_calls = [], []
        for tc in msg.tool_calls or []:
            if getattr(tc, "type", "function") != "function":
                continue
            text = tc.function.arguments or "{}"
            try:
                args = json.loads(text)
            except json.JSONDecodeError:
                args = None
            if not isinstance(args, dict):
                args, text = {}, "{}"
            calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
            raw_calls.append({"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": text}})
        raw = {"role": "assistant", "content": msg.content}
        if raw_calls:
            raw["tool_calls"] = raw_calls
        return {"content": msg.content, "tool_calls": calls, "raw": raw}


_llm = None


def get_llm() -> LLM | None:
    global _llm
    if _llm is None and openai_api_key():
        _llm = LLM()
    return _llm
