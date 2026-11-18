"""Fail-closed review of a proposed DOUGLAS change.

    python -m scripts.review --model doug-a --challenger results/<run> \
        --diff-file path/to.diff --base origin/main

The review verifies containment, policy, hermetic checks, scope/protection,
the frozen suite, the seed count, an independent replay re-grade and the CI
promotion gate. Any missing or failing check writes a rejection report and
stops. This module never writes to registry/, baseline.json or a champion
file: only scripts.gate (invoked here) may promote.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import jsonschema

from scripts import attestation, containment, policy, rejection
from scripts.common import (
    ROOT,
    frozen_sha256,
    load_json,
    read_jsonl,
    sha256_bytes,
    verify_frozen_manifest,
    write_json,
)
from scripts.containment import ContainmentViolation

PASS, REJECT, HALT = 0, 1, 2


class ReviewHalt(RuntimeError):
    """A required check or artifact was unavailable; the loop must stop."""


def _failure(check: str, evidence: str, why: str, fix: str, root_cause: str | None = None) -> dict:
    return {
        "check": check,
        "evidence": evidence,
        "why": why,
        "fix": fix,
        "root_cause": root_cause,
    }


def _tail(output: str, limit: int = 2000) -> str:
    text = output.strip()
    return text[-limit:] if len(text) > limit else (text or "<empty output>")


def run_command(
    cmd: list[str], env: dict[str, str], *, cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def regrade(model: str, challenger: dict, predictions: Path, out_dir: Path) -> dict:
    """Re-run the frozen suite from committed predictions, without a network."""
    from scripts import eval as eval_module

    code = eval_module.main(
        [
            "--model",
            model,
            "--ckpt",
            str(challenger.get("run", "challenger")),
            "--seeds",
            str(len(challenger.get("seeds") or [1, 2, 3])),
            "--engine",
            "replay",
            "--predictions",
            str(predictions),
            "--out",
            str(out_dir),
            "--run",
            f"review-{out_dir.name}",
            "--adapter-sha",
            str(challenger.get("hashes", {}).get("adapter_sha256", "unknown")),
        ]
    )
    if code != 0:
        raise ReviewHalt(f"re-grade exited {code}")
    scores = load_json(out_dir / "scores.json")
    write_json(out_dir / "reviewed-scores.json", scores)
    return scores


def invoke_gate(
    model: str, scores_path: Path, env: dict[str, str], *, cwd: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, "-m", "scripts.gate", "--model", model, "--challenger", str(scores_path)],
        env,
        cwd=cwd,
    )


def verify_gate_receipt(receipt: str, pub_path: Path):
    return attestation.verify_gate_receipt(receipt, pub_path)


def _report(
    root: Path,
    model: str,
    run: str | None,
    diff_sha256: str,
    failures: list[dict],
    *,
    code: int = REJECT,
    addresses: str | None = None,
) -> tuple[int, str]:
    report = rejection.build_report(
        model=model, run=run, diff_sha256=diff_sha256, failures=failures, addresses=addresses
    )
    path, report_id = rejection.write_report(report, root=root)
    policy.record(
        "rejection",
        path=root / "reviews" / "events.jsonl",
        model=model,
        diff=diff_sha256,
        report=report_id,
        run=run,
    )
    for failure in failures:
        print(f"  FAIL: {failure['check']} — {failure['evidence']}")
    print(f"rejection report: {path}")
    print("decision: REJECT" if code == REJECT else "decision: HALT (no work performed)")
    return code, report_id


def _diff_text(root: Path, diff_file: str | None, base: str, env: dict[str, str]) -> str:
    if diff_file:
        path = containment.assert_writable(diff_file, root=root, env=os.environ.copy())
        return path.read_text(encoding="utf-8")
    result = run_command(["git", "diff", f"{base}...HEAD"], env, cwd=root)
    if result.returncode != 0:
        raise ReviewHalt(f"cannot compute diff against {base}: {_tail(result.stderr)}")
    return result.stdout


def _latest_frozen_hash(model: str, root: Path) -> str | None:
    latest = None
    for entry in read_jsonl(root / "reviews" / "decisions.jsonl"):
        payload = entry.get("payload") or {}
        if payload.get("model_id") == model:
            latest = payload
    return latest.get("frozen_eval_sha256") if latest else None


def _parent_champion(model: str, root: Path) -> dict[str, Any]:
    champion_file = root / "registry" / f"{model}.champion.scores.json"
    champion = load_json(champion_file) if champion_file.exists() else {}
    baseline = load_json(root / "baseline.json") if (root / "baseline.json").exists() else {}
    champion_adapter = (baseline.get("models", {}).get(model) or {}).get("champion")
    return {
        "adapter_sha256": champion.get("adapter_sha256") or champion_adapter,
        "run": champion.get("run"),
        "receipt": champion.get("receipt"),
    }


def _per_seed(scores: dict) -> list[dict[str, Any]]:
    seeds = scores.get("seeds") or []
    rows = []
    for index, seed in enumerate(seeds):
        row: dict[str, Any] = {"seed": seed}
        for name, entry in (scores.get("metrics") or {}).items():
            values = entry.get("values") or []
            if index < len(values):
                row[name] = values[index]
        rows.append(row)
    return rows


def review(
    model: str,
    challenger_ref: str,
    *,
    root: Path = ROOT,
    diff_file: str | None = None,
    base: str = "origin/main",
    predictions: str | None = None,
    allow_network: bool = False,
    network_reason: str | None = None,
    addresses: str | None = None,
    key_text: str | None = None,
    now: str | None = None,
) -> int:
    """Run every check in order. Returns PASS / REJECT / HALT."""
    events = root / "reviews" / "events.jsonl"
    original_connect = None
    try:
        if allow_network:
            if not network_reason or len(network_reason) < 10:
                raise ReviewHalt("--allow-network requires a recorded --network-reason")
            policy.record("network_allowed", path=events, reason=network_reason, model=model)
        else:
            original_connect = containment.block_network(root=root)

        clean_env = containment.scrub_env(allow_network=allow_network)
        diff_text = _diff_text(root, diff_file, base, clean_env)
        if not diff_text.strip():
            return _report(
                root,
                model,
                None,
                sha256_bytes(b""),
                [
                    _failure(
                        "single-concern diff",
                        "empty diff",
                        "A change with no diff cannot be reviewed or traced.",
                        "Commit the single recipe/hyperparameter change before requesting review.",
                    )
                ],
                addresses=addresses,
            )[0]
        diff_digest = sha256_bytes(diff_text.encode("utf-8"))

        allowed, reasons = policy.check_start(
            model,
            diff_digest,
            addresses=addresses,
            now=now,
            policy_path=root / "reviews" / "policy.json",
            events_path=events,
        )
        if not allowed:
            code = HALT if any("unavailable" in r for r in reasons) else REJECT
            return _report(
                root,
                model,
                None,
                diff_digest,
                [
                    _failure(
                        "review policy",
                        reason,
                        "Changing faster than we can verify risks unreviewed regressions.",
                        "Wait for the cooldown / close the open PR / address the prior rejection report.",
                    )
                    for reason in reasons
                ],
                code=code,
                addresses=addresses,
            )[0]
        policy.record(
            "run", path=events, ts=now, model=model, diff=diff_digest, addresses=addresses
        )

        check = run_command(["make", "check"], clean_env, cwd=root)
        if check.returncode != 0:
            return _report(
                root,
                model,
                None,
                diff_digest,
                [
                    _failure(
                        "hermetic checks",
                        f"make check exited {check.returncode}: {_tail(check.stdout + check.stderr)}",
                        "A red check suite means the change is not safe to train or promote.",
                        "Fix the failing test; re-run make check REPEAT=3 before submitting.",
                        root_cause="cause unknown",
                    )
                ],
                addresses=addresses,
            )[0]

        for target in ("scope", "protect"):
            result = run_command(["make", target, f"BASE={base}"], clean_env, cwd=root)
            if result.returncode != 0:
                return _report(
                    root,
                    model,
                    None,
                    diff_digest,
                    [
                        _failure(
                            f"{target} check",
                            f"make {target} exited {result.returncode}: {_tail(result.stdout + result.stderr)}",
                            "Multi-concern or protected-file changes bypass the review guarantees.",
                            "Split into one model/one concern and leave gate/frozen/eval files untouched.",
                        )
                    ],
                    addresses=addresses,
                )[0]

        problems = verify_frozen_manifest(model)
        if problems:
            return _report(
                root,
                model,
                None,
                diff_digest,
                [
                    _failure(
                        "frozen suite integrity",
                        problem,
                        "A modified frozen suite invalidates every champion score.",
                        "Restore the frozen files from the signed manifest; open an issue instead.",
                        root_cause="frozen manifest mismatch",
                    )
                    for problem in problems
                ],
                code=HALT,
                addresses=addresses,
            )[0]
        current_hash = frozen_sha256(model)
        previous_hash = _latest_frozen_hash(model, root)
        if previous_hash and previous_hash != current_hash:
            return _report(
                root,
                model,
                None,
                diff_digest,
                [
                    _failure(
                        "frozen suite drift",
                        f"current {current_hash}, last signed decision {previous_hash}",
                        "The gatekeeper changed since the last promotion; scores are not comparable.",
                        "Only a human-reviewed PR may change the frozen suite; re-score the champion.",
                        root_cause="frozen suite changed after last signed decision",
                    )
                ],
                code=HALT,
                addresses=addresses,
            )[0]

        challenger_path = (
            root / challenger_ref
            if not Path(challenger_ref).is_absolute()
            else Path(challenger_ref)
        )
        if not challenger_path.is_file():
            raise ReviewHalt(f"challenger scores unavailable: {challenger_ref}")
        challenger = load_json(challenger_path)
        seeds = challenger.get("seeds") or []
        if len(seeds) < 3:
            return _report(
                root,
                model,
                challenger.get("run"),
                diff_digest,
                [
                    _failure(
                        "seed count",
                        f"{len(seeds)} seeds ({seeds})",
                        "Fewer than three seeds cannot distinguish a real gain from noise.",
                        "Re-evaluate with SEEDS=3 and report mean +/- std over all seeds.",
                    )
                ],
                addresses=addresses,
            )[0]

        schema = load_json(ROOT / "schemas" / "scores.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        schema_errors = sorted(validator.iter_errors(challenger), key=lambda e: str(e.path))
        if schema_errors:
            return _report(
                root,
                model,
                challenger.get("run"),
                diff_digest,
                [
                    _failure(
                        "scores schema",
                        str(error.message),
                        "Malformed scores can hide a missing seed or a fabricated metric.",
                        "Regenerate scores with make eval SEEDS=3 and commit a valid scores.json.",
                    )
                    for error in schema_errors[:10]
                ],
                addresses=addresses,
            )[0]

        hash_in_scores = (challenger.get("hashes") or {}).get("frozen_eval_sha256")
        if hash_in_scores != current_hash:
            return _report(
                root,
                model,
                challenger.get("run"),
                diff_digest,
                [
                    _failure(
                        "frozen hash",
                        f"scores {hash_in_scores}, current {current_hash}",
                        "Scores from a different frozen suite are not comparable to the champion.",
                        "Re-evaluate against the current frozen suite.",
                    )
                ],
                addresses=addresses,
            )[0]
        for name, entry in (challenger.get("metrics") or {}).items():
            values = entry.get("values") or []
            if len(values) != len(seeds):
                return _report(
                    root,
                    model,
                    challenger.get("run"),
                    diff_digest,
                    [
                        _failure(
                            "per-seed results",
                            f"{name}: {len(values)} values for {len(seeds)} seeds",
                            "Missing per-seed values make the noise margin meaningless.",
                            "Re-run make eval with all seeds and commit the complete scores.json.",
                        )
                    ],
                    addresses=addresses,
                )[0]

        predictions_path = (
            Path(predictions) if predictions else challenger_path.parent / "predictions.jsonl"
        )
        if not predictions_path.is_file():
            raise ReviewHalt(f"predictions for re-grade unavailable: {predictions_path}")
        out_dir = Path(tempfile.mkdtemp(prefix=".review-", dir=root / "results"))
        reviewed = regrade(model, challenger, predictions_path, out_dir)
        differences = []
        for name, entry in (challenger.get("metrics") or {}).items():
            fresh = (reviewed.get("metrics") or {}).get(name)
            if fresh is None:
                differences.append(f"{name}: missing after re-grade")
                continue
            for stat in ("mean", "std"):
                if abs(float(entry.get(stat, 0)) - float(fresh.get(stat, 0))) > 1e-6:
                    differences.append(
                        f"{name}.{stat}: submitted {entry.get(stat)}, re-graded {fresh.get(stat)}"
                    )
        if differences:
            return _report(
                root,
                model,
                challenger.get("run"),
                diff_digest,
                [
                    _failure(
                        "independent re-grade",
                        difference,
                        "The gate trusts scores.json, so unverifiable scores could promote a regression.",
                        "Re-evaluate and submit scores that exactly match a replay of predictions.jsonl.",
                        root_cause="submitted scores do not match replay",
                    )
                    for difference in differences
                ],
                addresses=addresses,
            )[0]

        signing_key = key_text or os.environ.get("DOUGLAS_SIGNING_KEY", "")
        if not signing_key:
            raise ReviewHalt("DOUGLAS_SIGNING_KEY unavailable; cannot invoke the gate")
        gate_env = containment.scrub_env(keep={"DOUGLAS_SIGNING_KEY"}, base=os.environ.copy())
        gate_env["DOUGLAS_SIGNING_KEY"] = signing_key
        gate_result = invoke_gate(model, out_dir / "scores.json", gate_env, cwd=root)
        if gate_result.returncode not in (PASS, REJECT):
            raise ReviewHalt(f"promotion gate unavailable: {_tail(gate_result.stderr)}")
        if gate_result.returncode == REJECT:
            failures = []
            for line in gate_result.stdout.splitlines():
                if line.strip().startswith("FAIL:"):
                    detail = line.strip().removeprefix("FAIL:").strip()
                    failures.append(
                        _failure(
                            "promotion gate",
                            detail,
                            "The gate blocks promotion for this metric; accepting it would regress the champion.",
                            "Address the gate failure with a new single-concern run and >=3 seeds.",
                        )
                    )
            if not failures:
                failures = [
                    _failure(
                        "promotion gate",
                        _tail(gate_result.stdout + gate_result.stderr),
                        "An unexplained gate rejection cannot be safely resubmitted.",
                        "Re-run the gate locally to capture its FAIL lines before resubmitting.",
                    )
                ]
            return _report(
                root, model, challenger.get("run"), diff_digest, failures, addresses=addresses
            )[0]

        registry = root / "registry" / f"{model}.jsonl"
        entries = list(read_jsonl(registry))
        if not entries:
            raise ReviewHalt(f"gate reported promotion but {registry} has no receipt")
        gate_receipt = str(entries[-1].get("receipt") or "")
        gate_payload = verify_gate_receipt(gate_receipt, root / "registry" / "verification_key.pub")
        if gate_payload.get("model_id") != model:
            raise ReviewHalt(f"gate receipt is for {gate_payload.get('model_id')!r}, not {model!r}")

        payload = attestation.build_payload(
            model_id=model,
            run=str(reviewed.get("run")),
            diff_sha256=diff_digest,
            diff=diff_text,
            per_seed=_per_seed(reviewed),
            metrics=reviewed.get("metrics") or {},
            adapter_sha256=reviewed.get("hashes", {}).get("adapter_sha256") or "unknown",
            gate_decision="PROMOTED",
            gate_receipt=gate_receipt,
            parent_champion=_parent_champion(model, root),
            frozen_eval_sha256=current_hash,
            promoted_scores=reviewed,
            addresses=addresses,
        )
        decision = attestation.sign_decision(payload, signing_key)
        attestation.append_decision(decision, payload, root=root)
        print(f"decision: PROMOTED ({model} / {reviewed.get('run')})")
        print(f"attestation: {decision}")
        return PASS
    except (ReviewHalt, ContainmentViolation, OSError, ValueError) as exc:
        containment_detail = str(exc)
        print(f"halt: {containment_detail}", file=sys.stderr)
        return _report(
            root,
            model,
            None,
            sha256_bytes(diff_text.encode("utf-8"))
            if "diff_text" in locals()
            else sha256_bytes(b""),
            [
                _failure(
                    "availability / containment",
                    containment_detail,
                    "A required check could not run, so the change is unverified.",
                    "Restore the missing check, key or artifact and start a new run; never skip it.",
                    root_cause="cause unknown",
                )
            ],
            code=HALT,
            addresses=addresses,
        )[0]
    finally:
        if original_connect is not None:
            containment.restore_network(original_connect)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=["doug-a", "doug-l"])
    parser.add_argument("--challenger", required=True)
    parser.add_argument("--diff-file")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--predictions")
    parser.add_argument("--addresses", help="rejection report id this run addresses")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--network-reason")
    args = parser.parse_args(argv)
    return review(
        args.model,
        args.challenger,
        diff_file=args.diff_file,
        base=args.base,
        predictions=args.predictions,
        addresses=args.addresses,
        allow_network=args.allow_network,
        network_reason=args.network_reason,
    )


if __name__ == "__main__":
    sys.exit(main())
