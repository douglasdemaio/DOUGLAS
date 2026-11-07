"""Contamination check: training data vs the frozen eval set.

Two independent signals:
  1. exact word n-gram containment (default 13-grams)
  2. cosine similarity of deterministic hashed n-gram embeddings

No model download, no network: the embedding is a hashed bag of words/bigrams,
which is deliberately conservative and reproducible.

    python -m scripts.contamination --model doug-a
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

from scripts.common import data_dir, frozen_dir, load_json

WORD_RE = re.compile(r"[a-z0-9]+")
TEXT_SUFFIXES = {".jsonl", ".json", ".txt", ".md", ".py"}


# --------------------------------------------------------------------------- #
# text loading
# --------------------------------------------------------------------------- #
def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_strings(item))
        return out
    return []


def load_corpus(root: Path) -> list[tuple[str, str]]:
    """Return (relative name, text) for every text-bearing file under root."""
    corpus: list[tuple[str, str]] = []
    if not root.exists():
        return corpus
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix == ".jsonl":
            chunks = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    chunks.extend(_strings(json.loads(line)))
                except json.JSONDecodeError:
                    chunks.append(line)
            corpus.append((rel, "\n".join(chunks)))
        elif path.suffix == ".json":
            try:
                corpus.append((rel, "\n".join(_strings(json.loads(path.read_text())))))
            except json.JSONDecodeError:
                corpus.append((rel, path.read_text(encoding="utf-8")))
        else:
            corpus.append((rel, path.read_text(encoding="utf-8")))
    return corpus


# --------------------------------------------------------------------------- #
# signals
# --------------------------------------------------------------------------- #
def tokens(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def shingles(text: str, n: int) -> set[tuple[str, ...]]:
    words = tokens(text)
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def hashed_embedding(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    words = tokens(text)
    features = words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]
    for feature in features:
        digest = 0
        for byte in feature.encode("utf-8"):
            digest = (digest * 131 + byte) & 0xFFFFFFFF
        index = digest % dim
        sign = 1.0 if (digest >> 31) & 1 else -1.0
        vec[index] += sign
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def default_thresholds() -> dict:
    return {"ngram": 13, "max_containment": 0.20, "embedding_dim": 256, "max_cosine": 0.97}


def thresholds(model: str) -> dict:
    path = frozen_dir(model) / "thresholds.json"
    data = default_thresholds()
    if path.exists():
        data.update(load_json(path))
    return data


def check(model: str) -> dict:
    cfg = thresholds(model)
    train = load_corpus(data_dir(model))
    frozen = load_corpus(frozen_dir(model))

    train_shingles: list[tuple[str, set]] = [
        (name, shingles(text, cfg["ngram"])) for name, text in train
    ]
    train_all: set = set()
    for _, sh in train_shingles:
        train_all |= sh

    train_vecs = {name: hashed_embedding(text, cfg["embedding_dim"]) for name, text in train}
    frozen_vecs = {name: hashed_embedding(text, cfg["embedding_dim"]) for name, text in frozen}

    leaks = []
    max_containment = 0.0
    max_cosine = 0.0
    worst_pair = None
    for name, text in frozen:
        sh = shingles(text, cfg["ngram"])
        if sh:
            shared = sh & train_all
            containment = len(shared) / len(sh)
            max_containment = max(max_containment, containment)
            if shared and len(shared) >= 1:
                leaks.append({"frozen": name, "shared_ngrams": len(shared)})
        for train_name, vec in train_vecs.items():
            sim = cosine(frozen_vecs[name], vec)
            if sim > max_cosine:
                max_cosine = sim
                worst_pair = (name, train_name)

    reasons = []
    if leaks:
        reasons.append(
            f"{len(leaks)} frozen file(s) share exact {cfg['ngram']}-grams with training data"
        )
    if max_containment > cfg["max_containment"]:
        reasons.append(f"containment {max_containment:.3f} > {cfg['max_containment']}")
    if max_cosine > cfg["max_cosine"]:
        reasons.append(f"embedding cosine {max_cosine:.3f} > {cfg['max_cosine']}")

    return {
        "model": model,
        "clean": not reasons,
        "reasons": reasons,
        "thresholds": cfg,
        "train_files": len(train),
        "frozen_files": len(frozen),
        "exact_leaks": leaks[:20],
        "max_containment": round(max_containment, 4),
        "max_cosine": round(max_cosine, 4),
        "closest_pair": list(worst_pair) if worst_pair else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = check(args.model)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "clean" if result["clean"] else "DIRTY"
        print(
            f"{args.model}: {status} "
            f"(files train={result['train_files']} frozen={result['frozen_files']}, "
            f"containment={result['max_containment']}, cosine={result['max_cosine']})"
        )
        for reason in result["reasons"]:
            print(f"  - {reason}")
    return 0 if result["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
