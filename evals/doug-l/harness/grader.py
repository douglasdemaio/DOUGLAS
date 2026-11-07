"""DOUG-L grader: extraction + solver tool call + grounded explanation.

Frozen items live in evals/doug-l/frozen/items.jsonl:
    {id, documents: [{id,text}], order: {...expected extraction...},
     fleet: [...], explanation_facts: [...]}

Model output (prediction):
    {extraction: {...}, solver_calls: [{tool:"plan_route", args:{...}}],
     plan: {vehicle_id, depart, arrive, drive_hours, cost}, explanation: str}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import solver  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
FROZEN = ROOT / "evals" / "doug-l" / "frozen"
ITEMS = FROZEN / "items.jsonl"

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# --------------------------------------------------------------------------- #
# items
# --------------------------------------------------------------------------- #
def list_items() -> list[dict]:
    items = []
    with open(ITEMS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def document_text(item: dict) -> str:
    return "\n".join(doc["text"] for doc in item["documents"])


def expected(item: dict) -> dict:
    return dict(item["order"])


# --------------------------------------------------------------------------- #
# predictions for the self-test
# --------------------------------------------------------------------------- #
def gold_prediction(item: dict) -> dict:
    order = expected(item)
    optimal = solver.plan(order, item["fleet"])
    explanation = (
        f"Vehicle {optimal['vehicle_id']} departs {optimal['depart']} and arrives "
        f"{optimal['arrive']} after {optimal['drive_hours']} driving hours, "
        f"cost {optimal['cost']}."
    )
    return {
        "extraction": order,
        "solver_calls": [{"tool": "plan_route", "args": order}],
        "plan": optimal,
        "explanation": explanation,
    }


def bad_prediction(item: dict) -> dict:
    wrong = expected(item)
    wrong["weight_kg"] = float(wrong["weight_kg"]) * 10
    wrong["due_at"] = "2000-01-01T00:00"
    return {
        "extraction": wrong,
        "solver_calls": [{"tool": "plan_route", "args": wrong}],
        "plan": {
            "vehicle_id": "nope",
            "depart": wrong["ready_at"],
            "arrive": wrong["due_at"],
            "drive_hours": 1.0,
            "cost": 1.0,
        },
        "explanation": "Trust me, the cost is 1.0.",
    }


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #
def norm(value):
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def extraction_correct(item: dict, extraction: dict) -> bool:
    want = expected(item)
    if set(extraction) != set(want):
        return False
    return all(norm(extraction[key]) == norm(want[key]) for key in want)


def solver_call_valid(item: dict, calls: list) -> bool:
    if not isinstance(calls, list) or not calls:
        return False
    for call in calls:
        if not isinstance(call, dict) or call.get("tool") != "plan_route":
            return False
        args = call.get("args")
        if not isinstance(args, dict):
            return False
        if set(solver.REQUIRED_ORDER_FIELDS) - set(args):
            return False
        if not isinstance(args["distance_km"], (int, float)):
            return False
        if not isinstance(args["weight_kg"], (int, float)):
            return False
    return True


def plan_matches(proposed: dict, optimal: dict) -> bool:
    if not proposed or proposed.get("feasible") is False:
        return False
    if not optimal.get("feasible", True):
        return False
    if proposed.get("vehicle_id") != optimal.get("vehicle_id"):
        return False
    if proposed.get("arrive") != optimal.get("arrive"):
        return False
    return abs(float(proposed.get("cost", -1)) - float(optimal["cost"])) <= 0.01


def hallucinated_rate(item: dict, extraction: dict) -> float:
    want = expected(item)
    doc_numbers = set(NUMBER_RE.findall(document_text(item)))
    doc_folded = document_text(item).casefold()
    problems = 0
    total = max(1, len(want))
    for key, value in extraction.items():
        if key not in want:
            problems += 1
            continue
        if isinstance(value, str):
            if norm(value) not in doc_folded and not set(NUMBER_RE.findall(value)) <= doc_numbers:
                problems += 1
        elif isinstance(value, (int, float)):
            if str(value) not in doc_numbers and str(int(value)) not in doc_numbers:
                problems += 1
    return min(1.0, problems / total)


def explanation_grounded(item: dict, prediction: dict) -> float:
    explanation = str(prediction.get("explanation", ""))
    numbers = set(NUMBER_RE.findall(explanation))
    if not numbers:
        return 1.0
    known = set(NUMBER_RE.findall(document_text(item)))
    known |= set(NUMBER_RE.findall(json.dumps(prediction.get("plan", {}))))
    known |= set(NUMBER_RE.findall(json.dumps(prediction.get("extraction", {}))))
    return 1.0 if numbers <= known else 0.0


def grade_item(item: dict, prediction: dict) -> dict:
    extraction = prediction.get("extraction") or {}
    calls = prediction.get("solver_calls") or []
    plan = prediction.get("plan") or {}

    extraction_ok = extraction_correct(item, extraction)
    call_ok = solver_call_valid(item, calls)
    optimal = solver.plan(extraction, item["fleet"]) if call_ok else {"feasible": False}
    constraints, problems = solver.constraints_ok(extraction, item["fleet"], plan)
    plan_ok = plan_matches(plan, optimal) and constraints
    gap = solver.cost_gap(plan, optimal) if call_ok else 1.0

    return {
        "id": item["id"],
        "task_success": 1.0 if (extraction_ok and call_ok and plan_ok) else 0.0,
        "solver_call_validity": 1.0 if call_ok else 0.0,
        "cost_gap_vs_solver": gap,
        "hallucinated_field_rate": hallucinated_rate(item, extraction),
        "explanation_grounded": explanation_grounded(item, prediction),
        "constraint_problems": problems,
    }
