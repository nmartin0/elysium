"""
A caller cannot pick which rate-limit bucket it lands in.

`E-02`'s residual: unauthenticated requests are counted per source,
and there was no correct source. BOTH CALL SITES PASSED NOTHING, so
every failed login in a deployment shared one bucket.

THE PRECEDENT IS UNANIMOUS. Six independent projects fixed the same
defect, and the two directions of the attack are both in their
reports:

    Any client can send `X-Forwarded-For: 1.2.3.4` to be rate-limited
    as 1.2.3.4 instead of their real IP. By rotating the spoofed
    header value, an attacker bypasses per-IP limits entirely.

    An attacker can spoof a victim's IP address in X-Forwarded-For and
    intentionally trigger rate limits, causing a Denial of Service for
    innocent users behind corporate NATs or cellular proxies.

The second needs no account at all, which is the same property OWASP
names in the finding this bound exists for.

FOUR RULES, and the tests below are one class each:

1. Default to the TCP peer -- the one value a client cannot forge.
2. Trust `X-Forwarded-For` only from a declared proxy, default NONE.
3. Take the RIGHTMOST hop. nginx's `$proxy_add_x_forwarded_for`
   APPENDS, so the rightmost is what the proxy wrote and the leftmost
   is whatever the client sent. Reading the leftmost is the bug in
   every one of those six reports.
4. A malformed header falls back to the peer, loudly.

IT IS NOT AN IDENTITY. Nothing here may be used for authorization. It
is a bucketing key, and a caller behind a corporate NAT legitimately
shares one with thousands of others.
"""

import pytest

from core.auth.client_source import UNKNOWN_SOURCE, client_source


class _Request:
    def __init__(self, peer, forwarded=None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


class TestTheDefaultIsThePeer:
    def test_with_nothing_configured(self):
        assert client_source(_Request("203.0.113.9")) == "203.0.113.9"

    def test_a_header_from_an_untrusted_peer_is_IGNORED(self):
        """THE ATTACK. A client sending its own header must not get to
        choose its bucket."""
        request = _Request("203.0.113.9", "1.2.3.4")

        assert client_source(request) == "203.0.113.9"

    def test_even_when_other_proxies_are_trusted(self):
        """Trusting one peer must not trust every peer."""
        request = _Request("203.0.113.9", "1.2.3.4")

        assert client_source(request, ("10.0.0.0/8",)) == "203.0.113.9"

    def test_no_peer_at_all_shares_one_bucket(self):
        """An unidentifiable caller must not get a PRIVATE allowance by
        being unidentifiable."""
        assert client_source(_Request(None)) == UNKNOWN_SOURCE


class TestTrustIsDeclaredAndEmptyByDefault:
    def test_an_empty_list_trusts_nobody(self):
        request = _Request("10.0.0.5", "1.2.3.4")

        assert client_source(request, ()) == "10.0.0.5"

    def test_a_declared_proxy_is_believed(self):
        request = _Request("10.0.0.5", "1.2.3.4")

        assert client_source(request, ("10.0.0.0/8",)) == "1.2.3.4"

    @pytest.mark.parametrize("entry", ["10.0.0.5", "10.0.0.0/8", "10.0.0.5/32"])
    def test_an_address_or_a_cidr_both_work(self, entry):
        """A proxy in a cluster has no stable address."""
        request = _Request("10.0.0.5", "1.2.3.4")

        assert client_source(request, (entry,)) == "1.2.3.4"

    def test_a_malformed_trust_entry_does_not_match(self):
        """Failing OPEN on a typo in a trust list is the whole hazard."""
        request = _Request("10.0.0.5", "1.2.3.4")

        assert client_source(request, ("not-an-address",)) == "10.0.0.5"


class TestTheRightmostHop:
    def test_two_hops_takes_the_one_the_proxy_appended(self):
        """THE BUG IN EVERY ONE OF THOSE SIX REPORTS. With
        `$proxy_add_x_forwarded_for` the leftmost entry is whatever the
        client sent; the rightmost is what the proxy saw."""
        request = _Request("10.0.0.5", "1.2.3.4, 198.51.100.7")

        assert client_source(request, ("10.0.0.0/8",)) == "198.51.100.7"

    def test_a_long_chain_still_takes_the_last(self):
        request = _Request("10.0.0.5", "9.9.9.9, 8.8.8.8, 198.51.100.7")

        assert client_source(request, ("10.0.0.0/8",)) == "198.51.100.7"

    def test_a_forged_prefix_cannot_displace_it(self):
        """A client prepending a victim's address must not get that
        victim rate-limited."""
        request = _Request("10.0.0.5", "203.0.113.1, 198.51.100.7")

        assert client_source(request, ("10.0.0.0/8",)) != "203.0.113.1"


class TestMalformedHeadersFallBackLoudly:
    def test_an_unusable_header_counts_against_the_proxy(self, caplog):
        """One of those six projects shipped a SILENT fallback here and
        had to fix it twice."""
        request = _Request("10.0.0.5", "garbage")

        with caplog.at_level("WARNING"):
            source = client_source(request, ("10.0.0.0/8",))

        assert source == "10.0.0.5"
        assert "no usable address" in caplog.text

    def test_a_trusted_proxy_sending_nothing_is_not_an_error(self):
        """Its own address is the honest answer, not a guess."""
        request = _Request("10.0.0.5")

        assert client_source(request, ("10.0.0.0/8",)) == "10.0.0.5"

    def test_a_partly_unusable_chain_takes_the_last_usable_hop(self):
        request = _Request("10.0.0.5", "1.2.3.4, nonsense")

        assert client_source(request, ("10.0.0.0/8",)) == "1.2.3.4"


class TestItIsActuallyCalled:
    """The half this codebase has forgotten seven times."""

    def test_both_login_failure_paths_pass_a_source(self):
        from pathlib import Path

        source = Path("api/routes.py").read_text()
        calls = [line for line in source.splitlines()
                 if "record_failure(" in line and "def " not in line]

        assert len(calls) >= 1
        joined = "\n".join(
            source[source.index(call):source.index(call) + 160]
            for call in calls)
        assert joined.count("_client_source(request)") == len(calls), joined

    def test_the_deployment_can_declare_its_proxies(self):
        import dataclasses

        from core.deployment_loader import DeploymentConfig

        names = {field.name for field in dataclasses.fields(DeploymentConfig)}

        assert "trusted_proxies" in names
