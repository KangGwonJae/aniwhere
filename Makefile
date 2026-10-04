# 자주 쓰는 명령 모음. 데모 코드를 옮기면서 각 명령을 실제 스크립트에 연결합니다.
.PHONY: setup data index run test eval

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

data:
	.venv/bin/python -m scripts.collect_external_data --count 20

index:
	.venv/bin/python -m scripts.build_chunks
	.venv/bin/python -m scripts.build_vector_db

run:
	.venv/bin/python -m aniwhere.api.server

test:
	.venv/bin/python -m unittest discover -s tests -v

eval:
	.venv/bin/python -m scripts.evaluate_chunking
