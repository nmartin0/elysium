"""
registry.py  (the tool registry -- generic, org-agnostic)

Same registry pattern as core/deployment_loader.py's _ADAPTER_REGISTRY/
_LLM_ADAPTER_REGISTRY -- a hardcoded dict today, the one place a future
entry-points-based third-party discovery mechanism would replace.

Unlike data silos and LLM backends, tools are genuinely OPTIONAL for a
deployment -- get_enabled_tools([]) is a completely valid, common case,
not an error condition.

Used by: core/deployment_loader.py (via AgentLoop.from_deployment)
"""

from core.tools.interface import Tool
from tools.linear_regression import LinearRegressionTool

_TOOL_REGISTRY: dict[str, type] = {
    "linear_regression": LinearRegressionTool,
}


def get_enabled_tools(enabled_names: list[str]) -> list[Tool]:
    tools = []
    for name in enabled_names:
        tool_class = _TOOL_REGISTRY.get(name)
        if tool_class is None:
            raise ValueError(
                f"Unknown tool {name!r} -- registered tools: {sorted(_TOOL_REGISTRY.keys())}"
            )
        tools.append(tool_class())
    return tools
