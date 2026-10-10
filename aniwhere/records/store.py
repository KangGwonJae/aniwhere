"""시청 기록장: 본 작품·진행 회차·평점. 다른 기능은 여기서 "어디까지 봤는가"를 읽어 스포일러 범위를 정합니다.

기록은 서비스용 DB의 watch_records 테이블에 둡니다. series를 참조(REFERENCES)하지 않는 것은 일부러입니다:
`collect.py migrate`가 서비스용 DB의 작품 데이터를 비우고 다시 채워도 사용자 기록은 남아야 합니다.
"""
from aniwhere.retrieval.catalog import UnknownSeries

LOCAL_USER = "local"     # 로그인이 없는 동안 쓰는 사용자 이름

SCHEMA = """CREATE TABLE IF NOT EXISTS watch_records (
    user_id    text NOT NULL,
    series_id  text NOT NULL,
    seen_ep    integer NOT NULL CHECK (seen_ep >= 0),    -- 전체 회차 번호(abs_ep) 기준으로 몇 화까지 봤는지
    rating     real CHECK (rating BETWEEN 0.5 AND 5),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, series_id)
)"""

_ready: set[str] = set()


def _ensure(db):
    if db.info.dsn not in _ready:
        db.execute(SCHEMA)
        _ready.add(db.info.dsn)


def save(db, series_id, seen_ep, rating=None, *, user_id=LOCAL_USER) -> dict:
    """기록 저장(있으면 갱신). 평점을 안 넘기면 전에 준 평점을 그대로 둡니다."""
    _ensure(db)
    s = db.execute("SELECT total_episodes FROM series WHERE series_id = %s", (series_id,)).fetchone()
    if not s:
        raise UnknownSeries(f"모르는 작품입니다: {series_id}")
    total = s["total_episodes"]
    if not isinstance(seen_ep, int) or isinstance(seen_ep, bool) or seen_ep < 0 or (total and seen_ep > total):
        raise ValueError(f"본 회차는 0부터 {total}까지의 정수여야 합니다: {seen_ep!r}")
    if rating is not None and not 0.5 <= rating <= 5:
        raise ValueError(f"평점은 0.5부터 5까지입니다: {rating!r}")
    db.execute("""INSERT INTO watch_records (user_id, series_id, seen_ep, rating) VALUES (%s, %s, %s, %s)
                  ON CONFLICT (user_id, series_id) DO UPDATE
                  SET seen_ep = EXCLUDED.seen_ep, rating = coalesce(EXCLUDED.rating, watch_records.rating),
                      updated_at = now()""", (user_id, series_id, seen_ep, rating))
    return get(db, series_id, user_id=user_id)


def get(db, series_id, *, user_id=LOCAL_USER) -> dict | None:
    _ensure(db)
    return db.execute(
        """SELECT r.series_id, coalesce(s.title_ko, s.title) AS name, r.seen_ep, s.total_episodes, r.rating,
                  r.updated_at, s.poster_url
           FROM watch_records r LEFT JOIN series s USING (series_id)
           WHERE r.user_id = %s AND r.series_id = %s""", (user_id, series_id)).fetchone()


def list_all(db, *, user_id=LOCAL_USER) -> list[dict]:
    _ensure(db)
    return db.execute(
        """SELECT r.series_id, coalesce(s.title_ko, s.title) AS name, r.seen_ep, s.total_episodes, r.rating,
                  r.updated_at, s.poster_url
           FROM watch_records r LEFT JOIN series s USING (series_id)
           WHERE r.user_id = %s ORDER BY r.updated_at DESC""", (user_id,)).fetchall()


def delete(db, series_id, *, user_id=LOCAL_USER) -> bool:
    _ensure(db)
    return db.execute("DELETE FROM watch_records WHERE user_id = %s AND series_id = %s",
                      (user_id, series_id)).rowcount > 0


def watched_map(db, *, user_id=LOCAL_USER) -> dict[str, int]:
    """{시리즈 ID: 본 회차} — 검색 함수의 watched 인자로 그대로 넘깁니다."""
    _ensure(db)
    return {r["series_id"]: r["seen_ep"] for r in
            db.execute("SELECT series_id, seen_ep FROM watch_records WHERE user_id = %s", (user_id,))}
