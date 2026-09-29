"""Builds a concrete AgentAdapter from an adapter_type + raw config dict.

The one place that maps the two adapter_type strings this phase supports
("http", "local") to their concrete classes — per the tools/registry.py
precedent already in this codebase (a single seam every caller goes
through, so adding a third adapter type later never requires touching
call sites). A third type is out of scope for Phase 10 per the locked
audit — attempting one raises AdapterConfigError, the same error class
used for every other configuration problem in this layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.adapters.base import AgentAdapter
from app.adapters.exceptions import AdapterConfigError
from app.adapters.http_adapter import HTTPAdapter, HTTPAdapterConfig
from app.adapters.local_adapter import LocalAdapter, LocalAdapterConfig

_SUPPORTED_ADAPTER_TYPES = ("http", "local")


def build_adapter(adapter_type: str, adapter_config: dict[str, Any]) -> AgentAdapter:
    if adapter_type == "http":
        try:
            http_config = HTTPAdapterConfig.model_validate(adapter_config)
        except ValidationError as exc:
            raise AdapterConfigError(f"invalid http adapter config: {exc}") from exc
        return HTTPAdapter(http_config)

    if adapter_type == "local":
        try:
            local_config = LocalAdapterConfig.model_validate(adapter_config)
        except ValidationError as exc:
            raise AdapterConfigError(f"invalid local adapter config: {exc}") from exc
        return LocalAdapter(local_config)

    raise AdapterConfigError(
        f"unsupported adapter_type '{adapter_type}' — must be one of {_SUPPORTED_ADAPTER_TYPES}"
    )
