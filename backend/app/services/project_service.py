from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository


class ProjectService:
    """Ownership and business rules for projects. Raises framework-independent
    domain exceptions only — never FastAPI's HTTPException."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)

    async def create_project(
        self, *, owner_id: uuid.UUID, name: str, description: str | None
    ) -> Project:
        project = await self._projects.create(name=name, description=description, owner_id=owner_id)
        await self._session.commit()
        return project

    async def list_projects(self, *, owner_id: uuid.UUID) -> list[Project]:
        return await self._projects.list_by_owner(owner_id)

    async def _get_owned_project(self, *, project_id: uuid.UUID, owner_id: uuid.UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise NotFoundError(f"Project not found: {project_id}")
        if project.owner_id != owner_id:
            raise PermissionDeniedError("You do not have access to this project")
        return project

    async def get_project(self, *, project_id: uuid.UUID, owner_id: uuid.UUID) -> Project:
        return await self._get_owned_project(project_id=project_id, owner_id=owner_id)

    async def update_project(
        self,
        *,
        project_id: uuid.UUID,
        owner_id: uuid.UUID,
        name: str | None,
        description: str | None,
        fields_set: set[str],
    ) -> Project:
        project = await self._get_owned_project(project_id=project_id, owner_id=owner_id)

        # fields_set comes from Pydantic's model_fields_set, so a field the
        # client omitted is left untouched, but one explicitly set to null
        # (e.g. clearing description) is still applied.
        updates: dict[str, object] = {}
        if "name" in fields_set and name is not None:
            updates["name"] = name
        if "description" in fields_set:
            updates["description"] = description

        if updates:
            project = await self._projects.update(project, **updates)
            await self._session.commit()

        return project

    async def delete_project(self, *, project_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        project = await self._get_owned_project(project_id=project_id, owner_id=owner_id)
        await self._projects.delete(project)
        await self._session.commit()
