"""URL/SSRF validation for HTTPAdapter.

Per the locked audit's Security section: this is a small allowlist/
denylist function appropriate for a single-user local/free tool, not a
general-purpose SSRF filter. It performs a resolve-then-check pass before
every invocation; it does not defend against DNS-rebinding attacks (a
host resolving to a safe IP at validation time and a different IP a
moment later) — that limitation is accepted and documented, matching the
audit's own framing of this as scoped protection, not a claim of
completeness.

Rules (all decided in the audit, not invented here):
  - scheme must be http or https.
  - "host.docker.internal" is always allowed, regardless of what IP it
    resolves to (the documented, required exception for reaching an
    agent running on the developer's own machine from inside the backend
    container).
  - loopback addresses (127.0.0.0/8, ::1) and the "localhost" hostname
    are always allowed.
  - the cloud-metadata address 169.254.169.254 (and its IPv6-mapped
    form) is always blocked, with no exception.
  - any other private-use or link-local address (RFC 1918, RFC 3927) is
    blocked.
  - any other (public) address is allowed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.adapters.exceptions import AdapterConfigError

_ALLOWED_SCHEMES = {"http", "https"}
_ALWAYS_ALLOWED_HOSTNAMES = {"host.docker.internal", "localhost"}
_METADATA_ADDRESSES = {"169.254.169.254", "::ffff:169.254.169.254"}


def _check_resolved_ip(ip_str: str, hostname: str) -> None:
    if ip_str in _METADATA_ADDRESSES:
        raise AdapterConfigError(
            f"URL resolves to a blocked cloud-metadata address ({ip_str})"
        )

    ip = ipaddress.ip_address(ip_str)
    if ip.is_loopback:
        return
    if hostname in _ALWAYS_ALLOWED_HOSTNAMES:
        return
    if ip.is_private or ip.is_link_local or ip.is_reserved:
        raise AdapterConfigError(
            f"URL resolves to a private/link-local address ({ip_str}) — "
            "only loopback and host.docker.internal are allowed for "
            "non-public agent addresses"
        )


async def validate_agent_url(url: str) -> None:
    """Raises AdapterConfigError if `url` is not safe to invoke.
    Otherwise returns None. Must be called before every real HTTP
    invocation — see http_adapter.py.
    """
    parsed = urlsplit(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise AdapterConfigError(
            f"unsupported URL scheme '{parsed.scheme}' — only http/https are allowed"
        )

    hostname = parsed.hostname
    if not hostname:
        raise AdapterConfigError("URL has no hostname")

    if hostname in _ALWAYS_ALLOWED_HOSTNAMES:
        return

    try:
        # getaddrinfo is blocking — run off the event loop so this
        # validation never stalls other concurrent request handling.
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
    except socket.gaierror as exc:
        raise AdapterConfigError(f"could not resolve host: {hostname}") from exc

    if not infos:
        raise AdapterConfigError(f"could not resolve host: {hostname}")

    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = str(sockaddr[0])
        _check_resolved_ip(ip_str, hostname)
