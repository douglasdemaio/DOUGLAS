# AGENTS.md: DOUGLAS

Working notes for coding agents on this repository. These are standing
constraints, not suggestions.

## Project

DOUGLAS is now a research/eval repository for H3-DO. The retained harness studies
the open-weight `Pika-Labs/Pika-H3-Flex` adapters on top of MiniMax H3. It is
research/eval only: no training job, promotion, champion, or gate exists.

## Hard constraints

1. **Research/eval only.** Do not add training, promotion, signing, champion
   selection, or frozen-eval machinery. Do not submit jobs.
2. **One concern per run.** Change exactly one thing. Do not bundle unrelated
   harness edits.
3. **No hosted calls in tests.** Tests use the committed numeric fixture. Keep
   endpoint calls opt-in and outside tests.
4. **Secrets stay secret.** `H3DO_ENDPOINT_TOKEN` and `HF_TOKEN` are never
   printed or written into result directories. Use `--require-token` for real
   endpoint runs.
5. **Pinned environment.** Use `requirements.lock`. New dependencies require a
   separate PR that does nothing else.
6. **No weights or generated media.** Commit feature traces and scores only.
7. **Deterministic checks.** Run `make check` before proposing any change.

## Commands

```bash
make setup                 # .venv + requirements.lock
make check                 # lint + unit tests (CPU only, hermetic)
make h3do-eval SEEDS=3     # offline research baseline
make h3do-endpoint-eval    # opt-in endpoint call; requires H3DO_ENDPOINT_URL
```

## Layout

```
evals/h3do/config.yaml          pinned Pika H3 Flex research target
evals/h3do/research/            manifest, prompts, numeric fixture
evals/h3do/tools/               scoring, reporting, endpoint adapter
scripts/common.py               generic JSON/YAML/hash helpers
tests/test_h3do_eval.py         offline harness tests
```

## Change protocol

1. Read `evals/h3do/README.md` and `config.yaml` first.
2. Make one focused change.
3. Run `make check` and, when the change affects scoring, `make h3do-eval`.
4. Open at most one PR with the hypothesis, diff summary, and check results.

Never reintroduce the retired model-track files or automation.
