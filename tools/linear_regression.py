"""
linear_regression.py  (example action tool -- pure computation, no dependencies)

Least-squares line fit over paired numeric data. Implements
core/tools/interface.py's Tool contract: run() receives only the
arguments the LLM supplied, touches nothing else, and raises
ValueError on any invalid input rather than guessing or silently
producing a meaningless result.

x_values' description is deliberately explicit about needing NUMERIC
values, with a concrete alternative spelled out for non-numeric
ordering data (dates, categories) -- found necessary by a real,
observed failure: a real model, asked about a trend over time, passed
raw date STRINGS as x_values (a reasonable-looking but type-
incompatible interpretation of "independent variable"), which failed
with a raw Python TypeError from sum() rather than run()'s own clear
ValueError. Caught correctly by AgentLoop's invalid-step recovery
either way (see core/agent/agentic_loop.py), but a clearer contract
here is a real fix to genuine ambiguity, not a workaround for a weak
model -- the tool's own spec was underspecified, independent of which
model is calling it.
"""


class LinearRegressionTool:
    name = "linear_regression"
    max_concurrent_calls = None  # pure computation, zero shared state
    description = (
        "Fits a least-squares line to paired (x, y) numeric data and "
        "returns slope, intercept, and R-squared (goodness of fit, 0 to 1)."
    )
    parameters = {
        "x_values": {
            "type": "list[float]",
            "description": (
                "Independent variable values -- MUST be numeric. If your data "
                "represents dates, categories, or another non-numeric sequence, "
                "use a simple position index instead (e.g. [1, 2, 3] for the "
                "1st, 2nd, 3rd data points in order), never the raw values themselves."
            ),
        },
        "y_values": {"type": "list[float]", "description": "Dependent variable values, same length as x_values"},
    }

    def run(self, x_values: list[float], y_values: list[float]) -> dict:
        # Explicit type check, not left to leak as a raw TypeError from
        # sum() -- this tool's own docstring promises ValueError on any
        # invalid input; a bare TypeError (observed for real: a model
        # passing date strings as x_values) violated that contract and
        # gave the model's own corrective nudge a less specific message
        # than a real ValueError would.
        for name, values in (("x_values", x_values), ("y_values", y_values)):
            for value in values:
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        f"{name} must contain only numbers, got {value!r} ({type(value).__name__})"
                    )

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
