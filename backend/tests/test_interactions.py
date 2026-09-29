"""Phase 2.4 interaction persistence tests.

These tests exercise the `Interaction` ORM model directly against the
project's real PostgreSQL test database (via the `db_session` fixture in
conftest.py). No HTTP client, no OpenAI calls, no OPENAI_API_KEY required.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interaction import Interaction
from app.models.project import Project
from app.models.user import User

pytestmark = pytest.mark.anyio


async def _create_user(session: AsyncSession, email: str = "owner@example.com") -> User:
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _create_project(
    session: AsyncSession, owner_id: uuid.UUID, name: str = "Project A"
) -> Project:
    project = Project(name=name, owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project


async def test_interaction_can_be_persisted_for_existing_project(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="What is the capital of France?",
        response="Paris is the capital of France.",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(interaction)

    assert interaction.id is not None


async def test_interaction_project_id_points_to_project(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="Question",
        response="Answer",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(interaction)

    assert interaction.project_id == project.id


async def test_interaction_prompt_is_persisted(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="What is the airspeed velocity of an unladen swallow?",
        response="African or European?",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(interaction)

    assert interaction.prompt == "What is the airspeed velocity of an unladen swallow?"


async def test_interaction_response_is_persisted(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="Question",
        response="African or European?",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(interaction)

    assert interaction.response == "African or European?"


async def test_interaction_created_at_is_populated(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="Question",
        response="Answer",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(interaction)

    assert interaction.created_at is not None
    assert isinstance(interaction.created_at, datetime)


async def test_interaction_can_be_retrieved_from_database(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="Question",
        response="Answer",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(interaction)

    result = await db_session.execute(select(Interaction).where(Interaction.id == interaction.id))
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.id == interaction.id
    assert fetched.project_id == project.id
    assert fetched.prompt == "Question"
    assert fetched.response == "Answer"


async def test_interaction_requires_existing_project(db_session: AsyncSession) -> None:
    interaction = Interaction(
        project_id=uuid.uuid4(),
        prompt="Question",
        response="Answer",
    )
    db_session.add(interaction)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


async def test_project_exposes_its_interactions(db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    project = await _create_project(db_session, owner_id=user.id)

    interaction = Interaction(
        project_id=project.id,
        prompt="Question",
        response="Answer",
    )
    db_session.add(interaction)
    await db_session.flush()
    await db_session.refresh(project, attribute_names=["interactions"])

    assert len(project.interactions) == 1
    assert project.interactions[0].id == interaction.id
