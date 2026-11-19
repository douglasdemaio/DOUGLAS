# Rotating open-weight reasoner for the improvement loop

Date: 2026-11-19

## Status

Design approved; **no workflow implementation in this run**. This document replaces
the Anthropic reasoner in the scheduled improvement loop with a rotating
open-weight reasoner served through Hugging Face. It changes no training data,
recipe, base-model pin, frozen eval, threshold, gate, signing key or budget cap.
No GPU job is submitted, no model is promoted, and no pull request is opened.

## Goal and non-goals

**Goal.** Remove Anthropic from `douglas-improvement`, and let the loop's
*scheduled reasoning work* rotate across several open-weight models over time,
with each run's model recorded where other people can see it. The public value
is the record: over successive runs the ledger and PR bodies show which open
model proposed which change and whether it passed the gate.

**Non-goals.**

- Do not change DOUG-A or DOUG-L base models, recipes, champions, frozen evals,
  thresholds, tolerances, gate logic, receipts, or budget caps.
- Do not create a new public dataset, trace archive, scoreboard, or periodic
  issue. Ledger entries and PR bodies are the only new record.
- Do not add a Python dependency or alter `requirements.lock`.
- Do not let the reasoner choose its own successor model. Rotation is
  deterministic and independent of the agent.
- Do not put an API key in the repository, the prompt, or the agent's
  environment. The HF token stays in the trusted workflow environment.

## Scope and invariants (approved)

1. **One concern per run.** The gh-aw compiler upgrade and the reasoner switch
   are separate one-concern PRs in separate runs. Never bundle them, and never
   touch both models in one run.
2. **`evals/*/frozen/` stays read-only.** No re-sampling, paraphrasing, or
   threshold change to make a check pass.
3. **The gate still promotes.** Only CI's `make gate` promotes a champion, and
   the maintainer merges. The reasoner only proposes.
4. **No repeated work.** Check `experiments/ledger.jsonl` and recently closed
   PRs before proposing anything; record the model that made each proposal.
5. **Budgets unchanged.** Caps in `models/<id>/config.yaml` are authoritative.
   Never shrink an eval to save budget.
6. **Pi is the harness engine.** The reasoner runs under Pi, not Claude, against
   an OpenAI-compatible endpoint.
7. **No Anthropic anywhere in this workflow.** Reasoner and threat detector use
   open models; the one documented exception below concerns Copilot's eval
   judges, which are not Anthropic.

## Model pool — "Balanced 3"

| Rotation days | HF model ID | License | Rationale |
| --- | --- | --- | --- |
| Monday, Thursday | `openai/gpt-oss-120b` | Apache-2.0 | General open weight reasoner, first in the rotation. |
| Tuesday, Friday | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | Apache-2.0 | Code-specialised, useful for patch-oriented runs. |
| Wednesday | `deepseek-ai/DeepSeek-V3.2` | MIT | Third independent model family; midweek rotation. |

All three were observed on the HF router catalogue with tool calling, at low
per-run cost. A bare model name is **not** accepted by the router: live probes
returned HTTP 400 for `gpt-oss-120b`, `Qwen3-Coder-30B-A3B-Instruct` and
`DeepSeek-V3.2`, while the fully qualified IDs returned success. The workflow
must therefore preserve the `owner/name` part of every ID.

## Serving path

- Endpoint: `https://router.huggingface.co/v1` (Hugging Face Inference
  Providers). Billing stays on the existing HF account/Pro credits; this is the
  same account already used for training and jobs.
- Main engine: `engine: pi` with `model-provider: openai`,
  `OPENAI_BASE_URL: https://router.huggingface.co/v1`, and
  `OPENAI_API_KEY: ${{ secrets.HF_TOKEN }}`.
- The current `ANTHROPIC_API_KEY` reference is removed from this workflow's
  generated lock, and `engine: claude` / `model: claude-haiku-4-5` are removed
  from the source.
- `network.allowed` already contains `huggingface.co` and `*.huggingface.co`;
  keep those entries and add nothing else.
- Pi is preferred even though Codex has the better-documented custom endpoint
  path, because Pi keeps the whole agent harness on an open, auditable engine.

## Rotation

Replace the single `schedule: daily on weekdays` with five fuzzy weekday
schedules: `weekly on monday`, `weekly on tuesday`, `weekly on wednesday`,
`weekly on thursday`, `weekly on friday`. Fuzzy schedules keep the existing
load-spreading behaviour and compile to one fixed cron per weekday.

The model is selected from `github.event.schedule` in frontmatter, using the
day-of-week field of the compiled cron:

```
hf/${{ contains(github.event.schedule, ' * * 1') && 'openai/gpt-oss-120b' ||
      contains(github.event.schedule, ' * * 2') && 'Qwen/Qwen3-Coder-30B-A3B-Instruct' ||
      contains(github.event.schedule, ' * * 3') && 'deepseek-ai/DeepSeek-V3.2' ||
      contains(github.event.schedule, ' * * 4') && 'openai/gpt-oss-120b' ||
      contains(github.event.schedule, ' * * 5') && 'Qwen/Qwen3-Coder-30B-A3B-Instruct' ||
      'openai/gpt-oss-120b' }}
```

Manual (`workflow_dispatch`) and push runs have an empty `github.event.schedule`
and fall back to Monday's model. There is no mutable counter, repository
variable, or agent-chosen successor: the schedule alone decides. The `hf/`
prefix is a gh-aw custom-provider marker, not part of the HF model ID; the
compiled workflow forwards the nested `owner/name` value to the router.

A trusted "Record baseline" step writes the selected model into
`/tmp/gh-aw/agent/baseline.txt` (and the model expression into `baseline.json`
if needed) so the agent can copy the exact value into the ledger and PR body
without guessing.

## Threat detection and eval judges

- `safe-outputs.threat-detection` moves to the **Codex detector** pointed at the
  same HF endpoint and the same open model. A compile probe with
  `id: codex`, `model-provider: openai`, `model: hf/openai/gpt-oss-120b`, and the
  HF base URL/key compiled cleanly. Detection keeps `continue-on-error: false`
  and two retries; no safety boundary is weakened.
- The five existing `evals:` judges remain on Copilot/Decisions. This is the one
  accepted exception: gh-aw eval judges use a separate OpenAI-compatible
  Decisions endpoint, and the HF router returned HTTP 404 for both
  `/v1/decisions` and `/decisions` in live probes. The judges are not Anthropic
  and do not select training data or promote a model.
- Keep the current five eval questions unchanged. Do not disable or weaken an
  eval to make the migration easier.

## Reporting

- Add `reasoner_model` to every `experiments/ledger.jsonl` entry written by the
  loop (hypothesis/plan, job submission, evaluation, gate result). The field is
  additive; `scripts/common.py:append_ledger` does not enforce a fixed schema,
  so existing readers are unaffected.
- Include `reasoner_model` in each PR body, beside the existing hypothesis,
  diff summary, champion vs challenger mean ± std over ≥3 seeds, contamination
  result, and ledger entry.
- Do not publish a new artifact or issue. The rotation's ecosystem value is the
  per-model history in the ledger and PRs.

## Prerequisites and verification performed

- The repository's pinned `gh aw` is **v0.89.21**. It cannot compile nested
  model IDs: probes with `openai/gpt-oss-120b`, `hf/openai/gpt-oss-120b` and a
  nested OpenRouter-style ID all failed with
  `character '/' is not allowed in model token`. It also left dynamic custom
  models on the GitHub/Copilot provider path (`GH_AW_LLM_PROVIDER=github`,
  `GH_AW_PI_GATEWAY_SECRET_ENV=COPILOT_GITHUB_TOKEN`).
- A newer local build (`dev`, from gh-aw source commit `2394457`, 2026-11-18)
  compiled the nested ID and weekday expression cleanly. It emitted
  `GH_AW_PI_MODEL: hf/openai/gpt-oss-120b`, `GH_AW_PI_NATIVE_PROVIDER: hf`,
  `GH_AW_ENGINE_MODEL` with the full weekday expression, and correct five
  weekday crons. The Codex detector probe compiled cleanly too.
- **Runtime check still required before implementation:** confirm the emitted
  `hf/` marker is stripped to the full `owner/name` ID on the wire to
  `router.huggingface.co/v1`. A compile success is necessary but not sufficient.
- Therefore the upgrade of the gh-aw compiler/action pins is a **separate
  single-concern PR** in an earlier run. Only after it is merged does the
  reasoner switch get its own run.

## Acceptance checks for the later implementation PR

1. Recompiled `douglas-improvement.lock.yml` contains no `ANTHROPIC_API_KEY` and
   no `claude-haiku-4-5`.
2. The lock shows the Pi agent, HF base URL, `HF_TOKEN`, one open model per
   weekday, and the Codex detector on the same open model.
3. The five Copilot eval questions are byte-for-byte unchanged.
4. A one-run smoke check shows the router receives a fully qualified model ID
   (not a bare name) and a tool-capable response.
5. No protected file changes; no base-model, recipe, frozen-eval, gate or budget
   changes; ledger changes are only the additive `reasoner_model` field.
6. `make check` and `make contamination` remain green.

## Implementation sequence (future runs, after approval)

1. PR A (one concern): upgrade the gh-aw compiler/action pins to a version that
   accepts nested model IDs and custom providers. Recompile the lock; no model
   or prompt changes.
2. PR B (one concern, this design): switch the reasoner, detector, schedule,
   model expression, and reporting; recompile the lock; verify acceptance
   checks above. Stop before any training or promotion.
3. Later scheduled runs use the rotated models as normal and record
   `reasoner_model` in the ledger and PR bodies.
