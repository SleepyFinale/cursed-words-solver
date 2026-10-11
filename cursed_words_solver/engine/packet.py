"""ScorePacket arithmetic (game ``ScorePacket``): checked int64 with ±infinity.

Finite values are plain Python ints; infinities are ``INF`` / ``NEG_INF``. Every
operator mirrors the C# overloads, including truncating division and the
overflow-to-infinity fallback, so the engine never drifts on large scores.
"""

from __future__ import annotations

import math

import numpy as np

INT64_MAX = (1 << 63) - 1
INT64_MIN = -(1 << 63)
INF = math.inf
NEG_INF = -math.inf


def _clamp(value: int) -> int | float:
    if value > INT64_MAX:
        return INF
    if value < INT64_MIN:
        return NEG_INF
    return value


def is_inf(a: int | float) -> bool:
    return isinstance(a, float)


def add(a: int | float, b: int | float) -> int | float:
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and isinstance(b, float) and (a > 0) != (b > 0):
            return 0
        return a if isinstance(a, float) else b
    return _clamp(a + b)


def sub(a: int | float, b: int | float) -> int | float:
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and isinstance(b, float) and (a > 0) == (b > 0):
            return 0
        if isinstance(a, float):
            return a
        return NEG_INF if b > 0 else INF
    return _clamp(a - b)


def mul(a: int | float, b: int | float) -> int | float:
    a_inf = isinstance(a, float)
    b_inf = isinstance(b, float)
    if a_inf and b_inf:
        return INF if (a > 0) == (b > 0) else NEG_INF
    if a_inf or b_inf:
        finite = b if a_inf else a
        inf = a if a_inf else b
        if finite == 0:
            return 0
        negative = (inf < 0) ^ (finite < 0)
        return NEG_INF if negative else INF
    return _clamp(a * b)


def div(a: int | float, b: int | float) -> int | float:
    """C# ``/``: truncates toward zero; finite / ±inf is 0."""
    if not isinstance(b, float) and b == 0:
        raise ZeroDivisionError("ScorePacket divide by zero")
    if isinstance(a, float):
        b_neg = b < 0
        return NEG_INF if (a < 0) ^ b_neg else INF
    if isinstance(b, float):
        return 0
    if a == INT64_MIN and b == -1:
        return INF
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def scale(a: int | float, factor: float) -> int | float:
    """``ScorePacket.Scale``: (long)Math.Round((float)Score * factor)."""
    if isinstance(a, float):
        return a
    product = np.float32(a) * np.float32(factor)
    return int(round(float(product)))


def round_to_int(value: float) -> int:
    """Unity ``Mathf.RoundToInt`` (banker's rounding of the float)."""
    return int(round(float(np.float32(value))))


def gt(a: int | float, b: int | float) -> bool:
    return a > b


def to_int(a: int | float) -> int:
    """Clamp infinities for callers that need a plain number (UI, ranking)."""
    if isinstance(a, float):
        return INT64_MAX if a > 0 else INT64_MIN
    return a
