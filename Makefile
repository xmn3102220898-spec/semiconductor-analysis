PYTHON ?= python

.PHONY: help install run test lint bench check
.DEFAULT_GOAL := help

help:
	@echo "make install  Install production and development dependencies"
	@echo "make run      Start FastAPI on 0.0.0.0:8000"
	@echo "make test     Run tests with core-analysis coverage gate"
	@echo "make lint     Run compile and pyflakes checks"
	@echo "make bench    Print query and analysis latency baseline"
	@echo "make check    Run lint and tests"

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

run:
	$(PYTHON) -m uvicorn main_api:app --host 0.0.0.0 --port 8000

test:
	$(PYTHON) -X utf8 scripts/coverage_check.py --fail-under 80 --verbosity 2

lint:
	$(PYTHON) -m compileall -q app scripts main.py main_api.py
	$(PYTHON) -m pyflakes app scripts tests main.py main_api.py

bench:
	$(PYTHON) -X utf8 scripts/bench.py

check: lint test
