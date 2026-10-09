"""검색 품질 평가: eval/questions.jsonl의 질문으로 "정답 회차를 몇 번째에 찾는가"를 잽니다.

    make eval                                            # 벡터 검색만 (LLM 없음): 청크 종류별 비교
    .venv/bin/python eval/run.py --pipeline --label 이름   # 찾기 기능 전체 (LLM 포함): 맞게 답한 비율과 걸린 시간

벡터 검색 평가는 질문(한국어)을 그대로 임베딩해서 청크 종류별로 검색하고, 맞은 청크를 회차로 묶어 순위를 봅니다.
- 작품 안: 작품을 아는 상태에서 정답 회차가 1위 / 3위 안 / 8위 안에 있는 비율 (8 = LLM 판정에 보여 주는 후보 수)
- 전체: 작품을 모르는 상태에서 정답 작품이 1위인 비율, 정답 회차가 8위 안에 있는 비율
결과는 eval/results/날짜_이름.json에 저장합니다.
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aniwhere import service  # noqa: E402
from aniwhere.config import section  # noqa: E402
from aniwhere.retrieval.embedder import embed_query  # noqa: E402
from aniwhere.retrieval.search import ALL_EPISODES, search_chunks  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIGS = {"회차 통째(plot)": ["plot"], "장면(event)": ["event"], "회차 통째 + 장면": ["plot", "event"]}
SCOPE = dict(watched={}, unrecorded=ALL_EPISODES)       # 평가는 끝까지 본 사용자 기준


def episodes_in_order(hits):
    """검색된 청크를 (작품, 회차)로 묶어 처음 나온 순서대로."""
    return list(dict.fromkeys((h["series_id"], h["abs_ep"]) for h in hits if h["abs_ep"]))


def rank_of(found, wanted):
    return next((i for i, x in enumerate(found, 1) if x in wanted), None)


def retrieval(questions):
    db = service.db()
    vectors = {q["id"]: embed_query(q["question"]) for q in questions}
    table = {}
    for name, types in CONFIGS.items():
        rows = []
        for q in questions:
            gold = {(q["series_id"], ep) for ep in q["abs_eps"]}
            inside = episodes_in_order(search_chunks(db, vectors[q["id"]], series_id=q["series_id"], types=types,
                                                     k=60, **SCOPE))
            everywhere = episodes_in_order(search_chunks(db, vectors[q["id"]], types=types, k=60, **SCOPE))
            series = list(dict.fromkeys(s for s, _ in everywhere))
            rows.append({"id": q["id"], "style": q["style"], "source": q["source"],
                         "in_series": rank_of(inside, gold), "global": rank_of(everywhere, gold),
                         "series": rank_of(series, {q["series_id"]})})
        table[name] = rows
    return table


def share(rows, key, k):
    return sum(1 for r in rows if r[key] and r[key] <= k) / max(len(rows), 1)


def summarize(rows):
    return {"n": len(rows), "작품 안 1위": share(rows, "in_series", 1), "작품 안 3위 안": share(rows, "in_series", 3),
            "작품 안 8위 안": share(rows, "in_series", 8), "전체: 작품 1위": share(rows, "series", 1),
            "전체: 회차 8위 안": share(rows, "global", 8)}


def pipeline(questions):
    """찾기 기능 전체. 질문에 작품 이름을 붙이지 않으므로 작품 찾기부터 합니다."""
    rows = []
    for q in questions:
        started = time.time()
        r = service.find(q["question"])
        got = [(c["series_id"], c.get("abs_ep")) for c in r["candidates"]]
        first = got[0] if got else (None, None)
        gold = {(q["series_id"], ep) for ep in q["abs_eps"]}
        if r["status"] == "episode":
            verdict = "회차 맞음" if first in gold else "틀린 회차를 단정"
        elif r["status"] == "series":
            verdict = "작품만 맞음" if first[0] == q["series_id"] else "틀린 작품을 단정"
        elif r["status"] == "ambiguous":
            verdict = "되물음(후보에 정답 있음)" if gold & set(got) else "되물음(후보에 정답 없음)"
        else:
            verdict = "못 찾음"
        rows.append({"id": q["id"], "style": q["style"], "source": q["source"], "verdict": verdict,
                     "seconds": round(time.time() - started, 2), "answer": r["answer"], "got": got[:3]})
        print(f"  {verdict:16} {rows[-1]['seconds']:5.1f}초  {q['question'][:50]}", flush=True)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipeline", action="store_true", help="찾기 기능 전체를 LLM까지 돌림 (질문당 3~5초, API 비용 발생)")
    ap.add_argument("--label", default=None, help="결과 파일 이름에 붙일 말")
    ap.add_argument("--limit", type=int, help="앞에서부터 N개 질문만")
    ap.add_argument("--chunk-types", nargs="+", help="--pipeline: 장면 검색 대상을 설정 대신 이 종류로 (비교용. 예: plot)")
    args = ap.parse_args()
    if args.chunk_types:
        section("retrieval")["chunk_types"] = args.chunk_types
    questions = [json.loads(x) for x in (HERE / "questions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    questions = questions[:args.limit] if args.limit else questions
    service.warm_up()
    out = {"date": str(date.today()), "questions": len(questions), "settings": {
        "embedding": section("embedding").get("model"), "retrieval": section("retrieval"), "llm": section("llm")}}
    groups = {"전체": lambda r: True, "사람이 쓴 질문": lambda r: r["source"] == "manual",
              "이름을 말한 질문": lambda r: r["style"] == "named", "이름 없이 묘사한 질문": lambda r: r["style"] == "unnamed"}
    if args.pipeline:
        rows = pipeline(questions)
        out["pipeline"] = {"rows": rows, "summary": {}}
        for group, keep in groups.items():
            sub = [r for r in rows if keep(r)]
            counts = {}
            for r in sub:
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
            out["pipeline"]["summary"][group] = {"n": len(sub), **counts,
                                                 "평균 초": round(sum(r["seconds"] for r in sub) / max(len(sub), 1), 2)}
            print(f"\n[{group}] {out['pipeline']['summary'][group]}")
    else:
        table = retrieval(questions)
        out["retrieval"] = {name: {g: summarize([r for r in rows if keep(r)]) for g, keep in groups.items()}
                            for name, rows in table.items()}
        out["retrieval_rows"] = table
        for group in groups:
            print(f"\n[{group}] 질문 {out['retrieval'][next(iter(CONFIGS))][group]['n']}개")
            print(f"  {'검색 대상':18} {'작품 안 1위':>9} {'3위 안':>7} {'8위 안':>7} {'전체:작품 1위':>11} {'전체:회차 8위 안':>13}")
            for name in CONFIGS:
                s = out["retrieval"][name][group]
                print(f"  {name:18} {s['작품 안 1위']:>10.0%} {s['작품 안 3위 안']:>8.0%} {s['작품 안 8위 안']:>8.0%} "
                      f"{s['전체: 작품 1위']:>13.0%} {s['전체: 회차 8위 안']:>15.0%}")
    label = args.label or ("pipeline" if args.pipeline else "retrieval")
    path = HERE / "results" / f"{date.today()}_{label}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
