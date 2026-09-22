"""
The CSRF token is compared in constant time (E-04).

`!=` stops at the first differing character, so how long a rejection
takes says how much of a guess was right. No timing test can be made
reliable on shared hardware, so the comparison is PINNED AT SOURCE --
parsed, so a comment naming compare_digest does not satisfy it -- and
the behaviour around it is tested normally.
"""

import ast
import inspect

import api.csrf_middleware as csrf
from tests.integration.test_api import _csrf_headers, _login

PW = "a-long-and-unremarkable-passphrase"


class TestPinnedAtSource:
    def _tree(self):
        return ast.parse(inspect.getsource(csrf))

    def test_the_token_is_compared_with_compare_digest(self):
        calls = [n for n in ast.walk(self._tree()) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "compare_digest"]
        assert calls

    def test_and_never_with_an_equality_operator(self):
        """Any `==` or `!=` between two values, in this module, is a
        comparison that could leak through timing."""
        equality = [n for n in ast.walk(self._tree()) if isinstance(n, ast.Compare)
                    and any(isinstance(op, ast.Eq | ast.NotEq) for op in n.ops)]
        assert equality == []


class TestTheBehaviourAroundIt:
    def _logged_in(self, client):
        client.app.state.user_directory.create_user("dana", PW, "us-west", "debug")
        _login(client, "dana", PW)

    def test_the_matching_token_is_accepted(self, client):
        self._logged_in(client)

        assert client.post("/api/logout", headers=_csrf_headers(client)).status_code == 204

    def test_a_different_token_is_refused(self, client):
        self._logged_in(client)

        response = client.post("/api/logout", headers={"X-CSRF-Token": "not-the-token"})

        assert response.status_code == 403

    def test_a_non_ascii_token_is_refused_not_a_server_error(self, client):
        """compare_digest RAISES on non-ASCII str -- a 500, and a leak of
        its own. So both sides are compared as bytes."""
        self._logged_in(client)

        response = client.post("/api/logout", headers={"X-CSRF-Token": "caf\u00e9-token".encode("latin-1")})

        assert response.status_code == 403
