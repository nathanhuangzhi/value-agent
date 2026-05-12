import math

from app.tools.financials_tools import _is_nan


def test_is_nan_recognizes_float_nan():
    assert _is_nan(float("nan")) is True
    assert _is_nan(math.nan) is True


def test_is_nan_returns_false_for_normal_values():
    assert _is_nan(0) is False
    assert _is_nan(1.5) is False
    assert _is_nan(None) is False  # None != None is False, so this returns False
    assert _is_nan("text") is False
