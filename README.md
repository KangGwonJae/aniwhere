# AniWhere

> 당신의 덕질 어디서든지, **AniWhere**

**애니를 볼 때 거칠 수밖에 없는 곳.**
영화를 볼 때 왓챠피디아를 여는 것처럼, 애니를 볼 때는 AniWhere를 엽니다.
볼 작품을 고를 때도, 제목이 기억나지 않을 때도, 오랜만에 이어볼 때도 — 시작은 여기서.

## 시청 여정 전체를 함께합니다

AniWhere는 기능 하나짜리 도구가 아니라, 애니를 보는 모든 순간에 들르는 곳입니다.

| 단계 | 이럴 때 | AniWhere가 하는 일 |
|---|---|---|
| 01 입문 | "뭘 봐야 할지 모르겠어" | 취향을 물어보고 분위기가 비슷한 작품 추천 |
| 02 탐색 | "그 애니 뭐였더라?" | 어렴풋한 장면 묘사로 작품과 회차 찾기 |
| 03 시청 | "어디서 보지? 이 사람 누구지?" | 국내 OTT 시청처 안내, 지금 보는 회차 기준 인물·용어 사전 |
| 04 이어보기 | "다시 보려니 다 까먹었어" | 본 회차까지만 골라 보는 맞춤 복습 |
| 05 깊이 빠지기 | "더 알고 싶어, 남기고 싶어" | 본 작품·평점·진행 회차를 남기는 시청 기록장 |

### 모든 기능에 적용되는 원칙

> **내 시청 기록을 기억하고, 본 회차 이후 내용은 보여주지 않는다.**

시청 기록이 모든 단계를 잇는 중심이고, 스포일러 차단은 그 기록 위에서 모든 기능에 똑같이 적용됩니다.

### 이번 과제 범위 (10/13 제출)

| 우선순위 | 기능 |
|---|---|
| 필수 | 기억으로 작품 찾기 · 기억으로 회차 찾기 · 시청처 안내 · 스포일러 차단 |
| 이번에 추가 | 맞춤 복습 · 시청 기록장 |
| 여유 되면 | 취향 인터뷰 추천 · 회차 기준 인물·용어 사전 |

전체 기능 14개와 우선순위는 기능 지도에 있습니다.

## 문서

- 기능 지도(프로젝트 정체성·범위의 기준): [`docs/identity/AniWhere_기능지도_2026-10-01.html`](docs/identity/AniWhere_기능지도_2026-10-01.html)
- 폴더 구조 정의: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · 한눈에 보기: [`docs/repo-map.html`](docs/repo-map.html)
- 회의록: [`docs/meetings/`](docs/meetings/)
- 협업 규칙(사람·AI 공통): [`AGENTS.md`](AGENTS.md)

## 실행 방법

> 데모 코드 이관 후 실제 명령으로 갱신합니다.

```bash
git clone https://github.com/KangGwonJae/aniwhere.git
cd aniwhere
cp .env.example .env      # API 키 입력
make setup                # 패키지 설치
make data                 # 외부 데이터 수집
make index                # 청킹 + 벡터 DB 생성
make run                  # 데모 실행
make api                  # API 서버 + 화면 (http://localhost:8000, 문서 /docs)
make api FAKE=1           # DB·LLM 없이 가짜 응답으로 띄우기 (프론트엔드 개발용)
```

## 협업 방법

1. `main`에서 브랜치 생성: `git switch -c feat/이름-주제`
2. 작업 후 push → GitHub에서 PR 생성 (템플릿 채우기)
3. 팀원 1명 승인 → **Merge commit**으로 merge

`main`에는 직접 push할 수 없습니다. 자세한 규칙은 [`AGENTS.md`](AGENTS.md).

## 팀

| 이름 | 담당 |
|---|---|
| 강권재 | 저장소·아키텍처 |
| 이의진 | UI·데모 |
| 한태호 | 데이터 탐색 |

서울대 KDT 13기 · 빅데이터 핀테크 AI 응용사례 · Category G
