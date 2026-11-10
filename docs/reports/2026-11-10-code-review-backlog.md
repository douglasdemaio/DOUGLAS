# Code review backlog (2026-11-10)

Findings from a full read of the repository. Only the first item has been fixed
(this PR). Everything else is recorded here for later, one concern per PR as
`AGENTS.md` requires. Items marked **protected** touch files that
`scripts/protect.py` guards and need the maintainer.

## Fixed in this PR

- DOUG-A grader: patches could edit files outside `allowed_paths` (for example
  rewrite the failing test) by using unprefixed diff headers, and could write
  outside the sandbox via absolute or `../` paths. Fixed by diffing the tree
  before and after apply and refusing escaping paths; covered in the self-test.

## Bugs, harness (one PR each)

1. **Environment leak.** `run_check` passes the full environment, so
   model-written code can read `HF_TOKEN` inside the predict job. Pass a
   minimal environment.
2. **Malformed DOUG-A output crashes the eval.** A non-string `patch`, a
   non-dict prediction, or a patch that hangs (`TimeoutExpired`) raises instead
   of scoring zero.
3. **Malformed DOUG-L output crashes the eval.** A non-dict `plan` or
   `extraction`, or a non-numeric `cost`, raises instead of scoring zero.
4. **Destructive command check misses a string.** `commands` given as a single
   string (`"rm -rf /"`) is not flagged.

## Bugs, training and eval pipeline

5. **Mixture weights are ignored.** `weight` and `mixture` in `recipe.yaml` are
   never read by `scripts/train_remote.py`; sources are concatenated. A run that
   only changes a weight is a no-op. Decide what a weight means first (sampling
   ratio or row multiplier).
6. **Seeds are not independent.** Predictions are generated once, greedily, and
   replayed per seed, so std is always 0. With 8 frozen items one flip moves the
   primary metric by 0.125 against a noise margin of 0.02.
7. **Adapter is not pinned.** Every run pushes to the same Hub repo and the
   predict job loads its head with no revision. Pin by revision.
8. **`--timeout` in `scripts/eval.py` is unused**, and a parse failure in the
   endpoint engine aborts the whole run instead of scoring that item zero.
9. **`scripts/scrub.py --check`** counts existing `[REDACTED:phone]` markers, so
   an already scrubbed file fails. (From reading the code, not reproduced.)
10. **`scripts/submit_job.py`** submits a job pushing to `your-namespace/...`
    when the namespace lookup fails. Refuse instead.
11. **`scripts/pending_jobs.py --refresh`** queries every job in the ledger,
    including finished ones.

## Bugs, protected files (maintainer)

12. **`scripts/gate.py`** trusts `scores.json` as given instead of re-grading
    `predictions.jsonl`.
13. **`scripts/gate.py`** accepts `replay:...` or `unhashed:...` as
    `adapter_sha256`.
14. **`scripts/gate.py`** signs the current recipe hash, not the one the adapter
    was trained with.
15. **`scripts/scope.py` and `scripts/protect.py`** fall back to `git status`
    and report OK when `git diff` fails (for example a bad base ref).
16. **CI runs the PR's own copy of `scope` and `protect`.** Run the base
    branch's copy.
17. **Unprotected but sensitive:** `ci.yml`, `contamination.py`, `common.py`,
    `budget.py` are not on the protected list.
18. **`scope` rejects a data source plus its recipe line** as two concerns
    (seen on `douglas/doug-l-recipe-42771490206`). Either treat that pair as one
    concern or require two PRs.

## Proposed expansions

A. **Gate re-grades.** Replay `predictions.jsonl` through the harness before
   signing, and add a command that verifies every receipt in `registry/`.
B. **Real noise estimates.** Sample with distinct seeds or bootstrap a
   confidence interval over items, and grow the frozen sets well beyond 8 items
   (maintainer only).
C. **Implement mixture weights** (see item 5).
D. **Per-item contamination check.** Compare each frozen item against each
   training row, not whole files. Current per-item max cosine: DOUG-A 0.70,
   DOUG-L 0.54, against file-level 0.34 and 0.46; both under the 0.97 threshold.
E. **Real DOUG-A sandbox.** Scrubbed environment, no network, resource limits.
   Today it is a temp directory plus a subprocess.
