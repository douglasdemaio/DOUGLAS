SHELL := /usr/bin/env bash
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else python3; fi)
export PYTHON

.PHONY: help setup check lint h3do-eval h3do-endpoint-eval clean

help:
	@echo "make setup                 install the pinned CPU environment into .venv"
	@echo "make check [REPEAT=n]      lint + unit tests (CPU, hermetic)"
	@echo "make h3do-eval SEEDS=3     run the offline H3-DO research harness"
	@echo "make h3do-endpoint-eval    call H3DO_ENDPOINT_URL with a required token"
	@echo "make clean                 remove local caches"

setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.lock

check: lint
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

h3do-eval:
	$(PYTHON) -m evals.h3do.tools.baseline --seeds $(or $(SEEDS),3) $(if $(OUT),--out "$(OUT)",)

h3do-endpoint-eval:
	@test -n "$(H3DO_ENDPOINT_URL)" || (echo "H3DO_ENDPOINT_URL is required" && exit 2)
	$(PYTHON) -m evals.h3do.tools.baseline --engine endpoint --endpoint-url "$(H3DO_ENDPOINT_URL)" --require-token --seeds $(or $(SEEDS),3) $(if $(OUT),--out "$(OUT)",)

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +
