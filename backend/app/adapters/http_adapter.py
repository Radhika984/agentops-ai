"""HTTPAdapter — invokes a System Under Test reachable over HTTP(S).

Response envelope convention (a documented convention this adapter
applies, not an assumption about hidden agent internals — see the locked
audit's observability-level rule: AgentOps never claims to know more
about a SUT than what it actually returned):

  If the agent's JSON response body is an object containing any of the
  optional keys "output", "tool_calls", "trace", "token_usage",
  "model_info", those keys are extracted into the matching
  AgentExecution field. Any key the agent's response does not contain is
  left at its default (None / [] on AgentExecution) — never inferred.

  If the response body has none of those keys (the common case for a
  Level 1 black-box agent that just returns its answer directly), the
  *entire* parsed body becomes AgentExecution.output verbatim, and
  tool_calls/trace/token_usage/model_info all stay unset.

  If the response body is not valid JSON, the raw text becomes
  AgentExecution.output as a plain string, raw_response is left None,
  and every other optional field stays unset.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from pydantic import BaseModel, Field

from app.adapters.base import AgentAdapter
from app.adapters.exceptions import ResponseTooLargeError
from app.adapters.execution import AgentExecution, ToolCallRecord, TraceSpanRecord
from app.adapters.url_safety import validate_agent_url

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES_DEFAULT = 2_000_000  # 2MB, per the locked audit's size limit
_ENVELOPE_KEYS = {"output", "tool_calls", "trace", "token_usage", "model_info"}


class HTTPAdapterConfig(BaseModel):
    """Validated shape of an HTTP adapter's configuration. `headers`
    holds literal values for this phase (there is no Credential store
    yet — that arrives with the Agent Registry in a later phase); a
    caller that needs an authenticated call passes the header value
    directly, and it is never persisted by this adapter (Phase 10 has no
    persistence at all) nor logged (see invoke()'s redaction)."""

    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_ms: int = 30_000
    max_response_bytes: int = MAX_RESPONSE_BYTES_DEFAULT


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Never persisted or logged with real values — used anywhere a
    representation of the request might otherwise leak a credential."""
    return {k: "***redacted***" for k in headers}


class HTTPAdapter(AgentAdapter):
    def __init__(
        self, config: HTTPAdapterConfig, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._config = config
        # `transport` is only ever passed in tests (httpx.MockTransport) —
        # production invocations always use the real network transport.
        self._transport = transport

    async def invoke(self, input: dict[str, Any]) -> AgentExecution:
        # Raises AdapterConfigError (scheme/SSRF/unresolvable host) —
        # deliberately before any timing/request_id bookkeeping starts,
        # so a config problem never produces a misleading AgentExecution.
        await validate_agent_url(self._config.url)

        request_id = uuid.uuid4()
        started_at = datetime.now(UTC)
        clock_start = time.monotonic()

        status: str
        error: str | None = None
        output: dict[str, Any] | str | None = None
        raw_response: dict[str, Any] | None = None
        tool_calls: list[ToolCallRecord] = []
        trace: list[TraceSpanRecord] | None = None
        token_usage: dict[str, Any] | None = None
        model_info: dict[str, Any] | None = None

        request_kwargs: dict[str, Any] = {"headers": self._config.headers}
        if self._config.method.upper() == "GET":
            request_kwargs["params"] = input
        else:
            request_kwargs["json"] = input

        logger.debug(
            "HTTPAdapter invoking %s %s (request_id=%s, headers=%s)",
            self._config.method.upper(),
            self._config.url,
            request_id,
            # Header values are never logged, even at debug level — only
            # which header *names* were sent, matching the locked audit's
            # "redaction of raw auth headers before persistence" rule
            # applied everywhere a request could otherwise be recorded.
            _redact_headers(self._config.headers),
        )

        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._config.timeout_ms / 1000, transport=self._transport
                ) as client,
                client.stream(
                    self._config.method.upper(), self._config.url, **request_kwargs
                ) as response,
            ):
                body = bytearray()
                too_large = False
                # httpx types aiter_bytes() as AsyncIterator[bytes], but it
                # is concretely an async generator; holding it in a
                # variable lets us explicitly aclose() it in `finally`
                # below regardless of whether the loop finishes, breaks,
                # or the body ends up oversized — an abandoned async
                # generator otherwise only gets cleaned up (with a
                # RuntimeWarning) at garbage-collection time.
                byte_stream = cast(AsyncGenerator[bytes, None], response.aiter_bytes())
                try:
                    async for chunk in byte_stream:
                        body.extend(chunk)
                        if len(body) > self._config.max_response_bytes:
                            too_large = True
                            break
                finally:
                    await byte_stream.aclose()
                body_bytes = bytes(body)
                http_status = response.status_code
            # Raised *after* the `async with` block above has exited
            # normally (stream/response/client all cleanly closed).
            if too_large:
                raise ResponseTooLargeError

            status = "ok"
            try:
                parsed = json.loads(body_bytes)
            except ValueError:
                parsed = None

            if isinstance(parsed, dict):
                raw_response = parsed
                if _ENVELOPE_KEYS & parsed.keys():
                    output = parsed.get("output")
                    tool_calls = [ToolCallRecord(**tc) for tc in parsed.get("tool_calls", []) or []]
                    trace_data = parsed.get("trace")
                    trace = [TraceSpanRecord(**s) for s in trace_data] if trace_data else None
                    token_usage = parsed.get("token_usage")
                    model_info = parsed.get("model_info")
                else:
                    output = parsed
            else:
                output = body_bytes.decode("utf-8", errors="replace")

            if http_status >= 400:
                status = "error"
                error = f"agent responded with HTTP {http_status}"

        except ResponseTooLargeError:
            status = "error"
            error = f"response truncated: exceeded {self._config.max_response_bytes} bytes"
        except httpx.TimeoutException:
            status = "timeout"
            error = f"adapter timeout after {self._config.timeout_ms}ms"
        except httpx.HTTPError as exc:
            status = "error"
            error = f"transport error: {exc}"

        finished_at = datetime.now(UTC)
        latency_ms = int((time.monotonic() - clock_start) * 1000)

        return AgentExecution(
            request_id=request_id,
            input=input,
            output=output,
            status=status,
            error=error,
            latency_ms=latency_ms,
            started_at=started_at,
            finished_at=finished_at,
            tool_calls=tool_calls,
            trace=trace,
            token_usage=token_usage,
            model_info=model_info,
            raw_response=raw_response,
        )
