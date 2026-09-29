"""Phase 15 — Grounding/hallucination repointed at real TestCase.reference_context.

Reuses the exact same entailment mechanism app/agents/hallucination.py's
hallucination_node already uses for the legacy Run path — the same
prompt template (app/agents/prompts/hallucination_check.txt), the same
HallucinationCheck schema, the same call_model(agent="hallucination",
model_group="judgment", cacheable=True) shape. hallucination_node itself
is not called or modified; this module is a new, narrower caller of the
same underlying mechanism, per the locked audit's "reuse the mechanism,
change the source context" instruction. Nothing about the entailment
algorithm is rewritten.

  OLD (hallucination_node): source context = goal + Phase 5 web_search
  result + Phase 6 retrieved memory. Checked AgentOps's own generated
  plan text.
  NEW (this module): source context = TestCase.reference_context,
  supplied explicitly by the test author. Checks the real System Under
  Test's actual output.

Hard rule: no reference_context means no supplied grounding source —
never fabricated from a web search, AgentOps's memory, or the original
goal. Grounding is SKIPPED, not PASS, not FAIL.

Per the locked audit: like Safety, this check is recorded for
visibility only in this phase — it does not influence
TestCaseResult.verdict (unchanged from Phase 14, still Phase-13-only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agents.schemas import HallucinationCheck
from app.ai.client import AIClientError, call_model
from app.evaluation.models import Check, CheckStatus, Determinism

# The exact same prompt file hallucination_node reads — not copied, not
# rewritten; a second reader of the one template file.
_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "agents" / "prompts" / "hallucination_check.txt"
)

CHECK_TYPE = "grounding"


async def evaluate_grounding(reference_context: str | None, actual_output: Any) -> Check:
    if not reference_context:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.SKIPPED,
            determinism=Determinism.DETERMINISTIC,
            detail=(
                "no reference_context supplied on the TestCase — grounding is not "
                "evaluable. Never fabricated from a web search, AgentOps's own memory, "
                "or the original goal."
            ),
        )

    if actual_output is None:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.SKIPPED,
            determinism=Determinism.DETERMINISTIC,
            detail="actual output is missing — grounding is not evaluable",
        )

    output_text = (
        actual_output
        if isinstance(actual_output, str)
        else json.dumps(actual_output, sort_keys=True)
    )
    # The same "- <item>" bullet shape hallucination_node formats its
    # plan tasks as (agents/hallucination.py) — the template's own
    # wording ("Proposed plan") is generic enough to apply to a single
    # real output item without needing its own copy of the prompt.
    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        source_context=reference_context,
        plan=f"- {output_text}",
    )

    try:
        result = await call_model(
            prompt,
            HallucinationCheck,
            agent="hallucination",
            model_group="judgment",
            cacheable=True,
        )
    except AIClientError as exc:
        # Distinct from SKIPPED: the check *was* applicable (a real
        # reference_context and a real output both existed) but the
        # entailment model was unreachable — genuinely undecided, not
        # "not applicable" and never silently PASS.
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.INCONCLUSIVE,
            determinism=Determinism.DETERMINISTIC,
            detail=(
                "grounding could not be evaluated — the entailment model was "
                f"unavailable: {exc}"
            ),
        )

    if result.unsupported_claims:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail=(
                f"output makes {len(result.unsupported_claims)} claim(s) not "
                "supported by reference_context"
            ),
            metadata={"unsupported_claims": result.unsupported_claims},
        )

    return Check(
        check_type=CHECK_TYPE,
        status=CheckStatus.PASS,
        determinism=Determinism.DETERMINISTIC,
        detail="output is fully supported by reference_context",
    )
