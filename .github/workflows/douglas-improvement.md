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
  # Block on a deliberate marker issue only. gh-aw's own failure reports carry the
  # same marker and the `agentic-workflows` label; matching those would deadlock
  # every later run behind the issue it just opened.
  skip-if-match: 'is:issue is:open "gh-aw-workflow-id: douglas-improvement" in:body -label:agentic-workflows'
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
              --search '"gh-aw-workflow-id: douglas-improvement" in:body -label:agentic-workflows' \
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
model: claude-haiku-4-5
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
  - name: Wait for the pinned release assets
    env:
      CDN_WAIT_MINUTES: "15"
    run: |
      # github.com/<org>/<repo>/releases/download/... has returned 504s for
      # extended windows, which fails the AWF install before the agent starts.
      # Poll the two pinned assets the generated install steps need so a
      # transient CDN outage delays the run instead of killing it.
      set -uo pipefail
      lock=.github/workflows/douglas-improvement.lock.yml
      awf=$(grep -oE 'install_awf_binary\.sh" v[0-9]+\.[0-9]+\.[0-9]+' "$lock" | awk '{print $2}' | head -1)
      detect=$(grep -oE 'install_threat_detect_binary\.sh" v[0-9]+\.[0-9]+\.[0-9]+' "$lock" | awk '{print $2}' | head -1)
      urls=(
        "https://github.com/github/gh-aw-firewall/releases/download/${awf}/checksums.txt"
        "https://github.com/github/gh-aw-firewall/releases/download/${awf}/awf-bundle.js"
        "https://github.com/github/gh-aw-threat-detection/releases/download/${detect}/threat-detect-linux-amd64"
      )
      deadline=$(( $(date +%s) + CDN_WAIT_MINUTES * 60 ))
      attempt=0
      while :; do
        attempt=$((attempt + 1))
        missing=()
        for u in "${urls[@]}"; do
          code=$(curl -sSL -o /dev/null -w '%{http_code}' --max-time 20 "$u" || echo 000)
          [ "$code" = "200" ] || missing+=("$code $u")
        done
        if [ "${#missing[@]}" -eq 0 ]; then
          echo "release assets reachable after ${attempt} attempt(s)"
          exit 0
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
          printf 'release CDN still failing after %s minutes:\n' "$CDN_WAIT_MINUTES"
          printf '  %s\n' "${missing[@]}"
          echo "::error title=GitHub release CDN unavailable::Pinned install assets never returned 200. Re-run once github.com release downloads recover; no repository change is needed."
          exit 1
        fi
        echo "attempt ${attempt}: ${missing[*]}"
        sleep 20
      done
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
          echo "## pending jobs: $m"; python -m scripts.pending_jobs --model "$m" --refresh
        done
        echo "## budget used today"; python -m scripts.budget --today
      } | tee /tmp/gh-aw/agent/baseline.txt
      python -m scripts.baseline_json > /tmp/gh-aw/agent/baseline.json
safe-outputs:
  create-pull-request:
    max: 1
    expires: 7
    if-no-changes: "error"       # a submission run must carry its ledger plan entry
    preserve-branch-name: true   # the submit job needs the exact branch name
    protected-files: fallback-to-issue   # evals/*/frozen/**, scripts/gate.py, thresholds
  push-to-pull-request-branch:
  jobs:
    submit-training:
      description: >-
        Submit exactly one Hugging Face GPU training job for the change already
        committed on this run's pull-request branch. Call this after
        create-pull-request, passing that same branch name. The job holds
        HF_TOKEN (the agent never does), enforces the budget caps, appends the
        job to experiments/ledger.jsonl, and pushes that commit back to the
        branch. It fails if any cap in models/<id>/config.yaml would be exceeded.
      runs-on: ubuntu-latest
      needs: safe_outputs
      if: needs.safe_outputs.result == 'success'
      permissions:
        contents: write
        pull-requests: read
      output: "Training job submitted; the pull-request branch records the job id in experiments/ledger.jsonl."
      env:
        HF_TOKEN: ${{ secrets.HF_TOKEN }}
      inputs:
        model:
          description: "Model to train"
          required: true
          type: choice
          options: ["doug-a", "doug-l"]
        stage:
          description: "Training stage"
          required: false
          type: choice
          options: ["sft", "dpo"]
          default: "sft"
        branch:
          description: "Exact pull-request branch name passed to create-pull-request in this run"
          required: true
          type: string
        hypothesis:
          description: "One-sentence hypothesis for this run"
          required: true
          type: string
        concern:
          description: "The one concern changed, for example recipe:data-filter"
          required: true
          type: string
      steps:
        - uses: actions/checkout@v7
          with:
            fetch-depth: 1
        - uses: actions/setup-python@v7
          with:
            python-version: "3.12"
            cache: pip
        - name: Install pinned environment
          run: pip install -r requirements.lock
        - name: Submit the job and record it on the PR branch
          run: |
            set -euo pipefail
            test -f "${GH_AW_AGENT_OUTPUT:-}" || { echo "no agent output"; exit 1; }
            mapfile -t items < <(jq -c '.items[] | select(.type == "submit_training")' "$GH_AW_AGENT_OUTPUT")
            [ "${#items[@]}" -eq 1 ] || { echo "expected exactly one submit_training item, got ${#items[@]}"; exit 1; }
            item="${items[0]}"
            model=$(jq -r '.model // empty' <<<"$item")
            stage=$(jq -r '.stage // "sft"' <<<"$item")
            branch=$(jq -r '.branch // empty' <<<"$item")
            hypothesis=$(jq -r '.hypothesis // empty' <<<"$item")
            concern=$(jq -r '.concern // empty' <<<"$item")
            for v in model branch hypothesis concern; do
              [ -n "${!v}" ] || { echo "$v is required"; exit 1; }
            done
            case "$branch" in douglas/*) ;; *) echo "branch must start with douglas/"; exit 1 ;; esac
            git fetch --depth 1 origin "$branch"
            git checkout --detach FETCH_HEAD
            python -m scripts.submit_job \
              --model "$model" --stage "$stage" \
              --hypothesis "$hypothesis" --concern "$concern"
            if git diff --quiet -- experiments/ledger.jsonl; then
              echo "no ledger change to push"
              exit 0
            fi
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add experiments/ledger.jsonl
            git commit -m "chore(ledger): record $model $stage job submission"
            git push origin "HEAD:refs/heads/$branch"
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
  open the pull request on a `douglas/...` branch, and submit the training job with the
  `submit-training` tool (see below).

## Choosing the concern

Prefer, in order:
1. A failing check.
2. A finished job awaiting evaluation.
3. The largest **guarded-metric weakness** or failure cluster in the champion's
   latest eval report (`results/<champion>/failures.md`).
4. A data-quality fix: deduplication, a filter, rebalancing the mixture toward the failure cluster.
5. A single hyperparameter group (learning rate/schedule, LoRA rank/alpha, epochs, DPO beta).

Alternate between the models when nothing in 1–3 applies, so neither one stalls.

## Submitting a training job

You **do not have `HF_TOKEN`** and must never try to read, print or set it. Running
`make train` in your container will fail. Submission happens through the
`submit-training` safe-output tool, which runs after you finish with the token,
the budget check and the ledger commit.

1. Append a `kind: plan` entry to `experiments/ledger.jsonl` with `model`,
   `concern`, `hypothesis`, `commit` (if known) and `ts`. This is the run's
   bookkeeping record and guarantees the branch is non-empty even on the
   first, baseline run where no recipe change is justified.
2. Commit that entry plus the single-concern change (if any) on a new branch
   named `douglas/<model>-<short-concern>-<YYYYMMDD>`.
3. Call `create-pull-request` once with that exact `branch` value and the PR body
   described under **Output**. Branch names are preserved, and an empty diff is
   an error, so collisions or a missing plan entry fail loudly.
4. Call `submit-training` **once** with `model`, `stage` (`sft`, or `dpo` when a
   SFT adapter already exists), the same `branch`, a one-sentence `hypothesis`,
   and `concern`.

Do not call `submit-training` when a job for that model is pending or running, and
do not call it unless you opened the PR in the same run. If the budget caps in
`models/<id>/config.yaml` refuse the job, the tool fails and reports why; do not
retry with a different flavor or a smaller eval.

## Output

One PR titled `douglas-improvement: <model> — <concern>`, whose body contains the hypothesis, the diff
summary, the score table (champion vs challenger, mean ± std, ≥3 seeds), the
contamination result, and the ledger entry. If nothing is worth proposing, write a
short summary of what you checked, with no PR.
