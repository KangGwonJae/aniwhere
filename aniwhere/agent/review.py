"""04 이어보기 — 맞춤 복습(09). 본 회차까지만 근거로 삼습니다.

도구 선택: 전체 요약·인물 관계·마지막 화 상황은 "몇 화부터 몇 화까지"가 정해져 있어 조건 검색으로 읽고,
직접 질문만 벡터 검색을 씁니다. 어느 쪽이든 본 회차 이후 청크는 retrieval이 읽기 전에 제외합니다.
"""
from aniwhere import records
from aniwhere.agent.llm import prompt
from aniwhere.config import section
from aniwhere.retrieval import catalog
from aniwhere.retrieval.embedder import embed_query
from aniwhere.retrieval.search import chunks_upto, search_chunks

MODES = {"summary": "전체 요약", "characters": "인물 관계", "last": "마지막 화 상황", "ask": "직접 질문"}
_ALIASES = {"요약": "summary", "전체 요약": "summary", "인물": "characters", "인물 관계": "characters",
            "마지막 화": "last", "마지막 화 상황": "last", "직접": "ask", "직접 질문": "ask"}
ASK_SEEN = "어디까지 봤어요? 마지막으로 본 회차를 알려 주세요."


def _by_episode(chunks, prefer):
    """회차마다 청크 하나: prefer 종류가 있으면 그것, 없으면 다른 종류."""
    best = {}
    for c in chunks:
        if c["abs_ep"] not in best or (c["type"] == prefer and best[c["abs_ep"]]["type"] != prefer):
            best[c["abs_ep"]] = c
    return [best[n] for n in sorted(best)]


def _context(db, series_id, seen_ep, mode, question, budget):
    """[(청크, LLM에 보여 줄 글자 수)]"""
    if mode == "ask":
        hits = search_chunks(db, embed_query(question), watched={series_id: seen_ep}, series_id=series_id)
        hits = sorted(hits, key=lambda c: c["abs_ep"] or 0)
        return [(c, budget // max(len(hits), 1)) for c in hits]
    if mode == "last":
        # 마지막으로 본 화는 상세 줄거리 통째로, 바로 앞 두 화는 짧은 요약으로 (어떤 흐름에서 이어졌는지)
        chunks = _by_episode(chunks_upto(db, series_id, seen_ep=seen_ep, from_ep=max(1, seen_ep - 2),
                                         types=["episode", "plot"]), "episode")
        last = chunks_upto(db, series_id, seen_ep=seen_ep, from_ep=seen_ep, types=["plot"])
        chunks = [c for c in chunks if c["abs_ep"] != seen_ep or not last] + last
        return [(c, budget if c["type"] == "plot" else 1500) for c in chunks]
    # 전체 요약·인물 관계: 1화부터 본 회차까지. 상세 줄거리가 다 들어가면 상세 줄거리로, 넘치면 짧은 회차 요약으로
    # 바꾸고 그래도 넘치면 회차당 글자 수를 줄여 전체를 고르게 담음.
    # (위키의 회차별 등장인물 목록은 쓰지 않음: 뒤에서 밝혀지는 정체가 이름에 그대로 적혀 있음)
    rows = chunks_upto(db, series_id, seen_ep=seen_ep, types=["episode", "plot"])
    fits = sum(len(c["text"]) for c in rows if c["type"] == "plot") <= budget
    chunks = _by_episode(rows, "plot" if fits else "episode")
    return [(c, max(200, budget // max(len(chunks), 1))) for c in chunks]


def review(db, series_id, seen_ep=None, mode="summary", question=None, *, llm=None,
           user_id=records.LOCAL_USER) -> dict:
    mode = _ALIASES.get(mode, mode)
    if mode not in MODES:
        raise ValueError(f"mode는 {list(MODES)} 중 하나여야 합니다: {mode!r}")
    info = catalog.series_info(db, series_id)
    if not info:
        raise ValueError(f"모르는 작품입니다: {series_id}")
    if seen_ep is None:                                  # 기록장의 진행 회차가 복습 범위를 정함
        record = records.get(db, series_id, user_id=user_id)
        seen_ep = record["seen_ep"] if record else None
    if seen_ep is None:                                  # 본 회차를 모르면 검색하지 않고 되물음
        return {"answer": None, "seen_ep": None, "sources": [], "follow_up": ASK_SEEN}
    seen_ep = min(int(seen_ep), info["total_episodes"] or int(seen_ep))
    if seen_ep <= 0:
        return {"answer": f"아직 「{info['name']}」을(를) 보기 전이라 복습할 내용이 없어요.", "seen_ep": 0,
                "sources": [], "follow_up": None}
    if mode == "ask" and not (question or "").strip():
        return {"answer": None, "seen_ep": seen_ep, "sources": [], "follow_up": "무엇이 궁금한지 알려 주세요."}

    cfg = section("review")
    context = _context(db, series_id, seen_ep, mode, question, cfg.get("max_context_chars", 60000))
    # 검색이 이미 걸렀지만, 답을 만들기 직전에 한 번 더 확인 (여기서 걸리면 검색 쪽 버그)
    assert all(c["abs_ep"] is None or c["abs_ep"] <= seen_ep for c, _ in context), "본 회차 이후 청크가 섞였습니다"
    sources = [{"n": i, "text": c["text"][:cfg.get("source_chars", 400)], "abs_ep": c["abs_ep"],
                "url": (c["sources"] or [{}])[0].get("url"), "license": (c["sources"] or [{}])[0].get("license"),
                "name": (c["sources"] or [{}])[0].get("name")} for i, (c, _) in enumerate(context, 1)]
    if not context:
        return {"answer": "본 회차까지의 자료에서는 확인할 수 없어요.", "seen_ep": seen_ep, "sources": [],
                "follow_up": None}
    if not llm:
        shown = context[-3:] if mode != "ask" else context
        return {"answer": "LLM 키가 없어 본 회차까지의 근거만 보여 드려요.\n\n" + "\n\n".join(
            c["text"][:600] for c, _ in shown), "seen_ep": seen_ep, "sources": sources, "follow_up": None}
    asked = MODES[mode] + (f"\n질문: {question.strip()}" if mode == "ask" else "")
    user = (f"작품: {info['name']}\n사용자가 본 회차: 전체 {seen_ep}화까지\n요청: {asked}\n"
            + "\n참고자료:\n"
            + "\n\n".join(f"[{i}] {c['text'][:limit]}" for i, (c, limit) in enumerate(context, 1)))
    return {"answer": llm.text(prompt("review"), user), "seen_ep": seen_ep, "sources": sources, "follow_up": None}
