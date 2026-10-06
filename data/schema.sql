-- AniWhere 수집·검색 DB (PostgreSQL 14+ / pgvector 0.8+)
-- 실행: python data/collect.py init   (여러 번 실행해도 안전)

CREATE EXTENSION IF NOT EXISTS vector;

-- 시리즈: 사용자가 "한 작품"으로 생각하는 단위. TMDB TV ID가 같은 시즌들을 하나로 묶음
CREATE TABLE IF NOT EXISTS series (
    series_id      text PRIMARY KEY,            -- 'tmdb:65930' 또는 'entry:anilist:12345'
    title          text NOT NULL,               -- 대표 로마자 제목 (첫 시즌)
    title_ko       text,                        -- TMDB 한국어 제목
    overview_ko    text,                        -- TMDB 한국어 작품 소개
    poster_url     text,                        -- TMDB 포스터 주소 (파일은 저장하지 않음)
    status         text,                        -- 가장 최근 시즌의 방영 상태 (AniList: FINISHED / RELEASING …)
    next_episode_at timestamptz,                -- 다음 회차 방영 예정 시각 (방영 중일 때만)
    tmdb_id        integer,
    tvdb_id        integer,
    tvmaze_id      integer,
    popularity     integer,                     -- 시즌 중 최댓값 (AniList)
    total_episodes integer
);
CREATE INDEX IF NOT EXISTS series_popularity_idx ON series (popularity DESC NULLS LAST);

-- 시즌별 항목: AniList/MAL의 작품 1개 = 1행 (나히아 3기 = AniList 100166)
CREATE TABLE IF NOT EXISTS entries (
    entry_key      text PRIMARY KEY,            -- 'anilist:100166' (없으면 'mal:..')
    series_id      text NOT NULL REFERENCES series ON DELETE CASCADE,
    order_in_series integer NOT NULL,           -- 시리즈 안에서 방영 순서 (1부터)
    abs_offset     integer NOT NULL,            -- 이 항목 1화의 전체 회차 번호 = abs_offset + 1
    anilist_id     integer UNIQUE,
    mal_id         integer,
    type           text,                        -- TV / ONA
    status         text,
    title          text NOT NULL,
    title_en       text,
    title_native   text,
    synonyms       text[] DEFAULT '{}',
    tags           text[] DEFAULT '{}',
    genres         text[] DEFAULT '{}',
    year           integer,
    season_of_year text,
    episodes       integer,
    tmdb_season    integer,                     -- 이 항목이 들어 있는 TMDB 시즌
    tmdb_offset    integer,                     -- 그 시즌 안에서 몇 화 뒤부터 시작하는지 (없으면 방영 순서대로 이어 붙임)
    tvdb_season    integer,
    tvdb_offset    integer,
    popularity     integer,
    average_score  integer,
    cover_url      text,
    description    text,
    airing_status  text,                        -- AniList 방영 상태
    next_episode_at timestamptz,
    recommendations integer[] DEFAULT '{}'      -- 비슷한 작품 (AniList ID, 추천 많은 순)
);
CREATE INDEX IF NOT EXISTS entries_series_idx ON entries (series_id, order_in_series);

-- 회차: 시리즈 안에서 전체 회차 번호(abs_ep)로 통일
CREATE TABLE IF NOT EXISTS episodes (
    series_id    text REFERENCES series ON DELETE CASCADE,
    abs_ep       integer,
    entry_key    text REFERENCES entries ON DELETE CASCADE,
    entry_ep     integer,                       -- 그 시즌 항목 안에서 몇 화
    tmdb_season  integer,
    tmdb_number  integer,
    still_url    text,                          -- TMDB 회차 장면 이미지 주소
    runtime      integer,                       -- 분
    title_ko     text,
    title_en     text,
    airdate      date,
    overview_ko  text,                          -- TMDB
    summary_en   text,                          -- TVmaze
    tvmaze_url   text,
    filler       boolean,                       -- Jikan
    recap        boolean,
    fandom_url   text,
    fandom_title text,
    arc          text,                          -- Fandom 인포박스의 아크(이야기 묶음) 이름
    chapters     text,                          -- 원작 대응 화수
    characters   text[],                        -- 등장 순서
    synopsis_en  text,                          -- Fandom 짧은 요약
    plot         text,                          -- Fandom 상세 줄거리
    PRIMARY KEY (series_id, abs_ep)
);

CREATE TABLE IF NOT EXISTS characters (
    series_id    text REFERENCES series ON DELETE CASCADE,
    anilist_char integer,
    name         text,
    name_native  text,
    role         text,                          -- MAIN / SUPPORTING
    gender       text,
    image_url    text,
    description  text,                          -- 외형·성격·능력 서술 (AniList, 스포일러 표시 구간은 제거)
    first_entry  text,                          -- 처음 등장한 시즌 항목
    first_abs_ep integer,                       -- 처음 등장한 회차 (Fandom 등장 순서와 이름이 맞을 때만)
    PRIMARY KEY (series_id, anilist_char)
);

CREATE TABLE IF NOT EXISTS streaming (
    series_id    text REFERENCES series ON DELETE CASCADE,
    tmdb_season  integer,
    season_name  text,
    flatrate     text[] DEFAULT '{}',           -- 구독형 제공처 (국내 대여·구매 정보는 TMDB에 없음)
    link         text,
    checked_at   date,
    PRIMARY KEY (series_id, tmdb_season)
);

-- 검색 청크. embedding은 embed 단계에서 채움 (차원은 config/settings.yaml의 embedding.dim과 같아야 함)
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     text PRIMARY KEY,
    series_id    text REFERENCES series ON DELETE CASCADE,
    type         text NOT NULL,                 -- summary / character / episode / event / streaming
    abs_ep       integer,                       -- NULL = 회차와 무관 (항상 검색 대상)
    tmdb_season  integer,
    filler       boolean,
    text         text NOT NULL,
    sources      jsonb NOT NULL DEFAULT '[]',
    embedding    vector(768)
);
CREATE INDEX IF NOT EXISTS chunks_filter_idx ON chunks (series_id, abs_ep);
-- 벡터 인덱스(chunks_embedding_idx)는 embed 단계가 임베딩을 채운 뒤 만듭니다.

-- 수집 상태: 시리즈 × 출처. 중단 후 이어받기, 실패한 것만 재시도
CREATE TABLE IF NOT EXISTS fetch_log (
    series_id    text REFERENCES series ON DELETE CASCADE,
    source       text,
    status       text NOT NULL,                 -- ok / empty / error
    detail       text,
    fetched_at   timestamptz DEFAULT now(),
    PRIMARY KEY (series_id, source)
);

-- API 원본 캐시 (jsonb는 자동 압축됨)
CREATE TABLE IF NOT EXISTS raw (
    source       text,
    key          text,
    data         jsonb,
    fetched_at   timestamptz DEFAULT now(),
    PRIMARY KEY (source, key)
);

-- 이전 구조로 만든 DB를 위 정의에 맞춤 (여러 번 실행해도 안전)
ALTER TABLE series     DROP COLUMN IF EXISTS updated_at,
                       ADD COLUMN IF NOT EXISTS overview_ko text, ADD COLUMN IF NOT EXISTS poster_url text,
                       ADD COLUMN IF NOT EXISTS status text, ADD COLUMN IF NOT EXISTS next_episode_at timestamptz;
ALTER TABLE entries    DROP COLUMN IF EXISTS anidb_id,
                       ADD COLUMN IF NOT EXISTS airing_status text, ADD COLUMN IF NOT EXISTS next_episode_at timestamptz,
                       ADD COLUMN IF NOT EXISTS recommendations integer[] DEFAULT '{}';
ALTER TABLE episodes   ADD COLUMN IF NOT EXISTS still_url text, ADD COLUMN IF NOT EXISTS runtime integer;
ALTER TABLE characters DROP COLUMN IF EXISTS age,
                       ADD COLUMN IF NOT EXISTS image_url text, ADD COLUMN IF NOT EXISTS first_abs_ep integer;
ALTER TABLE streaming  DROP COLUMN IF EXISTS rent, DROP COLUMN IF EXISTS buy;
ALTER TABLE chunks     DROP COLUMN IF EXISTS tmdb_number, DROP COLUMN IF EXISTS collected_at;

-- TMDB에서 받는 작품 단위 정보 확장
ALTER TABLE series
    ADD COLUMN IF NOT EXISTS title_original text, ADD COLUMN IF NOT EXISTS tagline_ko text,
    ADD COLUMN IF NOT EXISTS genres_ko text[] DEFAULT '{}', ADD COLUMN IF NOT EXISTS keywords text[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS alt_titles text[] DEFAULT '{}',      -- 한국·일본·미국에서 쓰는 다른 제목
    ADD COLUMN IF NOT EXISTS first_air_date date, ADD COLUMN IF NOT EXISTS last_air_date date,
    ADD COLUMN IF NOT EXISTS vote_average real, ADD COLUMN IF NOT EXISTS vote_count integer,
    ADD COLUMN IF NOT EXISTS content_rating_kr text,              -- 국내 시청 등급
    ADD COLUMN IF NOT EXISTS backdrop_url text, ADD COLUMN IF NOT EXISTS trailer_url text,
    ADD COLUMN IF NOT EXISTS networks text[] DEFAULT '{}', ADD COLUMN IF NOT EXISTS studios text[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS origin_country text[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS homepage text, ADD COLUMN IF NOT EXISTS imdb_id text;
ALTER TABLE episodes
    ADD COLUMN IF NOT EXISTS overview_en text,                    -- TMDB 영어 줄거리 (TVmaze 요약이 없을 때 대신 씀)
    ADD COLUMN IF NOT EXISTS rating real;                         -- TMDB 회차 평점

-- TMDB 시즌 (한국어 시즌명·소개·포스터)
CREATE TABLE IF NOT EXISTS seasons (
    series_id     text REFERENCES series ON DELETE CASCADE,
    tmdb_season   integer,
    name_ko       text,
    overview_ko   text,
    air_date      date,
    poster_url    text,
    episode_count integer,
    PRIMARY KEY (series_id, tmdb_season)
);

-- 성우 (TMDB 출연진, 출연 회차가 많은 순 상위)
CREATE TABLE IF NOT EXISTS voice_cast (
    series_id     text REFERENCES series ON DELETE CASCADE,
    tmdb_person   integer,
    name          text,
    character     text,
    episode_count integer,
    profile_url   text,
    PRIMARY KEY (series_id, tmdb_person)
);

-- Fandom 위키의 모든 문서 (회차 문서 포함). 한 위키를 여러 시리즈가 같이 쓸 수 있어 위키 기준으로 저장
CREATE TABLE IF NOT EXISTS wiki_pages (
    wiki         text,
    title        text,
    kind         text,                          -- character / episode / chapter / location / group / ability / item / music / person / arc / other
    infobox_name text,
    infobox      jsonb,
    sections     jsonb,                         -- {구역 제목: 본문}
    links        text[],                        -- 본문에서 가리키는 다른 문서
    wikitext     text,                          -- 원문 (다시 정리할 때 씀)
    fetched_at   timestamptz DEFAULT now(),
    PRIMARY KEY (wiki, title)
);
CREATE INDEX IF NOT EXISTS wiki_pages_kind_idx ON wiki_pages (wiki, kind);
