# DOUGLAS architecture

Date: 2026-11-07
Status: bootstrap scaffold

## 1. Purpose and invariants

DOUGLAS improves two fine-tuned open-weight models without ever regressing on a
frozen suite. The invariants are the ones in `AGENTS.md`:

1. One model and one concern per run.
2. `evals/*/frozen/` is immutable; thresholds, tolerances and base pins are
   protected.
3. The baseline is read before work is chosen.
4. Agents propose; the CI gate promotes; the maintainer merges.
5. Declined work is not repeated without new evidence.
6. Budget caps are enforced before submission.
7. The pinned environment is the only toolchain.
8. Noise is not signal: at least three seeds, mean ± std.
9. Secrets stay out of logs; data is scrubbed.
10. DOUG-A patches are only executed inside the eval sandbox.

## 2. Data flow

```
data/<id>/seed + data/<id>/synthetic
        │
        ▼
models/<id>/recipe.yaml ──► scripts/submit_job.py ──► HF Job
        │                                              │  QLoRA SFT
        │                                              ▼  then DPO
        │                                        Hub adapter
        │                                              │
        ▼                                              ▼
scripts/contamination.py ◄── compare ──► scripts/eval.py ──► results/<run>/scores.json
        │                                                        │
        └──────────────► scripts/gate.py ◄───────────────────────┘
                              │
                              ├─ sign JWS (Ed25519)
                              ├─ append registry/<id>.jsonl
                              └─ update baseline.json
```

## 3. Frozen evaluation sets

`evals/<id>/frozen/manifest.json` records the SHA-256 of every frozen file.
`scripts/common.verify_frozen_manifest` fails if a file is modified, removed or
added, and `frozen_sha256` feeds the signed receipt.

### DOUG-A

Each incident is a directory with `meta.json`, a broken `repo/`, and `gold/`
containing the fixed files. The harness copies the repo to a temporary
directory, proves the check fails, applies the model's unified diff, and re-runs
the check. Paths outside `allowed_paths` invalidate the fix. Commands are
scanned against a destructive denylist.

### DOUG-L

Items are JSONL records with documents, the expected extraction, and a fleet.
The model returns extraction + a `plan_route` call + a plan + an explanation.
The harness re-runs the deterministic solver, checks capacity, availability,
driving hours and due time, and compares cost. The model never does the
optimisation arithmetic itself.

## 4. Gate arithmetic

Let `c` and `b` be the challenger and champion means for the primary metric, and
`σc`, `σb` their standard deviations across seeds. Promotion requires:

```
c - b > max(noise_margin, σc + σb)
```

For each guarded metric with direction `higher`:

```
c >= b - tolerance        (and c >= floor when a floor exists)
```

With direction `lower`:

```
c <= b + tolerance
```

When no champion exists, the bootstrap rule requires the primary metric to clear
`bootstrap_min_primary`, perfect safety floors, and clean contamination.

## 5. Receipts

`scripts/sign_receipt.py` emits a compact JWS with `alg=EdDSA`, canonical JSON
payload, and base64url with no padding. The payload is exactly:

```
{model_id, base_revision, adapter_sha256, recipe_sha256,
 frozen_eval_sha256, scores, seeds, timestamp}
```

The private seed lives outside the repository; the public key is committed at
`registry/verification_key.pub`.

## 6. Deterministic guards

| Script | Constraint | Behaviour |
|---|---|---|
| `scripts/scope.py` | one model, one concern | rejects mixed models or concern categories, ignores bookkeeping paths |
| `scripts/protect.py` | frozen/thresholds/pins | rejects protected paths and changes to `base`, `budget`, `metrics` in config |
| `scripts/contamination.py` | no leakage | 13-gram containment plus hashed-embedding cosine |
| `scripts/budget.py` | caps | per-run/day/week GPU-hour accounting from the ledger |
| `scripts/scrub.py` | no raw customer data | deterministic PII redaction; review still required |

## 7. Failure handling

- Red `make check`: fix the harness or code, never training settings. If a rerun
  passes with no change, open an issue naming the flaky test.
- Finished job: evaluate with ≥3 seeds, append to the ledger, and only open a PR
  if the primary clears the noise margin.
- Running job: do not submit another for that model.
- Missing credentials: stop and report; never fabricate a score.

## 8. Expanding the frozen suite

Each quarter the maintainer:

1. Creates a new held-out slice from fresh, independently sourced material.
2. Writes the slice and updates `manifest.json` (never edits old items).
3. Re-scores the current champion against the new frozen hash.
4. Runs `make contamination` for both models and `make check`.
5. Announces the new baseline; the next challenger must beat it.

Frozen slices must never be copied, paraphrased or resampled into `data/`.
