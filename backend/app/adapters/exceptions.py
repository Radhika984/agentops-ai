"""Adapter-layer domain exceptions.

Per app/core/exceptions.py's own convention: framework-independent,
mapped to an HTTP response only at the API layer (app/api/v1/*).

Note the distinction this module enforces: a problem with the *adapter
configuration itself* (a blocked URL, an unresolvable host, a malformed
config) is a real error, raised before any agent is ever invoked — it
never produces an AgentExecution. A problem *during* invocation (the
agent errored, timed out, or returned something odd) is not raised at
all: it is captured as data, via AgentExecution(status="error"/"timeout",
error=...) — see http_adapter.py / local_adapter.py. This mirrors the
locked audit's rule that adapter/config problems and real-agent-execution
outcomes must never be conflated.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for adapter-layer errors."""


class AdapterConfigError(AdapterError):
    """Raised when an adapter's configuration is invalid or unsafe to use
    — an unsupported URL scheme, a blocked/private-network target, an
    unresolvable host, or a malformed adapter-specific config field.
    Always raised before invocation, never mid-call."""


class ResponseTooLargeError(AdapterError):
    """Raised internally by HTTPAdapter when the connected agent's
    response body exceeds the configured size limit. Caught by the
    adapter itself and turned into AgentExecution(status="error"), never
    propagated to the API layer."""
