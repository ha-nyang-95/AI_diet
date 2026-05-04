"""dev smoke — LangSmith 보드에 6노드 풀 트리 trace 송신 (운영자 검증용).

사용 시점:
    - Story 3.8 LangSmith 통합 후 실 분석 1회 호출의 보드 시각화 확인.
    - prompt/노드 변경 PR 후 회귀 평가 전, 노드 트리 정상 펼쳐지는지 점검.
    - 외주 client 영업 데모 직전 스모크 (보드 가시성 사전 확인).

전제:
    - docker-compose up -d (postgres + redis healthy).
    - .env에 OPENAI_API_KEY 박힘 (실 키, parse_meal/generate_feedback 노드용).
    - .env에 LANGSMITH_API_KEY 박힘. LANGCHAIN_TRACING_V2는 본 스크립트가 강제 true.
    - food_nutrition / knowledge_chunks 시드 완료 (`scripts/seed_food_db.py` +
      `seed_guidelines.py`). 미시드 시 retrieve_nutrition이 빈 결과 → Self-RAG
      rewrite/clarify 분기.

사용법:
    cd api && uv run python ../scripts/dev_smoke_six_node_pipeline.py

idempotent — 같은 deterministic user_id를 반복 시드(ON CONFLICT skip).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Windows ProactorEventLoop 비호환(psycopg checkpointer setup) — Selector로 강제.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

# LANGCHAIN_TRACING_V2 강제 활성 — .env가 false 디폴트라도 본 smoke는 trace 송신.
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")

import redis.asyncio as redis_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core import observability  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.models.consent import Consent  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.domain.legal_documents import CURRENT_VERSIONS  # noqa: E402
from app.graph.checkpointer import build_checkpointer, dispose_checkpointer  # noqa: E402
from app.graph.deps import NodeDeps  # noqa: E402
from app.graph.pipeline import compile_pipeline  # noqa: E402
from app.graph.state import MealAnalysisState  # noqa: E402

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker as _BaseSessionMaker

    _SessionMaker = _BaseSessionMaker[AsyncSession]

# deterministic UUID — 매 실행 동일 user 시드(ON CONFLICT skip).
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_GOOGLE_SUB = "dev-smoke-six-node-001"
DEV_EMAIL = "dev-smoke@balancenote.local"

DEV_RAW_TEXT = "삼겹살 200g 김치 1접시 쌀밥 1공기"


async def seed_dev_user(session_maker: _SessionMaker) -> None:
    """dev user + consent 시드 — 6노드 풀 흐름 통과 가능한 최소 fixture."""
    async with session_maker() as session:
        existing = (
            await session.execute(select(User).where(User.id == DEV_USER_ID))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"[seed] user {DEV_USER_ID} already exists — skip")
            return

        now = datetime.now(UTC)
        user = User(
            id=DEV_USER_ID,
            google_sub=DEV_GOOGLE_SUB,
            email=DEV_EMAIL,
            email_verified=True,
            display_name="Dev Smoke",
            role="user",
            created_at=now,
            updated_at=now,
            onboarded_at=now,
            age=30,
            weight_kg=70.0,
            height_cm=175,
            activity_level="moderate",
            health_goal="maintenance",
            allergies=["복숭아"],
            profile_completed_at=now,
        )
        session.add(user)
        # FK(consents.user_id → users.id) 위반 차단 — user 먼저 flush.
        await session.flush()
        consent = Consent(
            id=uuid.uuid4(),
            user_id=DEV_USER_ID,
            disclaimer_acknowledged_at=now,
            terms_consent_at=now,
            privacy_consent_at=now,
            sensitive_personal_info_consent_at=now,
            disclaimer_version=CURRENT_VERSIONS["disclaimer"],
            terms_version=CURRENT_VERSIONS["terms"],
            privacy_version=CURRENT_VERSIONS["privacy"],
            sensitive_personal_info_version=CURRENT_VERSIONS["sensitive_personal_info"],
            automated_decision_consent_at=now,
            automated_decision_version=CURRENT_VERSIONS["automated-decision"],
            created_at=now,
            updated_at=now,
        )
        session.add(consent)
        await session.commit()
        print(f"[seed] user {DEV_USER_ID} + consent inserted")


async def run_pipeline_once() -> None:
    print(
        f"[boot] tracing_v2={settings.langchain_tracing_v2}, project={settings.langsmith_project}"
    )
    observability.init_langsmith()

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    redis_client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)

    try:
        await seed_dev_user(session_maker)

        checkpointer, pool = await build_checkpointer(settings.database_url)
        try:
            deps = NodeDeps(
                session_maker=session_maker,
                redis=redis_client,
                settings=settings,
            )
            graph = compile_pipeline(checkpointer, deps)

            state = cast(
                MealAnalysisState,
                {
                    "meal_id": uuid.uuid4(),
                    "user_id": DEV_USER_ID,
                    "raw_text": DEV_RAW_TEXT,
                    "rewrite_attempts": 0,
                    "node_errors": [],
                },
            )
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}

            print(f"[run] raw_text={DEV_RAW_TEXT!r}")
            print("[run] graph.ainvoke ... (5-15s, OpenAI 호출 발생)")
            result = await graph.ainvoke(state, config=config)

            print()
            print(f"[done] final_fit_score : {result.get('final_fit_score')}")
            feedback = result.get("feedback")
            print(f"[done] feedback present: {feedback is not None}")
            if feedback is not None:
                text = feedback.text if hasattr(feedback, "text") else feedback.get("text", "")
                print(f"[done] feedback excerpt: {text[:120]!r}...")
            errors = result.get("node_errors") or []
            if errors:
                print(f"[done] node_errors: {errors}")
            else:
                print("[done] node_errors: 0 (풀 6노드 흐름 통과)")
        finally:
            await dispose_checkpointer(pool)
    finally:
        await redis_client.aclose()
        await engine.dispose()

    print()
    print("LangSmith UI:")
    print(f"  https://smith.langchain.com → Projects → {settings.langsmith_project} → Runs")
    print("  - parse_meal → retrieve_nutrition → evaluate_retrieval_quality")
    print("    → fetch_user_profile → evaluate_fit → generate_feedback")
    print("  - 노드별 latency / token / cost / inputs(마스킹) / outputs(마스킹)")


if __name__ == "__main__":
    asyncio.run(run_pipeline_once())
