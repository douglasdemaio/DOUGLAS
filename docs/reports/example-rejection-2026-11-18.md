<!-- Illustrative example of a system-generated rejection report. This is not
     an entry in reviews/rejections.jsonl; it shows the four-section format the
     agent must produce for every rejected change. See the design doc at
     docs/specs/2026-11-18-testing-review-system-design.md. -->

# Rejection 20261118T091500Z-4c1f8a2e

- model: `doug-a`
- run: `doug-a-two-seed-noise-20261118`
- diff sha256: `9d3a7c1b6e4f2a08d5b7c9e1f3a6d8b0c2e4f6a8d0b2c4e6f8a0d2c4e6f8a0b2c`
- timestamp: `2026-11-18T09:15:00Z`
- addresses: `none (first submission)`

## What failed

- **seed count**: 2 seeds ([11, 29]); a minimum of 3 is required.
- **primary_metric**: `fix_rate` challenger 0.885 (seed 11 = 0.890, seed 29 = 0.880) vs champion 0.875. Delta +0.010 is inside the noise margin 0.020 (required: delta > 0.020). mean ± std = 0.885 ± 0.005.
- **per-seed results**: `fix_rate` has 2 values for 2 seeds, but the gate requires ≥3 seeded values to compute mean ± std.

## Why it matters

- Fewer than three seeds cannot distinguish a real gain from run-to-run noise; a two-seed "win" is not evidence of improvement.
- A `fix_rate` delta inside the noise margin counts as "no change" under the repo protocol. Promoting it would replace a champion with an indistinguishable model and burn a promotion slot.
- Missing per-seed values make the noise margin meaningless and can hide a fabricated or cherry-picked metric.

## What would make it acceptable

- Re-evaluate the same diff with `make eval MODEL=doug-a CKPT=challenger SEEDS=3` and report mean ± std over all three seeds.
- Show a `fix_rate` improvement greater than 0.020 over champion 0.875 (i.e. mean > 0.895) with no guarded-metric regression, then let `make gate` in CI decide promotion.
- Resubmit as a **new run** that names this report id in `--addresses`; an identical diff hash is blocked until it does.

## Root cause

the change was evaluated with only two seeds, so the apparent gain fell inside the noise margin
