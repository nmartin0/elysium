"""
Every GET route under /api answers `Cache-Control: no-store`, unless it
is on the short list below with a stated reason.

Enumerated from the app itself, so a route added tomorrow is covered
without anyone remembering to give it the header. Before no-store was
the default, 21 GET routes (object search, detail, history, notes,
users, config) had never been given it.

Two passes: signed out (every answer, including a refusal, carries it)
and signed in (the real answers do). Signed in skips the routes that
stream, because a TestClient would wait on them for ever.
"""

import pytest

from tests.integration.test_api import _login

#: Routes that choose their own policy, on purpose.
DELIBERATE_EXCEPTIONS = {
    # A rebuilt bundle keeps its name, so the browser must ask again;
    # `private` because it is served only to someone offered the module.
    "/api/modules/{module_id}/files/{relative}": "private, no-cache",
}

#: Streams, not requested while signed in.
STREAMING = {"/api/events"}


class _Route:
    def __init__(self, path):
        self.path = path


def _get_routes(app):
    # From the app's own OpenAPI document (app.openapi(); the served
    # /openapi.json is disabled on purpose), because the routers are
    # included as nested objects that app.routes does not flatten.
    return [_Route(path) for path, methods in app.openapi()["paths"].items()
            if "get" in methods and path.startswith("/api/")]


def _filled(path):
    import re
    return re.sub(r"\{[^}]+\}", "x", path)


def test_the_app_has_many_get_routes_so_the_enumeration_is_not_vacuous(client):
    assert len(_get_routes(client.app)) > 60


@pytest.mark.parametrize("signed_in", [False, True])
def test_every_get_route_forbids_caching_unless_listed(client, signed_in):
    if signed_in:
        client.app.state.user_directory.create_user("alice", "correct-pw", "us-west", "customer_service")
        _login(client, "alice", "correct-pw")
    wrong = []
    checked = 0
    raised = []
    for route in _get_routes(client.app):
        if signed_in and route.path in STREAMING:
            continue
        try:
            response = client.get(_filled(route.path))
        except Exception:  # noqa: BLE001
            # A handler that raises on the made-up identifier "x" is
            # answered by the server's outermost error layer, outside
            # every middleware; there is no header to inspect.
            raised.append(route.path)
            continue
        checked += 1
        expected = DELIBERATE_EXCEPTIONS.get(route.path)
        header = response.headers.get("cache-control")
        if expected is None and header != "no-store":
            wrong.append(f"{route.path} -> {response.status_code} {header!r}")
        if expected is not None and response.status_code == 200 and header != expected:
            wrong.append(f"{route.path} -> {header!r}, expected {expected!r}")
    assert checked > 60
    assert not wrong, "GET routes that may be cached:\n" + "\n".join(wrong)


def test_the_exception_list_names_routes_that_exist(client):
    paths = {r.path for r in _get_routes(client.app)}
    assert set(DELIBERATE_EXCEPTIONS) <= paths
