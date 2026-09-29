"""Framework-independent domain exceptions.

Services raise these instead of FastAPI's HTTPException, per the
Clean Architecture rule that only the API layer knows about HTTP.
The API layer (api/v1/*) catches these and maps them to responses.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all domain-level errors."""


class EmailAlreadyExistsError(DomainError):
    """Raised when registering an email that is already in use."""


class InvalidCredentialsError(DomainError):
    """Raised when login credentials are invalid (unknown email or wrong password)."""


class InactiveUserError(DomainError):
    """Raised when an inactive user attempts to authenticate."""


class NotFoundError(DomainError):
    """Raised when a requested resource does not exist."""


class PermissionDeniedError(DomainError):
    """Raised when a user attempts to access a resource they do not own."""


class InvalidStateError(DomainError):
    """Phase 9: raised when an action is attempted against a resource
    that isn't in a state that allows it — e.g. requesting a release
    review for a run that hasn't finished yet, or deciding an approval
    that's already been decided."""


class ValidationError(DomainError):
    """Phase 11: raised when a request is well-formed JSON but its
    domain-level content is invalid in a way Pydantic's own field
    validation can't express — e.g. an AgentVersion's adapter_config not
    matching its declared adapter_type's actual config shape."""


class ConflictError(DomainError):
    """Phase 11: raised when a request would violate a uniqueness rule
    the domain enforces — e.g. two AgentVersions for the same Agent with
    the same label."""
