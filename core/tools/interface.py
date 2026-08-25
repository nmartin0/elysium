"""
interface.py  (the action-tool contract -- generic, zero implementation knowledge)

Tool is what EVERY concrete tool (tools/linear_regression.py, and any
future one) must implement. run() receives ONLY the arguments the LLM
supplied -- no data-silo access, no LLM access, no network, no file I/O.
That's the real security property: a tool cannot leak protected data it
was never given, because it has zero ambient authority to reach
anything beyond its own arguments. Tools are pure computation, nothing
more -- they never mutate org data (see core/ontology/write_mediator.py
for the one real write path).

name/description/parameters used by core/llm/agent_step_prompt.py's
_describe_tools() to generate prompt text -- never hardcoded.
max_concurrent_calls declared here like every other adapter's
concurrency fields -- None is correct for a genuinely stateless tool.
"""

from typing import Any, Protocol


class Tool(Protocol):
    name: str
    description: str
    parameters: dict   # {param_name: {"type": ..., "description": ...}}
    max_concurrent_calls: int | None   # None = genuinely stateless, no limit needed

    def run(self, **kwargs) -> Any:
        ...
