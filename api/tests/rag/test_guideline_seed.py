"""Story 3.2 — ``run_guideline_seed`` 단위 테스트 (AC #3).

``embed_texts`` monkeypatch + DB session 사용. 케이스:
  1. 정상 시드 → ≥ 40 chunks + embedding NOT NULL
  2. dev graceful — OPENAI_API_KEY 미설정 + ENVIRONMENT=dev → chunks 시드 + embedding NULL
  3. prod fail-fast — 같은 입력 + ENVIRONMENT=prod → GuidelineSeedSourceUnavailableError
  4. frontmatter 검증 실패 → GuidelineSeedValidationError
  5. 멱등 — 동일 시드 두 번째 → DB count 동일 + UPDATE 분기
  6. chunks count < 40 → GuidelineSeedAdapterError (test에서 1 파일만 노출)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters import openai_adapter as openai_module
from app.core.config import settings
from app.core.exceptions import (
    GuidelineSeedAdapterError,
    GuidelineSeedSourceUnavailableError,
    GuidelineSeedValidationError,
    MealOCRUnavailableError,
)
from app.main import app
from app.rag.guidelines import seed as guideline_seed


async def _truncate_knowledge_chunks(session_maker: async_sessionmaker[AsyncSession]) -> None:
    async with session_maker() as session:
        await session.execute(text("TRUNCATE knowledge_chunks RESTART IDENTITY"))
        await session.commit()


@pytest.fixture(autouse=True)
def _disable_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUN_GUIDELINE_SEED_STRICT", raising=False)


async def test_run_guideline_seed_normal_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정상 시드 → ≥ 40 chunks + embedding NOT NULL + 6 파일 처리."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_knowledge_chunks(session_maker)

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    async with session_maker() as session:
        result = await guideline_seed.run_guideline_seed(session)

    assert result.total >= guideline_seed.GUIDELINE_SEED_MIN_CHUNKS
    assert result.inserted >= guideline_seed.GUIDELINE_SEED_MIN_CHUNKS
    assert result.updated == 0
    assert result.files_processed == 6  # KDRIs AMDR/Protein + KSSO + KDA + MFDS + KDCA
    assert result.embeddings_skipped is False

    async with session_maker() as session:
        not_null = await session.execute(
            text("SELECT count(*) AS n FROM knowledge_chunks WHERE embedding IS NOT NULL")
        )
        row = not_null.first()
        assert row is not None
        assert row.n >= guideline_seed.GUIDELINE_SEED_MIN_CHUNKS


async def test_run_guideline_seed_dev_graceful_when_no_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPENAI_API_KEY 미설정 + ENVIRONMENT=dev → chunks 시드 + embedding NULL + skipped=True."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_knowledge_chunks(session_maker)

    async def failing_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        raise MealOCRUnavailableError("OPENAI_API_KEY not configured")

    monkeypatch.setattr(openai_module, "embed_texts", failing_embed)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)

    async with session_maker() as session:
        result = await guideline_seed.run_guideline_seed(session)

    assert result.total >= guideline_seed.GUIDELINE_SEED_MIN_CHUNKS
    assert result.embeddings_skipped is True

    async with session_maker() as session:
        null_count = await session.execute(
            text("SELECT count(*) AS n FROM knowledge_chunks WHERE embedding IS NULL")
        )
        row = null_count.first()
        assert row is not None
        assert row.n >= guideline_seed.GUIDELINE_SEED_MIN_CHUNKS


async def test_run_guideline_seed_prod_fail_fast_when_no_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OPENAI_API_KEY 미설정 + ENVIRONMENT=prod → GuidelineSeedSourceUnavailableError."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_knowledge_chunks(session_maker)

    async def failing_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        raise MealOCRUnavailableError("OPENAI_API_KEY not configured")

    monkeypatch.setattr(openai_module, "embed_texts", failing_embed)
    monkeypatch.setattr(settings, "environment", "prod", raising=False)

    async with session_maker() as session:
        with pytest.raises(GuidelineSeedSourceUnavailableError):
            await guideline_seed.run_guideline_seed(session)
        await session.rollback()


async def test_run_guideline_seed_invalid_frontmatter_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """frontmatter source가 enum 위반(``INVALID``) → GuidelineSeedValidationError."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_knowledge_chunks(session_maker)

    bad_dir = tmp_path / "guidelines"
    bad_dir.mkdir()
    (bad_dir / "bad.md").write_text(
        "---\n"
        "source: INVALID\n"
        "source_id: BAD-DOC-1\n"
        "authority_grade: A\n"
        "topic: macronutrient\n"
        "applicable_health_goals: []\n"
        "doc_title: Bad doc title test\n"
        "---\n\n"
        "## 본문\n\n탄수화물 권장량 본문\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(guideline_seed, "_GUIDELINE_DATA_DIR", bad_dir)

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    async with session_maker() as session:
        with pytest.raises(GuidelineSeedValidationError):
            await guideline_seed.run_guideline_seed(session)
        await session.rollback()


async def test_run_guideline_seed_idempotent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """동일 시드 두 번째 호출 → ON CONFLICT UPDATE → DB row 동일 count."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_knowledge_chunks(session_maker)

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    async with session_maker() as session:
        first = await guideline_seed.run_guideline_seed(session)

    async with session_maker() as session:
        second = await guideline_seed.run_guideline_seed(session)

    assert first.total == second.total
    assert second.inserted == 0
    assert second.updated == first.inserted


async def test_run_guideline_seed_count_below_threshold_raises(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """chunks count < GUIDELINE_SEED_MIN_CHUNKS → GuidelineSeedAdapterError."""
    _ = client
    session_maker: async_sessionmaker[AsyncSession] = app.state.session_maker
    await _truncate_knowledge_chunks(session_maker)

    # 단일 짧은 파일만 노출 → chunks 1-2건 → < 40.
    tiny_dir = tmp_path / "guidelines"
    tiny_dir.mkdir()
    (tiny_dir / "tiny.md").write_text(
        "---\n"
        "source: MOHW\n"
        "source_id: TINY-DOC-1\n"
        "authority_grade: A\n"
        "topic: general\n"
        "applicable_health_goals: []\n"
        "doc_title: Tiny test doc\n"
        "---\n\n"
        "## 짧은 단락\n\n짧은 본문 테스트.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(guideline_seed, "_GUIDELINE_DATA_DIR", tiny_dir)

    async def fake_embed(texts: list[str], *, batch_size: int = 300) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    monkeypatch.setattr(openai_module, "embed_texts", fake_embed)

    async with session_maker() as session:
        with pytest.raises(GuidelineSeedAdapterError) as exc_info:
            await guideline_seed.run_guideline_seed(session)
        await session.rollback()
    assert "insufficient" in str(exc_info.value).lower()
