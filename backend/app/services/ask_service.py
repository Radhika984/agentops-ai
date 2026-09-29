from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import call_model, owner_call_context
from app.ai.schemas import AnswerResponse
from app.models.interaction import Interaction
from app.repositories.interaction_repository import InteractionRepository
from app.services.project_service import ProjectService

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "ai" / "prompts" / "answer_question.txt"


class AskService:
    """Orchestrates the authenticated /ask flow.

    Verifies project ownership by delegating to ProjectService (so ownership
    rules live in exactly one place), renders the existing answer_question
    prompt template, calls the existing call_model() (Phase 2.3 — including
    its exactly-one-retry semantics, unchanged here), and persists the
    resulting interaction via InteractionRepository. Raises
    framework-independent domain exceptions only — never FastAPI's
    HTTPException — matching AuthService/ProjectService.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._interactions = InteractionRepository(session)

    async def ask(
        self, *, project_id: uuid.UUID, owner_id: uuid.UUID, question: str
    ) -> tuple[Interaction, AnswerResponse]:
        # Raises NotFoundError / PermissionDeniedError if the project does not
        # exist or is not owned by owner_id — checked before any model call.
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)

        prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(question=question)
        with owner_call_context(owner_id):
            answer = await call_model(prompt, AnswerResponse, agent="ask")

        interaction = await self._interactions.create(
            project_id=project_id, prompt=question, response=answer.answer
        )
        await self._session.commit()

        return interaction, answer

    async def get_history(
        self, *, project_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[Interaction]:
        # Same ownership check as ask() — a project's history is only
        # visible to its owner.
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)

        return await self._interactions.list_by_project(project_id)
