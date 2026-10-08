# 자주 쓰는 명령 모음. 데모 코드를 옮기면서 각 명령을 실제 스크립트에 연결합니다.
.PHONY: setup data index run test eval

# 인기순 상위 몇 개 시리즈까지 받을지: make data LIMIT=1000
LIMIT ?= 300
COLLECT = .venv/bin/python data/collect.py

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

test:
	.venv/bin/python -m pytest tests

eval:
	.venv/bin/python eval/run.py
