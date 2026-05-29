"""Numerically stable percentile helpers used by DoraCalculator.

We use Python's stdlib `statistics.quantiles(..., method='inclusive')` for
linear-interpolation percentiles compatible with NumPy's default behaviour,
without taking a NumPy dependency at runtime.
"""
from __future__ import annotations

import statistics
from typing import Iterable


def _clean(xs: Iterable[float]) -> list[float]:
    return [float(x) for x in xs if x is not None]


def percentile(xs: Iterable[float], p: float) -> float | None:
    """
    Linear-interpolation percentile. p is in [0, 100].

    n=0 → None
    n=1 → that value
    n=2..  → linear interpolation (statistics.quantiles inclusive method)
    """
    data = _clean(xs)
    n = len(data)
    if n == 0:
        return None
    if n == 1:
        return data[0]

    if not 0.0 <= p <= 100.0:
        raise ValueError("p must be in [0, 100]")

    if p == 0.0:
        return min(data)
    if p == 100.0:
        return max(data)

    # statistics.quantiles with n=100 gives 99 cut points (1st..99th percentile)
    # using the inclusive method (compatible with NumPy linear interpolation).
    cut_points = statistics.quantiles(data, n=100, method="inclusive")
    # p=1 → cut_points[0]; p=99 → cut_points[98]; p=50 → cut_points[49]
    if p == int(p):
        idx = int(p) - 1
        if 0 <= idx < len(cut_points):
            return cut_points[idx]

    # Fractional percentiles — interpolate between adjacent cut points.
    lo = max(0, int(p) - 1)
    hi = min(len(cut_points) - 1, lo + 1)
    frac = p - int(p)
    return cut_points[lo] + (cut_points[hi] - cut_points[lo]) * frac


def median(xs: Iterable[float]) -> float | None:
    data = _clean(xs)
    if not data:
        return None
    return statistics.median(data)


def mean(xs: Iterable[float]) -> float | None:
    data = _clean(xs)
    if not data:
        return None
    return statistics.fmean(data)
