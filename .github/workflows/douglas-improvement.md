---
name: douglas-improvement
description: Improve a DOUGLAS model by one measured, single-concern change per run
intent: >-
  Keep each DOUGLAS champion (DOUG-A, DOUG-L) improving on its frozen eval
  suite without ever regressing, with every promotion backed by a signed,
  verifiable receipt.
on:
  schedule: daily on weekdays
  push:
    branches: [main]
  skip-if-match: 'is:issue is:open "gh-aw-workflow-id: douglas-improvement" in:body'
  steps:
    - name: Skip scheduled runs when too many workflow PRs are open
      id: pr_pressure
      env:
        GH_TOKEN: ${{ github.token }}
        EVENT_NAME: ${{ github.event_name }}
      run: |
        set -uo pipefail
        if [ "$EVENT_NAME" != "schedule" ]; then exit 0; fi
        n=$(gh pr list --repo "$GITHUB_REPOSITORY" --state open --limit 100 \
              --json title --jq '[.[] | select(.title | startswith("douglas-improvement:"))] | length')
        echo "open douglas-improvement PRs: $n (ceiling 2)"
        [ "$n" -lt 2 ]
    - name: Announce a skip so a green run is never mistaken for a pass
      env:
        GH_TOKEN: ${{ github.token }}
      run: |
        set -uo pipefail
        n=$(gh issue list --repo "$GITHUB_REPOSITORY" --state open --limit 100 \
              --search '"gh-aw-workflow-id: douglas-improvement" in:body' \
              --json number --jq 'length' 2>/dev/null || echo 0)
        case "$n" in ''|*[!0-9]*) n=0 ;; esac
        if [ "$n" -gt 0 ]; then
          echo "## Skipped — no work performed. Close the marker issue to unblock." >> "$GITHUB_STEP_SUMMARY"
          echo "::warning title=Skipped, no work performed::Open marker issue blocked this run."
        fi
if: needs.pre_activation.outputs.pr_pressure_result == 'success'
permissions:
  contents: read
  issues: read
  pull-requests: read
engine: claude
model: claude-sonnet-5
tools:
  bash: true
  github:
    mode: gh-proxy
    toolsets: [default]
  cache-memory: true
network:
  allowed:
    - defaults
    - python
    - huggingface.co
    - "*.huggingface.co"
steps:
  - name: Set up Python
    uses: actions/setup-python@v7
    with:
      python-version: "3.12"
      cache: pip
  - name: Install pinned environment
    run: pip install -r requirements.lock
  - name: Record baseline
    env:
      HF_TOKEN: ${{ secrets.HF_TOKEN }}
    run: |
      set -uo pipefail
      mkdir -p /tmp/gh-aw/agent
      {
        echo "## make check"; make check 2>&1 | tail -40; echo "check_exit=${PIPESTATUS[0]}"
        for m in doug-a doug-l; do
          echo "## champion scores: $m"; cat "registry/$m.champion.scores.json" 2>/dev/null || echo "none yet"
          echo "## pending jobs: $m"; python scripts/pending_jobs.py --model "$m" --refresh
        done
        echo "## budget used today"; python scripts/budget.py --today
      } | tee /tmp/gh-aw/agent/baseline.txt
      python scripts/baseline_json.py > /tmp/gh-aw/agent/baseline.json
safe-outputs:
  create-pull-request:
    max: 1
    expires: 7
    protected-files: fallback-to-issue   # evals/*/frozen/**, scripts/gate.py, thresholds
  push-to-pull-request-branch:
  threat-detection:
    continue-on-error: false
    retries: 2
concurrency:
  group: douglas-improvement-${{ github.ref }}
  cancel-in-progress: false
timeout-minutes: 30
evals:
  - id: evidence
    question: >-
      Does the output include real command output comparing challenger and
      champion on the frozen eval, as mean ± std over at least 3 seeds?
  - id: single_concern
    question: >-
      Did the change touch exactly one model and one concern, with no
      unrelated modifications?
  - id: no_repeat
    question: >-
      Were experiments/ledger.jsonl and recently closed PRs from this workflow
      inspected, and is the proposed change absent from them (or justified
      with stated new evidence)?
  - id: frozen_untouched
    question: >-
      Were evals/*/frozen/, thresholds, tolerances, and scripts/gate.py left
      unmodified?
  - id: budget_respected
    question: >-
      Did any submitted GPU job stay within the caps in models/<id>/config.yaml?
---

# DOUGLAS Improvement

## Intent

DOUGLAS is a family of fine-tuned open-weight models: **DOUG-A** (DevOps) and
**DOUG-L** (logistics). This workflow exists for one guarantee: each champion
improves on its frozen eval suite without ever regressing, and every promotion
carries a signed receipt. Every run works on that single outcome.

Read `AGENTS.md` first. Its hard constraints are binding.

## Baseline (read this first)

`/tmp/gh-aw/agent/baseline.txt` and `baseline.json` hold the `make check` result, each
champion's scores, any pending or finished GPU jobs, and today's budget use.

- If `make check` is **red**, that's your concern for this run: fix the harness or
  code, and touch no training settings. Re-run with `-count`-style repeats
  (`make check REPEAT=3`) first. If it passes on a later attempt without any
  change, it's **flaky**: open an issue naming the flaky test instead of
  "fixing" it.
- If a **GPU job has finished**, evaluate it (`make eval ... SEEDS=3`), append the
  result to the ledger, and open a PR if it clears the noise margin. That counts as this run's concern.
- If a job is still **running**, don't submit another one for that model.
- Otherwise, pick **one** model and **one** recipe or hyperparameter change, run `make check`,
  submit `make train`, and record the job id and your one-sentence hypothesis in the ledger.

## Choosing the concern

Prefer, in order:
1. A failing check.
2. A finished job awaiting evaluation.
3. The largest **guarded-metric weakness** or failure cluster in the champion's
   latest eval report (`results/<champion>/failures.md`).
4. A data-quality fix: deduplication, a filter, rebalancing the mixture toward the failure cluster.
5. A single hyperparameter group (learning rate/schedule, LoRA rank/alpha, epochs, DPO beta).

Alternate between the models when nothing in 1–3 applies, so neither one stalls.

## Output

One PR titled `douglas-improvement: <model> — <concern>`, whose body contains the hypothesis, the diff
summary, the score table (champion vs challenger, mean ± std, ≥3 seeds), the
contamination result, and the ledger entry. If nothing is worth proposing, write a
short summary of what you checked, with no PR.
