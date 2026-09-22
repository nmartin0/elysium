"""
Every response denies the powerful browser features nothing here uses
(E-05): camera, microphone, geolocation, payment, USB.
"""

import pytest

from api.app import PERMISSIONS_POLICY

DENIED = ["camera", "microphone", "geolocation", "payment", "usb"]


def test_each_feature_is_denied_to_everyone_including_this_origin():
    """`()` is the empty allowlist; `(self)` would allow this origin."""
    directives = dict(part.strip().split("=", 1) for part in PERMISSIONS_POLICY.split(","))

    assert directives == {feature: "()" for feature in DENIED}


@pytest.mark.parametrize("path", ["/api/health", "/", "/api/no-such-thing"])
def test_every_response_carries_it(client, path):
    """INCLUDING ERRORS: a middleware that only decorated successes would
    leave the 404 undecorated."""
    response = client.get(path)

    assert response.headers.get("Permissions-Policy") == PERMISSIONS_POLICY
