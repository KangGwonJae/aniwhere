"""02 탐색 — 기억으로 작품 찾기(05)·회차 찾기(06).

흐름: 단서 추출(LLM) → 작품 후보(제목 언급·짐작·전체 벡터 검색) → 후보 작품 안에서 회차 재검색(벡터 + 키워드)
→ 판정(LLM이 검색된 줄거리만 보고 맞는지 판단). 후보가 비슷하면 다시 묻고, 근거가 약하면 단정하지 않습니다.

스포일러: 기록장에 있는 작품은 본 회차까지만 검색합니다. 기록이 없는 작품은 사용자가 이미 본 장면을 묻는 것이므로
전체 회차를 검색하되, 응답에는 작품명과 회차 번호·제목만 넣고 줄거리 본문은 넣지 않습니다.
"""
import re

from aniwhere import records
from aniwhere.agent.llm import prompt
from aniwhere.config import section
from aniwhere.retrieval import catalog
from aniwhere.retrieval.embedder import embed_query
from aniwhere.retrieval.search import ALL_EPISODES, chunks_upto, keyword_search, search_chunks

RRF_K = 60                      # 여러 검색 결과의 순위를 합칠 때 쓰는 상수 (Reciprocal Rank Fusion)
PROFILE_TYPES = ["character", "terminology", "summary"]    # 인물 생김새·설정은 줄거리가 아니라 여기에 적혀 있음
KEYWORD_TYPES = ["event"] + PROFILE_TYPES
ASK_MORE = "기억나는 인물의 생김새나 이름, 장소, 그 장면 앞뒤에 있었던 일을 조금 더 알려 주세요."
QUOTE_MATCH = 0.7              # 근거 문장의 낱말 가운데 이만큼이 자료의 이어진 두 문장 안에 있어야 인정
NOT_FOUND = "지금 단서로는 찾지 못했어요."


def _clues(llm, question, history):
    if not llm:
        return {}
    turns = [f"{'사용자' if m.get('role') == 'user' else 'AniWhere'}: {m.get('content', '')}" for m in history]
    c = llm.json(prompt("find_clues"), "\n".join(turns + [f"사용자: {question}"]))
    strings = lambda v: [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []
    return {"series_title": c.get("series_title") if isinstance(c.get("series_title"), str) else None,
            "title_guesses": strings(c.get("title_guesses"))[:3], "names": strings(c.get("names"))[:6],
            "query_en": c.get("query_en") if isinstance(c.get("query_en"), str) else None,
            "keywords": strings(c.get("keywords"))[:8]}


def _rank_series(hit_lists):
    score = {}
    for hits in hit_lists:
        for rank, h in enumerate(hits):
            score[h["series_id"]] = score.get(h["series_id"], 0) + 1 / (RRF_K + rank)
    return sorted(score, key=score.get, reverse=True)


def _episodes(dense_lists, keyword_hits):
    """검색 결과 여러 벌을 (작품, 회차) 단위로 합침 → rrf 높은 순. 회차마다 줄거리 청크 하나와 벡터 유사도를 남김."""
    eps = {}

    def add(key, rank, chunk, score=None, weight=1):
        e = eps.setdefault(key, {"series_id": key[0], "abs_ep": key[1], "rrf": 0.0, "score": None, "chunk": chunk,
                                 "scenes": []})
        e["rrf"] += weight / (RRF_K + rank)
        if score is not None:
            e["score"] = max(e["score"] or 0, score)
        return e

    for hits in dense_lists:
        for rank, h in enumerate(h for h in hits if h["abs_ep"]):
            add((h["series_id"], h["abs_ep"]), rank, h, h["score"])["chunk"] = h
    seen = []
    for h in keyword_hits:
        if h["type"] != "event":
            continue
        key = (h["series_id"], h["abs_ep"])
        if key not in seen:
            seen.append(key)
            # 벡터 검색은 질문 수만큼 벌이 있으므로, 키워드 검색 한 벌이 묻히지 않게 같은 무게를 줌
            add(key, len(seen) - 1, h, weight=max(len(dense_lists), 1))
        eps[key]["scenes"].append(h)
    return sorted(eps.values(), key=lambda e: (e["rrf"], len(e["scenes"]), e["score"] or 0), reverse=True)


def _evidence(db, eps, watched, limit):
    """후보 회차마다 LLM에게 보여 줄 글: 그 회차의 상세 줄거리. 키워드로 맞은 장면이 있으면 그 장면을 앞에 둠.

    어떤 검색으로 찾았든(벡터·키워드) 같은 글을 보여 주려고 줄거리를 다시 읽습니다. 본 회차 조건은 그대로 적용됩니다.
    """
    plots = {}
    for sid in {e["series_id"] for e in eps}:
        rows = chunks_upto(db, sid, seen_ep=watched.get(sid, ALL_EPISODES), types=["plot"],
                           only_eps=[e["abs_ep"] for e in eps if e["series_id"] == sid])
        plots.update({(sid, c["abs_ep"]): c for c in rows})
    out = []
    for e in eps:
        plot = plots.get((e["series_id"], e["abs_ep"]))
        scenes = "\n".join(s["text"] for s in e["scenes"][:2])
        text = "\n".join(x for x in (scenes, plot["text"][:limit] if plot else "") if x)
        out.append((text, plot or e["chunk"]))
    return out


def _words(text):
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def _quoted(quote, text):
    """LLM이 근거로 든 문장이 자료에 실제로 있는지: 이어진 두 문장 안에 그 문장의 낱말이 대부분 들어 있어야 함.

    LLM이 문장을 조금 줄여 옮기는 일이 있어 글자 그대로 비교하지 않습니다.
    """
    want = _words(quote) if isinstance(quote, str) else set()
    if len(want) < 4:
        return False
    sents = [_words(s) for s in re.split(r"(?<=[.!?])\s+|\n+", text)]
    return any(len(want & (a | b)) >= QUOTE_MATCH * len(want) for a, b in zip(sents, sents[1:] + [set()]))


def _grounded(j, text):
    """회차를 단정해도 되는지를 LLM의 말이 아니라 자료로 확인. → (되는지, 자료에서 확인 못 한 단서)"""
    missing = [m for m in j.get("missing") or [] if isinstance(m, str)] if isinstance(j.get("missing"), list) else []
    told = [c for c in j.get("clues") or [] if isinstance(c, str)] if isinstance(j.get("clues"), list) else []
    ok = _quoted(j.get("quote"), text) and len(missing) * 3 <= max(len(told), 3)
    return ok, missing


def find(db, question, history=None, *, llm=None, user_id=records.LOCAL_USER) -> dict:
    cfg = section("find")
    history = history or []
    said = " ".join([m.get("content", "") for m in history if m.get("role") == "user"] + [question]).strip()
    if not said:
        return _result("none", "어떤 장면이 기억나는지 알려 주세요.", follow_up=ASK_MORE)
    clues = _clues(llm, question, history)
    watched = records.watched_map(db, user_id=user_id)
    queries = [said] + ([clues["query_en"]] if clues.get("query_en") else [])
    vectors = [embed_query(q) for q in queries]
    scope = dict(watched=watched, unrecorded=ALL_EPISODES)
    terms = clues.get("names", []) + clues.get("keywords", []) + ([clues["query_en"]] if clues.get("query_en") else [])

    # 1단계: 작품 후보. 사용자가 제목을 말했으면 그 작품만, 아니면 LLM의 짐작 + 전체 검색에서 많이 잡힌 작품
    named = catalog.mentioned_series(db, said) or \
        (catalog.find_series(db, clues["series_title"], limit=1) if clues.get("series_title") else [])
    if named:
        series_ids, global_lists = named[:1], []
    else:
        global_lists = [search_chunks(db, v, k=cfg.get("pool", 30), **scope) for v in vectors]
        # 장면이 아니라 인물·설정을 묘사한 경우: 전체 작품의 캐릭터·용어·작품 소개에서 낱말로 찾음
        profiles = keyword_search(db, terms, series_ids=None, types=PROFILE_TYPES, k=cfg.get("pool", 30), **scope)
        guessed = [sid for t in clues.get("title_guesses", []) for sid in catalog.find_series(db, t, limit=1)]
        found = _rank_series(global_lists + [profiles] * len(global_lists))
        series_ids = list(dict.fromkeys(guessed + found))[:cfg.get("max_series", 4)]
    if not series_ids:
        return _result("none", "지금 단서로는 찾지 못했어요.", follow_up=ASK_MORE, clues=clues)

    # 2단계: 후보 작품 안에서 회차 재검색. 질문마다 작품별 결과를 유사도 순으로 합쳐 한 벌로 만듦
    dense = [sorted((h for sid in series_ids for h in search_chunks(db, v, series_id=sid, k=10, **scope)),
                    key=lambda h: h["score"], reverse=True) for v in vectors]
    words = keyword_search(db, terms, series_ids=series_ids, types=["event"], k=30, **scope)
    eps = _episodes(dense, words)
    # 인물·용어·작품 소개: 몇 화인지는 못 정해도 어느 작품인지를 뒷받침하는 근거. 작품마다 가장 잘 맞은 것 두 개씩
    extras = [h for sid in series_ids for h in keyword_search(db, terms, series_ids=[sid], types=PROFILE_TYPES, k=2,
                                                              **scope)]
    names = {sid: catalog.series_info(db, sid)["name"] for sid in series_ids}
    labels = {sid: catalog.episodes(db, sid, [e["abs_ep"] for e in eps if e["series_id"] == sid])
              for sid in series_ids}

    def cand(e):
        ep = labels[e["series_id"]].get(e["abs_ep"], {})
        return {"series_id": e["series_id"], "title": names[e["series_id"]], "abs_ep": e["abs_ep"],
                "label": ep.get("label", f"(전체 {e['abs_ep']}화)"), "score": e["score"]}

    limited = {sid: watched[sid] for sid in series_ids if sid in watched}
    out = dict(clues=clues, eps=eps, names=names, limited=limited)
    if not eps and not extras:
        return _result("none", "지금 단서로는 찾지 못했어요.", follow_up=ASK_MORE, **out)

    if llm:
        shown = eps[:cfg.get("judge_chunks", 6)]
        texts = _evidence(db, shown, watched, cfg.get("judge_chunk_chars", 8000))
        items = [(cand(e), text, chunk) for e, (text, chunk) in zip(shown, texts)] + \
                [({"series_id": h["series_id"], "title": names[h["series_id"]]}, h["text"], h) for h in extras]
        j = llm.json(prompt("find_judge"), f"사용자의 묘사:\n{said}\n\n후보 자료:\n" + "\n\n".join(
            f"[{i}] {text}" for i, (_, text, _) in enumerate(items, 1)))
        valid = lambda n: isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(items)
        status, pick = j.get("status"), j.get("pick")
        also = [n for n in (j.get("also") or []) if valid(n) and n != pick] if isinstance(j.get("also"), list) else []
        reason = j.get("reason") if isinstance(j.get("reason"), str) else ""
        if status not in ("episode", "series", "ambiguous") or not valid(pick):
            return _result("none", NOT_FOUND, follow_up=j.get("follow_up") or ASK_MORE, **out)
        picked = [items[n - 1] for n in [pick] + also[:3]]
        if status == "episode" and "abs_ep" not in picked[0][0]:
            status = "series"                                   # 인물 설명만으로는 회차를 말할 수 없음
        # 회차를 단정하려면 그 장면이 적힌 문장이 실제로 자료에 있어야 하고, 빠진 단서가 없어야 함
        ok, missing = _grounded(j, picked[0][1]) if status == "episode" else (True, [])
        if not ok:
            return _result("none", NOT_FOUND, follow_up=ASK_MORE, **out)
        if missing:
            reason += " 다만 " + ", ".join(f"'{m}'" for m in missing) + " 부분은 줄거리에서 확인하지 못했어요."
        if status == "ambiguous":
            return _result("ambiguous", "비슷한 후보가 여러 개 있어요. " + reason, [c for c, _, _ in picked],
                           j.get("follow_up") or ASK_MORE, [ch for _, _, ch in picked], **out)
        first, _, chunk = picked[0]
        if status == "series":
            return _result("series", f"「{first['title']}」 같아요. 몇 화인지는 지금 단서만으로는 정하기 어려워요. "
                           + reason, [{"series_id": first["series_id"], "title": first["title"]}],
                           "어떤 장면이었는지 조금 더 알려 주시면 회차도 찾아볼게요.", [chunk], **out)
        return _result("episode", f"「{first['title']}」 {first['label']} 같아요. " + reason,
                       [c for c, _, _ in picked if "abs_ep" in c], None, [chunk], **out)

    # LLM이 없을 때: 벡터 유사도만으로 판단 (줄거리를 읽고 확인하지 못하므로 기준을 보수적으로)
    notice = "LLM 키가 없어 검색 점수만으로 판단했어요."
    eps = [e for e in eps if e["score"] is not None]
    if not eps or eps[0]["score"] < cfg.get("min_score", 0.5):
        return _result("none", "지금 단서로는 찾지 못했어요.", follow_up=ASK_MORE, notice=notice, **out)
    top = eps[0]
    head = [h["series_id"] for h in (global_lists[0][:5] if global_lists else [])]
    if not named and head.count(top["series_id"]) < 3:
        firsts = list({e["series_id"]: e for e in reversed(eps)}.values())      # 작품마다 가장 잘 맞은 회차
        firsts = sorted(firsts, key=lambda e: e["score"], reverse=True)[:3]
        return _result("ambiguous", "비슷한 작품이 여러 개 있어요: " + ", ".join(f"「{names[e['series_id']]}」" for e in firsts),
                       [{"series_id": e["series_id"], "title": names[e["series_id"]]} for e in firsts],
                       "혹시 이 중에 있나요? 작품 이름이나 " + ASK_MORE, [e["chunk"] for e in firsts],
                       notice=notice, **out)
    same = [e for e in eps if e["series_id"] == top["series_id"]]
    if len(same) > 1 and top["score"] - same[1]["score"] < cfg.get("margin", 0.02):
        cands = [cand(e) for e in same[:3]]
        return _result("ambiguous", f"「{names[top['series_id']]}」에서 비슷한 회차가 여러 개 있어요: "
                       + ", ".join(c["label"] for c in cands), cands, ASK_MORE, [e["chunk"] for e in same[:3]],
                       notice=notice, **out)
    c = cand(top)
    return _result("episode", f"「{c['title']}」 {c['label']} 같아요.", [c], None, [top["chunk"]], notice=notice, **out)


def _result(status, answer, candidates=(), follow_up=None, chunks=(), *, clues=None, eps=(), names=None, limited=None,
            notice=None):
    names, limited = names or {}, limited or {}
    shown = {c["series_id"] for c in candidates} or set(limited)
    notes = [f"기록장에 「{names.get(sid, sid)}」은(는) {n}화까지 본 것으로 되어 있어 그 범위에서만 찾았어요. "
             "더 보셨다면 기록장을 고쳐 주세요."
             for sid, n in limited.items() if sid in shown] + ([notice] if notice else [])
    return {
        "status": status,                       # episode / series / ambiguous / none
        "answer": " ".join([answer.strip()] + notes),
        "candidates": list(candidates),
        "follow_up": follow_up,
        # 근거 링크. 줄거리 본문은 넣지 않음 (아직 안 본 회차일 수 있음)
        "sources": [{"series_id": ch["series_id"], "abs_ep": ch["abs_ep"], **src}
                    for ch in chunks for src in (ch["sources"] or [])],
        "debug": {"clues": clues or {}, "ranked": [
            {"series_id": e["series_id"], "abs_ep": e["abs_ep"], "score": e["score"], "rrf": round(e["rrf"], 4)}
            for e in list(eps)[:10]]},
    }
