"""01 입문 — 취향 인터뷰 추천. 좋아하는 영화·드라마·웹툰을 듣고 분위기가 비슷한 애니를 권합니다.

흐름: 취향을 장르·태그로 옮김(LLM) → 장르·태그가 겹치는 작품을 조건 검색 → 작품 소개만 근거로 권하는 이유 작성(LLM).
이미 본 작품(시청 기록장)은 빼고, 소개는 회차와 무관한 청크(1기 소개)만 읽으므로 스포일러가 없습니다.
"""
from aniwhere import records
from aniwhere.agent.llm import prompt
from aniwhere.config import section
from aniwhere.retrieval import catalog
from aniwhere.retrieval.search import chunks_upto

NEED_LLM = "취향을 장르로 옮기는 데 LLM이 필요해요. .env에 OPENAI_API_KEY를 넣어 주세요."


def recommend(db, likes: str, *, llm=None, user_id=records.LOCAL_USER) -> dict:
    """{mood, picks[{series_id, title, reason, poster_url, genres}], follow_up?}"""
    if not (likes or "").strip():
        return {"mood": None, "picks": [], "follow_up": "재미있게 본 영화나 드라마, 웹툰을 두세 개 알려 주세요."}
    if not llm:
        return {"mood": None, "picks": [], "follow_up": NEED_LLM}
    taste = llm.json(prompt("recommend_taste"), f"좋아하는 작품: {likes.strip()}")
    words = lambda v: [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
    genres, tags = words(taste.get("genres")), words(taste.get("tags"))
    if not genres and not tags:
        return {"mood": None, "picks": [], "follow_up": "취향을 읽지 못했어요. 작품 이름을 조금 더 알려 주세요."}
    count = section("recommend").get("count", 5)
    seen = list(records.watched_map(db, user_id=user_id))
    pool = [r for r in catalog.similar_by_tags(db, genres, tags, exclude=seen, limit=count * 4) if r["overlap"] > 0]
    intro = {r["series_id"]: " ".join(c["text"] for c in chunks_upto(
        db, r["series_id"], seen_ep=0, types=["summary"], include_episode_free=True))[:1200] for r in pool}
    pool = [r for r in pool if intro[r["series_id"]]]
    if not pool:
        return {"mood": taste.get("mood"), "picks": [], "follow_up": "지금 가진 작품 가운데 맞는 것을 찾지 못했어요."}
    j = llm.json(prompt("recommend_reason"), f"사용자가 좋아하는 작품: {likes.strip()}\n취향 요약: {taste.get('mood')}\n"
                 f"고를 개수: {count}\n\n후보:\n" + "\n\n".join(
                     f"[{i}] {intro[r['series_id']]}" for i, r in enumerate(pool, 1)))
    picks = []
    for p in j.get("picks") if isinstance(j.get("picks"), list) else []:
        n = p.get("n") if isinstance(p, dict) else None
        if isinstance(n, int) and 1 <= n <= len(pool) and pool[n - 1]["series_id"] not in {x["series_id"] for x in picks}:
            r = pool[n - 1]
            picks.append({"series_id": r["series_id"], "title": r["name"], "reason": str(p.get("reason") or ""),
                          "poster_url": r["poster_url"], "genres": r["genres"]})
    return {"mood": taste.get("mood"), "picks": picks[:count], "follow_up": None}
