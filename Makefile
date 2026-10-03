# 자주 쓰는 명령 모음. 데모 코드를 옮기면서 각 명령을 실제 스크립트에 연결합니다.
.PHONY: setup data index run test eval

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

data:
	@echo "TODO: aniwhere/ingest 연결 → data/raw/"

index:
	@echo "TODO: aniwhere/chunking + retrieval 연결 → data/processed/, data/index/"

run:
	@echo "TODO: 데모 실행 명령 연결"

test:
	.venv/bin/python -m pytest tests

eval:
	@echo "TODO: eval 스크립트 연결 → eval/results/"
