"""Tests for tools/linear_regression.py -- pure computation, no mocking needed."""

import pytest

from tools.linear_regression import LinearRegressionTool


@pytest.fixture
def tool() -> LinearRegressionTool:
    return LinearRegressionTool()


def test_perfect_line_fit(tool):
    # y = 2x + 1 exactly
    result = tool.run(x_values=[1, 2, 3, 4], y_values=[3, 5, 7, 9])
    assert abs(result["slope"] - 2.0) < 1e-9
    assert abs(result["intercept"] - 1.0) < 1e-9
    assert abs(result["r_squared"] - 1.0) < 1e-9


def test_mismatched_lengths_raises(tool):
    with pytest.raises(ValueError):
        tool.run(x_values=[1, 2, 3], y_values=[1, 2])


def test_too_few_points_raises(tool):
    with pytest.raises(ValueError):
        tool.run(x_values=[1], y_values=[1])


def test_identical_x_values_raises(tool):
    # Vertical line -- undefined slope, must fail clearly rather than
    # divide by zero silently or return a nonsensical value.
    with pytest.raises(ValueError):
        tool.run(x_values=[5, 5, 5], y_values=[1, 2, 3])


def test_wrong_kwargs_raises_typeerror(tool):
    # Confirms the failure mode AgentLoop._execute_step() specifically
    # catches for tool calls -- calling with wrong parameter names
    # raises TypeError, not ValueError.
    with pytest.raises(TypeError):
        tool.run(wrong_param=[1, 2, 3])


def test_non_numeric_x_values_raises_valueerror_not_typeerror():
    # THE real, observed scenario: a real model passed date STRINGS as
    # x_values (see tools/linear_regression.py's module docstring). A
    # bare TypeError from sum() would violate this tool's own promised
    # contract -- this must be a clear, deliberate ValueError instead.
    tool = LinearRegressionTool()
    with pytest.raises(ValueError, match="x_values must contain only numbers"):
        tool.run(x_values=["2026-05-01", "2026-06-14"], y_values=[49.99, 199.00])


def test_non_numeric_y_values_raises_valueerror():
    tool = LinearRegressionTool()
    with pytest.raises(ValueError, match="y_values must contain only numbers"):
        tool.run(x_values=[1, 2], y_values=["a", "b"])


def test_mixed_int_and_float_values_still_work(tool):
    # Real, valid data is very often a mix of int and float -- this
    # must NOT be swept up by the new type check.
    result = tool.run(x_values=[1, 2, 3], y_values=[3.0, 5.5, 7.0])
    assert "slope" in result
