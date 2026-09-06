"""
registry.py  (the function registry -- generic, org-agnostic)

Same registry pattern as core/deployment_loader.py's own adapter
registries -- a hardcoded dict today, the one place a future
entry-points-based discovery mechanism would replace.

Functions are genuinely OPTIONAL for a deployment:
get_enabled_functions([]) is a valid, common case, not an error.
"""

from core.functions.interface import Function
from functions.linear_regression import LinearRegressionFunction

_FUNCTION_REGISTRY: dict[str, type] = {
    "linear_regression": LinearRegressionFunction,
}


def get_enabled_functions(enabled_names: list[str]) -> list[Function]:
    functions = []
    for name in enabled_names:
        function_class = _FUNCTION_REGISTRY.get(name)
        if function_class is None:
            raise ValueError(
                f"Unknown function {name!r} -- registered functions: "
                f"{sorted(_FUNCTION_REGISTRY.keys())}"
            )
        functions.append(function_class())
    return functions


def validate_function_declarations(enabled_names: list[str], object_types: dict) -> None:
    """Checks every enabled function against the ontology, at LOAD time.

    Foundry runs backward-compatibility checks before publishing a
    function, warning about breaks like dropping a function or adding a
    required parameter. Elysium has no versioning to protect (see
    ROADMAP.md for why), but the same class of mistake is worth
    catching: a function declaring an object type the ontology does not
    have would otherwise surface as a confusing failure mid-conversation,
    after a user has already asked a question.

    Raises here instead, alongside every other deployment config error,
    where the message can name the real cause.
    """
    for function in get_enabled_functions(enabled_names):
        for object_type in getattr(function, "reads_object_types", []):
            if object_type not in object_types:
                raise ValueError(
                    f"Function {function.name!r} declares reads_object_types "
                    f"{object_type!r}, which is not a declared object type -- "
                    f"known types: {sorted(object_types)}."
                )
