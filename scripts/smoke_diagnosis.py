"""
Smoke test: detection + diagnosis directly (no Redis / Prefect / storage).
Usage:  python scripts/smoke_diagnosis.py
"""
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.limits import SENSOR_LIMITS, has_alarm, label_all_readings
from core.mechanisms import STEP_MECHANISMS
from ingest.generator import (
    DESIGNED_NOTE_CASES,
    _normal_value,
    generate_event,
    generate_note_case,
)
from pipeline.flows import (
    DiagnosisParseError,
    _signature_consistent,
    run_diagnosis,
)

LLM_MODEL         = os.getenv("LLM_MODEL", "llama3.2:3b")
N_EVENTS          = int(os.getenv("N_EVENTS", "15"))
NORMAL_RATE       = 0.20
UNRECOGNIZED_RATE = 0.15


def _make_normal(step: str) -> tuple[dict, str]:
    readings = {s: _normal_value(s) for s in SENSOR_LIMITS}
    event = {
        "event_id":      f"smoke-{random.randint(10000,99999)}",
        "wafer_id":      f"W-{random.randint(1000,9999)}",
        "machine_id":    f"{step[:3].upper()}-01",
        "process_step":  step,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "readings":      readings,
        "operator_note": None,
    }
    return event, "normal"


def _make_fault(mechanism_id: str, step: str) -> tuple[dict, str]:
    event, gt = generate_event(mechanism_id, step)
    event["event_id"] = f"smoke-{random.randint(10000,99999)}"
    return event, gt


def _build_event_list() -> list[tuple[dict, str, bool]]:
    """Returns list of (event, ground_truth, note_dependent)."""
    events: list[tuple[dict, str, bool]] = []

    # Guarantee all designed note cases appear exactly once
    for case in DESIGNED_NOTE_CASES:
        ev, gt, nd = generate_note_case(case)
        ev["event_id"] = f"smoke-{random.randint(10000,99999)}"
        events.append((ev, gt, nd))

    # Fill remaining slots randomly
    remaining = N_EVENTS - len(DESIGNED_NOTE_CASES)
    for _ in range(remaining):
        r    = random.random()
        step = random.choice(list(STEP_MECHANISMS.keys()))

        if r < NORMAL_RATE:
            ev, gt = _make_normal(step)
            events.append((ev, gt, False))
        elif r < NORMAL_RATE + UNRECOGNIZED_RATE:
            ev, gt = _make_fault("unrecognized_pattern", step)
            events.append((ev, gt, False))
        else:
            mech = random.choice(STEP_MECHANISMS[step])
            ev, gt = _make_fault(mech, step)
            events.append((ev, gt, False))

    random.shuffle(events)
    return events


def main():
    print(f"\nSmoke Diagnosis — model: {LLM_MODEL}  n={N_EVENTS}\n")
    header = (
        f"{'#':>3}  {'step':12} {'injected':28} {'predicted':28} "
        f"{'pos':5} {'sig':4} {'ok?':4} {'ptok':>5} {'etok':>5} {'ms':>6}"
    )
    print(header)
    print("-" * len(header))

    event_list = _build_event_list()
    results = []
    parse_failures          = 0
    note_cases: list[bool]  = []
    unrec_cases: list[bool] = []
    guardrail_wrong         = 0
    guardrail_false_pos     = 0

    for i, (event, gt, note_dependent) in enumerate(event_list):
        labeled   = label_all_readings(event["readings"])
        is_normal = not has_alarm(labeled)
        has_note  = bool(event.get("operator_note"))

        if is_normal:
            correct = gt == "normal"
            row = {"gt": gt, "predicted": "NORMAL_SKIP", "correct": correct,
                   "ms": 0, "pos": "-", "sig": "-", "ptok": 0, "etok": 0}
        else:
            t0 = time.perf_counter()
            try:
                diagnosis, order, ptok, etok = run_diagnosis(event, labeled, [])
                ms = int((time.perf_counter() - t0) * 1000)

                predicted = diagnosis.mechanism
                correct   = predicted == gt
                sig_ok    = _signature_consistent(predicted, labeled)

                try:
                    pos_idx = order.index(predicted) + 1
                    pos = f"{pos_idx}/{len(order)}"
                except ValueError:
                    pos = "?"

                if not sig_ok and not correct:
                    guardrail_wrong += 1
                if not sig_ok and correct:
                    guardrail_false_pos += 1

                row = {"gt": gt, "predicted": predicted, "correct": correct,
                       "ms": ms, "pos": pos, "sig": "YES" if sig_ok else "NO ",
                       "ptok": ptok, "etok": etok}

            except DiagnosisParseError as exc:
                ms = int((time.perf_counter() - t0) * 1000)
                parse_failures += 1
                row = {"gt": gt, "predicted": "PARSE_FAIL", "correct": False,
                       "ms": ms, "pos": "?", "sig": "?", "ptok": 0, "etok": 0,
                       "_exc": exc}

        if note_dependent:
            note_cases.append(row["correct"])
        if gt == "unrecognized_pattern":
            unrec_cases.append(row["correct"])

        note_marker = "*" if has_note else " "
        tick = "YES" if row["correct"] else "NO "
        print(
            f"{i+1:>3}{note_marker} {event['process_step']:12} {row['gt']:28} {row['predicted']:28} "
            f"{row['pos']:5} {row['sig']:4} {tick:4} {row['ptok']:>5} {row['etok']:>5} {row['ms']:>6}"
        )

        if row["predicted"] == "PARSE_FAIL":
            exc = row.get("_exc")
            print(f"       FAIL reason : {exc}")
            print(f"       FAIL raw    : {exc.raw[:300]!r}" if exc else "       FAIL raw    : (unavailable)")

        results.append(row)

    # ── summary ──────────────────────────────────────────────────────────────
    total   = len(results)
    correct = sum(1 for r in results if r["correct"])
    fault_r = [r for r in results if r["gt"] != "normal" and r["predicted"] != "NORMAL_SKIP"]
    f_cor   = sum(1 for r in fault_r if r["correct"])
    n_ok    = sum(1 for r in results if r["predicted"] == "NORMAL_SKIP" and r["gt"] == "normal")
    n_mis   = sum(1 for r in results if r["predicted"] == "NORMAL_SKIP" and r["gt"] != "normal")
    timed   = [r["ms"] for r in results if r["ms"] > 0]
    avg_ms  = int(sum(timed) / len(timed)) if timed else 0
    ptoks   = [r["ptok"] for r in results if r["ptok"] > 0]
    avg_pt  = int(sum(ptoks) / len(ptoks)) if ptoks else 0
    etoks   = [r["etok"] for r in results if r["etok"] > 0]
    avg_et  = int(sum(etoks) / len(etoks)) if etoks else 0

    llm_calls = [r for r in results if r["predicted"] not in ("NORMAL_SKIP",)]
    last_pos_count = sum(
        1 for r in llm_calls
        if isinstance(r["pos"], str) and "/" in r["pos"]
        and r["pos"].split("/")[0] == r["pos"].split("/")[1]
    )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total events          : {total}")
    print(f"  Overall accuracy      : {correct}/{total}  ({correct/total:.0%})")
    if fault_r:
        print(f"  Fault accuracy        : {f_cor}/{len(fault_r)}  ({f_cor/len(fault_r):.0%})")
    print(f"  Parse failures        : {parse_failures}")
    print(f"  Normal skip           : {n_ok} correct, {n_mis} missed")
    if note_cases:
        print(f"  Note-dep accuracy     : {sum(note_cases)}/{len(note_cases)}  ({sum(note_cases)/len(note_cases):.0%})  (* rows)")
    else:
        print("  Note-dep accuracy     : 0 cases seen")
    if unrec_cases:
        print(f"  Unrecognized acc      : {sum(unrec_cases)}/{len(unrec_cases)}  ({sum(unrec_cases)/len(unrec_cases):.0%})")
    else:
        print("  Unrecognized acc      : 0 cases seen")
    print(f"  Guardrail caught wrong: {guardrail_wrong}  (sig=NO, answer wrong → needs_review)")
    print(f"  Guardrail false-pos   : {guardrail_false_pos}  (sig=NO, answer correct)")
    print(f"  Last-position bias    : {last_pos_count}/{len(llm_calls)} predicted last in list")
    print(f"  Avg prompt tokens     : {avg_pt}")
    print(f"  Avg output tokens     : {avg_et}")
    print(f"  Avg ms per LLM call   : {avg_ms}")
    print()


if __name__ == "__main__":
    main()
