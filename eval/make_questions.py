"""평가 질문 만들기: 장면 청크에서 "기억으로 묻는 말"을 LLM으로 만들어 eval/questions.jsonl에 더합니다.

    .venv/bin/python eval/make_questions.py --per-series 12

- 작품마다 서로 다른 회차의 장면을 무작위(시드 고정)로 뽑고, 장면 하나에서 질문 두 개를 만듭니다:
  이름을 말하는 질문(named)과 이름 없이 생김새·역할로만 말하는 질문(unnamed).
- 정답은 그 장면이 나온 회차입니다. 사람이 쓴 질문(source가 manual)은 건드리지 않고 그대로 둡니다.
- LLM이 만든 질문이므로 발표 전에 사람이 훑어보고 어색한 것은 지우거나 고치세요.
- 주의: 장면 청크에서 만든 질문이라 장면 단위 검색에 조금 유리합니다. 사람이 쓴 질문의 결과를 같이 보세요.
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aniwhere.agent.llm import get_llm  # noqa: E402
from aniwhere.db import connect  # noqa: E402
from aniwhere.retrieval import catalog  # noqa: E402
from aniwhere.retrieval.search import ALL_EPISODES, chunks_upto  # noqa: E402

QUESTIONS = Path(__file__).resolve().parent / "questions.jsonl"
DEMO = ["tmdb:1429", "tmdb:85937", "tmdb:65930"]      # 진격의 거인, 귀멸의 칼날, 나의 히어로 아카데미아

PROMPT = """너는 애니메이션 검색 서비스의 평가 질문을 만든다. 아래는 어떤 애니메이션 한 화의 한 장면을 적은 영어 줄거리다.
이 장면을 예전에 본 한국 시청자가 "그 장면 몇 화였지?" 하고 떠올리며 검색창에 적을 법한 말을 두 개 만든다.

JSON 객체 하나만 출력한다.
{
  "named": 인물 이름이나 고유 용어를 한국에서 통용되는 표기로 한두 개 넣은 질문,
  "unnamed": 이름과 고유 용어를 하나도 쓰지 않고 생김새·역할·관계(주인공, 금발 여자애, 선생님, 큰 거인)로만 말한 질문
}

규칙
- 한두 문장, 일상 말투("~하는 장면", "~했던 거", "~하던데"). 줄거리 문장을 그대로 번역하지 말고 기억에 남을 만한 일 한두 가지만 말한다.
- 사람의 기억처럼 조금 뭉뚱그린다. 다만 이 장면에서 실제로 벌어진 일이어야 하고, 줄거리에 없는 일을 지어내지 않는다.
- 작품 제목, 몇 기 몇 화인지는 쓰지 않는다."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-series", type=int, default=12, help="작품마다 뽑을 장면 수")
    ap.add_argument("--series", nargs="+", default=DEMO)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    llm = get_llm()
    if not llm:
        raise SystemExit(".env에 OPENAI_API_KEY가 필요합니다")
    db = connect()
    rng = random.Random(args.seed)
    old = [json.loads(x) for x in QUESTIONS.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if QUESTIONS.exists() else []
    rows = [q for q in old if q.get("source") == "manual"]
    for sid in args.series:
        name = catalog.series_info(db, sid)["name"]
        scenes = [c for c in chunks_upto(db, sid, seen_ep=ALL_EPISODES, types=["event"]) if 400 <= len(c["text"]) <= 900]
        by_ep = {}
        for c in scenes:
            by_ep.setdefault(c["abs_ep"], []).append(c)
        for ep in sorted(rng.sample(sorted(by_ep), min(args.per_series, len(by_ep)))):
            scene = rng.choice(by_ep[ep])
            out = llm.json(PROMPT, scene["text"].partition("\n")[2])
            for style in ("named", "unnamed"):
                if isinstance(out.get(style), str) and out[style].strip():
                    rows.append({"id": f"{scene['chunk_id']}:{style}", "question": out[style].strip(), "series_id": sid,
                                 "series": name, "abs_eps": [ep], "style": style, "source": "synthetic"})
            print(f"  {name} {ep}화: {out.get('named')} / {out.get('unnamed')}", flush=True)
    QUESTIONS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{QUESTIONS}: {len(rows)}개 (사람이 쓴 질문 {sum(r['source'] == 'manual' for r in rows)}개 포함)")


if __name__ == "__main__":
    main()
