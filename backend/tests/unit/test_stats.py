"""Numerical sanity tests for the percentile/median helpers."""
import pytest

from app.services.stats import mean, median, percentile


def test_percentile_empty_returns_none():
    assert percentile([], 50) is None


def test_percentile_single_value():
    # With one sample, every percentile should collapse to that value —
    # the old implementation crashed on `quantiles` with n<2.
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 95) == 42.0


def test_percentile_known_distribution():
    data = list(range(1, 101))  # 1..100
    p50 = percentile(data, 50)
    p95 = percentile(data, 95)
    assert 50 <= p50 <= 51   # inclusive method puts the median around 50.5
    assert 94 <= p95 <= 96


def test_percentile_rejects_out_of_range():
    with pytest.raises(ValueError):
        percentile([1, 2, 3], 150)


def test_median_and_mean_with_nones_are_dropped():
    # Stats helpers receive None values from the DB on un-set columns; they
    # should silently drop them rather than throw or pollute the result.
    assert median([1, None, 3]) == 2
    assert mean([2, None, 4]) == 3
