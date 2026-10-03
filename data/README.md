# data/

데이터는 한 방향으로만 흐릅니다: `raw/` → `processed/` → `index/`. `curated/`는 사람이 넣습니다.

| 폴더 | 내용 | 만드는 주체 | 커밋 |
|---|---|---|---|
| `raw/` | 외부 API·위키 원본 그대로. **수정 금지** | `aniwhere/ingest` (`make data`) | ❌ |
| `curated/` | 사람이 쓰거나 검수한 데이터(주요 사건, 회차 보강, 사용자식 표현) | 사람 | ✅ |
| `processed/` | 청크(`chunks.jsonl`) + 메타데이터(작품·종류·시즌·회차) | `aniwhere/chunking` (`make index`) | ❌ |
| `index/` | 벡터 DB 파일 | `aniwhere/retrieval` (`make index`) | ❌ |

## 출처와 라이선스

| 출처 | 가져오는 것 | 라이선스·조건 |
|---|---|---|
| AniList API | 작품명, 줄거리, 장르, 캐릭터 | 확인 필요 |
| TMDB API | 한국어 제목, 시즌·회차, 포스터 | 출처 표기 필요 |
| JustWatch | 국내 OTT 제공 정보 | 확인 필요 |
| Kitsu API | 회차 줄거리 | 확인 필요 |
| 팬 위키 | 상세 회차 줄거리 | CC BY-SA — 출처 표기·동일 조건 |

> 상세 비교는 `docs/data-sources.md`(데이터 탐색 결과)를 기준으로 갱신합니다.
