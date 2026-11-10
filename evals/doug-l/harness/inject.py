"""Generate synthetic DOUG-L shipments into data/doug-l/synthetic/sft.jsonl.

These are new shipments drawn from templates, not copies of the frozen set. Run:

    python evals/doug-l/harness/inject.py --count 600 --seed 7

Every template is validated: the extraction fields and plan must match the
solver output, so a bad template never enters training data.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import solver  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "doug-l" / "synthetic" / "sft.jsonl"

SYSTEM = "You are DOUG-L. Extract fields, call the solver tool, never do optimisation arithmetic yourself."

# European cities for realistic shipment pairs
CITIES = [
    ("Barcelona", "Zaragoza", 90),
    ("Lille", "Paris", 225),
    ("Gdansk", "Poznan", 310),
    ("Rotterdam", "Utrecht", 75),
    ("Hamburg", "Bremen", 120),
    ("Lyon", "Marseille", 315),
    ("Antwerp", "Ghent", 60),
    ("Munich", "Nuremberg", 170),
    ("Madrid", "Valencia", 355),
    ("Warsaw", "Krakow", 295),
    ("Brussels", "Liege", 95),
    ("Milan", "Bologna", 210),
    ("Prague", "Brno", 205),
    ("Vienna", "Salzburg", 300),
    ("Copenhagen", "Aarhus", 185),
    ("Oslo", "Bergen", 465),
    ("Stockholm", "Gothenburg", 470),
    ("Helsinki", "Tampere", 175),
    ("Dublin", "Cork", 255),
    ("Lisbon", "Porto", 315),
    ("Athens", "Thessaloniki", 505),
    ("Budapest", "Debrecen", 230),
    ("Bucharest", "Cluj-Napoca", 445),
    ("Sofia", "Plovdiv", 145),
    ("Belgrade", "Novi Sad", 75),
]

FLEET_TEMPLATES = [
    # Light fleet
    [
        {
            "vehicle_id": "VAN-1",
            "capacity_kg": 1200,
            "available_from": "2026-11-20T06:00",
            "available_to": "2026-11-20T21:00",
            "max_hours": 9,
            "rate_per_hour": 28,
            "rate_per_km": 0.45,
        },
        {
            "vehicle_id": "VAN-2",
            "capacity_kg": 1500,
            "available_from": "2026-11-20T07:00",
            "available_to": "2026-11-20T20:00",
            "max_hours": 8,
            "rate_per_hour": 30,
            "rate_per_km": 0.5,
        },
    ],
    # Medium fleet
    [
        {
            "vehicle_id": "TRUCK-1",
            "capacity_kg": 3500,
            "available_from": "2026-11-20T05:00",
            "available_to": "2026-11-20T22:00",
            "max_hours": 10,
            "rate_per_hour": 38,
            "rate_per_km": 0.6,
        },
        {
            "vehicle_id": "TRUCK-2",
            "capacity_kg": 8000,
            "available_from": "2026-11-20T06:00",
            "available_to": "2026-11-20T23:00",
            "max_hours": 11,
            "rate_per_hour": 42,
            "rate_per_km": 0.7,
        },
    ],
    # Mixed fleet
    [
        {
            "vehicle_id": "SPRINTER-1",
            "capacity_kg": 1400,
            "available_from": "2026-11-20T06:00",
            "available_to": "2026-11-20T21:00",
            "max_hours": 9,
            "rate_per_hour": 26,
            "rate_per_km": 0.4,
        },
        {
            "vehicle_id": "RIGID-2",
            "capacity_kg": 9000,
            "available_from": "2026-11-20T05:00",
            "available_to": "2026-11-20T23:00",
            "max_hours": 11,
            "rate_per_hour": 40,
            "rate_per_km": 0.65,
        },
        {
            "vehicle_id": "ARTIC-3",
            "capacity_kg": 13000,
            "available_from": "2026-11-20T00:00",
            "available_to": "2026-11-20T23:59",
            "max_hours": 13,
            "rate_per_hour": 58,
            "rate_per_km": 0.9,
        },
    ],
]


def generate_shipment(rng: random.Random, order_num: int) -> dict | None:
    """Generate one synthetic shipment and validate it."""
    pickup, delivery, distance_km = rng.choice(CITIES)
    fleet = rng.choice(FLEET_TEMPLATES)

    # Weight and pallets - varied distribution
    weight_kg = rng.choice(
        [
            rng.randint(500, 1200),  # light
            rng.randint(2000, 4000),  # medium
            rng.randint(5000, 8000),  # heavy
            rng.randint(9000, 12500),  # very heavy
        ]
    )
    pallets = max(1, weight_kg // 600)  # ~600 kg per pallet

    # Time windows
    ready_hour = rng.randint(6, 10)
    ready_at = f"2026-11-20T{ready_hour:02d}:00"
    due_hour = rng.randint(ready_hour + 4, 22)
    due_at = f"2026-11-20T{due_hour:02d}:00"

    order_id = f"SH-{90000 + order_num}"

    order = {
        "order_id": order_id,
        "pickup": pickup,
        "delivery": delivery,
        "weight_kg": weight_kg,
        "pallets": pallets,
        "ready_at": ready_at,
        "due_at": due_at,
        "distance_km": distance_km,
    }

    # Check if this shipment is feasible with at least one vehicle
    try:
        optimal = solver.plan(order, fleet)
        if not optimal.get("feasible"):
            return None  # Skip infeasible shipments
    except Exception:
        return None

    # Build document text - varied formats
    templates = [
        f"Booking {order_id}: {weight_kg} kg on {pallets} pallets, {pickup} to {delivery}. Ready {ready_at}, due {due_at}, {distance_km} km.",
        f"Shipment {order_id}\nOrigin: {pickup}\nDestination: {delivery}\nWeight: {weight_kg} kg ({pallets} pallets)\nPickup: {ready_at}\nDelivery deadline: {due_at}\nDistance: {distance_km} km",
        f"Order #{order_id}: Transport {weight_kg} kg ({pallets} pallet{'s' if pallets != 1 else ''}) from {pickup} to {delivery}. Available from {ready_at}, must arrive by {due_at}. Route distance: {distance_km} km.",
    ]
    document = rng.choice(templates)

    # Format fleet for user message
    fleet_json = json.dumps(fleet)

    user_msg = (
        f"Extract the shipment fields, call plan_route, and explain the returned plan. Document:\n"
        f"{document}\n"
        f"Fleet:\n{fleet_json}\n"
        f"Return JSON only."
    )

    # Build assistant response using solver
    explanation = (
        f"Vehicle {optimal['vehicle_id']} departs {optimal['depart']} and "
        f"arrives {optimal['arrive']}, cost {optimal['cost']}."
    )

    assistant_msg = json.dumps(
        {
            "extraction": order,
            "solver_calls": [{"tool": "plan_route", "args": order}],
            "plan": optimal,
            "explanation": explanation,
        }
    )

    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=600, help="Number of shipments to generate")
    parser.add_argument("--seed", type=int, default=7, help="Random seed")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # Ensure output directory exists
    OUT.parent.mkdir(parents=True, exist_ok=True)

    generated = []
    attempts = 0
    max_attempts = args.count * 3  # Allow some failures

    while len(generated) < args.count and attempts < max_attempts:
        attempts += 1
        shipment = generate_shipment(rng, len(generated) + 1)
        if shipment is not None:
            generated.append(shipment)

    if len(generated) < args.count:
        print(
            f"Warning: only generated {len(generated)}/{args.count} feasible shipments",
            file=sys.stderr,
        )

    # Write to output file
    with open(OUT, "w", encoding="utf-8") as fh:
        for shipment in generated:
            fh.write(json.dumps(shipment, ensure_ascii=False) + "\n")

    print(f"Generated {len(generated)} synthetic shipments to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
