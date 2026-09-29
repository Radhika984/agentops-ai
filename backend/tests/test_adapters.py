"""Phase 10 — Agent Adapter layer unit tests.

No network access, no real agent, no DB (the adapter layer itself has no
persistence in this phase) — HTTPAdapter is tested against
httpx.MockTransport (a real httpx transport, so the adapter's actual
request/response handling code runs, just without a socket), LocalAdapter
against a real toy module under tests/fixtures/.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.exceptions import AdapterConfigError
from app.adapters.factory import build_adapter
from app.adapters.http_adapter import HTTPAdapter, HTTPAdapterConfig
from app.adapters.local_adapter import LocalAdapter, LocalAdapterConfig
from app.adapters.url_safety import validate_agent_url

# ---- url_safety ------------------------------------------------------


async def test_public_https_url_is_allowed() -> None:
    await validate_agent_url("https://example.com/agent")


async def test_loopback_is_allowed() -> None:
    await validate_agent_url("http://127.0.0.1:8080/agent")
    await validate_agent_url("http://localhost:8080/agent")


async def test_host_docker_internal_is_allowed_without_dns_resolution() -> None:
    # Must not raise even though this hostname would not resolve in a
    # test environment outside Docker Desktop — it's allowed by name,
    # before any getaddrinfo() call.
    await validate_agent_url("http://host.docker.internal:9000/agent")


async def test_disallowed_scheme_is_blocked() -> None:
    with pytest.raises(AdapterConfigError, match="scheme"):
        await validate_agent_url("ftp://example.com/agent")


async def test_file_scheme_is_blocked() -> None:
    with pytest.raises(AdapterConfigError, match="scheme"):
        await validate_agent_url("file:///etc/passwd")


async def test_metadata_ip_is_blocked() -> None:
    with pytest.raises(AdapterConfigError, match="metadata"):
        await validate_agent_url("http://169.254.169.254/latest/meta-data/")


async def test_private_network_ip_is_blocked() -> None:
    with pytest.raises(AdapterConfigError, match="private"):
        await validate_agent_url("http://192.168.1.50:8080/agent")


async def test_unresolvable_host_is_blocked() -> None:
    with pytest.raises(AdapterConfigError, match="resolve"):
        await validate_agent_url("http://this-host-does-not-exist.invalid/agent")


# ---- HTTPAdapter -------------------------------------------------------


def _mock_transport(handler: object) -> httpx.MockTransport:
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


async def test_http_adapter_extracts_envelope_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": {"answer": "42"},
                "tool_calls": [
                    {"tool_name": "calc", "input": {"expr": "6*7"}, "output": "42", "ok": True}
                ],
                "token_usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent"), transport=_mock_transport(handler)
    )
    execution = await adapter.invoke({"question": "what is 6*7"})

    assert execution.status == "ok"
    assert execution.output == {"answer": "42"}
    assert len(execution.tool_calls) == 1
    assert execution.tool_calls[0].tool_name == "calc"
    assert execution.token_usage == {"input_tokens": 5, "output_tokens": 2}
    assert execution.trace is None  # never fabricated — the response had none
    assert execution.latency_ms >= 0


async def test_http_adapter_without_envelope_keys_uses_whole_body_as_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "Paris", "confidence": 0.9})

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent"), transport=_mock_transport(handler)
    )
    execution = await adapter.invoke({"question": "capital of France?"})

    assert execution.status == "ok"
    assert execution.output == {"answer": "Paris", "confidence": 0.9}
    assert execution.tool_calls == []


async def test_http_adapter_handles_non_json_response_as_plain_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="just plain text, not json")

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent"), transport=_mock_transport(handler)
    )
    execution = await adapter.invoke({"question": "hi"})

    assert execution.status == "ok"
    assert execution.output == "just plain text, not json"
    assert execution.raw_response is None


async def test_http_adapter_error_status_code_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "internal error"})

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent"), transport=_mock_transport(handler)
    )
    execution = await adapter.invoke({"question": "hi"})

    assert execution.status == "error"
    assert execution.error is not None
    assert "500" in execution.error


async def test_http_adapter_timeout_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent"), transport=_mock_transport(handler)
    )
    execution = await adapter.invoke({"question": "hi"})

    assert execution.status == "timeout"
    assert execution.error is not None


async def test_http_adapter_transport_error_is_captured_not_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent"), transport=_mock_transport(handler)
    )
    execution = await adapter.invoke({"question": "hi"})

    assert execution.status == "error"
    assert "transport error" in (execution.error or "")


async def test_http_adapter_oversized_response_is_truncated_as_error() -> None:
    big_body = json.dumps({"output": "x" * 1000}).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big_body)

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://127.0.0.1:9999/agent", max_response_bytes=100),
        transport=_mock_transport(handler),
    )
    execution = await adapter.invoke({"question": "hi"})

    assert execution.status == "error"
    assert "truncated" in (execution.error or "")


async def test_http_adapter_raises_config_error_for_blocked_url_before_invoking() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"output": "should never get here"})

    adapter = HTTPAdapter(
        HTTPAdapterConfig(url="http://169.254.169.254/latest/meta-data/"),
        transport=_mock_transport(handler),
    )

    with pytest.raises(AdapterConfigError):
        await adapter.invoke({"question": "hi"})

    assert calls == []  # the agent (mock transport) must never have been reached


async def test_http_adapter_never_echoes_header_values_in_output() -> None:
    received_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received_headers.update(request.headers)
        return httpx.Response(200, json={"output": "ok"})

    adapter = HTTPAdapter(
        HTTPAdapterConfig(
            url="http://127.0.0.1:9999/agent", headers={"Authorization": "Bearer super-secret"}
        ),
        transport=_mock_transport(handler),
    )
    execution = await adapter.invoke({"question": "hi"})

    # The header really was sent to the agent (that's the whole point of
    # header injection)...
    assert received_headers.get("authorization") == "Bearer super-secret"
    # ...but never reflected back anywhere in the normalized execution
    # AgentOps stores/returns.
    assert "super-secret" not in json.dumps(execution.model_dump(mode="json"))


# ---- LocalAdapter -------------------------------------------------------


async def test_local_adapter_sync_callable() -> None:
    adapter = LocalAdapter(
        LocalAdapterConfig(module_path="tests.fixtures.toy_agent", callable_name="invoke")
    )
    execution = await adapter.invoke({"question": "hello"})

    assert execution.status == "ok"
    assert execution.output == "echo: hello"


async def test_local_adapter_async_callable_with_tool_calls() -> None:
    adapter = LocalAdapter(
        LocalAdapterConfig(module_path="tests.fixtures.toy_agent", callable_name="invoke_async")
    )
    execution = await adapter.invoke({"question": "what is 6*7"})

    assert execution.status == "ok"
    assert execution.output == {"answer": "42"}
    assert len(execution.tool_calls) == 1
    assert execution.tool_calls[0].tool_name == "calculator"


async def test_local_adapter_plain_string_return() -> None:
    adapter = LocalAdapter(
        LocalAdapterConfig(
            module_path="tests.fixtures.toy_agent", callable_name="invoke_plain_string"
        )
    )
    execution = await adapter.invoke({"question": "hello"})

    assert execution.status == "ok"
    assert execution.output == "just a plain string answer"


async def test_local_adapter_exception_is_captured_not_raised() -> None:
    adapter = LocalAdapter(
        LocalAdapterConfig(module_path="tests.fixtures.toy_agent", callable_name="invoke_raises")
    )
    execution = await adapter.invoke({"question": "hello"})

    assert execution.status == "error"
    assert "the toy agent broke" in (execution.error or "")


async def test_local_adapter_bad_module_path_raises_config_error() -> None:
    with pytest.raises(AdapterConfigError, match="could not import"):
        LocalAdapter(LocalAdapterConfig(module_path="tests.fixtures.does_not_exist"))


async def test_local_adapter_bad_callable_name_raises_config_error() -> None:
    with pytest.raises(AdapterConfigError, match="no callable attribute"):
        LocalAdapter(
            LocalAdapterConfig(
                module_path="tests.fixtures.toy_agent", callable_name="does_not_exist"
            )
        )


# ---- factory -------------------------------------------------------


async def test_factory_builds_http_adapter() -> None:
    adapter = build_adapter("http", {"url": "https://example.com/agent"})
    assert isinstance(adapter, HTTPAdapter)


async def test_factory_builds_local_adapter() -> None:
    adapter = build_adapter("local", {"module_path": "tests.fixtures.toy_agent"})
    assert isinstance(adapter, LocalAdapter)


async def test_factory_rejects_unsupported_adapter_type() -> None:
    with pytest.raises(AdapterConfigError, match="unsupported adapter_type"):
        build_adapter("webhook", {})


async def test_factory_rejects_http_config_missing_url() -> None:
    with pytest.raises(AdapterConfigError, match="invalid http adapter config"):
        build_adapter("http", {})


async def test_factory_rejects_local_config_missing_module_path() -> None:
    with pytest.raises(AdapterConfigError, match="invalid local adapter config"):
        build_adapter("local", {})
