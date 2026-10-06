# data/

수집기 하나(`collect.py`)로 애니메이션 약 1만 2천 개 시리즈의 목록을 만들고, 인기순으로 회차·캐릭터·OTT 정보를 받아
검색 청크와 임베딩까지 **PostgreSQL + pgvector 한 곳**에 저장합니다.

| 파일·폴더 | 내용 | 커밋 |
|---|---|---|
| `collect.py` | 수집기. 단계별 명령(아래 표) | ✅ |
| `schema.sql` | 테이블 정의 | ✅ |
| `fandom_wikis.json` | 상세 줄거리를 받을 작품과 위키 주소 (사람이 고르거나 `fandom-find`가 자동으로 추가) | ✅ |
| `raw/` | 내려받은 작품 목록 원본(약 70MB). **수정 금지** | ❌ |
| `curated/` | 사람이 쓰거나 검수한 데이터(주요 사건, 사용자식 표현) | ✅ |
| `processed/` | 수집 리포트 `report.md` | ❌ |
| `index/` | (지금은 쓰지 않음. 청크와 벡터는 DB에 있음) | ❌ |

## 1. 준비

1. PostgreSQL 14 이상과 [pgvector](https://github.com/pgvector/pgvector) 0.8 이상. 확인:
   `psql -d postgres -c "SELECT default_version FROM pg_available_extensions WHERE name='vector';"`
   결과가 비어 있으면 pgvector를 설치합니다(Postgres.app은 포함, Homebrew는 `brew install pgvector`).
2. 저장소 루트에 `.env`를 만들고 값을 채웁니다: `cp .env.example .env`
   - `DATABASE_URL=postgresql://사용자:비밀번호@localhost:5432/aniwhere`
   - `TMDB_API_KEY=` (한국어 회차명·줄거리, 국내 OTT에 필요)
3. `make setup` 후 `python data/collect.py init` — 데이터베이스가 없으면 만들고 테이블을 생성합니다.

## 2. 수집 순서

| 순서 | 명령 | 출처 | 하는 일 | 예상 시간 |
|---|---|---|---|---|
| 0 | `init` | - | DB·테이블 생성 | 즉시 |
| 1 | `seed` | anime-offline-database, Fribb/anime-lists | 시리즈·시즌 목록 자동 생성, 출처 간 ID 연결 | 1분 미만 |
| 2 | `anilist` | AniList | 인기도, 작품 설명, 장르, 포스터, 방영 상태·다음 회차 일정, 비슷한 작품 | 처음 7분 안팎 |
| 3 | `tvmaze --limit N` | TVmaze | 회차 목록, 방영일, 영어 요약 | 시리즈당 약 1초 |
| 4 | `tmdb --limit N` | TMDB (JustWatch) | 한국어 제목·작품 소개·회차명·줄거리, 포스터·회차 이미지 주소, 상영 시간, 시즌별 국내 OTT | 시리즈당 1초 미만 |
| 5 | `jikan --limit N` | MyAnimeList (Jikan) | 필러·총집편 여부 | 시즌 항목당 1초 이상 |
| 6 | `characters --limit N` | AniList | 주요 캐릭터 이름·설명·이미지 주소 | 시즌 항목당 약 2초 |
| 7-0 | `fandom-find --limit N` | Fandom | 인기작의 위키를 제목으로 추측해 찾고 `fandom_wikis.json`에 추가 | 작품당 2~8초 |
| 7 | `fandom` | Fandom 작품별 위키 | 회차별 상세 줄거리, 등장 순서, 원작 화수, 아크 | 위키당 수 초 (50문서씩 한 번에 받음) |
| 8 | `chunks` | 위 결과 | 검색 청크 생성·갱신 | 몇 분 |
| 9 | `embed --limit N` | 로컬 임베딩 모델 | 청크 임베딩, 벡터 인덱스 생성 | 청크 수에 비례 |
| | `report` | - | 작품별 수집 리포트(`processed/report.md`) | 즉시 |
| | `status --limit N` | - | 출처별 진행률(상위 N개 기준)과 쌓인 데이터 양. 수집 중에도 다른 터미널에서 확인 가능 | 즉시 |

```bash
make data            # init seed anilist → tvmaze tmdb jikan characters (상위 300개) → fandom
make index           # chunks report → embed
make data LIMIT=1000 # 범위를 늘려 다시 실행 (이미 받은 작품은 건너뜀)
```

- **중간에 멈춰도 됩니다.** 다시 실행하면 끝난 시리즈는 건너뛰고 실패(`error`)한 것만 다시 시도합니다.
  어디까지 받았는지는 DB의 `fetch_log` 테이블이 기억합니다.
- 한 출처가 연속 8번 실패하면(서비스 장애·차단) 그 단계만 멈춥니다. 나중에 같은 명령을 다시 실행하세요.
- 특정 작품만: `--series tmdb:65930`. 처음부터 다시 받기: `--refresh`. 새로 받지 않고 받아 둔 원본으로 다시 정리: `--reparse`.
- 수집 중에는 10개마다 `[120/300, 남은 시간 약 6분]` 형태로 진행 상황이 찍힙니다.
- 받은 API 원본은 `raw` 테이블에 저장되므로 같은 요청을 두 번 보내지 않습니다.
- `fandom`은 회차 제목이 문서 이름인 위키(진격, 하이큐 등)에서 TVmaze 영어 제목으로 회차를 맞추므로 `tvmaze` 뒤에 실행합니다.

## 3. 테이블

| 테이블 | 한 행 | 주요 칸 |
|---|---|---|
| `series` | 사용자가 생각하는 "한 작품" (TMDB TV ID가 같은 시즌들을 묶음) | 제목, 한국어 제목·소개, 포스터, 인기도, 총 회차, 방영 상태, 다음 회차 일정 |
| `entries` | 시즌별 항목 (나히아 3기 = AniList 100166) | 방영 순서, `abs_offset`, 설명, 별칭, 장르, 포스터, 비슷한 작품(`recommendations`) |
| `episodes` | 회차 | `abs_ep`, 시즌·화, 한/영 제목, 방영일, 상영 시간, 회차 이미지, 한국어 줄거리, 영어 요약, 필러, 상세 줄거리, 등장인물, 원작 화수, 아크 |
| `characters` | 캐릭터 | 이름, 역할, 설명, 이미지, 첫 등장 시즌, 첫 등장 회차(`first_abs_ep`) |
| `streaming` | 시즌별 OTT | 구독형 제공처, 확인일 (국내 대여·구매 정보는 TMDB에 없음) |
| `chunks` | 검색 청크 | `type`, `abs_ep`, 텍스트, 출처 URL·라이선스, `embedding` |
| `fetch_log` | 시리즈 × 출처의 수집 상태 | ok / empty / error, 결과 요약 |
| `raw` | API 원본 캐시 | |

### 전체 회차 번호 `abs_ep`

모든 출처를 시리즈 안에서 1화부터 이어지는 번호로 맞춥니다. 나히아 3기 11화 = 1기 13화 + 2기 25화 + 11 = **전체 49화**.
시즌 나눔은 출처마다 다릅니다(주술회전 3기는 TVDB에서 시즌 3, TMDB에서 시즌 1의 48화부터). 그래서 매핑 데이터의
출처별 시작 위치를 쓰고, 시즌 단위로 90% 이상 맞지 않으면 1화부터 순서대로 이어 붙입니다(원피스·나루토처럼 한 항목이 긴 작품).

### 청크 종류와 스포일러 차단

청크마다 `abs_ep`가 붙어 있어서 "본 회차 이하만 검색" 조건 하나로 스포일러를 막습니다.

| type | 단위 | `abs_ep` (이 회차까지 본 사용자에게만 보임) |
|---|---|---|
| summary | 시즌 항목별 설명·별칭·장르 | 1기는 NULL(항상), 2기 이후는 앞 시즌 마지막 회차 |
| character | 캐릭터 설명 | Fandom 등장 순서에서 첫 등장 회차를 찾았으면 그 회차(1화 등장은 NULL). 못 찾았으면 첫 등장 시즌 기준(1기는 NULL, 아니면 앞 시즌 마지막 회차) |
| episode | 회차 요약 (한국어 + 영어) | 그 회차 |
| event | Fandom 상세 줄거리를 약 700자씩 나눈 장면 | 그 회차 |
| streaming | 시즌별 국내 OTT | NULL(항상) |

검색은 `collect.search_chunks(db, 질문_벡터, watched={시리즈 ID: 본 회차}, …)`를 씁니다. `watched`는 필수 인자이고,
본 회차 이후 청크는 정렬 전에 `WHERE`에서 제외됩니다. `watched`에 없는 시리즈는 회차와 무관한 청크만 검색됩니다.

```bash
python data/collect.py search "올마이트가 올포원과 싸우고 손가락을 가리켰어" --series tmdb:65930 --watched 49
```

AniList 설명의 스포일러 표시 구간(`~! … !~`)은 저장할 때 지웁니다. 다만 표시가 없는 스포일러까지 걸러내지는 못합니다.
캐릭터의 첫 등장 회차는 AniList 이름과 Fandom 등장인물 이름이 같을 때만(성·이름 순서, 장음 표기는 무시) 알 수 있고,
나머지는 "첫 등장 시즌" 단위로 가립니다.

> 주의: 첫 등장 회차가 2화 이후인 캐릭터는 그 작품의 시청 기록이 없는 사용자에게 검색되지 않습니다.
> "기억나는 캐릭터로 작품 찾기"에서 이 캐릭터들도 찾게 하려면, 검색 쪽에서 작품 확정 전 단계의 규칙을 따로 정해야 합니다.

### 임베딩

모델과 차원은 `config/settings.yaml`의 `embedding`에서 정합니다. `schema.sql`의 `vector(768)`과 `dim`이 같아야 합니다.
청크 텍스트가 바뀌면 그 청크의 임베딩만 비워지므로 `embed`를 다시 실행하면 바뀐 것만 계산합니다.

## 4. 상세 줄거리(Fandom) 작품 추가

`python data/collect.py fandom-find --limit 300`은 인기 상위 작품의 위키 주소를 제목으로 추측해(`attack-on-titan`, `attackontitan` …)
회차 문서 수가 작품 회차 수와 비슷하면 `fandom_wikis.json`에 `"auto": true`로 추가합니다. 자동으로 찾은 위키는 수집할 때
회차 제목이 TVmaze와 거의 안 맞으면(다른 작품의 위키) 저장하지 않습니다. 별명으로 된 위키(`fma`, `konosuba` 등)는 못 찾으므로 직접 적습니다.

`fandom_wikis.json`에 시리즈 ID와 위키 주소를 적습니다. 회차 문서가 모인 분류 이름이 `Episodes`가 아니면 `category`를,
한 위키에 여러 작품이 섞여 있으면 `include`·`exclude`(문서 제목 정규식)나 `infobox`(인포박스 값 조건)를 추가합니다.
받은 뒤 `report`의 "상세 줄거리(Fandom)를 받은 시리즈" 표에서 채움률과 회차 번호를 못 찾은 문서 수를 확인하세요.

**운영 기준:** 채움률이 90% 이상인 작품만 회차 기능을 켜고 `config/settings.yaml`의 `works`에 올립니다.

## 5. 출처와 라이선스

| 출처 | 가져오는 것 | 라이선스·조건 |
|---|---|---|
| [anime-offline-database](https://github.com/manami-project/anime-offline-database) | 작품 목록, 별칭, 태그, 회차 수 | ODbL 1.0 + DbCL 1.0 — 출처 표기, 가공 DB 공개 시 동일 조건 |
| [Fribb/anime-lists](https://github.com/Fribb/anime-lists) | AniList·MAL·TMDB·TVDB ID와 시즌 연결 | 저장소에 라이선스 파일 없음(2026-10-05 확인) — ID 매핑으로만 쓰고 재배포하지 않음 |
| AniList API | 인기도, 설명, 장르, 캐릭터, 포스터 | [API 약관](https://docs.anilist.co/guide/terms-of-use) — 비상업, 분당 요청 제한, 대량 재배포 금지 |
| TVmaze API | 회차 목록, 방영일, 영어 요약 | CC BY-SA 4.0 — TVmaze 출처 링크, 동일 조건 |
| TMDB API | 한국어 제목·회차명·줄거리 | 비상업 무료 — TMDB 로고와 "This product uses the TMDB API but is not endorsed or certified by TMDB" 고지 |
| JustWatch (TMDB 경유) | 국내 OTT 제공처 | JustWatch 출처 표기 필수 |
| Jikan (MyAnimeList) | 필러·총집편 표시 | 비공식 API — MyAnimeList 이용약관, 초당 3회 |
| Fandom 작품별 위키 | 회차 상세 줄거리, 등장 순서, 원작 화수, 아크 | 텍스트 CC BY-SA — 출처 링크·라이선스 표기, 동일 조건. 위키별 표기는 `fetch_log.detail`에 기록 |

- 청크의 `sources` 칸에 출처 이름·URL·라이선스가 들어 있어 답변의 근거 링크로 그대로 보여줄 수 있습니다.
- Fandom·TVmaze는 동일조건(SA)이라 가공한 청크를 공개하면 같은 라이선스로 풀어야 합니다. DB 덤프는 커밋하지 않습니다.
- 장면 이미지·자막·대사는 저작권 문제로 수집하지 않습니다.
- 작품별 비교와 결정은 `docs/data-sources.md`에 있습니다.

## 6. 테스트

`make test` — 위키 파서와 회차 번호 연결은 DB 없이, 전체 흐름과 스포일러 차단은 `DATABASE_URL`의 DB 이름 뒤에 `_test`를
붙인 별도 DB에서 가짜 API 응답으로 확인합니다(실제 수집 DB는 건드리지 않음. DB에 접속할 수 없으면 건너뜀).
필수 테스트 "N화까지 봤으면 N+1화 이후 청크는 검색 결과에 절대 나오지 않는다"는 `tests/test_collect.py`에 있습니다.
