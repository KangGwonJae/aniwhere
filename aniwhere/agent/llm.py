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
        if not self.model:
            raise RuntimeError("config/settings.yaml의 llm.model을 정하세요")
        if client is None:
            from openai import OpenAI
            if not openai_api_key().isascii():
                raise RuntimeError(".env의 OPENAI_API_KEY에 영문·숫자가 아닌 글자가 섞여 있습니다. 키 뒤에 붙은 글자를 지우세요")
            client = OpenAI(api_key=openai_api_key(), timeout=60, max_retries=2)
        self.client = client

    def _chat(self, system, user, **extra):
        args = {"model": self.model, "messages": [{"role": "system", "content": system},
                                                  {"role": "user", "content": user}], **extra}
        if self.temperature is not None:
            args["temperature"] = self.temperature
        try:
            reply = self.client.chat.completions.create(**args)
        except Exception as e:
            # temperature를 정할 수 없는 모델(추론 모델)이면 그 값 없이 다시 부르고, 다음부터는 보내지 않음
            if "temperature" not in args or "temperature" not in str(e):
                raise
            self.temperature = None
            del args["temperature"]
            reply = self.client.chat.completions.create(**args)
        return reply.choices[0].message.content or ""

    def text(self, system: str, user: str) -> str:
        return self._chat(system, user).strip()

    def json(self, system: str, user: str) -> dict:
        """JSON 객체 하나로 답하게 함. 프롬프트에 'JSON'이라는 말과 형식이 적혀 있어야 합니다."""
        raw = self._chat(system, user, response_format={"type": "json_object"})
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


_llm = None


def get_llm() -> LLM | None:
    global _llm
    if _llm is None and openai_api_key():
        _llm = LLM()
    return _llm
