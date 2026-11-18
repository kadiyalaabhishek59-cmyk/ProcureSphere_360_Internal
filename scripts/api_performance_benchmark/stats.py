"""
Statistical calculations for API performance benchmarking.
All measurements are strictly in milliseconds (ms) with two decimal places.
No category labels or performance classifications.
"""

from typing import List, Optional, Tuple
import math


def calculate_percentile(data: List[float], percentile: float) -> float:
    """Calculate the given percentile (e.g. 95, 99) using linear interpolation."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 1:
        return round(sorted_data[0], 2)
    
    # R7 rank method (standard in numpy/scipy)
    rank = (percentile / 100.0) * (n - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    weight = rank - lower
    
    val = sorted_data[lower] * (1.0 - weight) + sorted_data[upper] * weight
    return round(val, 2)


def compute_metrics(durations_ms: List[float]) -> dict:
    """
    Computes statistical metrics from a list of durations in milliseconds.
    Returns:
        avg_ms, min_ms, max_ms, p95_ms, p99_ms
    """
    if not durations_ms:
        return {
            "avg_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "count": 0,
        }

    avg_ms = round(sum(durations_ms) / len(durations_ms), 2)
    min_ms = round(min(durations_ms), 2)
    max_ms = round(max(durations_ms), 2)
    p95_ms = calculate_percentile(durations_ms, 95.0)
    p99_ms = calculate_percentile(durations_ms, 99.0)

    return {
        "avg_ms": avg_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "count": len(durations_ms),
    }


def compute_differences(local_avg_ms: float, render_avg_ms: float) -> Tuple[float, float]:
    """
    Calculates numerical difference and percentage difference between Render and Localhost.
    Response time difference (ms): Render Average - Localhost Average
    Percentage difference (%): ((Render Average - Localhost Average) / Localhost Average) * 100
    """
    diff_ms = round(render_avg_ms - local_avg_ms, 2)

    if local_avg_ms > 0:
        pct_diff = round(((render_avg_ms - local_avg_ms) / local_avg_ms) * 100.0, 2)
    elif local_avg_ms == 0 and render_avg_ms == 0:
        pct_diff = 0.0
    else:
        pct_diff = 100.0 if render_avg_ms > 0 else 0.0

    return diff_ms, pct_diff
