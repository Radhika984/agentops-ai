"""Phase 6 memory tests.

app/memory/retrieval.py is tested for real against the test database (it
needs actual pgvector cosine-distance query behavior, not a mock of it) —
using a small fixture set of hand-built 768-dim vectors with known
relationships (near-identical vs. orthogonal), not real Gemini embeddings,
matching the blueprint's "unit test for embedding+retrieval round trip
against a small fixture set."

app/memory/manager.py's recall()/remember() mock embed_text() (no real
network call in this automated suite — same precedent as Phase 2's real
Gemini call, which is verified manually rather than committed as a
network-dependent test) but exercise the real DB round trip underneath.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import manager as memory_manager
from app.memory.retrieval import find_similar, store_embedding
from app.models.embedding import EMBEDDING_DIMENSIONS

pytestmark = pytest.mark.anyio


def _vector(*nonzero: tuple[int, float]) -> list[float]:
    v = [0.0] * EMBEDDING_DIMENSIONS
    for index, value in nonzero:
        v[index] = value
    return v


VEC_BIRTHDAY = _vector((0, 1.0))
VEC_BIRTHDAY_SIMILAR = _vector((0, 0.9), (1, 0.1))  # small angle from VEC_BIRTHDAY
VEC_UNRELATED = _vector((2, 1.0))  # orthogonal to both — cosine distance 1.0


# ---- retrieval.py: real pgvector queries against a small fixture set ----


async def test_find_similar_retrieves_the_closer_vector_first(db_session: AsyncSession) -> None:
    await store_embedding(
        db_session, content="closer", vector=VEC_BIRTHDAY_SIMILAR, source_type="run"
    )
    await store_embedding(db_session, content="farther", vector=VEC_UNRELATED, source_type="run")
    await db_session.commit()

    results = await find_similar(db_session, VEC_BIRTHDAY, top_k=5)

    assert [r.content for r in results] == ["closer"]


async def test_find_similar_excludes_unrelated_vectors_beyond_max_distance(
    db_session: AsyncSession,
) -> None:
    """Two semantically similar past runs are correctly retrieved; an
    unrelated one is not — the blueprint's own Manual Testing Checklist,
    exercised here against real pgvector distance computation rather than
    just asserted."""
    await store_embedding(
        db_session, content="similar", vector=VEC_BIRTHDAY_SIMILAR, source_type="run"
    )
    await store_embedding(
        db_session, content="unrelated", vector=VEC_UNRELATED, source_type="run"
    )
    await db_session.commit()

    results = await find_similar(db_session, VEC_BIRTHDAY, top_k=5, max_distance=0.6)

    contents = [r.content for r in results]
    assert "similar" in contents
    assert "unrelated" not in contents


async def test_find_similar_respects_top_k(db_session: AsyncSession) -> None:
    for i in range(5):
        await store_embedding(
            db_session, content=f"item {i}", vector=VEC_BIRTHDAY, source_type="run"
        )
    await db_session.commit()

    results = await find_similar(db_session, VEC_BIRTHDAY, top_k=2)

    assert len(results) == 2


async def test_find_similar_filters_by_source_type(db_session: AsyncSession) -> None:
    await store_embedding(db_session, content="a run", vector=VEC_BIRTHDAY, source_type="run")
    await store_embedding(
        db_session, content="not a run", vector=VEC_BIRTHDAY, source_type="something_else"
    )
    await db_session.commit()

    results = await find_similar(db_session, VEC_BIRTHDAY, source_type="run", top_k=5)

    assert [r.content for r in results] == ["a run"]


async def test_store_embedding_round_trip_preserves_source_id(db_session: AsyncSession) -> None:
    source_id = uuid.uuid4()

    stored = await store_embedding(
        db_session, content="x", vector=VEC_BIRTHDAY, source_type="run", source_id=source_id
    )
    await db_session.commit()

    results = await find_similar(db_session, VEC_BIRTHDAY, top_k=1)

    assert results[0].id == stored.id
    assert results[0].source_id == source_id


# ---- manager.py: agent-agnostic API (embed_text mocked, DB real) ----


async def test_remember_and_recall_round_trip(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async def fake_embed_text(text: str) -> list[float]:
        return VEC_BIRTHDAY if "birthday" in text else VEC_UNRELATED

    # manager.py opens its own session (see its docstring) — pointed at the
    # test database, matching how test_runs.py redirects run_service.py's.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tests.conftest import TEST_DATABASE_URL

    engine = create_async_engine(TEST_DATABASE_URL)
    test_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(memory_manager, "embed_text", fake_embed_text)
    monkeypatch.setattr(memory_manager, "AsyncSessionLocal", test_session_factory)

    await memory_manager.remember(content="Plan a birthday party", source_type="run")

    results = await memory_manager.recall("birthday party goal", source_type="run")

    assert results == ["Plan a birthday party"]

    await engine.dispose()


async def test_recall_returns_empty_list_when_embedding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.client import MissingAPIKeyError

    async def failing_embed_text(text: str) -> list[float]:
        raise MissingAPIKeyError("no key configured")

    monkeypatch.setattr(memory_manager, "embed_text", failing_embed_text)

    results = await memory_manager.recall("anything")

    assert results == []


async def test_remember_does_not_raise_when_embedding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai.client import MissingAPIKeyError

    async def failing_embed_text(text: str) -> list[float]:
        raise MissingAPIKeyError("no key configured")

    monkeypatch.setattr(memory_manager, "embed_text", failing_embed_text)

    await memory_manager.remember(content="x", source_type="run")  # does not raise
