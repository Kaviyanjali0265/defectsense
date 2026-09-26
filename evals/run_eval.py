"""
Phase-2 eval suite for DefectSense diagnosis quality.

Distinct from scripts/smoke_diagnosis.py (live-random, small-n, for quick
iteration during development). This script runs against a FIXED, versioned
dataset (evals/dataset.json) so results are reproducible run-to-run and
comparable across model / prompt changes — the same reasoning that led us
to pin the model via seeded A/B comparison earlier.

Dataset (40 events, evals/dataset.json, generated once — see
evals/build_dataset.py for how):
  - 18 events: one unambiguous case per mechanism (excl. unrecognized_pattern)
  - 6 events:  the DESIGNED_NOTE_CASES (4 genuinely-ambiguous note-pairs +
               2 neutral confirming notes) from ingest/generator.py
  - 8 events:  unrecognized_pattern, one per process step
  - 8 events:  normal (no-anomaly), one per process step — free: these never
               reach the LLM (has_alarm() short-circuits them), so they add
               ~zero runtime while covering the rule-based detector fully.

Only 32 of the 40 events call the LLM (~35-40s each ⇒ roughly 20 minutes
total on llama3.2:3b on typical hardware).

Diagnosis is run with an EMPTY verified_history by default (WITH_HISTORY unset) —
same choice smoke_diagnosis.py makes — so results don't drift as defect_history
accumulates between runs. Set WITH_HISTORY=1 to instead retrieve from the eval-only
history collection (built by evals/build_history.py; never live defect_history) using
the exact same query construction as classify_defect(), to measure whether retrieval
actually helps diagnosis (goal B of the RAG eval — see evals/run_retrieval_eval.py
for goal A, the retriever measured in isolation with no LLM calls).

Usage:
    python evals/run_eval.py
    LLM_MODEL=qwen2.5:3b python evals/run_eval.py   # compare a different model
    WITH_HISTORY=1 python evals/run_eval.py         # measure history's effect on diagnosis
    LLM_PROVIDER=groq python evals/run_eval.py       # compare a different provider

Writes evals/results_<provider>_<model>_<hist-on|hist-off>_<timestamp>.json and
prints a summary report. Never mutates live defect_history, Redis, or the report
store — this is read-only against a local JSON file, using the same run_diagnosis()
the real pipeline calls.
"""
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.limits import has_alarm, label_all_readings
from core.mechanisms import CATEGORY
from core.vectorstore import search
from evals.build_history import EVAL_HISTORY_COLLECTION
from pipeline.flows import (
    CONFIDENCE_THRESHOLD,
    LLM_MODEL,
    LLM_PROVIDER,
    DiagnosisParseError,
    _note_contradicts_pick,
    _signature_consistent,
    run_diagnosis,
)

DATASET_PATH = Path(__file__).parent / "dataset.json"

# Default unchanged (WITH_HISTORY unset -> verified_history=[], same as always).
# When set, retrieves from the eval-only history collection (never live
# defect_history) using the exact same query construction as classify_defect.
WITH_HISTORY = os.getenv("WITH_HISTORY", "0") == "1"


def _fetch_eval_history(event: dict, labeled: dict) -> list[dict]:
    """Mirrors pipeline/flows.py classify_defect()'s history retrieval exactly,
    just pointed at the eval-only collection instead of live defect_history."""
    step = event["process_step"]
    query = (
        f"{step} anomaly: "
        + ", ".join(f"{s} {r['label']}" for s, r in labeled.items() if r["label"] != "normal")
    )
    history_raw = search(EVAL_HISTORY_COLLECTION, query, n_results=2, where={"step": step})
    return [h["metadata"] for h in history_raw]


def _status_for(mechanism, sig_ok, note_conflict, confidence):
    """Mirror generate_report()'s status/review_reason decision exactly."""
    if mechanism == "unrecognized_pattern":
        return "needs_review", "unrecognized_pattern"
    if note_conflict:
        return "needs_review", "model's own reasoning contradicts its pick"
    if not sig_ok:
        return "needs_review", "signature mismatch"
    if confidence < CONFIDENCE_THRESHOLD:
        return "needs_review", "low confidence"
    return "triaged", None


def run_one(record: dict) -> dict:
    event = record["event"]
    gt    = record["ground_truth"]
    slice_name = record["slice"]

    labeled   = label_all_readings(event["readings"])
    is_normal = not has_alarm(labeled)

    out = {
        "event_id": event["event_id"], "step": event["process_step"],
        "ground_truth": gt, "slice": slice_name,
        "note_dependent": record["note_dependent"],
        "has_note": bool(event.get("operator_note")),
    }

    if is_normal:
        out.update(predicted="normal", correct=(gt == "normal"), status="skipped_normal",
                    review_reason=None, confidence=None, sig_ok=None, note_conflict=None,
                    position=None, ms=0, history_has_gt=None)
        return out

    verified_history = _fetch_eval_history(event, labeled) if WITH_HISTORY else []
    out["history_has_gt"] = (
        any(h.get("mechanism") == gt for h in verified_history) if WITH_HISTORY else None
    )

    t0 = time.perf_counter()
    try:
        diagnosis, order, ptok, etok = run_diagnosis(event, labeled, verified_history)
        ms = int((time.perf_counter() - t0) * 1000)
        predicted = diagnosis.mechanism
        sig_ok = _signature_consistent(predicted, labeled)
        note_conflict = _note_contradicts_pick(predicted, diagnosis.reasoning, diagnosis.explanation)
        status, review_reason = _status_for(predicted, sig_ok, note_conflict, diagnosis.confidence)
        try:
            pos = order.index(predicted) + 1
            position = f"{pos}/{len(order)}"
            last_position = pos == len(order)
        except ValueError:
            position, last_position = None, False

        out.update(
            predicted=predicted, correct=(predicted == gt), status=status,
            review_reason=review_reason, confidence=diagnosis.confidence,
            sig_ok=sig_ok, note_conflict=note_conflict, position=position,
            last_position=last_position, prompt_tokens=ptok, output_tokens=etok, ms=ms,
        )
    except DiagnosisParseError as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        out.update(predicted="PARSE_FAIL", correct=False, status="parse_failed",
                    review_reason=str(exc), confidence=None, sig_ok=None,
                    note_conflict=None, position=None, last_position=False, ms=ms)
    return out


def compute_metrics(results: list[dict]) -> dict:
    m = {}
    total = len(results)
    m["total_events"] = total
    m["overall_accuracy"] = round(sum(r["correct"] for r in results) / total, 3)

    fault = [r for r in results if r["slice"] != "normal"]
    m["fault_accuracy"] = round(sum(r["correct"] for r in fault) / len(fault), 3) if fault else None

    # per-category (skip normal/unrecognized, which have no MECHANISMS category)
    cat_acc = defaultdict(lambda: [0, 0])
    for r in fault:
        if r["slice"] == "unrecognized":
            continue
        cat = CATEGORY.get(r["ground_truth"], "unclassified")
        cat_acc[cat][1] += 1
        cat_acc[cat][0] += int(r["correct"])
    m["accuracy_by_category"] = {k: f"{v[0]}/{v[1]} ({v[0]/v[1]:.0%})" for k, v in cat_acc.items()}

    # per-step
    step_acc = defaultdict(lambda: [0, 0])
    for r in results:
        step_acc[r["step"]][1] += 1
        step_acc[r["step"]][0] += int(r["correct"])
    m["accuracy_by_step"] = {k: f"{v[0]}/{v[1]} ({v[0]/v[1]:.0%})" for k, v in step_acc.items()}

    # confusion matrix (fault events only, excluding unrecognized/normal ground truths)
    confusion = defaultdict(lambda: defaultdict(int))
    for r in fault:
        if r["slice"] == "unrecognized":
            continue
        confusion[r["ground_truth"]][r["predicted"]] += 1
    m["confusion_matrix"] = {k: dict(v) for k, v in confusion.items()}

    # confidence calibration
    buckets = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    calib = {}
    scored = [r for r in fault if r.get("confidence") is not None]
    for lo, hi in buckets:
        in_bucket = [r for r in scored if lo <= r["confidence"] < hi]
        if in_bucket:
            acc = sum(r["correct"] for r in in_bucket) / len(in_bucket)
            calib[f"{lo:.1f}-{hi if hi <= 1 else 1.0:.1f}"] = f"{sum(r['correct'] for r in in_bucket)}/{len(in_bucket)} ({acc:.0%})"
    m["confidence_calibration"] = calib

    # guardrail effectiveness
    wrong = [r for r in fault if not r["correct"] and r["status"] != "parse_failed"]
    wrong_caught = sum(1 for r in wrong if r["status"] == "needs_review")
    m["guardrail_effectiveness"] = {
        "wrong_diagnoses_total": len(wrong),
        "wrong_caught_as_needs_review": wrong_caught,
        "wrong_slipped_through_as_triaged": len(wrong) - wrong_caught,
        "catch_rate": round(wrong_caught / len(wrong), 3) if wrong else None,
    }
    correct_but_flagged = [r for r in fault if r["correct"] and r["status"] == "needs_review"]
    m["guardrail_false_positive_rate"] = {
        "correct_diagnoses_total": len(fault) - len(wrong),
        "correct_but_flagged_needs_review": len(correct_but_flagged),
    }

    # note-dependent subset
    note_dep = [r for r in results if r["note_dependent"]]
    if note_dep:
        m["note_dependent_accuracy"] = f"{sum(r['correct'] for r in note_dep)}/{len(note_dep)} ({sum(r['correct'] for r in note_dep)/len(note_dep):.0%})"

    # unrecognized_pattern precision/recall
    unrec_recall_set = [r for r in results if r["slice"] == "unrecognized"]
    unrec_pred_set = [r for r in results if r["predicted"] == "unrecognized_pattern"]
    if unrec_recall_set:
        m["unrecognized_recall"] = f"{sum(r['correct'] for r in unrec_recall_set)}/{len(unrec_recall_set)} ({sum(r['correct'] for r in unrec_recall_set)/len(unrec_recall_set):.0%})"
    if unrec_pred_set:
        tp = sum(1 for r in unrec_pred_set if r["ground_truth"] == "unrecognized_pattern")
        m["unrecognized_precision"] = f"{tp}/{len(unrec_pred_set)} ({tp/len(unrec_pred_set):.0%})"

    # normal true-negative rate
    normal = [r for r in results if r["slice"] == "normal"]
    if normal:
        m["normal_true_negative_rate"] = f"{sum(r['correct'] for r in normal)}/{len(normal)} ({sum(r['correct'] for r in normal)/len(normal):.0%})"

    # position bias
    llm_events = [r for r in results if r["slice"] != "normal" and r["status"] != "parse_failed"]
    last_pos = sum(1 for r in llm_events if r.get("last_position"))
    if llm_events:
        m["last_position_bias"] = f"{last_pos}/{len(llm_events)} ({last_pos/len(llm_events):.0%})"

    m["parse_failures"] = sum(1 for r in results if r["status"] == "parse_failed")
    timed = [r["ms"] for r in results if r["ms"] > 0]
    m["avg_ms_per_llm_call"] = int(sum(timed) / len(timed)) if timed else 0

    return m


def print_report(model: str, metrics: dict) -> None:
    print("\n" + "=" * 72)
    print(f"DEFECTSENSE EVAL — model: {model}")
    print("=" * 72)
    print(f"  Total events            : {metrics['total_events']}")
    print(f"  Overall accuracy        : {metrics['overall_accuracy']:.0%}")
    if metrics["fault_accuracy"] is not None:
        print(f"  Fault accuracy          : {metrics['fault_accuracy']:.0%}")
    print(f"  Parse failures          : {metrics['parse_failures']}")
    print(f"  Avg ms/LLM call         : {metrics['avg_ms_per_llm_call']}")

    print("\n  Accuracy by category:")
    for k, v in metrics["accuracy_by_category"].items():
        print(f"    {k:24} {v}")

    print("\n  Accuracy by process step:")
    for k, v in metrics["accuracy_by_step"].items():
        print(f"    {k:24} {v}")

    print("\n  Confidence calibration (bucket → accuracy):")
    for k, v in metrics["confidence_calibration"].items():
        print(f"    {k:12} {v}")

    print("\n  Guardrail effectiveness (wrong diagnoses):")
    ge = metrics["guardrail_effectiveness"]
    print(f"    wrong total={ge['wrong_diagnoses_total']}  caught={ge['wrong_caught_as_needs_review']}  "
          f"slipped_through_as_triaged={ge['wrong_slipped_through_as_triaged']}  "
          f"catch_rate={ge['catch_rate']}")
    fp = metrics["guardrail_false_positive_rate"]
    print(f"    correct total={fp['correct_diagnoses_total']}  wrongly_flagged_needs_review={fp['correct_but_flagged_needs_review']}")

    if "note_dependent_accuracy" in metrics:
        print(f"\n  Note-dependent subset accuracy : {metrics['note_dependent_accuracy']}")
    if "unrecognized_recall" in metrics:
        print(f"  Unrecognized_pattern recall    : {metrics['unrecognized_recall']}")
    if "unrecognized_precision" in metrics:
        print(f"  Unrecognized_pattern precision : {metrics['unrecognized_precision']}")
    if "normal_true_negative_rate" in metrics:
        print(f"  Normal true-negative rate      : {metrics['normal_true_negative_rate']}")
    if "last_position_bias" in metrics:
        print(f"  Last-position bias             : {metrics['last_position_bias']}")

    print("\n  Confusion matrix (ground truth → predicted counts):")
    for gt, preds in metrics["confusion_matrix"].items():
        wrong_preds = {k: v for k, v in preds.items() if k != gt}
        if wrong_preds:
            print(f"    {gt:28} misclassified as: {wrong_preds}")
    print()


def main():
    with open(DATASET_PATH) as f:
        dataset = json.load(f)

    limit = os.getenv("EVAL_LIMIT")
    if limit:
        limit = min(int(limit), len(dataset))
        random.seed(42)  # reproducible subset, still representative across all slices
        dataset = random.sample(dataset, limit)

    history_tag = "hist-on" if WITH_HISTORY else "hist-off"
    print(f"\nLoaded {len(dataset)} events from {DATASET_PATH.name}" + (f" (EVAL_LIMIT={limit})" if limit else ""))
    print(f"Provider: {LLM_PROVIDER}  Model: {LLM_MODEL}  History: {history_tag}\n")

    results = []
    for i, record in enumerate(dataset):
        r = run_one(record)
        results.append(r)
        tick = "skip" if r["status"] == "skipped_normal" else ("OK  " if r["correct"] else "WRONG")
        print(f"  [{i+1:>2}/{len(dataset)}] {r['step']:12} gt={r['ground_truth']:26} "
              f"pred={r['predicted']!s:26} {tick}  ({r['ms']}ms)")

    metrics = compute_metrics(results)
    print_report(LLM_MODEL, metrics)
    if WITH_HISTORY:
        scored = [r for r in results if r.get("history_has_gt") is not None]
        n_has_gt = sum(1 for r in scored if r["history_has_gt"])
        print(f"  History contained ground-truth mechanism: {n_has_gt}/{len(scored)}\n")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = LLM_MODEL.replace(":", "-").replace("/", "-")
    safe_provider = LLM_PROVIDER.replace(":", "-").replace("/", "-")
    out_path = Path(__file__).parent / f"results_{safe_provider}_{safe_model}_{history_tag}_{timestamp}.json"
    with open(out_path, "w") as f:
        json.dump(
            {
                "provider": LLM_PROVIDER, "model": LLM_MODEL, "history": "on" if WITH_HISTORY else "off",
                "timestamp": timestamp, "metrics": metrics, "raw_results": results,
            },
            f, indent=2,
        )
    print(f"Saved full results to {out_path}\n")


if __name__ == "__main__":
    main()
