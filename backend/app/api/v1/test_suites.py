"""Phase 12 — Test Suite / Test Case API.

Routes span three different path prefixes (agent-scoped suite creation,
suite-scoped case creation, and bare case-ID mutation) per this phase's
exact required route list, so this router carries no single `prefix=`
— each route declares its own full path instead.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import (
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.db.session import get_db
from app.models.test_case import TestCase
from app.models.test_suite import TestSuite
from app.models.user import User
from app.schemas.test_suite import (
    TestCaseCreate,
    TestCasePatch,
    TestCaseRead,
    TestSuiteCreate,
    TestSuiteRead,
)
from app.services.test_suite_service import TestSuiteService

router = APIRouter(tags=["test-suites"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, InvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


# ---- Test Suites (agent-scoped) -------------------------------------


@router.post(
    "/agents/{agent_id}/test-suites",
    response_model=TestSuiteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_suite(
    agent_id: uuid.UUID,
    payload: TestSuiteCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TestSuite:
    service = TestSuiteService(session)
    try:
        return await service.create_suite(
            agent_id=agent_id, owner_id=current_user.id, name=payload.name
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/agents/{agent_id}/test-suites", response_model=list[TestSuiteRead])
async def list_test_suites(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[TestSuite]:
    service = TestSuiteService(session)
    try:
        return await service.list_suites(agent_id=agent_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/test-suites", response_model=list[TestSuiteRead])
async def list_all_test_suites(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[TestSuite]:
    """The account-wide "Test Suites" nav page's data source — every
    TestSuite across every Agent/Project this user owns. Distinct from
    list_test_suites() above (agent-scoped); this is the real backend
    capability that page needed and did not have before."""
    return await TestSuiteService(session).list_all_for_owner(owner_id=current_user.id)


# ---- Test Cases (suite-scoped create/list) ----------------------------


@router.post(
    "/test-suites/{suite_id}/test-cases",
    response_model=TestCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_case(
    suite_id: uuid.UUID,
    payload: TestCaseCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TestCase:
    service = TestSuiteService(session)
    try:
        return await service.create_case(
            suite_id=suite_id, owner_id=current_user.id, fields=payload.model_dump()
        )
    except (NotFoundError, PermissionDeniedError, ValidationError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/test-suites/{suite_id}/test-cases", response_model=list[TestCaseRead])
async def list_test_cases(
    suite_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[TestCase]:
    service = TestSuiteService(session)
    try:
        return await service.list_cases(suite_id=suite_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


# ---- Test Cases (bare-ID patch/delete) --------------------------------


@router.patch("/test-cases/{case_id}", response_model=TestCaseRead)
async def patch_test_case(
    case_id: uuid.UUID,
    payload: TestCasePatch,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TestCase:
    service = TestSuiteService(session)
    try:
        return await service.patch_case(
            case_id=case_id,
            owner_id=current_user.id,
            payload=payload.model_dump(),
            fields_set=payload.model_fields_set,
        )
    except (NotFoundError, PermissionDeniedError, ValidationError) as exc:
        raise _map_domain_error(exc) from exc


@router.delete("/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_test_case(
    case_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    service = TestSuiteService(session)
    try:
        await service.delete_case(case_id=case_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


# ---- Phase 20: regression candidates -----------------------------------


@router.post("/test-cases/{case_id}/accept", response_model=TestCaseRead)
async def accept_candidate_test_case(
    case_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TestCase:
    """The one explicit human-control step a proposed regression
    candidate (app/services/production_execution_service.py) requires
    before it is included in any Suite Runner execution."""
    service = TestSuiteService(session)
    try:
        return await service.accept_candidate(case_id=case_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError, InvalidStateError) as exc:
        raise _map_domain_error(exc) from exc
