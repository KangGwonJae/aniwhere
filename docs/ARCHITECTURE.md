# 폴더 구조 정의

이 문서는 각 폴더에 **무엇을 넣고, 무엇을 넣으면 안 되는지**의 기준입니다.
구조는 RAG 앱의 일반적인 구성(기능별 하위 모듈)과 데이터 분석 프로젝트의 표준
([cookiecutter-data-science](https://github.com/drivendataorg/cookiecutter-data-science): 원본 불변, 재생성 가능)을 합쳤습니다.

## 정체성이 구조를 정한다

AniWhere의 정체성은 **"애니를 볼 때 거칠 수밖에 없는 곳"**입니다. 기능 하나짜리 도구가 아니라
시청 여정 5단계(01 입문 → 02 탐색 → 03 시청 → 04 이어보기 → 05 깊이 빠지기) 전체에 들르는 곳이어야 합니다.
그래서 구조는 다음 세 가지를 지킵니다.

1. **시청 기록(`aniwhere/records/`)이 중심이다.** 모든 단계가 "이 사람이 무엇을, 어디까지 봤는가"를 공유합니다.
   기록이 있어야 다음에 다시 왔을 때 이어서 도울 수 있고, 스포일러 범위도 정할 수 있습니다.
2. **기능은 단계별로 늘어나고, 기반은 공유한다.** 단계마다 기능이 추가되어도 데이터(`data/`)·검색(`retrieval/`)·
   기록(`records/`)은 하나를 함께 씁니다. 새 단계 기능을 위해 별도의 데이터·DB를 만들지 않습니다.
3. **스포일러 차단은 기반에 있다.** 개별 기능이 각자 거르지 않고, `retrieval/`이 검색 전에 일괄 적용합니다.
   그래서 어떤 단계의 기능을 추가해도 원칙이 자동으로 지켜집니다.

### 단계 ↔ 기능 ↔ 코드 위치

| 단계 | 기능 (우선순위) | 주로 쓰는 모듈 |
|---|---|---|
| 01 입문 | 취향 인터뷰 추천 (여유 되면) | `agent/` + `retrieval/`(작품 요약 유사도) |
| 02 탐색 | 기억으로 작품 찾기 · 회차 찾기 (필수) | `agent/`(단서 추출·추가 질문) + `retrieval/`(캐릭터·사건 청크) |
| 03 시청 | 시청처 안내 (필수) · 회차 기준 인물·용어 사전 (여유 되면) | `ingest/`(OTT 정보) · `retrieval/`(회차 필터) |
| 04 이어보기 | 맞춤 복습 (이번에 추가) · 스포일러 차단 (필수) | `agent/`(도구 선택) + `records/`(본 회차) + `retrieval/` |
| 05 깊이 빠지기 | 시청 기록장 (이번에 추가) | `records/` |

전체 14개 기능과 우선순위는 `docs/identity/`의 기능 지도가 기준입니다. 위 표에 없는 기능을 만들 때는
먼저 기능 지도에서 단계와 우선순위를 확인하고, 이 표에 행을 추가합니다.

## 전체 구조

```
aniwhere/
├── README.md · AGENTS.md · CLAUDE.md · Makefile · requirements.txt · .env.example · .gitignore
├── .github/            PR 템플릿
├── config/             바뀔 수 있는 값
├── data/
│   ├── raw/            외부 원본 (커밋 X)
│   ├── curated/        사람이 검수한 데이터 (커밋 O)
│   ├── processed/      청크 (커밋 X)
│   └── index/          벡터 DB (커밋 X)
├── notebooks/          탐색·실험
├── aniwhere/           앱 본체 (파이썬 패키지)
│   ├── ingest/
│   ├── chunking/
│   ├── retrieval/
│   ├── agent/
│   ├── records/
│   └── api/ 또는 app/  ← 데모 형태 확인 후 결정
├── frontend/           ← 화면과 서버가 분리된 경우에만
├── eval/               검색 품질 평가
├── tests/              고장 여부 테스트
├── reports/figures/    발표용 그림
└── docs/               사람이 읽는 문서
```

## 최상위 파일

| 파일 | 역할 |
|---|---|
| `README.md` | 프로젝트 소개, clone부터 실행까지의 명령, 팀. 처음 온 사람이 이것만 보고 데모를 돌릴 수 있어야 함 |
| `AGENTS.md` | 사람·AI 공통 작업 규칙의 **원본**. Cursor·Codex·Copilot 등이 읽음 |
| `CLAUDE.md` | `@AGENTS.md` 한 줄로 원본을 불러옴. Claude Code 전용 메모만 추가 |
| `Makefile` | `setup → data → index → run`, `test`, `eval` 명령 모음 |
| `requirements.txt` | 파이썬 패키지와 버전 |
| `.env.example` | 필요한 키 이름 목록(값은 비움). 실제 `.env`는 커밋 금지 |
| `.gitignore` | `.env`, 재생성 가능한 데이터, 가상환경 등 제외 |

## `config/`

바뀔 수 있는 값을 모으는 곳. `settings.yaml` 하나로 시작합니다.

- 넣는 것: 지원 작품 목록, 임베딩 모델 이름, 청킹 방식·크기, `top_k`, LLM 모델
- 넣지 않는 것: API 키(→ `.env`), 로직
- 규칙: 코드 안에 작품명·숫자를 하드코딩하지 않는다

## `data/`

데이터는 `raw/ → processed/ → index/` 한 방향으로만 흐릅니다. `curated/`만 사람이 직접 넣습니다.

| 폴더 | 정의 | 만드는 주체 | 커밋 |
|---|---|---|---|
| `raw/` | 외부 API·위키에서 받은 원본 그대로. **손으로 수정 금지** | `aniwhere/ingest` | ❌ 다시 받으면 됨 |
| `curated/` | 사람이 작성·검수한 데이터: 주요 사건, 회차 보강, "커터칼 같은 칼" 같은 사용자식 표현 | 사람 | ✅ 팀의 핵심 자산 |
| `processed/` | 청크 파일. 각 청크에 작품·청크 종류·시즌·회차 메타데이터 포함 | `aniwhere/chunking` | ❌ |
| `index/` | 벡터 DB 파일 | `aniwhere/retrieval` | ❌ |

출처별 라이선스는 `data/README.md`에 기록합니다.

## `notebooks/`

탐색과 실험의 기록. 출처 비교, 데이터 품질 확인, 청킹 A/B 비교 등.

- 파일명: `번호-이름-내용.ipynb` (예: `0-taeho-출처비교.ipynb`)
- 재사용할 코드가 생기면 `aniwhere/`로 옮긴다
- `aniwhere/`가 노트북을 import하는 것은 금지 — 노트북은 기록이지 부품이 아님

## `aniwhere/` — 앱 본체

의존 방향은 **위에서 아래로만** 허용합니다. 아래 모듈이 위 모듈을 쓰는 것은 OK, 반대는 금지.

| 모듈 | 정의 | 입력 → 출력 |
|---|---|---|
| `ingest/` | 외부 수집. 출처마다 파일 하나(`anilist.py`, `tmdb.py`, `kitsu.py` …) | 인터넷 → `data/raw/` |
| `chunking/` | 기억 단위 청킹. 청크 종류: `anime_summary` · `character` · `event` · `episode` · `terminology` · `streaming`. 비교용 고정 길이 방식도 함께 구현 | `raw/` + `curated/` → `processed/` |
| `retrieval/` | 임베딩, 벡터 DB 적재·검색, 하이브리드 검색, 2단계 검색(작품 확정 → 회차 재검색). **스포일러 필터 위치**: 검색 함수는 "본 회차"를 필수 인자로 받고 그 이후 청크를 검색 전에 제외 | `processed/` → `index/`, 질문 → 근거 청크 |
| `agent/` | 의도 분류(사용자가 시청 여정 어느 단계에 있는지 판단), 단서 추출, 도구 선택(조건 검색 vs 벡터 검색), 추가 질문, 답변 생성. 프롬프트는 `agent/prompts/` | 사용자 발화 → 판단 → 답변 |
| `records/` | **앱의 중심 기억.** 본 작품·평점·진행 회차 저장·조회. 모든 단계가 여기서 "어디까지 봤는가"를 읽고, 스포일러 범위도 여기서 결정 | 사용자 기록 ↔ DB |
| `api/` 또는 `app/` | 바깥과의 입구. **판단 로직 금지** — `agent/`를 호출하고 결과만 전달 | 화면 ↔ `agent/` |

### 화면 구성 (데모 확인 후 하나로 확정)

- **Python 하나로 화면까지 그리는 경우**(Streamlit·Gradio 등): `aniwhere/app/`에 화면. `frontend/` 없음
- **HTML/JS 화면 + Python 서버인 경우**: `aniwhere/api/`(서버) + 최상위 `frontend/`(화면)

## `frontend/` (분리형일 때만)

- 화면은 시청 여정 단계에 대응: 검색/대화(01·02), 작품 상세·시청처(03), 복습(04), 시청 기록장(05)
- 어느 화면에서든 시청 기록장과 다른 단계로 이어지는 동선을 둔다 (한 기능만 쓰고 떠나는 앱이 되지 않게)
- 한/영 문구는 `frontend/i18n/`에 분리
- 규칙: API만 호출한다. 데이터 파일·DB를 직접 읽지 않는다

## `eval/`

검색 품질을 숫자로 증명합니다.

- `questions.jsonl`: 질문 ↔ 정답(작품·회차). 30개 → 100개
- `results/날짜_설정.json`: 실행마다 저장
- 청킹 A/B, 임베딩 교체 전/후 등의 Top-1 정확도 → 발표 근거

## `tests/`

고장 여부를 확인합니다(`eval/`은 품질, `tests/`는 고장).

- 필수: "N화까지 봤으면 N+1화 이후 청크는 절대 나오지 않는다"

## `reports/figures/`

노트북·`eval/`이 만든 발표용 차트와 그림.

## `docs/`

| 위치 | 내용 |
|---|---|
| `ARCHITECTURE.md` | 이 문서 |
| `repo-map.html` | 이 문서를 보기 쉽게 옮긴 저장소 지도(폴더 트리·데이터 흐름·브랜치/PR 규칙). 브라우저로 열기 |
| `identity/` | AniWhere 기능 지도 — 정체성("애니를 볼 때 거칠 수밖에 없는 곳"), 시청 여정 5단계, 기능 14개와 우선순위의 기준. 초기 에이전트 아이디어(`AniWhere_에이전트_아이디어_이의진.html`)도 함께 둠 |
| `workflow/` | 도입 전/후 흐름도 (Category G 필수) |
| `data-sources.md` | "작품 × 출처" 비교표와 결정 |
| `ui/` | 화면 목록과 시안 |
| `meetings/` | 날짜별 회의록 `YYYY-MM-DD_주제.md` |

## 헷갈릴 때

| 질문 | 위치 |
|---|---|
| 사람이 손으로 만든 데이터인가? | `data/curated/` |
| 코드가 만든 데이터인가? | `data/raw·processed·index/` (커밋 X) |
| 반복 실행되어 같은 결과가 나와야 하는 코드인가? | `aniwhere/` |
| 한 번 해보는 실험인가? | `notebooks/` |
| 값만 바뀌는가? | `config/` |
| 사람이 읽는 글인가? / 그림인가? | `docs/` / `reports/figures/` |
