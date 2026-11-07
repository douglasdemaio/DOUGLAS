"""Runnable harness self-test: python evals/doug-l/harness/selftest.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grader  # noqa: E402
import solver  # noqa: E402


def main() -> int:
    items = grader.list_items()
    if not items:
        print("no frozen items found", file=sys.stderr)
        return 2

    failures = []
    for item in items:
        gold = grader.grade_item(item, grader.gold_prediction(item))
        if gold["task_success"] != 1.0:
            failures.append(f"{gold['id']}: gold prediction did not succeed")
        if gold["solver_call_validity"] != 1.0:
            failures.append(f"{gold['id']}: gold solver call invalid")
        if gold["cost_gap_vs_solver"] > 0.01:
            failures.append(f"{gold['id']}: gold cost gap {gold['cost_gap_vs_solver']}")
        if gold["hallucinated_field_rate"] != 0.0:
            failures.append(f"{gold['id']}: gold hallucination rate != 0")

        bad = grader.grade_item(item, grader.bad_prediction(item))
        if bad["task_success"] != 0.0:
            failures.append(f"{bad['id']}: bad prediction was accepted")

        optimal = solver.plan(item["order"], item["fleet"])
        if not optimal.get("feasible"):
            failures.append(f"{item['id']}: frozen item has no feasible plan")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(f"doug-l harness self-test: OK ({len(items)} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
