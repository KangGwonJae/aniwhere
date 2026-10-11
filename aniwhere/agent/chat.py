"""모든 기능의 입구 — 에이전트 대화. 사용자의 한 문장에서 LLM이 도구(기능)를 고르고, 결과를 보고 다시 고릅니다.

짧은 도구 루프: 한 턴에 도구 호출 최대 3번, LLM 호출 최대 4번. 도구가 되물으면(follow_up) 루프를 바로 끝내고
그 글을 그대로 답으로 씁니다. 기록 저장(save_record)은 프롬프트만 믿지 않고 코드가 인자를 검사합니다.
서버는 상태가 없습니다: 화면이 history를 보내고, assistant 턴마다 서버가 준 context를 붙여 되돌려 줍니다.

이 모듈은 service를 import하지 않습니다. service.chat이 {도구 이름: 함수} dict를 run()에 넘깁니다.
설계: docs/design/2026-10-11_에이전트-대화-설계.md
"""
import json
import re

from aniwhere.agent.llm import prompt

MAX_TOOL_CALLS = 3                   # LLM이 낸 tool_call 개수. 실행·실패·모르는 도구 모두 센다
MAX_LLM_CALLS = MAX_TOOL_CALLS + 1
NEED_LLM = "에이전트 대화에는 LLM이 필요해요. .env에 OPENAI_API_KEY를 넣어 주세요."
NO_ANSWER = "지금은 답을 만들지 못했어요. 다시 한번 말해 주세요."
# 시즌 안 회차 표기: "3기 11화", "시즌 3 11화", "season 2", "2쿨". 전체 기준 회차만 저장한다
SEASON_RE = re.compile(r"\d+\s*(기|시즌|season|쿨)|(시즌|season)\s*\d+", re.IGNORECASE)

# 도구 이름 → 화면 문구 (말줄임표 없음, 화면이 …를 붙임)
LABELS = {
    "search_series": "작품 찾는 중",
    "list_records": "시청 기록 확인 중",
    "get_record": "시청 기록 확인 중",
    "save_record": "시청 기록 저장 중",
    "find": "장면으로 작품·회차 찾는 중",
    "review": "본 회차까지 복습 준비 중",
    "dictionary": "인물·용어 찾는 중",
    "where_to_watch": "시청처 확인 중",
    "recommend": "취향 분석 중",
}


def _tool(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": list(required)}}}


SERIES_ID = {"type": "string", "description": "작품 ID(tmdb:숫자). search_series 결과나 [직전 결과] 줄에서만 가져온다"}

# 손으로 적은 OpenAI 도구 스키마. 설명이 LLM의 선택을 좌우하므로 자동 생성하지 않는다.
# review·dictionary에 seen_ep가 없는 것은 일부러다: 스포일러 범위는 기록장 값만 쓴다.
TOOLS = [
    _tool("search_series",
          "작품 이름(한국어·영어, 일부만도 됨)으로 서비스가 지원하는 작품을 찾는다. series_id가 필요한 다른 도구보다 먼저 부른다. "
          "→ items[{series_id, name, title, total_episodes}]. 비어 있으면 지원하지 않는 작품이다.",
          {"query": {"type": "string", "description": "사용자가 말한 작품 이름 또는 그 일부"}}, ["query"]),
    _tool("list_records", "사용자의 시청 기록 전체(작품·본 회차·평점). '내 기록'을 물을 때. → items[{series_id, name, seen_ep, rating}]"),
    _tool("get_record", "한 작품의 시청 기록(몇 화까지 봤는지). 기록이 없으면 record: null.", {"series_id": SERIES_ID}, ["series_id"]),
    _tool("save_record",
          "사용자가 'N화까지 봤어'처럼 봤다고 단정했을 때 그 회차를 기록장에 저장한다(덮어쓰기). 확인을 묻지 않고 바로 저장한다. "
          "series_id는 search_series 결과나 [직전 결과] 줄의 것만. seen_ep는 사용자가 말한 전체 기준 회차 숫자 그대로. "
          "부정·미래·가정·질문형이면 부르지 않는다. 한 턴에 한 작품만.",
          {"series_id": SERIES_ID,
           "seen_ep": {"type": "integer", "description": "사용자가 말한 회차 숫자(전체 기준). 시즌 안 회차면 부르지 말고 전체 기준을 묻는다"},
           "rating": {"type": "number", "description": "0.5~5. 사용자가 '4점'처럼 점수를 숫자로 말했을 때만"}},
          ["series_id", "seen_ep"]),
    _tool("find",
          "사용자가 기억나는 장면·인물 묘사로 어느 작품 몇 화인지 찾는다. 사용자의 원문이 그대로 쓰이므로 인자가 없다. "
          "→ {status: episode|series|ambiguous|none, answer, candidates[{series_id, title, abs_ep?}], follow_up?}"),
    _tool("review",
          "기록장에 저장된 본 회차까지의 내용을 복습한다(그 뒤 내용은 절대 포함되지 않는다). 기록이 없으면 follow_up으로 어디까지 봤는지 묻는다. "
          "회차를 지정할 수 없다. → {answer, seen_ep, sources[], follow_up?}",
          {"series_id": SERIES_ID,
           "mode": {"type": "string", "enum": ["summary", "characters", "last", "ask"],
                    "description": "summary 전체 요약 / characters 인물 관계 / last 마지막 화 상황 / ask 직접 질문"},
           "question": {"type": "string", "description": "mode가 ask일 때 사용자의 질문 원문"}},
          ["series_id", "mode"]),
    _tool("dictionary",
          "기록장의 본 회차까지 등장한 인물·용어 사전. '누구야', '그 용어 뭐야', '인물·용어'. 기록이 없으면 follow_up으로 묻는다. "
          "→ {seen_ep, entries[{kind, name, text, first_ep}], follow_up?}",
          {"series_id": SERIES_ID}, ["series_id"]),
    _tool("where_to_watch", "작품을 볼 수 있는 OTT 시청처. '어디서 봐'. → {series_id, title, seasons[{name, providers[]}]}",
          {"series_id": SERIES_ID}, ["series_id"]),
    _tool("recommend", "사용자의 취향(좋아한 작품·분위기)으로 볼 작품을 추천한다. '뭐 볼까', '추천'. → {mood, picks[{series_id, title, reason}]}",
          {"likes": {"type": "string", "description": "사용자가 말한 취향·좋아한 작품을 그대로"}}, ["likes"]),
]
SCHEMAS = {t["function"]["name"]: t["function"]["parameters"] for t in TOOLS}


def as_result(value) -> dict:
    """도구 함수의 반환값을 JSON 객체 하나로. dict는 그대로, list는 items, None은 record: null."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"items": value}
    if value is None:
        return {"record": None}
    return {"value": value}


def slim(result: dict) -> dict:
    """LLM에 보내는 결과: sources의 본문(text)과 debug를 뺀다 (비용·지연). 화면용 results는 그대로."""
    out = {k: v for k, v in result.items() if k != "debug"}
    if isinstance(out.get("sources"), list):
        out["sources"] = [{k: v for k, v in s.items() if k != "text"} if isinstance(s, dict) else s for s in out["sources"]]
    return out


def save_with_previous(fns, series_id, seen_ep, rating=None) -> dict:
    """이전 기록을 먼저 읽고 저장. → 저장 결과 + previous_seen_ep, previous_rating (되돌릴 수 있게 답에 적는다)."""
    previous = fns["get_record"](series_id=series_id)
    saved = fns["save_record"](series_id=series_id, seen_ep=seen_ep, rating=rating)
    return dict(saved, previous_seen_ep=previous["seen_ep"] if previous else None,
                previous_rating=previous["rating"] if previous else None)


def confirmation(saved: dict) -> str:
    """저장 확인 문장. LLM이 '저장했어요'라고 말해도 실제 저장은 이 문장이 있을 때만이다."""
    text = f"「{saved['name']}」 {saved['seen_ep']}화까지로 저장했어요."
    if saved.get("previous_seen_ep") is not None:
        text += f" (이전 {saved['previous_seen_ep']}화)"
    return text


def find_history(history: list[dict]) -> list[dict]:
    """find에 넘길 history: 마지막 assistant 턴이 find 결과였을 때만 전체, 아니면 []
    (agent/find.py는 user 턴을 모두 단서로 이어 붙이므로 찾기와 무관한 대화가 섞이면 틀어진다)."""
    last = next((t for t in reversed(history) if t.get("role") == "assistant"), None)
    return list(history) if last and (last.get("context") or {}).get("tool") == "find" else []


def context_of(tool: str, args: dict, result: dict, title: str | None = None) -> dict:
    """응답의 context: 마지막으로 성공한 도구 기준 {tool, series_id?, title?, seen_ep?}. 값의 출처는 설계 문서 표.
    title은 review·dictionary·where_to_watch처럼 결과에 제목이 없는 도구를 위해 밖에서 찾아 넘긴다."""
    ctx = {"tool": tool}

    def put(series_id=None, title=None, seen_ep=None):
        if series_id:
            ctx["series_id"] = series_id
        if title:
            ctx["title"] = title
        if seen_ep is not None:
            ctx["seen_ep"] = seen_ep

    if tool == "find":
        first = (result.get("candidates") or [None])[0]
        if first and result.get("status") in ("episode", "series"):
            put(first.get("series_id"), first.get("title"),
                first.get("abs_ep") if result["status"] == "episode" else None)
    elif tool in ("save_record", "get_record"):
        if result.get("series_id"):
            put(result["series_id"], result.get("name"), result.get("seen_ep"))
    elif tool in ("review", "dictionary", "where_to_watch"):
        put(args.get("series_id"), title or result.get("title"), result.get("seen_ep"))
    elif tool == "search_series":
        items = result.get("items") or []
        if len(items) == 1:
            put(items[0].get("series_id"), items[0].get("name") or items[0].get("title"))
    elif tool == "recommend":
        picks = result.get("picks") or []
        if picks:
            put(picks[0].get("series_id"), picks[0].get("title"))
    return ctx


def suggest(tool: str, result: dict, context: dict | None) -> list[dict]:
    """다음 행동 칩 [{label, message}]. message는 상태 없는 서버가 그대로 받아도 동작하는 완전한 문장.
    마지막으로 성공한 도구 기준의 규칙. 되묻는 중(follow_up)이면 []. {제목}이 없으면 그 칩을 뺀다."""
    if not result or not context or result.get("follow_up"):
        return []
    title, seen_ep = context.get("title"), context.get("seen_ep")
    chips = {
        "seen": ("여기까지 봤어요", f"{title} {seen_ep}화까지 봤어" if title and seen_ep is not None else None),
        "watch": ("시청처 보기", f"{title} 어디서 볼 수 있어?" if title else None),
        "dict": ("인물·용어", f"{title} 인물·용어 알려줘" if title else None),
        "review": ("3분 복습", f"{title} 지금까지 복습해줘" if title else None),
        "more": ("다른 추천", "다른 작품도 추천해줘"),
    }
    if tool == "find":
        order = {"episode": ["seen", "watch"], "series": ["watch", "dict"]}.get(result.get("status"), [])
    elif tool == "recommend":
        order = ["watch", "more"] if result.get("picks") else []
    else:
        order = {"save_record": ["review", "dict"], "review": ["dict", "watch"],
                 "dictionary": ["review", "watch"], "where_to_watch": ["review", "dict"]}.get(tool, [])
    return [{"label": chips[k][0], "message": chips[k][1]} for k in order if chips[k][1]]


# ───────────────────────── 루프 ─────────────────────────

def _context_line(ctx: dict) -> str:
    parts = [f"tool={ctx['tool']}"]
    if ctx.get("series_id"):
        parts.append(f"series_id={ctx['series_id']}")
    if ctx.get("title"):
        parts.append(f"제목={ctx['title']}")
    if ctx.get("seen_ep") is not None:
        parts.append(f"회차={ctx['seen_ep']}")
    return "[직전 결과: " + ", ".join(parts) + "]"


def _messages(history: list[dict], message: str) -> list[dict]:
    """OpenAI messages. assistant 턴에 context가 있으면 끝에 [직전 결과: …] 한 줄을 붙여 LLM이 작품·회차를 잇게 한다."""
    out = []
    for turn in history:
        role = "user" if turn.get("role") == "user" else "assistant"
        content = turn.get("content") or ""
        ctx = turn.get("context") if role == "assistant" else None
        if isinstance(ctx, dict) and ctx.get("tool"):
            content += "\n" + _context_line(ctx)
        out.append({"role": role, "content": content})
    out.append({"role": "user", "content": message})
    return out


def _title(series_id, results: dict, fns: dict):
    """이번 턴 결과에서 제목을 찾고, 없으면 fns["series"]로 조회 (title_ko, 없으면 title)."""
    for name in ("save_record", "get_record", "where_to_watch"):
        r = results.get(name) or {}
        if r.get("series_id") == series_id and (r.get("name") or r.get("title")):
            return r.get("name") or r.get("title")
    for item in (results.get("search_series") or {}).get("items") or []:
        if item.get("series_id") == series_id and (item.get("name") or item.get("title")):
            return item.get("name") or item.get("title")
    for c in (results.get("find") or {}).get("candidates") or []:
        if c.get("series_id") == series_id and c.get("title"):
            return c["title"]
    info = fns["series"](series_id) if series_id and "series" in fns else None
    return (info.get("title_ko") or info.get("title")) if info else None


def _norm(text) -> str:
    """띄어쓰기·기호·대소문자를 무시하고 비교하기 위한 꼴 ("테스트칼날" == "테스트 칼날", "TestBlade" == "Test Blade")."""
    return re.sub(r"[\W_]+", "", text or "").lower()


def _mentioned(item: dict, message: str) -> bool:
    low = _norm(message)
    return any(_norm(n) and _norm(n) in low for n in (item.get("name"), item.get("title")) if n)


def _episode_numbers(text: str) -> list[str]:
    """저장할 수 있는 회차 숫자. "N화까지"가 있으면 그 숫자들만("7화까지 봤는데 8화 내용"의 8은 질문), 없으면 글의 모든 숫자."""
    anchored = re.findall(r"(\d+)\s*화?\s*까지", text)
    return anchored or re.findall(r"\d+", text)


def _rating_said(rating, message: str) -> bool:
    """rating은 사용자가 '4점'·'4.5점'·'별 4개'처럼 숫자를 점·별 바로 옆에 말했을 때만 인정 ("별로였어", "11화"의 1은 아님)."""
    if rating is None or isinstance(rating, bool) or not isinstance(rating, (int, float)):
        return False
    forms = {str(rating)}
    if float(rating).is_integer():
        forms.add(str(int(rating)))
    return any(re.search(rf"(?<![\d.]){re.escape(n)}\s*점|별\s*{re.escape(n)}(?![\d.])", message) for n in forms)


class _Turn:
    """한 턴의 상태: 실행한 단계·결과, 저장 보호에 쓰는 series_id 출처."""

    def __init__(self, message, history, fns):
        self.message, self.history, self.fns = message, history, fns
        self.steps, self.results = [], {}
        self.last = None                 # (tool, args, result) 마지막으로 성공한 도구
        self.saved = None                # save_record 성공 결과
        self.follow_up = None
        contexts = [t.get("context") or {} for t in history if t.get("role") == "assistant"]
        self.known_ids = {c["series_id"] for c in contexts if isinstance(c, dict) and c.get("series_id")}
        self.direct_ids = set(self.known_ids)      # find·get_record·list_records·context에서 온 id: 후보 모호 검사를 건너뜀
        self.search_items = []                     # 이번 턴 search_series 결과

    def _clarified_text(self):
        """직전 턴이 작품을 되물은 상태(마지막 assistant 턴에 성공한 도구가 없거나 search_series에서 끝남)면
        그 앞 user 턴의 글. "테스트 7화까지 봤어" → "어느 작품인가요?" → "테스트 칼날"에서 7을 이어 쓰기 위해."""
        turns = self.history
        for i in range(len(turns) - 1, -1, -1):
            if turns[i].get("role") == "assistant":
                ctx = turns[i].get("context") or {}
                if ctx.get("tool") not in (None, "search_series"):
                    return None
                return next((t.get("content") or "" for t in reversed(turns[:i]) if t.get("role") == "user"), None)
        return None

    def _fail(self, name, args, error):
        self.steps.append({"tool": name, "label": LABELS[name], "ok": False, "args": args})
        return {"error": error}

    def _remember(self, name, result):
        if name == "search_series":
            self.search_items = [i for i in result.get("items") or [] if isinstance(i, dict)]
            self.known_ids |= {i["series_id"] for i in self.search_items if i.get("series_id")}
            return
        if name == "find":
            ids = {c["series_id"] for c in result.get("candidates") or [] if c.get("series_id")}
        elif name == "list_records":
            ids = {r["series_id"] for r in result.get("items") or [] if isinstance(r, dict) and r.get("series_id")}
        elif name in ("get_record", "save_record") and result.get("series_id"):
            ids = {result["series_id"]}
        else:
            return
        self.known_ids |= ids
        self.direct_ids |= ids

    def _check_save(self, args):
        """save_record 보호. 통과하면 None, 걸리면 LLM에 돌려줄 오류 글. rating은 조건이 안 맞으면 None으로 바꿈."""
        sid, seen_ep = args["series_id"], args["seen_ep"]
        if isinstance(seen_ep, str) and seen_ep.isdigit():
            seen_ep = args["seen_ep"] = int(seen_ep)
        if self.saved is not None:
            return "한 턴에 한 작품만 저장해요. 나머지는 다음에 말해 달라고 하세요"
        if sid not in self.known_ids:
            return "series_id는 search_series 결과나 직전 결과에서 가져오세요"
        if len(self.search_items) >= 2 and sid not in self.direct_ids:
            item = next((i for i in self.search_items if i.get("series_id") == sid), None)
            if item is not None and not _mentioned(item, self.message):
                return "후보가 여러 개입니다. 어느 작품인지 사용자에게 물으세요"
        if str(seen_ep) not in _episode_numbers(self.message):
            previous = self._clarified_text()
            if previous is None or str(seen_ep) not in _episode_numbers(previous):
                return "사용자가 말한 회차 숫자만 저장할 수 있어요"
        if SEASON_RE.search(self.message):
            return "시즌 안 회차는 저장하지 않아요. 전체 기준으로 몇 화인지 물으세요"
        args["rating"] = args.get("rating") if _rating_said(args.get("rating"), self.message) else None
        return None

    def call(self, name, raw_args):
        if name not in SCHEMAS:
            return {"error": f"없는 도구입니다: {name}"}
        schema = SCHEMAS[name]
        raw_args = raw_args if isinstance(raw_args, dict) else {}
        args = {k: v for k, v in raw_args.items() if k in schema["properties"]}
        missing = [k for k in schema["required"] if k not in args]
        if missing:
            return self._fail(name, args, f"{missing[0]}가 필요합니다")
        if name == "save_record":
            error = self._check_save(args)
            if error:
                return self._fail(name, args, error)
        try:
            if name == "find":
                value = self.fns["find"](self.message, find_history(self.history))
            elif name == "save_record":
                value = save_with_previous(self.fns, args["series_id"], args["seen_ep"], args.get("rating"))
            else:
                value = self.fns[name](**args)
        except ValueError as e:              # 모르는 작품(UnknownSeries), 회차·평점 범위 밖, 잘못된 mode
            return self._fail(name, args, str(e))
        result = as_result(value)
        self.steps.append({"tool": name, "label": LABELS[name], "ok": True, "args": args})
        self.results[name] = result
        self.last = (name, args, result)
        self._remember(name, result)
        if name == "save_record":
            self.saved = result
        if result.get("follow_up"):
            self.follow_up = result["follow_up"]
        return result

    def reply(self, content):
        answer = self.follow_up or (content or "").strip() or NO_ANSWER
        if self.saved is not None:
            answer = f"{confirmation(self.saved)} {answer}".strip()
        context, suggestions = None, []
        if self.last:
            tool, args, result = self.last
            title = _title(args.get("series_id"), self.results, self.fns) if tool in ("review", "dictionary", "where_to_watch") else None
            context = context_of(tool, args, result, title)
            suggestions = suggest(tool, result, context)
        return {"answer": answer, "follow_up": self.follow_up, "steps": self.steps, "results": self.results,
                "suggestions": suggestions, "context": context}


def run(llm, message: str, history: list[dict], fns: dict) -> dict:
    """→ {answer, follow_up?, steps[{tool, label, ok, args}], results{}, suggestions[{label, message}], context?}

    fns: {도구 이름: service 함수} + "series"(제목 조회용, LLM에는 보이지 않음). llm이 None이면 도구를 돌리지 않는다."""
    if llm is None:
        return {"answer": NEED_LLM, "follow_up": NEED_LLM, "steps": [], "results": {}, "suggestions": [], "context": None}
    turn = _Turn(message, history or [], fns)
    messages = _messages(turn.history, message)
    n_tools = n_llm = 0
    content = None
    while True:
        allow = n_tools < MAX_TOOL_CALLS and n_llm < MAX_LLM_CALLS - 1
        reply = llm.tools(prompt("chat"), messages, TOOLS, allow_tools=allow)
        n_llm += 1
        content = reply.get("content")
        calls = reply.get("tool_calls") or []
        if not calls or not allow:                 # 글만 왔거나, 도구를 막은 마지막 호출
            break
        messages.append(reply["raw"])              # assistant(tool_calls)를 먼저 붙이고, 모든 id에 tool 메시지를 하나씩
        for c in calls:
            n_tools += 1
            if turn.follow_up:
                result = {"error": "되묻는 중이라 실행하지 않았습니다"}
            elif n_tools > MAX_TOOL_CALLS:
                result = {"error": f"이번 턴의 도구 호출 한도({MAX_TOOL_CALLS}번)를 넘었습니다. 지금까지의 결과로 답하세요."}
            else:
                result = turn.call(c.get("name"), c.get("arguments"))
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(slim(result), ensure_ascii=False)})
        if turn.follow_up:                         # 되묻는 글은 원문 그대로 사용자에게. LLM을 다시 부르지 않음
            break
    return turn.reply(content)
