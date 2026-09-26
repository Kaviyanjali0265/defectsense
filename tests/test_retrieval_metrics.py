"""Unit tests for evals/retrieval_metrics.py — pure functions, hand-computed cases."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.retrieval_metrics import (
    dcg_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    wilson_interval,
)


class TestRecallAtK:
    def test_hit_at_first_position(self):
        assert recall_at_k([True, False, False], 1) is True

    def test_hit_within_k(self):
        assert recall_at_k([False, False, True, False], 3) is True

    def test_hit_outside_k(self):
        assert recall_at_k([False, False, False, True], 2) is False

    def test_no_relevant_at_all(self):
        assert recall_at_k([False, False, False], 5) is False


class TestPrecisionAtK:
    def test_all_relevant(self):
        assert precision_at_k([True, True, True], 3) == 1.0

    def test_half_relevant(self):
        assert precision_at_k([True, False], 2) == 0.5

    def test_one_of_three(self):
        assert precision_at_k([False, True, False], 3) == pytest.approx(1 / 3)

    def test_k_smaller_than_list(self):
        # only the top-1 counts, even though list has a later hit
        assert precision_at_k([False, True, True], 1) == 0.0

    def test_zero_k(self):
        assert precision_at_k([True, True], 0) == 0.0


class TestReciprocalRank:
    def test_first_position(self):
        assert reciprocal_rank([True, False, False]) == 1.0

    def test_second_position(self):
        assert reciprocal_rank([False, True, False]) == 0.5

    def test_third_position(self):
        assert reciprocal_rank([False, False, True]) == pytest.approx(1 / 3)

    def test_no_relevant(self):
        assert reciprocal_rank([False, False, False]) == 0.0


class TestDCGAndNDCG:
    def test_dcg_single_hit_at_top(self):
        # rel=[1,0,0,0,0] -> DCG@k = 1/log2(2) = 1.0
        assert dcg_at_k([True, False, False, False, False], 5) == 1.0

    def test_dcg_single_hit_at_second(self):
        # rel=[0,1,0] -> DCG@2 = 0/log2(2) + 1/log2(3)
        expected = 1 / math.log2(3)
        assert dcg_at_k([False, True, False], 2) == pytest.approx(expected)

    def test_dcg_no_hits(self):
        assert dcg_at_k([False, False, False], 3) == 0.0

    def test_ndcg_perfect_when_hit_is_first(self):
        # ideal DCG@k for a single relevant doc IS "relevant at rank 1" -> nDCG = 1.0
        assert ndcg_at_k([True, False, False], 3) == 1.0

    def test_ndcg_hand_computed_hit_at_second(self):
        # rel=[False, True, False, False, False], k=2
        # DCG@2 = 0 + 1/log2(3) = 0.630929...
        # ideal@2 = [True, False] -> IDCG@2 = 1/log2(2) = 1.0
        # nDCG@2 = 0.630929...
        relevance = [False, True, False, False, False]
        expected_dcg = 1 / math.log2(3)
        assert ndcg_at_k(relevance, 2) == pytest.approx(expected_dcg)

    def test_ndcg_multiple_relevant_already_ideal_order(self):
        # rel=[True, True, False] -> DCG@3 = 1/log2(2) + 1/log2(3) + 0
        # ideal = [True, True, False] (already sorted) -> IDCG == DCG -> nDCG = 1.0
        assert ndcg_at_k([True, True, False], 3) == pytest.approx(1.0)

    def test_ndcg_multiple_relevant_out_of_order(self):
        # rel=[False, True, True], k=3
        # DCG@3 = 0 + 1/log2(3) + 1/log2(4)
        # ideal = [True, True, False] -> IDCG@3 = 1/log2(2) + 1/log2(3)
        relevance = [False, True, True]
        dcg = 1 / math.log2(3) + 1 / math.log2(4)
        idcg = 1 / math.log2(2) + 1 / math.log2(3)
        expected = dcg / idcg
        assert ndcg_at_k(relevance, 3) == pytest.approx(expected)

    def test_ndcg_no_relevant_is_zero(self):
        assert ndcg_at_k([False, False, False], 3) == 0.0


class TestWilsonInterval:
    def test_zero_n_returns_zero_zero(self):
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_perfect_score_interval_not_degenerate(self):
        # 5/5 successes still has a lower bound < 1.0 (Wilson doesn't overclaim on small n)
        lo, hi = wilson_interval(5, 5)
        assert 0.0 < lo < 1.0
        assert hi == pytest.approx(1.0, abs=1e-6)

    def test_zero_score_interval_not_degenerate(self):
        lo, hi = wilson_interval(0, 5)
        assert lo == pytest.approx(0.0, abs=1e-6)
        assert 0.0 < hi < 1.0

    def test_half_and_half_centered_near_half(self):
        lo, hi = wilson_interval(5, 10)
        assert lo < 0.5 < hi

    def test_interval_widens_with_smaller_n(self):
        lo_small, hi_small = wilson_interval(1, 2)
        lo_large, hi_large = wilson_interval(50, 100)
        assert (hi_small - lo_small) > (hi_large - lo_large)
