"""
calculator.py  (exact arithmetic, so the model never has to do any)

LB-1. Synthesis produced figures in prose and nothing checked them: an
invented total of $7,412.00 against records of 49.99 and 199.00 was
returned verbatim, and so was wrong arithmetic, and so was an invented
count. Reproduced against the real synthesise path.

THE INDUSTRY PATTERN IS ONE SENTENCE: the model orchestrates,
deterministic code computes. Palantir ships this as a first-class tool
-- AIP Logic's four tools are Apply actions, Call function, Query
objects, and Calculator, which "enables you to perform accurate
mathematical calculations with an LLM". This is that tool, in the
registry this project already has.

DECIMAL, NEVER FLOAT, and that is the whole reason this is not three
lines. This project declares a `decimal` field type specifically
because float loses money digits -- prompt_values.py exists to stop a
stored 49.990000000 reaching a model as a float, and
Decimal("12345678901234567.89") does not survive a round trip through
one. A calculator that answered in floats would reintroduce, at the
last step, exactly the defect the type system was built to prevent.
0.1 + 0.2 returns 0.3 here, not 0.30000000000000004.

NO eval(), NO exec(), NOT NEGOTIABLE. The expression comes from a
model, and a model reads untrusted field values (AL-2). eval() on that
path is arbitrary code execution reachable from a customer's own data.
The expression is parsed to an AST and walked against a closed
whitelist of node types; anything else -- a name, a call, an
attribute, a subscript, a comprehension -- is refused before
evaluation, not sanitised.

POWER IS ABSENT AS A SCOPE DECISION, NOT A SECURITY ONE, and the
first draft of this comment got that wrong. It claimed `**` was a
denial-of-service vector because 10**10**10 is short to write and
unbounded to compute. MEASURED: with Pow added to the whitelist, that
expression does not hang -- the Decimal context raises Overflow and
run() returns a refusal in milliseconds. Bounded precision is what
makes it safe, and that was already true.

WHAT DOES HANG IS eval(), which is the actual evidence for the
paragraph above. Swapping the AST walk for eval() during a control
run left 10**10**10 computing in native Python integers until the
test run was killed. So eval() is not merely a code-execution hole; it
is also unbounded arithmetic. Two reasons, one line of defence.

Power stays out because nothing this serves -- totals, differences,
rates over money and counts -- needs it, and Foundry does not promise
it either. Every operator is surface area. If a real query needs it,
add it deliberately.

THIS DOES NOT CLOSE LB-1 ON ITS OWN. The model must still CHOOSE to
call it, and LB-9 records that the loop under-selects tools. The
number check (LB-1b) is what catches the times it does not, and the
two were always meant to ship together.
"""

import ast
import decimal
import operator
from collections.abc import Callable
from typing import Any

# 28 significant digits, Python's default. Enough for money at any
# scale a ledger holds, and bounded so a division that does not
# terminate (1/3) stops rather than running forever.
_CONTEXT = decimal.Context(prec=28)

# A closed whitelist. Membership is the check -- there is no fallback
# branch that evaluates something not named here.
_BINARY_OPERATORS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPERATORS: dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Long enough for a sum of many line items, short enough that a
# pathological expression cannot arrive at all. A model that needs
# more is doing something this tool is the wrong shape for.
MAX_EXPRESSION_LENGTH = 500


def _evaluate(node: ast.AST) -> decimal.Decimal:
    """One AST node, or a refusal.

    Recursive, and bounded by the parser: CPython refuses to parse an
    expression nested deeply enough to exhaust the stack, and
    MAX_EXPRESSION_LENGTH caps the input long before that.
    """
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            # bool is a subclass of int in Python, so True would
            # otherwise arithmetic as 1. A boolean in a sum is a
            # mistake worth naming, not coercing.
            raise ValueError("calculator: booleans are not numbers")
        if isinstance(node.value, int):
            return _CONTEXT.create_decimal(node.value)
        if isinstance(node.value, float):
            # Parsed from the TEXT of the expression, so the original
            # digits are recoverable exactly -- repr() of a float
            # round-trips. Going through the string rather than
            # Decimal(float) is what keeps 0.1 as 0.1 instead of
            # 0.1000000000000000055511151231257827.
            return _CONTEXT.create_decimal(repr(node.value))
        raise ValueError(f"calculator: {type(node.value).__name__} is not a number")

    if isinstance(node, ast.BinOp):
        apply_binary = _BINARY_OPERATORS.get(type(node.op))
        if apply_binary is None:
            raise ValueError(
                f"calculator: {type(node.op).__name__} is not a supported "
                f"operation. Supported: + - * / and parentheses."
            )
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if apply_binary is operator.truediv and right == 0:
            raise ValueError("calculator: division by zero")
        with decimal.localcontext(_CONTEXT):
            return apply_binary(left, right)

    if isinstance(node, ast.UnaryOp):
        # NAMED SEPARATELY from the binary case above, because they
        # have different arities and sharing one name let mypy see a
        # one-argument call against a two-argument type.
        apply_unary = _UNARY_OPERATORS.get(type(node.op))
        if apply_unary is None:
            raise ValueError(f"calculator: {type(node.op).__name__} is not supported")
        with decimal.localcontext(_CONTEXT):
            return apply_unary(_evaluate(node.operand))

    # EVERYTHING ELSE IS REFUSED BY DEFAULT. Names, calls, attributes,
    # subscripts, comprehensions, lambdas, walrus. Named individually
    # they would be a list to keep current; refused as a class they
    # cannot be forgotten.
    raise ValueError(
        f"calculator: {type(node).__name__} is not allowed in an expression. "
        f"Give arithmetic over literal numbers only, e.g. '49.99 + 199.00'."
    )


class CalculatorFunction:
    name = "calculator"
    max_concurrent_calls = None  # pure computation, zero shared state
    # Declares NO object types, so it receives no ontology access at
    # all and provably cannot reach data. The values it works on are
    # ones the caller already read and was already authorised for --
    # this adds no reach of its own.
    reads_object_types: list[str] = []
    description = (
        "Evaluates an arithmetic expression EXACTLY and returns the result. "
        "Use this for any sum, difference, product or rate -- do not "
        "calculate in your head. Supply the numbers you have already read, "
        "as literal figures."
    )
    parameters = {
        "expression": {
            "type": "string",
            "description": (
                "Arithmetic over literal numbers, using + - * / and "
                "parentheses only, e.g. '49.99 + 199.00' or "
                "'(120 - 80) / 80'. Substitute the values you read into "
                "the expression yourself -- field names, object ids and "
                "function calls are NOT understood here and will be "
                "refused."
            ),
        },
    }

    def run(self, **kwargs) -> decimal.Decimal:
        """The result as a Decimal, rendered by prompt_values on the way
        to the model so it reads at the ontology's declared scale."""
        expression = kwargs.get("expression")
        if not isinstance(expression, str):
            raise ValueError("calculator: 'expression' must be a string")
        expression = expression.strip()
        if not expression:
            raise ValueError("calculator: 'expression' must not be empty")
        if len(expression) > MAX_EXPRESSION_LENGTH:
            raise ValueError(
                f"calculator: expression is {len(expression)} characters, "
                f"over the limit of {MAX_EXPRESSION_LENGTH}. Calculate it in "
                f"parts."
            )

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            # RAISED AS ValueError, like every other refusal here, so
            # the agent loop's invalid-step recovery handles it as a
            # recoverable mistake rather than a crash. A SyntaxError
            # would propagate past that handler.
            raise ValueError(f"calculator: {expression!r} is not an expression") from e

        try:
            with decimal.localcontext(_CONTEXT):
                result = _evaluate(tree)
        except decimal.DecimalException as e:
            # Overflow, underflow, an operation the context refuses.
            # Named rather than leaked as a bare library exception.
            raise ValueError(f"calculator: {expression!r} could not be evaluated") from e

        if not result.is_finite():
            # Infinity or NaN would render as text a model might copy
            # into an answer as though it were a figure.
            raise ValueError(f"calculator: {expression!r} has no finite result")
        return result
