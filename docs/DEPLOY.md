# 발표용 웹 배포

발표용 배포는 FastAPI와 `frontend/`를 하나의 Render Web Service로 제공합니다. 기본 설정은
`ANIWHERE_FAKE=1`이므로 외부 DB나 API 키가 없어도 핵심 화면과 데모 대화가 동작합니다.

## 최초 배포

1. 아래 버튼을 누르고 Render에 GitHub 계정으로 로그인합니다.
2. `aniwhere-demo` 서비스 구성을 확인한 뒤 **Deploy Blueprint**를 누릅니다.
3. 배포가 끝나면 발급된 `https://...onrender.com` 주소를 엽니다.
4. 그 주소를 QR 코드로 만들어 발표 자료에 넣습니다.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/KangGwonJae/aniwhere/tree/feat/uijin-ui-integration-v2)

## 사용자 기록 분리 방식

- 처음 접속한 브라우저는 `localStorage`에 익명 ID를 생성합니다.
- 모든 API 요청은 `X-AniWhere-User` 헤더에 이 ID를 담습니다.
- 서버의 기록·복습·인물 사전·추천·채팅은 해당 ID만 사용합니다.
- 로그인하지 않아도 각 휴대폰과 브라우저의 기록이 서로 섞이지 않습니다.
- 브라우저 저장 공간을 지우면 해당 기기의 익명 ID와 화면 기록도 초기화됩니다.

기존 로컬 실행은 그대로입니다. 헤더 없이 API를 호출하면 이전과 동일하게 `local` 사용자로 처리되고,
`make api`는 실제 DB 모드, `make api FAKE=1`은 데모 모드로 실행됩니다.

## 실제 DB·AI 모드로 전환

발표 후 실제 데이터 모드가 필요하면 Render 환경변수에서 `ANIWHERE_FAKE=0`으로 바꾸고
`DATABASE_URL`, `OPENAI_API_KEY`를 설정해야 합니다. 이때 빌드 명령도 전체 `requirements.txt`를
설치하도록 바꿔야 하며, 서비스 DB에 수집·청킹·임베딩 데이터가 준비되어 있어야 합니다.
