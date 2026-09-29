"""LocalAdapter — invokes an agent importable in the same Python process.

Per the locked audit (§6, §27): "LocalAdapter is trusted local-development
functionality" — it dynamically imports and calls a Python callable by
module path, which means it executes arbitrary code the developer
configuring it already has filesystem access to run anyway. It is
documented, not sandboxed, and must never be offered as a way to run
code from an untrusted or remote source.

Response envelope convention — identical to HTTPAdapter's, applied to the
callable's return value instead of an HTTP response body, so both
adapters normalize into AgentExecution the same way:

  - If the callable returns a dict containing any of "output",
    "tool_calls", "trace", "token_usage", "model_info", those keys are
    extracted; any key not present stays unset.
  - If the callable returns a dict with none of those keys, the whole
    dict becomes `output` verbatim.
  - If the callable returns anything else (a string, a list, a number),
    that value becomes `output` verbatim.
"""

from __future__ import annotations

import importlib
import inspect
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.adapters.base import AgentAdapter
from app.adapters.exceptions import AdapterConfigError
from app.adapters.execution import AgentExecution, ToolCallRecord, TraceSpanRecord

_ENVELOPE_KEYS = {"output", "tool_calls", "trace", "token_usage", "model_info"}


class LocalAdapterConfig(BaseModel):
    module_path: str
    callable_name: str = "invoke"


def _resolve_callable(config: LocalAdapterConfig) -> Any:
    try:
        module = importlib.import_module(config.module_path)
    except ImportError as exc:
        raise AdapterConfigError(
            f"could not import module '{config.module_path}': {exc}"
        ) from exc

    target = getattr(module, config.callable_name, None)
    if target is None or not callable(target):
        raise AdapterConfigError(
            f"'{config.module_path}' has no callable attribute '{config.callable_name}'"
        )
    return target


class LocalAdapter(AgentAdapter):
    def __init__(self, config: LocalAdapterConfig) -> None:
        self._config = config
        # Resolved eagerly, at construction time — a bad module_path/
        # callable_name is a configuration error, exactly like an
        # unsafe URL for HTTPAdapter, and should fail the same way
        # (before invocation, not mid-call).
        self._callable = _resolve_callable(config)

    async def invoke(self, input: dict[str, Any]) -> AgentExecution:
        request_id = uuid.uuid4()
        started_at = datetime.now(UTC)
        clock_start = time.monotonic()

        status: str = "ok"
        error: str | None = None
        output: dict[str, Any] | str | None = None
        raw_response: dict[str, Any] | None = None
        tool_calls: list[ToolCallRecord] = []
        trace: list[TraceSpanRecord] | None = None
        token_usage: dict[str, Any] | None = None
        model_info: dict[str, Any] | None = None

        try:
            result = self._callable(input)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 - a SUT's own bug must not crash AgentOps
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
        else:
            if isinstance(result, dict):
                if _ENVELOPE_KEYS & result.keys():
                    raw_response = result
                    output = result.get("output")
                    tool_calls = [ToolCallRecord(**tc) for tc in result.get("tool_calls", []) or []]
                    trace_data = result.get("trace")
                    trace = [TraceSpanRecord(**s) for s in trace_data] if trace_data else None
                    token_usage = result.get("token_usage")
                    model_info = result.get("model_info")
                else:
                    output = result
                    raw_response = result
            elif isinstance(result, str) or result is None:
                output = result
            else:
                # Anything else JSON-shaped (list, number, bool) is
                # preserved as-is inside a wrapper so `output`'s declared
                # type (dict | str | None) always holds.
                output = {"value": result}

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
