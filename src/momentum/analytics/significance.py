"""Statistical-significance helpers (pure, numpy/stdlib only).

Just enough inferential statistics to gate audit conclusions on evidence — a
correlation with a p-value, Welch's two-sample t-test, a two-proportion z-test and
a peak-to-trough drawdown. p-values use the Student-t and normal distributions
implemented from ``math`` (regularized incomplete beta + ``erfc``), so there is no
scipy dependency. These let callers say "only if statistically significant" and
mean it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from momentum.analytics.statistics import ArrayLike


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    """A Pearson correlation with its two-sided p-value and sample size."""

    r: float | None
    p_value: float | None
    n: int

    @property
    def significant(self) -> bool:
        return self.p_value is not None and self.p_value < 0.05


@dataclass(frozen=True, slots=True)
class TTestResult:
    """A two-group mean comparison (Welch's t-test)."""

    mean_a: float
    mean_b: float
    diff: float  # mean_a - mean_b
    t_stat: float | None
    p_value: float | None
    n_a: int
    n_b: int

    @property
    def significant(self) -> bool:
        return self.p_value is not None and self.p_value < 0.05


# --------------------------------------------------------------------------- #
# distribution tails (no scipy)
# --------------------------------------------------------------------------- #
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """``I_x(a, b)`` — the regularized incomplete beta function on ``[0, 1]``."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(ln_beta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t_stat: float, df: float) -> float:
    """Two-sided p-value for a Student-t statistic with ``df`` degrees of freedom."""
    if df <= 0 or not math.isfinite(t_stat):
        return 1.0
    x = df / (df + t_stat * t_stat)
    return float(regularized_incomplete_beta(df / 2.0, 0.5, x))


def normal_two_sided_p(z: float) -> float:
    """Two-sided p-value for a standard-normal z statistic."""
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
def pearson_with_p(xs: ArrayLike, ys: ArrayLike) -> CorrelationResult:
    """Pearson correlation of ``xs`` vs ``ys`` with a two-sided p-value."""
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    n = int(x.size)
    if n < 3 or y.size != n or x.std() == 0 or y.std() == 0:
        return CorrelationResult(r=None, p_value=None, n=n)
    r = float(np.corrcoef(x, y)[0, 1])
    r = max(-0.999999, min(0.999999, r))
    df = n - 2
    t = r * math.sqrt(df / (1.0 - r * r))
    return CorrelationResult(r=r, p_value=t_two_sided_p(t, df), n=n)


def welch_ttest(a: ArrayLike, b: ArrayLike) -> TTestResult:
    """Welch's unequal-variance t-test comparing the means of ``a`` and ``b``."""
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    na, nb = int(av.size), int(bv.size)
    ma = float(av.mean()) if na else 0.0
    mb = float(bv.mean()) if nb else 0.0
    if na < 2 or nb < 2:
        return TTestResult(ma, mb, ma - mb, None, None, na, nb)
    va, vb = float(av.var(ddof=1)), float(bv.var(ddof=1))
    se2 = va / na + vb / nb
    if se2 <= 0:
        return TTestResult(ma, mb, ma - mb, None, None, na, nb)
    t = (ma - mb) / math.sqrt(se2)
    df = se2**2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    return TTestResult(ma, mb, ma - mb, t, t_two_sided_p(t, df), na, nb)


def two_proportion_p(k_a: int, n_a: int, k_b: int, n_b: int) -> float | None:
    """Two-sided p-value for the difference between two proportions (z-test)."""
    if n_a < 1 or n_b < 1:
        return None
    p_pool = (k_a + k_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
    if se <= 0:
        return None
    z = (k_a / n_a - k_b / n_b) / se
    return normal_two_sided_p(z)


def max_drawdown(values: Sequence[float]) -> float:
    """Peak-to-trough drawdown of a cumulative series (returned as a positive number).

    Fed a per-item sequence (e.g. R-multiples in chronological order) it builds the
    running cumulative sum and returns the largest peak-to-trough decline in the same
    units. ``0.0`` when the series only rises.
    """
    cum = 0.0
    peak = 0.0
    worst = 0.0
    for v in values:
        cum += v
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return abs(worst)
