"""
interface.py  (the action-tool contract -- generic, zero implementation knowledge)

Tool is what EVERY concrete tool (tools/linear_regression.py, and any
future one) must implement. run() receives ONLY the arguments the LLM
supplied -- no data-silo access, no LLM access, no network, no file I/O.
That's the real security property: a tool cannot leak protected data it
was never given, because it has zero ambient authority to reach
anything beyond its own arguments. Tools are pure computation, nothing
more -- they never mutate org data (see core/ontology/write_mediator.py,
not yet built, for the one real write path).

name/description/parameters are used by
core/llm/agent_step_prompt.py's _describe_tools() to generate prompt
text -- never hardcoded, same discipline as _describe_schema().
"""

from typing import Any, Protocol


class Tool(Protocol):
    name: str
    description: str
    parameters: dict   # {param_name: {"type": ..., "description": ...}}

    def run(self, **kwargs) -> Any:
        ...
