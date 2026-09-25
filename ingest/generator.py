"""Fault injector — emits full sensor snapshots. Ground truth logged separately."""
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from core.limits import SENSOR_LIMITS
from core.mechanisms import MECHANISMS, STEP_MECHANISMS

API_URL = "http://localhost:8000/ingest/event"
GROUND_TRUTH_LOG = Path(__file__).parent / "injected_log.jsonl"

# Machines per step
MACHINES = {step: [f"{step.upper()[:3]}-01", f"{step.upper()[:3]}-02"] for step in STEP_MECHANISMS}

# Designed note cases: specific readings + note that either disambiguates (note_dependent=True)
# or neutrally confirms (note_dependent=False). No random notes on ordinary fault events.
DESIGNED_NOTE_CASES = [
    # CMP pair — identical readings (vibration HIGH + particle_count HIGH), note decides
    {
        "step": "cmp",
        "mechanism": "head_bearing_wear",
        "readings_labels": {"vibration": "HIGH", "particle_count": "HIGH"},
        "note": "Polishing pad replaced yesterday",
        "note_dependent": True,
    },
    {
        "step": "cmp",
        "mechanism": "polishing_pad_wear",
        "readings_labels": {"vibration": "HIGH", "particle_count": "HIGH"},
        "note": "Head bearings replaced last week",
        "note_dependent": True,
    },
    # Etching pair — identical readings (pressure HIGH + flow_rate slightly_high), note decides
    {
        "step": "etching",
        "mechanism": "mfc_drift",
        "readings_labels": {"pressure": "HIGH", "flow_rate": "slightly_high"},
        "note": "Exhaust line cleaned last shift",
        "note_dependent": True,
    },
    {
        "step": "etching",
        "mechanism": "exhaust_valve_blockage",
        "readings_labels": {"pressure": "HIGH", "flow_rate": "slightly_high"},
        "note": "MFC recalibrated yesterday",
        "note_dependent": True,
    },
    # Neutral confirming cases
    {
        "step": "wet_clean",
        "mechanism": "chemical_bath_contamination",
        "readings_labels": {},
        "note": "Bath last replaced 3 days ago",
        "note_dependent": False,
    },
    {
        "step": "diffusion",
        "mechanism": "heater_degradation",
        "readings_labels": {},
        "note": "PID controller not recalibrated this quarter",
        "note_dependent": False,
    },
]


def _normal_value(sensor: str) -> float:
    cfg = SENSOR_LIMITS[sensor]
    lo = cfg["normal_low"] or cfg["alarm_low"] or 0
    hi = cfg["normal_high"]
    return round(random.uniform(lo, hi), 2)


def _signature_value(sensor: str, label: str) -> float:
    """Generate a value that will always label exactly as intended — no post-noise."""
    cfg = SENSOR_LIMITS[sensor]
    n_lo = cfg["normal_low"] or 0.0
    n_hi = cfg["normal_high"]
    a_lo = cfg["alarm_low"]
    a_hi = cfg["alarm_high"]

    if label == "HIGH":
        # strictly above alarm_high
        base = a_hi if a_hi is not None else n_hi
        val = base * random.uniform(1.06, 1.25)
    elif label == "LOW":
        # strictly below alarm_low
        base = a_lo if a_lo is not None else n_lo
        val = base * random.uniform(0.75, 0.93) if base > 0 else 0.01
    elif label == "slightly_high":
        # strictly between normal_high and alarm_high — margin must survive round(val, 2)
        lo = n_hi + max(n_hi * 0.001, 0.02)
        hi = (a_hi - max(a_hi * 0.001, 0.02)) if a_hi is not None else n_hi * 1.08
        val = random.uniform(lo, hi)
    elif label == "slightly_low":
        if n_lo == 0.0:
            val = _normal_value(sensor)  # no low band defined
        else:
            lo = (a_lo + max(a_lo * 0.001, 0.02)) if a_lo is not None else n_lo * 0.92
            hi = n_lo - max(n_lo * 0.001, 0.02)
            val = random.uniform(lo, hi)
    else:
        val = _normal_value(sensor)

    return round(val, 2)


def _readings_for(mechanism_id: str) -> dict:
    sig = MECHANISMS[mechanism_id]["signature"]
    readings = {}
    for sensor in SENSOR_LIMITS:
        label = sig.get(sensor, "normal")
        readings[sensor] = _signature_value(sensor, label)
    return readings


def _unrecognized_readings(step: str) -> dict:
    """Produce readings that don't match any mechanism for this step."""
    # Pick a sensor that has no HIGH signature in any mechanism for this step
    step_mechs = STEP_MECHANISMS.get(step, [])
    high_sensors: set[str] = set()
    for mid in step_mechs:
        for s, lbl in MECHANISMS[mid]["signature"].items():
            if lbl in ("HIGH", "LOW"):
                high_sensors.add(s)

    # Use a sensor NOT high for this step to trigger HIGH (guaranteed no match)
    candidates = [s for s in SENSOR_LIMITS if s not in high_sensors]
    if not candidates:
        candidates = list(SENSOR_LIMITS.keys())

    readings = {s: _normal_value(s) for s in SENSOR_LIMITS}
    chosen = random.choice(candidates)
    readings[chosen] = _signature_value(chosen, "HIGH")
    return readings


def generate_event(mechanism_id: str | None = None, step: str | None = None) -> tuple[dict, str]:
    """Returns (event_dict, ground_truth_mechanism)."""
    if step is None:
        step = random.choice(list(STEP_MECHANISMS.keys()))

    if mechanism_id is None:
        mechanism_id = random.choice(STEP_MECHANISMS[step])

    if mechanism_id == "unrecognized_pattern":
        readings = _unrecognized_readings(step)
        ground_truth = "unrecognized_pattern"
    else:
        readings = _readings_for(mechanism_id)
        ground_truth = mechanism_id

    event = {
        "wafer_id":     f"W-{random.randint(1000, 9999)}",
        "machine_id":   random.choice(MACHINES.get(step, [f"{step[:3].upper()}-01"])),
        "process_step": step,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "readings":     readings,
        "operator_note": None,
    }
    return event, ground_truth


def generate_note_case(case: dict | None = None) -> tuple[dict, str, bool]:
    """Returns (event, ground_truth, note_dependent). Uses a DESIGNED_NOTE_CASES entry."""
    if case is None:
        case = random.choice(DESIGNED_NOTE_CASES)

    step           = case["step"]
    mechanism      = case["mechanism"]
    readings_labels = case.get("readings_labels", {})

    if readings_labels:
        # Build from explicit sensor labels; everything else normal
        readings = {s: _signature_value(s, readings_labels.get(s, "normal")) for s in SENSOR_LIMITS}
    else:
        readings = _readings_for(mechanism)

    event = {
        "wafer_id":      f"W-{random.randint(1000, 9999)}",
        "machine_id":    random.choice(MACHINES.get(step, [f"{step[:3].upper()}-01"])),
        "process_step":  step,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "readings":      readings,
        "operator_note": case["note"],
    }
    return event, mechanism, case["note_dependent"]


def _log_ground_truth(event_id: str, ground_truth: str, step: str):
    with open(GROUND_TRUTH_LOG, "a") as f:
        f.write(json.dumps({"event_id": event_id, "mechanism": ground_truth, "step": step}) + "\n")


def run(count: int = 40, normal_rate: float = 0.2, unrecognized_rate: float = 0.05,
        note_rate: float = 0.10, delay: float = 0.5):
    print(f"Sending {count} events (normal: {normal_rate*100:.0f}%, unrecognized: {unrecognized_rate*100:.0f}%, note: {note_rate*100:.0f}%)...\n")
    GROUND_TRUTH_LOG.parent.mkdir(parents=True, exist_ok=True)

    for i in range(count):
        r = random.random()

        if r < normal_rate:
            step = random.choice(list(STEP_MECHANISMS.keys()))
            readings = {s: _normal_value(s) for s in SENSOR_LIMITS}
            event = {
                "wafer_id":     f"W-{random.randint(1000, 9999)}",
                "machine_id":   random.choice(MACHINES.get(step, [f"{step[:3].upper()}-01"])),
                "process_step": step,
                "timestamp":    datetime.now(timezone.utc).isoformat(),
                "readings":     readings,
                "operator_note": None,
            }
            ground_truth = "normal"
        elif r < normal_rate + unrecognized_rate:
            step = random.choice(list(STEP_MECHANISMS.keys()))
            event, ground_truth = generate_event("unrecognized_pattern", step)
        elif r < normal_rate + unrecognized_rate + note_rate:
            event, ground_truth, _ = generate_note_case()
        else:
            step = random.choice(list(STEP_MECHANISMS.keys()))
            event, ground_truth = generate_event(step=step)

        try:
            resp = httpx.post(API_URL, json=event, timeout=5)
            data = resp.json()
            event_id = data.get("event_id", "?")
            _log_ground_truth(event_id, ground_truth, event["process_step"])
            print(f"[{ground_truth[:20]:20}] {event['wafer_id']} | {event['process_step']:12} → {event_id[:8]}...")
        except (httpx.HTTPError, KeyError, ValueError) as e:
            print(f"Error: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    run()
