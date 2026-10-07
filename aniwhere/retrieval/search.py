"""청크 검색. 스포일러 차단이 여기 한 곳에 있습니다.

청크를 읽는 함수는 모두 "본 회차"를 필수 인자로 받고, 그 이후 청크를 정렬·검색 *전에* WHERE에서 제외합니다.
다른 모듈은 chunks 테이블을 직접 읽지 않고 이 파일의 함수만 씁니다.
"""
import re

from psycopg.types.json import Jsonb

from aniwhere.config import section

# 기록이 없는 작품을 끝까지 본 것으로 보는 값. "기억으로 찾기"에서만 씁니다 (search_chunks의 unrecorded 설명 참고)
ALL_EPISODES = 1_000_000

COLUMNS = "c.chunk_id, c.series_id, c.type, c.abs_ep, c.tmdb_season, c.text, c.sources"


def search_chunks(db, query_vector, *, watched: dict[str, int], unrecorded: int = 0, series_id=None, types=None,
                  k=None):
    """벡터 검색. watched = {시리즈 ID: 본 회차}는 필수 인자입니다.

    watched에 있는 작품은 본 회차까지만 검색합니다. watched에 없는 작품은 unrecorded화까지 본 것으로 봅니다.
    기본값 0은 회차와 무관한 청크만 검색한다는 뜻입니다. "기억으로 찾기"는 사용자가 이미 본 장면을 묻는 기능이라
    ALL_EPISODES를 넘기되, 답에는 작품명과 회차 번호·제목만 내보냅니다(줄거리 본문은 내보내지 않음).
    """
    if watched is None:
        raise TypeError("watched(시리즈별 본 회차)는 반드시 넘겨야 합니다")
    cfg = section("retrieval")
    k = k or cfg.get("top_k", 5)
    types = list(types or cfg.get("chunk_types") or []) or None
    vec = str([float(x) for x in query_vector])
    with db.transaction():
        db.execute("SET LOCAL hnsw.iterative_scan = strict_order")   # 필터 때문에 k개가 안 채워지는 일을 막음
        db.execute(f"SET LOCAL hnsw.ef_search = {max(40, min(int(k), 1000))}")
        return db.execute(
            f"""SELECT {COLUMNS}, 1 - (c.embedding <=> %(vec)s::vector) AS score
                FROM chunks c
                LEFT JOIN jsonb_each_text(%(watched)s) w ON w.key = c.series_id
                WHERE c.embedding IS NOT NULL
                  AND (c.abs_ep IS NULL OR c.abs_ep <= COALESCE(w.value::int, %(unrecorded)s))
                  AND (%(sid)s::text IS NULL OR c.series_id = %(sid)s)
                  AND (%(types)s::text[] IS NULL OR c.type = ANY(%(types)s))
                ORDER BY c.embedding <=> %(vec)s::vector
                LIMIT %(k)s""",
            {"vec": vec, "watched": Jsonb({s: int(n) for s, n in watched.items()}), "unrecorded": int(unrecorded),
             "sid": series_id, "types": types, "k": k}).fetchall()


def keyword_search(db, words, *, watched: dict[str, int], unrecorded: int = 0, series_ids, types, k=20):
    """영어 낱말로 찾기 (임베딩하지 않은 장면·캐릭터 청크도 찾을 수 있음). 드문 낱말이 맞을수록 점수가 높습니다.

    점수는 맞은 낱말들의 희귀도(IDF) 합입니다. 그 작품의 어느 장면에나 나오는 낱말(주인공 이름)은 거의 0점이고,
    몇 장면에만 나오는 낱말(boulder)이 순위를 정합니다.
    인덱스 없이 훑는 방식이라 series_ids로 작품을 좁혀서 씁니다. series_ids=None(전체 작품)은 양이 적은 종류
    (캐릭터·용어·작품 소개)에만 쓰세요. 스포일러 조건은 search_chunks와 같습니다.
    """
    if watched is None:
        raise TypeError("watched(시리즈별 본 회차)는 반드시 넘겨야 합니다")
    terms = list(dict.fromkeys(w.lower() for text in words for w in re.findall(r"[A-Za-z0-9]{2,}", text)))
    if not terms or series_ids == []:
        return []
    return db.execute(
        f"""WITH docs AS MATERIALIZED (
                SELECT {COLUMNS}, to_tsvector('english', c.text) AS tsv
                FROM chunks c
                LEFT JOIN jsonb_each_text(%(watched)s) w ON w.key = c.series_id
                WHERE (%(sids)s::text[] IS NULL OR c.series_id = ANY(%(sids)s)) AND c.type = ANY(%(types)s)
                  AND (c.abs_ep IS NULL OR c.abs_ep <= COALESCE(w.value::int, %(unrecorded)s))
            ), terms AS MATERIALIZED (       -- 어간이 같은 낱말(titan, titans)은 하나로, 불용어(the)는 뺌
                SELECT DISTINCT q FROM (SELECT plainto_tsquery('english', t) AS q FROM unnest(%(terms)s::text[]) t) x
                WHERE numnode(q) > 0
            ), idf AS (
                SELECT t.q, ln(1 + ((SELECT count(*) FROM docs) - count(*) + 0.5) / (count(*) + 0.5)) AS weight
                FROM terms t JOIN docs d ON d.tsv @@ t.q GROUP BY t.q
            ), scored AS (
                SELECT d.chunk_id, sum(i.weight) AS score FROM docs d JOIN idf i ON d.tsv @@ i.q GROUP BY d.chunk_id
            )
            SELECT d.chunk_id, d.series_id, d.type, d.abs_ep, d.tmdb_season, d.text, d.sources, s.score
            FROM scored s JOIN docs d USING (chunk_id)
            ORDER BY s.score DESC, d.chunk_id
            LIMIT %(k)s""",
        {"terms": terms, "watched": Jsonb({s: int(n) for s, n in watched.items()}), "unrecorded": int(unrecorded),
         "sids": None if series_ids is None else list(series_ids), "types": list(types), "k": k}).fetchall()


def chunks_upto(db, series_id, *, seen_ep: int, types, from_ep=1, include_episode_free=False, only_eps=None):
    """한 작품의 청크를 회차 순으로 읽음 (벡터 검색이 아니라 조건 검색). seen_ep는 필수 인자입니다.

    from_ep화부터 seen_ep화까지만 읽습니다. include_episode_free=True면 회차와 무관한 청크(abs_ep가 NULL)도 포함합니다.
    only_eps를 주면 그 범위 안에서 그 회차들만 읽습니다.
    """
    if seen_ep is None:
        raise TypeError("seen_ep(본 회차)는 반드시 넘겨야 합니다")
    return db.execute(
        f"""SELECT {COLUMNS} FROM chunks c
            WHERE c.series_id = %(sid)s AND c.type = ANY(%(types)s)
              AND ((c.abs_ep BETWEEN %(from_ep)s AND %(seen)s) OR (%(free)s AND c.abs_ep IS NULL))
              AND (%(only)s::int[] IS NULL OR c.abs_ep = ANY(%(only)s))
            ORDER BY c.abs_ep NULLS FIRST, c.chunk_id""",
        {"sid": series_id, "types": list(types), "from_ep": int(from_ep), "seen": int(seen_ep),
         "free": include_episode_free, "only": None if only_eps is None else list(only_eps)}).fetchall()

