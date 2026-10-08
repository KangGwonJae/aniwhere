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
| 7-0 | `fandom-find --limit N` | 위키데이터, Fandom 위키 목록 | 인기작의 위키를 찾아 `fandom_wikis.json`에 추가 (ID → 위키 목록의 제목 → 주소 추측 순) | 작품당 2~8초 |
| 7 | `fandom` | Fandom 작품별 위키 | 회차별 상세 줄거리, 등장 순서, 원작 화수, 아크 | 위키당 수 초 (50문서씩 한 번에 받음) |
| 8 | `chunks` | 위 결과 | 검색 청크 생성·갱신 | 몇 분 |
| 9 | `embed --limit N` | 로컬 임베딩 모델 | 청크 임베딩, 벡터 인덱스 생성 | 청크 수에 비례 |
| | `report` | - | 작품별 수집 리포트(`processed/report.md`) | 즉시 |
| | `status --limit N` | - | 출처별 진행률(상위 N개 기준)과 쌓인 데이터 양. 수집 중에도 다른 터미널에서 확인 가능 | 즉시 |
| | `migrate` | 수집 DB | 상세 줄거리가 제대로 있는 작품만 서비스용 DB로 옮김 (아래 "서비스용 DB") | 약 20초 |

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
- `fandom`은 위키 문서가 몇 화인지를 TVmaze의 영어 회차 제목과 방영일로 맞추므로 `tvmaze` 뒤에 실행합니다.

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
| plot | Fandom 상세 줄거리 한 화 통째 | 그 회차 |
| event | 같은 줄거리를 약 700자씩 나눈 장면 | 그 회차 |
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

### 서비스용 DB

수집 DB(`aniwhere`)는 1만 2천 개 시리즈를 다 담고 있어 대부분의 회차에 상세 줄거리가 없습니다. 서비스(검색·복습)에는
**500자 이상 상세 줄거리가 있는 회차가 전체의 80% 이상인 작품**만 따로 옮긴 DB를 씁니다.

```bash
python data/collect.py migrate                              # → aniwhere_service
python data/collect.py migrate --min-fill 0.9 --to 다른이름   # 기준·DB 이름 바꾸기
```

- 기준과 DB 이름의 기본값은 `config/settings.yaml`의 `service_db`에 있습니다.
- 수집 DB는 읽기만 합니다. 서비스용 DB는 실행할 때마다 비우고 다시 채우므로, 수집·정제를 고친 뒤 다시 실행하면 됩니다.
  (서비스용 DB에서 직접 고친 내용과 임베딩은 사라집니다. 임베딩은 수집 DB에서 `embed`를 하고 옮기면 같이 넘어갑니다.)
- 옮기는 것: `series` `entries` `episodes` `characters` `streaming` `seasons` `voice_cast` `chunks` `fetch_log`,
  그리고 그 작품들의 `wiki_pages`(원문 `wikitext` 칸 제외). `raw`(API 원본 캐시)는 옮기지 않습니다.
- 서비스용 DB를 쓰려면 `.env`의 `DATABASE_URL`에서 DB 이름만 `aniwhere_service`로 바꿉니다.

### 임베딩

모델과 차원은 `config/settings.yaml`의 `embedding`에서 정합니다(지금은 `BAAI/bge-m3`, 1024차원. 처음 실행할 때
모델 약 2.3GB를 내려받습니다). `schema.sql`의 `vector(1024)`와 `dim`이 같아야 합니다. 이미 만든 DB의 차원을 바꾸려면
`ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1024);`를 실행합니다(임베딩이 비어 있어야 함).
청크 텍스트가 바뀌면 그 청크의 임베딩만 비워지므로 `embed`를 다시 실행하면 바뀐 것만 계산합니다.

```bash
python data/collect.py embed                                        # 모든 종류를 임베딩 (이미 한 것은 건너뜀)
python data/collect.py embed --chunk-types event                    # 한 종류만
python data/collect.py search "질문" --series tmdb:65930 --watched 49 --chunk-types event
```

**어떤 종류로 검색하나 — 작게 찾고 크게 읽기.** 모든 종류를 임베딩해 두고, 앱이 어느 종류로 검색할지는
`config/settings.yaml`의 `retrieval.chunk_types`로 고릅니다(지금은 `event`). 장면(`event`, 약 700자)으로 찾아
회차로 묶은 뒤, LLM에게는 그 회차의 상세 줄거리(`plot`) 전체를 보여 줍니다. 회차 통째(`plot`)를 벡터 하나로 만들어
찾으면 한 장면의 뜻이 묻힙니다. 데모 3작품 질문 75개로 잰 결과(`eval/results/2026-10-08_chunking-ab.json`):

| 검색 대상 | 작품 안에서 정답 회차 1위 | 8위 안 |
|---|---|---|
| 회차 통째(`plot`) | 20% | 53% |
| 장면(`event`) | 63% | 85% |

캐릭터·용어·작품 소개(`character`·`terminology`·`summary`)는 "키 작은 아저씨가 칼 들고 날아다녀"처럼 장면이 아니라
생김새로 작품을 찾을 때 검색합니다.

`embed`는 끝날 때 `ANALYZE chunks`로 통계를 갱신합니다. 이것이 빠지면 PostgreSQL이 임베딩이 비어 있다고 보고
벡터 인덱스를 쓰지 않습니다. 임베딩은 오래 걸리므로 노트북에서는 절전을 막고 돌리세요: `caffeinate -i -s python data/collect.py embed`

상세 줄거리는 청크로 만들기 전에 줄거리가 아닌 줄을 지웁니다(`clean_plot`): 위키 탭 표시(`|-|Netflix=`), 일본어·로마자
원문, 이름·소제목만 있는 50자 미만 줄.

## 4. 상세 줄거리(Fandom) 작품 추가

`python data/collect.py fandom-find --limit 300`은 인기 상위 작품의 위키를 세 가지 방법으로 찾아 `fandom_wikis.json`에
`"auto": true`로 추가합니다: ① 위키데이터(AniList·MAL ID로) ② Fandom 애니 위키 목록(제목·별칭으로) ③ 제목으로 주소 추측
(`attack-on-titan`, `attackontitan` …). ①②로 찾은 위키는 여러 작품이 같이 쓰는 위키여도 받고, ③은 회차 문서 수가 작품
회차 수와 비슷할 때만 받습니다. 자동으로 찾은 위키는 수집할 때 회차 제목도 방영일도 TVmaze와 거의 안 맞으면(다른 작품의 위키)
저장하지 않습니다.

### 위키 문서가 몇 화인지 맞추는 방법

`fandom` 단계는 회차 분류(`Episodes`)의 문서를 받고, 문서가 적으면 시즌별 하위 분류까지 내려갑니다. 그다음 문서마다 번호를 붙입니다.

1. 문서 제목의 번호 (`Episode 49`, `Rebirth Episode 01`). 같은 번호가 여러 문서에 있으면 시즌마다 다시 세는 위키이므로 쓰지 않습니다.
2. TVmaze 영어 회차 제목과 같은 문서.
3. 인포박스의 방영일이 TVmaze 방영일과 같은 회차(하루 차이까지). 번역이 달라 제목이 안 맞아도 찾을 수 있습니다.
   방영일로 찾은 번호가 1·2와 자주 어긋나면 해외 방영일만 적힌 위키로 보고 쓰지 않습니다.
4. 인포박스의 이전·다음 회차 링크.
5. 인포박스의 회차 번호. 같은 시즌의 다른 문서들과 번호 차이가 일정하면 그만큼 더합니다(2기 3화 = 전체 28화).

4·5로 붙인 번호가 그 회차의 방영일과 2주 넘게 어긋나면 같은 위키의 다른 작품(외전, 속편)으로 보고 뺍니다.

한 위키를 여러 시리즈가 같이 쓰면(본편과 외전, 원작과 리메이크) 같은 문서를 둘 이상이 가져갈 수 있습니다. 문서 하나는
한 작품의 한 회차이므로, 모든 시리즈를 정리한 뒤 겹친 문서는 근거가 가장 강한 시리즈에만 남기고 나머지에서는 지웁니다.
근거 순서: 방영일이 맞음 → 회차 제목이 맞음 → 사람이 고른 위키 → 인기도. 뺀 회차 수는 `fetch_log.detail`에 남습니다.
`--series`로 한 작품만 다시 정리해도 같은 위키를 쓰는 시리즈는 함께 정리합니다.

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
