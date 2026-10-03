"""Which value identifies a caller, when there may be a proxy in front.

`E-02`'s residual, and the question it left open: unauthenticated
requests are counted per source, and there was no correct source to
count them by. Both call sites passed nothing.

THE ANSWER IS SETTLED PRECEDENT, not a judgement call. Six independent
projects reached the same four rules, and the failure they each fixed
was the same one:

    Any client can send `X-Forwarded-For: 1.2.3.4` to be rate-limited
    as 1.2.3.4 instead of their real IP. By rotating the spoofed
    header value, an attacker bypasses per-IP limits entirely.

AND THE REVERSE IS WORSE, because it needs no account and harms
someone else:

    An attacker can spoof a victim's IP address in X-Forwarded-For and
    intentionally trigger rate limits, causing a Denial of Service for
    innocent users behind corporate NATs or cellular proxies.

THE FOUR RULES:

1. DEFAULT TO THE PEER ADDRESS. The TCP peer is the one value a client
   cannot forge. Everything else is a header.

2. HONOUR `X-Forwarded-For` ONLY FROM A TRUSTED PEER, listed by the
   deployment. The default list is EMPTY, so a deployment that has not
   said it sits behind a proxy ignores the header entirely -- the same
   shape as `write_targets`, and for the same reason: a capability
   nobody configured should not be on.

3. TAKE THE RIGHTMOST HOP, not the leftmost. nginx's
   `$proxy_add_x_forwarded_for` APPENDS the peer it saw, so the
   rightmost entry is the one the immediate proxy wrote and the
   leftmost is whatever the client sent. Reading the leftmost is the
   bug in every one of those six reports.

4. A MALFORMED HEADER FALLS BACK TO THE PEER, loudly. One of those
   projects shipped a silent fallback and had to fix it twice.

WHAT THIS IS NOT. It is not an identity, and nothing here should be
used for authorization. It is a bucketing key for a bound, and a
caller behind a corporate NAT legitimately shares one with thousands
of others -- which is exactly why the bound is per source and
generous rather than per source and tight.
"""

import ipaddress
import logging

logger = logging.getLogger(__name__)

#: The header nginx and most proxies append to.
FORWARDED_HEADER = "x-forwarded-for"

#: What a caller is counted as when there is no address at all -- a
#: test client, or an ASGI server that reports none. One shared bucket
#: is right here: an unidentifiable caller should not get a private
#: allowance by being unidentifiable.
UNKNOWN_SOURCE = "unknown"


def _peer(request) -> str:
    """The TCP peer address, or UNKNOWN_SOURCE."""
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or UNKNOWN_SOURCE


def _is_trusted(address: str, trusted: "tuple[str, ...]") -> bool:
    """Whether the peer is one of the deployment's own proxies.

    CIDR, because a proxy in a cluster does not have a stable address.
    An unparseable entry is ignored rather than treated as a match --
    failing open on a typo in a trust list is the whole hazard.
    """
    try:
        peer = ipaddress.ip_address(address)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if peer in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            logger.warning(
                "trusted_proxies entry %r is not a valid address or CIDR "
                "and is ignored; the header will NOT be trusted from it",
                entry)
    return False


def client_source(request, trusted_proxies: "tuple[str, ...]" = ()) -> str:
    """The value a caller is counted as.

    Returns the peer address unless the peer is a declared proxy, in
    which case the rightmost forwarded hop.
    """
    peer = _peer(request)
    if not trusted_proxies or not _is_trusted(peer, trusted_proxies):
        return peer

    headers = getattr(request, "headers", {})
    forwarded = headers.get(FORWARDED_HEADER) if headers else None
    if not forwarded:
        # A trusted proxy that sent nothing. Its own address is the
        # honest answer, not a guess.
        return peer

    # RIGHTMOST: the hop the immediate proxy appended.
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            continue
        return hop

    logger.warning(
        "%s from trusted proxy %s held no usable address (%r); counting "
        "against the proxy itself", FORWARDED_HEADER, peer, forwarded[:120])
    return peer
