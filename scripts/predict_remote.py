"""Run inside a Hugging Face Job: answer the frozen eval set and score it.

    python3 -m scripts.predict_remote --model doug-l \
        --adapter douglasdemaio/douglas-doug-l --run doug-l-predict-20261109

Loads the pinned base plus the trained LoRA adapter, answers every frozen item
once, grades the answers through `scripts.eval` (hermetic, CPU only), and
uploads predictions.jsonl, scores.json and failures.md to the adapter repo
under `evals/<run>/`. The frozen set is only ever read.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from scripts.common import ROOT, load_config, utc_now
from scripts.eval import build_prompt, load_grader, parse_json_content

MAX_INPUT_TOKENS = 16000
MAX_NEW_TOKENS = {"doug-a": 1536, "doug-l": 1024}
RUN_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def load_model(config: dict, adapter: str):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    base = config["base"]["repo"]
    revision = config["base"]["revision"]
    tokenizer = AutoTokenizer.from_pretrained(base, revision=revision)
    # Keep the trailing instruction when a prompt is longer than the window.
    tokenizer.truncation_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        base,
        revision=revision,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer


def generate(model, tokenizer, prompt: dict, max_new_tokens: int) -> str:
    import torch

    messages = [
        {"role": "system", "content": prompt["system"]},
        {"role": "user", "content": prompt["user"]},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=MAX_INPUT_TOKENS).to(
        model.device
    )
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    completion = output[0][inputs["input_ids"].shape[1] :]
    return tokenizer.decode(completion, skip_special_tokens=True)


def predict_all(model, tokenizer, model_id: str, items: list, path: Path) -> int:
    parsed = 0
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            item_id = Path(item).name if model_id == "doug-a" else item["id"]
            prompt = build_prompt(model_id, item)
            raw = generate(model, tokenizer, prompt, MAX_NEW_TOKENS[model_id])
            record: dict = {"id": item_id}
            try:
                record["output"] = parse_json_content(raw)
                parsed += 1
            except Exception as exc:  # an unparsable answer scores zero, it is not fatal
                record["output"] = {}
                record["parse_error"] = str(exc)[:500]
                record["raw"] = raw[:2000]
            fh.write(json.dumps(record) + "\n")
            print(
                f"{item_id}: {'parsed' if 'parse_error' not in record else 'unparsed'}", flush=True
            )
    return parsed


def adapter_revision(adapter: str) -> str | None:
    try:
        from huggingface_hub import HfApi

        return HfApi().repo_info(adapter, repo_type="model").sha
    except Exception as exc:  # receipts can fall back to the predictions hash
        print(f"warning: cannot resolve adapter revision: {exc}", file=sys.stderr)
        return None


def upload_run(adapter: str, run: str, out_dir: Path, attempts: int = 4) -> None:
    from huggingface_hub import HfApi

    delay = 15
    for attempt in range(1, attempts + 1):
        try:
            HfApi().upload_folder(
                repo_id=adapter,
                repo_type="model",
                folder_path=str(out_dir),
                path_in_repo=f"evals/{run}",
                commit_message=f"eval: {run}",
            )
            return
        except Exception as exc:  # noqa: BLE001 - the Hub 429s under load
            if attempt == attempts:
                raise
            print(f"upload failed ({exc}); retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=["doug-a", "doug-l"])
    parser.add_argument("--adapter", required=True, help="Hub repo holding the LoRA adapter")
    parser.add_argument("--run", help="run name; defaults to <model>-predict-<timestamp>")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args(argv)

    run = args.run or f"{args.model}-predict-{utc_now().strftime('%Y%m%dT%H%M%SZ')}"
    if not RUN_RE.match(run):
        parser.error(f"invalid run name {run!r}")

    config = load_config(args.model)
    grader = load_grader(args.model)
    items = list(grader.list_items()) if args.model == "doug-a" else grader.list_items()
    if not items:
        print("no frozen items", file=sys.stderr)
        return 2

    out_dir = ROOT / "results" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = out_dir / "predictions.jsonl"

    print(
        json.dumps({"model": args.model, "adapter": args.adapter, "run": run, "items": len(items)})
    )
    model, tokenizer = load_model(config, args.adapter)
    parsed = predict_all(model, tokenizer, args.model, items, predictions_path)
    print(f"parsed {parsed}/{len(items)} predictions")

    if args.model == "doug-a" and importlib.util.find_spec("pytest") is None:
        # Without pytest every frozen check fails and every fix silently scores 0.
        print("pytest is missing; refusing to grade doug-a", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        "-m",
        "scripts.eval",
        "--model",
        args.model,
        "--ckpt",
        args.adapter.rsplit("/", 1)[-1],
        "--seeds",
        str(args.seeds),
        "--engine",
        "replay",
        "--predictions",
        str(predictions_path),
        "--run",
        run,
    ]
    revision = adapter_revision(args.adapter)
    if revision:
        cmd += ["--adapter-sha", revision]
    subprocess.run(cmd, check=True, cwd=ROOT)

    if args.no_upload:
        print(f"skipped upload; results in {out_dir}")
    else:
        upload_run(args.adapter, run, out_dir)
        print(f"uploaded {args.adapter}/evals/{run}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
