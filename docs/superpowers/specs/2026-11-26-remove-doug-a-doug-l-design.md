# Remove DOUG-A and DOUG-L model tracks

Date: 2026-11-26

## Goal

Reduce the repository to the H3-DO research/eval harness by deleting the
DOUG-A and DOUG-L model tracks and all model-track history. H3-DO remains
research/eval only.

## Decisions

- Delete all DOUG-A/DOUG-L data, configs, frozen evals, harnesses, results,
  receipts, ledger history, and dated docs/reports. Recovery remains available
  through git history.
- Delete the DOUG-A/DOUG-L training, evaluation, promotion, signing,
  contamination, policy, and scope machinery because it has no remaining
  consumer.
- Delete the scheduled improvement workflow and promotion gate workflow. No
  training or promotion automation remains.
- Keep the H3-DO harness, its offline fixture, endpoint adapter, and tests.
- In the same change, retarget the retained H3-DO research config to the pinned
  open-weight `Pika-Labs/Pika-H3-Flex` adapters and record its MiniMax H3
  upstream base. This remains research/eval only: no training or promotion.
- Keep the pinned Python environment. No dependencies are added.
- Rewrite the README, AGENTS.md, Makefile, and CI workflow for the reduced
  repository scope.
- Work on a local branch and commit locally. Do not push or open a PR without
  explicit approval.

## Files removed

- `models/`, `data/`, `registry/`, `results/`, `schemas/`, `experiments/`
- `evals/doug-a/`, `evals/doug-l/`
- `baseline.json`, `requirements.train.lock`
- `docs/reports/`, `docs/reviews/`, `docs/specs/` old model-track documents
- `scripts/` except a rewritten generic `common.py` and `__init__.py`
- all `tests/` except `conftest.py` and `test_h3do_eval.py`
- `.github/aw/`, `.github/workflows/douglas-improvement.md`,
  `.github/workflows/douglas-improvement.lock.yml`,
  `.github/workflows/gate.yml`

## Files retained or rewritten

- `evals/h3do/config.yaml` retargeted to `Pika-Labs/Pika-H3-Flex` at pinned
  revision `ca45d99f9b1d1859ffb9dc1cd6bfaaa994257f56`, with FL2VA and Ref2VA
  adapter paths and the MiniMax H3 upstream base recorded.
- `evals/h3do/tools/baseline.py` reads the track/model identity from config for
  `scores.json` instead of hardcoding the old base.
- `evals/h3do/README.md` and `evals/h3do/__init__.py` rewritten to remove stale
  DOUG-A/L language and describe the Pika H3 Flex research target.
- Other `evals/h3do/**` files unchanged.
- `scripts/common.py` reduced to generic helpers required by H3-DO:
  `ROOT`, time helpers, serialization helpers, JSONL helpers, hashing, and
  YAML/JSON loading.
- `tests/conftest.py` reduced to path setup and `repo_root`.
- `Makefile` reduced to `setup`, `help`, `lint`, `check`, `h3do-eval`,
  `h3do-endpoint-eval`, and `clean`.
- `.github/workflows/ci.yml` reduced to install pinned environment and run
  `make check`.
- `README.md` rewritten to document H3-DO only, including the endpoint secret
  behavior and the research/eval boundary.
- `AGENTS.md` rewritten to state that H3-DO is research/eval only, with no
  training, promotion, gate, signing, frozen eval, or threshold changes.

## Non-goals

- No new H3-DO capability or benchmark is added.
- No model endpoint is called during validation.
- No secret is printed, stored, or committed.
- No PR is opened or pushed as part of this change.

## Verification

1. `git grep -n -E 'doug-a|doug-l|DOUG-A|DOUG-L'` returns no tracked references.
2. `make check` passes.
3. `make h3do-eval` completes offline, writes `scores.json` and `report.md`, and
   records `model: pika-h3-flex` plus the pinned Pika revision.
4. `make h3do-endpoint-eval` is not executed without a configured endpoint.
5. `git status --short` shows only intended changes.

## Risks

- Deleting frozen eval directories conflicts with the old repository policy,
  but this change explicitly supersedes that policy by retiring the tracks.
- Removing model scripts and tests is intentionally irreversible in the
  working tree; git history remains the recovery path.
- README/AGENTS documentation must avoid implying that H3-DO can be trained or
  promoted.
