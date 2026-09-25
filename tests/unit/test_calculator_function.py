"""The calculator is exact, and it is not an interpreter.

LB-1's first half. Synthesis produced figures in prose and nothing
checked them: an invented $7,412.00 against records of 49.99 and
199.00 was returned verbatim, and so was wrong arithmetic. The
industry pattern is that the model orchestrates and deterministic code
computes; Palantir ships this as one of AIP Logic's four tools.

TWO PROPERTIES CARRY THE FILE, and both are the kind that look like
details until they are wrong.

EXACT, because float is the defect this project already fixed once.
`decimal` exists as a field type precisely because float loses money
digits, and prompt_values.py exists to stop a stored 49.990000000
reaching a model badly. A calculator answering in floats would
reintroduce that at the last step, after every other layer had got it
right.

NOT AN INTERPRETER, because the expression comes from a model and the
model reads untrusted field values (AL-2). `eval()` there is arbitrary
code execution reachable from a customer's own data. These tests
assert the refusals as hard as they assert the arithmetic.
"""

import decimal

import pytest

from core.functions.registry import get_enabled_functions


@pytest.fixture
def calculator():
    return get_enabled_functions(["calculator"])[0]


# ------------------------------------------------------------------ exactness


def test_the_total_from_the_lb_1_reproduction(calculator):
    """49.99 + 199.00 = 248.99 -- the sum whose invented alternative
    ($7,412.00) was returned to a user verbatim."""
    assert calculator.run(expression="49.99 + 199.00") == decimal.Decimal("248.99")


def test_it_is_exact_where_float_is_not(calculator):
    """THE TEST THAT FAILS THE MOMENT SOMEONE SIMPLIFIES THIS TO float().

    0.1 + 0.2 is 0.30000000000000004 in binary floating point. Every
    language with floats has this; it is not a Python quirk. A total
    shown to a user must not have it.
    """
    result = calculator.run(expression="0.1 + 0.2")

    assert result == decimal.Decimal("0.3")
    assert str(result) == "0.3"
    assert 0.1 + 0.2 != 0.3  # the thing being avoided, stated


def test_a_large_money_value_survives_intact(calculator):
    """Decimal("12345678901234567.89") does not survive a float round
    trip, and money is exactly the field someone chose decimal for."""
    result = calculator.run(expression="12345678901234567.89 + 0.01")

    assert result == decimal.Decimal("12345678901234568.01")


def test_it_returns_a_Decimal_so_the_prompt_renders_it(calculator):
    """Not a string and not a float: prompt_values renders a Decimal at
    the ontology's declared scale, which is how the result reaches the
    model looking like the other money in the answer."""
    assert isinstance(calculator.run(expression="1 + 1"), decimal.Decimal)


@pytest.mark.parametrize(("expression", "expected"), [
    ("(120 - 80) / 80", "0.5"),
    ("-5 + 10", "5"),
    ("2 * (3 + 4)", "14"),
    ("100 / 8", "12.5"),
    ("+7", "7"),
])
def test_the_supported_arithmetic(calculator, expression, expected):
    assert calculator.run(expression=expression) == decimal.Decimal(expected)


def test_a_non_terminating_division_terminates(calculator):
    """1/3 has no exact decimal form. It must stop at the context's
    precision rather than run, and must not raise."""
    result = calculator.run(expression="1/3")

    assert result.is_finite()
    assert str(result).startswith("0.333333")


# ------------------------------------------------------------- not an interpreter


@pytest.mark.parametrize("hostile", [
    '__import__("os").system("ls")',
    'open("/etc/passwd").read()',
    "().__class__.__bases__",
    "[1, 2, 3]",
    "{'a': 1}",
    "lambda: 1",
    "(x := 5)",
    "amount",
    "self.mediator",
])
def test_nothing_but_arithmetic_is_evaluated(calculator, hostile):
    """THE REFUSALS MATTER AS MUCH AS THE SUMS.

    The expression is written by a model, and the model reads untrusted
    field values. Anything evaluated here is reachable from a
    customer's own data.
    """
    with pytest.raises(ValueError):
        calculator.run(expression=hostile)


def test_power_is_refused_as_a_scope_decision(calculator):
    """ABSENT BECAUSE NOTHING NEEDS IT, not because it is dangerous --
    and the distinction was found by running the control rather than
    by reasoning.

    The first version of this test claimed 10**10**10 was a
    denial-of-service vector. Adding Pow to the whitelist and
    measuring showed otherwise: the Decimal context raises Overflow
    and the call returns a refusal in milliseconds. What DID hang was
    the control that swapped the AST walk for eval(), where the same
    expression ran in native Python integers until the test run was
    killed -- so unbounded arithmetic is a second reason eval() is
    refused, on top of code execution.

    Power stays out because every operator is surface area and nothing
    this serves needs one.
    """
    with pytest.raises(ValueError, match="not a supported operation"):
        calculator.run(expression="10**10**10")


def test_division_by_zero_is_a_named_refusal(calculator):
    with pytest.raises(ValueError, match="division by zero"):
        calculator.run(expression="1/0")


def test_a_boolean_is_not_a_number(calculator):
    """bool subclasses int in Python, so True would otherwise sum as 1.
    A boolean in a total is a mistake worth naming."""
    with pytest.raises(ValueError, match="boolean"):
        calculator.run(expression="True + 1")


def test_every_refusal_is_a_ValueError(calculator):
    """THE CONTRACT THE AGENT LOOP DEPENDS ON.

    _execute_step catches (ValueError, TypeError, PermissionError) and
    turns them into a recoverable mistake the model can correct. A
    SyntaxError from ast.parse would sail straight past that handler
    and out of the loop -- which is AL-1's shape exactly, a
    model-written value crashing /query outside the error handling.
    """
    for bad in ["not an expression!", "1 +", "((", "", "   ", "1 2 3"]:
        with pytest.raises(ValueError):
            calculator.run(expression=bad)


def test_a_non_string_expression_is_refused(calculator):
    """A model can send any JSON value for a declared string."""
    for bad in (None, 42, ["1 + 1"], {"expression": "1 + 1"}):
        with pytest.raises(ValueError, match="must be a string"):
            calculator.run(expression=bad)


def test_an_over_long_expression_is_refused_before_parsing(calculator):
    from functions.calculator import MAX_EXPRESSION_LENGTH

    with pytest.raises(ValueError, match="over the limit"):
        calculator.run(expression=" + ".join(["1"] * MAX_EXPRESSION_LENGTH))


# ------------------------------------------------------------------- contract


def test_it_declares_no_ontology_access(calculator):
    """ZERO AMBIENT AUTHORITY, visible in the declaration rather than
    trusted in the implementation. The values it works on were already
    read and already authorised; this adds no reach of its own."""
    assert calculator.reads_object_types == []


def test_it_satisfies_the_function_contract(calculator):
    assert calculator.name == "calculator"
    assert calculator.max_concurrent_calls is None
    assert "expression" in calculator.parameters
    assert calculator.description


def test_the_description_tells_the_model_not_to_do_it_itself(calculator):
    """The tool existing is not enough -- LB-9 records that the loop
    under-selects tools. The description is where the instruction to
    use it lives."""
    assert "do not calculate in your head" in calculator.description.lower()
