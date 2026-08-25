"""
linear_regression.py  (example action tool -- pure computation, no dependencies)

Least-squares line fit over paired numeric data. Implements
core/tools/interface.py's Tool contract: run() receives only the
arguments the LLM supplied, touches nothing else, and raises
ValueError on any invalid input rather than guessing or silently
producing a meaningless result.
"""


class LinearRegressionTool:
    name = "linear_regression"
    max_concurrent_calls = None  # pure computation, zero shared state
    description = (
        "Fits a least-squares line to paired (x, y) numeric data and "
        "returns slope, intercept, and R-squared (goodness of fit, 0 to 1)."
    )
    parameters = {
        "x_values": {"type": "list[float]", "description": "Independent variable values"},
        "y_values": {"type": "list[float]", "description": "Dependent variable values, same length as x_values"},
    }

    def run(self, x_values: list[float], y_values: list[float]) -> dict:
        if len(x_values) != len(y_values):
            raise ValueError(
                f"x_values and y_values must be the same length "
                f"(got {len(x_values)} and {len(y_values)})"
            )
        n = len(x_values)
        if n < 2:
            raise ValueError(f"Need at least 2 data points for a regression, got {n}")

        mean_x = sum(x_values) / n
        mean_y = sum(y_values) / n

        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
        denominator = sum((x - mean_x) ** 2 for x in x_values)

        if denominator == 0:
            raise ValueError("All x_values are identical -- cannot fit a line (undefined slope)")

        slope = numerator / denominator
        intercept = mean_y - slope * mean_x

        predicted = [slope * x + intercept for x in x_values]
        ss_res = sum((y - pred) ** 2 for y, pred in zip(y_values, predicted))
        ss_tot = sum((y - mean_y) ** 2 for y in y_values)
        r_squared = 1.0 if ss_tot == 0 else 1 - (ss_res / ss_tot)

        return {"slope": slope, "intercept": intercept, "r_squared": r_squared}
