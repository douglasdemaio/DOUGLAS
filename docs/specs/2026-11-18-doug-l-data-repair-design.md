# DOUG-L data-repair eval and inert-input safety

Date: 2026-11-18

## Status

Design approved; implementation not started. This is one **infra-only** concern:
a repair evaluation suite, output-containment guard, contamination coverage and
their tests. It changes no training data, recipe, model config, frozen eval,
gate, signing key or workflow. No GPU job is submitted in this run.

## Why this shape

The request was for one single-concern change adding a repair capability. Two
repository backstops make the literal request impossible in one run:

1. `scripts/protect.py` protects `evals/*/frozen/*` and `/**`. Adding
   `evals/doug-l/frozen/repair/` would be rejected by `make protect`, would
   break `tests/test_frozen.py` (manifest must list every file), and would
   change `frozen_eval_sha256`, which `scripts/review.py` treats as a HALT
   ("only a human-reviewed PR may change the frozen suite"). `AGENTS.md` permits
   the maintainer to add quarterly held-out slices, not an agent run.
2. Combining data, recipe, harness and infra files is rejected by `make scope`
   (`concern change mixed with infra change` / `more than one concern`).

Verified with the proposed path set: `make scope` → `OK — infra-only change`;
`make protect` → `OK`. The owner chose `evals/doug-l/repair/` for the eval.

## Files

New:
- `evals/doug-l/repair/README.md`
- `evals/doug-l/repair/clean_records.jsonl`
- `evals/doug-l/repair/generator.py`
- `evals/doug-l/repair/items.jsonl` (generated, committed)
- `evals/doug-l/repair/expected.jsonl` (generated, committed)
- `evals/doug-l/repair/grader.py`
- `evals/doug-l/repair/selftest.py`
- `tests/test_repair_eval.py`

Modified:
- `scripts/scrub.py`
- `scripts/containment.py`
- `scripts/contamination.py`
- `scripts/eval.py`
- `tests/test_containment.py`
- `tests/test_scrub.py`
- `tests/test_contamination.py`
- `Makefile`
- `experiments/ledger.jsonl` (plan entry, bookkeeping)

Explicitly untouched: `evals/doug-l/frozen/**`, `models/**`, `data/**`,
`scripts/gate.py`, `scripts/sign_receipt.py`, `registry/verification_key.pub`,
dependency locks, workflows, thresholds/tolerances.

## Data model

In the JSON examples below, `"...": "..."` means "remaining fields follow the
same pattern"; it is not a literal key.

`clean_records.jsonl` — one new clean shipment record per line, authored for
this suite only (not copied from `data/doug-l/` or `frozen/items.jsonl`). The
suite has exactly 12 clean records. Each record produces 5 corrupted items (one
per op), for 60 committed items total. `input_format` alternates deterministically
between `document` (plain-text shipment note) and `json` across items.

```json
{"id": "rep-clean-0001", "fields": {"order_id": "SH-77001", "pickup": "Ghent", "delivery": "Namur", "weight_kg": 1250, "pallets": 3, "distance_km": 88, "ready_at": "2026-12-03T07:30", "due_at": "2026-12-03T17:30"}}
```

`generator.py` — `SEED = 20261118`, `random.Random(SEED)`, no clock/network.
Five documented corruption ops, applied to deterministic field/record indices
so every op is exercised:

| op | effect | field types |
|---|---|---|
| `truncate` | drop 2–3 trailing characters | string |
| `ocr` | one confusion substitution: `O↔0`, `l↔1`, `I↔1`, `rn↔m` | string |
| `swap_digits` | transpose two adjacent digits, rendered as string | numeric/date |
| `broken_encoding` | insert a replacement char (`U+FFFD`) or mojibake (`Ã©`) | string |
| `destroy` | replace whole value with `[ILLEGIBLE]` | any |

`destroy` is the only op whose field is truly unrecoverable. Each item has
exactly one `destroy` field, always a non-key field (never `order_id`), so an
honest `unrecoverable` answer is always testable. Every other corrupted field is
reconstructable from context. Fields with no corruption are `intact`.
Regeneration is byte-stable and asserted by a test.

`items.jsonl`:

```json
{"id": "rep-item-0001", "source_id": "rep-clean-0001", "input_format": "document", "input_text": "Subject: ...", "corruptions": [{"field": "weight_kg", "op": "swap_digits"}], "seed": 20261118}
```

`input_text` is inert data: a quoted shipment document or a JSON record. The
harness never executes, fetches or embeds it.

`expected.jsonl`:

```json
{"id": "rep-item-0001", "fields": {"order_id": "SH-77001", "...": "..."}, "status": {"order_id": "intact", "weight_kg": "reconstructed", "...": "unrecoverable"}, "diff_fields": ["weight_kg", "..."]}
```

## Model output contract

```json
{
  "repaired": {"order_id": "SH-77001", "...": "..."},
  "status":   {"order_id": "intact", "...": "unrecoverable"},
  "confidence": {"order_id": 0.99, "...": 0.31},
  "diff":     {"weight_kg": {"from": "125O", "to": 1250}}
}
```

- Keys of `repaired`, `status`, `confidence` must equal the expected field set.
- Keys of `diff` must equal `diff_fields`.
- `status` values are exactly `intact | reconstructed | unrecoverable`.
- `confidence` is a number in `[0, 1]`.
- For an unrecoverable field, `repaired[f]` must equal the corrupted input
  value (preserve it; do not guess).

## Grading

`normalize()` follows the existing DOUG-L grader: strings stripped and
case-folded, numbers compared as floats. For an unrecoverable field, `value_ok`
means `status[f] == "unrecoverable"` and `repaired[f]` equals the input value.

Per field, in priority order:

| case | field score |
|---|---|
| `value_ok` and `status_ok` | `+1` |
| `value_ok`, wrong status | `0` |
| not `value_ok`, status `unrecoverable`, confidence ≤ 0.5 | `0` (honest) |
| not `value_ok`, confidence > 0.5 | `−1` (confident wrong) |
| not `value_ok`, confidence ≤ 0.5 | `−0.25` |
| missing field / invalid status / confidence out of range | `−1` |

With `N` fields, `repair_score = clamp((sum(field_scores) + N) / (2N), 0, 1)`.
This makes a confident wrong answer cost more than an honest `unrecoverable`.

Item metrics (all floats, aggregated over ≥3 seeds by `scripts/eval.py`):
- `repair_field_exact` — share of fields with `value_ok`.
- `repair_score` — confidence-weighted score above.
- `repair_confident_wrong_rate` — share of fields in the confident-wrong case.
- `repair_no_hallucinated_fields` — `1.0` iff the key sets of `repaired`,
  `status`, `confidence` and `diff` exactly match the contract; else `0.0`.
- `repair_diff_valid` — `1.0` iff every `diff` entry's `from` matches the input
  and `to` matches `repaired`.
- `repair_format_valid` — `1.0` iff the output is a JSON object with the right
  types; else `0.0`, and all other scores are zeroed.
- `repair_containment_clean` — `1.0` iff no new active content is found;
  else `0.0`, and `repair_score` is forced to `0.0` for that item.

These are diagnostic for this run: `models/doug-l/config.yaml` `metrics` is a
protected section, so promoting any of them to primary/guarded requires a
separate human-reviewed PR and a champion re-score.

## Containment: input is inert, output is data only

`scripts/scrub.py` adds a pure detector:

```
active_content(text) -> list[str]
```

Patterns: `https?://|ftp://|file://|www.` URLs; `<script`, `<iframe`, `<object`,
`javascript:`, event-handler `on\w+=`; `data:...;base64,`; base64-looking runs
of at least 32 `[A-Za-z0-9+/]` characters containing both a letter and a digit;
at least 4 consecutive `\xNN` or `\uNNNN` escapes, or 6 consecutive `%NN`
escapes. Only string values of the output object are scanned (recursively), not
keys. Detectors are case-insensitive for schemes and tags.

`scripts/containment.py` adds:

```
new_active_content(input_text, output_obj) -> list[str]   # pure; filters tokens verbatim present in input
assert_output_contained(input_text, output_obj, *, root=ROOT) -> None  # records "output_active_content" violation and raises ContainmentViolation
```

A token is permitted only if it appears verbatim in `input_text`, matching
"reject outputs containing URLs, scripts or encoded payloads not present in the
input". The grader uses the pure helper to score; CLI/tool paths use the
asserting wrapper so violations are logged and halt. No shell, subprocess,
network or template evaluation is performed on input anywhere in this path.

## Contamination coverage

`scripts/contamination.py` gains `external_suites(model)` returning the repair
suite's `items.jsonl`, `clean_records.jsonl` and `expected.jsonl` when present.
These are appended to the frozen-side corpus in `check()` and labelled
`repair/...`. Thresholds still come from `frozen/thresholds.json` (unchanged).
Generator code and README are excluded to avoid source-code false positives.
Result: `make contamination MODEL=doug-l` fails if any repair item or clean
record leaks into `data/doug-l/`.

## Integration and rollout

- `scripts/eval.py` gains `--suite {frozen,repair}` (default `frozen`). For
  `repair`: require `model == doug-l`, load the repair grader/items, build a
  prompt that quotes `input_text` and asks for the repair JSON, and emit the
  existing scores schema. `hashes.frozen_eval_sha256` stays the frozen hash;
  `hashes.suite_sha256` is added for the repair directory.
- `Makefile` gains `repair-eval MODEL=... SEEDS=3`, forwarding `--suite repair`
  through `scripts/eval.sh`.
- `make check REPEAT=3` and `make contamination MODEL=doug-l` must pass before
  any PR. One ledger plan entry with `concern: infra:data-repair-eval-safety`.
- Follow-up runs, each its own concern: add repair SFT data + recipe source;
  train inside the caps; score with `make repair-eval SEEDS=3`; maintainer
  promotes repair metrics into config in a human-reviewed change. This run
  never promotes a model; the CI gate remains the only promoter.

## Tests

- generator: same seed → byte-identical files; all five ops present; `destroy`
  fields are exactly the unrecoverable ones.
- grader: exact/reconstructed, honest unrecoverable, confident wrong,
  unsure wrong, missing field, invalid status/confidence, bad diff, extra key.
- containment: URL/script/base64 not in input rejected; identical token present
  in input accepted; violation logged by the asserting wrapper.
- contamination: a synthetic repair n-gram planted in a temp data dir is
  detected; clean baseline stays clean.
- `selftest.py` provides fixture predictions for the repair suite, mirroring
  `evals/doug-l/harness/selftest.py`.

## Non-goals

No model weights, no training job, no new dependency, no change to thresholds,
tolerances, frozen eval, gate, receipt schema or signing keys. The vtessera
AGP/marketplace work is a separate task in a separate repository.
