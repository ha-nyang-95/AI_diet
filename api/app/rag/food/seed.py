"""Story 3.1 — ``food_nutrition`` 시드 비즈니스 로직 (AC #4).

식약처 OpenAPI 1차 + 통합 자료집 ZIP 백업 2단 fallback + dev/ci/test graceful 분기
(D9). 1500-3000건 한식 우선 시드 + 임베딩 호출 + 멱등 INSERT.

흐름:
  1. **1차** — ``mfds_openapi.fetch_food_items(target_count=1500)`` 호출 → 응답
     ≥ target 시 채택.
  2. **2차** — 1차 실패 또는 부족 시 ``api/data/mfds_food_nutrition_seed.csv`` 정적
     백업 ZIP fallback. CSV 헤더만 있는 placeholder는 *2차 데이터 없음*으로 분류.
  3. **두 경로 모두 실패** — ``settings.environment`` 분기:
     - prod / staging — 비-zero exit + Sentry capture.
     - dev / ci / test — graceful 0건 진행 (food_aliases만 시드 + warning).
     - ``RUN_FOOD_SEED_STRICT=1`` — dev에서도 prod fail-fast 강제.

멱등 — ``ON CONFLICT (source, source_id) DO UPDATE SET ...`` (D5).

NFR-S5 — 음식명 raw 노출 X(잠재 raw_text 포함 — 식습관 추론). 통계만 (count + source).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import mfds_openapi, openai_adapter
from app.adapters.mfds_openapi import FoodNutritionRaw
from app.core.config import settings
from app.core.exceptions import (
    FoodSeedAdapterError,
    FoodSeedQuotaExceededError,
    FoodSeedSourceUnavailableError,
)

logger = structlog.get_logger(__name__)

# 시드 batch 단위 — 300건 (D6: OpenAI embeddings batch + DB transaction). 1500건 시드
# = 5 batches.
SEED_BATCH_SIZE: Final[int] = 300
SEED_TARGET_COUNT: Final[int] = 1500
SEED_GRACEFUL_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"dev", "ci", "test"})
RUN_FOOD_SEED_STRICT_ENV: Final[str] = "RUN_FOOD_SEED_STRICT"

# ZIP fallback CSV 경로 — `api/data/mfds_food_nutrition_seed.csv`. placeholder(헤더만)는
# *데이터 없음*으로 분류.
_SEED_CSV_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "data" / "mfds_food_nutrition_seed.csv"
)

_INSERT_SEED_SQL: Final[str] = """
INSERT INTO food_nutrition (
    name, category, nutrition, embedding, source, source_id
) VALUES (
    :name, :category, CAST(:nutrition AS jsonb),
    CAST(:embedding AS vector), :source, :source_id
)
ON CONFLICT (source, source_id) DO UPDATE SET
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    nutrition = EXCLUDED.nutrition,
    embedding = EXCLUDED.embedding,
    updated_at = now()
RETURNING (xmax = 0) AS inserted
"""


@dataclass(frozen=True, slots=True)
class FoodSeedResult:
    """``run_food_seed`` 결과 — 통계 + source 표시 (NFR-S5: 음식명 raw 노출 X)."""

    inserted: int
    updated: int
    total: int
    source: str  # "primary" / "fallback" / "none"


_STRICT_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


def _is_strict_mode() -> bool:
    """``RUN_FOOD_SEED_STRICT`` 환경 변수 set 여부 — dev에서도 fail-fast opt-in.

    12-factor 정합 — 대소문자 무시 + ``1``/``true``/``yes``/``on`` 모두 허용.
    """
    return os.environ.get(RUN_FOOD_SEED_STRICT_ENV, "").strip().lower() in _STRICT_TRUTHY


def _is_graceful_environment() -> bool:
    """현 환경이 graceful 분기 대상인지 (D9). strict opt-in 시 graceful 무효."""
    if _is_strict_mode():
        return False
    env = (settings.environment or "").strip().lower()
    return env in SEED_GRACEFUL_ENVIRONMENTS


def _embedding_text(item: FoodNutritionRaw) -> str:
    """임베딩 입력 텍스트 — ``f"{name} ({category})"`` (category None 시 name only) (D8).

    동일 음식명(*"국수"* 한식 vs 양식)을 카테고리로 분리 → 검색 정확도 ↑.
    """
    if item.category:
        return f"{item.name} ({item.category})"
    return item.name


def _csv_field_to_float(row: dict[str, str], key: str) -> float | None:
    """CSV row dict에서 float 변환 — 빈 문자열/누락은 None."""
    value = (row.get(key) or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _read_zip_fallback() -> list[FoodNutritionRaw]:
    """``api/data/mfds_food_nutrition_seed.csv`` 파일 읽기.

    파일 미존재 또는 헤더만 있는 placeholder(데이터 행 0건)는 빈 리스트 반환 —
    *데이터 없음* 신호.
    """
    if not _SEED_CSV_PATH.exists():
        return []

    items: list[FoodNutritionRaw] = []
    # ``utf-8-sig`` — Excel-export BOM 자동 제거 (운영자가 통합 자료집을 Excel로 변환 시
    # ``﻿name`` 키 silent skip 차단).
    with _SEED_CSV_PATH.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            raw_source_id = (row.get("source_id") or "").strip()
            if raw_source_id:
                source_id = raw_source_id
            else:
                # ``MFDS-ZIP-{idx}`` 인덱스 fallback은 CSV 행 재정렬 시 ON CONFLICT가 잘못된
                # 행을 덮어쓰는 데이터 손상 위험 → name 기반 안정 해시로 충돌 분리.
                source_id = f"MFDS-ZIP-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}"
            try:
                items.append(
                    FoodNutritionRaw.model_validate(
                        {
                            "name": name,
                            "category": (row.get("category") or "").strip() or None,
                            "energy_kcal": _csv_field_to_float(row, "energy_kcal"),
                            "carbohydrate_g": _csv_field_to_float(row, "carbohydrate_g"),
                            "protein_g": _csv_field_to_float(row, "protein_g"),
                            "fat_g": _csv_field_to_float(row, "fat_g"),
                            "saturated_fat_g": _csv_field_to_float(row, "saturated_fat_g"),
                            "sugar_g": _csv_field_to_float(row, "sugar_g"),
                            "fiber_g": _csv_field_to_float(row, "fiber_g"),
                            "sodium_mg": _csv_field_to_float(row, "sodium_mg"),
                            "cholesterol_mg": _csv_field_to_float(row, "cholesterol_mg"),
                            "serving_size_g": _csv_field_to_float(row, "serving_size_g"),
                            "serving_unit": (row.get("serving_unit") or "").strip() or None,
                            "source_id": source_id,
                            "source": "MFDS_ZIP",
                        }
                    )
                )
            except (ValueError, TypeError):
                # 부분 실패 graceful — 1행 skip + 진행.
                continue

    return items


def _nutrition_payload(item: FoodNutritionRaw) -> dict[str, object]:
    """``food_nutrition.nutrition`` jsonb 페이로드 — 식약처 표준 키 그대로 (None은 키 omission)."""
    payload: dict[str, object] = {}
    candidates = {
        "energy_kcal": item.energy_kcal,
        "carbohydrate_g": item.carbohydrate_g,
        "protein_g": item.protein_g,
        "fat_g": item.fat_g,
        "saturated_fat_g": item.saturated_fat_g,
        "sugar_g": item.sugar_g,
        "fiber_g": item.fiber_g,
        "sodium_mg": item.sodium_mg,
        "cholesterol_mg": item.cholesterol_mg,
        "serving_size_g": item.serving_size_g,
        "serving_unit": item.serving_unit,
        "source": item.source,
        "source_id": item.source_id,
    }
    for key, value in candidates.items():
        if value is not None:
            payload[key] = value
    return payload


def _format_vector_literal(vector: list[float] | None) -> str | None:
    """pgvector ``vector`` 입력 literal — ``[0.1,0.2,...]`` 문자열 cast.

    NaN/Inf은 pgvector가 reject — 1행이 batch 전체 transaction을 abort시키지 않도록
    None으로 강등 (검색 시 ``WHERE embedding IS NOT NULL`` 자동 제외, D4 graceful 흡수).
    """
    if vector is None:
        return None
    if any(not math.isfinite(v) for v in vector):
        logger.warning("food_seed.embedding_non_finite", dim=len(vector))
        return None
    return "[" + ",".join(format(v, ".7g") for v in vector) + "]"


async def _insert_batch(
    session: AsyncSession,
    items: list[FoodNutritionRaw],
    embeddings: list[list[float] | None],
) -> tuple[int, int]:
    """단일 batch INSERT 멱등 — ``(inserted, updated)`` 카운터 반환."""
    inserted = 0
    updated = 0

    for item, embedding in zip(items, embeddings, strict=True):
        try:
            nutrition_json = json.dumps(
                _nutrition_payload(item), ensure_ascii=False, allow_nan=False
            )
        except ValueError:
            # NaN/Inf nutrition 값 — jsonb invalid literal 회피용 row skip
            # (전 batch transaction abort 차단).
            logger.warning("food_seed.nutrition_non_finite", source_id=item.source_id)
            continue
        params: dict[str, object] = {
            "name": item.name,
            "category": item.category,
            "nutrition": nutrition_json,
            "embedding": _format_vector_literal(embedding),
            "source": item.source,
            "source_id": item.source_id,
        }
        result = await session.execute(text(_INSERT_SEED_SQL), params)
        row = result.first()
        if row is None:
            continue
        if row.inserted:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


async def _embed_batch(items: list[FoodNutritionRaw]) -> list[list[float] | None]:
    """batch 임베딩 호출 — 부분 실패 graceful (전체 batch가 fail이면 모두 None).

    개별 row 실패 분리는 cost 비효율(API 1건당 별 호출 = round-trip 폭발). batch
    전체 fail 시 NULL embedding으로 INSERT — 검색 시 ``WHERE embedding IS NOT NULL``
    자동 제외 (D4 graceful).
    """
    texts = [_embedding_text(item) for item in items]
    try:
        embeddings = await openai_adapter.embed_texts(texts)
    except FoodSeedAdapterError as exc:
        logger.warning(
            "food_seed.embedding_batch_failed",
            items_count=len(items),
            error=str(exc),
        )
        return [None] * len(items)
    if len(embeddings) != len(items):
        # OpenAI 부분 응답(undocumented but possible) — ``zip(..., strict=True)``
        # ValueError로 batch abort 차단. 전 batch NULL로 강등 (D4 graceful 흡수).
        logger.warning(
            "food_seed.embedding_count_mismatch",
            items_count=len(items),
            embeddings_count=len(embeddings),
        )
        return [None] * len(items)
    return list(embeddings)


async def _try_primary_source(target_count: int) -> tuple[list[FoodNutritionRaw], bool]:
    """1차 — 식약처 OpenAPI fetch.

    Returns:
        (items, sufficient) — sufficient=True는 ``target_count`` 도달, False는 응답 부족
        또는 예외(items=[]). 부족이어도 부분 결과는 보존(union for fallback).
    """
    try:
        items = await mfds_openapi.fetch_food_items(target_count=target_count)
    except (
        FoodSeedSourceUnavailableError,
        FoodSeedQuotaExceededError,
        FoodSeedAdapterError,
    ) as exc:
        logger.warning(
            "food_seed.primary_source_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return [], False
    if len(items) < target_count:
        logger.warning(
            "food_seed.primary_source_insufficient",
            count=len(items),
            target=target_count,
        )
        return items, False
    return items, True


async def run_food_seed(
    session: AsyncSession, *, target_count: int = SEED_TARGET_COUNT
) -> FoodSeedResult:
    """음식 영양 시드 — 1차 OpenAPI + 2차 ZIP fallback + dev graceful 분기.

    각 batch INSERT 직후 ``session.commit()`` — D6 *"5 batch / 5 commit / 부분 실패 시
    마지막 commit 이전 batch는 보존"* 정합. 호출자는 graceful 0건 분기 시점에 별도
    commit 처리.

    Returns:
        ``FoodSeedResult`` — inserted/updated/total/source. source는
        "primary"(OpenAPI), "fallback"(ZIP), "none"(graceful 0건).

    Raises:
        ``FoodSeedAdapterError`` — prod/staging 또는 strict 모드에서 두 경로 모두
        실패 시.
    """
    primary_items, primary_sufficient = await _try_primary_source(target_count)
    items: list[FoodNutritionRaw] = list(primary_items)
    source_used = "primary" if primary_items else ""

    if not primary_sufficient:
        # 2차 ZIP fallback — 1차 부분 결과 + ZIP 결과 union.
        zip_items = _read_zip_fallback()
        items.extend(zip_items)
        if zip_items:
            source_used = "primary+fallback" if primary_items else "fallback"

    if not items:
        # 두 경로 모두 데이터 없음 — 환경별 분기 (D9).
        if _is_graceful_environment():
            logger.warning(
                "food_seed.no_data_graceful",
                environment=settings.environment,
                strict=_is_strict_mode(),
            )
            return FoodSeedResult(inserted=0, updated=0, total=0, source="none")
        raise FoodSeedAdapterError(
            f"food_seed total failure: primary OpenAPI + ZIP fallback both unavailable "
            f"(environment={settings.environment})"
        )

    # target_count 상한 — 과다 수집 회피 (메모리/cost 보호).
    items = items[:target_count]

    # Batch 처리 — 300건 단위 (D6 — 5 batch / 5 commit). 각 batch 종료 직후 commit해
    # 부분 실패 시 마지막 commit 이전 chunk는 DB에 보존.
    inserted_total = 0
    updated_total = 0
    for chunk_start in range(0, len(items), SEED_BATCH_SIZE):
        chunk = items[chunk_start : chunk_start + SEED_BATCH_SIZE]
        embeddings = await _embed_batch(chunk)
        chunk_inserted, chunk_updated = await _insert_batch(session, chunk, embeddings)
        await session.commit()
        inserted_total += chunk_inserted
        updated_total += chunk_updated

    count_result = await session.execute(text("SELECT count(*) AS n FROM food_nutrition"))
    count_row = count_result.first()
    total = int(count_row.n) if count_row else 0

    logger.info(
        "food_seed.complete",
        inserted=inserted_total,
        updated=updated_total,
        total=total,
        source=source_used,
    )
    return FoodSeedResult(
        inserted=inserted_total,
        updated=updated_total,
        total=total,
        source=source_used,
    )
