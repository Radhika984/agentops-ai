"""Phase 2.2 structured output tests.

These verify the AnswerResponse schema and the answer_question prompt
template in isolation. No OpenAI call, no OPENAI_API_KEY, no database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.schemas import AnswerResponse

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "ai" / "prompts" / "answer_question.txt"
)


def test_valid_response_is_accepted() -> None:
    response = AnswerResponse(answer="Paris is the capital of France.", confidence=0.95)

    assert response.answer == "Paris is the capital of France."
    assert response.confidence == 0.95


def test_answer_must_be_a_string() -> None:
    with pytest.raises(ValidationError):
        AnswerResponse(answer=12345, confidence=0.5)  # type: ignore[arg-type]


def test_confidence_zero_is_accepted() -> None:
    response = AnswerResponse(answer="test", confidence=0.0)

    assert response.confidence == 0.0


def test_confidence_one_is_accepted() -> None:
    response = AnswerResponse(answer="test", confidence=1.0)

    assert response.confidence == 1.0


def test_confidence_below_zero_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerResponse(answer="test", confidence=-0.01)


def test_confidence_above_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerResponse(answer="test", confidence=1.01)


def test_missing_answer_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerResponse(confidence=0.5)  # type: ignore[call-arg]


def test_missing_confidence_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnswerResponse(answer="test")  # type: ignore[call-arg]


def test_prompt_template_exists() -> None:
    assert PROMPT_PATH.is_file()


def test_prompt_template_is_not_empty() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")

    assert content.strip() != ""


def test_prompt_template_contains_question_placeholder() -> None:
    content = PROMPT_PATH.read_text(encoding="utf-8")

    assert "{question}" in content
