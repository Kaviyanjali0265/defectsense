"""
Builds the fixed, versioned eval dataset (evals/dataset.json) for DefectSense's
phase-2 eval suite. Reuses the REAL fault-injection logic from ingest/generator.py
(rather than duplicating it) so the eval set can never silently drift from what
the live generator actually produces.

Run once with a fixed seed → commit the resulting dataset.json. Re-run only if
the mechanism taxonomy or signature ranges change and the eval set needs to be
regenerated (in which case treat it as a new dataset version, since re-running
changes the composition and invalidates old results as an apples-to-apples
comparison point).

Composition (40 events total, 32 requiring an LLM call — ~20 min at ~38s/call):
  18 × one unambiguous case per mechanism (excl. unrecognized_pattern)
   6 × DESIGNED_NOTE_CASES (4 genuinely-ambiguous note-pairs, 2 neutral notes)
   8 × unrecognized_pattern, one per process step
   8 × normal (no-anomaly), one per process step — free, rule-based, no LLM call

Usage:
    python evals/build_dataset.py
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.limits import SENSOR_LIMITS, has_alarm, label_all_readings
from core.mechanisms import MECHANISMS, STEP_MECHANISMS
from ingest.generator import (
    DESIGNED_NOTE_CASES,
    _normal_value,
    _readings_for,
    _signature_value,
    _unrecognized_readings,
)

SEED = 42
OUT_PATH = Path(__file__).parent / "dataset.json"


def make_event(n: int, step: str, readings: dict, note: str | None = None) -> dict:
    return {
        "event_id":      f"eval-{n:03d}",
        "wafer_id":      f"W-EVAL-{n:03d}",
        "machine_id":    f"{step[:3].upper()}-01",
        "process_step":  step,
        "timestamp":     "2026-09-25T00:00:00+00:00",
        "readings":      readings,
        "operator_note": note,
    }


def build() -> list[dict]:
    random.seed(SEED)
    dataset = []
    n = 0

    # 1) One unambiguous event per mechanism (excl. unrecognized_pattern)
    for mid, data in MECHANISMS.items():
        if mid == "unrecognized_pattern":
            continue
        step = data["step"]
        readings = _readings_for(mid)
        labeled = label_all_readings(readings)
        assert has_alarm(labeled), f"{mid} produced no alarm: {labeled}"
        n += 1
        dataset.append({
            "event": make_event(n, step, readings),
            "ground_truth": mid, "slice": "unambiguous", "note_dependent": False,
        })

    # 2) Designed note cases
    for case in DESIGNED_NOTE_CASES:
        step, mech, rl = case["step"], case["mechanism"], case["readings_labels"]
        readings = _readings_for(mech) if not rl else {
            s: _signature_value(s, rl.get(s, "normal")) for s in SENSOR_LIMITS
        }
        labeled = label_all_readings(readings)
        assert has_alarm(labeled), f"note case {mech} produced no alarm: {labeled}"
        n += 1
        dataset.append({
            "event": make_event(n, step, readings, note=case["note"]),
            "ground_truth": mech,
            "slice": "note_dependent" if case["note_dependent"] else "note_neutral",
            "note_dependent": case["note_dependent"],
        })

    # 3) unrecognized_pattern — one per step
    for step in STEP_MECHANISMS:
        readings = _unrecognized_readings(step)
        labeled = label_all_readings(readings)
        assert has_alarm(labeled), f"unrecognized {step} produced no alarm: {labeled}"
        n += 1
        dataset.append({
            "event": make_event(n, step, readings),
            "ground_truth": "unrecognized_pattern", "slice": "unrecognized", "note_dependent": False,
        })

    # 4) normal — one per step (free: no LLM call, rule-based skip)
    for step in STEP_MECHANISMS:
        readings = {s: _normal_value(s) for s in SENSOR_LIMITS}
        labeled = label_all_readings(readings)
        assert not has_alarm(labeled), f"'normal' {step} accidentally alarmed: {labeled}"
        n += 1
        dataset.append({
            "event": make_event(n, step, readings),
            "ground_truth": "normal", "slice": "normal", "note_dependent": False,
        })

    return dataset


def main():
    dataset = build()
    with open(OUT_PATH, "w") as f:
        json.dump(dataset, f, indent=2)

    from collections import Counter
    llm_calls = sum(1 for d in dataset if d["ground_truth"] != "normal")
    print(f"Built {len(dataset)} events → {OUT_PATH}")
    print("By slice:", dict(Counter(d["slice"] for d in dataset)))
    print(f"LLM calls required: {llm_calls} (~{llm_calls * 38 // 60}m{llm_calls * 38 % 60}s at ~38s/call)")


if __name__ == "__main__":
    main()
