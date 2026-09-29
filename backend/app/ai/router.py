"""Model routing: centralizes model selection and fallback across every
agent's LLM call, replacing the single hardcoded `settings.GEMINI_MODEL`
each call site used directly through Phase 7.

Routing config as data, per the blueprint ("routing config as data ...
not code, so it can change without a deploy"): MODEL_GROUPS below is the
one place that knows which models exist and in what priority order —
nothing else in the app hardcodes a model id. Both groups currently share
the same two Gemini Free Tier models (this project only has one real
provider/account to route across), but the "reasoning" vs "judgment"
split is still real: it's what future per-group config (temperature,
caching eligibility, a genuinely different provider/model per group)
attaches to, per this phase's own "reasoning" for introducing the
abstraction now rather than earlier ("earlier phases had too few call
sites to justify it").

Uses litellm's functional `acompletion`/`aembedding`, not its `Router`
class: the fallback/retry loop below is hand-rolled (try each model in
the group's priority list in order, catching failures) rather than
handed to litellm.Router's internal fallback config. This keeps the one
thing that matters most here — structured JSON output correctness, which
every agent's structured-output parsing depends on — fully inspectable
and testable in this file, rather than depending on litellm.Router's
own (less transparent, harder to unit-test) internal retry/fallback
machinery. The centralization the blueprint is after ("instead of
duplicating that logic per agent") is achieved either way: there is
exactly one fallback loop in the whole app, here.

Cost note: litellm's `response_cost` is computed from its own published
per-token pricing table for the model actually used — it is a notional
/estimated dollar figure for the cost dashboard (Phase 8's whole point:
"Cost dashboard numbers match a manual spot-check against model_calls"),
not a real charge. This project is Free Tier only; Google does not bill
these calls. Verified live against the real Gemini API.

Extraction/embeddings note: this router deliberately does not carry an
"extraction" runtime path. app/memory/embeddings.py (Phase 6) requests a
reduced 768-dimension output via google-genai's `output_dimensionality`
config — pgvector's HNSW index (see the embeddings migration) is built
against exactly that width, so a routing layer for embeddings would need
to guarantee the same reduced dimensionality through litellm before it
could safely replace that code path. That wasn't verified (a live check
showed litellm.aembedding() returning the model's native 3072-dim
output with no dimension-reduction parameter attempted), and getting it
wrong would silently break Phase 6/7's memory retrieval — a correctness
regression, not a cost-tracking gap. embeddings.py is intentionally left
on its proven direct SDK path; the "extraction" name only appears here
as a documented gap, not a model group other code references.
"""

from __future__ import annotations

import litellm

from app.core.config import settings

MODEL_GROUPS: dict[str, list[str]] = {
    "reasoning": [settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL],
    "judgment": [settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL],
}


class AllModelsFailedError(Exception):
    """Raised when every model in a group's priority list failed."""


class RouteResult:
    __slots__ = ("text", "model", "tokens_in", "tokens_out", "cost")

    def __init__(
        self, *, text: str, model: str, tokens_in: int, tokens_out: int, cost: float
    ) -> None:
        self.text = text
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost = cost


async def route_completion(prompt: str, *, model_group: str) -> RouteResult:
    """Tries each model in `model_group`'s priority list in order,
    returning the first one that responds successfully. Raises
    AllModelsFailedError (chaining the last underlying exception) if
    every model in the list fails — e.g. GEMINI_API_KEY missing/invalid,
    or every model genuinely unavailable.
    """
    models = MODEL_GROUPS[model_group]
    last_exc: Exception | None = None

    for model_id in models:
        try:
            response = await litellm.acompletion(
                model=f"gemini/{model_id}",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                api_key=settings.GEMINI_API_KEY,
            )
        except Exception as exc:  # noqa: BLE001 — any model/provider failure triggers fallback
            last_exc = exc
            continue

        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        cost = float((response._hidden_params or {}).get("response_cost") or 0.0)

        return RouteResult(
            text=text,
            model=model_id,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            cost=cost,
        )

    raise AllModelsFailedError(
        f"All models in group '{model_group}' failed: {models}"
    ) from last_exc
