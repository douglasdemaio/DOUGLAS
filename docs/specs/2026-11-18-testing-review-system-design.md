# Testing and review system for the improvement loop

Date: 2026-11-18

## Principle

Fail closed. A proposed change is accepted only when every required check is
present, passes, and is independently verified. A missing check, an
unavailable gate, an unverifiable receipt or a containment violation is a
rejection — never a skip. The agent can prepare and submit a change; only the
existing CI promotion gate (`scripts/gate.py` via `.github/workflows/gate.yml`)
can turn a challenger into a champion.

Nothing in this system edits the frozen suites, the gate, the harness, the
acceptance thresholds, the receipt schema, the signing keys, or either
workflow. Those stay human-reviewed and are checked as protected paths.

Review artifacts live under `docs/reviews/` so `make scope` classifies them as
bookkeeping paths; this keeps the one-model/one-concern check meaningful without
editing the protected `scripts/scope.py`.

## Requirement map

| # | Requirement | Tests | CI check | Files |
|---|---|---|---|---|
| 1 | Test every proposed change: frozen suite, ≥3 seeds, CI gate; stop if any is unavailable | `tests/test_review.py` (missing check, gate unavailable, replay re-grade, bad seeds), `tests/test_eval_gate.py` (existing) | `make check` runs all tests; `review.py` re-runs `make check`, verifies the frozen manifest and re-grades `predictions.jsonl` before calling the gate | `scripts/review.py`, `scripts/eval.py` (read-only use), `Makefile` (`review` target) |
| 2 | Explain every rejection with what failed, why it matters, how to fix it, root cause; append-only log; PR link; resubmission as a new run | `tests/test_rejection.py` (four sections, append-only, no overwrite, link), `tests/test_policy.py` (same diff hash blocked) | `make check`; review preflight validates the rejection log before starting a run | `scripts/rejection.py`, `docs/reviews/rejections.jsonl`, `docs/reviews/reports/*.md`, `scripts/policy.py` |
| 3 | Gatekeeper out of reach; test it with known-bad changes and tampered receipts; check frozen suite unchanged | `tests/test_gatekeeper.py` (weak score, too few seeds, frozen-hash mismatch, dirty contamination, tampered payload/signature/wrong key/malformed JWS, frozen hash drift), `tests/test_protect.py` (existing) | `make protect BASE=<base>` in `ci.yml`; `make check`; `review.py` preflight compares the current frozen hash with the last signed decision | `tests/test_gatekeeper.py`, `scripts/review.py`, `scripts/protect.py` (read-only use) |
| 4 | At most one PR, daily run cap, cooldown after rejection or rollback | `tests/test_policy.py` (caps, cooldown, clock, open PR count, fail-closed) | `make check`; `review.py` refuses to start when a cap or cooldown is active | `docs/reviews/policy.json`, `docs/reviews/events.jsonl`, `scripts/policy.py` |
| 5 | Traceable promotion: signed receipt with diff, per-seed results, gate decision, parent champion, timestamp; one-command rollback with receipt | `tests/test_attestation.py` (payload fields, signature, tamper detection, registry link), `tests/test_rollback.py` (restores prior signed champion, emits receipt, refuses unsigned origin) | `make check`; `ci.yml` runs `python -m scripts.attestation verify-all` | `scripts/attestation.py`, `scripts/rollback.py`, `docs/reviews/decisions.jsonl` |
| 6 | Least permission; no network or writes outside repo + artifact store; violations logged and halt | `tests/test_containment.py` (path allowlist, env scrubbing, network off, violation log) | `make check`; `review.py` uses the guard for every subprocess | `scripts/containment.py`, `docs/reviews/containment.jsonl` |

## Components

- **`scripts/review.py`** — orchestrator. Steps, in order: containment guard →
  policy check (run cap, open PR, cooldown, prior rejection) → `make check` →
  `make scope` + `make protect` → frozen manifest and hash → verify ≥3 seeds and
  re-grade the run's `predictions.jsonl` with `ENGINE=replay` (without a
  predictions file the run stops; the gate itself trusts `scores.json`) →
  invoke `scripts.gate` → on pass,
  read the new registry receipt and sign a decision attestation → on any
  failure, write a rejection report. It never writes to `registry/` or
  `baseline.json` itself.
- **`scripts/rejection.py`** — renders the four required sections and appends
  the report to `docs/reviews/rejections.jsonl` and a Markdown file under
  `docs/reviews/reports/`. Appends only; existing lines are never rewritten.
- **`scripts/attestation.py`** — compact JWS built with
  `scripts.sign_receipt.sign_payload` and the key supplied only through
  `DOUGLAS_SIGNING_KEY`. Payload: `kind`, `model_id`, `run`, `diff_sha256`,
  `diff`, `per_seed`, `metrics`, `gate_decision`, `gate_receipt`,
  `parent_champion`, `frozen_eval_sha256`, `timestamp`. `verify-all` checks
  every attestation and the linked registry receipt.
- **`scripts/policy.py`** — loads `docs/reviews/policy.json` (`max_runs_per_day: 1`,
  `max_open_prs: 1`, `cooldown_hours_after_rejection: 24`,
  `cooldown_hours_after_rollback: 24`, artifact roots) and reads append-only
  `docs/reviews/events.jsonl` (`run`, `pr_open`, `pr_closed`, `rejection`,
  `rollback`). The loop records PR state through `scripts.policy record`;
  without PR-state evidence a new run is refused. Unreadable or missing state
  means "no run".
- **`scripts/containment.py`** — allowlisted roots: repository root plus
  `results/`, `_hub/` and `$DOUGLAS_ARTIFACT_DIR`. Subprocesses get a minimal
  environment and proxy settings that make network calls fail; in-process
  sockets are blocked unless `--allow-network` is recorded with a reason.
  Violations append to `docs/reviews/containment.jsonl` and halt with exit 2.
- **`scripts/rollback.py`** — `--model doug-a` restores the most recent
  verified signed promotion from `registry/<id>.jsonl` that is older than the
  current champion, rewrites the champion scores file, updates `baseline.json`
  and the ledger, and emits a signed rollback attestation. It cannot invent a
  champion: the restoration source must verify against
  `registry/verification_key.pub`.

## Exit codes

`0` pass / promoted, `1` rejected (report written), `2` unavailable, halted or
containment violation. A `2` is always a stop, never a retry with weaker checks.

## Rejection report format

Four headings, in order: **What failed** (check, metric, seed, numbers),
**Why it matters** (risk or regression), **What would make it acceptable**
(concrete changes or evidence), **Root cause** (best diagnosis or the literal
string `cause unknown`; never a silent guess). See
`docs/reports/example-rejection-2026-11-18.md`, written for a deliberately bad
change (a two-seed challenger whose `fix_rate` is inside the noise margin).

## Packaging

One `douglas/` branch with small stacked commits, then one PR (per `AGENTS.md`
constraint 4). The PR body links the design doc and the example report.
