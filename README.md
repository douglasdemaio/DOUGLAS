# DOUGLAS

**Daily Optimized, Unsupervised Growth via Learning And Scoring**

DOUGLAS is a family of fine-tuned open-weight models that improves itself through
a scheduled agent loop. Each run makes one measured, single-concern change to a
recipe or hyperparameter group, evaluates it on a frozen suite over at least three
seeds, and opens at most one PR. Only the promotion gate in CI can turn a
challenger into a champion, and every promotion carries a signed receipt.

| Model | Base | Job |
|---|---|---|
| DOUG-A | `Qwen/Qwen2.5-Coder-7B-Instruct` | Read logs, alerts and CI failures, find the root cause, propose a patch or runbook step. |
| DOUG-L | `Qwen/Qwen2.5-7B-Instruct` | Turn shipment documents into structured orders, call the solver, explain delays and options. |

Both start from a pinned open-weight base and are trained with QLoRA SFT followed
by DPO. Pretraining from scratch is out of scope.

## Quickstart

```bash
make setup          # .venv + requirements.lock
make check          # lint, unit tests, harness self-tests (CPU, hermetic)
make contamination MODEL=doug-a
make baseline
```

Training and evaluation use Hugging Face Jobs:

```bash
make train MODEL=doug-a                 # submits a job, records it in the ledger, does not block
make job-status JOB=<job-id>
make eval MODEL=doug-a CKPT=champion SEEDS=3
make gate MODEL=doug-a CHALLENGER=results/<run>   # CI does this; local use for inspection
```

`make train` refuses to submit when a job would exceed the caps in
`models/<id>/config.yaml`. It never runs model code outside the Jobs container.

## Repository map

```
models/<id>/config.yaml     base pin, LoRA, training, budget caps, metric thresholds
models/<id>/recipe.yaml     data sources, filters, mixture weights  <- the normal edit
data/<id>/                  versioned training data (never frozen eval items)
evals/<id>/frozen/          locked eval set; read-only, manifest hashed
evals/<id>/harness/         graders; DOUG-A sandboxes patches, DOUG-L calls the solver
experiments/ledger.jsonl    every job, eval, decision and promotion
registry/<id>.jsonl         signed promotion receipts
registry/verification_key.pub   Ed25519 public key
scripts/                    gate, signing, contamination, budget, eval, train
.github/workflows/douglas-improvement.md   the scheduled agent loop (gh-aw source)
```

## Secrets

| Secret | Used by | Purpose |
|---|---|---|
| `HF_TOKEN` | training jobs, `pending_jobs`, eval endpoints | HF Jobs submit, Hub push, job status |
| `ANTHROPIC_API_KEY` | `douglas-improvement` agent | Claude engine for the loop |
| `DOUGLAS_SIGNING_KEY` | promotion gate | base64 Ed25519 seed used to sign receipts |

Create the signing key once, keep the private half out of the repository:

```bash
python -m scripts.sign_receipt keygen \
  --priv ~/.config/douglas/signing_key \
  --pub registry/verification_key.pub
gh secret set DOUGLAS_SIGNING_KEY < ~/.config/douglas/signing_key
```

Verify any receipt:

```bash
python -m scripts.sign_receipt verify --receipt receipt.jws \
  --pub registry/verification_key.pub
```

## Evaluation contract

- Frozen sets are hashed in `evals/<id>/frozen/manifest.json`. `make check` and
  every eval verify the manifest; the promotion gate also checks that the
  challenger was scored against the current frozen hash.
- **DOUG-A** primary: `fix_rate`. Guarded: `root_cause_accuracy`,
  `no_destructive_commands` (floor 100%), `format_valid` (floor 90%),
  `false_fix_rate`.
- **DOUG-L** primary: `task_success`. Guarded: `solver_call_validity` (floor 100%),
  `cost_gap_vs_solver`, `hallucinated_field_rate`, `explanation_grounded`.
- A challenger is promoted only when the primary metric beats the champion by
  more than `max(noise_margin, challenger_std + champion_std)`, no guarded metric
  regresses past its tolerance, contamination is clean, and the receipt signs.

## Bootstrap notice

The frozen sets and seed data in this repository are small synthetic slices
created to make the loop executable end to end. Expand them deliberately with
the quarterly held-out slice process in
`docs/specs/2026-11-07-architecture.md`, and keep `make contamination` clean.

## The agent loop

`.github/workflows/douglas-improvement.md` is a GitHub Agentic Workflow (gh-aw).
Edit the Markdown, then recompile:

```bash
gh aw compile .github/workflows/douglas-improvement.md --approve
```

The compiled `douglas-improvement.lock.yml` is generated and must not be edited
by hand.
