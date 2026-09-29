"""Thin LLM client layer.

Provides a single entry point, call_model(), which every agent already
calls with a prompt + a caller-supplied Pydantic schema (unchanged since
Phase 2) and validates the structured JSON response against it. Phase 8
changes only what happens *inside* call_model(): it no longer talks to
the google-genai SDK directly — every call now goes through
app/ai/router.py (model selection + fallback across a group's priority
list, per app/ai/router.py's own docstring for why litellm's functional
API is used instead of its Router class), optionally checks
app/ai/cache.py first for calls the caller marks `cacheable=True`, and
logs every real (non-cached) call to the model_calls table for the cost
dashboard (agents/cost_optimization.py, api/v1/cost.py).

Retry policy: unchanged from Phase 2 — if the model's output cannot be
parsed as JSON and validated against the supplied schema, the client
retries exactly once with an explicit instruction that the previous
response was invalid. If the second attempt also fails validation, a
ModelOutputValidationError is raised. There is never a third attempt.
This is a *separate* retry layer from router.py's model-fallback loop:
router.py retries across models for transport/availability failures;
this retries the *same* successfully-reached model once for a malformed
response. The two compose (a retried call still goes through the full
model-fallback list).

model_calls logging failure must never break an agent's actual model
call — it opens its own DB session (same fire-and-forget background
-session pattern as services/run_service.py's run_graph_and_persist, for
the same reason: this is not necessarily running inside a request's
own DI-scoped session) and swallows any error.
"""

from __future__ import annotations

import contextvars
import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai import cache, router
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.observability.tracing import current_run_id
from app.repositories.model_call_repository import ModelCallRepository

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Who to attribute the next model_calls row to (GET /api/v1/cost's
# scoping key — see the 202609270001 migration for why this exists).
# A contextvar, not a call_model() parameter, for the same reason
# app/observability/tracing.py's current_run_id is one: every real call
# site is several layers below the already-ownership-checked service
# method that knows the owner (Suite Runner's trial evaluation, RCA's
# hypothesis tier, the legacy Run graph's nodes, ...) — threading an
# explicit owner_id parameter through every one of those layers would be
# a far larger, more invasive change than setting this once at each
# top-level entry point and letting it flow through the existing async
# call chain. asyncio contextvars are isolated per-Task, so concurrent
# requests from different users never bleed into each other's calls.
current_owner_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_owner_id", default=None
)


@contextmanager
def owner_call_context(owner_id: uuid.UUID | None) -> Iterator[None]:
    """Attributes every model_calls row logged during this block to
    `owner_id`. Call this once, near the top of an already
    ownership-checked service method, before it does anything that might
    reach call_model() — see run_service.py, suite_runner.py,
    rca_service.py, ask_service.py, production_execution_service.py for
    the real entry points."""
    token = current_owner_id.set(str(owner_id) if owner_id is not None else None)
    try:
        yield
    finally:
        current_owner_id.reset(token)

_RETRY_INSTRUCTION = (
    "\n\nYour previous response could not be parsed as valid JSON matching the "
    "required schema. Return a corrected response that is valid JSON matching "
    "the required schema exactly, with no additional text."
)


class AIClientError(Exception):
    """Base class for application-level AI client errors."""


class MissingAPIKeyError(AIClientError):
    """Raised when GEMINI_API_KEY is not configured at call time.

    The application must still start and existing functionality must still
    work without an API key configured; this error is only raised if the
    model client is actually invoked.
    """


class ModelOutputValidationError(AIClientError):
    """Raised when the model's structured output could not be validated,
    even after the single allowed retry."""


class ModelUnavailableError(AIClientError):
    """Raised when every model in the requested group's fallback list
    failed (see app/ai/router.py's AllModelsFailedError). Re-raised here
    as an AIClientError subclass — not left as router.py's own exception
    type — because Safety and Hallucination's existing `except
    AIClientError` fail-closed/fail-open handling is written against
    this module's exception hierarchy; letting a raw router-layer
    exception escape instead would have silently bypassed that handling
    for exactly the case (every model unavailable) it exists for."""


def _parse_and_validate(raw_text: str | None, schema: type[SchemaT]) -> SchemaT:
    data: Any = json.loads(raw_text or "")
    return schema.model_validate(data)


async def _log_model_call(
    *,
    agent: str,
    model_group: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost: float,
    cache_hit: bool,
) -> None:
    run_id_str = current_run_id.get()
    run_id = uuid.UUID(run_id_str) if run_id_str is not None else None
    owner_id_str = current_owner_id.get()
    owner_id = uuid.UUID(owner_id_str) if owner_id_str is not None else None
    try:
        async with AsyncSessionLocal() as session:
            repo = ModelCallRepository(session)
            await repo.create(
                agent=agent,
                model_group=model_group,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost=cost,
                cache_hit=cache_hit,
                run_id=run_id,
                owner_id=owner_id,
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to log model_calls row; continuing.", exc_info=True)


async def call_model(
    prompt: str,
    schema: type[SchemaT],
    *,
    agent: str = "unknown",
    model_group: str = "reasoning",
    cacheable: bool = False,
) -> SchemaT:
    """Call the configured model group with `prompt` and validate the
    response against `schema`.

    `agent` and `model_group` attribute the resulting model_calls row
    (cost dashboard) to the right caller/group — every call site should
    pass its own agent name. `cacheable=True` opts into the Redis
    response cache (see app/ai/cache.py's docstring for which calls that
    is and isn't safe for); it defaults to False so existing call sites
    behave exactly as before unless they explicitly opt in.

    Retries exactly once if the model's output cannot be parsed/validated.
    Raises ModelOutputValidationError if the second attempt also fails.
    """
    if not settings.GEMINI_API_KEY:
        raise MissingAPIKeyError("GEMINI_API_KEY is not configured; cannot call the model.")

    key = cache.cache_key(model_group, prompt) if cacheable else None
    if key is not None:
        cached_text = await cache.get_cached(key)
        if cached_text is not None:
            try:
                result = _parse_and_validate(cached_text, schema)
            except (json.JSONDecodeError, ValidationError):
                pass  # stale/corrupt cache entry — fall through to a real call
            else:
                await _log_model_call(
                    agent=agent,
                    model_group=model_group,
                    model="cache",
                    tokens_in=0,
                    tokens_out=0,
                    cost=0.0,
                    cache_hit=True,
                )
                return result

    try:
        route_result = await router.route_completion(prompt, model_group=model_group)
    except router.AllModelsFailedError as exc:
        raise ModelUnavailableError(str(exc)) from exc
    try:
        result = _parse_and_validate(route_result.text, schema)
    except (json.JSONDecodeError, ValidationError):
        try:
            route_result = await router.route_completion(
                prompt + _RETRY_INSTRUCTION, model_group=model_group
            )
        except router.AllModelsFailedError as exc:
            raise ModelUnavailableError(str(exc)) from exc
        try:
            result = _parse_and_validate(route_result.text, schema)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ModelOutputValidationError(
                "Model output failed schema validation after one retry."
            ) from exc

    await _log_model_call(
        agent=agent,
        model_group=model_group,
        model=route_result.model,
        tokens_in=route_result.tokens_in,
        tokens_out=route_result.tokens_out,
        cost=route_result.cost,
        cache_hit=False,
    )
    if key is not None:
        await cache.set_cached(key, route_result.text)

    return result
