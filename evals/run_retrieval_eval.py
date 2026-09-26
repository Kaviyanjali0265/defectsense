"""
Retrieval-only eval — measures the retriever (Chroma + nomic-embed-text) in isolation.
NO LLM calls, embeddings only. Answers: (A) is the retriever itself any good, before
ever handing its output to a model?

Requires evals/build_history.py to have been run first (populates the eval-only
history collections this script reads from — never live defect_history).

For each FAULT event in dataset.json (normal events skipped — nothing to retrieve
for), builds the query exactly as pipeline/flows.py's classify_defect() does, then
retrieves from four configurations:
  - with_filter_l2      : step filter + L2 distance   (mirrors live defect_history's
                           current unconfigured-default distance metric)
  - with_filter_cosine  : step filter + cosine distance (ablation)
  - without_filter_l2   : L2, no step filter            (ablation — shows what the
                           step filter is actually buying you)
  - random_baseline     : uniform-random pick from the same step's history pool,
                           no embedding ranking at all (seeded, reproducible)

Relevance = retrieved doc's mechanism == the event's ground-truth mechanism.
Reports recall@k / precision@k / nDCG@k for k in {1,2,5}, plus MRR, for each config,
with counts and Wilson intervals (small-n honesty).

The 8 unrecognized_pattern events are reported SEPARATELY (final section) — by
construction no history doc can ever be relevant to them (history only holds named
mechanisms, since a human never verifies "unrecognized" as a final answer), so the
interesting question there isn't recall — it's how often the retriever still
confidently hands back a misleading named-mechanism "similar case".

Usage:
    python evals/build_history.py        # once, before this
    python evals/run_retrieval_eval.py
"""
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.limits import label_all_readings
from core.vectorstore import get_all, search
from evals.build_history import (
    EVAL_HISTORY_COLLECTION_COSINE,
    EVAL_HISTORY_COLLECTION_L2,
)
from evals.retrieval_metrics import (
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    wilson_interval,
)

DATASET_PATH = Path(__file__).parent / "dataset.json"
K_VALUES = (1, 2, 5)
MAX_K = max(K_VALUES)
RANDOM_BASELINE_SEED = 123


def build_query(event: dict) -> str:
    """Exactly mirrors pipeline/flows.py classify_defect()'s query construction."""
    step = event["process_step"]
    labeled = label_all_readings(event["readings"])
    return f"{step} anomaly: " + ", ".join(
        f"{s} {r['label']}" for s, r in labeled.items() if r["label"] != "normal"
    )


def relevance_for(retrieved: list[dict], ground_truth: str) -> list[bool]:
    return [doc["metadata"].get("mechanism") == ground_truth for doc in retrieved]


def retrieve_with_filter(collection: str, query: str, step: str) -> list[dict]:
    return search(collection, query, n_results=MAX_K, where={"step": step})


def retrieve_without_filter(collection: str, query: str) -> list[dict]:
    return search(collection, query, n_results=MAX_K)


def retrieve_random_baseline(collection: str, step: str, rng: random.Random) -> list[dict]:
    pool = get_all(collection, where={"step": step})
    if not pool:
        return []
    k = min(MAX_K, len(pool))
    return rng.sample(pool, k)


def compute_config_metrics(per_event_relevance: list[list[bool]]) -> dict:
    """Aggregate metrics across all events for one retrieval configuration."""
    n = len(per_event_relevance)
    out = {"n": n}
    for k in K_VALUES:
        hits = [recall_at_k(rel, k) for rel in per_event_relevance]
        n_hits = sum(hits)
        lo, hi = wilson_interval(n_hits, n)
        out[f"recall@{k}"] = {
            "value": round(n_hits / n, 3) if n else 0.0,
            "count": f"{n_hits}/{n}",
            "wilson_95ci": [round(lo, 3), round(hi, 3)],
        }
        precisions = [precision_at_k(rel, k) for rel in per_event_relevance]
        out[f"precision@{k}"] = round(sum(precisions) / n, 3) if n else 0.0
        ndcgs = [ndcg_at_k(rel, k) for rel in per_event_relevance]
        out[f"nDCG@{k}"] = round(sum(ndcgs) / n, 3) if n else 0.0

    rrs = [reciprocal_rank(rel) for rel in per_event_relevance]
    out["MRR"] = round(sum(rrs) / n, 3) if n else 0.0
    return out


def run_config(events: list[dict], config_name: str, retrieve_fn) -> tuple[dict, list[dict]]:
    per_event_relevance = []
    per_event_detail = []
    for record in events:
        event = record["event"]
        gt = record["ground_truth"]
        retrieved = retrieve_fn(event)
        rel = relevance_for(retrieved, gt)
        per_event_relevance.append(rel)
        per_event_detail.append({
            "event_id": event["event_id"], "ground_truth": gt,
            "retrieved_mechanisms": [d["metadata"].get("mechanism") for d in retrieved],
            "relevance": rel,
        })
    return compute_config_metrics(per_event_relevance), per_event_detail


def run_unrecognized_section(unrecognized_events: list[dict]) -> dict:
    """No history doc can ever be relevant here — report how often a (necessarily
    misleading) named-mechanism case gets confidently returned anyway."""
    detail = []
    any_returned_top1 = 0
    any_returned_top2 = 0
    for record in unrecognized_events:
        event = record["event"]
        step = event["process_step"]
        query = build_query(event)
        retrieved = retrieve_with_filter(EVAL_HISTORY_COLLECTION_L2, query, step)
        top1 = bool(retrieved[:1])
        top2 = bool(retrieved[:2])
        any_returned_top1 += int(top1)
        any_returned_top2 += int(top2)
        detail.append({
            "event_id": event["event_id"], "step": step,
            "misleading_mechanisms_returned": [d["metadata"].get("mechanism") for d in retrieved[:2]],
        })
    n = len(unrecognized_events)
    lo1, hi1 = wilson_interval(any_returned_top1, n)
    lo2, hi2 = wilson_interval(any_returned_top2, n)
    return {
        "n": n,
        "misleading_case_returned_at_top1": {
            "count": f"{any_returned_top1}/{n}", "wilson_95ci": [round(lo1, 3), round(hi1, 3)],
        },
        "misleading_case_returned_at_top2": {
            "count": f"{any_returned_top2}/{n}", "wilson_95ci": [round(lo2, 3), round(hi2, 3)],
        },
        "detail": detail,
    }


def print_table(configs: dict) -> None:
    print("\n" + "=" * 88)
    print("RETRIEVAL EVAL — retriever only, no LLM calls")
    print("=" * 88)
    header = f"  {'config':22} {'n':>4} " + " ".join(f"{'R@'+str(k):>10}" for k in K_VALUES) \
             + " " + " ".join(f"{'nDCG@'+str(k):>10}" for k in K_VALUES) + f" {'MRR':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, m in configs.items():
        row = f"  {name:22} {m['n']:>4} "
        row += " ".join(f"{m[f'recall@{k}']['value']:>10.2f}" for k in K_VALUES)
        row += " " + " ".join(f"{m[f'nDCG@{k}']:>10.2f}" for k in K_VALUES)
        row += f" {m['MRR']:>8.2f}"
        print(row)
    print()
    for name, m in configs.items():
        print(f"  {name}:")
        for k in K_VALUES:
            r = m[f"recall@{k}"]
            print(f"    recall@{k}: {r['count']}  (95% CI {r['wilson_95ci']})")
    print()


def main():
    with open(DATASET_PATH) as f:
        dataset = json.load(f)

    fault_events = [r for r in dataset if r["slice"] != "normal"]
    named_events = [r for r in fault_events if r["slice"] != "unrecognized"]
    unrecognized_events = [r for r in fault_events if r["slice"] == "unrecognized"]

    print(f"Loaded {len(dataset)} events: {len(named_events)} named-mechanism fault events, "
          f"{len(unrecognized_events)} unrecognized_pattern events (reported separately).")

    configs = {}
    details = {}

    configs["with_filter_l2"], details["with_filter_l2"] = run_config(
        named_events, "with_filter_l2",
        lambda ev: retrieve_with_filter(EVAL_HISTORY_COLLECTION_L2, build_query(ev), ev["process_step"]),
    )
    configs["with_filter_cosine"], details["with_filter_cosine"] = run_config(
        named_events, "with_filter_cosine",
        lambda ev: retrieve_with_filter(EVAL_HISTORY_COLLECTION_COSINE, build_query(ev), ev["process_step"]),
    )
    configs["without_filter_l2"], details["without_filter_l2"] = run_config(
        named_events, "without_filter_l2",
        lambda ev: retrieve_without_filter(EVAL_HISTORY_COLLECTION_L2, build_query(ev)),
    )

    rng = random.Random(RANDOM_BASELINE_SEED)
    configs["random_baseline"], details["random_baseline"] = run_config(
        named_events, "random_baseline",
        lambda ev: retrieve_random_baseline(EVAL_HISTORY_COLLECTION_L2, ev["process_step"], rng),
    )

    print_table(configs)

    unrec = run_unrecognized_section(unrecognized_events)
    print("  Unrecognized-pattern events (no relevant case can exist by construction):")
    print(f"    misleading case returned @top1: {unrec['misleading_case_returned_at_top1']['count']}"
          f"  (95% CI {unrec['misleading_case_returned_at_top1']['wilson_95ci']})")
    print(f"    misleading case returned @top2: {unrec['misleading_case_returned_at_top2']['count']}"
          f"  (95% CI {unrec['misleading_case_returned_at_top2']['wilson_95ci']})")
    print()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(__file__).parent / f"retrieval_results_{timestamp}.json"
    with open(out_path, "w") as f:
        json.dump(
            {
                "timestamp": timestamp,
                "n_named_events": len(named_events),
                "n_unrecognized_events": len(unrecognized_events),
                "k_values": list(K_VALUES),
                "configs": configs,
                "unrecognized_section": unrec,
                "per_event_detail": details,
            },
            f, indent=2,
        )
    print(f"Saved full results to {out_path}\n")


if __name__ == "__main__":
    main()
