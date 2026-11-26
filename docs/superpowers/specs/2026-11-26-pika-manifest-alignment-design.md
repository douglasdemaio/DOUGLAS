# Align H3-DO manifest with the Pika H3 Flex pin

Date: 2026-11-26

## Goal

Make the H3-DO research manifest describe the same pinned Pika H3 Flex target
as `evals/h3do/config.yaml`. This is one research/eval metadata concern.

## Decisions

- Change only `evals/h3do/research/eval_manifest.json`, its documentation, and
  its tests.
- Replace stale `base_repo` / `base_revision` fields with explicit Pika fields:
  `model`, `adapter_repo`, `adapter_revision`, `adapter_path`,
  `upstream_base_repo`, and `upstream_base_revision`.
- Keep `variant: FL2VA`, duration, resolution, seeds, tolerances, prompts,
  items, and numeric fixtures unchanged.
- Do not change endpoint request behavior or scoring logic.
- Do not add training, promotion, signing, or frozen-eval machinery.

## Files changed

- `evals/h3do/research/eval_manifest.json` — Pika adapter identity and upstream
  base metadata.
- `tests/test_h3do_eval.py` — one assertion group proving the manifest and
  config agree on model, repo, revision, adapter path, and upstream base.
- `evals/h3do/README.md` — document the Pika-specific manifest metadata.

## Verification

1. `make check` passes.
2. `make h3do-eval SEEDS=3` completes offline.
3. `scores.json` still records `model: pika-h3-flex` and the pinned Pika
   revision from the config.
4. No manifest item, prompt, fixture, or tolerance changes are present.

## Non-goals

- No Ref2VA items or fixtures are added.
- No endpoint payload changes.
- No new dependency or workflow.
