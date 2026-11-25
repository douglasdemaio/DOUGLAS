# MiniMax H3-DO research/eval design

Date: 2026-11-25

## Status

Design approved; implementation not started. This record establishes what
"Daily Optimized" means for a MiniMax H3 track. It does not change DOUG-A,
DOUG-L, their champions, recipes, frozen evals, gates, budgets, or training
data. No GPU job is submitted and no Hugging Face repository is created in this
run.

## What changes conceptually

DOUGLAS currently consists of two text models:

- **DOUG-A** — DevOps Operator for Uptime, Guardrails, Logs, Alerts and
  Systems. It reads logs, alerts and CI failures, finds the root cause, and
  proposes a patch or runbook step.
- **DOUG-L** — Distribution Orchestrator for Unified Goods, Loads And
  Shipments. It turns shipment documents into structured orders, plans routes
  and loads by calling a solver, and explains delays and options.

This design adds a separate track:

> **H3-DO = MiniMax H3 — Daily Optimized**

Its purpose is to make open MiniMax H3-Base generations measurably better in
two areas:

1. **Visual quality** — semantic fidelity, motion quality, artifacts, and
   consistency.
2. **Speed/cost** — wall time, GPU time, VRAM peak, and successful generations
   per unit of compute.

This does not redefine the existing primary models or their promotion gates.
H3-DO gets its own baseline, eval harness, ledger namespace, model repository,
and Space. The previously approved open-reasoner rotation work is paused until
after this design is approved and can land later as its own single-concern PR.

## Hard constraints

- Do not edit `evals/*/frozen/**`.
- Do not change DOUG-A/L configs, recipes, champions, thresholds, budgets,
  gate, signing, or training data.
- No training in the first run. This is research/eval only.
- No new Python dependencies in the first run; use the pinned environment
  where possible.
- No secret values, tokens, customer data, or production logs in reports or
  files.
- Do not upload model weights in the first run.
- The public Space is an open demo only after eval and upload mechanics are
  proven; if that cannot be done safely in one change, the Space is a separate
  change.
- Rotate or retrain models only under the existing one-concern-per-run rule.

## What MiniMax H3 actually is

`MiniMaxAI/MiniMax-H3` is a 33B-parameter audio-video generation system:

- `FL2VA`: text-to-video and first-or-last-frame-to-video.
- `Ref2VA`: reference-to-video with images, video, and audio.
- Native output: 768p, 24 fps, 4–15 seconds, stereo audio.
- The H3-Context-IR preprocessor and H3-Regenerate-2K upscaler are hosted
  services and are not part of the open weights.
- The initial open release uses full attention; sparse attention is expected
  in a later release.
- Published serving examples use multiple GPUs; Hugging Face ZeroGPU has
  smaller per-request resources and a short duration budget.

Therefore "daily optimization" cannot assume LoRA over the whole system. The
first useful optimization is measurement: establish which parts can run under
HF hosting and which improvements are actually measurable.

## Staged changes

### PR 1 — design record

Commit this document. No code. This gives the maintainer a clear record of
what "Daily Optimized" means.

### PR 2 — local research harness, no training

Add a new top-level area such as `h3do/`:

- `h3do/README.md` — scope and operating instructions.
- `h3do/config.yaml` — pinned base repository/revision, task variant,
  benchmark profile, and budget metadata.
- `h3do/eval_manifest.json` — prompt/reference IDs, seeds, duration,
  resolution, and settings; frozen within this track.
- `h3do/prompts.jsonl` — authored prompts for objective visual-quality checks.
- `h3do/reference_images/` — small, license-cleared reference images, only if
  needed.
- `h3do/baseline.py` — runs a benchmark locally or against a configured
  endpoint and writes scores.
- `h3do/quality_metrics.py` — deterministic, low-cost visual metrics.
- `h3do/speed_metrics.py` — latency, GPU time where available, peak VRAM where
  available, and success rate.
- `h3do/report.py` — mean ± standard deviation over at least three seeds,
  Markdown/JSON report.
- `tests/test_h3do_eval.py` — manifest validation, deterministic scoring, and
  no-network self-tests.
- `experiments/ledger.jsonl` — one additive plan entry with `track: h3do`,
  `concern: research-eval-baseline`, and no training claim.

The initial manifest should use short, low-resolution generations to fit
research iteration. It must not call hosted MiniMax APIs; H3-Base is the thing
being studied.

### PR 3 — HF Space smoke test

Create a public Space under `douglasdemaio`, proposed name
`douglasdemaio/MiniMax-H3-DO-Demo`, after PR 2 passes.

The Space should:

- Load the pinned `MiniMaxAI/MiniMax-H3` checkpoint or a checkpoint mirrored
  under the account.
- Use ZeroGPU.
- Offer an open demo with arbitrary text prompts and optional first-frame
  input.
- Enforce short durations, low resolution, and a queue/timeout to avoid
  runaway cost.
- Display quality and speed metadata for each result.
- Never accept model weights or training jobs from users.
- Keep source and logs free of secrets.

If H3-Base cannot fit or reliably complete within ZeroGPU limits, PR 3 becomes
a documented blocker report instead of a Space, and a later decision chooses
between a paid GPU and a smaller proxy model.

### PR 4 — first optimization experiment

Only after PRs 2 and 3:

- Pick one concern: for example prompt/context representation, a LoRA target,
  sampler setting, or quantization.
- Record a hypothesis.
- Run at least three seeds.
- Report mean ± standard deviation for visual and speed metrics.
- Treat any difference inside the noise margin as no change.
- Never promote a new champion automatically; maintainer review is required.

## Evaluation design

### Visual quality

First-stage metrics must be objective and reproducible:

- `temporal_consistency` — frame-to-frame feature stability; lower sudden
  incoherence is better.
- `flicker` — short-window luminance or feature variance.
- `prompt_alignment` — similarity between prompt and sampled frames. If an
  already-pinned dependency is unavailable, use a simpler authored-rubric
  score with human review.
- `artifact_rate` — black frames, frozen frames, invalid frames, broken audio
  track.
- `audio_video_sync` — basic duration/channel validity; full sync scoring is
  deferred.

No metric becomes a promotion gate until it has been human-reviewed.

### Speed/cost

- `wall_seconds` — end-to-end generation time.
- `gpu_seconds` — where the runtime exposes it.
- `peak_vram_gb` — where available.
- `success_rate` — completed valid outputs divided by attempts.
- `output_seconds_per_gpu_second` — normalized throughput.

The benchmark pins model revision, prompt set, seeds, duration, resolution,
sampler settings, and hardware class.

### Study protocol

- Baseline first: run the unmodified pinned H3-Base checkpoint.
- At least three seeds per condition.
- Compare one change at a time.
- Publish mean ± standard deviation.
- Keep outputs small and out of the repository unless license-cleared.
- Record every attempt in `experiments/ledger.jsonl` under the same
  one-concern rule used by DOUG-A/L.

## Public model and Space

The final H3-DO repository under `douglasdemaio` should contain:

- A model card explaining H3-DO, its base revision, license inheritance, and
  limitations.
- The adapter/delta or merged weights only if the license permits and the
  maintainer approves.
- Eval reports with metric definitions and baseline comparisons.
- A clear statement that hosted H3-Context-IR and H3-Regenerate-2K are not
  included.
- Demo instructions and known failure modes.

The Space should be linked from the model card. Promotion to "champion" is
manual, not automatic.

## Explicitly deferred

- Fine-tuning or LoRA in the first run.
- Any change to DOUG-A/L.
- Any change to the CI gate or existing frozen evals.
- Any new shared dependency.
- 2K regeneration, because that module is hosted and not open.
- Full multimodal reference evaluation, because it is much broader than
  text/first-frame generation.
- Commercial or customer-data use.

## Acceptance criteria

1. Design was approved before implementation.
2. The research harness does not change DOUG-A/L, frozen evals, gates,
   budgets, or dependencies.
3. The baseline harness is deterministic and has offline self-tests.
4. Reports include at least three seeds and mean ± standard deviation.
5. No training is submitted in the research PR.
6. The Space PR either works as an open demo or reports a concrete ZeroGPU
   blocker.
7. No secrets, weights, customer data, or protected files are added.
