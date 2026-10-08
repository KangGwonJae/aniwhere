"""앱 기능(aniwhere/) 테스트: 스포일러 차단, 찾기, 복습, 기록장, 사전, 시청처.

실제 PostgreSQL을 쓰되 서비스용 DB 이름 뒤에 `_test`를 붙인 별도 DB에 작은 가짜 작품 두 개를 넣고 돕니다
(접속할 수 없으면 건너뜀). 임베딩 모델과 LLM은 가짜로 바꿔 끼우므로 모델을 내려받거나 API를 부르지 않습니다.

가짜 데이터의 규칙: 모든 청크 본문에 `SECRET-작품-회차` 표시가 들어 있어서, 응답이나 LLM 입력에 본 회차 이후의
표시가 있는지로 스포일러가 샜는지 확인합니다.
"""
import json
import re
from pathlib import Path

import psycopg
import psycopg.conninfo
import psycopg.sql
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from aniwhere import records
from aniwhere.agent import find as find_mod
from aniwhere.agent import recommend as recommend_mod
from aniwhere.agent import review as review_mod
from aniwhere.agent.llm import prompt
from aniwhere.config import service_db_url
from aniwhere.retrieval import catalog, embedder
from aniwhere.retrieval.dictionary import dictionary
from aniwhere.retrieval.search import ALL_EPISODES, chunks_upto, keyword_search, search_chunks

A, B = "tmdb:1", "tmdb:2"            # A: 테스트 거인 (10화, 1기 1~5화 / 2기 6~10화), B: 테스트 칼날 (5화)
EPISODES = {A: 10, B: 5}
DIM = 1024
SRC = [{"name": "Fandom", "license": "CC BY-SA 3.0", "url": "https://example.fandom.com/wiki/Episode"}]


def axis(series_id, ep):
    """(작품, 회차)마다 벡터의 한 칸을 씀 → 질문 벡터로 어느 회차가 1위일지 정할 수 있음."""
    return (0 if series_id == A else 100) + ep


def vector(weights):
    v = [0.0] * DIM
    for i, w in weights.items():
        v[i] = w
    return v


def fake_embed(text):
    """질문에 '[A7]'처럼 적으면 그 회차 쪽 벡터. 여러 개면 똑같이 가까움. 없으면 어느 청크와도 무관한 벡터."""
    marks = re.findall(r"\[([AB])(\d+)\]", text)
    return vector({axis(A if s == "A" else B, int(n)): 1.0 for s, n in marks} or {999: 1.0})


class FakeLLM:
    """프롬프트별로 정해 둔 답을 돌려주고, 받은 입력을 모아 둠."""

    def __init__(self, **answers):
        self.answers = answers
        self.calls = []

    def _reply(self, system, user):
        name = next(n for n in ("find_clues", "find_judge", "review", "recommend_taste", "recommend_reason")
                    if system == prompt(n))
        self.calls.append((name, user))
        return self.answers.get(name)

    def json(self, system, user):
        return self._reply(system, user) or {}

    def text(self, system, user):
        return self._reply(system, user) or "요약입니다 [1]"

    def seen(self, name):
        return "\n".join(user for n, user in self.calls if n == name)


@pytest.fixture(scope="module")
def db():
    url = service_db_url()
    name = (psycopg.conninfo.conninfo_to_dict(url).get("dbname") or "aniwhere_service") + "_test"
    test_url = psycopg.conninfo.make_conninfo(url, dbname=name)
    try:
        try:
            conn = psycopg.connect(test_url, row_factory=dict_row, autocommit=True)
        except psycopg.OperationalError as e:
            if "does not exist" not in str(e):
                raise
            with psycopg.connect(psycopg.conninfo.make_conninfo(url, dbname="postgres"), autocommit=True) as admin:
                admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
            conn = psycopg.connect(test_url, row_factory=dict_row, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"테스트용 PostgreSQL({name})에 접속할 수 없음: {str(e).splitlines()[0]}")
    assert conn.info.dbname.endswith("_test")     # 실제 서비스용 DB를 지우는 일이 없도록
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    conn.execute((Path(__file__).resolve().parents[1] / "data" / "schema.sql").read_text(encoding="utf-8"))
    for sid, title, title_ko, pop in ((A, "Test Titan", "테스트 거인", 100), (B, "Test Blade", "테스트 칼날", 50)):
        conn.execute("INSERT INTO series (series_id, title, title_ko, popularity, total_episodes) VALUES (%s,%s,%s,%s,%s)",
                     (sid, title, title_ko, pop, EPISODES[sid]))
        conn.execute("""INSERT INTO entries (entry_key, series_id, order_in_series, abs_offset, title, title_en,
                                             genres, tags, average_score)
                        VALUES (%s,%s,1,0,%s,%s,%s,%s,80)""",
                     (f"e:{sid}", sid, title, title, ["Action", "Drama"], ["revenge", "survival"]))
        chunks = [(f"{sid}:summary:1", "summary", None, f"{title_ko} 작품 소개. 벽 안의 인류 이야기.", None)]
        for ep in range(1, EPISODES[sid] + 1):
            season, number = (1, ep) if ep <= 5 else (2, ep - 5)
            conn.execute("""INSERT INTO episodes (series_id, abs_ep, entry_key, entry_ep, tmdb_season, tmdb_number,
                                                  title_ko, characters) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                         (sid, ep, f"e:{sid}", ep, season, number, f"제목{ep}", ["Hero (Anime)", f"Guest{ep}"]))
            mark = f"SECRET-{'A' if sid == A else 'B'}-{ep}"
            head = f"{title_ko} {season}기 {number}화 (전체 {ep}화) 〈제목{ep}〉"
            chunks += [
                (f"{sid}:plot:{ep}", "plot", ep, f"{head} 줄거리\nThe hero fights dragon{ep}. {mark}", axis(sid, ep)),
                (f"{sid}:ep:{ep}", "episode", ep, f"{head}\n{ep}화 요약. {mark}", None),
                (f"{sid}:event:{ep}:1", "event", ep, f"{head} 장면\nThe hero meets wizard{ep} at the tower. {mark}",
                 axis(sid, ep)),
                (f"{sid}:event:{ep}:2", "event", ep, f"{head} 장면\nThe hero goes home after wizard{ep}. {mark}",
                 axis(sid, ep)),
            ]
        chunks += [(f"{sid}:char:7", "character", None, f"{title_ko} 캐릭터 Hero [MAIN]\nA brave hero.", None),
                   (f"{sid}:char:8", "character", 4, f"{title_ko} 캐릭터 Rival [MAIN]\nA masked rival. SECRET-X-4", None),
                   (f"{sid}:wiki:Magic Sword:1", "terminology", 6, f"{title_ko} 물건·장비 Magic Sword\nA sword. SECRET-X-6",
                    None)]
        for cid, name in ((7, "Hero"), (8, "Rival")):
            conn.execute("""INSERT INTO characters (series_id, anilist_char, name, role, description, first_entry)
                            VALUES (%s,%s,%s,'MAIN','d',%s)""", (sid, cid, name, f"e:{sid}"))
        for chunk_id, type_, ep, text, ax in chunks:
            conn.execute("INSERT INTO chunks (chunk_id, series_id, type, abs_ep, text, sources, embedding) "
                         "VALUES (%s,%s,%s,%s,%s,%s,%s::vector)",
                         (chunk_id, sid, type_, ep, text, Jsonb(SRC), str(vector({ax: 1.0})) if ax is not None else None))
        conn.execute("INSERT INTO streaming (series_id, tmdb_season, season_name, flatrate, link, checked_at) "
                     "VALUES (%s, 1, '시즌 1', %s, 'https://example.com', '2026-10-05')", (sid, ["Netflix", "TVING"]))
    embedder.set_embedder(fake_embed)
    yield conn
    embedder.set_embedder(None)
    conn.close()


@pytest.fixture(autouse=True)
def clean_records(db):
    yield
    db.execute("DROP TABLE IF EXISTS watch_records")
    records.store._ready.clear()


def leaked(text, series, seen_ep):
    """글에 들어 있는, seen_ep 이후 회차의 표시 목록."""
    return [m for m in re.findall(rf"SECRET-(?:{series}|X)-(\d+)", text) if int(m) > seen_ep]


# ───────────────────────── 11 스포일러 차단 ─────────────────────────

def test_search_functions_require_seen_episode(db):
    with pytest.raises(TypeError):
        search_chunks(db, vector({1: 1.0}))
    with pytest.raises(TypeError):
        search_chunks(db, vector({1: 1.0}), watched=None)
    with pytest.raises(TypeError):
        keyword_search(db, ["hero"], series_ids=[A], types=["event"])
    with pytest.raises(TypeError):
        chunks_upto(db, A, types=["plot"])


@pytest.mark.parametrize("watched", [0, 1, 4, 5, 9, 10])
def test_no_chunk_after_watched_episode(db, watched):
    """N화까지 봤으면 N+1화 이후 청크는 검색 결과에 절대 나오지 않는다 (벡터·키워드·조건 검색 모두)."""
    types = ["plot", "episode", "event", "character", "terminology", "summary"]
    for target in (1, watched + 1, 10):
        rows = search_chunks(db, vector({axis(A, min(target, 10)): 1.0}), watched={A: watched}, types=types, k=1000)
        assert all(r["abs_ep"] is None or (r["series_id"] == A and r["abs_ep"] <= watched) for r in rows)
        assert len([r for r in rows if r["type"] == "plot"]) == watched      # 볼 수 있는 청크는 빠짐없이 검색 대상
        assert len([r for r in rows if r["type"] == "event"]) == watched * 2
    rows = keyword_search(db, ["hero wizard rival sword"], watched={A: watched}, series_ids=[A, B], types=types, k=1000)
    assert rows and all(r["abs_ep"] is None or (r["series_id"] == A and r["abs_ep"] <= watched) for r in rows)
    rows = chunks_upto(db, A, seen_ep=watched, types=types, include_episode_free=True)
    assert rows and all(r["abs_ep"] is None or r["abs_ep"] <= watched for r in rows)
    assert {r["chunk_id"] for r in rows} >= {f"{A}:plot:{n}" for n in range(1, watched + 1)}


def test_find_scope_still_respects_records(db):
    """찾기는 기록 없는 작품을 전체 회차까지 검색하지만, 기록이 있는 작품은 본 회차까지만."""
    rows = search_chunks(db, vector({axis(A, 7): 1.0}), watched={A: 3}, unrecorded=ALL_EPISODES, k=1000)
    assert max(r["abs_ep"] for r in rows if r["series_id"] == A) == 3
    assert max(r["abs_ep"] for r in rows if r["series_id"] == B) == 5


# ───────────────────────── 09 복습 ─────────────────────────

def test_review_without_seen_episode_asks_instead_of_searching(db, monkeypatch):
    monkeypatch.setattr(review_mod, "search_chunks", lambda *a, **k: pytest.fail("본 회차 없이 검색함"))
    monkeypatch.setattr(review_mod, "chunks_upto", lambda *a, **k: pytest.fail("본 회차 없이 검색함"))
    llm = FakeLLM()
    r = review_mod.review(db, A, None, "summary", llm=llm)
    assert r["answer"] is None and r["seen_ep"] is None and r["sources"] == [] and "어디까지" in r["follow_up"]
    assert not llm.calls


def test_review_reads_seen_episode_from_records(db):
    records.save(db, A, 4)
    r = review_mod.review(db, A, None, "last", llm=FakeLLM())
    assert r["seen_ep"] == 4 and max(s["abs_ep"] for s in r["sources"]) == 4


@pytest.mark.parametrize("mode,question", [("summary", None), ("characters", None), ("last", None),
                                           ("ask", "[A9] 그 뒤에 어떻게 돼?"), ("요약", None), ("마지막 화", None)])
@pytest.mark.parametrize("seen_ep", [1, 4, 7])
def test_review_never_shows_llm_later_episodes(db, mode, question, seen_ep):
    """복습은 어떤 종류든 본 회차 이후 내용을 LLM에게도, 응답의 근거에도 넣지 않는다 (9화를 물어도)."""
    llm = FakeLLM()
    r = review_mod.review(db, A, seen_ep, mode, question, llm=llm)
    sent = llm.seen("review")
    assert sent and not leaked(sent, "A", seen_ep)
    assert f"SECRET-A-{seen_ep}" in sent                          # 본 회차까지는 들어 있음
    assert r["seen_ep"] == seen_ep and r["sources"]
    assert all(s["abs_ep"] <= seen_ep for s in r["sources"]) and not leaked(json.dumps(r), "A", seen_ep)
    assert set(r["sources"][0]) >= {"text", "abs_ep", "url", "license"}


def test_review_modes_pick_the_right_episodes(db):
    llm = FakeLLM()
    assert [s["abs_ep"] for s in review_mod.review(db, A, 6, "summary", llm=llm)["sources"]] == [1, 2, 3, 4, 5, 6]
    last = review_mod.review(db, A, 6, "last", llm=llm)["sources"]
    assert [s["abs_ep"] for s in last] == [4, 5, 6] and "줄거리" in last[-1]["text"]     # 마지막 화는 상세 줄거리
    review_mod.review(db, A, 6, "characters", llm=llm)
    assert "dragon6" in llm.calls[-1][1] and "Guest" not in llm.calls[-1][1]     # 상세 줄거리로, 등장인물 목록은 안 씀
    assert review_mod.review(db, A, 0, "summary", llm=llm)["sources"] == []
    assert review_mod.review(db, A, 99, "summary", llm=llm)["seen_ep"] == 10              # 총 회차를 넘지 않음
    assert review_mod.review(db, A, 3, "ask", " ", llm=llm)["follow_up"]


def test_review_works_without_llm(db):
    r = review_mod.review(db, A, 2, "summary", llm=None)
    assert "LLM 키가 없어" in r["answer"] and not leaked(r["answer"], "A", 2)


# ───────────────────────── 05·06 찾기 ─────────────────────────

def test_find_without_llm_decides_by_score(db):
    r = find_mod.find(db, "테스트 거인에서 용이랑 싸우는 장면 [A7]")
    assert r["status"] == "episode" and r["candidates"][0]["series_id"] == A and r["candidates"][0]["abs_ep"] == 7
    assert r["candidates"][0]["label"] == "2기 2화 (전체 7화) 〈제목7〉" and r["follow_up"] is None
    r = find_mod.find(db, "테스트 거인에서 [A7] 아니면 [A8]")
    assert r["status"] == "ambiguous" and {c["abs_ep"] for c in r["candidates"]} >= {7, 8} and r["follow_up"]
    r = find_mod.find(db, "아무 단서도 없는 말")
    assert r["status"] == "none" and r["candidates"] == [] and r["follow_up"]      # 근거가 약하면 단정하지 않음


def test_find_uses_history_as_clues(db):
    history = [{"role": "user", "content": "용이랑 싸웠어 [B3]"}, {"role": "assistant", "content": "어느 작품인가요?"}]
    r = find_mod.find(db, "테스트 칼날이었어", history)
    assert r["status"] == "episode" and (r["candidates"][0]["series_id"], r["candidates"][0]["abs_ep"]) == (B, 3)


def test_find_stays_inside_recorded_episodes(db):
    records.save(db, A, 3)
    r = find_mod.find(db, "테스트 거인 [A7]")
    assert all(c.get("abs_ep", 0) <= 3 for c in r["candidates"]) and r["status"] != "episode"
    assert "3화까지" in r["answer"] or r["status"] == "none"
    llm = FakeLLM(find_judge={"status": "none", "pick": None})
    find_mod.find(db, "테스트 거인 [A7]", llm=llm)
    assert not leaked(llm.seen("find_judge"), "A", 3)                 # LLM에게도 본 회차 이후는 보여 주지 않음


def test_find_with_llm_answers_only_from_retrieved_candidates(db):
    clues = {"series_title": None, "title_guesses": ["Test Titan"], "query_en": "wizard7 appears",
             "keywords": ["wizard7"], "names": []}
    llm = FakeLLM(find_clues=clues, find_judge={"status": "episode", "pick": 1, "also": [], "reason": "용과 싸웠어요.",
                                                     "quote": "The hero meets wizard7 at the tower.", "missing": []})
    r = find_mod.find(db, "마법사를 탑에서 만났어", llm=llm)          # 벡터로는 못 찾고 키워드(wizard7)로 찾는 경우
    assert r["status"] == "episode" and (r["candidates"][0]["series_id"], r["candidates"][0]["abs_ep"]) == (A, 7)
    assert "「테스트 거인」 2기 2화 (전체 7화)" in r["answer"] and r["sources"][0]["url"]
    assert "SECRET" not in json.dumps(r, ensure_ascii=False)          # 응답에 줄거리 본문은 없음
    quote = "The hero meets wizard7 at the tower."
    for bad in ({"status": "episode", "pick": 99, "quote": quote}, {"status": "episode", "pick": "1", "quote": quote},
                {}, {"status": "none"},
                {"status": "episode", "pick": 1},                                        # 근거 문장을 못 댐
                {"status": "episode", "pick": 1, "quote": "The hero defeats the demon king."},   # 자료에 없는 문장
                {"status": "episode", "pick": 1, "quote": quote, "clues": ["용", "싸움"], "missing": ["용", "싸움"]}):
        r = find_mod.find(db, "마법사를 탑에서 만났어", llm=FakeLLM(find_clues=clues, find_judge=bad))
        assert r["status"] == "none" and r["candidates"] == []        # LLM이 후보에 없는 것을 고르면 답하지 않음
    r = find_mod.find(db, "마법사를 탑에서 만났어", llm=FakeLLM(find_clues=clues, find_judge={
        "status": "episode", "pick": 1, "quote": quote, "clues": ["용", "싸움", "탑"], "missing": ["탑"], "reason": "."}))
    assert r["status"] == "episode" and "'탑' 부분은 줄거리에서 확인하지 못했어요" in r["answer"]
    r = find_mod.find(db, "마법사를 탑에서 만났어", llm=FakeLLM(find_clues=clues, find_judge={
        "status": "ambiguous", "pick": 1, "also": [2], "reason": "", "follow_up": "누가 나왔나요?"}))
    assert r["status"] == "ambiguous" and len(r["candidates"]) == 2 and r["follow_up"] == "누가 나왔나요?"


def test_series_is_found_by_title_or_alias(db, monkeypatch, tmp_path):
    assert catalog.mentioned_series(db, "테스트거인 몇 화였지") == [A]
    assert catalog.mentioned_series(db, "그냥 거인 나오는 거") == []
    assert catalog.find_series(db, "Test Blade") == [B] and catalog.find_series(db, "없는 작품") == []
    (tmp_path / "aliases.json").write_text(json.dumps({"테거": A}), encoding="utf-8")
    monkeypatch.setattr(catalog, "ALIASES", tmp_path / "aliases.json")
    catalog._names_cache.clear()
    assert catalog.mentioned_series(db, "테거 3화") == [A]
    catalog._names_cache.clear()


# ───────────────────────── 13 기록장 · 07 시청처 · 08 사전 · 01 추천 ─────────────────────────

def test_records_save_update_and_validate(db):
    assert records.get(db, A) is None and records.watched_map(db) == {}
    assert records.save(db, A, 3, 4.5)["seen_ep"] == 3
    r = records.save(db, A, 5)                                        # 평점을 안 넘기면 전 평점 유지
    assert (r["seen_ep"], r["rating"], r["name"], r["total_episodes"]) == (5, 4.5, "테스트 거인", 10)
    assert records.watched_map(db) == {A: 5} and [x["series_id"] for x in records.list_all(db)] == [A]
    assert records.watched_map(db, user_id="other") == {}
    for bad in (-1, 11, 2.5, None, True):
        with pytest.raises(ValueError):
            records.save(db, A, bad)
    with pytest.raises(ValueError):
        records.save(db, A, 3, 6)
    with pytest.raises(ValueError):
        records.save(db, "tmdb:404", 1)
    assert records.delete(db, A) and not records.delete(db, A)


def test_streaming_lists_providers_with_checked_date(db):
    s = catalog.streaming(db, A)
    assert s[0]["providers"] == ["Netflix", "TVING"] and str(s[0]["checked_at"]) == "2026-10-05" and s[0]["name"]


def test_dictionary_shows_only_entries_up_to_seen_episode(db):
    names = lambda n: {e["name"] for e in dictionary(db, A, seen_ep=n)}
    assert names(3) == {"Hero"} and names(4) == {"Hero", "Rival"} and names(6) == {"Hero", "Rival", "Magic Sword"}
    assert {e["kind"] for e in dictionary(db, A, seen_ep=10)} == {"character", "term"}


def test_recommend_skips_watched_series_and_reads_only_intro(db):
    records.save(db, A, 2)
    llm = FakeLLM(recommend_taste={"mood": "복수극", "genres": ["Drama"], "tags": ["revenge"]},
                  recommend_reason={"picks": [{"n": 1, "reason": "복수극을 좋아하셨다면"}, {"n": 9, "reason": "x"}]})
    r = recommend_mod.recommend(db, "더 글로리", llm=llm)
    assert [p["series_id"] for p in r["picks"]] == [B] and r["mood"] == "복수극"
    assert "SECRET" not in llm.seen("recommend_reason")
    assert recommend_mod.recommend(db, "더 글로리", llm=None)["picks"] == []
