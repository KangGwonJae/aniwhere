# AGENTS.md

AI 코딩 도구(Claude Code, Cursor, Codex, Copilot 등)가 이 저장소에서 작업할 때 따르는 규칙입니다.
사람 팀원도 같은 규칙을 따릅니다. **규칙의 원본은 이 파일 하나**이고, `CLAUDE.md`는 이 파일을 불러오기만 합니다.

## 프로젝트

AniWhere — "당신의 덕질 어디서든지".
**애니를 볼 때 거칠 수밖에 없는 곳**이 정체성입니다. 영화를 볼 때 왓챠피디아를 여는 것처럼, 애니를 볼 때는 AniWhere를 엽니다.
특정 기능 하나(작품 찾기, 복습 등)가 정체성이 아닙니다. 시청 여정 전체에 들르는 곳이어야 합니다.

시청 여정 5단계: **01 입문 → 02 탐색 → 03 시청 → 04 이어보기 → 05 깊이 빠지기**
기능 범위와 우선순위는 `docs/identity/AniWhere_기능지도_2026-10-01.html`이 기준입니다.

## 반드시 지킬 원칙

1. **모든 기능은 시청 여정의 한 단계에 속한다.** 새 기능·화면·PR은 5단계 중 어디를 위한 것인지 먼저 밝힌다.
   어느 단계에도 속하지 않으면 만들지 않는다. 기능끼리는 시청 기록으로 이어져야 한다
   (예: 기록장의 진행 회차 → 복습의 스포일러 범위 → 인물 사전의 공개 범위).
2. **스포일러 차단.** 모든 기능에 적용되는 공통 원칙: "내 시청 기록을 기억하고, 본 회차 이후 내용은 보여주지 않는다."
   사용자가 본 회차 이후의 청크는 검색 *전에* 제외한다. 검색 결과에서 걸러내는 방식은 금지.
   검색 함수는 "본 회차"를 필수 인자로 받는다. 이 규칙은 `tests/`의 테스트로 지킨다.
3. **근거 없는 답 금지.** LLM은 검색된 청크만 근거로 답한다. 근거가 약하면 회차를 단정하지 않고 추가 질문한다.
4. **비밀 값은 커밋하지 않는다.** API 키는 `.env`에만 둔다. 새 키가 필요하면 `.env.example`에 이름만 추가한다.

## 폴더 규칙

각 폴더의 정확한 정의는 `docs/ARCHITECTURE.md`에 있습니다. 요약:

| 폴더 | 역할 |
|---|---|
| `config/` | 바뀔 수 있는 값(지원 작품, 모델 이름, 청크 크기). 코드에 하드코딩 금지 |
| `data/raw/` | 외부 API 원본. 손으로 수정 금지, 커밋 안 함 |
| `data/curated/` | 사람이 검수한 데이터. **커밋함** |
| `data/processed/`, `data/index/` | 코드가 만드는 청크·벡터 DB. 커밋 안 함 |
| `notebooks/` | 탐색·실험. `번호-이름-내용.ipynb`. 앱 코드가 노트북을 import하면 안 됨 |
| `aniwhere/` | 앱 본체. `ingest → chunking → retrieval → agent → (api/app)` 방향으로만 의존 |
| `eval/` | 평가 질문셋과 결과. 검색 품질을 숫자로 기록 |
| `tests/` | 고장 여부 확인. 스포일러 차단 테스트 필수 |
| `docs/` | 사람이 읽는 문서 |

어디에 둘지 헷갈리면: 사람이 만든 데이터 → `data/curated/`, 반복 실행되는 코드 → `aniwhere/`,
일회성 실험 → `notebooks/`, 바뀔 수 있는 값 → `config/`.

## Git 규칙

- `main`에 직접 push 금지. 브랜치를 만들고 PR로만 merge한다.
- 브랜치 이름: `종류/이름-주제` — 예: `feat/taeho-kitsu-collect`, `fix/uijin-search-ui`, `docs/gwonjae-readme`
  - 종류: `feat`(기능), `fix`(버그), `data`(데이터), `docs`(문서), `exp`(실험), `chore`(설정)
- merge는 **Merge commit** 방식만 쓴다(squash 금지). 과제 요구사항인 merge log를 남기기 위해서.
- PR 하나에는 한 가지 목적만. PR 본문은 `.github/pull_request_template.md`를 채운다.
- 커밋 메시지는 한국어 가능. 첫 줄에 무엇을 바꿨는지 한 문장으로.

## 실행 명령

```bash
make setup   # 패키지 설치
make data    # 외부 데이터 수집 → data/raw/
make index   # 청킹 + 벡터 DB 생성 → data/processed/, data/index/
make run     # 데모 실행
make test    # 테스트
make eval    # 평가셋 실행 → eval/results/
```

작업을 마치기 전에 `make test`를 실행해 통과를 확인한다.
