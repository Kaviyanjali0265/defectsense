"""
Builds a synthetic pool of VERIFIED-history documents for the retrieval eval suite,
in the exact same text/metadata format api/routes.py's _write_to_history() writes —
so retrieval behavior measured here matches what the live pipeline actually sees.

Written to eval-only Chroma collections (never live DEFECT_HISTORY_COLLECTION /
"defect_history"). Two collections are built with identical documents but different
distance metrics, for the cosine-vs-L2 ablation in run_retrieval_eval.py:
  - EVAL_HISTORY_COLLECTION_COSINE (hnsw:space="cosine")
  - EVAL_HISTORY_COLLECTION_L2     (hnsw:space="l2", Chroma's unconfigured default)
A third alias, EVAL_HISTORY_COLLECTION, points at the plain (L2) collection and is
what run_eval.py's WITH_HISTORY=1 mode reads from — same shape as production reads.

Uses SEED=7 (dataset.json uses 42) so the two pools never coincidentally overlap.
3-5 cases per mechanism (random.randint(3,5) per mechanism, seeded), for all 18 real
mechanisms (excl. unrecognized_pattern — a human never verifies "unrecognized" as a
final mechanism, so no history entries exist for it in the real system either).

Idempotent: doc_ids are deterministic (hist-eval-<mechanism>-<i>), so re-running just
upserts the same seeded content again — safe to re-run any time.

Usage:
    python evals/build_history.py
"""
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.limits import label_all_readings
from core.mechanisms import MECHANISMS, REPAIR_STEPS
from core.vectorstore import upsert
from ingest.generator import MACHINES, _readings_for

SEED = 7
CASES_PER_MECHANISM_RANGE = (3, 5)  # inclusive

EVAL_HISTORY_COLLECTION        = os.getenv("EVAL_HISTORY_COLLECTION", "eval_defect_history")
EVAL_HISTORY_COLLECTION_COSINE = os.getenv("EVAL_HISTORY_COLLECTION_COSINE", "eval_defect_history_cosine")
EVAL_HISTORY_COLLECTION_L2     = os.getenv("EVAL_HISTORY_COLLECTION_L2", "eval_defect_history_l2")

DATASET_PATH  = Path(__file__).parent / "dataset.json"
MANIFEST_PATH = Path(__file__).parent / "history_manifest.json"


def _fix_for(mechanism: str) -> str:
    steps = REPAIR_STEPS.get(mechanism, [])
    return steps[0] if steps else "not recorded"


def _build_case(mechanism: str, step: str, i: int) -> dict:
    readings = _readings_for(mechanism)
    labeled  = label_all_readings(readings)
    machine  = random.choice(MACHINES.get(step, [f"{step[:3].upper()}-01"]))
    fix      = _fix_for(mechanism)

    alarms = ", ".join(
        f"{s} {info['label']}" for s, info in labeled.items() if info.get("label") in ("HIGH", "LOW")
    ) or "none"

    text = (
        f"Verified defect at {step} on {machine}: "
        f"mechanism={mechanism}, alarms=[{alarms}], fix={fix}."
    )

    doc_id = f"hist-eval-{mechanism}-{i:02d}"
    timestamp = (datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat()

    return {
        "doc_id": doc_id,
        "text": text,
        "readings": readings,
        "metadata": {
            "event_id":    doc_id,
            "mechanism":   mechanism,
            "step":        step,
            "machine":     machine,
            "fix_applied": fix,
            "timestamp":   timestamp,
        },
    }


def build() -> list[dict]:
    random.seed(SEED)
    cases = []
    for mid, data in MECHANISMS.items():
        if mid == "unrecognized_pattern":
            continue
        step = data["step"]
        n = random.randint(*CASES_PER_MECHANISM_RANGE)
        for i in range(1, n + 1):
            cases.append(_build_case(mid, step, i))
    return cases


def _assert_zero_overlap(cases: list[dict]) -> None:
    if not DATASET_PATH.exists():
        print(f"WARNING: {DATASET_PATH} not found — skipping overlap check.")
        return
    with open(DATASET_PATH) as f:
        dataset = json.load(f)

    dataset_ids      = {r["event"]["event_id"] for r in dataset}
    dataset_readings = {tuple(sorted(r["event"]["readings"].items())) for r in dataset}

    for c in cases:
        assert c["doc_id"] not in dataset_ids, f"history doc_id collides with dataset event_id: {c['doc_id']}"
        r_key = tuple(sorted(c["readings"].items()))
        assert r_key not in dataset_readings, f"history readings collide with a dataset event: {c['doc_id']}"

    print(f"Zero-overlap check passed: {len(cases)} history cases vs {len(dataset)} dataset events "
          f"(event_id and readings, both dimensions).")


def write_to_collections(cases: list[dict]) -> None:
    # L2 collection doubles as EVAL_HISTORY_COLLECTION (the one WITH_HISTORY=1 reads from —
    # matches live "defect_history", which is also unconfigured/default-L2).
    targets = [
        (EVAL_HISTORY_COLLECTION_L2, {"hnsw:space": "l2"}),
        (EVAL_HISTORY_COLLECTION_COSINE, {"hnsw:space": "cosine"}),
    ]
    for collection_name, collection_metadata in targets:
        for c in cases:
            upsert(
                collection_name=collection_name,
                doc_id=c["doc_id"],
                text=c["text"],
                metadata=c["metadata"],
                collection_metadata=collection_metadata,
            )
        print(f"Wrote {len(cases)} docs → collection '{collection_name}' ({collection_metadata})")

    if EVAL_HISTORY_COLLECTION != EVAL_HISTORY_COLLECTION_L2:
        for c in cases:
            upsert(
                collection_name=EVAL_HISTORY_COLLECTION,
                doc_id=c["doc_id"],
                text=c["text"],
                metadata=c["metadata"],
                collection_metadata={"hnsw:space": "l2"},
            )
        print(f"Wrote {len(cases)} docs → collection '{EVAL_HISTORY_COLLECTION}' (alias, l2)")


def main():
    cases = build()
    print(f"Built {len(cases)} synthetic verified-history cases (seed={SEED}), "
          f"{len(MECHANISMS) - 1} mechanisms x {CASES_PER_MECHANISM_RANGE[0]}-{CASES_PER_MECHANISM_RANGE[1]} each.")

    _assert_zero_overlap(cases)
    write_to_collections(cases)

    with open(MANIFEST_PATH, "w") as f:
        json.dump(
            {"seed": SEED, "count": len(cases),
             "collections": [EVAL_HISTORY_COLLECTION, EVAL_HISTORY_COLLECTION_COSINE, EVAL_HISTORY_COLLECTION_L2],
             "cases": [{"doc_id": c["doc_id"], "metadata": c["metadata"]} for c in cases]},
            f, indent=2,
        )
    print(f"Manifest written to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
