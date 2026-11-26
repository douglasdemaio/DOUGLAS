# DOUGLAS

**Daily Optimized, Unsupervised Growth via Learning And Scoring**

DOUGLAS is now a compact research/eval repository for H3-DO. The retained
harness studies the open-weight **Pika H3 Flex** adapters on top of MiniMax H3
with deterministic offline fixtures and an opt-in endpoint adapter.

Pika H3 Flex is a post-trained MiniMax H3 adapter pair, not a standalone
checkpoint. This repo records the pinned Pika revision and the FL2VA/Ref2VA
adapter paths, but it does not download weights, run generation, train, or
promote anything.

## Quickstart

```bash
make setup
make check
make h3do-eval SEEDS=3
```

`make check` runs lint and the offline unit tests with the pinned CPU
environment. It never calls a hosted endpoint.

## Active research target

| Field | Value |
|---|---|
| Adapter repo | `Pika-Labs/Pika-H3-Flex` |
| Pinned revision | `ca45d99f9b1d1859ffb9dc1cd6bfaaa994257f56` |
| Upstream base | `MiniMaxAI/MiniMax-H3` |
| Tasks | FL2VA (text/frame-to-video-audio), Ref2VA (reference-to-video-audio) |
| Training | None; research/eval only |

The config lives at `evals/h3do/config.yaml`. Scores write the config hash and
pinned revision into `scores.json`, so a run can be tied back to the exact
research target.

## Repository map

```
evals/h3do/config.yaml          pinned Pika H3 Flex research target
evals/h3do/research/            manifest, prompts, numeric fixture
evals/h3do/tools/               scoring, reporting, endpoint adapter
scripts/common.py               generic JSON/YAML/hash helpers
tests/test_h3do_eval.py         offline harness tests
AGENTS.md                       standing constraints for agents
```

## Endpoint runs

The scored offline path uses the committed numeric fixture. An endpoint run is
explicit and is never part of `make check`:

```bash
H3DO_ENDPOINT_URL="https://example.hf.space/predict" \
make h3do-endpoint-eval SEEDS=3
```

The token is read from `H3DO_ENDPOINT_TOKEN` or `HF_TOKEN`. With
`--require-token`, a missing token fails before any request is sent. Tokens are
never printed or stored in result directories, and endpoint URLs must be
absolute HTTPS URLs without embedded credentials, query strings, or fragments.

## Evaluation contract

- `evals/h3do/research/eval_manifest.json` defines item IDs, prompts, seeds, and
  tolerances.
- `evals/h3do/research/synthetic_predictions.jsonl` is a small numeric feature
  trace fixture. It contains no video bytes, model weights, or customer data.
- `baseline.py` scores replay or endpoint predictions and writes `scores.json`
  and `report.md` under the chosen output directory.
- Results are research measurements, not promotion evidence. There is no
  champion, gate, or signed receipt.

## Scope boundary

The previous model tracks have been retired. Their models, data, frozen evals,
training scripts, promotion gate, improvement workflow, ledger, and receipts
have been removed. Do not reintroduce model-track files or automation here.

H3-DO remains research/eval only. No training job is submitted, no hosted model
is called by tests, and no promotion or signing path exists.
