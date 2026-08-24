"""
logging_config.py  (generic -- org-agnostic)

One place to configure how diagnostic messages look and where they go,
instead of every module (core/agent/agentic_loop.py, core/llm/agent_step_prompt.py,
and any future one) hand-typing its own "[tag] message" prefix via
print(). Standard logging.getLogger(__name__) already includes the
calling module's own name -- e.g. "core.agent.agentic_loop" -- so no manual
tagging is needed anywhere once this is configured.

Called once, at the start of a real entry point (e.g.
deployments/<org>/test_run.py). Library code (agentic_loop.py, etc.) never
calls this itself -- it just does logging.getLogger(__name__) and lets
whoever configured logging decide the format/level/destination.
"""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="[%(name)s] %(message)s")
