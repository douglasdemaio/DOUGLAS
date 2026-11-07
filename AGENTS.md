# AGENTS.md: DOUGLAS

Working notes for coding agents on this repository. These are **standing
constraints set deliberately by the maintainer**, not suggestions.

## Project

**DOUGLAS** stands for *Daily Optimized, Unsupervised Growth via Learning And
Scoring*. It is a family of fine-tuned open-weight models that improves itself
through a scheduled agent loop (`.github/workflows/douglas-improvement.md`).

| Model  | Full name | Job |
|--------|-----------|-----|
| DOUG-A | DevOps Operator for Uptime, Guardrails, Logs, Alerts and Systems | Reads logs, alerts and CI failures; finds the root cause; proposes a patch or a runbook step. |
| DOUG-L | Distribution Orchestrator for Unified Goods, Loads And Shipments | Turns shipment documents into structured orders; plans routes and loads by calling a solver; explains delays and options. |

Both models start from a **pinned open-weight base** and are trained with
**LoRA/QLoRA SFT**, followed by **DPO** on preference pairs. Pretraining from
scratch is out of scope.

## Layout

```
models/<id>/config.yaml     base model + revision pin, LoRA params, budget, metrics
models/<id>/recipe.yaml     data sources, filters, mixture weights  (the main thing you change)
data/<id>/                  training data, versioned; NEVER contains frozen eval items
evals/<id>/frozen/          locked test set; read-only (constraint 2)
evals/<id>/harness/         graders: sandbox runner (DOUG-A), solver/field checks (DOUG-L)
experiments/ledger.jsonl    every attempt, win or lose
registry/<id>.jsonl         every promoted champion + its signed receipt
scripts/                    train.sh, eval.sh, gate.py, sign_receipt.py, contamination.py
docs/specs/ docs/reports/   dated YYYY-MM-DD-*.md
```

## Commands

```bash
make check                      # lint, unit tests, harness self-tests (CPU only, hermetic)
make eval MODEL=doug-a CKPT=champion SEEDS=3    # writes results/<run>/scores.json
make train MODEL=doug-a         # submits a GPU job; returns a job id, does not block
make job-status JOB=<id>        # pending | running | done | failed
make gate MODEL=doug-a CHALLENGER=<run>   # promotion gate; CI runs this, not you
make contamination MODEL=doug-a # n-gram + embedding overlap, data/ vs evals/frozen/
```

## Hard constraints

1. **One concern per run.** Change exactly one thing: one data source or filter,
   one mixture weight, one hyperparameter group, one training-stage tweak, *or*
   one harness bug. Never bundle changes, and never touch both models in one run.
2. **`evals/*/frozen/` is read-only.** Don't edit it, re-sample it, train on it,
   or paraphrase it into training data. Never change a threshold, tolerance or
   pin to make a check pass. If an eval looks wrong, open an issue and stop.
3. **Baseline first.** Read `baseline.json` before choosing work.
4. **Propose, don't promote.** You open at most one PR. Only `make gate` in CI
   promotes a model, and the maintainer merges.
5. **Don't repeat declined work.** Check `experiments/ledger.jsonl` and this
   workflow's recently closed PRs. Don't re-propose a change that's already
   there unless you bring new evidence, and say what that evidence is.
6. **Budget caps** live in `models/<id>/config.yaml` (GPU-hours per run, per day,
   per week). If a job would go over a cap, don't submit it; report instead.
   Never shrink an eval to save budget.
7. **No new toolchains.** Use the pinned Python environment (`requirements.lock`).
   New dependencies go in their own PR that does nothing else.
8. **Noise is not signal.** Compare over ≥3 seeds and report mean ± std. Any
   difference inside the noise margin counts as "no change".
9. **Secrets and data.** Never print tokens, and never commit weights (they go to
   the artifact store). Never put customer logistics data or production logs into
   `data/` unless they've been through `scripts/scrub.py`.
10. **DOUG-A safety.** A proposed fix is only ever run inside the eval sandbox.
    The model's outputs are never executed against real infrastructure in this repo.

## Promotion gate (`scripts/gate.py`, run by CI)

A challenger becomes champion only if **all** of these hold:

- Primary metric beats the champion by more than `noise_margin`.
- No guarded metric regresses beyond its `tolerance`.
- `make contamination` is clean.
- `scripts/sign_receipt.py` produces a compact JWS (Ed25519) over:
  `{model_id, base_revision, adapter_sha256, recipe_sha256, frozen_eval_sha256, scores, seeds, timestamp}`.
  The receipt is appended to `registry/<id>.jsonl` and can be verified with the
  public key in `registry/verification_key.pub`.

Every quarter the maintainer adds a new held-out slice to `evals/<id>/frozen/` and
re-scores the champion, so the loop can't overfit to one fixed test.

## Per-model metrics

**DOUG-A**
- Primary: `fix_rate`, the share of sandboxed incidents where the proposed patch
  makes the failing check pass.
- Guarded: `root_cause_accuracy`, `no_destructive_commands` (must stay at 100%),
  `format_valid`, `false_fix_rate` (the patch passes but the root cause is wrong).
- Seed data: this org's `code-improvement` history (baseline → fix → green),
  public CI-failure datasets, and synthetic incidents from `harness/inject.py`.

**DOUG-L**
- Primary: `task_success`, i.e. extraction fields exactly correct AND the plan
  passes every constraint (capacity, time windows, legal hours).
- Guarded: `solver_call_validity`, `cost_gap_vs_solver` (must not grow),
  `hallucinated_field_rate`, `explanation_grounded`.
- The model never does optimization math itself. It calls the solver tool and explains the result.
- Seed data: public shipping documents, synthetic orders, and partner data after scrubbing.

## Run protocol (what each scheduled run does)

1. Read `baseline.json`, the ledger, and the last 10 closed PRs from this workflow.
2. Pick **one** model and **one** concern. Write the hypothesis in one sentence.
3. If a GPU job from an earlier run has finished, evaluate it, append the result to the ledger,
   and open the PR if it looks promising. That counts as this run's concern.
4. Otherwise, make the change, run `make check`, submit `make train`, and record the job id
   with your hypothesis in the ledger. Then stop. A later run picks up the result.
5. The PR body must include: the hypothesis, the diff summary, champion vs challenger
   scores (mean ± std over ≥3 seeds), the contamination result, and the ledger entry.
