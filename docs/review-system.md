# Fail-closed review system

Every proposed change must pass the full review before it can be promoted. A
missing check, an unavailable gate, an unverifiable receipt or a write/network
outside the repo and artifact store stops the loop with exit code `2` — it is
never skipped. See `docs/specs/2026-11-18-testing-review-system-design.md` for
the requirement map and `docs/reports/example-rejection-2026-11-18.md` for a
sample rejection.

## Commands

```bash
make review MODEL=doug-a CHALLENGER=results/<run> BASE=origin/main \
  PREDICTIONS=results/<run>/predictions.jsonl   # run every check; write a report on rejection
make attestations              # verify every signed decision + linked gate receipt
make rollback MODEL=doug-a     # restore the previous signed champion; emits its own receipt
make policy MODEL=doug-a DIFF=<sha256>          # run cap, open-PR cap, cooldown, prior rejection
make rejections                # list rejection reports
```

## Guarantees

- The review re-runs `make check`, `make scope` and `make protect`, verifies the
  frozen manifest, refuses fewer than 3 seeds, re-grades `predictions.jsonl`
  from a committed run, and only then invokes the CI gate. It never writes to
  `registry/`, `baseline.json` or a champion file — only `scripts.gate` promotes.
- Each rejection appends a report with **What failed / Why it matters / What
  would make it acceptable / Root cause** to `docs/reviews/rejections.jsonl`
  and a Markdown copy under `docs/reviews/reports/`. Link the report from the
  PR. The same diff hash cannot be resubmitted until a new run names that report
  in `--addresses`.
- The agent cannot edit the gate, signing code, frozen sets, thresholds, keys
  or workflows — `make protect` enforces this. Only a human-reviewed PR can.
- Promotions carry a signed decision attestation (diff, per-seed results, gate
  decision, parent champion, gate receipt, timestamp). Rollback restores only a
  previously verified signed champion and signs its own receipt.
- At most one open PR, one run per day, and a 24-hour cooldown after a rejection
  or rollback are enforced by `docs/reviews/policy.json` and
  `docs/reviews/events.jsonl`.

## Artifacts

All review state is append-only and lives under `docs/reviews/`:

| File | Contents |
|---|---|
| `policy.json` | run caps, open-PR cap, cooldown hours |
| `events.jsonl` | `run`, `pr_open`, `pr_closed`, `rejection`, `rollback`, `network_allowed` |
| `rejections.jsonl` | machine-readable rejection reports |
| `reports/*.md` | human-readable rejection reports |
| `decisions.jsonl` | signed promotion and rollback attestations |
| `containment.jsonl` | logged write/network violations |

A missing or unreadable state file means "no run": the policy fails closed.
