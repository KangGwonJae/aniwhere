# AniWhere UI 프로토타입

- 담당: 이의진
- 형태: HTML/CSS/JavaScript 기반 설치형 PWA
- 위치: [`frontend/`](../../frontend/)
- 현재 상태: UI 프로토타입. Vector DB·Agent·OTT API·영구 저장은 연결 전

## 확인 방법

```bash
cd frontend
python3 -m http.server 8000
```

브라우저에서 <http://localhost:8000>을 엽니다.

## 팀 리뷰 동선

1. **AI 대화**
   - 기억으로 작품 찾기
   - 기억으로 회차 찾기
   - 추가 질문과 시청 지점 저장
   - 3분 복습·시청 순서·재미 시작점·원작 연결 바로가기
2. **시청 기록**
   - 작품별 진행 회차
   - 기록 수정
   - 스포일러 보호 범위
   - 새 시즌 알림과 직전 내용 복습
3. **탐색**
   - 취향 인터뷰 추천
   - 시청 순서 가이드
   - “몇 화부터 재밌어져요?”
   - 애니 → 원작 연결
   - 비슷한 작품 검색·스포일러 없는 추천 문구

## 기능 범위

기능 지도의 14개 기능을 모두 화면에서 확인할 수 있습니다. 다만 현재 대화·결과·저장은 모두 가짜 응답으로 동작하며, 팀의 API 약속에 맞춰 연결해야 합니다.

### 백엔드 연결 대상

- 05·06 찾기: `question`, `history` → `answer`, `candidates`, `follow_up`, `sources`
- 07 시청처: `series_id` → `seasons[].providers`, `checked_at`
- 09 복습: `series_id`, `seen_ep`, `mode`, `question` → `answer`, `sources`
- 13 기록: `series_id`, `seen_ep`, `rating` → 저장 결과

`seen_ep`는 복습·인물 사전·검색의 스포일러 범위를 정하는 필수 값입니다.
