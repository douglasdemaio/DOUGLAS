# H3-DO research/eval harness

This directory is the offline research harness for the proposed H3-DO track:
**MiniMax H3 — Daily Optimized**. It is separate from DOUG-A and DOUG-L and
does not change their champions, frozen sets, recipes, gates, or budgets.

The harness lives under `evals/h3do/` because the repository's `scope`/`protect`
backstops already treat `evals/` as infrastructure and keep `evals/*/frozen/`
read-only. Nothing here is frozen and nothing here is a DOUG-A/L eval.

## Scope

- Baseline measurement only. No training job is submitted from this change.
- No hosted MiniMax APIs are called. The open H3-Base checkpoint is the thing
  being studied; hosted H3-Context-IR and H3-Regenerate-2K are out of scope.
- No new dependencies. The harness uses the pinned Python environment and the
  standard library.
- No model weights, generated videos, customer data, or secrets are committed.

## Files

- `config.yaml` — pinned base repository/revision and research profile.
- `research/eval_manifest.json` — item IDs, prompts, seeds, duration, and
  tolerance settings for this track.
- `research/prompts.jsonl` — authored text prompts.
- `research/synthetic_predictions.jsonl` — small numeric fixture used by tests
  and the offline smoke command. It contains no generated media.
- `tools/baseline.py` — CLI that scores predictions and writes a run.
- `tools/quality_metrics.py` — deterministic visual-quality scoring.
- `tools/speed_metrics.py` — latency, GPU time, VRAM, and throughput scoring.
- `tools/report.py` — aggregation and Markdown reporting.

## Prediction contract

One JSON object per line:

```json
{
  "id": "h3do-t2v-001",
  "seed": 1,
  "frames": [
    {"valid": true, "mean_luma": 0.40, "hash": "00000001"}
  ],
  "alignment": 0.78,
  "audio": {"valid": true, "duration_seconds": 4.0, "channels": 2, "sample_rate_hz": 32000},
  "timings": {"wall_seconds": 128.4, "gpu_seconds": 101.2, "peak_vram_gb": 20.4},
  "errors": []
}
```

`frames` is a compact feature trace, not video bytes. `alignment` is a
precomputed prompt/frame similarity in `[0, 1]`; a future change may compute it
from real sampled frames with an already-pinned dependency. The harness never
executes, fetches, or decodes anything from a prediction record.

## Offline smoke command

```bash
PYTHON=.venv/bin/python make h3do-eval
```

or directly:

```bash
.venv/bin/python -m evals.h3do.tools.baseline \
  --seeds 3 \
  --out results/h3do-baseline-smoke
```

This writes `scores.json` and `report.md` under the output directory. The smoke
run uses the committed numeric fixture; it does not call a model endpoint.

## Endpoint adapter

The same CLI can call an endpoint that accepts the manifest item plus a seed
and returns the prediction contract. Use `--require-token` for the real
backend-secret path:

```bash
H3DO_ENDPOINT_URL="https://example.hf.space/predict" \
make h3do-endpoint-eval SEEDS=3
```

or directly:

```bash
.venv/bin/python -m evals.h3do.tools.baseline \
  --engine endpoint \
  --endpoint-url "https://example.hf.space/predict" \
  --require-token \
  --seeds 3
```

The token is read from `H3DO_ENDPOINT_TOKEN` or `HF_TOKEN`. With
`--require-token`, a missing token fails before any request is sent. The token
is never printed or stored in the run directory; `scores.json` records only the
environment variable name and a credential-free endpoint URL. Endpoint URLs
must be absolute `https` URLs without embedded credentials, query strings, or
fragments. If the endpoint reports `capability.backend_configured: false`, the
run fails closed before writing scores so a stub response cannot be mistaken for
model performance. No endpoint call is made in tests.
