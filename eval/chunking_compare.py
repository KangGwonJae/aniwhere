"""청킹 방식 비교: 같은 줄거리를 여러 방식으로 나눠 임베딩하고, 정답 회차를 몇 위에 찾는지 잽니다.

    .venv/bin/python eval/chunking_compare.py                       # 기본: eval/questions_plot.jsonl
    .venv/bin/python eval/chunking_compare.py --questions eval/questions.jsonl --label taeho-questions

서비스 DB(aniwhere_service)의 데모 3작품 줄거리만 읽고, DB에는 아무것도 쓰지 않습니다.
청크와 벡터는 이 스크립트 안에서만 만들어 data/processed/chunking_compare/에 캐시합니다(커밋 안 함).

비교하는 방식 (장면 청크는 모두 같은 머리말 "작품 N기 M화 (전체 X화) 〈제목〉 장면"을 붙여 임베딩)
- paragraph   : 지금 방식. 위키 문단을 이어 붙여 약 700자 (data/collect.py split_paragraphs)
- overlap     : paragraph의 각 조각 앞뒤에 이웃 조각의 문장 하나씩을 붙임
- semantic    : 문장마다 임베딩해 앞뒤 문장의 유사도가 가장 크게 떨어지는 곳에서 자름. 조각 수는 paragraph와 같게 맞춤
- fixed       : 문단·문장과 상관없이 700자마다 자름 (단순 기준선)
- plot        : 회차 줄거리 통째 하나 (참고)

질문셋의 source가 synthetic인 질문은 지금의 paragraph 조각을 보고 만든 것이라 paragraph에 유리합니다.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
from collect import clean_plot, split_paragraphs  # noqa: E402

HERE = ROOT / "eval"
CACHE = ROOT / "data" / "processed" / "chunking_compare"
SERIES = ["tmdb:1429", "tmdb:65930", "tmdb:85937"]          # 진격의 거인, 나의 히어로 아카데미아, 귀멸의 칼날
TARGET = 700
SENTENCE_RE = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+")
METHODS = ["paragraph", "overlap", "semantic", "fixed", "plot"]

_model = None


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-m3")
        _model.max_seq_length = 8192
        if _model.device.type != "cpu":
            _model.half()
    return _model


def embed(texts, cache_name=None):
    """정규화된 벡터. cache_name을 주면 글 목록이 같을 때 캐시를 다시 씀."""
    key = hashlib.sha1("\x00".join(texts).encode()).hexdigest()[:16]
    path = CACHE / f"{cache_name}_{key}.npy" if cache_name else None
    if path and path.exists():
        return np.load(path)
    order = sorted(range(len(texts)), key=lambda i: -len(texts[i]))   # 길이가 비슷한 글끼리 묶어 빠르게
    out = np.zeros((len(texts), 1024), dtype=np.float32)
    done = 0
    while done < len(order):
        size = max(1, min(32, 32000 // max(len(texts[order[done]]), 1)))
        idx = order[done:done + size]
        out[idx] = model().encode([texts[i] for i in idx], normalize_embeddings=True, show_progress_bar=False)
        done += size
    if path:
        CACHE.mkdir(parents=True, exist_ok=True)
        np.save(path, out)
    return out


def sentences(text):
    out = []
    for para in (p.strip() for p in text.split("\n") if p.strip()):
        out += [s.strip() for s in SENTENCE_RE.split(para) if s.strip()]
    return out


def split_overlap(parts):
    """각 조각 앞에 앞 조각의 마지막 문장, 뒤에 다음 조각의 첫 문장을 붙임."""
    sents = [sentences(p) for p in parts]
    out = []
    for i, p in enumerate(parts):
        before = sents[i - 1][-1] if i > 0 and sents[i - 1] else ""
        after = sents[i + 1][0] if i + 1 < len(parts) and sents[i + 1] else ""
        out.append("\n".join(x for x in (before, p, after) if x))
    return out


def split_semantic(plot, n_parts, min_chars=200):
    """문장 사이 유사도가 가장 크게 떨어지는 n_parts-1곳에서 자름. 너무 짧은 조각이 생기는 자리는 건너뜀."""
    sents = sentences(plot)
    if n_parts <= 1 or len(sents) <= 1:
        return [" ".join(sents)]
    vec = embed(sents, cache_name="sentences")
    drop = 1 - (vec[:-1] * vec[1:]).sum(1)        # i번째 문장과 i+1번째 문장 사이의 거리
    lengths = np.cumsum([len(s) + 1 for s in sents])
    cuts = []
    for i in np.argsort(-drop):
        trial = sorted(cuts + [i])
        bounds = [0] + [lengths[c] for c in trial] + [lengths[-1]]
        if min(b - a for a, b in zip(bounds, bounds[1:])) >= min_chars:
            cuts = trial
        if len(cuts) == n_parts - 1:
            break
    edges = [0] + [c + 1 for c in cuts] + [len(sents)]
    return [" ".join(sents[a:b]) for a, b in zip(edges, edges[1:])]


def split_fixed(plot, size=TARGET):
    flat = re.sub(r"\s+", " ", plot).strip()
    return [flat[i:i + size] for i in range(0, len(flat), size)]


def load_episodes(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        names = {r["series_id"]: r["title_ko"] or r["title"] for r in db.execute(
            "SELECT series_id, title, title_ko FROM series WHERE series_id = ANY(%s)", (SERIES,))}
        rows = db.execute("""SELECT series_id, abs_ep, tmdb_season, tmdb_number, title_ko, title_en, fandom_title, plot
                             FROM episodes WHERE series_id = ANY(%s) AND plot IS NOT NULL
                             ORDER BY series_id, abs_ep""", (SERIES,)).fetchall()
    eps = []
    for ep in rows:
        plot = clean_plot(ep["plot"])
        if not plot:
            continue
        # 머리말은 data/collect.py build_chunks와 같은 모양
        head = f"{names[ep['series_id']]} " + \
               (f"{ep['tmdb_season']}기 {ep['tmdb_number']}화 " if ep["tmdb_season"] else "") + f"(전체 {ep['abs_ep']}화)"
        title = ep["title_ko"] or ep["title_en"] or ep["fandom_title"]
        head += f" 〈{title}〉" if title else ""
        eps.append({"series_id": ep["series_id"], "abs_ep": ep["abs_ep"], "head": head, "plot": plot})
    return eps


def build(eps):
    """방식별 청크: {method: [(series_id, abs_ep, text)]}"""
    chunks = {m: [] for m in METHODS}
    for n, ep in enumerate(eps, 1):
        para = split_paragraphs(ep["plot"])
        parts = {"paragraph": para, "overlap": split_overlap(para),
                 "semantic": split_semantic(ep["plot"], len(para)), "fixed": split_fixed(ep["plot"])}
        for m, ps in parts.items():
            chunks[m] += [(ep["series_id"], ep["abs_ep"], f"{ep['head']} 장면\n{p}") for p in ps]
        chunks["plot"].append((ep["series_id"], ep["abs_ep"], f"{ep['head']} 줄거리\n{ep['plot']}"))
        if n % 50 == 0:
            print(f"  청크 만드는 중 {n}/{len(eps)}", flush=True)
    return chunks


def boundary_split(eps, questions):
    """질문의 근거 문장(evidence)이 paragraph 조각 경계에 걸쳐 둘로 갈렸는지."""
    by_key = {(e["series_id"], e["abs_ep"]): e for e in eps}
    out = {}
    for q in questions:
        ev, ep = q.get("evidence"), by_key.get((q["series_id"], q["abs_eps"][0]))
        if not ev or not ep:
            continue
        out[q["id"]] = not any(ev in p for p in split_paragraphs(ep["plot"])) and ev in ep["plot"]
    return out


def rank_episodes(scores, keys):
    """청크 점수 → 회차별 최고 점수로 순위를 매긴 (series_id, abs_ep) 목록."""
    best = {}
    for s, k in zip(scores, keys):
        if s > best.get(k, -9):
            best[k] = s
    return sorted(best, key=lambda k: -best[k])


def evaluate(chunks, vectors, questions, qvec):
    rows = {m: [] for m in METHODS}
    for m in METHODS:
        keys = [(s, e) for s, e, _ in chunks[m]]
        series = np.array([s for s, _ in keys])
        sims = qvec @ vectors[m].T
        for q, sc in zip(questions, sims):
            gold = {(q["series_id"], e) for e in q["abs_eps"]}
            inside = rank_episodes(sc[series == q["series_id"]], [k for k in keys if k[0] == q["series_id"]])
            everywhere = rank_episodes(sc, keys)
            series_order = list(dict.fromkeys(s for s, _ in everywhere))
            rows[m].append({"id": q["id"],
                            "in_series": next(i for i, k in enumerate(inside, 1) if k in gold),
                            "global": next(i for i, k in enumerate(everywhere, 1) if k in gold),
                            "series": series_order.index(q["series_id"]) + 1})
    return rows


def summarize(rows):
    n = max(len(rows), 1)
    hit = lambda k: sum(r["in_series"] <= k for r in rows) / n  # noqa: E731
    return {"n": len(rows), "작품 안 1위": hit(1), "작품 안 3위 안": hit(3), "작품 안 8위 안": hit(8),
            "작품 안 MRR": sum(1 / r["in_series"] for r in rows) / n,
            "3작품 전체: 작품 1위": sum(r["series"] == 1 for r in rows) / n,
            "3작품 전체: 회차 8위 안": sum(r["global"] <= 8 for r in rows) / n}


def paired(rows, a, b):
    """같은 질문에서 a가 b보다 정답 회차를 높게 찾은 수 / 낮게 찾은 수."""
    win = sum(x["in_series"] < y["in_series"] for x, y in zip(rows[a], rows[b]))
    lose = sum(x["in_series"] > y["in_series"] for x, y in zip(rows[a], rows[b]))
    return {"이김": win, "짐": lose, "같음": len(rows[a]) - win - lose}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(HERE / "questions_plot.jsonl"))
    ap.add_argument("--label", default="chunking-compare")
    ap.add_argument("--db", default="dbname=aniwhere_service")
    args = ap.parse_args()
    questions = [json.loads(x) for x in Path(args.questions).read_text(encoding="utf-8").splitlines() if x.strip()]
    questions = [q for q in questions if q["series_id"] in SERIES]

    eps = load_episodes(args.db)
    print(f"회차 {len(eps)}개, 질문 {len(questions)}개")
    chunks = build(eps)
    vectors = {}
    for m in METHODS:
        texts = [t for _, _, t in chunks[m]]
        print(f"  {m}: 청크 {len(texts):,}개, 평균 {np.mean([len(t) for t in texts]):,.0f}자 — 임베딩", flush=True)
        vectors[m] = embed(texts, cache_name=m)
    qvec = embed([q["question"] for q in questions])
    rows = evaluate(chunks, vectors, questions, qvec)

    split = boundary_split(eps, questions)
    groups = {"전체": lambda q: True,
              "이름을 말한 질문": lambda q: q.get("style") == "named",
              "이름 없이 묘사한 질문": lambda q: q.get("style") == "unnamed",
              "근거가 paragraph 경계에 걸린 질문": lambda q: split.get(q["id"]) is True}
    out = {"date": str(date.today()), "questions_file": Path(args.questions).name, "questions": len(questions),
           "episodes": len(eps), "embedding": "BAAI/bge-m3",
           "chunks": {m: {"count": len(chunks[m]), "avg_chars": round(float(np.mean([len(t) for _, _, t in chunks[m]])))}
                      for m in METHODS},
           "summary": {}, "paired_vs_paragraph": {m: paired(rows, m, "paragraph") for m in METHODS if m != "paragraph"},
           "rows": rows}
    for g, keep in groups.items():
        ids = {q["id"] for q in questions if keep(q)}
        out["summary"][g] = {m: summarize([r for r in rows[m] if r["id"] in ids]) for m in METHODS}
        n = out["summary"][g]["paragraph"]["n"]
        if not n:
            continue
        print(f"\n[{g}] 질문 {n}개")
        print(f"  {'방식':10} {'청크':>6} {'1위':>6} {'3위 안':>7} {'8위 안':>7} {'MRR':>6} {'작품 1위':>8}")
        for m in METHODS:
            s = out["summary"][g][m]
            print(f"  {m:10} {len(chunks[m]):>6,} {s['작품 안 1위']:>6.0%} {s['작품 안 3위 안']:>7.0%} "
                  f"{s['작품 안 8위 안']:>7.0%} {s['작품 안 MRR']:>6.2f} {s['3작품 전체: 작품 1위']:>8.0%}")
    print("\n[paragraph와 질문별 비교: 정답 회차 순위가 더 높음 / 낮음 / 같음]")
    for m, p in out["paired_vs_paragraph"].items():
        print(f"  {m:10} {p['이김']:>3} / {p['짐']:>3} / {p['같음']:>3}")
    path = HERE / "results" / f"{date.today()}_{args.label}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {path}")


if __name__ == "__main__":
    main()
