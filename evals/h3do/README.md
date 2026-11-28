# H3-DO research/eval harness

This directory is the offline research harness for H3-DO. Its active target is
the pinned open-weight `Pika-Labs/Pika-H3-Flex` adapter pair on top of MiniMax
H3. Pika H3 Flex is a post-trained H3 model, not a standalone checkpoint.

This harness is research/eval only. It does not download weights, submit
training, promote a model, or sign receipts. It never calls a hosted endpoint
during tests.

## Scope

- Baseline measurement using the committed numeric fixture.
- No training job, hosted generation call, or promotion path.
- No new dependencies; the pinned Python environment is used.
- No model weights, generated videos, customer data, or secrets are committed.

## Files

- `config.yaml` — pinned Pika H3 Flex revision, adapter paths, upstream MiniMax
  H3 base, and research profile.
- `research/eval_manifest.json` — pinned Pika adapter identity, upstream base,
  item IDs, prompts, seeds, duration, and tolerance settings.
- `research/prompts.jsonl` — authored text prompts.
- `research/synthetic_predictions.jsonl` — numeric fixture used by tests and
  the offline smoke command. It contains no generated media.
- `tools/baseline.py` — CLI that scores predictions and writes a run.
- `tools/quality_metrics.py` — deterministic visual-quality scoring.
- `tools/speed_metrics.py` — latency, GPU time, VRAM, and throughput scoring.
- `tools/report.py` — aggregation and Markdown reporting.

## Manifest identity

The manifest records the same pinned target as `config.yaml`:

- `model`: `pika-h3-flex`
- `adapter_repo` / `adapter_revision`: the pinned Pika H3 Flex repository and
  revision
- `task_adapters`: the FL2VA adapter for `t2va` items and the Ref2VA adapter
  for `ref2va` items
- `upstream_base_repo` / `upstream_base_revision`: the pinned MiniMax H3 base

This metadata is descriptive only. It does not download weights or change the
offline scoring path.

## Task slices

The manifest has four offline `t2va` items using the FL2VA adapter and two
`ref2va` items using the Ref2VA adapter. Reference inputs are ID+type
placeholders such as `{"id": "ref-img-005", "type": "image"}`; no media bytes or
URLs are committed.

`scores.json` keeps the existing overall `metrics` and also writes
`metrics_by_task`, so FL2VA and Ref2VA results can be read separately. The
Markdown report includes the same per-task table.

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
precomputed prompt/frame similarity in `[0, 1]`. The harness never executes,
fetches, or decodes anything from a prediction record.

## Offline smoke command

```bash
make h3do-eval SEEDS=3
```

or directly:

```bash
.venv/bin/python -m evals.h3do.tools.baseline \
  --seeds 3 \
  --out results/h3do-baseline-smoke
```

This writes `scores.json` and `report.md` under the output directory. The smoke
run uses the committed numeric fixture; it does not call a model endpoint.
`scores.json` records `model: pika-h3-flex` and the pinned Pika revision.

## Endpoint adapter

The same CLI can call a configured endpoint that accepts a manifest item plus a
seed and returns the prediction contract. This is opt-in and is not used in
tests:

```bash
H3DO_ENDPOINT_URL="https://example.hf.space/predict" \
make h3do-endpoint-eval SEEDS=3
```

The token is read from `H3DO_ENDPOINT_TOKEN` or `HF_TOKEN`. With
`--require-token`, a missing token fails before any request is sent. The token
is never printed or stored in the run directory; `scores.json` records only the
environment variable name and a credential-free endpoint URL. Endpoint URLs
must be absolute `https` URLs without embedded credentials, query strings, or
fragments. If the endpoint reports `capability.backend_configured: false`, the
run fails closed before writing scores so a stub response cannot be mistaken for
model performance.
