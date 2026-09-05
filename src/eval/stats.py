"""The only place statistics are computed. Pure stdlib."""

from __future__ import annotations

from math import sqrt
from typing import Sequence


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def confusion(pred: Sequence[bool], exp: Sequence[bool]) -> dict[str, int]:
    if len(pred) != len(exp):
        raise ValueError("pred and exp must be the same length")
    out = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for p, e in zip(pred, exp):
        if p and e:
            out["tp"] += 1
        elif p and not e:
            out["fp"] += 1
        elif not p and e:
            out["fn"] += 1
        else:
            out["tn"] += 1
    return out


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return (precision, recall, f1)


LEVELS = (0.0, 0.5, 1.0)


def bucket(score: float) -> float:
    """Map a continuous 0-1 score onto the three levels the labels use."""
    if score < 1 / 3:
        return 0.0
    if score < 2 / 3:
        return 0.5
    return 1.0


def cohens_kappa(a: Sequence[object], b: Sequence[object]) -> float:
    """Cohen's kappa over any hashable categories, not just booleans.

    Returns 0.0 when the raters agree only as much as chance predicts, and when the
    denominator vanishes -- which happens when one rater uses a single category for
    every item. On a small, skewed set that is common, so read kappa next to the
    raw agreement rate rather than on its own.
    """
    if len(a) != len(b) or not a:
        return 0.0
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    categories = set(a) | set(b)
    expected = sum(
        (sum(1 for x in a if x == c) / n) * (sum(1 for y in b if y == c) / n)
        for c in categories
    )
    if expected >= 1.0:
        return 0.0
    return (observed - expected) / (1 - expected)


def agreement(a: Sequence[object], b: Sequence[object]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def scored(pred: Sequence[bool], exp: Sequence[bool]) -> dict:
    c = confusion(pred, exp)
    precision, recall, f1 = prf(c["tp"], c["fp"], c["fn"])
    return {
        **c,
        "precision": precision,
        "precision_ci": wilson(c["tp"], c["tp"] + c["fp"]),
        "recall": recall,
        "recall_ci": wilson(c["tp"], c["tp"] + c["fn"]),
        "f1": f1,
    }


def kappa_interval(a: Sequence[object], b: Sequence[object], resamples: int = 2000,
                   seed: int = 20260904) -> tuple[float, float]:
    """Percentile bootstrap interval for Cohen's kappa.

    At n=11 a point estimate of kappa is close to meaningless on its own -- the same judge
    on the same turns produced -0.10 and -0.14 on two runs -- so the interval is reported
    beside it. Paired resampling with replacement over the item indices.
    """
    import random

    if len(a) != len(b) or len(a) < 3:
        return (-1.0, 1.0)
    rng = random.Random(seed)
    n = len(a)
    draws = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        draws.append(cohens_kappa([a[i] for i in idx], [b[i] for i in idx]))
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    return (lo, hi)
