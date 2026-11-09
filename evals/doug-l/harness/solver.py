"""Deterministic small-instance solver used by the DOUG-L harness.

The model never does optimisation arithmetic. It extracts fields, calls
plan_route, and explains the returned plan. This module is the tool.
"""

from __future__ import annotations

from datetime import datetime, timedelta

REQUIRED_ORDER_FIELDS = (
    "order_id",
    "pickup",
    "delivery",
    "weight_kg",
    "pallets",
    "ready_at",
    "due_at",
    "distance_km",
)

AVG_SPEED_KMH = 60.0
LOADING_HOURS = 0.5


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def drive_hours(distance_km: float) -> float:
    return round(float(distance_km) / AVG_SPEED_KMH + LOADING_HOURS, 4)


def plan(order: dict, fleet: list[dict]) -> dict:
    hours = drive_hours(order["distance_km"])
    depart = _dt(order["ready_at"])
    arrive = depart + timedelta(hours=hours)

    feasible = []
    for vehicle in fleet:
        if float(vehicle["capacity_kg"]) < float(order["weight_kg"]):
            continue
        if _dt(vehicle["available_from"]) > depart:
            continue
        if _dt(vehicle["available_to"]) < arrive:
            continue
        if hours > float(vehicle["max_hours"]):
            continue
        cost = round(
            float(vehicle["rate_per_hour"]) * hours
            + float(vehicle["rate_per_km"]) * float(order["distance_km"]),
            2,
        )
        feasible.append(
            {
                "vehicle_id": vehicle["vehicle_id"],
                "depart": order["ready_at"],
                "arrive": arrive.isoformat(timespec="minutes"),
                "drive_hours": hours,
                "cost": cost,
            }
        )

    if not feasible:
        return {"feasible": False, "reason": "no vehicle satisfies capacity and time windows"}
    best = min(feasible, key=lambda p: (p["cost"], p["vehicle_id"]))
    return {"feasible": True, **best}


def constraints_ok(order: dict, fleet: list[dict], proposed: dict) -> tuple[bool, list[str]]:
    # Model output is untrusted: a plan or order missing a field fails the check.
    try:
        return _constraints_ok(order, fleet, proposed)
    except (KeyError, TypeError, ValueError) as exc:
        return False, [f"malformed plan or order: {exc!r}"]


def _constraints_ok(order: dict, fleet: list[dict], proposed: dict) -> tuple[bool, list[str]]:
    if not proposed or not proposed.get("feasible", True):
        return False, ["no feasible plan"]
    vehicle = next((v for v in fleet if v["vehicle_id"] == proposed.get("vehicle_id")), None)
    if vehicle is None:
        return False, ["unknown vehicle"]
    problems = []
    if float(vehicle["capacity_kg"]) < float(order["weight_kg"]):
        problems.append("capacity exceeded")
    arrive = _dt(proposed["arrive"])
    if arrive > _dt(order["due_at"]):
        problems.append("delivery after due time")
    if _dt(vehicle["available_from"]) > _dt(proposed["depart"]):
        problems.append("vehicle not available at departure")
    if _dt(vehicle["available_to"]) < arrive:
        problems.append("vehicle unavailable at arrival")
    hours = float(proposed.get("drive_hours", 0.0))
    if hours > float(vehicle["max_hours"]):
        problems.append("legal driving hours exceeded")
    return (not problems, problems)


def cost_gap(proposed: dict, optimal: dict) -> float:
    if not optimal.get("feasible", True):
        return 0.0 if not proposed.get("feasible", True) else 1.0
    if not proposed or not proposed.get("feasible", True):
        return 1.0
    best = float(optimal["cost"])
    if best <= 0:
        return 0.0
    return min(1.0, abs(float(proposed.get("cost", 0.0)) - best) / best)
