SHELL := /usr/bin/env bash
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
MODEL ?=
CKPT ?= champion
SEEDS ?= 3
REPEAT ?= 1
JOB ?=
CHALLENGER ?=
ENGINE ?=
PREDICTIONS ?=
BASE ?= origin/main

.PHONY: help setup check lint harness eval train job-status gate contamination scope protect baseline scrub clean

help:
	@echo "make setup                      install the pinned CPU environment into .venv"
	@echo "make check [REPEAT=n]           lint + unit tests + harness self-tests (CPU, hermetic)"
	@echo "make eval MODEL= CKPT= SEEDS=3  evaluate a checkpoint and write results/<run>/scores.json"
	@echo "make train MODEL=               submit a GPU job (does not block)"
	@echo "make job-status JOB=<id>        pending | running | done | failed"
	@echo "make gate MODEL= CHALLENGER=<run>   promotion gate (CI runs this)"
	@echo "make contamination MODEL=       n-gram + embedding overlap, data/ vs evals/frozen/"
	@echo "make scope                      one-model, one-concern diff check"
	@echo "make protect                    protected-file diff check"
	@echo "make baseline                   print baseline.json contents"
	@echo "make scrub IN= OUT=             redact PII from a document"

setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.lock

check: lint harness
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

harness:
	$(PYTHON) evals/doug-a/harness/selftest.py
	$(PYTHON) evals/doug-l/harness/selftest.py

eval:
	@test -n "$(MODEL)" || (echo "MODEL is required" && exit 2)
	bash scripts/eval.sh --model "$(MODEL)" --ckpt "$(CKPT)" --seeds "$(SEEDS)" $(if $(ENGINE),--engine "$(ENGINE)",) $(if $(PREDICTIONS),--predictions "$(PREDICTIONS)",)

train:
	@test -n "$(MODEL)" || (echo "MODEL is required" && exit 2)
	bash scripts/train.sh --model "$(MODEL)"

job-status:
	@test -n "$(JOB)" || (echo "JOB is required" && exit 2)
	$(PYTHON) -m scripts.job_status --job "$(JOB)"

gate:
	@test -n "$(MODEL)" -a -n "$(CHALLENGER)" || (echo "MODEL and CHALLENGER are required" && exit 2)
	$(PYTHON) -m scripts.gate --model "$(MODEL)" --challenger "$(CHALLENGER)"

contamination:
	@test -n "$(MODEL)" || (echo "MODEL is required" && exit 2)
	$(PYTHON) -m scripts.contamination --model "$(MODEL)"

scope:
	$(PYTHON) -m scripts.scope --base "$(BASE)"

protect:
	$(PYTHON) -m scripts.protect --base "$(BASE)"

baseline:
	@cat baseline.json

scrub:
	@test -n "$(IN)" -a -n "$(OUT)" || (echo "IN and OUT are required" && exit 2)
	$(PYTHON) -m scripts.scrub --in "$(IN)" --out "$(OUT)"

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +
