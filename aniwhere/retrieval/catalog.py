"""작품 목록에서 읽는 정보: 제목으로 작품 찾기, 회차 이름, 시청처. 줄거리(청크)는 search.py로만 읽습니다."""
import json
import re

from aniwhere.config import REPO

ALIASES = REPO / "data" / "curated" / "aliases.json"     # 사람이 적은 줄임말: {"나히아": "tmdb:65930"}
HANGUL_RE = re.compile(r"[가-힣]")

_names_cache: dict[str, list] = {}


class UnknownSeries(ValueError):
    """DB에 없는 series_id. API는 이 예외를 404로 바꿉니다 (그 외 ValueError는 400)."""


def norm(text) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower())


def _names(db):
    """[(정규화한 이름, 시리즈 ID, 인기도, 대표 제목인지)] — 대표 제목: 한국어·로마자·영어 제목과 사람이 적은 줄임말."""
    key = db.info.dsn
    if key not in _names_cache:
        rows = []
        pop = {}
        for s in db.execute("SELECT series_id, title, title_ko, title_original, alt_titles, popularity FROM series"):
            pop[s["series_id"]] = s["popularity"] or 0
            rows += [(norm(n), s["series_id"], True) for n in (s["title_ko"], s["title"]) if n]
            rows += [(norm(n), s["series_id"], False) for n in [s["title_original"], *(s["alt_titles"] or [])] if n]
        for e in db.execute("SELECT series_id, order_in_series, title, title_en, synonyms FROM entries"):
            first = e["order_in_series"] == 1
            rows += [(norm(n), e["series_id"], first and n == e["title_en"])
                     for n in [e["title"], e["title_en"], *(e["synonyms"] or [])] if n]
        if ALIASES.exists():
            rows += [(norm(n), sid, True) for n, sid in json.loads(ALIASES.read_text(encoding="utf-8")).items()
                     if sid in pop]
        _names_cache[key] = [(n, sid, pop.get(sid, 0), main) for n, sid, main in dict.fromkeys(rows) if n]
    return _names_cache[key]


def mentioned_series(db, text) -> list[str]:
    """글 안에 제목(또는 줄임말)이 그대로 들어 있는 작품. 긴 제목이 먼저, 같으면 인기순."""
    hay = norm(text)
    found = {}
    for name, sid, pop, main in _names(db):
        # 짧은 영문 제목('K', 'Another')은 다른 말에 우연히 들어 있기 쉬워 5자 이상만
        if main and len(name) >= (2 if HANGUL_RE.search(name) else 5) and name in hay:
            found[sid] = max(found.get(sid, (0, 0, "")), (len(name), pop, name))
    # 더 긴 제목 안에 들어 있는 짧은 제목은 뺌 ('진격의 거인'을 물었는데 '거인'이라는 작품까지 잡히지 않게)
    longer = [v[2] for v in found.values()]
    keep = [s for s, v in found.items() if not any(v[2] != x and v[2] in x for x in longer)]
    return sorted(keep, key=lambda s: found[s], reverse=True)


def find_series(db, title, limit=3) -> list[str]:
    """제목 한 개로 작품 찾기: 같은 이름 → 포함하는 이름 순, 같으면 인기순."""
    want = norm(title)
    if len(want) < 2:
        return []
    best = {}
    for name, sid, pop, _ in _names(db):
        if name == want:
            rank = 2
        elif len(want) >= 3 and (want in name or (len(name) >= 4 and name in want)):
            rank = 1
        else:
            continue
        best[sid] = max(best.get(sid, (0, 0)), (rank, pop))
    return sorted(best, key=lambda s: best[s], reverse=True)[:limit]


def series_info(db, series_id) -> dict | None:
    s = db.execute("""SELECT series_id, title, title_ko, overview_ko, poster_url, status, next_episode_at,
                             total_episodes, genres_ko, first_air_date
                      FROM series WHERE series_id = %s""", (series_id,)).fetchone()
    if s:
        s["name"] = s["title_ko"] or s["title"]
    return s


def list_series(db, query=None, limit=50) -> list[dict]:
    """화면의 작품 선택 목록. query가 있으면 제목에 그 말이 들어간 작품만, 인기순."""
    rows = db.execute("""SELECT series_id, coalesce(title_ko, title) AS name, title, total_episodes
                         FROM series ORDER BY popularity DESC NULLS LAST""").fetchall()
    if query:
        want = norm(query)
        rows = [r for r in rows if want in norm(r["name"]) or want in norm(r["title"])]
    return rows[:limit]


def episode_label(ep) -> str:
    """'3기 11화 (전체 49화) 〈원 포 올〉' — 청크 머리말과 같은 표기."""
    title = ep.get("title_ko") or ep.get("title_en") or ep.get("fandom_title")
    return (f"{ep['tmdb_season']}기 {ep['tmdb_number']}화 " if ep.get("tmdb_season") else "") + \
        f"(전체 {ep['abs_ep']}화)" + (f" 〈{title}〉" if title else "")


def episodes(db, series_id, abs_eps) -> dict[int, dict]:
    """회차 번호 → 회차 이름 정보. 제목과 번호만 읽고 줄거리는 읽지 않습니다."""
    rows = db.execute("""SELECT abs_ep, tmdb_season, tmdb_number, title_ko, title_en, fandom_title, airdate, still_url
                         FROM episodes WHERE series_id = %s AND abs_ep = ANY(%s)""",
                      (series_id, list(abs_eps))).fetchall()
    return {r["abs_ep"]: {**r, "label": episode_label(r)} for r in rows}


def streaming(db, series_id) -> list[dict]:
    """시즌별 국내 구독형 제공처와 확인일 (TMDB가 전달하는 JustWatch 정보)."""
    return db.execute(
        """SELECT st.tmdb_season, coalesce(st.season_name, se.name_ko, st.tmdb_season || '기') AS name,
                  st.flatrate AS providers, st.checked_at, st.link
           FROM streaming st LEFT JOIN seasons se USING (series_id, tmdb_season)
           WHERE st.series_id = %s ORDER BY st.tmdb_season""", (series_id,)).fetchall()


def character_cards(db, series_id, char_ids) -> dict[int, dict]:
    rows = db.execute("""SELECT anilist_char, name, name_native, role, image_url FROM characters
                         WHERE series_id = %s AND anilist_char = ANY(%s)""", (series_id, list(char_ids))).fetchall()
    return {r["anilist_char"]: r for r in rows}


def similar_by_tags(db, genres, tags, exclude=(), limit=30) -> list[dict]:
    """장르·태그가 많이 겹치는 작품 (1기 항목 기준). 겹치는 수 → 평점 → 인기순."""
    return db.execute(
        """SELECT s.series_id, coalesce(s.title_ko, s.title) AS name, e.genres, e.average_score, s.poster_url,
                  (SELECT count(*) FROM unnest(e.genres) g WHERE lower(g) = ANY(%(genres)s)) * 2
                  + (SELECT count(*) FROM unnest(e.tags) t WHERE lower(t) = ANY(%(tags)s)) AS overlap
           FROM series s JOIN entries e ON e.series_id = s.series_id AND e.order_in_series = 1
           WHERE NOT (s.series_id = ANY(%(exclude)s))
           ORDER BY overlap DESC, e.average_score DESC NULLS LAST, s.popularity DESC NULLS LAST
           LIMIT %(limit)s""",
        {"genres": [g.lower() for g in genres], "tags": [t.lower() for t in tags], "exclude": list(exclude),
         "limit": limit}).fetchall()
