# Bayyinah — common tasks.
# Windows without make: use the commands in README.md; they are identical.

PY ?= python
PORT ?= 8080

.PHONY: help install ingest test eval lint dev docker-build docker-up clean

help:
	@echo "make ingest       - ingest corpora/raw into SQLite"
	@echo "make test         - run the test suite"
	@echo "make eval         - run both eval suites (gates the build)"
	@echo "make lint         - ruff (optional)"
	@echo "make dev          - serve on :$(PORT)"
	@echo "make docker-up    - docker compose up --build"
	@echo "make clean        - remove the database and caches"

install:
	pip install python-docx pypdf

ingest:
	$(PY) -m bayyinah ingest corpora/raw

test:
	$(PY) -m unittest discover -s tests -t . -v

eval:
	$(PY) evals/run_eval.py --fail-on-gate

lint:
	ruff check bayyinah evals tests

dev:
	$(PY) -m bayyinah serve --port $(PORT)

docker-build:
	docker build -t bayyinah .

docker-up:
	docker compose up --build

clean:
	rm -rf var corpora/index
	find . -name "__pycache__" -type d -exec rm -rf {} +
