# Add a Pika H3 Flex Ref2VA research slice

Date: 2026-11-28

## Goal

Extend the offline H3-DO research harness with a small Pika H3 Flex
reference-to-video-audio slice, reported separately from the existing FL2VA
slice. This is one research/eval concern.

## Decisions

- Add two prompt IDs (`p005`, `p006`) and two manifest items
  (`h3do-ref2va-001`, `h3do-ref2va-002`) with `task: ref2va`.
- Represent references as ID+type placeholders only: no media bytes, URLs, or
  endpoint calls. Allowed types are `image`, `video`, and `audio`.
- Add six numeric fixture records: two new items × seeds 1–3.
- Replace the manifest's single `adapter_path` with `task_adapters`, mapping
  `t2va` to `fl2va/adapter.safetensors` and `ref2va` to
  `ref2va/adapter.safetensors`. Keep the pinned Pika identity and upstream base.
- Extend manifest validation so `ref2va` items require a non-empty `references`
  list and `t2va` items have no references.
- Keep one offline run. Add `metrics_by_task` to `scores.json` and `report.md`
  while preserving the existing overall `metrics` contract.
- Do not change endpoint request behavior, prompt text for existing items,
  numeric fixtures for existing items, tolerances, or seeds.
- No training, promotion, signing, frozen eval, or new dependency.

## Files changed

- `evals/h3do/research/prompts.jsonl` — two new Ref2VA prompts with references.
- `evals/h3do/research/eval_manifest.json` — two new items, `task_adapters`,
  and reference metadata.
- `evals/h3do/research/synthetic_predictions.jsonl` — six new numeric records.
- `evals/h3do/tools/baseline.py` — validate references and aggregate by task.
- `evals/h3do/tools/report.py` — render per-task metrics when present.
- `evals/h3do/README.md` — document the Ref2VA slice and per-task reporting.
- `tests/test_h3do_eval.py` — consistency, validation, and reporting tests.

## Verification

1. `make check` passes.
2. `make h3do-eval SEEDS=3` completes offline.
3. `scores.json` contains overall `metrics`, `metrics_by_task` with `t2va` and
   `ref2va`, `items: 6`, and `failure_count: 0`.
4. `report.md` includes a per-task metrics table.

## Non-goals

- No hosted endpoint call.
- No real video, audio, or reference media is committed.
- No adaptation of scoring weights beyond grouping by task.
