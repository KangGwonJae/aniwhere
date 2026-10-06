"""데이터 수집기(data/collect.py) 테스트.

DB가 필요 없는 테스트(위키 파서, 회차 번호 연결)와 실제 PostgreSQL을 쓰는 테스트(전체 흐름, 스포일러 차단)가 있습니다.
DB 테스트는 DATABASE_URL의 데이터베이스 이름 뒤에 `_test`를 붙인 별도 DB에서만 돌고, 접속할 수 없으면 건너뜁니다.
"""
import argparse
import random
import sys
from pathlib import Path

import psycopg
import psycopg.conninfo
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data"))
import collect  # noqa: E402

WIKI = """{{PageTheme|arc-hideout_raid}}
{{Episode_Infobox
|season number = 3
|ep number = 49
|image = <gallery>
Episode 49.png|Episode
</gallery>
|ep title = One For All
|adapted from = [[Chapter 92]]<br>
[[Chapter 93]]
|arc = Hideout Raid
}}
'''One For All''' is the forty-ninth episode of the ''My Hero Academia'' anime.<ref>Official site</ref>

==Summary==
[[File:All Might vs All For One.png|thumb|right|Light and [[darkness]] collide.]]During [[All Might]]'s adolescence, he spoke with [[Nana Shimura]] about his desire to become a pillar of hope.

[[All For One]] taunts All Might about being too similar to his weak predecessor.

===Aftermath===
All Might finishes All For One with one final technique: '''United States of Smash!'''

==Characters in Order of Appearance==
*[[Toshinori Yagi]]
*[[Nana Shimura]]
*[[Toshinori Yagi]]

==Site Navigation==
[[Category:Episodes]]
"""


def entry(key, order, offset, n, tmdb=None, tmdb_off=None, tvdb=None, tvdb_off=None):
    return {"entry_key": key, "order_in_series": order, "abs_offset": offset, "episodes": n,
            "tmdb_season": tmdb, "tmdb_offset": tmdb_off, "tvdb_season": tvdb, "tvdb_offset": tvdb_off}


AOT = [entry("s1", 1, 0, 25, 1, None, 1), entry("s2", 2, 25, 12, 2, None, 2), entry("s3a", 3, 37, 12, 3, None, 3),
       entry("s3b", 4, 49, 10, 3, 12, 3, 12), entry("f1", 5, 59, 16, 4, None, 4), entry("f2", 6, 75, 12, 4, 16, 4, 16)]


# ───────────────────────── DB 없이 ─────────────────────────

def test_wikitext_parser():
    p = collect.parse_episode_wikitext(WIKI)
    assert p["episode_no"] == 49 and p["title"] == "One For All" and p["arc"] == "Hideout Raid"
    assert p["chapters"] == "Chapter 92, Chapter 93"
    assert p["characters"] == ["Toshinori Yagi", "Nana Shimura"]
    # 그림 설명은 빠지고, 그림 뒤에 붙어 있던 본문과 하위 구역은 남아야 함
    assert "collide" not in p["plot"] and "thumb" not in p["plot"]
    assert p["plot"].startswith("During All Might's adolescence")
    assert "United States of Smash" in p["plot"]


def test_non_integer_episode_number_is_ignored():
    p = collect.parse_episode_wikitext("{{Infobox OVA\n|Number (episode) = 13.5\n|Kanji = x\n|Romaji = y\n}}\n==Summary==\ntext")
    assert p["episode_no"] is None


def test_season_map_stacks_split_seasons():
    m = collect.SeasonMap(AOT, "tmdb")
    assert m.lookup(3, 12) == (49, "s3a", 12)
    assert m.lookup(3, 13) == (50, "s3b", 1)       # 3기 Part 2는 TMDB 시즌 3의 13화부터
    assert m.lookup(3, 23) is None                  # 항목의 회차 수를 넘는 회차(스페셜 등)는 버림
    assert m.lookup(4, 28) == (87, "f2", 12)


def test_season_map_uses_source_specific_offset():
    jjk = [entry("s1", 1, 0, 24, 1, None, 1), entry("s2", 2, 24, 23, 2, None, 2), entry("s3", 3, 47, 12, 1, 47, 3)]
    assert collect.SeasonMap(jjk, "tmdb").lookup(1, 48) == (48, "s3", 1)   # TMDB는 3기를 시즌 1의 48화로 둠
    assert collect.SeasonMap(jjk, "tvdb").lookup(3, 1) == (48, "s3", 1)    # TVDB는 시즌 3의 1화


def test_map_episodes_falls_back_to_running_order():
    one_piece = [entry("op", 1, 0, 1168)]
    pairs, how = collect.map_episodes(one_piece, "tvdb", [(1 + i // 60, i) for i in range(1, 1101)])
    assert how == "순서 기준" and len(pairs) == 1100 and pairs[700][0] == (701, "op", 701)
    pairs, how = collect.map_episodes(AOT, "tvdb", [(s, n) for s, c in {1: 25, 2: 12, 3: 22, 4: 28}.items()
                                                    for n in range(1, c + 1)])
    assert how == "시즌 기준" and [hit[0] for hit, _ in pairs] == list(range(1, 88))


def test_owner_of_rejects_out_of_range():
    assert collect.owner_of(AOT, 60) == (60, "f1", 1)
    assert collect.owner_of(AOT, 88) is None and collect.owner_of(AOT, 0) is None


def test_clean_html_removes_marked_spoilers():
    assert collect.clean_html("Tall.<br>~!He dies in the end.!~ <i>Kind</i> &amp; calm") == "Tall.\n Kind & calm"


def test_split_paragraphs():
    parts = collect.split_paragraphs("\n".join(["가" * 300] * 5 + ["A sentence. " * 200]))
    assert len(parts) > 3 and all(len(x) <= 1500 for x in parts)


def test_search_requires_watched():
    with pytest.raises(TypeError):
        collect.search_chunks(None, [0.0] * 768)                  # 본 회차 없이는 호출 자체가 안 됨
    with pytest.raises(TypeError):
        collect.search_chunks(None, [0.0] * 768, watched=None)


# ───────────────────────── 실제 PostgreSQL ─────────────────────────

MHA = "tmdb:65930"
SEASONS = {1: (21459, 31964, 13), 2: (21856, 33486, 25), 3: (100166, 36456, 25)}   # 시즌: (AniList, MAL, 회차 수)
OTHER = "entry:anilist:777"


def fake_download(url, name):
    if "offline" in name:
        data = [{"sources": [f"https://anilist.co/anime/{al}", f"https://myanimelist.net/anime/{mal}"],
                 "title": f"Boku no Hero Academia {s}", "type": "TV", "episodes": n, "status": "FINISHED",
                 "animeSeason": {"season": "SPRING", "year": 2015 + s}, "synonyms": ["나히아"], "tags": ["hero"]}
                for s, (al, mal, n) in SEASONS.items()]
        data.append({"sources": ["https://anilist.co/anime/777"], "title": "Other Show", "type": "TV", "episodes": 12,
                     "status": "FINISHED", "animeSeason": {"season": "FALL", "year": 2020}, "synonyms": [], "tags": []})
        # AniList 항목과 같은 작품인 MAL 단독 항목 → 중복이므로 무시되어야 함
        data.append({"sources": ["https://myanimelist.net/anime/31964"], "title": "dup", "type": "TV", "episodes": 13,
                     "status": "FINISHED", "animeSeason": {}, "synonyms": [], "tags": []})
        return {"data": data}
    return [{"anilist_id": al, "mal_id": mal, "tvdb_id": 305074, "themoviedb_id": {"tv": 65930},
             "season": {"tvdb": s, "tmdb": s}} for s, (al, mal, n) in SEASONS.items()]


calls = []


def fake_http(db, method, url, *, params=None, body=None, headers=None, cache=None, tries=4):
    calls.append(url)
    p = params or {}
    if "anilist" in url:
        if "id_in" in body["query"]:
            return {"data": {"Page": {"media": [
                {"id": al, "popularity": 900000 - s, "averageScore": 80, "genres": ["Action"],
                 "title": {"english": f"My Hero Academia {s}", "native": "僕のヒーローアカデミア"},
                 "coverImage": {"large": "https://example.com/c.jpg"}, "status": "FINISHED",
                 "nextAiringEpisode": None, "recommendations": {"nodes": [
                     {"rating": 5, "mediaRecommendation": {"id": 777}}, {"rating": -1, "mediaRecommendation": {"id": 1}}]},
                 "description": "Izuku <br> inherits <i>One For All</i>. ~!All Might retires.!~"}
                for s, (al, _, _) in SEASONS.items()]}}}
        chars = [{"role": "MAIN", "node": {"id": 36421 + body["variables"]["id"] % 2, "gender": "Male", "age": "14",
                                           "name": {"full": "Izuku Midoriya", "native": "緑谷出久"},
                                           "image": {"large": "https://example.com/i.jpg"},
                                           "description": "Green curly hair and freckles."}},
                 {"role": "SUPPORTING", "node": {"id": 99, "gender": "Female", "name": {"full": "Shimura Nana",
                                                                                     "native": "志村菜奈"},
                                                 "image": None, "description": "Seventh user of One For All."}}]
        return {"data": {"Media": {"characters": {"pageInfo": {"hasNextPage": False}, "edges": chars}}}}
    if "tvmaze.com/lookup" in url:
        return {"id": 13615}
    if "tvmaze.com/shows" in url:
        eps = [{"season": s, "number": n, "type": "regular", "name": f"Title {s}x{n}", "airdate": "2018-06-16",
                "summary": f"<p>Summary {s}x{n} &amp; more.</p>", "url": f"https://www.tvmaze.com/episodes/{s}{n}"}
               for s, (_, _, c) in SEASONS.items() for n in range(1, c + 1)]
        return eps + [{"season": 3, "number": None, "type": "significant_special", "name": "Special"}]
    if "themoviedb" in url:
        if url.endswith("/watch/providers"):
            return {"results": {"KR": {"flatrate": [{"provider_name": "Netflix"}, {"provider_name": "Laftel"}],
                                       "link": "https://www.themoviedb.org/tv/65930/watch?locale=KR"}}}
        if "/season/" in url:
            s = int(url.rsplit("/", 1)[1])
            return {"name": f"시즌 {s}", "episodes": [
                {"episode_number": n, "name": f"{s}기 {n}화", "overview": "한국어 줄거리" if n % 2 == 0 else "",
                 "still_path": "/still.jpg", "runtime": 24}
                for n in range(1, SEASONS[s][2] + 1)]}
        return {"name": "나의 히어로 아카데미아", "overview": "한국어 작품 소개", "poster_path": "/p.jpg",
                "genres": [{"name": "애니메이션"}], "keywords": {"results": [{"name": "superhero"}]},
                "alternative_titles": {"results": [{"iso_3166_1": "KR", "title": "히로아카"}]},
                "content_ratings": {"results": [{"iso_3166_1": "KR", "rating": "15"}]},
                "videos": {"results": [{"site": "YouTube", "type": "Trailer", "key": "abc", "iso_639_1": "ko"}]},
                "aggregate_credits": {"cast": [{"id": 1, "name": "Daiki Yamashita", "total_episode_count": 63,
                                                "roles": [{"character": "Izuku Midoriya (voice)", "episode_count": 63}]}]},
                "seasons": [{"season_number": s} for s in (0, *SEASONS)]}
    if "jikan" in url:
        mal = int(url.split("/anime/")[1].split("/")[0])
        count = next(c for _, m, c in SEASONS.values() if m == mal)
        return {"data": [{"mal_id": n, "filler": mal == 33486 and n == 13, "recap": False}
                         for n in range(1, count + 1)], "pagination": {"has_next_page": False}}
    if "fandom" in url:
        if p.get("generator") == "allpages":
            page = lambda title, text: {"title": title, "revisions": [{"slots": {"main": {"content": text}}}]}
            char = ("{{Character Infobox\n|name = Nana Shimura\n|quirk = Float\n|status = Deceased\n}}\n"
                    "Nana was the seventh user who dies before the story.\n\n==Appearance==\n"
                    + "Nana was a tall woman with black hair tied in a bun and a bright smile. " * 3
                    + "\n\n==History==\n" + "She was killed by All For One in a decisive battle. " * 3)
            return {"query": {"pages": [
                page("Nana Shimura", char), page("Mangaonly Person", char.replace("Nana", "Mangaonly")),
                page("Episode 30", WIKI.replace("[[Nana Shimura]]", "[[Nana Shimura]] [[Float]]")),
                page("Episode 5", WIKI.replace("[[Nana Shimura]]", "nobody")),
                page("Float", "{{Quirk Infobox\n|name = Float\n|user = Nana\n|type = Emitter\n}}\n"
                     + "Float lets the user levitate freely in the air at will. " * 3)]}}
        if p.get("meta") == "siteinfo":
            return {"query": {"rightsinfo": {"text": "CC-BY-SA"}}}
        pages = [{"title": f"Episode {n}", "revisions": [{"slots": {"main": {"content": WIKI.replace(
            "ep number = 49", f"ep number = {n}").replace("adolescence", "adolescence " + "long plot text " * 60)}}}]}
            for n in range(1, 61)]
        pages.append({"title": "Episode 1 (Vigilantes)", "revisions": [{"slots": {"main": {"content": WIKI}}}]})
        pages.append({"title": "List of Episodes", "revisions": [{"slots": {"main": {"content": "'''List'''"}}}]})
        return {"query": {"pages": pages}}
    raise AssertionError(url)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    info = psycopg.conninfo.conninfo_to_dict(collect.DB_URL)
    name = (info.get("dbname") or "aniwhere") + "_test"
    test_url = psycopg.conninfo.make_conninfo(collect.DB_URL, dbname=name)
    mp = pytest.MonkeyPatch()
    mp.setattr(collect, "DB_URL", test_url)
    try:
        collect.ensure_database()
        conn = collect.connect()
    except psycopg.OperationalError as e:
        mp.undo()
        pytest.skip(f"테스트용 PostgreSQL({name})에 접속할 수 없음: {str(e).splitlines()[0]}")
    assert conn.info.dbname.endswith("_test")     # 실제 수집 DB를 지우는 일이 없도록
    conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    mp.setattr(collect, "http", fake_http)
    mp.setattr(collect, "download", fake_download)
    mp.setattr(collect, "PROCESSED", tmp_path_factory.mktemp("processed"))
    mp.setenv("TMDB_API_KEY", "test")
    args = argparse.Namespace(limit=None, series=None, pages=None, types=["TV", "ONA"], refresh=False)
    for step in ("init", "seed", "anilist", "tvmaze", "tmdb", "jikan", "characters", "fandom", "wiki", "chunks",
                 "report", "status"):
        collect.STEPS[step](conn, args)
    # 임베딩 모델 없이 검색 SQL만 확인하기 위한 임의 벡터
    rng = random.Random(0)
    for r in conn.execute("SELECT chunk_id FROM chunks").fetchall():
        conn.execute("UPDATE chunks SET embedding = %s::vector WHERE chunk_id = %s",
                     (str([rng.uniform(-1, 1) for _ in range(768)]), r["chunk_id"]))
    yield conn, args
    conn.close()
    mp.undo()


def q(conn, sql, *a):
    return conn.execute(sql, a).fetchall()


def test_pipeline_links_every_source_to_abs_ep(db):
    conn, _ = db
    assert q(conn, "SELECT count(*) n FROM entries")[0]["n"] == 4          # 중복 항목은 빠짐
    e49 = q(conn, "SELECT * FROM episodes WHERE series_id=%s AND abs_ep=49", MHA)[0]
    assert (e49["entry_key"], e49["entry_ep"], e49["tmdb_season"], e49["tmdb_number"]) == ("anilist:100166", 11, 3, 11)
    assert e49["title_en"] == "Title 3x11" and e49["summary_en"] == "Summary 3x11 & more."
    assert e49["plot"] and e49["chapters"] == "Chapter 92, Chapter 93" and e49["arc"] == "Hideout Raid"
    assert q(conn, "SELECT filler FROM episodes WHERE series_id=%s AND abs_ep=26", MHA)[0]["filler"] is True
    assert q(conn, "SELECT count(*) n FROM episodes WHERE series_id=%s", MHA)[0]["n"] == 63
    assert q(conn, "SELECT title_ko, popularity, poster_url, status FROM series WHERE series_id=%s", MHA)[0] == {
        "title_ko": "나의 히어로 아카데미아", "popularity": 899999, "status": "FINISHED",
        "poster_url": "https://image.tmdb.org/t/p/w500/p.jpg"}
    extra = q(conn, "SELECT genres_ko, alt_titles, content_rating_kr, trailer_url FROM series WHERE series_id=%s", MHA)[0]
    assert extra == {"genres_ko": ["애니메이션"], "alt_titles": ["히로아카"], "content_rating_kr": "15",
                     "trailer_url": "https://www.youtube.com/watch?v=abc"}
    assert q(conn, "SELECT name, character FROM voice_cast WHERE series_id=%s", MHA) == [
        {"name": "Daiki Yamashita", "character": "Izuku Midoriya"}]
    assert q(conn, "SELECT count(*) n FROM seasons WHERE series_id=%s", MHA)[0]["n"] == 3
    assert (e49["still_url"], e49["runtime"]) == ("https://image.tmdb.org/t/p/w300/still.jpg", 24)
    assert q(conn, "SELECT recommendations r FROM entries WHERE anilist_id=21459")[0]["r"] == [777]
    summary = q(conn, "SELECT text FROM chunks WHERE chunk_id=%s", f"{MHA}:summary:anilist:21459")[0]["text"]
    assert "한국어 작품 소개" in summary
    types = {r["type"]: r["n"] for r in q(conn, "SELECT type, count(*) n FROM chunks GROUP BY 1")}
    assert types["episode"] == 63 and types["streaming"] == 3 and types["character"] == 6 and types["terminology"] == 1 and types["event"] >= 60
    detail = q(conn, "SELECT detail FROM fetch_log WHERE series_id=%s AND source='fandom'", MHA)[0]["detail"]
    assert detail.startswith("60화 (상세 줄거리 60화)") and "CC-BY-SA" in detail


def test_marked_spoilers_never_reach_chunks(db):
    conn, _ = db
    assert not q(conn, "SELECT 1 FROM chunks WHERE text LIKE '%%retires%%'")


def test_resume_skips_finished_series(db):
    conn, args = db
    calls.clear()
    collect.STEPS["tvmaze"](conn, args)
    assert not calls


def test_embedding_kept_until_text_changes(db):
    conn, args = db
    conn.execute("UPDATE episodes SET summary_en='changed' WHERE series_id=%s AND abs_ep=1", (MHA,))
    collect.STEPS["chunks"](conn, args)
    assert q(conn, "SELECT count(*) FILTER (WHERE embedding IS NULL) n FROM chunks")[0]["n"] == 1
    conn.execute("UPDATE chunks SET embedding = array_fill(0.1, ARRAY[768])::vector WHERE embedding IS NULL")


@pytest.mark.parametrize("watched", [0, 1, 13, 14, 38, 49, 63])
def test_no_chunk_after_watched_episode(db, watched):
    """N화까지 봤으면 N+1화 이후 청크는 검색 결과에 절대 나오지 않는다."""
    conn, _ = db
    rng = random.Random(watched)
    total = q(conn, "SELECT count(*) n FROM chunks")[0]["n"]
    for _ in range(5):
        vec = [rng.uniform(-1, 1) for _ in range(768)]
        rows = collect.search_chunks(conn, vec, watched={MHA: watched}, k=total)   # 걸러진 전체를 다 받아 봄
        assert rows and all(r["abs_ep"] is None or r["abs_ep"] <= watched for r in rows)
        allowed = q(conn, "SELECT count(*) n FROM chunks WHERE abs_ep IS NULL OR "
                          "(series_id=%s AND abs_ep <= %s)", MHA, watched)[0]["n"]
        assert len(rows) == allowed            # 볼 수 있는 청크는 빠짐없이 검색 대상


def test_later_season_summary_and_characters_are_hidden(db):
    conn, _ = db
    hidden = {r["chunk_id"] for r in collect.search_chunks(conn, [0.1] * 768, watched={MHA: 12}, k=1000)}
    assert f"{MHA}:summary:anilist:21459" in hidden          # 1기 소개는 항상 보임
    assert f"{MHA}:summary:anilist:21856" not in hidden      # 2기 소개는 1기(13화)를 다 본 뒤부터
    after = {r["chunk_id"] for r in collect.search_chunks(conn, [0.1] * 768, watched={MHA: 13}, k=1000)}
    assert f"{MHA}:summary:anilist:21856" in after


def test_series_without_record_shows_only_episode_free_chunks(db):
    conn, _ = db
    rows = collect.search_chunks(conn, [0.1] * 768, watched={}, k=1000)
    assert rows and all(r["abs_ep"] is None for r in rows)
    rows = collect.search_chunks(conn, [0.1] * 768, watched={MHA: 49}, series_id=MHA, types=["event"], k=1000)
    assert rows and {r["type"] for r in rows} == {"event"} and max(r["abs_ep"] for r in rows) == 49


def test_character_debut_episode_from_fandom(db):
    """위키 등장 순서에 이름이 있으면(성·이름 순서 무관) 첫 등장 회차를 기록하고, 없으면 시즌 단위로 가림."""
    conn, _ = db
    rows = {r["name"]: r["first_abs_ep"] for r in q(conn, "SELECT name, first_abs_ep FROM characters WHERE series_id=%s", MHA)}
    assert rows == {"Shimura Nana": 1, "Izuku Midoriya": None}
    conn.execute("UPDATE episodes SET characters = '{}' WHERE series_id=%s AND abs_ep < 30", (MHA,))
    collect.STEPS["chunks"](conn, argparse.Namespace(limit=None, series=MHA))
    assert q(conn, "SELECT abs_ep FROM chunks WHERE chunk_id=%s", f"{MHA}:char:99")[0]["abs_ep"] == 30
    conn.execute("UPDATE chunks SET embedding = array_fill(0.1, ARRAY[768])::vector WHERE embedding IS NULL")
    ids = lambda w: {r["chunk_id"] for r in collect.search_chunks(conn, [0.1] * 768, watched={MHA: w}, k=1000)}
    assert f"{MHA}:char:99" not in ids(29) and f"{MHA}:char:99" in ids(30)


def test_per_season_infobox_numbers_are_not_trusted():
    """시즌마다 1화부터 다시 세는 위키: 제목으로 맞춘 번호와 인포박스 번호가 어긋나면 인포박스 번호를 버림."""
    page = lambda title, no, nxt=None: (title, {"title": title, "episode_no": no, "infobox": {"next": nxt} if nxt else {}})
    pages = [page("A", 1, "B"), page("B", 2, "C"), page("C", 1, "D"), page("D", 2), page("Lost", 2)]
    by_title = {"a": 1, "b": 2, "c": 13}
    assert collect.number_pages(pages, by_title) == {"A": 1, "B": 2, "C": 13, "D": 14}


def test_wiki_pages_become_gated_chunks(db):
    """위키 문서는 처음 가리킨 회차부터 보이고, 내력(History) 구역과 애니에 안 나온 문서는 청크가 되지 않는다."""
    conn, _ = db
    kinds = {r["title"]: r["kind"] for r in q(conn, "SELECT title, kind FROM wiki_pages")}
    assert kinds["Nana Shimura"] == "character" and kinds["Float"] == "ability" and kinds["Episode 30"] == "episode"
    rows = q(conn, "SELECT chunk_id, type, abs_ep, text FROM chunks WHERE chunk_id LIKE %s ORDER BY 1", f"{MHA}:wiki:%")
    assert [(r["chunk_id"].split(":")[3], r["type"], r["abs_ep"]) for r in rows] == [
        ("Float", "terminology", 30), ("Nana Shimura", "character", 30)]
    text = " ".join(r["text"] for r in rows)
    assert "black hair" in text and "killed by" not in text and "dies before" not in text and "Mangaonly" not in text
