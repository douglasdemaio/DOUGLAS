SHELL := /usr/bin/env bash
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
export PYTHON  # scripts/eval.sh reads it, so `make eval` uses the same interpreter
MODEL ?=
CKPT ?= champion
SEEDS ?= 3
REPEAT ?= 1
JOB ?=
CHALLENGER ?=
ENGINE ?=
PREDICTIONS ?=
DIFF_FILE ?=
ADDRESSES ?=
DIFF ?=
BASE ?= origin/main

.PHONY: help setup check lint harness eval h3do-eval train job-status gate contamination scope protect baseline scrub clean review rollback attestations policy rejections

help:
	@echo "make setup                      install the pinned CPU environment into .venv"
	@echo "make check [REPEAT=n]           lint + unit tests + harness self-tests (CPU, hermetic)"
	@echo "make eval MODEL= CKPT= SEEDS=3  evaluate a checkpoint and write results/<run>/scores.json"
	@echo "make h3do-eval SEEDS=3          run the offline H3-DO baseline harness"
	@echo "make train MODEL=               submit a GPU job (does not block)"
	@echo "make job-status JOB=<id>        pending | running | done | failed"
	@echo "make gate MODEL= CHALLENGER=<run>   promotion gate (CI runs this)"
	@echo "make contamination MODEL=       n-gram + embedding overlap, data/ vs evals/frozen/"
	@echo "make scope                      one-model, one-concern diff check"
	@echo "make protect                    protected-file diff check"
	@echo "make review MODEL= CHALLENGER=  run every check; write a report on rejection"
	@echo "make rollback MODEL=            restore the previous signed champion"
	@echo "make attestations               verify every signed decision receipt"
	@echo "make policy MODEL= DIFF=        check run caps, cooldown and open PRs"
	@echo "make rejections                 list rejection reports"
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

h3do-eval:
	$(PYTHON) -m evals.h3do.tools.baseline --seeds $(or $(SEEDS),3) $(if $(OUT),--out "$(OUT)",)

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

review:
	@test -n "$(MODEL)" -a -n "$(CHALLENGER)" || (echo "MODEL and CHALLENGER are required" && exit 2)
	$(PYTHON) -m scripts.review --model "$(MODEL)" --challenger "$(CHALLENGER)" --base "$(BASE)" $(if $(DIFF_FILE),--diff-file "$(DIFF_FILE)",) $(if $(PREDICTIONS),--predictions "$(PREDICTIONS)",) $(if $(ADDRESSES),--addresses "$(ADDRESSES)",)

rollback:
	@test -n "$(MODEL)" || (echo "MODEL is required" && exit 2)
	$(PYTHON) -m scripts.rollback --model "$(MODEL)"

attestations:
	$(PYTHON) -m scripts.attestation verify-all

policy:
	@test -n "$(MODEL)" -a -n "$(DIFF)" || (echo "MODEL and DIFF are required" && exit 2)
	$(PYTHON) -m scripts.policy check --model "$(MODEL)" --diff "$(DIFF)" $(if $(ADDRESSES),--addresses "$(ADDRESSES)",)

rejections:
	$(PYTHON) -m scripts.rejection list

baseline:
	@cat baseline.json

scrub:
	@test -n "$(IN)" -a -n "$(OUT)" || (echo "IN and OUT are required" && exit 2)
	$(PYTHON) -m scripts.scrub --in "$(IN)" --out "$(OUT)"

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +
