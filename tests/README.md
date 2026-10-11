# tests/

코드가 깨지지 않았는지 확인합니다. `make test`로 실행합니다.

필수 테스트: **"N화까지 봤으면 N+1화 이후 청크는 검색 결과에 절대 나오지 않는다."**

- test_api.py: API 서버. DB·LLM 없이 가짜 서비스로 돕니다. service.py에 함수를 추가하면 라우트도 추가해야 통과합니다.
- test_chat.py: 에이전트 대화 루프(agent/chat.py). DB·LLM 없이 stub 도구와 대본 LLM(chat_script.py)으로 돕니다. 도구·LLM 한도, 메시지 순서, save_record 보호, 칩·context 규칙.
- test_llm.py: LLM 래퍼(agent/llm.py)의 function calling 요청·응답 해석. 가짜 OpenAI 클라이언트.
- chat_script.py: 테스트 공용 대본 LLM(테스트 파일이 아님).
