"""
generation_dependency.py  (pinning ONE configuration per request)

Every request reads the current DeploymentGeneration exactly once, at
entry, and uses that one object for its whole life.

WHY ONCE. The five configuration-derived objects -- config, mediator,
write_mediator, loop, synthesis_client -- used to be separate
attributes on app.state, read independently wherever they were needed.
A reload replacing them one at a time gives a window in which a request
reads a new mediator and an old config: schema and grants disagreeing
inside one request, which is an authorization bug rather than a
cosmetic one. Step 2b made them one immutable object; this makes each
request take one reference to it.

NO LOCK, deliberately. Rebinding app.state.generation is a single
atomic assignment in CPython, and reading it is atomic too, so a
reader can never observe a half-built generation. A lock here would
serialise every request to buy what one atomic read already gives.

This is read-copy-update, and it is sound ONLY because the shared
object genuinely cannot be mutated -- see core/immutable.py. Had
configuration stayed mutable, the lock-free read path would be unsafe
and the hottest path in the system would need real synchronisation.

The pin also keeps the OLD generation alive for as long as any request
holds it: Python's refcounting frees it when the last one finishes.
That covers memory. It does NOT cover the Iceberg snapshots the
generation names, which expiry can delete out from under a running
read -- see HOT_RELOAD_PLAN.md step 5h.
"""

from fastapi import Request

from core.deployment_loader import DeploymentGeneration


def get_generation(request: Request) -> DeploymentGeneration:
    """The configuration this request is pinned to.

    Stored on request.state as well as returned, so that code reached
    from a route without the dependency in its signature -- a helper,
    a nested call -- uses the SAME generation rather than reading
    app.state again and possibly getting a newer one mid-request.
    """
    generation = request.app.state.generation
    request.state.generation = generation
    return generation
