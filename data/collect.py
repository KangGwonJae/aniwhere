"""AniWhere 데이터 수집기 (PostgreSQL + pgvector, 1만 개 작품 규모).

    python data/collect.py init                 # 0. 테이블 생성 (schema.sql)
    python data/collect.py seed                 # 1. 작품 목록 자동 생성 (anime-offline-database + Fribb 매핑)
    python data/collect.py anilist              # 2. 인기도·설명·장르 (목록의 ID를 50개씩 조회)
    python data/collect.py tvmaze  --limit 300  # 3. 회차 목록·영어 요약 (인기순 상위 300개 시리즈)
    python data/collect.py tmdb    --limit 300  # 4. 한국어 회차명·줄거리, 국내 OTT (TMDB_API_KEY 필요)
    python data/collect.py jikan   --limit 300  # 5. 필러·총집편
    python data/collect.py characters --limit 300  # 6. 주요 캐릭터 설명 (AniList)
    python data/collect.py fandom-find --limit 300  # 7-0. 인기작의 Fandom 위키를 자동으로 찾아 fandom_wikis.json에 추가
    python data/collect.py fandom               # 7. 상세 줄거리 (fandom_wikis.json에 적은 작품만)
    python data/collect.py wiki                 # 7-1. 그 위키들의 모든 문서 (캐릭터·용어·장소 …) → wiki_pages
    python data/collect.py chunks               # 8. 검색 청크 생성/갱신
    python data/collect.py embed   --limit 300  # 9. 청크 임베딩 (config/settings.yaml의 embedding)
    python data/collect.py report               # 수집 현황 → data/processed/report.md
    python data/collect.py status --limit 300   # 진행률 (상위 300개 기준, 다른 터미널에서 수시로 확인 가능)
    python data/collect.py search "질문" --series tmdb:65930 --watched 49   # 스포일러 차단 검색 확인

단계는 여러 개를 한 번에 적을 수 있습니다: python data/collect.py init seed anilist

공통 옵션
    --limit N      인기순 상위 N개 시리즈만 (기본: 전체)
    --series ID    특정 시리즈만 (예: tmdb:65930)
    --refresh      이미 받은 것도 다시 받기
    --reparse      새로 받지 않고, 이미 받은 원본(raw 캐시)으로 다시 정리

DB 연결과 API 키는 저장소 루트의 .env에서 읽습니다 (DATABASE_URL, TMDB_API_KEY, ANIWHERE_UA).
모든 단계는 중간에 멈춰도 다시 실행하면 이어서 진행합니다 (fetch_log 테이블).
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import psycopg.conninfo
import psycopg.sql
import requests
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DATA = Path(__file__).resolve().parent
REPO = DATA.parent
RAW = DATA / "raw"
PROCESSED = DATA / "processed"


def _load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#") and m.group(2):
            os.environ.setdefault(m.group(1), m.group(2).strip("\"'"))


_load_env(REPO / ".env")
DB_URL = os.environ.get("DATABASE_URL", "postgresql:///aniwhere")
USER_AGENT = os.environ.get(
    "ANIWHERE_UA", "AniWhereCollector/0.3 (student project; https://github.com/KangGwonJae/aniwhere)")

AOD_URL = ("https://github.com/manami-project/anime-offline-database/releases/latest/download/"
           "anime-offline-database-minified.json")
FRIBB_URL = "https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json"

# 출처별 최소 요청 간격(초) — 각 서비스 안내보다 보수적으로
MIN_INTERVAL = {
    "graphql.anilist.co": 2.1,     # 분당 30회 이하
    "api.tvmaze.com": 0.6,         # 10초에 20회 이상 허용
    "api.jikan.moe": 1.1,          # 초당 3회, 분당 60회
    "api.themoviedb.org": 0.05,
    "fandom.com": 1.0,             # 공식 수치 없음 → 1초에 1회
}
LICENSES = {
    "anilist": ("AniList", "AniList API Terms"),
    "tvmaze": ("TVmaze", "CC BY-SA 4.0"),
    "tmdb": ("TMDB", "TMDB API Terms (비상업, 로고·고지 필요)"),
    "justwatch": ("JustWatch via TMDB", "JustWatch 출처 표기 필수"),
    "jikan": ("MyAnimeList via Jikan", "MyAnimeList 이용약관"),
    "fandom": ("Fandom", "CC BY-SA 3.0"),
}
MAX_CONSECUTIVE_ERRORS = 8   # 한 출처가 연속으로 이만큼 실패하면 그 단계를 멈춤 (서비스 장애·차단)

REFRESH = False
REPARSE = False   # 이미 받은 원본(raw 캐시)으로 다시 정리
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last_call: dict[str, float] = {}


# ───────────────────────── 공통 ─────────────────────────

def connect():
    return psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True)


def _host_key(url):
    host = urlparse(url).hostname or ""
    for key in MIN_INTERVAL:
        if host == key or host.endswith("." + key):
            return key
    return host


def http(db, method, url, *, params=None, body=None, headers=None, cache=None, tries=4):
    """요청 → JSON. cache=(source, key)면 raw 테이블에 저장하고 재사용. 404 → None."""
    if cache and not REFRESH:
        row = db.execute("SELECT data FROM raw WHERE source=%s AND key=%s", cache).fetchone()
        if row:
            return row["data"]
    host = _host_key(url)
    last = "응답 없음"
    for attempt in range(tries):
        wait = MIN_INTERVAL.get(host, 0.5) - (time.time() - _last_call.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.time()
        try:
            r = _session.request(method, url, params=params, json=body, headers=headers, timeout=(10, 60))
        except requests.RequestException as e:
            last = e.__class__.__name__
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            data = None
        elif r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            delay = min(int(r.headers.get("Retry-After") or 2 ** (attempt + 2)), 90)
            print(f"    ! {r.status_code} 응답, {delay}초 대기")
            time.sleep(delay)
            continue
        else:
            r.raise_for_status()
            data = r.json()
        if cache:
            db.execute("""INSERT INTO raw (source, key, data) VALUES (%s, %s, %s)
                          ON CONFLICT (source, key) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()""",
                       (*cache, Jsonb(data)))
        return data
    raise RuntimeError(f"요청 실패 ({last}): {url}")


def download(url, name):
    path = RAW / name
    if not path.exists() or REFRESH:
        print(f"  {name} 다운로드 중…")
        RAW.mkdir(exist_ok=True)
        r = _session.get(url, timeout=600)
        r.raise_for_status()
        path.write_bytes(r.content)
    return json.loads(path.read_text(encoding="utf-8"))


PLACEHOLDER_RE = re.compile(r"(to be added|tba|tbd|coming soon|n/?a|none|\?+|under construction)[.!]?", re.I)
EPISODE_N_RE = re.compile(r"(에피소드|episode|제)\s*\d+\s*(화|회)?", re.I)      # TMDB가 제목 대신 넣어 둔 '에피소드 3'


def clean_chunk_body(text):
    """청크 본문에 남은 마크업을 지움: AniList의 마크다운·스포일러 표시, 위키 문법, 줄 머리의 쉼표."""
    text = re.sub(r"~!.*?!~", " ", text or "", flags=re.S)
    text = text.replace("~!", " ").replace("!~", " ")
    text = re.sub(r"!?\[([^\]\n]*)\]\((?:https?://|/)[^)\s]*\)", r"\1", text)      # [All Might](https://…) → All Might
    text = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|</?[a-z][^>\n]{0,80}>", " ", text, flags=re.S | re.I)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\{\{|\}\}|\[\[|\]\]|'{2,}|__|\*\*", "", text)
    text = re.sub(r"(?m)^[ \t]*[,;:][ \t]*", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def tidy_chunks(rows):
    """build_chunks가 만든 청크를 다듬음: 본문 정리, 내용이 없는 청크와 같은 내용이 되풀이되는 청크 제거."""
    kept, by_body = [], {}
    for chunk_id, kind, abs_ep, season, filler, text, sources in rows:
        head, _, body = text.partition("\n")
        if kind in ("summary", "streaming"):
            kept.append((chunk_id, kind, abs_ep, season, filler, clean_chunk_body(text), sources))
            continue
        lines = [x for x in clean_chunk_body(body).split("\n")
                 if not PLACEHOLDER_RE.fullmatch(x.strip()) and not (kind == "episode" and EPISODE_N_RE.fullmatch(x.strip()))]
        body = "\n".join(lines)
        if len(body) < (20 if kind == "episode" else 50):       # '센타로의 할머니.' 한 줄짜리, 'TBA.' 같은 자리채움
            continue
        head = re.sub(r" 〈" + EPISODE_N_RE.pattern + r"〉", "", head)
        row = (chunk_id, kind, abs_ep, season, filler, f"{head}\n{body}", sources)
        if kind == "character":               # 캐릭터는 설명이 같아도 다른 인물일 수 있고, 첫 등장 회차를 늦추면 안 됨
            kept.append(row)
            continue
        # 같은 종류의 청크가 같은 본문이면 하나만 남김 (문서 하나가 여러 화에 붙은 경우 등).
        # 스포일러를 막기 위해 가장 늦은 회차에 붙은 것을 남김
        same = by_body.get((kind, body))
        if same is None:
            by_body[(kind, body)] = len(kept)
            kept.append(row)
        elif (abs_ep or 0) > (kept[same][2] or 0):
            kept[same] = row
    return kept


def clean_html(text):
    """AniList·TVmaze 설명 → 일반 텍스트. AniList의 스포일러 표시 구간(~! … !~)은 통째로 지움."""
    if not text:
        return ""
    text = re.sub(r"~!.*?!~", " ", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def as_date(s):
    try:
        return dt.date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def targets(db, source, args, where="TRUE", redo=False):
    """인기순으로 처리할 시리즈 목록. 이미 ok/empty인 것은 건너뜀 (--refresh, redo 제외)."""
    sql = f"""SELECT s.* FROM series s
              LEFT JOIN fetch_log f ON f.series_id = s.series_id AND f.source = %(src)s
              WHERE ({where})
                AND (%(sid)s::text IS NULL OR s.series_id = %(sid)s)
                AND (%(redo)s OR f.status IS NULL OR f.status = 'error')
              ORDER BY s.popularity DESC NULLS LAST, s.series_id"""
    rows = db.execute(sql, {"src": source, "sid": args.series, "redo": redo or REFRESH or REPARSE}).fetchall()
    if args.limit and not args.series:  # 상위 N개 '안에서' 아직 안 한 것만
        top = {r["series_id"] for r in db.execute(
            "SELECT series_id FROM series ORDER BY popularity DESC NULLS LAST, series_id LIMIT %s",
            (args.limit,))}
        rows = [r for r in rows if r["series_id"] in top]
    return rows


def log(db, series_id, source, status, detail=None):
    db.execute("""INSERT INTO fetch_log (series_id, source, status, detail) VALUES (%s,%s,%s,%s)
                  ON CONFLICT (series_id, source) DO UPDATE
                  SET status=EXCLUDED.status, detail=EXCLUDED.detail, fetched_at=now()""",
               (series_id, source, status, detail))


def run_each(db, source, rows, fn):
    """시리즈마다 fn 실행. 하나가 실패해도 나머지는 계속, 연속으로 실패하면 단계를 멈춤."""
    total, streak, started = len(rows), 0, time.time()
    if not total:
        print("  새로 처리할 시리즈가 없습니다")
    for i, s in enumerate(rows, 1):
        try:
            with db.transaction():
                status, detail = fn(s)
        except Exception as e:  # noqa: BLE001 — 한 작품 실패가 전체를 멈추지 않게
            status, detail = "error", f"{e.__class__.__name__}: {e}"[:500]
        log(db, s["series_id"], source, status, detail)
        streak = streak + 1 if status == "error" else 0
        if i % 10 == 0 or i == total or status == "error":
            left = (time.time() - started) / i * (total - i)
            print(f"  [{i}/{total}, 남은 시간 약 {left / 60:.0f}분] {s['title'][:40]} → {status} {detail or ''}",
                  flush=True)
        if streak >= MAX_CONSECUTIVE_ERRORS:
            print(f"  ! {source}: 연속 {streak}번 실패해서 멈춥니다. 나중에 같은 명령을 다시 실행하면 이어서 받습니다.")
            break


def entries_of(db, series_id):
    return db.execute("SELECT * FROM entries WHERE series_id=%s ORDER BY order_in_series",
                      (series_id,)).fetchall()


class SeasonMap:
    """'외부 출처의 (시즌 s, 그 시즌 k번째 회차)' → (전체 회차 번호, 시즌 항목, 항목 안 회차).

    매핑 데이터에 시작 위치(offset)가 있으면 그대로 쓰고, 없으면 같은 시즌을 나눠 쓰는 항목들을
    방영 순서대로 이어 붙입니다 (진격 3기 Part 1·2).
    """

    def __init__(self, entries, src):
        self.slots = {}
        for e in entries:
            s = e[f"{src}_season"]
            if not s:
                continue
            slot = self.slots.setdefault(s, [])
            start = e[f"{src}_offset"]
            if start is None:
                start = max((x["_end"] or x["_start"] for x in slot), default=0)
            slot.append({**e, "_start": start, "_end": start + e["episodes"] if e["episodes"] else None})

    def lookup(self, season, k):
        for e in self.slots.get(season, []):
            if e["_start"] < k and (e["_end"] is None or k <= e["_end"]):
                local = k - e["_start"]
                return e["abs_offset"] + local, e["entry_key"], local
        return None


def _still_airing(entries, e):
    """방영 중인 마지막 항목은 목록의 회차 수보다 실제 회차가 더 많을 수 있음."""
    return e is entries[-1] and (not e["episodes"] or e.get("status") == "ONGOING")


def owner_of(entries, abs_ep):
    """전체 회차 번호 → (전체 회차 번호, 시즌 항목, 항목 안 회차). 범위를 벗어나면 None."""
    if not abs_ep or abs_ep < 1:
        return None
    e = next((e for e in reversed(entries) if abs_ep > e["abs_offset"]), None)
    if not e or (e["episodes"] and abs_ep > e["abs_offset"] + e["episodes"] and not _still_airing(entries, e)):
        return None
    return abs_ep, e["entry_key"], abs_ep - e["abs_offset"]


def map_episodes(entries, src, eps):
    """외부 출처의 본편 회차 목록 [(시즌, 회차 데이터)] (방영 순서) → [((abs_ep, entry_key, entry_ep), 회차 데이터)].

    먼저 시즌 단위로 맞추고, 시즌 나눔이 달라 90% 미만만 맞으면 1화부터 순서대로 이어 붙입니다
    (원피스처럼 AniList는 한 항목인데 출처는 여러 시즌으로 나눈 작품).
    """
    smap, counter, by_season = SeasonMap(entries, src), {}, []
    for season, ep in eps:
        counter[season] = counter.get(season, 0) + 1
        hit = smap.lookup(season, counter[season])
        if hit:
            by_season.append((hit, ep))
    if len(by_season) >= 0.9 * len(eps):
        return by_season, "시즌 기준"
    total = sum(e["episodes"] or 0 for e in entries)
    if len(eps) <= total or _still_airing(entries, entries[-1]):
        in_order = [(owner_of(entries, i), ep) for i, (_, ep) in enumerate(eps, 1)]
        in_order = [(hit, ep) for hit, ep in in_order if hit]
        if len(in_order) > len(by_season):
            return in_order, "순서 기준"
    return by_season, "시즌 기준"


def upsert_episode(db, series_id, abs_ep, entry_key, entry_ep, **cols):
    names = ["series_id", "abs_ep", "entry_key", "entry_ep", *cols]
    sets = ", ".join(f"{c}=EXCLUDED.{c}" for c in ["entry_key", "entry_ep", *cols])
    db.execute(f"""INSERT INTO episodes ({", ".join(names)}) VALUES ({", ".join(["%s"] * len(names))})
                   ON CONFLICT (series_id, abs_ep) DO UPDATE SET {sets}""",
               (series_id, abs_ep, entry_key, entry_ep, *cols.values()))


# ───────────────────────── 1. seed: 작품 목록 ─────────────────────────

SEASON_ORDER = {"WINTER": 1, "SPRING": 2, "SUMMER": 3, "FALL": 4}


def _src_id(sources, host):
    for s in sources:
        if host in s:
            tail = s.rstrip("/").rsplit("/", 1)[-1]
            return int(tail) if tail.isdigit() else None
    return None


def step_seed(db, args):
    aod = download(AOD_URL, "anime-offline-database.json")["data"]
    fribb = download(FRIBB_URL, "anime-list-full.json")
    by_al = {f["anilist_id"]: f for f in fribb if f.get("anilist_id")}
    by_mal = {f["mal_id"]: f for f in fribb if f.get("mal_id")}

    aod_anilist = {_src_id(a["sources"], "anilist.co") for a in aod}
    groups: dict[str, list] = {}
    for a in aod:
        if a["type"] not in args.types or a["status"] == "UPCOMING":
            continue
        al, mal = _src_id(a["sources"], "anilist.co"), _src_id(a["sources"], "myanimelist.net")
        if not (al or mal):
            continue
        f = by_al.get(al) or by_mal.get(mal) or {}
        if not al and f.get("anilist_id") and f["anilist_id"] in aod_anilist:
            continue    # 같은 작품이 AniList 항목으로 따로 들어 있음 (목록 쪽 중복)
        tmdb = (f.get("themoviedb_id") or {}).get("tv") if isinstance(f.get("themoviedb_id"), dict) else None
        season, offset = f.get("season") or {}, f.get("episode_offset") or {}
        key = f"anilist:{al}" if al else f"mal:{mal}"
        e = {
            "entry_key": key, "anilist_id": al, "mal_id": mal,
            "type": a["type"], "status": a["status"], "title": a["title"],
            "synonyms": a.get("synonyms", [])[:40], "tags": a.get("tags", [])[:40],
            "year": a.get("animeSeason", {}).get("year"),
            "season_of_year": a.get("animeSeason", {}).get("season"),
            "episodes": a.get("episodes") or None,
            "tmdb_season": season.get("tmdb"), "tmdb_offset": offset.get("tmdb"),
            "tvdb_season": season.get("tvdb"), "tvdb_offset": offset.get("tvdb"),
            "tvdb_id": f.get("tvdb_id"), "tmdb_id": tmdb,
        }
        # TMDB 시즌 0(스페셜)에 붙은 항목은 본편 순서에 넣지 않고 따로 둠
        sid = f"tmdb:{tmdb}" if tmdb and e["tmdb_season"] != 0 else f"entry:{key}"
        groups.setdefault(sid, []).append(e)

    cols = ["entry_key", "series_id", "order_in_series", "abs_offset", "anilist_id", "mal_id",
            "type", "status", "title", "synonyms", "tags", "year", "season_of_year",
            "episodes", "tmdb_season", "tmdb_offset", "tvdb_season", "tvdb_offset"]
    n_entries = 0
    with db.transaction():
        for sid, es in groups.items():
            # 방영 순서. 매핑의 시즌 번호는 출처마다 달라서(주술회전 3기 = TMDB 시즌 1) 정렬 기준으로 쓰지 않음
            es.sort(key=lambda e: (e["year"] or 9999, SEASON_ORDER.get(e["season_of_year"], 5),
                                   e["tmdb_season"] or 999, e["tmdb_offset"] or 0, e["title"]))
            offset = 0
            for i, e in enumerate(es, 1):
                e["order_in_series"], e["abs_offset"] = i, offset
                offset += e["episodes"] or 0
            first = es[0]
            db.execute("""INSERT INTO series (series_id, title, tmdb_id, tvdb_id, total_episodes)
                          VALUES (%s,%s,%s,%s,%s)
                          ON CONFLICT (series_id) DO UPDATE SET title=EXCLUDED.title, tmdb_id=EXCLUDED.tmdb_id,
                            tvdb_id=EXCLUDED.tvdb_id, total_episodes=EXCLUDED.total_episodes""",
                       (sid, first["title"], first["tmdb_id"],
                        next((e["tvdb_id"] for e in es if e["tvdb_id"]), None), offset))
            for e in es:
                vals = [e["entry_key"], sid, *(e[c] for c in cols[2:])]
                db.execute(f"""INSERT INTO entries ({", ".join(cols)}) VALUES ({", ".join(["%s"] * len(cols))})
                               ON CONFLICT (entry_key) DO UPDATE SET {", ".join(f"{c}=EXCLUDED.{c}" for c in cols[1:])}""",
                           vals)
                n_entries += 1
        # 다시 seed했을 때 다른 시리즈로 옮겨간 빈 시리즈 정리
        db.execute("DELETE FROM series s WHERE NOT EXISTS (SELECT 1 FROM entries e WHERE e.series_id = s.series_id)")
    print(f"  시리즈 {len(groups):,}개, 시즌 항목 {n_entries:,}개, 회차 {sum(e['episodes'] or 0 for es in groups.values() for e in es):,}개 "
          f"(TMDB로 묶인 시리즈 {sum(1 for k in groups if k.startswith('tmdb:')):,}개)")


# ───────────────────────── 2. AniList: 인기도·설명 ─────────────────────────

ANILIST = "https://graphql.anilist.co"
SWEEP_QUERY = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(type: ANIME, id_in: $ids) {
      id popularity averageScore genres status
      title { english native }
      coverImage { large }
      nextAiringEpisode { airingAt }
      recommendations(sort: RATING_DESC, perPage: 8) { nodes { rating mediaRecommendation { id } } }
      description(asHtml: false)
    }
  }
}"""


def step_anilist(db, args):
    """우리 목록의 AniList ID를 50개씩 묶어 조회 (인기순 전체 훑기는 AniList가 5,000건까지만 허용)."""
    ids = [r["anilist_id"] for r in db.execute(
        """SELECT anilist_id FROM entries WHERE anilist_id IS NOT NULL
             AND (%s OR popularity IS NULL) ORDER BY anilist_id""", (REFRESH,))]
    batches = [ids[i:i + 50] for i in range(0, len(ids), 50)]
    if args.pages:
        batches = batches[:args.pages]
    updated = 0
    for n, batch in enumerate(batches, 1):
        d = http(db, "POST", ANILIST, body={"query": SWEEP_QUERY, "variables": {"ids": batch}})
        for m in (d or {}).get("data", {}).get("Page", {}).get("media", []):
            recs = [n["mediaRecommendation"]["id"] for n in (m.get("recommendations") or {}).get("nodes", [])
                    if n.get("mediaRecommendation") and (n.get("rating") or 0) > 0]
            airing = (m.get("nextAiringEpisode") or {}).get("airingAt")
            r = db.execute("""UPDATE entries SET popularity=%s, average_score=%s, genres=%s,
                                title_en=%s, title_native=%s, cover_url=%s, description=%s,
                                airing_status=%s, next_episode_at=to_timestamp(%s), recommendations=%s
                              WHERE anilist_id=%s""",
                           (m["popularity"] or 0, m["averageScore"], m["genres"] or [],
                            m["title"]["english"], m["title"]["native"], (m.get("coverImage") or {}).get("large"),
                            clean_html(m["description"]), m.get("status"), airing, recs, m["id"]))
            updated += r.rowcount
        # AniList에서 지워진 ID는 다시 묻지 않도록 인기도 0으로 표시
        db.execute("UPDATE entries SET popularity = 0 WHERE anilist_id = ANY(%s) AND popularity IS NULL", (batch,))
        if n % 20 == 0 or n == len(batches):
            print(f"  {n}/{len(batches)}묶음 ({updated:,}개 갱신)", flush=True)
    db.execute("""UPDATE series s SET popularity = x.p, next_episode_at = x.next_at, status = x.status FROM
                  (SELECT series_id, max(popularity) p, min(next_episode_at) next_at,
                          (array_agg(airing_status ORDER BY order_in_series DESC)
                             FILTER (WHERE airing_status IS NOT NULL))[1] status
                   FROM entries GROUP BY series_id) x
                  WHERE x.series_id = s.series_id""")
    print(f"  시즌 항목 {updated:,}개 갱신 → 시리즈 인기도·방영 상태 계산 완료")


CHAR_QUERY = """
query ($id: Int, $page: Int) {
  Media(id: $id) {
    characters(sort: [ROLE, RELEVANCE], perPage: 25, page: $page) {
      pageInfo { hasNextPage }
      edges { role node { id gender name { full native } image { large } description(asHtml: false) } }
    }
  }
}"""


def name_key(name):
    """'Tōru Oikawa' = 'Oikawa Toru'. 성·이름 순서와 장음 표기 차이를 무시한 비교용 열쇠."""
    plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(re.findall(r"[a-z0-9]+", plain)))


def link_character_debuts(db, series_id):
    """Fandom 회차별 등장인물 목록에서 캐릭터가 처음 나온 회차를 찾아 characters.first_abs_ep에 기록."""
    first = {}
    for ep in db.execute("SELECT abs_ep, characters FROM episodes WHERE series_id=%s AND characters IS NOT NULL "
                         "ORDER BY abs_ep", (series_id,)).fetchall():
        for link in ep["characters"]:
            first.setdefault(name_key(link), ep["abs_ep"])
    found = 0
    for c in db.execute("SELECT anilist_char, name FROM characters WHERE series_id=%s", (series_id,)).fetchall():
        n = first.get(name_key(c["name"])) if name_key(c["name"]) else None
        db.execute("UPDATE characters SET first_abs_ep=%s WHERE series_id=%s AND anilist_char=%s",
                   (n, series_id, c["anilist_char"]))
        found += n is not None
    return found


def step_characters(db, args):
    def one(s):
        n = 0
        for e in entries_of(db, s["series_id"]):
            if not e["anilist_id"]:
                continue
            d = http(db, "POST", ANILIST, body={"query": CHAR_QUERY,
                                                "variables": {"id": e["anilist_id"], "page": 1}},
                     cache=("anilist_chars2", str(e["anilist_id"])))
            for ed in ((d or {}).get("data", {}).get("Media") or {}).get("characters", {}).get("edges", []):
                c = ed["node"]
                db.execute("""INSERT INTO characters (series_id, anilist_char, name, name_native, role,
                                gender, image_url, description, first_entry)
                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                              ON CONFLICT (series_id, anilist_char) DO UPDATE SET
                                role = CASE WHEN characters.role='MAIN' THEN 'MAIN' ELSE EXCLUDED.role END,
                                image_url = EXCLUDED.image_url,
                                description = COALESCE(EXCLUDED.description, characters.description)""",
                           (s["series_id"], c["id"], c["name"]["full"], c["name"]["native"], ed["role"],
                            c["gender"], (c.get("image") or {}).get("large"),
                            clean_html(c["description"]) or None, e["entry_key"]))
                n += 1
        debuts = link_character_debuts(db, s["series_id"])
        return ("ok" if n else "empty"), f"{n}명" + (f", 첫 등장 회차 확인 {debuts}명" if debuts else "")
    run_each(db, "characters", targets(db, "characters", args), one)


# ───────────────────────── 3. TVmaze ─────────────────────────

def step_tvmaze(db, args):
    def one(s):
        if s["tvmaze_id"]:
            show = {"id": s["tvmaze_id"]}
        else:
            show = http(db, "GET", "https://api.tvmaze.com/lookup/shows",
                        params={"thetvdb": s["tvdb_id"]}, cache=("tvmaze_lookup", str(s["tvdb_id"])))
            if not show:
                return "empty", "TVDB ID로 TVmaze 작품을 찾지 못함"
            db.execute("UPDATE series SET tvmaze_id=%s WHERE series_id=%s", (show["id"], s["series_id"]))
        eps = http(db, "GET", f"https://api.tvmaze.com/shows/{show['id']}/episodes",
                   cache=("tvmaze_episodes", str(show["id"]))) or []
        regular = [(ep["season"], ep) for ep in sorted(eps, key=lambda e: (e["season"], e["number"] or 0))
                   if ep.get("type", "regular") == "regular" and ep.get("number")]
        pairs, how = map_episodes(entries_of(db, s["series_id"]), "tvdb", regular)
        with_summary = 0
        for hit, ep in pairs:
            summary = clean_html(ep.get("summary"))
            upsert_episode(db, s["series_id"], *hit, title_en=ep.get("name"),
                           airdate=as_date(ep.get("airdate")), summary_en=summary or None,
                           tvmaze_url=ep.get("url"))
            with_summary += bool(summary)
        if not pairs:
            return "empty", f"회차 {len(regular)}개 중 연결된 회차 없음"
        return "ok", f"{len(pairs)}/{len(regular)}화 연결({how}), 요약 {with_summary}화"
    run_each(db, "tvmaze", targets(db, "tvmaze", args, "s.tvdb_id IS NOT NULL OR s.tvmaze_id IS NOT NULL"), one)


# ───────────────────────── 4. TMDB ─────────────────────────

def _tmdb(db, path, params=None, cache=None):
    key = os.environ["TMDB_API_KEY"]
    params, headers = dict(params or {}), {}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    return http(db, "GET", f"https://api.themoviedb.org/3{path}", params=params, headers=headers,
                cache=("tmdb", cache) if cache else None)


def _tmdb_image(path, size):
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else None


TMDB_EXTRA = "alternative_titles,keywords,content_ratings,external_ids,videos,aggregate_credits"


def _save_tmdb_show(db, sid, show):
    """TMDB 작품 상세(한국어) → series, voice_cast."""
    names = lambda key: [x["name"] for x in show.get(key) or [] if x.get("name")]
    alt = [t["title"] for t in (show.get("alternative_titles") or {}).get("results", [])
           if t.get("iso_3166_1") in ("KR", "JP", "US") and t.get("title")]
    rating = next((r["rating"] for r in (show.get("content_ratings") or {}).get("results", [])
                   if r.get("iso_3166_1") == "KR" and r.get("rating")), None)
    videos = [v for v in (show.get("videos") or {}).get("results", []) if v.get("site") == "YouTube"]
    videos.sort(key=lambda v: (v.get("type") != "Trailer", v.get("iso_639_1") != "ko", not v.get("official")))
    db.execute("""UPDATE series SET title_ko=%s, title_original=%s, overview_ko=%s, tagline_ko=%s, poster_url=%s,
                    backdrop_url=%s, genres_ko=%s, keywords=%s, alt_titles=%s, first_air_date=%s, last_air_date=%s,
                    vote_average=%s, vote_count=%s, content_rating_kr=%s, trailer_url=%s, networks=%s, studios=%s,
                    origin_country=%s, homepage=%s, imdb_id=%s
                  WHERE series_id=%s""",
               (show.get("name"), show.get("original_name"), (show.get("overview") or "").strip() or None,
                (show.get("tagline") or "").strip() or None, _tmdb_image(show.get("poster_path"), "w500"),
                _tmdb_image(show.get("backdrop_path"), "w1280"), names("genres"),
                names_of((show.get("keywords") or {}).get("results")), list(dict.fromkeys(alt))[:20],
                as_date(show.get("first_air_date")), as_date(show.get("last_air_date")),
                show.get("vote_average") or None, show.get("vote_count"), rating,
                f"https://www.youtube.com/watch?v={videos[0]['key']}" if videos else None,
                names("networks"), names("production_companies"), show.get("origin_country") or [],
                show.get("homepage") or None, (show.get("external_ids") or {}).get("imdb_id"), sid))
    cast = sorted((show.get("aggregate_credits") or {}).get("cast", []),
                  key=lambda c: -(c.get("total_episode_count") or 0))[:40]
    db.execute("DELETE FROM voice_cast WHERE series_id=%s", (sid,))
    for c in cast:
        role = max(c.get("roles") or [{}], key=lambda r: r.get("episode_count") or 0).get("character")
        db.execute("""INSERT INTO voice_cast (series_id, tmdb_person, name, character, episode_count, profile_url)
                      VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                   (sid, c["id"], c.get("name"), (role or "").replace(" (voice)", "") or None,
                    c.get("total_episode_count"), _tmdb_image(c.get("profile_path"), "w185")))


def names_of(items):
    return [x["name"] for x in items or [] if x.get("name")]


def step_tmdb(db, args):
    if not os.environ.get("TMDB_API_KEY"):
        print("  ! TMDB_API_KEY가 없어 건너뜁니다 (.env에 추가하세요)")
        return

    def one(s):
        tid, sid = s["tmdb_id"], s["series_id"]
        show = _tmdb(db, f"/tv/{tid}", {"language": "ko-KR", "append_to_response": TMDB_EXTRA,
                                        "include_video_language": "ko,ja,en,null"}, cache=f"{tid}_full")
        if not show:
            return "empty", "TMDB 작품 없음"
        _save_tmdb_show(db, sid, show)
        eps = []
        for meta in sorted((x for x in show.get("seasons", []) if x["season_number"] > 0),
                           key=lambda x: x["season_number"]):
            n = meta["season_number"]
            season = _tmdb(db, f"/tv/{tid}/season/{n}", {"language": "ko-KR"}, cache=f"{tid}_s{n}") or {}
            english = _tmdb(db, f"/tv/{tid}/season/{n}", {"language": "en-US"}, cache=f"{tid}_s{n}_en") or {}
            en_by_no = {e["episode_number"]: e for e in english.get("episodes", [])}
            eps += [(n, (n, ep, en_by_no.get(ep["episode_number"], {}))) for ep in season.get("episodes", [])]
            db.execute("""INSERT INTO seasons (series_id, tmdb_season, name_ko, overview_ko, air_date, poster_url, episode_count)
                          VALUES (%s,%s,%s,%s,%s,%s,%s)
                          ON CONFLICT (series_id, tmdb_season) DO UPDATE SET name_ko=EXCLUDED.name_ko,
                            overview_ko=EXCLUDED.overview_ko, air_date=EXCLUDED.air_date,
                            poster_url=EXCLUDED.poster_url, episode_count=EXCLUDED.episode_count""",
                       (sid, n, season.get("name") or meta.get("name"),
                        (season.get("overview") or meta.get("overview") or "").strip() or None,
                        as_date(season.get("air_date") or meta.get("air_date")),
                        _tmdb_image(season.get("poster_path") or meta.get("poster_path"), "w500"),
                        len(season.get("episodes", [])) or meta.get("episode_count")))
            pv = _tmdb(db, f"/tv/{tid}/season/{n}/watch/providers", cache=f"{tid}_s{n}_providers") or {}
            kr = pv.get("results", {}).get("KR", {})
            db.execute("""INSERT INTO streaming (series_id, tmdb_season, season_name, flatrate, link, checked_at)
                          VALUES (%s,%s,%s,%s,%s,current_date)
                          ON CONFLICT (series_id, tmdb_season) DO UPDATE SET season_name=EXCLUDED.season_name,
                            flatrate=EXCLUDED.flatrate, link=EXCLUDED.link, checked_at=current_date""",
                       (sid, n, season.get("name"), [p["provider_name"] for p in kr.get("flatrate", [])],
                        kr.get("link")))
        pairs, how = map_episodes(entries_of(db, sid), "tmdb", eps)
        with_overview = with_english = 0
        for hit, (n, ep, en) in pairs:
            ov, ov_en = (ep.get("overview") or "").strip(), (en.get("overview") or "").strip()
            upsert_episode(db, sid, *hit, tmdb_season=n, tmdb_number=ep["episode_number"],
                           still_url=_tmdb_image(ep.get("still_path"), "w300"), runtime=ep.get("runtime"),
                           rating=ep.get("vote_average") or None,
                           title_ko=ep.get("name"), overview_ko=ov or None, overview_en=ov_en or None)
            # TVmaze가 없는 작품은 TMDB의 영어 제목·방영일로 채움
            db.execute("""UPDATE episodes SET title_en = COALESCE(title_en, %s), airdate = COALESCE(airdate, %s)
                          WHERE series_id=%s AND abs_ep=%s""",
                       (en.get("name") or None, as_date(ep.get("air_date")), sid, hit[0]))
            with_overview += bool(ov)
            with_english += bool(ov_en)
        return ("ok" if pairs else "empty"), (f"{len(pairs)}/{len(eps)}화 연결({how}), 한국어 줄거리 {with_overview}화, "
                                             f"영어 줄거리 {with_english}화")
    run_each(db, "tmdb", targets(db, "tmdb", args, "s.tmdb_id IS NOT NULL"), one)


# ───────────────────────── 5. Jikan (필러) ─────────────────────────

def step_jikan(db, args):
    def one(s):
        mapped = filler = 0
        for e in entries_of(db, s["series_id"]):
            if not e["mal_id"]:
                continue
            page = 1
            while True:
                d = http(db, "GET", f"https://api.jikan.moe/v4/anime/{e['mal_id']}/episodes",
                         params={"page": page}, cache=("jikan", f"{e['mal_id']}_p{page}"), tries=2)
                if not d:
                    break
                for ep in d.get("data", []):
                    n = ep.get("mal_id")
                    if not n or (e["episodes"] and n > e["episodes"]):
                        continue
                    upsert_episode(db, s["series_id"], e["abs_offset"] + n, e["entry_key"], n,
                                   filler=bool(ep.get("filler")), recap=bool(ep.get("recap")))
                    mapped += 1
                    filler += bool(ep.get("filler"))
                if not d.get("pagination", {}).get("has_next_page"):
                    break
                page += 1
        return ("ok" if mapped else "empty"), f"{mapped}화, 필러 {filler}화"
    run_each(db, "jikan", targets(db, "jikan", args), one)


# ───────────────────────── 6. Fandom ─────────────────────────

PLOT_RE = re.compile(r"plot|summ[ae]ry|syn?[oy]?p[no]?sis|overview|story|recap", re.I)      # 흔한 오타(Sypnosis)까지
# 줄거리가 아닌 구역. 줄거리 이름의 구역이 없을 때, 여기에 안 걸리는 가장 긴 글을 줄거리로 봄
NOT_PLOT_RE = re.compile(
    r"trivia|note|differ|reference|gallery|character|cast|credit|music|navigat|quote|staff|appearance|see also|external|"
    r"link|source|song|soundtrack|video|image|screenshot|error|goof|mistake|production|reception|release|home media|dvd|"
    r"preview|broadcast|rating|voice|change|adapt|comparison|censor|spell|item|jutsu|technique|battle|event|location|"
    r"omake|script|transcript|chronolog", re.I)
EVENT_RE = re.compile(r"event|battle|fight", re.I)                # 사건·전투 목록 구역
RANGE_RE = re.compile(r"episodes?\s*(\d{1,4})\s*[-–~]\s*(\d{1,4})", re.I)    # 'Short Episodes 6-10': 문서 하나가 여러 화
PART_RE = re.compile(r"^(part|segment|skit|scene|story|featured duel)\b", re.I)   # 한 화를 여러 구역으로 나눠 쓴 위키


def _is_prose(text, at_least=500):
    return len(text) >= at_least and text.count(". ") >= 3
CHAR_RE = re.compile(r"characters?|appearances?", re.I)
# 회차 번호가 들어 있는 인포박스 칸. 앞쪽이 '시리즈 전체 기준 번호'임이 확실한 이름
EP_KEYS = ("number (overall)", "overall", "ep number", "episode number", "episode_number", "episodenumber",
           "epnum", "ep_num", "ep num", "episode", "number", "#", "ep", "no")
TITLE_KEYS = ("ep title", "episode title", "name of episode", "name", "title", "en title", "translation", "english")
DATE_RE = re.compile(r"\b(19|20)\d\d\b")      # 방영일이 들어 있는 칸을 제목으로 잘못 읽지 않기 위함
CHAPTER_KEYS = ("adapted from", "adaptedfrom", "adapted", "adaptation", "manga chapters", "chapters", "chapter",
                "manga")
EP_PAGE_RE = re.compile(r"Episode[ _:]#?(\d{1,4})\s*(?:\(.*\))?", re.I)
EP_TITLED_RE = re.compile(r"Episode[ _]#?(\d{1,4})\s*[:\-–]\s*\S.*", re.I)      # 'Episode 3: The Chef …'
EP_SUFFIX_RE = re.compile(r".*\bEpisode[ _]#?(\d{1,4})", re.I)                   # 'Rebirth Episode 01'
# 같은 위키 안에서 번호를 따로 세는 묶음(시즌·작품)을 알려 주는 인포박스 칸
SEASON_KEYS = ("season", "partofseason", "season number", "seriesname", "series")
DATE_KEY_RE = re.compile(r"air|date|release|broadcast|premiere", re.I)
DUB_KEY_RE = re.compile(r"en|usa|\bus\b|dub|sub|date2|america", re.I)     # 해외·더빙 방영일 칸은 뒤로 미룸
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}
DATE_RES = [re.compile(rx, re.I) for rx in (
    r"(?P<m>[a-z]{3,9})\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>(?:19|20)\d\d)",      # October 5th, 2014
    r"(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m>[a-z]{3,9})\.?,?\s+(?P<y>(?:19|20)\d\d)",      # 5 October 2014
    r"(?P<y>(?:19|20)\d\d)\s+(?P<m>[a-z]{3,9})\s+(?P<d>\d{1,2})\b",                         # 2009 August 2
    r"(?P<y>(?:19|20)\d\d)[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})\b")]                        # 2014-10-05


def parse_dates(text):
    """글 안의 날짜를 나온 순서대로. 'October 5th, 2014', '5 October 2014', '2009 August 2', '2014-10-05'."""
    found = []
    for rx in DATE_RES:
        for m in rx.finditer(text or ""):
            month = int(m["m"]) if m["m"].isdigit() else MONTHS.get(m["m"][:3].lower())
            try:
                found.append((m.start(), dt.date(int(m["y"]), month, int(m["d"]))))
            except (TypeError, ValueError):
                pass
    return list(dict.fromkeys(d for _, d in sorted(found)))


def norm_title(s):
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\((?:episode|anime)\)", "", (s or "").lower()))


SKIP_TEMPLATES = re.compile(r"quote|nihongo|tabs?\b|theme|disambig|for\b|redirect|stub|spoiler|main\b|see also|"
                            r"navbox|navigation|translation|ruby|color|scroll|cleanup|delete|icon", re.I)
# 인포박스 이름 → 문서 종류. 위에서부터 먼저 맞는 것으로 정함
KIND_RULES = [(k, re.compile(rx, re.I)) for k, rx in (
    ("episode", r"episode|\bep\b"), ("chapter", r"chapter|volume|\bbook\b|novel|manga"),
    ("music", r"song|music|album|\bost\b|soundtrack|opening|ending"),
    ("person", r"staff|actor|actress|seiyu|voice|\bcast\b|author|real|people"),
    ("arc", r"\barc\b|saga"), ("media", r"game|movie|film|\bova\b|dvd|blu-?ray|merch|anime|series|stage|event"),
    ("character", r"character|chara|\bchar\b|individual|person|human|demon|titan|hero|villain"),
    ("ability", r"abilit|technique|quirk|jutsu|magic|spell|power|skill|fruit|\bnen\b|breathing|curse|stand|move"),
    ("item", r"item|weapon|object|tool|equipment|artifact|vehicle|ship|sword|food"),
    ("location", r"location|place|city|country|island|village|world|town|planet|building|kingdom"),
    ("group", r"organi[sz]ation|group|team|clan|guild|squad|family|crew|affiliation|school|race|species|faction"))]


def _parse_wiki(wikitext, is_infobox, unwrap=False):
    """위키 원문 → (인포박스 이름, 인포박스 {칸: 값}, 구역 {제목: {text, links}}). 그림·각주·갤러리는 뺌.

    unwrap=True면 줄글이 틀(template) 안에 들어 있는 경우 꺼냅니다 ({{Full Synopsis|…}}, 인포박스의 description 칸).
    """
    import mwparserfromhell as mwp

    text = re.sub(r"<gallery.*?</gallery>", "", wikitext, flags=re.S | re.I)
    text = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", " ⏎ ", text, flags=re.I)        # 줄바꿈 표시. 인포박스 값에서는 쉼표, 본문에서는 줄바꿈으로 바꿈
    code = mwp.parse(text)
    for t in code.filter_templates():         # 긴 줄거리를 스크롤 상자 틀 안에 넣어 둔 위키: 상자를 벗기고 글만 남김
        if re.fullmatch(r"scroll ?box|scroll", str(t.name).strip(), re.I):
            inner = max((str(p.value) for p in t.params), key=len, default="")
            try:
                code.replace(t, inner)
            except ValueError:
                pass
    for t in code.filter_templates():
        if re.fullmatch(r"nihongo\d?|nihongo[ -]?(title|foot)|tt|tooltip|w|wp|wikipedia|lang|ruby|abbr|small|big|nowrap|c|color",
                        str(t.name).strip(), re.I):
            shown = [str(x.value).strip() for x in t.params if not x.showkey and str(x.value).strip()]
            try:
                code.replace(t, shown[-1] if re.fullmatch(r"lang|color|c", str(t.name).strip(), re.I) and shown
                             else shown[0] if shown else "")
            except ValueError:
                pass
    code = mwp.parse(str(code))
    if unwrap:
        for t in code.filter_templates(recursive=False):
            name = str(t.name).strip().lower().replace("_", " ")
            if re.search(r"quote|list|table", name):
                continue
            prose = [p for p in t.params if not NOT_PLOT_RE.search(str(p.name)) and _is_prose(p.value.strip_code().strip(), 300)]
            if not prose:
                continue
            inner = "\n\n".join(str(p.value).strip() for p in prose)
            try:
                if len(t.params) >= 3 and is_infobox(name, t):     # 인포박스는 그대로 두고 글만 뒤에 붙임
                    code.insert_after(t, "\n" + inner + "\n")
                else:
                    code.replace(t, "\n" + inner + "\n")
            except ValueError:
                pass
    code = mwp.parse(str(code))
    for link in code.filter_wikilinks():      # 그림·분류 링크는 본문이 아니므로 설명글째 지움
        if str(link.title).strip().lower().startswith(("file:", "image:", "category:")):
            try:
                code.remove(link)
            except ValueError:                # 이미 지운 그림 안에 들어 있던 링크
                pass

    box_name, infobox = None, {}
    for t in code.filter_templates(recursive=False):
        name = str(t.name).strip().lower().replace("_", " ")
        if len(t.params) >= 3 and is_infobox(name, t):
            box_name = name
            for p in t.params:
                value = re.sub(r"\s+", " ", p.value.strip_code().replace("⏎", ","))
                infobox[str(p.name).strip().lower()] = re.sub(r"(\s*,)+", ",", value).strip(" ,")[:2000]
            break

    def plain(node) -> str:
        text = re.sub(r"[ \t]*⏎[ \t]*", "\n", node.strip_code(normalize=True, collapse=True))
        text = re.sub(r"(?m)^[ \t]*[,;:][ \t]*", "", text)             # 틀이 지워지고 남은 줄 머리의 쉼표
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    sections = {}
    for sec in code.get_sections(levels=[2], include_lead=True):
        heads = sec.filter_headings()
        title = heads[0].title.strip_code().strip() if heads and str(sec).lstrip().startswith("=") else "_lead"
        body = mwp.parse(str(sec))
        for h in body.filter_headings():
            body.remove(h)
        if title == "_lead":                  # 머리말에서는 인포박스 같은 틀을 걷어내고 글만 남김
            for t in body.filter_templates(recursive=False):
                if len(t.params) >= 3:
                    try:
                        body.remove(t)
                    except ValueError:
                        pass
        sections[title] = {"text": plain(body),
                           "links": list(dict.fromkeys(str(l.title).strip() for l in body.filter_wikilinks()
                                                       if ":" not in str(l.title) and str(l.title).strip()))}
    return box_name, infobox, sections


def parse_wiki_page(wikitext: str) -> dict:
    """아무 위키 문서 → 종류(kind), 인포박스, 구역별 본문, 본문 링크."""
    name, infobox, sections = _parse_wiki(
        wikitext, lambda n, t: not SKIP_TEMPLATES.search(n) and ("infobox" in n or "box" in n or len(t.params) >= 5
                                                                 or any(rx.search(n) for _, rx in KIND_RULES)))
    kind = next((k for k, rx in KIND_RULES if name and rx.search(name)), "other")
    return {"kind": kind, "infobox_name": name, "infobox": infobox,
            "sections": {k: v["text"][:20000] for k, v in sections.items() if v["text"]},
            "links": list(dict.fromkeys(l for v in sections.values() for l in v["links"]))[:400]}


def _is_episode_box(name, t):
    """회차 인포박스인가. 이름이 제각각이라({{Konosuba Anime}}) 방영일·이전·다음 같은 칸이 둘 이상 있으면 인정."""
    return "infobox" in name or "episode" in name or \
        sum(bool(re.search(r"air|date|prev|next|episode|kanji|romaji|japanese", str(p.name), re.I)) for p in t.params) >= 2


def parse_episode_wikitext(wikitext: str) -> dict:
    """회차 문서 → 인포박스 필드 + 줄거리 + 짧은 요약 + 등장인물.

    줄거리는 ① 이름이 줄거리인 구역(Plot, Summary, Synopsis …) 중 가장 긴 것. 그것이 500자보다 짧으면 ② 줄거리가 아닌
    구역(Trivia, Characters …)만 빼고 나머지를 이어 붙인 것(Part A·B, 단편 묶음, Content, Description, 틀 안에 든 글),
    ③ 구역 없이 머리말에 쓴 줄글 중 더 긴 쪽을 씁니다.
    """
    _, infobox, sections = _parse_wiki(wikitext, _is_episode_box, unwrap=True)

    plots = sorted((sections[n]["text"] for n in sections if PLOT_RE.search(n) and sections[n]["text"]),
                   key=len, reverse=True)
    if not plots or len(plots[0]) < 500:
        # 한 화를 여러 구역에 나눠 쓴 문서(단편 묶음, Part A·B, 짧은 Synopsis + Summary): 줄거리가 아닌 구역만 빼고 이어 붙임
        pieces = [sections[n]["text"] for n in sections if n != "_lead" and sections[n]["text"] and (
            PLOT_RE.search(n) or PART_RE.search(n) or (not NOT_PLOT_RE.search(n) and len(sections[n]["text"]) >= 100))]
        found = "\n\n".join(pieces)
        lead = sections.get("_lead", {}).get("text", "")
        if _is_prose(lead) and len(lead) > len(found):       # 구역 없이 머리말에 줄거리를 쓴 문서
            found = lead
        if len(found) >= 40 and len(found) > (len(plots[0]) if plots else 0):      # 짧아도 위키에 있는 만큼은 가져옴
            plots = [found]
    # 줄거리가 전혀 없는 문서: 머리말(몇 화인지 소개하는 문장)과 사건·전투 목록이라도 짧은 요약으로 남김
    note = ""
    if not plots:
        note = "\n".join(x for x in [sections.get("_lead", {}).get("text", "")] + [
            f"{n}: " + re.sub(r"\s*\n\s*", "; ", sections[n]["text"]) for n in sections
            if EVENT_RE.search(n) and sections[n]["text"]] if x)[:1500]
        note = note if len(note) >= 40 else ""
    char_keys = sorted((n for n in sections if CHAR_RE.search(n)),
                       key=lambda n: 0 if re.search("order", n, re.I) else 1)
    ep_no = None
    for k in EP_KEYS:
        m = re.fullmatch(r"\D{0,10}(\d{1,4})\D{0,3}", infobox.get(k, ""))
        if m:
            ep_no = int(m.group(1))
            break
    date_keys = sorted((k for k in infobox if DATE_KEY_RE.search(k)), key=lambda k: bool(DUB_KEY_RE.search(k)))
    return {
        "infobox": infobox, "episode_no": ep_no,
        "airdates": list(dict.fromkeys(d for k in date_keys for d in parse_dates(infobox[k]))),
        "season": next((infobox[k].lower() for k in SEASON_KEYS if infobox.get(k)), ""),
        "title": next((infobox[k] for k in TITLE_KEYS if infobox.get(k) and not DATE_RE.search(infobox[k])), None),
        "arc": infobox.get("arc") or None,
        "chapters": next((infobox[k] for k in CHAPTER_KEYS if infobox.get(k)), None),
        "plot": plots[0] if plots else "",
        "synopsis": plots[-1] if len(plots) > 1 else note,
        "span": next((int(m.group(2)) - int(m.group(1)) + 1 for k in EP_KEYS if (m := RANGE_RE.search(infobox.get(k, "")))
                      and 0 < int(m.group(2)) - int(m.group(1)) < 10), 1),
        "characters": sections[char_keys[0]]["links"][:80] if char_keys else [],
    }


def _same_title(wiki_title, tvmaze_norm):
    """번역·표기 차이를 감안한 제목 비교 (한쪽이 다른 쪽을 포함하면 같은 회차로 봄). 검증용."""
    a, b = norm_title(wiki_title), tvmaze_norm or ""
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a)))


def _infobox_ok(value, want):
    """fandom_wikis.json의 infobox 조건. "Yes" = 같아야 함, "!Yes" = 같으면 안 됨."""
    if want.startswith("!"):
        return value.lower() != want[1:].lower()
    return value.lower() == want.lower()


def fandom_subcategories(db, wiki, category):
    """분류 바로 아래의 하위 분류 이름들 ('Episodes' → 'Season 1 Episodes', 'Season 2 Episodes' …)."""
    d = http(db, "GET", f"https://{wiki}.fandom.com/api.php", cache=("fandom", f"{wiki}/{category[:200]}/_subcats"),
             params={"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}", "cmtype": "subcat",
                     "cmlimit": 100, "format": "json", "formatversion": 2}) or {}
    return [m["title"].split(":", 1)[1] for m in d.get("query", {}).get("categorymembers", [])]


EP_CATEGORY_RE = re.compile(r"episode|session", re.I)
NOT_EP_CATEGORY_RE = re.compile(r"galler|image|screenshot|music|song|character|chapter|video|credit|staff|cast|"
                                r"appearance|stub|template|needing|candidates|missing|preview", re.I)


def fandom_episode_categories(db, wiki):
    """위키마다 다른 회차 분류 이름을 검색으로 찾음 ('K-ON!! Episodes', 'Sessions', 'Season 3 Episode' …)."""
    d = http(db, "GET", f"https://{wiki}.fandom.com/api.php", cache=("fandom", f"{wiki}/_episode_categories"),
             params={"action": "query", "list": "search", "srsearch": "episode OR episodes OR session OR sessions",
                     "srnamespace": 14, "srlimit": 50, "format": "json", "formatversion": 2}) or {}
    names = [x["title"].split(":", 1)[1] for x in d.get("query", {}).get("search", [])]
    return [n for n in names if EP_CATEGORY_RE.search(n) and not NOT_EP_CATEGORY_RE.search(n)]


def fandom_titled_pages(db, wiki, prefix="Episode", limit=1500):
    """제목이 'Episode'로 시작하는 문서 전부 → [(제목, 원문)]. 회차 문서를 아무 분류에도 넣지 않은 위키를 위한 것."""
    api, out, cont = f"https://{wiki}.fandom.com/api.php", [], {}
    while len(out) < limit:
        d = http(db, "GET", api, cache=("fandom", f"{wiki}/_titled/{prefix}/{json.dumps(cont, sort_keys=True)}"), params={
            "action": "query", "generator": "allpages", "gapprefix": prefix, "gapnamespace": 0, "gaplimit": 50,
            "gapfilterredir": "nonredirects", "prop": "revisions", "rvprop": "content", "rvslots": "main",
            "format": "json", "formatversion": 2, **cont}) or {}
        out += [(pg["title"], pg["revisions"][0]["slots"]["main"]["content"])
                for pg in d.get("query", {}).get("pages", []) if pg.get("revisions")]
        cont = {k: v for k, v in (d.get("continue") or {}).items() if k != "continue"}
        if not cont:
            break
    return out


def fandom_pages(db, wiki, category=None, titles=None, expect=0, all_ns=False):
    """문서 원문을 50개씩 한 번에 받음 → [(제목, 원문)]. 분류 전체 또는 제목 목록.

    분류 바로 아래의 문서가 expect(작품 회차 수)의 절반도 안 되면 시즌별로 나눠 둔 위키로 보고 하위 분류를 두 단계까지 내려갑니다.
    all_ns=True면 일반 문서가 아닌 이름공간(회차 전용 'Episode:01' 등)의 문서만 받습니다.
    """
    api, out = f"https://{wiki}.fandom.com/api.php", {}
    base = {"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main", "redirects": 1,
            "format": "json", "formatversion": 2}

    def fetch(batch, label):
        cont = {}
        while True:
            key = f"{wiki}/{label[:200]}/{json.dumps(cont, sort_keys=True)}"
            d = http(db, "GET", api, params={**base, **batch, **cont}, cache=("fandom", key)) or {}
            for p in d.get("query", {}).get("pages", []):
                revs = p.get("revisions") or []
                if revs and (not all_ns or p.get("ns", 0) >= 100 and p["ns"] % 2 == 0):
                    out.setdefault(p["title"], revs[0]["slots"]["main"]["content"])
            cont = d.get("continue") or {}
            if not cont:
                break

    if titles:
        for i in range(0, len(titles), 50):
            fetch({"titles": "|".join(titles[i:i + 50])}, "|".join(titles[i:i + 50]))
        return list(out.items())
    todo, seen = [(category, 0)], {category}
    while todo:
        cat, depth = todo.pop(0)
        if all_ns:
            fetch({"generator": "categorymembers", "gcmtitle": f"Category:{cat}", "gcmtype": "page", "gcmlimit": 50},
                  f"{cat}/_all_ns")
        else:
            fetch({"generator": "categorymembers", "gcmtitle": f"Category:{cat}", "gcmnamespace": 0, "gcmlimit": 50}, cat)
        if depth < 2 and len(out) < 0.5 * expect:
            for sub in fandom_subcategories(db, wiki, cat):
                if sub not in seen and len(seen) < 40:
                    seen.add(sub)
                    todo.append((sub, depth + 1))
    return list(out.items())


NEXT_KEYS = ("next", "nextepisode", "next episode", "n")
PREV_KEYS = ("previous", "prev", "previousepisode", "previous episode", "lastepisode", "p")


def date_lookup(by_date, dates, latest=False):
    """문서의 방영일 → 전체 회차 번호. 같은 날이 없으면 하루 차이(심야 방송의 날짜 표기 차이)까지 봄."""
    for d in sorted(dates or [], reverse=latest):     # 첫 방영일이 가장 이름. 뒤의 날짜는 재방송·해외 방영일
        if d in by_date:                      # 여러 화가 방영된 날(None)이면 어느 화인지 가릴 수 없으므로 여기서 멈춤
            return by_date[d]
        near = {by_date[x] for x in (d - dt.timedelta(days=1), d + dt.timedelta(days=1)) if by_date.get(x)}
        if len(near) == 1:
            return near.pop()
    return None


def _page_group(title, p):
    """번호를 따로 세는 묶음. 인포박스의 시즌 칸 + 문서 제목에서 회차 번호를 뺀 나머지 ('Sword Art Online II')."""
    rest = "" if EP_TITLED_RE.fullmatch(title) else re.sub(r"(episode|ep\.?)[ _]*#?\d+", "", title, flags=re.I)
    return (p.get("season") or "", rest.strip(" -:_").lower() if rest != title else "")


def number_pages(pages, by_title, by_date=None, aired=None):
    """[(문서 제목, 파싱 결과)] → {문서 제목: 전체 회차 번호}.

    ① 문서 제목 'Episode N' → ② 이미 받은 영어 회차 제목과 같은 문서 → ③ 방영일이 같은 회차
    (by_date = {방영일: 회차}, 여러 화가 방영된 날은 None) → ④ 인포박스의 이전·다음 회차 링크를 따라 이어 붙임
    → ⑤ 그래도 남은 문서는 인포박스 번호. 같은 묶음(시즌)에서 이미 번호가 정해진 문서들과 인포박스 번호의 차이가
    일정하면 그 차이만큼 더하고(2기 3화 = 전체 28화), 묶음 정보가 없으면 위키 전체에서 번호가 맞을 때만 씁니다.
    ④⑤로 붙인 번호는 방영일(aired = {회차: 방영일})과 2주 넘게 어긋나면 같은 위키의 다른 작품으로 보고 뺍니다.

    ①과 ③은 위키마다 믿을 수 있는지 먼저 확인합니다. 같은 'Episode N'이 여러 문서에 있으면 시즌마다 다시 세는
    위키이므로 ①을 버립니다. 방영일로 찾은 번호는 같은 시즌 안에서 문서에 적힌 번호와 차이가 일정하면 ②보다 먼저 믿고,
    그렇지 않으면서 ①·②와 자주 어긋나면 해외 방영일만 적힌 위키이므로 버립니다.
    """
    by_date = by_date or {}
    by_norm, local = {}, {}
    for title, p in pages:
        by_norm.setdefault(norm_title(title), title)
        m = EP_PAGE_RE.fullmatch(title) or EP_TITLED_RE.fullmatch(title)
        if not m and (m := EP_SUFFIX_RE.fullmatch(title)) and p["episode_no"] not in (None, int(m.group(1))):
            m = None                          # 'Power - Episode 1' (인포박스 번호 290): 제목 끝의 번호는 이야기 안의 순번
        local[title] = int(m.group(1)) if m else None

    def by_dates(latest):
        return {t: date_lookup(by_date, p.get("airdates"), latest) for t, p in pages}

    def usual_offsets(dated):
        """묶음(시즌)마다 '방영일로 찾은 번호 - 문서에 적힌 번호'로 가장 흔한 값. 문서 3개 이상인 묶음만."""
        offsets = {}
        for t, p in pages:
            n = local[t] or p["episode_no"]
            if n and dated[t]:
                offsets.setdefault(_page_group(t, p), []).append(dated[t] - n)
        return {g: (max(set(o), key=o.count), o) for g, o in offsets.items() if len(o) >= 3}

    def steady(dated):
        """방영일로 찾은 번호가 믿을 만한가: 같은 묶음 안에서 그 차이가 일정한 문서의 비율."""
        groups = usual_offsets(dated).values()
        total = sum(len(o) for _, o in groups)
        return sum(o.count(usual) for usual, o in groups) / total if total >= 6 else None

    # 방영일이 둘 이상 적힌 문서는 이른 날짜를 쓰되, 늦은 날짜가 더 잘 맞는 위키(선행 방영일을 함께 적음)는 늦은 날짜를 씀
    dated = max((by_dates(False), by_dates(True)), key=lambda d: steady(d) or 0)
    cand = {t: (local[t], by_title.get(norm_title(p["title"])) or by_title.get(norm_title(t)), dated[t]) for t, p in pages}

    def agree(i, j):                          # 두 방법이 모두 번호를 낸 문서 중 같은 번호인 비율 (3개 미만이면 판단 안 함)
        both = [(c[i], c[j]) for c in cand.values() if c[i] and c[j]]
        return sum(x == y for x, y in both) / len(both) if len(both) >= 3 else None

    by_page_title = [c[0] for c in cand.values() if c[0]]
    title_ok = sum(by_page_title.count(n) > 1 for n in by_page_title) < 0.2 * len(by_page_title)
    # 시즌별 번호와 아귀가 맞는 위키에서는, 그 차이가 묶음의 흔한 값과 같은 문서에 한해 제목이 같은 문서보다 방영일을 먼저 믿음
    usual = usual_offsets(dated) if (steady(dated) or 0) >= 0.8 else {}
    fits = {t for t, p in pages if dated[t] and (local[t] or p["episode_no"]) and _page_group(t, p) in usual
            and dated[t] - (local[t] or p["episode_no"]) == usual[_page_group(t, p)][0]}
    date_sure = bool(usual)
    date_ok = date_sure or all(a is None or a >= 0.8 for a in (agree(2, 1), agree(2, 0) if title_ok else None))
    numbers, named = {}, [c[1] for c in cand.values() if c[1]]
    for title, (n_title, n_name, n_date) in cand.items():
        by_fit = n_date if title in fits and not (n_name and n_name != n_date and n_date in named) else None
        n = (n_title if title_ok else None) or by_fit or n_name or (n_date if date_ok else None)
        if n:
            numbers[title] = n
    sure = set(numbers)

    def follow_links():
        changed = True
        while changed:
            changed = False
            for title, p in pages:
                if title not in numbers:
                    continue
                for keys, step in ((NEXT_KEYS, 1), (PREV_KEYS, -1)):
                    link = next((p["infobox"][k] for k in keys if p["infobox"].get(k)), None)
                    other = by_norm.get(norm_title(link)) if link else None
                    if other and other not in numbers:
                        numbers[other] = numbers[title] + step
                        changed = True

    follow_links()
    groups = {}
    for title, p in pages:
        groups.setdefault(_page_group(title, p), []).append((title, p))
    both = [(numbers[t], p["episode_no"]) for t, p in pages if t in numbers and p["episode_no"]]
    whole_wiki = not both or sum(a == b for a, b in both) >= 0.8 * len(both)
    for members in groups.values():
        offsets = [numbers[t] - p["episode_no"] for t, p in members if t in numbers and p["episode_no"]]
        if offsets:
            offset = max(set(offsets), key=offsets.count)
            if offsets.count(offset) < 0.7 * len(offsets):     # 위키에 번호가 잘못 적힌 문서가 몇 개 섞여도 됨
                continue
        elif whole_wiki:
            offset = 0
        else:
            continue
        for title, p in members:
            if title not in numbers and p["episode_no"]:
                numbers[title] = p["episode_no"] + offset
    follow_links()
    if aired:                                 # 방영일이 대체로 맞는 위키에서만 날짜로 걸러냄
        gap = {t: min(abs((d - aired[numbers[t]]).days) for d in p["airdates"])
               for t, p in pages if numbers.get(t) in aired and p.get("airdates")}
        hits = sum(g <= 1 for g in gap.values())
        if gap and (hits >= 0.6 * len(gap) or hits >= max(6, 0.5 * sum(map(bool, by_date.values())))):
            for t, g in gap.items():
                if g > 14 and t not in sure:
                    del numbers[t]
    return numbers


def step_fandom(db, args):
    cfg = json.loads((DATA / "fandom_wikis.json").read_text(encoding="utf-8"))["wikis"]

    def one(s):
        f = cfg[s["series_id"]]
        base = f"https://{f['wiki']}.fandom.com"
        info = http(db, "GET", f"{base}/api.php", params={
            "action": "query", "meta": "siteinfo", "siprop": "rightsinfo", "format": "json", "formatversion": 2},
            cache=("fandom", f"{f['wiki']}/_rights")) or {}
        license_ = (info.get("query", {}).get("rightsinfo", {}).get("text") or "").strip()
        entries = entries_of(db, s["series_id"])
        title_of = {r["abs_ep"]: norm_title(r["title_en"]) for r in db.execute(
            "SELECT abs_ep, title_en FROM episodes WHERE series_id=%s AND title_en IS NOT NULL", (s["series_id"],))}
        names = list(title_of.values())
        # 여러 회차가 같은 제목이거나 'Episode 3' 같은 제목이면 제목으로는 회차를 가릴 수 없음
        named = [(t, n) for n, t in sorted(title_of.items(), reverse=True)
                 if t and not re.fullmatch(r"(episode|ep|stage|chapter)?\d+", t)]
        by_title = {t: n for t, n in named if names.count(t) == 1}
        repeated_title = {t: n for t, n in named if names.count(t) > 1}      # 같은 제목의 회차가 여럿이면 앞 회차
        aired = {r["abs_ep"]: r["airdate"] for r in db.execute(
            "SELECT abs_ep, airdate FROM episodes WHERE series_id=%s AND airdate IS NOT NULL", (s["series_id"],))}
        days = list(aired.values())
        by_date = {d: n if days.count(d) == 1 else None for n, d in aired.items()}     # 여러 화가 방영된 날은 None
        first_found = None        # 회차 분류에서 바로 찾은 문서들 (모자라서 더 찾아본 경우에만 채움)
        if f.get("pattern"):      # 회차 분류가 없는 위키: 'Episode 1' … 'Episode N' 문서를 직접 받음
            last = max(s["total_episodes"] or 0, max(title_of, default=0))
            raw_pages = fandom_pages(db, f["wiki"], titles=[f["pattern"].format(n=n) for n in range(1, last + 1)])
        else:
            total, seen_titles = s["total_episodes"] or 0, set()
            raw_pages = fandom_pages(db, f["wiki"], f.get("category", "Episodes"), expect=total)
            # 회차 문서가 모자라면 위키가 다른 이름으로 둔 회차 분류와, 이미 받아 둔 위키 전체 문서 중 회차 문서까지 봄
            # (어느 문서가 이 작품의 몇 화인지는 아래에서 제목·방영일로 가려냄)
            if len(raw_pages) < 0.9 * total:
                first_found = {t for t, _ in raw_pages}
                seen_titles = {t for t, _ in raw_pages}
                for cat in fandom_episode_categories(db, f["wiki"])[:15]:
                    if cat != f.get("category", "Episodes"):
                        raw_pages += [x for x in fandom_pages(db, f["wiki"], cat) if x[0] not in seen_titles]
                        seen_titles = {t for t, _ in raw_pages}
                if len(raw_pages) < 0.5 * total:
                    raw_pages += fandom_pages(db, f["wiki"], f.get("category", "Episodes"), all_ns=True)
                    seen_titles = {t for t, _ in raw_pages}
                if len(raw_pages) < 0.9 * total:      # 분류에 안 넣은 'Episode 51' 같은 문서
                    raw_pages += [x for x in fandom_titled_pages(db, f["wiki"]) if x[0] not in seen_titles]
                    seen_titles = {t for t, _ in raw_pages}
                raw_pages += [(r["title"], r["wikitext"]) for r in db.execute(
                    "SELECT title, wikitext FROM wiki_pages WHERE wiki=%s AND kind='episode' AND NOT (title = ANY(%s))",
                    (f["wiki"], list(seen_titles)))]
        pages = []
        for title, wikitext in raw_pages:
            if (f.get("include") and not re.search(f["include"], title)) or \
               (f.get("exclude") and re.search(f["exclude"], title)) or re.match(r"(List of|Episode List)\b|Episodes?$", title, re.I):
                continue
            p = parse_episode_wikitext(wikitext)
            if all(_infobox_ok(p["infobox"].get(k, ""), v) for k, v in f.get("infobox", {}).items()):
                pages.append((title, p))
        if first_found is None:
            numbers = number_pages(pages, by_title, by_date, aired)
        else:
            # 더 찾아본 문서에는 다른 작품·게임의 'Episode N'도 섞여 있으므로, 회차 분류의 문서끼리 먼저 번호를 정하고
            # 더 찾아본 문서는 아직 비어 있는 회차에만 붙임
            numbers = number_pages([x for x in pages if x[0] in first_found], by_title, by_date, aired)
            taken = set(numbers.values())
            for title, n in number_pages(pages, by_title, by_date, aired).items():
                if title not in first_found and n not in taken:
                    numbers[title] = n
                    taken.add(n)

        # 제목이 여러 회차에 쓰여 위에서 가리지 못한 문서: 다른 방법으로도 번호가 안 붙었으면 그 제목의 앞 회차에 붙임
        for title, p in pages:
            n = repeated_title.get(norm_title(p["title"])) or repeated_title.get(norm_title(title))
            if title not in numbers and n and n not in numbers.values():
                numbers[title] = n

        def date_ok(item):                    # 문서의 방영일이 그 회차의 방영일과 맞는가 (하루 차이까지)
            day = aired.get(numbers.get(item[0]))
            return bool(day) and any(abs((d - day).days) <= 1 for d in item[1]["airdates"])

        dated = [x for x in pages if x[1]["airdates"] and aired.get(numbers.get(x[0]))]
        date_hits = sum(date_ok(x) for x in dated)
        got = with_plot = unnumbered = dup = title_ok = 0
        # 방영 중인 작품도 다른 출처가 아는 마지막 회차까지만 받음 (같은 위키의 다른 작품이 뒤 번호로 붙는 것을 막음)
        last_known = max(s["total_episodes"] or 0, max(title_of, default=0), max(aired, default=0))
        seen, rows = set(), []
        # 같은 번호가 겹치면 방영일이 맞는 문서, 그다음 줄거리가 있는 문서를 씀
        for title, p in sorted(pages, key=lambda x: (not date_ok(x), len(x[1]["plot"]) < 500)):
            abs_ep = numbers.get(title)
            hit = owner_of(entries, abs_ep)
            if not hit or abs_ep > last_known:
                unnumbered += 1
                continue
            if abs_ep in seen:
                dup += 1
                continue
            seen.add(abs_ep)
            ep_title = title if not EP_PAGE_RE.fullmatch(title) else (p["title"] or title)
            ep_title = re.sub(r"\s*\((?:episode|anime)\)$", "", ep_title, flags=re.I)
            rows.append((title, p, abs_ep, hit, ep_title))
            title_ok += _same_title(ep_title, title_of.get(abs_ep))
        for title, p, abs_ep, hit, ep_title in list(rows):      # 문서 하나가 여러 화(단편 5개 묶음)를 다루는 위키
            for n in range(abs_ep + 1, abs_ep + p.get("span", 1)):
                more = owner_of(entries, n)
                if more and n <= last_known and n not in seen:
                    seen.add(n)
                    rows.append((title, p, n, more, ep_title))
        # 자동으로 찾은 위키인데 회차 제목이 거의 안 맞으면 다른 작품의 위키이거나 번호 체계가 다른 것 → 저장하지 않음
        named = sum(1 for r in rows if not EP_PAGE_RE.fullmatch(r[4]))     # 회차 제목을 읽을 수 있었던 문서
        # (번역이 달라 제목이 안 맞는 위키가 많으므로, 방영일이 맞으면 같은 작품으로 봄)
        if f.get("auto") and len(by_title) >= 6 and named >= 6 and title_ok < 0.1 * named \
                and date_hits < 0.3 * max(6, min(len(dated), sum(map(bool, by_date.values())))):
            return "empty", (f"자동으로 찾은 위키 {f['wiki']}의 회차 제목이 TVmaze와 맞지 않음 "
                             f"({title_ok}/{named}화, 방영일 일치 {date_hits}/{len(dated)}) → 저장 안 함. 직접 확인 필요")
        # 다시 정리할 때 예전에 다른 회차에 붙었던 문서가 남지 않도록 먼저 비움
        db.execute("""UPDATE episodes SET fandom_url=NULL, fandom_title=NULL, arc=NULL, chapters=NULL, characters=NULL,
                        synopsis_en=NULL, plot=NULL WHERE series_id=%s AND fandom_url IS NOT NULL""", (s["series_id"],))
        for title, p, abs_ep, hit, ep_title in rows:
            upsert_episode(db, s["series_id"], *hit, fandom_title=ep_title, arc=p["arc"],
                           fandom_url=f"{base}/wiki/{title.replace(' ', '_')}",
                           chapters=p["chapters"], characters=p["characters"],
                           synopsis_en=p["synopsis"] or None, plot=p["plot"] or None)
            got += 1
            with_plot += len(p["plot"]) >= 500
        # 예전에 위키 문서만으로 만들어졌다가 이제 아무 정보도 남지 않은 회차 행은 지움
        db.execute("""DELETE FROM episodes WHERE series_id=%s AND fandom_url IS NULL AND title_en IS NULL AND title_ko IS NULL
                        AND airdate IS NULL AND overview_ko IS NULL AND tmdb_number IS NULL AND filler IS NULL""",
                   (s["series_id"],))
        link_character_debuts(db, s["series_id"])
        detail = (f"{got}화 (상세 줄거리 {with_plot}화), 회차 번호를 못 찾은 문서 {unnumbered}개, 번호 중복 {dup}개, "
                  f"TVmaze 제목과 일치 {title_ok}화, 방영일 일치 {date_hits}화, 라이선스 {license_ or '확인 필요'}")
        return ("ok" if got else "empty"), detail

    ids = list(cfg)
    known = {r["series_id"] for r in db.execute("SELECT series_id FROM series WHERE series_id = ANY(%s)", (ids,))}
    if set(ids) - known:
        print(f"  ! fandom_wikis.json의 시리즈 ID가 DB에 없음: {sorted(set(ids) - known)}")
    # 위키 목록은 사람이 고른 것이라 인기순 제한 없이, 받은 원문(raw 캐시)으로 매번 다시 정리함
    limit, args.limit = args.limit, None
    rows = [r for r in targets(db, "fandom", args, redo=True) if r["series_id"] in ids]
    args.limit = limit
    run_each(db, "fandom", rows, one)


# ───────────────────────── 6-1. Fandom 위키 자동 찾기 ─────────────────────────

EPISODE_CATEGORIES = ("Episodes", "Anime Episodes", "Anime episodes", "Episode", "Anime Episode", "Episodes (Anime)")
SEASON_WORDS = re.compile(r"\b(\d+(st|nd|rd|th) season|season \d+|part \d+|(the )?final season|2nd|ii+|tv)\b.*", re.I)


def wiki_slugs(titles):
    """작품 제목들 → 있을 법한 위키 주소 후보 ('Attack on Titan' → attack-on-titan, attackontitan)."""
    out = []
    for title in titles:
        plain = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
        plain = SEASON_WORDS.sub("", re.sub(r"\(.*?\)", " ", plain))
        for part in dict.fromkeys((plain, re.split(r":| - ", plain)[0])):
            tokens = re.findall(r"[a-z0-9]+", part)
            if len("".join(tokens)) >= 4:
                out += ["-".join(tokens), "".join(tokens)]
            if len(tokens) > 2 and len("".join(tokens[:2])) >= 5:      # 'Re:Zero kara …' → rezero
                out.append("".join(tokens[:2]))
    return list(dict.fromkeys(out))[:10]


def probe_wiki(db, slug):
    """위키가 있으면 {'sitename', 'cats': {분류: 문서 수}}, 없으면 None. 결과는 raw에 기억."""
    row = db.execute("SELECT data FROM raw WHERE source='fandom_probe' AND key=%s", (slug,)).fetchone()
    if row and not REFRESH:
        return row["data"] or None
    wait = MIN_INTERVAL["fandom.com"] - (time.time() - _last_call.get("fandom.com", 0))
    if wait > 0:
        time.sleep(wait)
    _last_call["fandom.com"] = time.time()
    data = None
    try:
        r = _session.get(f"https://{slug}.fandom.com/api.php", allow_redirects=False, timeout=(10, 30), params={
            "action": "query", "meta": "siteinfo", "siprop": "general", "prop": "categoryinfo",
            "titles": "|".join(f"Category:{c}" for c in EPISODE_CATEGORIES), "format": "json", "formatversion": 2})
        if r.status_code == 200:
            q = r.json().get("query", {})
            data = {"sitename": q.get("general", {}).get("sitename"),
                    "cats": {pg["title"].split(":", 1)[1]: pg.get("categoryinfo", {}).get("pages", 0)
                             for pg in q.get("pages", []) if pg.get("categoryinfo")}}
        elif r.status_code >= 500 or r.status_code == 429:
            return None                      # 일시 오류는 기억하지 않고 다음 실행에서 다시 확인
    except (requests.RequestException, ValueError):
        return None
    db.execute("""INSERT INTO raw (source, key, data) VALUES ('fandom_probe', %s, %s)
                  ON CONFLICT (source, key) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()""",
               (slug, Jsonb(data)))
    return data


WIKIDATA_QUERY = """SELECT ?fandom ?anilist ?mal WHERE {
  ?item wdt:P6262 ?fandom .
  OPTIONAL { ?item wdt:P8729 ?anilist } OPTIONAL { ?item wdt:P4086 ?mal }
  FILTER(BOUND(?anilist) || BOUND(?mal))
}"""


def title_key(title):
    plain = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", SEASON_WORDS.sub("", re.sub(r"\(.*?\)", " ", plain)))


def wiki_directory(db):
    """이미 정리된 위키 목록 두 가지를 받아 둠 (한 번 받으면 raw에 기억).

    ① Fandom 'Animanga' 허브의 애니·만화 위키 목록: {작품 제목: 위키 주소} 약 3천 개 → 제목으로 찾음
    ② 위키데이터: AniList·MAL ID가 있는 항목의 Fandom 주소 → ID로 찾음 (제목이 달라도 정확)
    """
    row = db.execute("SELECT data FROM raw WHERE source='fandom_directory' AND key='all'").fetchone()
    if row and not REFRESH:
        return row["data"]
    by_title, offset = {}, 0
    while offset is not None:
        d = http(db, "GET", "https://animanga.fandom.com/api.php", params={
            "action": "ask", "format": "json",
            "query": f"[[Concept:Series]][[Wiki Name::+]]|?Wiki Name|limit=500|offset={offset}"}) or {}
        for title, v in (d.get("query", {}).get("results") or {}).items():
            names = v["printouts"].get("Wiki Name") or []
            if names and title_key(title):
                by_title.setdefault(title_key(title), names[0].strip().lower())
        offset = d.get("query-continue-offset")
    by_id = {}
    try:
        r = _session.get("https://query.wikidata.org/sparql", params={"query": WIKIDATA_QUERY}, timeout=120,
                         headers={"Accept": "application/sparql-results+json"})
        r.raise_for_status()
        for b in r.json()["results"]["bindings"]:
            wiki = b["fandom"]["value"].split(":")[0].lower()
            if "." in wiki:                      # 영어가 아닌 위키 (es.doblaje 등)
                continue
            for src in ("anilist", "mal"):
                if src in b:
                    by_id.setdefault(f"{src}:{b[src]['value']}", wiki)
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"  ! 위키데이터 조회 실패, 건너뜀: {e}")
    data = {"by_title": by_title, "by_id": by_id}
    db.execute("""INSERT INTO raw (source, key, data) VALUES ('fandom_directory', 'all', %s)
                  ON CONFLICT (source, key) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()""", (Jsonb(data),))
    return data


def save_fandom_config(doc):
    lines = ["{", '  "_설명": ' + json.dumps(doc["_설명"], ensure_ascii=False, indent=4).replace("\n]", "\n  ]") + ",",
             '  "wikis": {']
    items = list(doc["wikis"].items())
    for i, (sid, cfg) in enumerate(items):
        lines.append(f'    {json.dumps(sid)}: {json.dumps(cfg, ensure_ascii=False)}' + ("," if i < len(items) - 1 else ""))
    (DATA / "fandom_wikis.json").write_text("\n".join(lines + ["  }", "}"]) + "\n", encoding="utf-8")


def step_fandom_find(db, args):
    """인기 상위 작품의 Fandom 위키를 찾아, 회차 문서가 충분하면 fandom_wikis.json에 추가.

    찾는 순서: ① 위키데이터(AniList·MAL ID로) ② Fandom 애니 위키 목록(제목·별칭으로) ③ 제목으로 주소 추측.
    """
    doc = json.loads((DATA / "fandom_wikis.json").read_text(encoding="utf-8"))
    directory = wiki_directory(db)
    print(f"  위키 목록: 제목 {len(directory['by_title']):,}개, ID {len(directory['by_id']):,}개")
    rows = db.execute("""SELECT s.*, e.title_en, e.synonyms,
                           (SELECT array_agg(x.entry_key) || array_agg('mal:' || x.mal_id)
                            FROM entries x WHERE x.series_id = s.series_id) ids
                         FROM series s JOIN entries e ON e.series_id = s.series_id AND e.order_in_series = 1
                         WHERE s.total_episodes > 0
                         ORDER BY s.popularity DESC NULLS LAST, s.series_id LIMIT %s""", (args.limit or 300,)).fetchall()
    rows = [r for r in rows if r["series_id"] not in doc["wikis"]]
    added = {"위키데이터": 0, "위키 목록": 0, "주소 추측": 0}
    for i, s in enumerate(rows, 1):
        titles = [s["title_en"], s["title"], s["title_original"], *(s["alt_titles"] or []), *(s["synonyms"] or [])]
        candidates = [(directory["by_id"][k], "위키데이터") for k in s["ids"] or [] if k in directory["by_id"]]
        candidates += [(directory["by_title"][title_key(t)], "위키 목록") for t in titles
                       if t and title_key(t) in directory["by_title"]]
        candidates += [(slug, "주소 추측") for slug in wiki_slugs([s["title_en"], s["title"]])]
        found, tried = None, set()
        for slug, how in candidates:
            if slug in tried:
                continue
            tried.add(slug)
            info = probe_wiki(db, slug)
            if not info or not (info["cats"] or how != "주소 추측"):
                continue
            cat, pages = max(info["cats"].items(), key=lambda kv: kv[1]) if info["cats"] else ("Episodes", 0)
            total = s["total_episodes"]
            shared = any(w["wiki"] == slug for w in doc["wikis"].values())
            if how != "주소 추측":
                # 위키데이터·위키 목록이 짝지어 준 위키: 회차 분류가 시즌별 하위 분류로 나뉘었거나(문서 수가 적게 보임)
                # 여러 작품이 같이 쓰는 위키여도 받음. 어느 문서가 이 작품의 회차인지는 fandom 단계가 방영일로 가려냄
                found = (slug, cat, pages, how)
                break
            if pages <= 2 * total + 12 and not shared and pages >= max(4, 0.5 * total):
                found = (slug, cat, pages, how)
                break
        if found:
            slug, cat, pages, how = found
            doc["wikis"][s["series_id"]] = {"title": s["title_ko"] or s["title"], "wiki": slug,
                                            **({"category": cat} if cat != "Episodes" else {}),
                                            "auto": True, "found_by": how}
            added[how] += 1
            save_fandom_config(doc)
            print(f"  + {s['title_ko'] or s['title']}: {slug}.fandom.com ({cat} {pages}개 / {s['total_episodes']}화, {how})",
                  flush=True)
        if i % 25 == 0:
            print(f"  [{i}/{len(rows)}] 지금까지 {sum(added.values())}개 찾음", flush=True)
    print(f"  {len(rows)}개 작품 중 {sum(added.values())}개의 위키를 찾아 fandom_wikis.json에 추가 "
          f"({', '.join(f'{k} {v}개' for k, v in added.items())}). 이어서 fandom chunks report를 실행하세요")


# ───────────────────────── 6-2. Fandom 위키 전체 문서 ─────────────────────────

def fandom_config():
    return json.loads((DATA / "fandom_wikis.json").read_text(encoding="utf-8"))["wikis"]


def step_wiki(db, args):
    """fandom_wikis.json에 있는 위키의 모든 문서(캐릭터·용어·장소·조직 …)를 wiki_pages에 저장.

    중간에 멈추면 마지막으로 받은 문서 제목 다음부터 이어 받습니다. --reparse는 받아 둔 원문으로 다시 정리만 합니다.
    """
    cfg = fandom_config()
    rows = db.execute("SELECT * FROM series WHERE series_id = ANY(%s) ORDER BY popularity DESC NULLS LAST",
                      (list(cfg),)).fetchall()
    if args.series:
        rows = [r for r in rows if r["series_id"] == args.series]
    wikis = list(dict.fromkeys(cfg[r["series_id"]]["wiki"] for r in rows))[:args.limit or None]
    done = {r["detail"] for r in db.execute("SELECT DISTINCT detail FROM fetch_log WHERE source='wiki' AND status='ok'")}
    started = time.time()
    for n, wiki in enumerate(wikis, 1):
        users = [sid for sid, f in cfg.items() if f["wiki"] == wiki]
        if REPARSE:
            for pg in db.execute("SELECT title, wikitext FROM wiki_pages WHERE wiki=%s", (wiki,)).fetchall():
                _save_wiki_page(db, wiki, pg["title"], pg["wikitext"])
            print(f"  [{n}/{len(wikis)}] {wiki} 다시 정리", flush=True)
            continue
        if wiki in done and not REFRESH:
            continue
        api = f"https://{wiki}.fandom.com/api.php"
        try:
            last = db.execute("""SELECT title FROM wiki_pages WHERE wiki=%s
                                 ORDER BY replace(title, ' ', '_') COLLATE "C" DESC LIMIT 1""", (wiki,)).fetchone()
            cont, got = ({"gapfrom": last["title"]} if last and not REFRESH else {}), 0
            while True:
                d = http(db, "GET", api, params={
                    "action": "query", "generator": "allpages", "gapnamespace": 0, "gapfilterredir": "nonredirects",
                    "gaplimit": 50, "prop": "revisions", "rvprop": "content", "rvslots": "main",
                    "format": "json", "formatversion": 2, **cont}) or {}
                for pg in d.get("query", {}).get("pages", []):
                    revs = pg.get("revisions") or []
                    if revs:
                        _save_wiki_page(db, wiki, pg["title"], revs[0]["slots"]["main"]["content"])
                        got += 1
                nxt = d.get("continue")
                if not nxt:
                    break
                cont = {k: v for k, v in nxt.items() if k != "continue"}
            total = db.execute("SELECT count(*) n FROM wiki_pages WHERE wiki=%s", (wiki,)).fetchone()["n"]
            for sid in users:
                log(db, sid, "wiki", "ok", wiki)
            left = (time.time() - started) / n * (len(wikis) - n)
            print(f"  [{n}/{len(wikis)}, 남은 시간 약 {left / 60:.0f}분] {wiki} → 문서 {total:,}개 (이번에 {got:,}개)", flush=True)
        except Exception as e:  # noqa: BLE001 — 위키 하나가 실패해도 나머지는 계속
            for sid in users:
                log(db, sid, "wiki", "error", f"{e.__class__.__name__}: {e}"[:300])
            print(f"  [{n}/{len(wikis)}] {wiki} → error {e}", flush=True)


def _save_wiki_page(db, wiki, title, wikitext):
    wikitext = wikitext[:400_000]
    try:
        p = parse_wiki_page(wikitext) if len(wikitext) >= 200 else \
            {"kind": "stub", "infobox_name": None, "infobox": {}, "sections": {}, "links": []}
    except Exception:  # noqa: BLE001 — 깨진 문법의 문서는 원문만 보관
        p = {"kind": "other", "infobox_name": None, "infobox": {}, "sections": {}, "links": []}
    clean = lambda x: x.replace("\x00", "") if isinstance(x, str) else x
    db.execute("""INSERT INTO wiki_pages (wiki, title, kind, infobox_name, infobox, sections, links, wikitext)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT (wiki, title) DO UPDATE SET kind=EXCLUDED.kind, infobox_name=EXCLUDED.infobox_name,
                    infobox=EXCLUDED.infobox, sections=EXCLUDED.sections, links=EXCLUDED.links,
                    wikitext=EXCLUDED.wikitext, fetched_at=now()""",
               (wiki, title, p["kind"], p["infobox_name"],
                Jsonb({k: clean(v) for k, v in p["infobox"].items()}),
                Jsonb({clean(k): clean(v) for k, v in p["sections"].items()}),
                [clean(l) for l in p["links"]], clean(wikitext)))


# 위키 문서에서 청크로 만드는 종류와 구역. 줄거리·내력(History, Plot …) 구역은 뒤 회차 내용이 섞여 있어 쓰지 않음
WIKI_CHUNK_KINDS = {"character": "캐릭터", "ability": "능력·기술", "item": "물건·장비", "location": "장소", "group": "조직·집단"}
# 캐릭터의 성격(Personality) 구역은 후반부 정체·배신이 그대로 적힌 경우가 많아 제외하고 외형만 씀
SAFE_SECTION_RE = re.compile(r"^(appearance|description|overview|characteristics|design)\b", re.I)


def wiki_chunks(db, s, name):
    """위키의 캐릭터·용어 문서 → 청크. 그 문서를 처음 가리킨 회차 문서의 회차부터 보이게 함.

    어느 회차 문서에서도 가리키지 않는 문서(애니에 아직 안 나온 원작 내용일 수 있음)는 청크로 만들지 않습니다.
    """
    f = fandom_config().get(s["series_id"])
    if not f:
        return []
    key = lambda t: t.replace("_", " ").strip().lower()
    first_seen = {}
    for ep in db.execute("""SELECT e.abs_ep, w.links FROM episodes e JOIN wiki_pages w
                              ON w.wiki = %s AND w.title = replace(split_part(e.fandom_url, '/wiki/', 2), '_', ' ')
                            WHERE e.series_id = %s AND e.fandom_url IS NOT NULL ORDER BY e.abs_ep""",
                         (f["wiki"], s["series_id"])).fetchall():
        for link in ep["links"] or []:
            first_seen.setdefault(key(link), ep["abs_ep"])
    rows = []
    for pg in db.execute("SELECT title, kind, sections FROM wiki_pages WHERE wiki=%s AND kind = ANY(%s)",
                         (f["wiki"], list(WIKI_CHUNK_KINDS))).fetchall():
        debut = first_seen.get(key(pg["title"]))
        if not debut:
            continue
        parts = [(sec, text) for sec, text in pg["sections"].items()
                 if SAFE_SECTION_RE.search(sec) or (sec == "_lead" and pg["kind"] != "character")]
        pieces = [(sec, para) for sec, text in parts for para in split_paragraphs(text)][:4]
        url = f"https://{f['wiki']}.fandom.com/wiki/{pg['title'].replace(' ', '_')}"
        for i, (sec, para) in enumerate(pieces, 1):
            if len(para) < 80:
                continue
            head = f"{name} {WIKI_CHUNK_KINDS[pg['kind']]} {pg['title']}" + ("" if sec == "_lead" else f" — {sec}")
            rows.append((f"{s['series_id']}:wiki:{pg['title']}:{i}",
                         "character" if pg["kind"] == "character" else "terminology",
                         debut if debut > 1 else None, None, None, f"{head}\n{para}", [_src("fandom", url)]))
    return rows


# ───────────────────────── 7. 청크 ─────────────────────────

def split_paragraphs(text, target=700):
    """문단을 이어 붙여 약 target자 단위로 나눔. 한 문단이 너무 길면 문장 단위로 다시 나눔."""
    paras = []
    for para in (p.strip() for p in re.split(r"\n+", text) if p.strip()):
        if len(para) <= target * 2:
            paras.append(para)
        else:
            paras += [x for x in re.split(r"(?<=[.!?])\s+", para) if x]
    out, buf = [], ""
    for para in paras:
        if buf and len(buf) + len(para) > target:
            out.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}".strip()
    if buf:
        out.append(buf)
    return out


def _src(name, url, license_=None):
    n, lic = LICENSES[name]
    return {"name": n, "license": license_ or lic, "url": url}


def build_chunks(db, s):
    """시리즈 하나의 청크 목록: (chunk_id, type, abs_ep, tmdb_season, filler, text, sources).

    abs_ep가 스포일러 차단 기준입니다. NULL이면 항상 검색 대상, 숫자면 그 회차까지 본 사용자에게만 보입니다.
    """
    sid = s["series_id"]
    name = s["title_ko"] or s["title"]
    rows = []
    for e in entries_of(db, sid):
        first = e["order_in_series"] == 1
        overview = s["overview_ko"] if first else None     # TMDB 한국어 소개는 작품 전체(1기 기준) 소개
        if e["description"] or e["synonyms"] or overview:
            text = "\n".join(x for x in (
                f"{name} — {e['title']}" + (f" ({e['year']})" if e["year"] else ""),
                "다른 이름: " + ", ".join(dict.fromkeys(
                    ([e["title_en"]] if e["title_en"] else []) + (s["alt_titles"] or [])[:8] + e["synonyms"][:15])),
                "장르: " + ", ".join(dict.fromkeys((s["genres_ko"] or []) + e["genres"] + e["tags"][:10]))
                if e["genres"] or e["tags"] or s["genres_ko"] else "",
                "키워드: " + ", ".join(s["keywords"][:15]) if first and s["keywords"] else "",
                s["tagline_ko"] if first else None, overview, e["description"]) if x)
            url = f"https://anilist.co/anime/{e['anilist_id']}" if e["anilist_id"] else None
            srcs = [_src("anilist", url)] + \
                   ([_src("tmdb", f"https://www.themoviedb.org/tv/{s['tmdb_id']}")] if overview else [])
            # 2기 이후 설명에는 앞 시즌 결말이 들어 있을 수 있어 앞 시즌을 다 본 뒤에만 보임
            rows.append((f"{sid}:summary:{e['entry_key']}", "summary", None if first else e["abs_offset"],
                         e["tmdb_season"], None, text, srcs))
    for c in db.execute("SELECT c.*, e.abs_offset FROM characters c JOIN entries e ON e.entry_key=c.first_entry "
                        "WHERE c.series_id=%s AND c.description IS NOT NULL", (sid,)):
        text = f"{name} 캐릭터 {c['name']}" + (f" ({c['name_native']})" if c["name_native"] else "") + \
               f" [{c['role']}]\n{c['description']}"
        # 첫 등장 회차를 알면 그 회차부터(1화 등장은 항상), 모르면 첫 등장 시즌이 시작될 때부터
        if c["first_abs_ep"]:
            visible_from = c["first_abs_ep"] if c["first_abs_ep"] > 1 else None
        else:
            visible_from = c["abs_offset"] or None
        rows.append((f"{sid}:char:{c['anilist_char']}", "character", visible_from, None, None, text,
                     [_src("anilist", f"https://anilist.co/character/{c['anilist_char']}")]))
    for ep in db.execute("SELECT * FROM episodes WHERE series_id=%s ORDER BY abs_ep", (sid,)):
        head = f"{name} " + (f"{ep['tmdb_season']}기 {ep['tmdb_number']}화 " if ep["tmdb_season"] else "") + \
               f"(전체 {ep['abs_ep']}화)"
        title = ep["title_ko"] or ep["title_en"] or ep["fandom_title"]
        body = [ep["overview_ko"], ep["summary_en"] or ep["overview_en"], ep["synopsis_en"]]
        if any(body):
            text = "\n".join(dict.fromkeys(x for x in (head, ep["title_ko"], ep["title_en"] or ep["fandom_title"],
                                                        *body) if x))
            srcs = ([_src("tvmaze", ep["tvmaze_url"])] if ep["summary_en"] else []) + \
                   ([_src("tmdb", f"https://www.themoviedb.org/tv/{s['tmdb_id']}")]
                    if ep["overview_ko"] or (ep["overview_en"] and not ep["summary_en"]) else []) + \
                   ([_src("fandom", ep["fandom_url"])] if ep["synopsis_en"] else [])
            rows.append((f"{sid}:ep:{ep['abs_ep']}", "episode", ep["abs_ep"], ep["tmdb_season"],
                         ep["filler"], text, srcs))
        if ep["plot"]:
            for i, para in enumerate(split_paragraphs(ep["plot"]), 1):
                rows.append((f"{sid}:event:{ep['abs_ep']}:{i}", "event", ep["abs_ep"], ep["tmdb_season"],
                             ep["filler"], f"{head}" + (f" 〈{title}〉" if title else "") + f" 장면\n{para}",
                             [_src("fandom", ep["fandom_url"])]))
    for st in db.execute("SELECT * FROM streaming WHERE series_id=%s", (sid,)):
        if not st["flatrate"]:
            continue
        text = f"{name} {st['season_name'] or str(st['tmdb_season']) + '기'} 국내 시청처: " + \
               ", ".join(st["flatrate"]) + f" (확인일 {st['checked_at']})"
        rows.append((f"{sid}:streaming:s{st['tmdb_season']}", "streaming", None, st["tmdb_season"], None, text,
                     [_src("justwatch", st["link"])]))
    return tidy_chunks(rows + wiki_chunks(db, s, name))


def step_chunks(db, args):
    def one(s):
        sid = s["series_id"]
        link_character_debuts(db, sid)
        rows = build_chunks(db, s)
        db.execute("DELETE FROM chunks WHERE series_id=%s AND NOT (chunk_id = ANY(%s))", (sid, [r[0] for r in rows]))
        with db.cursor() as cur:
            cur.executemany(
                """INSERT INTO chunks (chunk_id, series_id, type, abs_ep, tmdb_season, filler, text, sources)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (chunk_id) DO UPDATE SET type=EXCLUDED.type, abs_ep=EXCLUDED.abs_ep,
                     tmdb_season=EXCLUDED.tmdb_season, filler=EXCLUDED.filler,
                     sources=EXCLUDED.sources, text=EXCLUDED.text,
                     embedding = CASE WHEN chunks.text = EXCLUDED.text THEN chunks.embedding END""",
                [(r[0], sid, *r[1:6], Jsonb(r[6])) for r in rows])
        return ("ok" if rows else "empty"), f"청크 {len(rows)}개"

    # 청크는 원천 데이터가 바뀌면 다시 만들어야 하므로 항상 전체 대상
    run_each(db, "chunks", targets(db, "chunks", args, redo=True), one)


# ───────────────────────── 8. 임베딩·검색 ─────────────────────────

def embedding_config():
    import yaml
    cfg = (yaml.safe_load((REPO / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}).get("embedding") or {}
    if not cfg.get("model"):
        raise SystemExit("config/settings.yaml의 embedding.model을 정하세요")
    return cfg


_model = None


def embed_texts(texts, kind):
    """kind: 'passage'(청크) 또는 'query'(질문). 모델에 따라 앞에 붙이는 말이 다름."""
    global _model
    cfg = embedding_config()
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(cfg["model"])
    prefix = cfg.get(f"{kind}_prefix") or ""
    return _model.encode([prefix + t for t in texts], batch_size=cfg.get("batch_size", 32),
                         normalize_embeddings=True, show_progress_bar=False)


def step_embed(db, args):
    cfg = embedding_config()
    dim = db.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid='chunks'::regclass AND attname='embedding'"
                     ).fetchone()["atttypmod"]
    if dim != cfg.get("dim"):
        raise SystemExit(f"chunks.embedding은 {dim}차원인데 config의 embedding.dim은 {cfg.get('dim')}입니다. "
                         "schema.sql의 vector(N)과 맞추세요")
    series = [r["series_id"] for r in targets(db, "embed", args, redo=True)]
    todo = db.execute("SELECT count(*) n FROM chunks WHERE embedding IS NULL AND series_id = ANY(%s)",
                      (series,)).fetchone()["n"]
    print(f"  모델 {cfg['model']}, 임베딩할 청크 {todo:,}개")
    done, started = 0, time.time()
    while True:
        batch = db.execute("""SELECT chunk_id, text FROM chunks WHERE embedding IS NULL AND series_id = ANY(%s)
                              LIMIT 256""", (series,)).fetchall()
        if not batch:
            break
        vecs = embed_texts([r["text"] for r in batch], "passage")
        with db.transaction(), db.cursor() as cur:
            cur.executemany("UPDATE chunks SET embedding = %s::vector WHERE chunk_id = %s",
                            [(str(v.tolist()), r["chunk_id"]) for v, r in zip(vecs, batch)])
        done += len(batch)
        if done % 2560 == 0 or done >= todo:
            print(f"  {done:,}/{todo:,} ({done / (time.time() - started):.0f}개/초)", flush=True)
    db.execute("CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)")
    print("  임베딩 완료, 벡터 인덱스 확인")


def search_chunks(db, query_vector, *, watched: dict[str, int], series_id=None, types=None, k=5):
    """벡터 검색. watched = {시리즈 ID: 본 회차}는 필수 인자입니다.

    본 회차 이후 청크는 정렬·검색 *전에* WHERE에서 제외합니다 (결과에서 걸러내지 않음).
    watched에 없는 시리즈는 0화까지 본 것으로 보고, 회차와 무관한 청크(abs_ep IS NULL)만 검색합니다.
    """
    if watched is None:
        raise TypeError("watched(시리즈별 본 회차)는 반드시 넘겨야 합니다")
    vec = str([float(x) for x in query_vector])
    with db.transaction():
        db.execute("SET LOCAL hnsw.iterative_scan = strict_order")   # 필터 때문에 k개가 안 채워지는 일을 막음
        return db.execute(
            """SELECT c.chunk_id, c.series_id, c.type, c.abs_ep, c.tmdb_season, c.text, c.sources,
                      1 - (c.embedding <=> %(vec)s::vector) AS score
               FROM chunks c
               LEFT JOIN jsonb_each_text(%(watched)s) w ON w.key = c.series_id
               WHERE c.embedding IS NOT NULL
                 AND (c.abs_ep IS NULL OR c.abs_ep <= COALESCE(w.value::int, 0))
                 AND (%(sid)s::text IS NULL OR c.series_id = %(sid)s)
                 AND (%(types)s::text[] IS NULL OR c.type = ANY(%(types)s))
               ORDER BY c.embedding <=> %(vec)s::vector
               LIMIT %(k)s""",
            {"vec": vec, "watched": Jsonb(dict(watched)), "sid": series_id, "types": types, "k": k}).fetchall()


def step_search(db, args):
    if not args.query:
        raise SystemExit('사용법: python data/collect.py search "질문" --series tmdb:65930 --watched 49')
    if args.watched is None:
        raise SystemExit("--watched N (본 회차)는 필수입니다. 아직 안 본 작품이면 0")
    watched = {args.series: args.watched} if args.series else {}
    vec = embed_texts([args.query], "query")[0]
    for r in search_chunks(db, vec, watched=watched, series_id=args.series, k=args.k):
        where = f"전체 {r['abs_ep']}화" if r["abs_ep"] else "회차 무관"
        print(f"  {r['score']:.3f} [{r['type']}] {r['series_id']} {where}\n      "
              + r["text"][:220].replace("\n", " / "))


# ───────────────────────── 현황 ─────────────────────────

SOURCE_SCOPE = {"tvmaze": "s.tvdb_id IS NOT NULL OR s.tvmaze_id IS NOT NULL", "tmdb": "s.tmdb_id IS NOT NULL"}


def step_status(db, args):
    """출처별 진행률. --limit N을 주면 인기순 상위 N개 안에서의 진행률을 보여줌."""
    r = db.execute("SELECT count(*) series, sum(total_episodes) eps, count(popularity) with_pop FROM series").fetchone()
    print(f"  전체: 시리즈 {r['series']:,}개, 회차 {r['eps'] or 0:,}개, 인기도 있는 시리즈 {r['with_pop']:,}개")
    scope = f"인기 상위 {args.limit:,}개" if args.limit else "전체"
    print(f"  ── 수집 진행률 ({scope} 시리즈 기준) ──")
    for src in ("tvmaze", "tmdb", "jikan", "characters", "chunks"):
        row = db.execute(f"""
            WITH top AS (SELECT * FROM series ORDER BY popularity DESC NULLS LAST, series_id LIMIT %s)
            SELECT count(*) FILTER (WHERE {SOURCE_SCOPE.get(src, 'TRUE')}) target,
                   count(*) FILTER (WHERE f.status = 'ok') ok, count(*) FILTER (WHERE f.status = 'empty') empty,
                   count(*) FILTER (WHERE f.status = 'error') err, max(f.fetched_at) last
            FROM top s LEFT JOIN fetch_log f ON f.series_id = s.series_id AND f.source = %s""",
                         (args.limit or r["series"], src)).fetchone()
        done = row["ok"] + row["empty"]
        pct = done / row["target"] if row["target"] else 0
        bar = "█" * round(pct * 20) + "░" * (20 - round(pct * 20))
        last = f", 마지막 {row['last'].astimezone():%m-%d %H:%M}" if row["last"] else ""
        print(f"  {src:<11}{bar} {done:>6,}/{row['target']:,} ({pct:.0%})  데이터 있음 {row['ok']:,} · 없음 {row['empty']:,}"
              f" · 실패 {row['err']:,}{last}")
    f = db.execute("SELECT count(*) n FROM fetch_log WHERE source='fandom' AND status='ok'").fetchone()["n"]
    print(f"  fandom     상세 줄거리를 받은 작품 {f}개 (fandom_wikis.json 기준)")
    e = db.execute("""SELECT count(*) n, count(title_en) tvm, count(overview_ko) ko, count(filler) fil,
                             count(*) FILTER (WHERE length(plot) >= 500) plot FROM episodes""").fetchone()
    print(f"  ── 쌓인 데이터 ──\n  회차 {e['n']:,}개 (영어 제목 {e['tvm']:,} · 한국어 줄거리 {e['ko']:,} · 상세 줄거리 {e['plot']:,}"
          f" · 필러 정보 {e['fil']:,}), 캐릭터 {db.execute('SELECT count(*) n FROM characters').fetchone()['n']:,}명")
    for r in db.execute("SELECT type, count(*) n, count(embedding) embedded FROM chunks GROUP BY 1 ORDER BY 1"):
        print(f"  청크 {r['type']:<10} {r['n']:>8,}  (임베딩 {r['embedded']:,})")
    size = db.execute("SELECT pg_size_pretty(pg_database_size(current_database())) s").fetchone()["s"]
    print(f"  DB 크기 {size}")


READY = 0.9   # 채움률이 이 이상인 작품만 회차 기능을 켬


def step_report(db, args):
    lim = args.limit or 100
    tiers = db.execute("""
        WITH ep AS (SELECT series_id, count(*) FILTER (WHERE summary_en IS NOT NULL OR overview_ko IS NOT NULL
                                                        OR overview_en IS NOT NULL OR synopsis_en IS NOT NULL) summ,
                           count(*) FILTER (WHERE length(plot) >= 500) plot FROM episodes GROUP BY 1)
        SELECT count(*) total, count(*) FILTER (WHERE s.tmdb_id IS NOT NULL OR s.tvdb_id IS NOT NULL) linked,
               count(*) FILTER (WHERE ep.summ >= %(r)s * NULLIF(s.total_episodes,0)) ep_ready,
               count(*) FILTER (WHERE ep.plot >= %(r)s * NULLIF(s.total_episodes,0)) detail_ready
        FROM series s LEFT JOIN ep USING (series_id)""", {"r": READY}).fetchone()
    lines = [f"# 수집 리포트 ({dt.date.today()})", "",
             f"- 전체 시리즈: {tiers['total']:,}개 → 작품 찾기 가능",
             f"- 회차 목록 출처(TMDB·TVmaze)에 연결된 시리즈: {tiers['linked']:,}개",
             f"- 회차 요약 {READY:.0%} 이상: {tiers['ep_ready']:,}개 → 회차 찾기 가능",
             f"- 상세 줄거리 {READY:.0%} 이상: {tiers['detail_ready']:,}개 → 장면 검색·복습 가능", "",
             "## 상세 줄거리(Fandom)를 받은 시리즈", "",
             "| 시리즈 | 총 회차 | 상세 줄거리 | 채움률 | 평균 길이(자) | 장면 청크 | 원작 화수 | 아크 | 수집 결과 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in db.execute("""
        SELECT s.series_id, coalesce(s.title_ko, s.title) t, s.total_episodes n,
          count(*) FILTER (WHERE length(e.plot) >= 500) plot, round(avg(length(e.plot))) len,
          count(e.chapters) ch, count(e.arc) arc,
          (SELECT count(*) FROM chunks c WHERE c.series_id=s.series_id AND c.type='event') events, f.detail
        FROM fetch_log f JOIN series s USING (series_id) LEFT JOIN episodes e USING (series_id)
        WHERE f.source='fandom' GROUP BY s.series_id, f.detail ORDER BY s.popularity DESC NULLS LAST"""):
        rate = r["plot"] / r["n"] if r["n"] else 0
        lines.append(f"| {r['t']} (`{r['series_id']}`) | {r['n']} | {r['plot']} | {rate:.0%} | {r['len'] or 0:,} | "
                     f"{r['events']:,} | {r['ch']} | {r['arc']} | {r['detail']} |")
    lines += ["", f"## 인기 상위 {lim}개 시리즈", "",
              "| 순위 | 시리즈 | 총 회차 | TVmaze 요약 | TMDB 한국어 줄거리 | 필러 정보 | 상세 줄거리 | 캐릭터 | 국내 OTT | 실패 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(db.execute("""
        SELECT s.series_id, coalesce(s.title_ko, s.title) t, s.total_episodes n,
          count(e.summary_en) tvm, count(e.overview_ko) ko, count(e.filler) jik,
          count(*) FILTER (WHERE length(e.plot) >= 500) plot,
          (SELECT count(*) FROM characters c WHERE c.series_id=s.series_id) ch,
          (SELECT string_agg(DISTINCT p, ', ') FROM streaming st, unnest(st.flatrate) p WHERE st.series_id=s.series_id) ott,
          (SELECT string_agg(source, ',') FROM fetch_log f WHERE f.series_id=s.series_id AND f.status='error') err
        FROM series s LEFT JOIN episodes e USING (series_id)
        GROUP BY s.series_id ORDER BY s.popularity DESC NULLS LAST, s.series_id LIMIT %s""", (lim,)), 1):
        lines.append(f"| {i} | {r['t']} (`{r['series_id']}`) | {r['n']} | {r['tvm']} | {r['ko']} | {r['jik']} | "
                     f"{r['plot']} | {r['ch']} | {r['ott'] or ''} | {r['err'] or ''} |")
    errors = db.execute("SELECT series_id, source, detail FROM fetch_log WHERE status='error' LIMIT 50").fetchall()
    if errors:
        lines += ["", "## 오류 (최대 50개)", ""] + [f"- `{e['series_id']}` {e['source']}: {e['detail']}" for e in errors]
    PROCESSED.mkdir(exist_ok=True)
    (PROCESSED / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  {PROCESSED / 'report.md'}")


# ───────────────────────── 실행 ─────────────────────────

def step_init(db, args):
    db.execute((DATA / "schema.sql").read_text(encoding="utf-8"))
    print("  테이블 생성 완료")


def ensure_database(url=None):
    """DATABASE_URL(또는 url)의 데이터베이스가 아직 없으면 만듦 (init·migrate 단계에서만)."""
    url = url or DB_URL
    info = psycopg.conninfo.conninfo_to_dict(url)
    try:
        psycopg.connect(url).close()
    except psycopg.OperationalError as e:
        if "does not exist" not in str(e):
            raise
        with psycopg.connect(psycopg.conninfo.make_conninfo(url, dbname="postgres"), autocommit=True) as admin:
            admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(info["dbname"])))
        print(f"  데이터베이스 {info['dbname']} 생성")


# ───────────────────────── 서비스용 DB ─────────────────────────

# 시리즈 단위로 옮기는 테이블 (참조 순서). raw(API 원본 캐시)는 옮기지 않음
SERVICE_TABLES = ("series", "entries", "episodes", "characters", "streaming", "seasons", "voice_cast", "chunks",
                  "fetch_log")
IN_SERVICE = "t.series_id IN (SELECT series_id FROM migrate_ids)"


def service_config():
    import yaml
    return (yaml.safe_load((REPO / "config" / "settings.yaml").read_text(encoding="utf-8")) or {}).get("service_db") or {}


def _copy_rows(src, dst, table, where, skip=()):
    """src의 table에서 where에 맞는 행을 dst의 같은 테이블로 복사. 칸 순서가 달라도 되도록 칸 이름을 적어서 옮김."""
    sql = psycopg.sql
    cols = sql.SQL(", ").join(sql.Identifier(r["column_name"]) for r in dst.execute(
        """SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s
           ORDER BY ordinal_position""", (table,)) if r["column_name"] not in skip)
    with src.cursor() as out, dst.cursor() as into:
        with out.copy(sql.SQL("COPY (SELECT {} FROM {} t WHERE {}) TO STDOUT").format(
                cols, sql.Identifier(table), where)) as reader, \
             into.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), cols)) as writer:
            for data in reader:
                writer.write(data)
        return into.rowcount


def step_migrate(db, args):
    """상세 줄거리가 제대로 있는 시리즈만 서비스용 DB로 옮김. 수집 DB는 읽기만 하고, 서비스용 DB는 매번 새로 채움.

    기준: 500자 이상 상세 줄거리(plot)가 있는 회차 ÷ 전체 회차 ≥ --min-fill (기본 config의 service_db.min_plot_fill).
    """
    cfg = service_config()
    name = args.to or cfg.get("name")
    fill = args.min_fill if args.min_fill is not None else cfg.get("min_plot_fill", READY)
    if not name:
        raise SystemExit("옮길 DB 이름을 --to 또는 config/settings.yaml의 service_db.name에 정하세요")
    if name == db.info.dbname:
        raise SystemExit(f"--to가 수집 DB({name})와 같습니다. 다른 이름을 쓰세요")
    url = psycopg.conninfo.make_conninfo(DB_URL, dbname=name)
    ensure_database(url)
    sql = psycopg.sql
    with psycopg.connect(url, row_factory=dict_row, autocommit=True) as dst:
        dst.execute((DATA / "schema.sql").read_text(encoding="utf-8"))
        # 양쪽 다 한 트랜잭션: 수집이 돌고 있어도 같은 시점의 데이터를 읽고, 중간에 실패하면 서비스용 DB는 이전 상태로 남음
        with db.transaction(), dst.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            db.execute("""CREATE TEMP TABLE migrate_ids ON COMMIT DROP AS
                          SELECT s.series_id FROM series s JOIN episodes e USING (series_id) GROUP BY s.series_id
                          HAVING count(*) FILTER (WHERE length(e.plot) >= 500)
                                 >= %s * greatest(s.total_episodes, count(*))""", (fill,))
            ids = {r["series_id"] for r in db.execute("SELECT series_id FROM migrate_ids")}
            total = db.execute("SELECT count(*) n FROM series").fetchone()["n"]
            print(f"  상세 줄거리 채움률 {fill:.0%} 이상: {len(ids):,}개 / 전체 {total:,}개 시리즈 → {name}")
            dst.execute("TRUNCATE series, wiki_pages CASCADE")
            for table in SERVICE_TABLES:
                print(f"  {table}: {_copy_rows(db, dst, table, sql.SQL(IN_SERVICE)):,}행", flush=True)
            # 위키 문서는 chunks 단계가 캐릭터·용어 청크를 다시 만들 때 필요. 원문(wikitext)은 수집 DB에만 둠
            wikis = sorted({f["wiki"] for sid, f in fandom_config().items() if sid in ids})
            n = _copy_rows(db, dst, "wiki_pages", sql.SQL("t.wiki = ANY({})").format(sql.Literal(wikis)),
                           skip=("wikitext",))
            print(f"  wiki_pages: {n:,}행 (위키 {len(wikis):,}개, 원문 제외)", flush=True)
        if dst.execute("SELECT 1 FROM chunks WHERE embedding IS NOT NULL LIMIT 1").fetchone():
            dst.execute("CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops)")
        dst.execute("ANALYZE")
        size = dst.execute("SELECT pg_size_pretty(pg_database_size(current_database())) s").fetchone()["s"]
    print(f"  완료: {name} ({size}). 이 DB를 쓰려면 .env의 DATABASE_URL에서 DB 이름을 {name}(으)로 바꾸세요")


STEPS = {"init": step_init, "seed": step_seed, "anilist": step_anilist, "tvmaze": step_tvmaze,
         "tmdb": step_tmdb, "jikan": step_jikan, "characters": step_characters, "fandom-find": step_fandom_find, "fandom": step_fandom, "wiki": step_wiki,
         "chunks": step_chunks, "embed": step_embed, "report": step_report, "status": step_status,
         "search": step_search, "migrate": step_migrate}


def main():
    global REFRESH, REPARSE
    ap = argparse.ArgumentParser(description="AniWhere 데이터 수집기 (PostgreSQL + pgvector)")
    ap.add_argument("steps", nargs="+", metavar="단계", help=" ".join(STEPS))
    ap.add_argument("--limit", type=int, help="인기순 상위 N개 시리즈만")
    ap.add_argument("--series", help="특정 시리즈만 (예: tmdb:65930)")
    ap.add_argument("--pages", type=int, help="anilist: 앞에서부터 N묶음(×50개)만")
    ap.add_argument("--types", nargs="+", default=["TV", "ONA"], help="seed: 포함할 형식 (기본 TV ONA)")
    ap.add_argument("--refresh", action="store_true", help="이미 받은 것도 다시 받기")
    ap.add_argument("--reparse", action="store_true", help="새로 받지 않고, 이미 받은 원본으로 다시 정리")
    ap.add_argument("--watched", type=int, help="search: 본 회차 (전체 회차 번호, 필수)")
    ap.add_argument("-k", type=int, default=5, help="search: 결과 개수")
    ap.add_argument("--to", help="migrate: 서비스용 DB 이름 (기본 config의 service_db.name)")
    ap.add_argument("--min-fill", type=float, help="migrate: 상세 줄거리 채움률 기준 0~1 (기본 config의 service_db.min_plot_fill)")
    args = ap.parse_args()
    args.query = None
    if args.steps[0] == "search":
        args.steps, args.query = ["search"], " ".join(args.steps[1:])
    unknown = [s for s in args.steps if s not in STEPS]
    if unknown:
        ap.error(f"모르는 단계: {unknown} (가능: {' '.join(STEPS)})")
    REFRESH, REPARSE = args.refresh, args.reparse
    if "init" in args.steps:
        ensure_database()
    with connect() as db:
        for step in args.steps:
            print(f"[{step}]", flush=True)
            STEPS[step](db, args)


if __name__ == "__main__":
    main()
