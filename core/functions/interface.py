"""
interface.py  (the Function contract)

Elysium's equivalent of Foundry's Functions: logic a deployment
provides, invocable by the agent, described to the model from its own
declaration rather than hardcoded prompt text.

FOUNDRY'S FUNCTIONS ARE DEFINED BY ONTOLOGY ACCESS -- "first-class
support for reading the properties of various object types, traversing
links, and flexibly making Ontology edits", which is what makes them
"go far beyond commonly used Functions-as-a-Service platforms". A
function here can do the read half of that. The write half is
deliberately excluded; see ROADMAP.md.

THE SECURITY PROPERTY, and why this is not simply "hand it a mediator".
These functions are invoked by an LLM that chooses their arguments
(see core/agent/agentic_loop.py, which calls run(**step["args"])). A
function with ambient access to the ontology is a function the model
can aim at data the caller may not see.

Foundry solves this at the platform level, and their own Q&A gives the
tell: "there is no way to get the executing user's ID within a
function without passing it as a parameter". Their function authors do
not write permission checks -- they cannot, because they do not know
who is calling. The SDK enforces it beneath them.

So a function here receives a CAPABILITY, not authority:
  - it declares which object types it reads, in `reads_object_types`
  - the caller's own authorization is bound into the query object
    before the function ever runs
  - the function never sees a UserRecord and cannot construct its own
    access to anything

A function declaring NO object types receives no query object at all,
and therefore provably cannot reach the ontology -- the original
zero-ambient-authority property, now visible in the declaration rather
than trusted in the implementation.
"""

from typing import Any, Protocol


class Function(Protocol):
    name: str
    description: str
    parameters: dict   # {param_name: {"type": ..., "description": ...}}
    max_concurrent_calls: int | None   # None = genuinely stateless, no limit needed

    # Object types this function may read, by name. Empty (the default
    # for a purely computational function) means run() is called with
    # its arguments only, exactly as before ontology access existed.
    reads_object_types: list[str]

    def run(self, **kwargs) -> Any:
        ...
