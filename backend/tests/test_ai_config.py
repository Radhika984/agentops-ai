"""Phase 2.1 configuration tests.

These verify the configuration boundary added for the AI layer
(GEMINI_API_KEY / GEMINI_MODEL) without making any network call to
Gemini and without disturbing existing Phase 1 Settings behavior.
"""

from __future__ import annotations

from app.core.config import Settings


def test_gemini_api_key_defaults_to_none_when_unset() -> None:
    """The app must be able to start without GEMINI_API_KEY configured.

    Unlike JWT_SECRET, GEMINI_API_KEY has no bare `str` requirement -
    Settings() must not raise just because the key is absent.
    """
    test_settings = Settings(JWT_SECRET="test-secret", GEMINI_API_KEY=None)  # type: ignore[call-arg]

    assert test_settings.GEMINI_API_KEY is None


def test_gemini_api_key_can_be_set() -> None:
    test_settings = Settings(  # type: ignore[call-arg]
        JWT_SECRET="test-secret",
        GEMINI_API_KEY="test-key-value",
    )

    assert test_settings.GEMINI_API_KEY == "test-key-value"


def test_gemini_model_has_sensible_default() -> None:
    test_settings = Settings(JWT_SECRET="test-secret")  # type: ignore[call-arg]

    assert test_settings.GEMINI_MODEL
    assert isinstance(test_settings.GEMINI_MODEL, str)


def test_gemini_model_can_be_overridden() -> None:
    test_settings = Settings(  # type: ignore[call-arg]
        JWT_SECRET="test-secret",
        GEMINI_MODEL="gemini-3.5-flash",
    )

    assert test_settings.GEMINI_MODEL == "gemini-3.5-flash"


def test_existing_jwt_settings_are_unaffected() -> None:
    """Guard against Part 2.1 accidentally changing Phase 1 auth config."""
    test_settings = Settings(JWT_SECRET="test-secret")  # type: ignore[call-arg]

    assert test_settings.JWT_ALGORITHM == "HS256"
    assert test_settings.JWT_EXPIRE_MINUTES == 60
