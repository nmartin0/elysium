"""
Test for scripts/serve_requests.py -- this had ZERO test coverage
before, and was silently broken: it called AgentLoop.run() with a raw
user_id string, which stopped working the moment run() was refactored
to require a resolved UserRecord (core/intermediate_layer/auth.py).
Nothing caught this until it was found by inspection, not by a test --
this file exists so that never happens silently again.

Marked @pytest.mark.mocked_llm -- exercises the real serve()
dispatch/concurrency path with a real AgentLoop, but the LLM call
itself is mocked, so this stays fast enough to run every time. See
pytest.ini for both markers' registered descriptions.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.serve_requests import serve
from core.agent.agentic_loop import AgentLoopResult

pytestmark = pytest.mark.mocked_llm


def test_serve_dispatches_multiple_users_concurrently_without_crashing():
    seq = [{"step": "finish"}]

    def fake_post(*args, **kwargs):
        response = MagicMock()
        response.json.return_value = {"message": {"content": json.dumps(seq[0])}}
        response.raise_for_status.return_value = None
        return response

    with patch("adapters.ollama_adapter.requests.post", side_effect=fake_post):
        results = serve([("user_alice", "q1"), ("user_carol", "q2"), ("user_alice", "q3")])

    assert len(results) == 3
    for result in results:
        assert isinstance(result, AgentLoopResult)
