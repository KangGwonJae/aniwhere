# 자주 쓰는 명령 모음. 데모 코드를 옮기면서 각 명령을 실제 스크립트에 연결합니다.
.PHONY: setup data index run api test eval db-dump db-restore

# 인기순 상위 몇 개 시리즈까지 받을지: make data LIMIT=1000
LIMIT ?= 300
COLLECT = .venv/bin/python data/collect.py
# 서비스용 DB 공유 (data/README.md의 "서비스용 DB 공유"): make db-dump / make db-restore DUMP=받은파일.dump
DUMP ?= data/dump/aniwhere_service_$(shell date +%F).dump
SERVICE_DB = $(shell .venv/bin/python -c "from aniwhere.config import service_db_url; print(service_db_url())")

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

data:
	$(COLLECT) init seed anilist
	$(COLLECT) tvmaze tmdb jikan characters --limit $(LIMIT)
	$(COLLECT) fandom

index:
	$(COLLECT) chunks report
	$(COLLECT) embed --limit $(LIMIT)

run:
	.venv/bin/streamlit run aniwhere/app/demo.py

# API 서버 + 화면 (http://localhost:8000, 문서 /docs). DB·LLM 없이 가짜 응답으로 띄우기: make api FAKE=1
# --reload-dir aniwhere: .venv·data/까지 감시하면 시작이 느려서 앱 코드만 감시
FAKE ?=
api:
	ANIWHERE_FAKE=$(FAKE) .venv/bin/uvicorn aniwhere.api.main:app --reload --reload-dir aniwhere --port 8000

test:
	.venv/bin/python -m pytest tests

eval:
	.venv/bin/python eval/run.py

# 서비스용 DB를 파일 하나로 내보냄 (내 시청 기록은 빼고). 만든 파일은 커밋하지 않고 클라우드에 올려 공유
db-dump:
	mkdir -p $(dir $(DUMP))
	@echo "서비스용 DB를 내보내는 중… (몇 분 걸림)"
	@pg_dump -Fc --no-owner --no-privileges --exclude-table-data=watch_records -d "$(SERVICE_DB)" -f $(DUMP)
	cd $(dir $(DUMP)) && shasum -a 256 $(notdir $(DUMP)) > $(notdir $(DUMP)).sha256
	@ls -lh $(DUMP)

# 받은 쪽: 덤프 파일을 내 PostgreSQL에 복원 (.env의 DATABASE_URL 서버에 aniwhere_service가 없으면 만들고, 있으면 지우고 다시 넣음)
# 벡터 인덱스를 메모리 안에서 만들도록 maintenance_work_mem을 넉넉히 줌 (기본값 64MB면 몇 배 느림)
db-restore:
	@test -f "$(DUMP)" || { echo "덤프 파일이 없습니다: $(DUMP)  (make db-restore DUMP=경로)"; exit 1; }
	@.venv/bin/python -c "import sys; sys.path.insert(0, 'data'); import collect; collect.ensure_database('$(SERVICE_DB)')"
	@echo "복원하는 중… (벡터 인덱스를 다시 만드느라 몇 분 걸림)"
	@PGOPTIONS="-c maintenance_work_mem=2GB" pg_restore --clean --if-exists --no-owner -j 4 -d "$(SERVICE_DB)" "$(DUMP)"
	@psql -d "$(SERVICE_DB)" -q -c "ANALYZE" -c "SELECT (SELECT count(*) FROM series) AS series, count(*) AS chunks, count(embedding) AS embedded FROM chunks"
