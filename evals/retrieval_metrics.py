"""
Pure retrieval-quality metric functions — no embeddings, no I/O, no LLM calls.
Operate on a `relevance` list: one bool per retrieved doc, in retrieved rank order,
True if that doc's mechanism == the query's ground-truth mechanism.

Used by evals/run_retrieval_eval.py; kept separate and dependency-free so they're
directly unit-testable with hand-computed cases (see tests/test_retrieval_metrics.py).
"""
import math


def recall_at_k(relevance: list[bool], k: int) -> bool:
    """Hit rate: was there at least one relevant doc in the top-k? (single query)"""
    return any(relevance[:k])


def precision_at_k(relevance: list[bool], k: int) -> float:
    """Fraction of the top-k that are relevant. 0.0 if k <= 0."""
    if k <= 0:
        return 0.0
    top_k = relevance[:k]
    return sum(top_k) / len(top_k) if top_k else 0.0


def reciprocal_rank(relevance: list[bool]) -> float:
    """1 / rank of the first relevant doc (rank is 1-indexed). 0.0 if none relevant."""
    for i, rel in enumerate(relevance):
        if rel:
            return 1.0 / (i + 1)
    return 0.0


def dcg_at_k(relevance: list[bool], k: int) -> float:
    """Binary-relevance discounted cumulative gain over the top-k."""
    return sum(int(rel) / math.log2(i + 2) for i, rel in enumerate(relevance[:k]))


def ndcg_at_k(relevance: list[bool], k: int) -> float:
    """DCG@k normalized by the ideal DCG@k (relevant docs sorted to the front).
    Handles any number of relevant docs among the top-k, not just zero-or-one.
    0.0 if there are no relevant docs at all (ideal DCG would be 0)."""
    dcg = dcg_at_k(relevance, k)
    ideal = sorted(relevance, reverse=True)
    idcg = dcg_at_k(ideal, k)
    return dcg / idcg if idcg > 0 else 0.0


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion — more honest than a raw
    percentage when n is small (e.g. the 8-event unrecognized slice, or per-k
    breakdowns with few queries). Returns (low, high), both in [0, 1].
    (0.0, 0.0) if n == 0."""
    if n == 0:
        return (0.0, 0.0)
    p_hat = successes / n
    denom = 1 + z * z / n
    center = p_hat + z * z / (2 * n)
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z * z / (4 * n)) / n)
    return ((center - margin) / denom, (center + margin) / denom)
