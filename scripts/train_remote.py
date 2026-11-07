"""Run inside a Hugging Face Job: QLoRA SFT or DPO, then push the adapter.

    python -m scripts.train_remote --model doug-a --stage sft \
        --output-repo <namespace>/douglas-doug-a

This module is never imported by `make check`; it needs a GPU and the packages
in requirements.train.lock.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.common import ROOT, load_config, load_recipe, read_jsonl, sha256_file


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def load_sft(model: str) -> list[dict]:
    recipe = load_recipe(model)
    rows: list[dict] = []
    seen: set[str] = set()
    min_chars = 80
    for rule in recipe.get("sft", {}).get("filters", []):
        if rule.get("name") == "min-assistant-chars":
            min_chars = int(rule.get("min_chars", min_chars))
    for source in recipe.get("sft", {}).get("sources", []):
        source_path = resolve(source["path"])
        if not source_path.exists():
            print(f"warning: missing SFT source {source_path}", file=sys.stderr)
            continue
        for row in read_jsonl(source_path):
            messages = row.get("messages") or []
            assistant = next(
                (m.get("content", "") for m in messages if m.get("role") == "assistant"), ""
            )
            if len(assistant) < min_chars:
                continue
            key = json.dumps(messages, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"messages": messages})
    return rows


def load_dpo(model: str) -> list[dict]:
    recipe = load_recipe(model)
    rows = []
    for source in recipe.get("dpo", {}).get("sources", []):
        source_path = resolve(source["path"])
        if not source_path.exists():
            print(f"warning: missing DPO source {source_path}", file=sys.stderr)
            continue
        for row in read_jsonl(source_path):
            if {"prompt", "chosen", "rejected"} <= set(row):
                rows.append(
                    {"prompt": row["prompt"], "chosen": row["chosen"], "rejected": row["rejected"]}
                )
    return rows


# --------------------------------------------------------------------------- #
# training
# --------------------------------------------------------------------------- #
def train_sft(args, config: dict, rows: list[dict]) -> None:
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    base = config["base"]["repo"]
    lora = config["lora"]
    params = config["training"]["sft"]

    tokenizer = AutoTokenizer.from_pretrained(base, revision=config["base"]["revision"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base,
        revision=config["base"]["revision"],
        quantization_config=quant,
        device_map="auto",
    )
    model = get_peft_model(
        model,
        LoraConfig(
            r=int(lora["r"]),
            lora_alpha=int(lora["alpha"]),
            lora_dropout=float(lora["dropout"]),
            target_modules=lora["target_modules"],
            task_type="CAUSAL_LM",
        ),
    )

    dataset = Dataset.from_list(rows)
    train_args = SFTConfig(
        output_dir=str(ROOT / "training-output"),
        num_train_epochs=float(params["epochs"]),
        learning_rate=float(params["lr"]),
        per_device_train_batch_size=int(params["batch_size"]),
        gradient_accumulation_steps=int(params["grad_accum"]),
        max_length=int(params["max_seq_len"]),
        bf16=True,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
        push_to_hub=True,
        hub_model_id=args.output_repo,
        hub_strategy="end",
    )
    if args.max_steps:
        train_args.max_steps = args.max_steps
    trainer = SFTTrainer(
        model=model,
        args=train_args,
        train_dataset=dataset,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.push_to_hub()
    print(json.dumps({"stage": "sft", "rows": len(rows), "metrics": trainer.state.log_history[-1]}))


def train_dpo(args, config: dict, rows: list[dict]) -> None:
    import torch
    from datasets import Dataset
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import DPOConfig, DPOTrainer

    base = config["base"]["repo"]
    params = config["training"]["dpo"]

    tokenizer = AutoTokenizer.from_pretrained(args.init_adapter or args.output_repo)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base,
        revision=config["base"]["revision"],
        quantization_config=quant,
        device_map="auto",
    )
    model = PeftModel.from_pretrained(
        model, args.init_adapter or args.output_repo, is_trainable=True
    )

    dataset = Dataset.from_list(rows)
    train_args = DPOConfig(
        output_dir=str(ROOT / "training-output"),
        beta=float(params["beta"]),
        num_train_epochs=float(params["epochs"]),
        learning_rate=float(params["lr"]),
        per_device_train_batch_size=int(params["batch_size"]),
        gradient_accumulation_steps=int(params["grad_accum"]),
        max_length=int(params["max_seq_len"]),
        bf16=True,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
        push_to_hub=True,
        hub_model_id=args.output_repo,
        hub_strategy="end",
    )
    if args.max_steps:
        train_args.max_steps = args.max_steps
    trainer = DPOTrainer(
        model=model,
        args=train_args,
        train_dataset=dataset,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.push_to_hub()
    print(json.dumps({"stage": "dpo", "rows": len(rows), "metrics": trainer.state.log_history[-1]}))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--stage", choices=["sft", "dpo"], default="sft")
    parser.add_argument("--output-repo", required=True)
    parser.add_argument("--init-adapter")
    parser.add_argument("--max-steps", type=int)
    args = parser.parse_args(argv)

    config = load_config(args.model)
    rows = load_sft(args.model) if args.stage == "sft" else load_dpo(args.model)
    if not rows:
        print("no training rows after filtering; refusing to train", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "model": args.model,
                "stage": args.stage,
                "rows": len(rows),
                "recipe_sha256": sha256_file(ROOT / "models" / args.model / "recipe.yaml"),
                "hf_token_present": bool(os.environ.get("HF_TOKEN")),
            }
        )
    )
    if args.stage == "sft":
        train_sft(args, config, rows)
    else:
        train_dpo(args, config, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
