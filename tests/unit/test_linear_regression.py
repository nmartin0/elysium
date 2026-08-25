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
