from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    """Database access for projects. No ownership rules, no HTTP concerns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, description: str | None, owner_id: uuid.UUID) -> Project:
        project = Project(name=name, description=description, owner_id=owner_id)
        self._session.add(project)
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def list_by_owner(self, owner_id: uuid.UUID) -> list[Project]:
        result = await self._session.execute(
            select(Project).where(Project.owner_id == owner_id).order_by(Project.created_at)
        )
        return list(result.scalars().all())

    async def count_by_owner(self, owner_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count(Project.id)).where(Project.owner_id == owner_id)
        )
        return int(result.scalar_one())

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        result = await self._session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def update(self, project: Project, **fields: Any) -> Project:
        for key, value in fields.items():
            setattr(project, key, value)
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def delete(self, project: Project) -> None:
        await self._session.delete(project)
        await self._session.flush()
