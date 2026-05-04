"""MealAnalysis ORM model — Story 3.7 (모바일 SSE 스트리밍 분석 + 영속화).

D5 결정(2026-05-04 — IN으로 변경) 정합: 식단 *관리* 앱 본연의 UX. ``meal_analyses``
테이블이 SSE ``event: done`` 시점 UPSERT 입력 + ``GET /v1/meals`` JOIN 입력으로
사용자 재로그인 시 한 주 식습관 한눈에 보이도록.

스키마 (12 컬럼):
- ``id``                   ``uuid``        PRIMARY KEY (gen_random_uuid)
- ``meal_id``              ``uuid``        NOT NULL FK meals.id ON DELETE CASCADE — 1:1 (UNIQUE)
- ``user_id``              ``uuid``        NOT NULL FK users.id ON DELETE CASCADE — Story 4.3
                                            user-level 리포트 입력 + 소유권 redundant 가드
- ``fit_score``            ``int``         NOT NULL CHECK (0-100)
- ``fit_score_label``      ``text``        NOT NULL CHECK IN(5-band)
- ``fit_reason``           ``text``        NOT NULL CHECK IN(3-band — Story 3.5 정합)
- ``carbohydrate_g``       ``numeric``     NOT NULL — 식약처 OpenAPI 키 정합
- ``protein_g``            ``numeric``     NOT NULL
- ``fat_g``                ``numeric``     NOT NULL
- ``energy_kcal``          ``int``         NOT NULL
- ``feedback_text``        ``text``        NOT NULL — full LLM 본문 (상세 화면용)
- ``feedback_summary``     ``text``        NOT NULL CHECK length<=120 — 1줄 (목록 화면용)
- ``citations``            ``jsonb``       NOT NULL DEFAULT '[]' — Story 3.6 Citation 정합
- ``used_llm``             ``text``        NOT NULL CHECK IN('gpt-4o-mini','claude','stub')
- ``created_at`` / ``updated_at``         ``timestamptz`` NOT NULL DEFAULT now()

UNIQUE 제약 — ``uq_meal_analyses_meal_id`` ON ``(meal_id)`` — 1 meal = 1 analysis,
재분석은 ``ON CONFLICT (meal_id) DO UPDATE`` UPSERT 패턴.

인덱스 — ``idx_meal_analyses_user_id_created_at`` ON ``(user_id, created_at DESC)`` —
Story 4.3 주간 리포트 forward-compat (사용자별 최근 분석 N건 조회 가속).

CHECK 제약 — ``fit_score 0-100`` / ``fit_score_label IN`` / ``fit_reason IN`` /
``used_llm IN`` / ``feedback_summary length <=120``. application-level Pydantic도 강제하나
*adapter-level defensive double-gate*(시드 스크립트/manual SQL 우회 차단).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime, Integer

from app.db.base import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.db.models.meal import Meal


class MealAnalysis(Base):
    __tablename__ = "meal_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    meal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meals.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    fit_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # 5-band: allergen_violation/low/moderate/good/excellent (MealAnalysisSummary 정합).
    fit_score_label: Mapped[str] = mapped_column(Text, nullable=False)
    # Story 3.5 fit_reason 3-band: ok/allergen_violation/incomplete_data.
    fit_reason: Mapped[str] = mapped_column(Text, nullable=False)
    # 식약처 OpenAPI 표준 키. NUMERIC(소수점 보존) — Pydantic float 변환 시점에 라운딩.
    carbohydrate_g: Mapped[float] = mapped_column(Numeric, nullable=False)
    protein_g: Mapped[float] = mapped_column(Numeric, nullable=False)
    fat_g: Mapped[float] = mapped_column(Numeric, nullable=False)
    # kcal는 int 충분(소수점 무의미 — 식약처 1 kcal 단위 round).
    energy_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    # full LLM 본문 — 상세 화면 전체 텍스트 표시(Story 3.6 generate_feedback 결과).
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 1줄 요약 — derive helper(``feedback_summary.derive_feedback_summary``)로 생성.
    # 120자 cap은 application + DB CHECK 양쪽 강제(double-gate).
    feedback_summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Story 3.6 Citation 배열: [{source, doc_title, published_year}].
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # router 결정 추적: 'gpt-4o-mini'/'claude'/'stub' 3-way (Story 3.6 dual-LLM 정합).
    used_llm: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    # 1:1 관계 — Meal.analysis가 본 row를 lazy=raise_on_sql으로 포인트(Meal 모델에서 정의).
    meal: Mapped[Meal] = relationship(back_populates="analysis", lazy="raise_on_sql")

    __table_args__ = (
        # 1 meal = 1 analysis — UPSERT ON CONFLICT 입력.
        UniqueConstraint("meal_id", name="uq_meal_analyses_meal_id"),
        # Story 4.3 주간 리포트 forward-compat (user별 최근 N건 정렬).
        Index(
            "idx_meal_analyses_user_id_created_at",
            "user_id",
            text("created_at DESC"),
        ),
        # CHECK 제약 — DB-level fail-fast(SQL 우회 차단).
        CheckConstraint("fit_score >= 0 AND fit_score <= 100", name="ck_meal_analyses_fit_score"),
        CheckConstraint(
            "fit_score_label IN ('allergen_violation','low','moderate','good','excellent')",
            name="ck_meal_analyses_fit_score_label",
        ),
        CheckConstraint(
            "fit_reason IN ('ok','allergen_violation','incomplete_data')",
            name="ck_meal_analyses_fit_reason",
        ),
        CheckConstraint(
            "used_llm IN ('gpt-4o-mini','claude','stub')",
            name="ck_meal_analyses_used_llm",
        ),
        CheckConstraint(
            "length(feedback_summary) <= 120",
            name="ck_meal_analyses_feedback_summary_len",
        ),
    )
