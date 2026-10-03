# AniWhere

> 당신의 덕질 어디서든지, **AniWhere**

장면은 기억나는데 제목이 기억 안 날 때, 어디까지 봤는지 모를 때, 오랜만에 이어볼 때 —
기억을 자연어로 말하면 작품과 회차를 찾고, **본 회차까지만 스포일러 없이** 복습해 주는 AI Agent 앱입니다.

- 기능 지도(프로젝트 정체성): [`docs/identity/AniWhere_기능지도_2026-10-01.html`](docs/identity/AniWhere_기능지도_2026-10-01.html)
- 폴더 구조 정의: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
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
