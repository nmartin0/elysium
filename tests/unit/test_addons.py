"""An add-on's own server (BLOCKING.md item 3, step 2): what its manifest
may declare, the token that says who is asking, and which headers pass
the proxy (core/addons.py). The token is checked by the verifier add-ons
copy (sdk/python/elysium_addon.py), so the two cannot drift apart."""

import base64
import json
import sys
from pathlib import Path

import pytest

from core.addons import (
    AddonError,
    ServerSpec,
    command_line,
    parse_server,
    request_headers,
    response_headers,
    sign_identity,
)
from core.modules import ModuleError, _load_manifest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk" / "python"))
import elysium_addon  # noqa: E402

HERE = Path("module.json")
NOW = 1_800_000_000.0


class TestTheServerDeclaration:
    def test_a_command_with_defaults(self):
        spec = parse_server(HERE, {"command": ["{python}", "server.py"]})

        assert spec == ServerSpec(command=("{python}", "server.py"), health="/health", stop_seconds=10.0)

    def test_none_declared_is_none(self):
        assert parse_server(HERE, None) is None

    @pytest.mark.parametrize("raw, said", [
        ("python server.py", "must be an object"),
        ({"command": []}, "list of words"),
        ({"command": "server.py"}, "list of words"),
        ({"command": ["{pyhton}", "x.py"]}, "no other placeholder"),
        ({"command": ["{python}", "{port}"]}, "no other placeholder"),
        ({"command": ["x"], "health": "health"}, "a path such as /health"),
        ({"command": ["x"], "stopSeconds": 0}, "more than 0"),
        ({"command": ["x"], "stopSeconds": True}, "more than 0"),
        ({"command": ["x"], "stopSeconds": 301}, "at most 300"),
        ({"command": ["x"], "port": 80}, "does not understand ['port']"),
    ])
    def test_a_mistake_is_said_with_the_file(self, raw, said):
        with pytest.raises(AddonError, match="module.json") as refused:
            parse_server(HERE, raw)
        assert said in str(refused.value)

    def test_the_command_is_resolved_against_the_module_folder(self, tmp_path):
        assert command_line(parse_server(HERE, {"command": ["{python}", "s.py"]}), tmp_path) \
            == [sys.executable, "s.py"]
        assert command_line(parse_server(HERE, {"command": ["./run", "-v"]}), tmp_path) \
            == [str(tmp_path / "run"), "-v"]
        assert command_line(parse_server(HERE, {"command": ["node", "s.js"]}), tmp_path) == ["node", "s.js"]

    def test_a_manifest_carries_it_and_a_bad_one_is_refused_at_load(self, tmp_path):
        (tmp_path / "module.json").write_text(json.dumps({
            "id": "a", "name": "A", "version": "1", "server": {"command": ["{python}", "s.py"]}}))
        assert _load_manifest(tmp_path).server.command == ("{python}", "s.py")

        (tmp_path / "module.json").write_text(json.dumps({
            "id": "a", "name": "A", "version": "1", "server": {"command": []}}))
        with pytest.raises(ModuleError, match="server.command"):
            _load_manifest(tmp_path)


def _start(secret="s3cret", audience="sim") -> dict:
    return {"identity": {"header": "X-Elysium-Identity", "secret": secret,
                         "issuer": "elysium", "audience": audience}}


def _forge(claims: dict, header: dict) -> str:
    def part(value) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()
    return f"{part(header)}.{part(claims)}."


class TestTheToken:
    def test_the_add_on_reads_who_is_asking(self):
        token = sign_identity("s3cret", audience="sim", user_id="ada", now=NOW)

        claims = elysium_addon.identity({"X-Elysium-Identity": token}, _start(), now=NOW + 1)

        assert claims["sub"] == "ada" and claims["aud"] == "sim" and claims["iss"] == "elysium"
        assert claims["exp"] - claims["iat"] == 60

    def test_a_standard_jwt_library_reads_it_too(self):
        # INTEROPERABILITY, which is why it is a JWT: an add-on in any
        # language verifies it with the library it has. PyJWT is not one
        # of Elysium's dependencies; where it is installed, it agrees.
        jwt = pytest.importorskip("jwt")
        token = sign_identity("a-secret-at-least-32-bytes-long-ok", audience="sim", user_id="ada")

        claims = jwt.decode(token, "a-secret-at-least-32-bytes-long-ok", algorithms=["HS256"],
                            audience="sim", issuer="elysium")

        assert claims["sub"] == "ada"

    @pytest.mark.parametrize("secret, audience, at, said", [
        ("other", "sim", NOW, "signature does not match"),
        ("s3cret", "heliograph", NOW, "made for another add-on"),
        ("s3cret", "sim", NOW + 66, "expired"),
        ("s3cret", "sim", NOW - 66, "issued in the future"),
    ])
    def test_it_is_refused_by_another_secret_another_add_on_and_out_of_time(self, secret, audience, at, said):
        token = sign_identity("s3cret", audience="sim", user_id="ada", now=NOW)

        with pytest.raises(elysium_addon.NotSignedIn, match=said):
            elysium_addon.identity({"X-Elysium-Identity": token}, _start(secret, audience), now=at)

    def test_an_altered_body_is_refused(self):
        header, _body, signature = sign_identity("s3cret", audience="sim", user_id="ada", now=NOW).split(".")
        claims = {"iss": "elysium", "aud": "sim", "sub": "root", "name": "root", "iat": NOW, "exp": NOW + 60}
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

        with pytest.raises(elysium_addon.NotSignedIn, match="signature"):
            elysium_addon.verify(f"{header}.{body}.{signature}", secret="s3cret", audience="sim", now=NOW)

    def test_alg_none_is_refused_not_believed(self):
        claims = {"iss": "elysium", "aud": "sim", "sub": "root", "iat": NOW, "exp": NOW + 60}

        with pytest.raises(elysium_addon.NotSignedIn, match="HS256"):
            elysium_addon.verify(_forge(claims, {"alg": "none"}), secret="s3cret", audience="sim", now=NOW)

    @pytest.mark.parametrize("headers", [{}, {"X-Elysium-Identity": ""}, {"X-Elysium-Identity": "a.b"}])
    def test_none_or_garbage_is_not_signed_in(self, headers):
        with pytest.raises(elysium_addon.NotSignedIn):
            elysium_addon.identity(headers, _start(), now=NOW)


class TestWhatPasses:
    def test_the_session_and_any_claimed_identity_stay_behind(self):
        passed = request_headers([
            ("Cookie", "elysium_session=abc"), ("Authorization", "Bearer x"),
            ("X-CSRF-Token", "t"), ("X-Elysium-Identity", "forged"), ("X-Forwarded-For", "1.2.3.4"),
            ("Accept", "application/json"), ("Content-Type", "application/json"), ("Last-Event-ID", "7"),
        ])

        assert passed == {"Accept": "application/json", "Content-Type": "application/json", "Last-Event-ID": "7"}

    def test_a_cookie_or_a_loopback_address_does_not_come_back(self):
        passed = response_headers([
            ("Set-Cookie", "elysium_session=stolen"), ("Location", "http://127.0.0.1:9/x"),
            ("Content-Security-Policy", "script-src *"), ("Content-Type", "text/plain"), ("ETag", '"1"'),
        ])

        assert passed == {"Content-Type": "text/plain", "ETag": '"1"'}
