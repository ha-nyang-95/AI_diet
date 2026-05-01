"""Story 3.2 — 가이드라인 RAG 시드 비즈니스 로직 (AC #3).

``data/guidelines/*.md`` 파일 단위 시드:
  1. frontmatter YAML 파싱 + ``_FrontmatterSchema`` Pydantic 검증.
  2. body chunking — ``chunk_markdown`` (heading-aware + max_chars=1000 + overlap=100).
  3. chunks → ``embed_texts`` (Story 3.1 D7 SDK singleton 공유).
  4. 멱등 INSERT — ``ON CONFLICT (source, source_id, chunk_index) DO UPDATE`` (D5).

D9 — ``OPENAI_API_KEY`` 미설정 분기:
  - dev/ci/test (default) — ``embeddings_skipped=True`` + chunks NULL embedding 시드.
  - prod/staging 또는 ``RUN_GUIDELINE_SEED_STRICT=1`` — fail-fast
    (``GuidelineSeedSourceUnavailableError``).

NFR-S5 — chunk_text raw 노출 X. ``source`` + ``source_id`` + ``chunks_count`` +
``latency_ms``만 1줄 (Story 3.1 정합).
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import structlog
import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import openai_adapter
from app.core.config import settings
from app.core.exceptions import (
    FoodSeedAdapterError,
    GuidelineSeedAdapterError,
    GuidelineSeedSourceUnavailableError,
    GuidelineSeedValidationError,
    MealOCRUnavailableError,
)
from app.rag.chunking import Chunk, chunk_markdown

logger = structlog.get_logger(__name__)

# `data/guidelines/` 디렉토리 — `app/rag/guidelines/seed.py`에서 4단계 상위가 api/ root.
# 본 모듈 경로: api/app/rag/guidelines/seed.py (parents[0]=guidelines, [1]=rag, [2]=app, [3]=api).
_GUIDELINE_DATA_DIR: Final[Path] = Path(__file__).resolve().parents[3] / "data" / "guidelines"

GUIDELINE_SEED_GRACEFUL_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"dev", "ci", "test"})
RUN_GUIDELINE_SEED_STRICT_ENV: Final[str] = "RUN_GUIDELINE_SEED_STRICT"

GUIDELINE_SEED_MIN_CHUNKS: Final[int] = 40

_STRICT_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

_INSERT_GUIDELINE_SQL: Final[str] = """
INSERT INTO knowledge_chunks (
    source, source_id, chunk_index, chunk_text, embedding,
    authority_grade, topic, applicable_health_goals, published_year, doc_title
) VALUES (
    :source, :source_id, :chunk_index, :chunk_text,
    CAST(:embedding AS vector),
    :authority_grade, :topic, :applicable_health_goals,
    :published_year, :doc_title
)
ON CONFLICT (source, source_id, chunk_index) DO UPDATE SET
    chunk_text = EXCLUDED.chunk_text,
    embedding = EXCLUDED.embedding,
    authority_grade = EXCLUDED.authority_grade,
    topic = EXCLUDED.topic,
    applicable_health_goals = EXCLUDED.applicable_health_goals,
    published_year = EXCLUDED.published_year,
    doc_title = EXCLUDED.doc_title,
    updated_at = now()
RETURNING (xmax = 0) AS inserted
"""


class _FrontmatterSchema(BaseModel):
    """``data/guidelines/*.md`` frontmatter 스키마 — application-level 검증.

    DB CHECK 제약 미사용 (Story 3.1 D4 정합) — 잘못된 source/authority_grade/topic enum
    값을 fail-fast로 차단해 Story 3.6 generate_feedback이 *(출처: 미상)* 패턴을 출력하지
    않도록 보장.

    옵션 필드:
      - ``allergens`` — ``mfds-allergens-22.md`` 전용 22 항목 list (verify_allergy_22 입력).
    """

    source: Literal["MFDS", "MOHW", "KSSO", "KDA", "KDCA"]
    source_id: str = Field(min_length=3)
    authority_grade: Literal["A", "B", "C"]
    topic: Literal["macronutrient", "allergen", "disease_specific", "general"]
    applicable_health_goals: list[
        Literal["weight_loss", "muscle_gain", "maintenance", "diabetes_management"]
    ]
    published_year: int | None = Field(ge=1990, le=2100)
    doc_title: str = Field(min_length=5)
    allergens: list[str] | None = None


@dataclass(frozen=True, slots=True)
class GuidelineSeedResult:
    """``run_guideline_seed`` 결과 — 통계 + graceful 신호."""

    inserted: int
    updated: int
    total: int
    files_processed: int
    embeddings_skipped: bool


def _is_strict_mode() -> bool:
    """``RUN_GUIDELINE_SEED_STRICT`` 환경변수 set 여부 — Story 3.1 D9 패턴 정합."""
    return os.environ.get(RUN_GUIDELINE_SEED_STRICT_ENV, "").strip().lower() in _STRICT_TRUTHY


def _is_graceful_environment() -> bool:
    """현 환경이 graceful 분기 대상인지 (D9). strict opt-in 시 graceful 무효."""
    if _is_strict_mode():
        return False
    env = (settings.environment or "").strip().lower()
    return env in GUIDELINE_SEED_GRACEFUL_ENVIRONMENTS


def _format_vector_literal(vector: list[float] | None) -> str | None:
    """pgvector ``vector`` 입력 literal — Story 3.1 ``_format_vector_literal`` 패턴 정합.

    NaN/Inf은 pgvector reject — None으로 강등 (검색 시 ``WHERE embedding IS NOT NULL``
    자동 제외).
    """
    if not vector:
        return None
    if any(not math.isfinite(v) for v in vector):
        logger.warning("guideline_seed.embedding_non_finite", dim=len(vector))
        return None
    return "[" + ",".join(format(v, ".7g") for v in vector) + "]"


def _parse_markdown_with_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """frontmatter YAML + body 분리.

    ``---\\n<yaml>\\n---\\n<body>`` 패턴. frontmatter 미존재 시 ``({}, content)``.

    Raises:
        ``GuidelineSeedValidationError`` — YAML 파싱 실패.
    """
    # UTF-8 BOM(﻿) 선처리 — Windows 편집기 저장 파일 호환.
    if content.startswith("﻿"):
        content = content[1:]

    if not content.startswith("---"):
        return {}, content

    # 첫 번째 ``---`` 라인 이후 ``---`` 종료 라인 위치를 찾아 frontmatter/body 분리.
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, content

    yaml_text = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        loaded = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise GuidelineSeedValidationError(f"YAML frontmatter parse failed: {exc}") from exc
    if not isinstance(loaded, dict):
        raise GuidelineSeedValidationError(
            f"frontmatter must be a YAML mapping, got {type(loaded).__name__}"
        )
    return loaded, body


def _validate_frontmatter(data: dict[str, Any], file_path: Path) -> _FrontmatterSchema:
    try:
        return _FrontmatterSchema.model_validate(data)
    except ValidationError as exc:
        raise GuidelineSeedValidationError(
            f"frontmatter validation failed for {file_path.name}: {exc}"
        ) from exc


async def _embed_chunks(
    chunks: list[Chunk],
) -> tuple[list[list[float] | None], bool]:
    """chunks → embeddings (또는 NULL graceful).

    Returns:
        ``(embeddings, embeddings_skipped)`` — ``embeddings_skipped=True``는 dev graceful.

    Raises:
        ``GuidelineSeedSourceUnavailableError`` — prod/strict 모드에서 OPENAI_API_KEY 미설정.
        ``GuidelineSeedAdapterError`` — embed_texts adapter 영구/transient 실패 (prod/strict 분기).
    """
    if not chunks:
        return [], False

    texts = [c.text for c in chunks]
    try:
        embeddings = await openai_adapter.embed_texts(texts)
    except MealOCRUnavailableError as exc:
        # OPENAI_API_KEY 미설정 신호 — Story 2.3 ``_get_client()`` raise 경로.
        if _is_graceful_environment():
            logger.warning(
                "guideline_seed.embed_skipped_graceful",
                environment=settings.environment,
                reason=str(exc),
            )
            return [None] * len(chunks), True
        raise GuidelineSeedSourceUnavailableError(
            f"OPENAI_API_KEY not configured (environment={settings.environment})"
        ) from exc
    except FoodSeedAdapterError as exc:
        # embed_texts 어댑터 transient/영구 실패 — D9 정합:
        #   prod/staging/strict 모드 → fail-fast (데이터 정합 보호).
        #   dev/ci/test (graceful) → NULL 시드로 진행 + warning (외주 인수 첫 부팅 영업 demo).
        if not _is_graceful_environment():
            raise GuidelineSeedAdapterError(
                f"guideline embedding failed (environment={settings.environment}): {exc}"
            ) from exc
        logger.warning(
            "guideline_seed.embed_failed_graceful",
            chunks_count=len(chunks),
            environment=settings.environment,
            error=str(exc),
        )
        return [None] * len(chunks), True

    if len(embeddings) != len(chunks):
        logger.warning(
            "guideline_seed.embedding_count_mismatch",
            chunks_count=len(chunks),
            embeddings_count=len(embeddings),
        )
        return [None] * len(chunks), True
    # mypy: AsyncOpenAI returns concrete list[float] — embed_texts returns list[list[float]]만.
    return [list(e) for e in embeddings], False


async def _insert_chunks(
    session: AsyncSession,
    *,
    meta: _FrontmatterSchema,
    chunks: list[Chunk],
    embeddings: list[list[float] | None],
) -> tuple[int, int]:
    """단일 파일 chunks 멱등 INSERT — ``(inserted, updated)``."""
    inserted = 0
    updated = 0
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        params: dict[str, Any] = {
            "source": meta.source,
            "source_id": meta.source_id,
            "chunk_index": chunk.chunk_index,
            "chunk_text": chunk.text,
            "embedding": _format_vector_literal(embedding),
            "authority_grade": meta.authority_grade,
            "topic": meta.topic,
            # asyncpg는 Python list[str]을 native Postgres text[] 매핑.
            "applicable_health_goals": list(meta.applicable_health_goals),
            "published_year": meta.published_year,
            "doc_title": meta.doc_title,
        }
        result = await session.execute(text(_INSERT_GUIDELINE_SQL), params)
        row = result.first()
        if row is None:
            continue
        if row.inserted:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


async def run_guideline_seed(session: AsyncSession) -> GuidelineSeedResult:
    """``data/guidelines/*.md`` 파일 단위 시드 — 멱등 + dev graceful 분기.

    Returns:
        ``GuidelineSeedResult`` — 통계 + ``embeddings_skipped`` 신호.

    Raises:
        ``GuidelineSeedSourceUnavailableError`` — 디렉토리/파일 없음 또는 prod/strict
        OPENAI_API_KEY 미설정.
        ``GuidelineSeedValidationError`` — frontmatter 검증 실패.
        ``GuidelineSeedAdapterError`` — chunks count 게이트(< 40) 미달 또는 chunking 실패.
    """
    start = time.monotonic()

    if not _GUIDELINE_DATA_DIR.exists():
        raise GuidelineSeedSourceUnavailableError(
            f"guideline data directory not found: {_GUIDELINE_DATA_DIR}"
        )

    md_files = sorted(_GUIDELINE_DATA_DIR.glob("*.md"))
    # README.md 등은 frontmatter 없거나 시드 대상이 아님 — 명시적으로 스키마 정합 파일만 처리.
    md_files = [p for p in md_files if p.name.lower() != "readme.md"]

    if not md_files:
        raise GuidelineSeedSourceUnavailableError(
            f"no guideline markdown files found in {_GUIDELINE_DATA_DIR}"
        )

    inserted_total = 0
    updated_total = 0
    embeddings_skipped_any = False

    for md_path in md_files:
        raw = md_path.read_text(encoding="utf-8")
        meta_dict, _body = _parse_markdown_with_frontmatter(raw)
        meta = _validate_frontmatter(meta_dict, md_path)
        # ``raw``를 그대로 chunker에 전달 — chunker 내부 ``_strip_frontmatter``가 BOM +
        # frontmatter 제거 후 ``body_shift``로 *원본 파일 기준* char_start를 계산
        # (``Chunk.char_start`` docstring contract). ``body``를 넘기면 body_shift=0이 되어
        # body-relative 좌표가 되므로 인용 위치 추적이 어긋난다(Gemini CR HIGH 정합).
        chunks = chunk_markdown(raw)
        if not chunks:
            logger.warning("guideline_seed.empty_body", file=md_path.name)
            continue

        embeddings, file_skipped = await _embed_chunks(chunks)
        embeddings_skipped_any = embeddings_skipped_any or file_skipped

        file_inserted, file_updated = await _insert_chunks(
            session, meta=meta, chunks=chunks, embeddings=embeddings
        )
        inserted_total += file_inserted
        updated_total += file_updated

        logger.info(
            "guideline_seed.insert",
            source=meta.source,
            source_id=meta.source_id,
            chunks_count=len(chunks),
            inserted=file_inserted,
            updated=file_updated,
        )

    # 게이트는 *현 run에서 처리한 chunks 합* 기준 — prior run 잔존 row가 게이트를 가짜로
    # 통과시키지 않도록(테이블 전체 count는 cross-run pollution 위험).
    run_total = inserted_total + updated_total
    if run_total < GUIDELINE_SEED_MIN_CHUNKS:
        raise GuidelineSeedAdapterError(
            f"knowledge_chunks seed insufficient: run_total={run_total} "
            f"< {GUIDELINE_SEED_MIN_CHUNKS}"
        )

    await session.commit()

    count_result = await session.execute(text("SELECT count(*) AS n FROM knowledge_chunks"))
    count_row = count_result.first()
    total = int(count_row.n) if count_row else 0

    latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "guideline_seed.complete",
        inserted=inserted_total,
        updated=updated_total,
        total=total,
        files_processed=len(md_files),
        embeddings_skipped=embeddings_skipped_any,
        latency_ms=latency_ms,
    )
    return GuidelineSeedResult(
        inserted=inserted_total,
        updated=updated_total,
        total=total,
        files_processed=len(md_files),
        embeddings_skipped=embeddings_skipped_any,
    )
