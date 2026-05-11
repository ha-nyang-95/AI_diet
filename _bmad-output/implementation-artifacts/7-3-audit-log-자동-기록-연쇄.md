# Story 7.3: Audit log 자동 기록 + dependency 자동 연쇄

Status: done

<!-- Epic 7 세 번째 스토리 — Story 7.1(`current_admin` 3-tier transitive 체인 + admin
JWT + IP 가드 + `bn_admin_access` cookie + `admin_whoami` smoke) + Story 7.2(`admin.py`
6 endpoint + `app/core/masking.py` SOT + `idx_users_email_lower` alembic 0021) 베이스라인
위에 *FR37 audit log 자동 기록 + audit_admin_action ↔ current_admin 자동 연쇄*
본격 신설. epics.md:905-918 정합 + architecture.md:308 *"Audit log 위치 — FastAPI
Dependency `Depends(audit_admin_action)` admin 라우터에 일괄"* 정합 + architecture.md:370
*"`audit_admin_action` dependency는 `admin_user_jwt_required` dependency에 자동 연쇄"* 정합
+ architecture.md:547 *"모든 admin 라우터는 `Depends(audit_admin_action)` 명시"* 정합 +
architecture.md:882/891 FR35-FR39 매핑 정합. **본 스토리는 audit 인프라 SOT** — Story
7.2가 6 endpoint 각 docstring + 모듈 docstring에 *Story 7.3 forward stub*으로 명시한
6 action 식별자(`user_search` / `user_profile_view` / `user_meal_history_view` /
`user_feedback_history_view` / `user_profile_edit` / `admin_meal_delete`)를 본 스토리에서
실제 dependency wire + DB INSERT로 구현. **본 스토리는 *쓰기(write)* 인프라만** — *읽기
(read)* 흐름(`GET /v1/admin/audit-logs` self-audit endpoint + Web `/admin/audit-logs/page.tsx`
+ 사용자 검색 결과 카드 마스킹 + 원문 보기 토글 + 5분 비활동 자동 복원)은 Story 7.4
forward. 신규 6 영역: (1) **`audit_logs` 테이블 신설** — ORM(`app/db/models/audit_log.py`)
+ alembic 0022(13 컬럼 + 3 인덱스 + `audit_logs_action_enum` Postgres ENUM 7 값 +
append-only trigger), (2) **`audit_admin_action(action, target_resource=None)` factory
Dependency** — `app/api/deps.py`에 신규 추가 + `Depends(current_admin)` transitive 포함
(epics.md:914 *"admin_user_jwt_required ↔ audit_admin_action 자동 연쇄 — admin 토큰
없으면 audit 미발동"* 정합), (3) **`app/services/audit_service.py:record_admin_action`**
single-INSERT 서비스 + actor email 마스킹(`app/core/masking.py` SOT 재사용) + structlog
contextvars에서 request_id 추출 + `get_real_client_ip` SOT 재사용, (4) **`admin.py` 6
endpoint wire** — 각 `@router.<method>(...)` 데코레이터에 `dependencies=[Depends(
audit_admin_action(action=..., target_resource=...))]` 1줄 wire + 6 endpoint docstring에서
*Story 7.3 forward stub* 단락 제거 + 모듈 docstring 23-28행 forward stub 단락 제거,
(5) **append-only DB trigger** — `audit_logs_append_only_guard` PL/pgSQL function +
BEFORE UPDATE/DELETE trigger(epics.md:917 *"audit log는 변경 불가 — INSERT 외 권한
없음 (DB role 분리 또는 트리거)"* 정합 — 트리거 채택, DB role 분리는 Story 8.4/8.5
운영 polish forward), (6) **시간/액터/대상 3 인덱스** — `idx_audit_logs_occurred_at`
+ `idx_audit_logs_actor_id_occurred_at` + `idx_audit_logs_target_user_id_occurred_at`(
partial WHERE) — epics.md:918 *"audit_logs 1만 건 가정 검색 — 시간/액터/대상별 인덱스로
응답 ≤ 1초"* 정합(검색 endpoint는 7.4 책임이지만 인덱스 인프라는 본 스토리에 포함 —
schema 분기 회피). **본 스토리는 백엔드 admin auth core SOT(security.py / deps.py
`current_admin`/`current_admin_claims`/`require_admin_ip_allowed` / `bn_admin_access`
cookie / `users.role`) 변경 0건 — Story 1.2 + 7.1 산출물 *재사용*만** + admin.py 6
endpoint 본문 변경 0건(데코레이터 `dependencies=[...]` 추가 + docstring forward stub
제거만). `auth.py:admin_whoami`(Story 7.1)은 *audit 대상 X* — 7.1 docstring 580행 명시
*"Story 7.3 audit log 기록 대상 X (admin meta-info 조회는 enum scope 제외)"*. `POST
/v1/auth/admin/exchange`(admin 로그인)도 *audit 대상 X* — 인증 lifecycle endpoint는
admin business action 범주 외. **신규 모듈 3건**(`app/db/models/audit_log.py` +
`app/services/audit_service.py` + `app/api/deps.py:audit_admin_action` 함수) + **수정
3건**(`app/api/v1/admin.py` 데코레이터 wire + docstring + `app/db/models/__init__.py`
AuditLog 등록 + alembic 0022 신규). 신규 환경 변수 0건. 신규 web 파일 0건(7.4 책임).
신규 mobile 파일 0건. 본 스토리 후 sprint-status에 `7-3-...: ready-for-dev →
in-progress → review` 전이. PR pattern: feature branch `story/7.3-audit-log`(master에서
분기, CS 시작 직전 분기 완료) — DS/CR 모두 동일 브랜치, PR은 CR 완료 후 1회. -->

## Story

As a 시스템 / 외주 발주자,
I want 관리자의 모든 조회·수정 액션이 시점·액터·액션·대상·IP·request_id로 audit log에 자동 기록되기를,
So that B2B 외주 신뢰 카드(누가 무엇을 봤는지 추적 가능)가 작동한다.

## Acceptance Criteria

1. **AC1 — `audit_logs` 테이블 + ORM + alembic 0022 신규 + Postgres ENUM 7 값** (FR37 — 기록 매체 SOT)
   **Given** Story 7.2 산출물 — `app/db/models/__init__.py` 11 모델 등록 + `payment_logs`(Story 6.1 D9 D10) audit-trail 패턴 + alembic 0021 head + `users.role` 컬럼 SOT, **When** 본 스토리에서 `audit_logs` 테이블 + ORM + alembic 0022 신설, **Then**:
   - **신규 ORM** `api/app/db/models/audit_log.py` (`payment_log.py` 패턴 1:1 정합):
     ```python
     """AuditLog ORM model — Story 7.3 (관리자 audit log 자동 기록).

     ``audit_logs`` 테이블 — Epic 7 admin *audit-trail*. 관리자의 *모든 조회·수정 액션*
     을 시점·액터·액션·대상·IP·request_id로 영구 기록(append-only — Story 7.3 trigger
     SOT). soft-delete 미적용 — audit-trail 성격이라 영구 보존(``actor_id`` ondelete
     ``RESTRICT`` — admin 사용자 hard delete 시점에 audit 행 보존을 위해 차단 + 운영
     이벤트로 신호).

     13 컬럼:

     - ``id``                      ``UUID`` PK (``gen_random_uuid()`` server_default)
     - ``occurred_at``             ``timestamptz NOT NULL`` ``server_default=now()`` — FR37 *시점*
     - ``actor_id``                ``UUID NOT NULL`` FK ``users.id ON DELETE RESTRICT`` — FR37 *액터*
                                   (RESTRICT: admin hard delete 시 audit 보존 invariant 차단)
     - ``actor_email_masked``      ``Text NOT NULL`` — ``j***@example.com``(NFR-S5, `mask_email` SOT 재사용)
                                   ``users.email`` 변경 후에도 audit 시점 식별 정보 보존
     - ``action``                  Postgres ENUM ``audit_logs_action_enum`` NOT NULL — FR37 *액션*
                                   (``user_search`` / ``user_profile_view`` / ``user_meal_history_view`` /
                                   ``user_feedback_history_view`` / ``user_profile_edit`` /
                                   ``admin_meal_delete`` / ``user_pii_view``) — 마지막은 Story 7.4 forward
     - ``target_user_id``          ``UUID NULL`` FK ``users.id ON DELETE SET NULL`` — FR37 *대상*
                                   (검색 endpoint는 NULL — path param 없음)
     - ``target_resource``         ``Text NULL`` — ``users`` / ``meals`` / ``meal_analyses``
                                   resource 분류(검색·필터 인덱스 hit률 향상)
     - ``target_resource_id``      ``UUID NULL`` — ``admin_meal_delete``의 ``meal_id`` 등
                                   sub-resource id (target_user_id와 직교)
     - ``path``                    ``Text NOT NULL`` — ``/v1/admin/users/{user_id}`` evaluated URL
     - ``method``                  ``Text NOT NULL`` — ``GET`` / ``PATCH`` / ``DELETE``(HTTP method literal)
     - ``ip``                      ``INET NULL`` — ``get_real_client_ip`` SOT(Story 3.9 CR P1 정합).
                                   middleware/proxy fall-through 시 빈 string → NULL 변환
     - ``request_id``              ``Text NOT NULL`` — ``RequestIdMiddleware``(Story 3.x SOT)
                                   ``structlog.contextvars`` 추출. middleware 미통과 fallback ``"unknown"``
     - ``user_agent``              ``Text NULL`` — ``User-Agent`` 헤더(마스킹 X — 디바이스/브라우저
                                   식별 정보는 PII 비포함)

     인덱스 3건 — epics.md:918 *"시간/액터/대상별 인덱스로 응답 ≤ 1초"* 정합:

     - ``idx_audit_logs_occurred_at`` ``(occurred_at DESC)`` — 전체 시계열 sort. Story 7.4
       *내 활동 로그 시간순 표시* 정합.
     - ``idx_audit_logs_actor_id_occurred_at`` ``(actor_id, occurred_at DESC)`` — Story 7.4
       *self-audit (`actor_id=me` 분기)* 정합.
     - ``idx_audit_logs_target_user_id_occurred_at`` ``(target_user_id, occurred_at DESC)
       WHERE target_user_id IS NOT NULL`` partial — *"이 사용자에게 누가 무엇을 했나"* 역추적.
       partial WHERE — 검색(target_user_id NULL)은 색인 미진입으로 hot path INSERT 비용 0.
     """

     from __future__ import annotations

     import ipaddress
     import uuid
     from datetime import datetime
     from typing import Final, Literal

     from sqlalchemy import ForeignKey, Index, Text, text
     from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
     from sqlalchemy.dialects.postgresql import INET, UUID
     from sqlalchemy.orm import Mapped, mapped_column
     from sqlalchemy.types import DateTime

     from app.db.base import Base

     AUDIT_LOG_ACTION_VALUES: Final[tuple[str, ...]] = (
         "user_search",
         "user_profile_view",
         "user_meal_history_view",
         "user_feedback_history_view",
         "user_profile_edit",
         "admin_meal_delete",
         "user_pii_view",  # Story 7.4 forward — 원문 보기 토글 액션 자체 기록
     )

     AuditLogAction = Literal[
         "user_search",
         "user_profile_view",
         "user_meal_history_view",
         "user_feedback_history_view",
         "user_profile_edit",
         "admin_meal_delete",
         "user_pii_view",
     ]


     class AuditLog(Base):
         __tablename__ = "audit_logs"

         id: Mapped[uuid.UUID] = mapped_column(
             UUID(as_uuid=True),
             primary_key=True,
             server_default=text("gen_random_uuid()"),
         )
         occurred_at: Mapped[datetime] = mapped_column(
             DateTime(timezone=True), nullable=False, server_default=text("now()")
         )
         actor_id: Mapped[uuid.UUID] = mapped_column(
             UUID(as_uuid=True),
             ForeignKey("users.id", ondelete="RESTRICT"),
             nullable=False,
         )
         actor_email_masked: Mapped[str] = mapped_column(Text, nullable=False)
         action: Mapped[str] = mapped_column(
             PG_ENUM(
                 *AUDIT_LOG_ACTION_VALUES,
                 name="audit_logs_action_enum",
                 create_type=False,
             ),
             nullable=False,
         )
         target_user_id: Mapped[uuid.UUID | None] = mapped_column(
             UUID(as_uuid=True),
             ForeignKey("users.id", ondelete="SET NULL"),
             nullable=True,
         )
         target_resource: Mapped[str | None] = mapped_column(Text, nullable=True)
         target_resource_id: Mapped[uuid.UUID | None] = mapped_column(
             UUID(as_uuid=True), nullable=True
         )
         path: Mapped[str] = mapped_column(Text, nullable=False)
         method: Mapped[str] = mapped_column(Text, nullable=False)
         ip: Mapped[ipaddress.IPv4Address | ipaddress.IPv6Address | None] = mapped_column(
             INET, nullable=True
         )
         request_id: Mapped[str] = mapped_column(Text, nullable=False)
         user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

         __table_args__ = (
             Index(
                 "idx_audit_logs_occurred_at",
                 text("occurred_at DESC"),
             ),
             Index(
                 "idx_audit_logs_actor_id_occurred_at",
                 "actor_id",
                 text("occurred_at DESC"),
             ),
             Index(
                 "idx_audit_logs_target_user_id_occurred_at",
                 "target_user_id",
                 text("occurred_at DESC"),
                 postgresql_where=text("target_user_id IS NOT NULL"),
             ),
         )
     ```
   - **`app/db/models/__init__.py` 수정** — AuditLog import + `__all__` 등재(declarative metadata 등록):
     ```python
     from app.db.models.audit_log import AuditLog  # 신규
     # __all__에 "AuditLog" 추가 (알파벳순 정렬 유지)
     ```
   - **신규 alembic 0022** `api/alembic/versions/0022_create_audit_logs.py` (0019 `payment_logs` 패턴 1:1 정합):
     ```python
     """0022_create_audit_logs — Story 7.3 (관리자 audit log 자동 기록).

     본 revision은 *3건 변경*:

     1. ``audit_logs_action_enum`` Postgres ENUM 신규 (7 값).
     2. ``audit_logs`` 테이블 신규 (13 컬럼 + 3 인덱스).
     3. ``audit_logs_append_only_guard`` PL/pgSQL function + BEFORE UPDATE/DELETE
        트리거 신규 — epics.md:917 *"audit log는 변경 불가 — INSERT 외 권한 없음"* 정합.

     설계 결정:

     - **append-only enforcement: trigger 채택**. 대안 *DB role 분리*(audit_logs INSERT
       only role + app 일반 role)는 Railway managed Postgres에서 role 운영 SOT 별도 셋업
       + connection 분리(dual session_maker) 의무로 1인 8주 ROI 0. 트리거가 동일 invariant
       을 단일 DDL로 달성 + 회귀 테스트가 SQL-level 검증 가능. DB role 분리는 Story 8.4/8.5
       운영 polish forward(README *키 회전 SOP*와 동일 분류).
     - **`actor_id ON DELETE RESTRICT`**: admin hard delete 시 audit 행 보존 invariant
       차단 + 운영 이벤트로 신호. ``users.deleted_at`` soft delete + 30일 grace +
       ``soft_delete_purge`` cron(Story 5.2)이 hard delete 시점에 RESTRICT 위반 →
       cron 실패 신호 → 운영자 인지 → 사전 audit archival SOP 트리거(Story 8 forward).
     - **`target_user_id ON DELETE SET NULL`**: 대상 사용자 hard delete 시 audit 행 보존 +
       target_user_id NULL로 *"삭제된 사용자에 대한 audit"* 식별 가능.
     - **`INET` type for ip column**: Postgres native INET(IPv4 + IPv6 + CIDR notation 통합
       타입) — ``get_real_client_ip``가 IPv4-mapped IPv6(``::ffff:203.0.113.42``) 형태도
       반환 가능(Story 7.1 CR 정합)이라 INET이 자연 표현. 별 CHECK 제약 미적용 — INET 자체
       parsing이 invariant.

     prod-scale lock 주의 (0020/0021 패턴 정합): 본 ``op.create_table`` + ``op.create_index``는
     비-CONCURRENTLY 실행. baseline sandbox라 영향 0. 미래 prod 트래픽 후 alembic CONCURRENTLY
     SOP는 Story 8.4 운영 polish forward.

     회귀 0건: 신규 테이블 + ENUM + 트리거만 추가. 기존 컬럼/CHECK/인덱스 변경 없음.
     """

     from __future__ import annotations

     from collections.abc import Sequence

     import sqlalchemy as sa
     from alembic import op
     from sqlalchemy.dialects import postgresql

     revision: str = "0022_create_audit_logs"
     down_revision: str | None = "0021_admin_users_search_indexes"
     branch_labels: str | Sequence[str] | None = None
     depends_on: str | Sequence[str] | None = None


     _ENUM_NAME = "audit_logs_action_enum"
     _ENUM_VALUES = (
         "user_search",
         "user_profile_view",
         "user_meal_history_view",
         "user_feedback_history_view",
         "user_profile_edit",
         "admin_meal_delete",
         "user_pii_view",
     )

     _TRIGGER_FUNCTION = "audit_logs_append_only_guard"
     _TRIGGER_NAME = "audit_logs_append_only"

     # PL/pgSQL function — UPDATE/DELETE는 RAISE EXCEPTION으로 차단.
     # SECURITY DEFINER 미적용 — 함수가 호출자 권한으로 실행(Railway DB는 단일 owner라
     # 영향 0). 미래 DB role 분리(Story 8) 시점에 권한 boundary 재검토.
     _CREATE_FUNCTION_SQL = f"""
     CREATE OR REPLACE FUNCTION {_TRIGGER_FUNCTION}() RETURNS trigger AS $$
     BEGIN
         RAISE EXCEPTION 'audit_logs is append-only: % operation forbidden', TG_OP
             USING ERRCODE = 'P0001';
     END;
     $$ LANGUAGE plpgsql;
     """

     _DROP_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_TRIGGER_FUNCTION}();"

     _CREATE_TRIGGER_SQL = f"""
     CREATE TRIGGER {_TRIGGER_NAME}
     BEFORE UPDATE OR DELETE ON audit_logs
     FOR EACH ROW EXECUTE FUNCTION {_TRIGGER_FUNCTION}();
     """

     _DROP_TRIGGER_SQL = f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON audit_logs;"


     def upgrade() -> None:
         action_enum = postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME)
         action_enum.create(op.get_bind(), checkfirst=False)

         op.create_table(
             "audit_logs",
             sa.Column(
                 "id",
                 postgresql.UUID(as_uuid=True),
                 primary_key=True,
                 server_default=sa.text("gen_random_uuid()"),
             ),
             sa.Column(
                 "occurred_at",
                 sa.DateTime(timezone=True),
                 nullable=False,
                 server_default=sa.text("now()"),
             ),
             sa.Column(
                 "actor_id",
                 postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("users.id", ondelete="RESTRICT"),
                 nullable=False,
             ),
             sa.Column("actor_email_masked", sa.Text(), nullable=False),
             sa.Column(
                 "action",
                 postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME, create_type=False),
                 nullable=False,
             ),
             sa.Column(
                 "target_user_id",
                 postgresql.UUID(as_uuid=True),
                 sa.ForeignKey("users.id", ondelete="SET NULL"),
                 nullable=True,
             ),
             sa.Column("target_resource", sa.Text(), nullable=True),
             sa.Column("target_resource_id", postgresql.UUID(as_uuid=True), nullable=True),
             sa.Column("path", sa.Text(), nullable=False),
             sa.Column("method", sa.Text(), nullable=False),
             sa.Column("ip", postgresql.INET(), nullable=True),
             sa.Column("request_id", sa.Text(), nullable=False),
             sa.Column("user_agent", sa.Text(), nullable=True),
         )

         op.create_index(
             "idx_audit_logs_occurred_at",
             "audit_logs",
             [sa.text("occurred_at DESC")],
         )
         op.create_index(
             "idx_audit_logs_actor_id_occurred_at",
             "audit_logs",
             ["actor_id", sa.text("occurred_at DESC")],
         )
         op.create_index(
             "idx_audit_logs_target_user_id_occurred_at",
             "audit_logs",
             ["target_user_id", sa.text("occurred_at DESC")],
             postgresql_where=sa.text("target_user_id IS NOT NULL"),
         )

         op.execute(_CREATE_FUNCTION_SQL)
         op.execute(_CREATE_TRIGGER_SQL)


     def downgrade() -> None:
         op.execute(_DROP_TRIGGER_SQL)
         op.execute(_DROP_FUNCTION_SQL)
         op.drop_index("idx_audit_logs_target_user_id_occurred_at", table_name="audit_logs")
         op.drop_index("idx_audit_logs_actor_id_occurred_at", table_name="audit_logs")
         op.drop_index("idx_audit_logs_occurred_at", table_name="audit_logs")
         op.drop_table("audit_logs")
         action_enum = postgresql.ENUM(*_ENUM_VALUES, name=_ENUM_NAME)
         action_enum.drop(op.get_bind(), checkfirst=False)
     ```
   - **alembic round-trip 회귀 가드** `api/tests/alembic/test_alembic_0022_round_trip.py` (Story 6.1+ 패턴 정합):
     - `test_alembic_0022_upgrade_creates_audit_logs` — `alembic upgrade head` 후 `audit_logs` 테이블 + 3 인덱스 + ENUM + trigger 존재 확인(pg_catalog 쿼리).
     - `test_alembic_0022_downgrade_drops_everything` — downgrade 후 모두 미존재(table/enum/trigger/function 모두 0건).
     - `test_alembic_0022_round_trip_up_down_up` — up → down → up 무오류.

2. **AC2 — `audit_admin_action(action, target_resource=None)` factory Dependency + `audit_admin_action ↔ current_admin` 자동 연쇄** (FR37 — dep 연쇄 SOT, epics.md:914 정합)
   **Given** Story 7.1 `app/api/deps.py:current_admin` transitive 체인(IP 가드 + JWT + DB role) + Story 3.9 `app/core/proxy.py:get_real_client_ip` SOT + Story 3.x `RequestIdMiddleware` + structlog contextvars `request_id` bind, **When** `app/api/deps.py`에 factory dep 추가 + `app/services/audit_service.py` 신규 서비스 신설, **Then**:
   - **신규 함수** `api/app/api/deps.py:audit_admin_action`:
     ```python
     # ``app/api/deps.py`` 끝에 추가 (기존 함수 변경 0)

     from collections.abc import Awaitable, Callable
     # 기존 import에 Request만 이미 존재(Story 7.1 + 3.9 SOT) — 추가 import 0
     from app.db.models.audit_log import AuditLogAction


     def audit_admin_action(
         *,
         action: AuditLogAction,
         target_resource: str | None = None,
     ) -> Callable[..., Awaitable[None]]:
         """관리자 액션 audit log 자동 기록 factory Dependency (Story 7.3, FR37).

         반환된 dep은 ``Depends(current_admin)``을 transitive 포함 — admin 토큰 없거나
         IP 가드 차단되거나 role!=admin이면 ``current_admin`` 단계에서 raise되어 audit
         INSERT는 *미발동*(epics.md:914 *"admin_user_jwt_required ↔ audit_admin_action
         자동 연쇄"* 정합 — 정합성).

         FastAPI dep cache 정합: 핸들러 시그니처에 ``Depends(current_admin)``가 이미
         있어도 같은 request scope에서 한 번만 실행됨(dep cache 표준 동작) — DB 재조회
         비용 0.

         path param 자동 추출:
         - ``user_id`` 경로 변수 → ``target_user_id``(UUID parsing 실패 시 None).
         - ``meal_id`` 경로 변수 → ``target_resource_id``(UUID parsing 실패 시 None).
         - 그 외 path param은 향후 endpoint별 add-on 시 본 dep 확장(YAGNI: 현 6 endpoint는
           ``user_id``/``meal_id``로 충분).

         실패 격리(critical): audit INSERT 자체 실패(DB error/connection drop)는 *fail-open
         + log.error*. 사유 — admin business action을 audit infra 일시 장애로 차단하면
         거버넌스 가용성(B3 KPI) 위반 + audit DB 분리 시점(Story 8) 이전 단계에서 단일
         DB 가용성 risk 흡수. Sentry로 운영 알림 + structlog ERROR + 본 함수는 silent
         return(요청 진행). 단, *DB integrity error*(예: ENUM 값 mismatch — 본 모듈
         enum과 alembic ENUM SOT 정합 자동 보장)는 deployment 직전 회귀 가드(AC6)로 사전
         차단(런타임 분기 도달 0).
         """

         async def _dep(
             request: Request,
             admin: Annotated[User, Depends(current_admin)],
             db: DbSession,
         ) -> None:
             # lazy import — 순환 의존(deps ↔ services) 회피
             from app.services.audit_service import record_admin_action  # noqa: PLC0415

             await record_admin_action(
                 db,
                 request=request,
                 admin=admin,
                 action=action,
                 target_resource=target_resource,
             )

         return _dep
     ```
   - **신규 서비스** `api/app/services/audit_service.py`:
     ```python
     """관리자 audit log 자동 기록 서비스 — Story 7.3 (FR37).

     ``record_admin_action`` 단일 함수 — ``audit_admin_action`` factory Dependency가
     호출. payment_service.py audit-trail INSERT 패턴 1:1 정합 (single-INSERT + commit).

     실패 격리: DB error는 silent log.error + return. ``audit_admin_action`` docstring
     정합 — fail-open으로 admin business action 가용성 보존.
     """

     from __future__ import annotations

     import ipaddress
     import uuid
     from typing import TYPE_CHECKING

     import structlog
     from sqlalchemy import insert

     from app.core.masking import mask_email
     from app.core.proxy import get_real_client_ip
     from app.db.models.audit_log import AuditLog, AuditLogAction

     if TYPE_CHECKING:  # pragma: no cover
         from fastapi import Request
         from sqlalchemy.ext.asyncio import AsyncSession

         from app.db.models.user import User

     logger = structlog.get_logger(__name__)

     _REQUEST_ID_FALLBACK = "unknown"
     _USER_AGENT_HEADER = "User-Agent"


     def _extract_request_id() -> str:
         """structlog contextvars에서 ``RequestIdMiddleware`` bind된 ``request_id`` 추출.

         middleware 미통과(직접 dep call 등 비정상 진입) 시 ``"unknown"`` fallback —
         audit row의 ``request_id NOT NULL`` invariant 보존.
         """
         ctx = structlog.contextvars.get_contextvars()
         value = ctx.get("request_id")
         if isinstance(value, str) and value:
             return value
         return _REQUEST_ID_FALLBACK


     def _coerce_ip(raw: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
         """``get_real_client_ip`` SOT 결과를 ``INET`` 컬럼 형식으로 변환.

         빈 string(헤더 부재 + request.client None — 테스트 환경) 또는 parsing 실패 시
         ``None`` 반환. INET NULL 허용으로 audit row 보존.
         """
         if not raw:
             return None
         try:
             return ipaddress.ip_address(raw)
         except ValueError:
             return None


     def _extract_path_param_uuid(request: "Request", key: str) -> uuid.UUID | None:
         """``request.path_params[key]``을 UUID로 parsing. 누락/실패 시 ``None``."""
         raw = request.path_params.get(key)
         if not isinstance(raw, str) or not raw:
             return None
         try:
             return uuid.UUID(raw)
         except ValueError:
             return None


     async def record_admin_action(
         db: "AsyncSession",
         *,
         request: "Request",
         admin: "User",
         action: AuditLogAction,
         target_resource: str | None = None,
     ) -> None:
         """admin business action audit row INSERT + commit. fail-open log.error.

         payment_service single-INSERT 패턴 정합. ``commit()``은 본 함수에서 즉시 — read-only
         endpoint(검색/상세/이력)에서도 audit row가 persistent invariant 보존(write endpoint
         의 후속 ``db.commit()``과 별 트랜잭션 — 두 번째 commit은 audit row에는 무해).

         ``expire_on_commit=False``(lifespan SOT)로 commit 후에도 SQLAlchemy session 재사용
         가능 — 핸들러가 admin/db 객체를 계속 사용.
         """
         try:
             target_user_id = _extract_path_param_uuid(request, "user_id")
             target_resource_id = _extract_path_param_uuid(request, "meal_id")
             ip_value = _coerce_ip(get_real_client_ip(request) or None)
             request_id = _extract_request_id()
             user_agent = request.headers.get(_USER_AGENT_HEADER)

             await db.execute(
                 insert(AuditLog).values(
                     actor_id=admin.id,
                     actor_email_masked=mask_email(admin.email),
                     action=action,
                     target_user_id=target_user_id,
                     target_resource=target_resource,
                     target_resource_id=target_resource_id,
                     path=request.url.path,
                     method=request.method,
                     ip=ip_value,
                     request_id=request_id,
                     user_agent=user_agent,
                 )
             )
             await db.commit()
         except Exception as exc:  # noqa: BLE001
             # fail-open: rollback + log + return.
             #   - business action 가용성 보존(거버넌스 SLA 우선)
             #   - Sentry 자동 capture(SDK before_send → NFR-S5 마스킹 정합)
             #   - audit DB 분리 시점(Story 8)까지 단일 DB 가용성 risk 흡수
             try:
                 await db.rollback()
             except Exception:  # noqa: BLE001
                 pass  # rollback 실패도 silent — 핸들러 자체 실행은 진행
             logger.error(
                 "audit.record_admin_action.failed",
                 action=action,
                 error=str(exc),
                 exc_info=True,
             )
     ```
   - **단위 테스트** `api/tests/services/test_audit_service.py` 신규 1파일 + 8 케이스:
     - `test_record_admin_action_inserts_row_with_all_fields` — admin/request fixture → INSERT 1건 + 11 컬럼 모두 채워짐(occurred_at·id는 server side).
     - `test_record_admin_action_masks_actor_email` — `admin.email="john.smith@example.com"` → `actor_email_masked="j***@example.com"`.
     - `test_record_admin_action_target_user_id_from_path_param` — `request.path_params={"user_id": uuid_str}` → INSERT의 target_user_id 일치.
     - `test_record_admin_action_target_resource_id_from_meal_id_path_param` — `request.path_params={"user_id": ..., "meal_id": ...}` → target_resource_id가 meal_id.
     - `test_record_admin_action_target_user_id_invalid_uuid_to_none` — `path_params={"user_id": "garbage"}` → target_user_id NULL.
     - `test_record_admin_action_request_id_from_structlog_contextvars` — `bound_contextvars(request_id="abc-123")` → INSERT request_id="abc-123".
     - `test_record_admin_action_request_id_fallback_unknown` — contextvars 미바인드 → request_id="unknown" + INSERT 성공.
     - `test_record_admin_action_fail_open_on_db_error` — `db.execute`가 raise → logger.error 호출 + 본 함수 자체는 no-raise(silent return).
   - **단위 테스트** `api/tests/api/test_audit_admin_action_dep.py` 신규 1파일 + 4 케이스(factory dep 자체):
     - `test_audit_admin_action_is_factory_returning_callable` — `dep = audit_admin_action(action="user_search")` → `callable(dep)` + 같은 signature 2번 호출 → 별 callable(factory invocation isolated).
     - `test_audit_admin_action_propagates_admin_auth_failure_audit_not_fired` — admin 토큰 부재 endpoint 호출 → 401 + `audit_logs` 0건(`current_admin` 단계 raise).
     - `test_audit_admin_action_propagates_non_admin_role_audit_not_fired` — user JWT(role=user) → 403 + `audit_logs` 0건.
     - `test_audit_admin_action_propagates_ip_block_audit_not_fired` — `ADMIN_IP_ALLOWLIST=["1.2.3.4/32"]` + client_ip=0.0.0.0 → 403 + `audit_logs` 0건.

3. **AC3 — `admin.py` 6 endpoint wire + docstring forward stub 제거** (FR37 — wire SOT, Story 7.2 forward stub closure)
   **Given** Story 7.2 `app/api/v1/admin.py` 6 endpoint(각 docstring에 *Story 7.3 forward: `action="..."`* 명시) + 모듈 docstring 23-28행 *"Story 7.3 forward stub"* 단락, **When** 각 데코레이터에 `dependencies=[Depends(audit_admin_action(action=..., target_resource=...))]` 1줄 추가 + 본문 변경 0 + 각 endpoint docstring의 *Story 7.3 forward* 단락 제거, **Then**:
   - **6 endpoint wire 매핑**:
     ```python
     # api/app/api/v1/admin.py 상단 import에 추가
     from app.api.deps import DbSession, audit_admin_action, current_admin  # 기존 + audit_admin_action

     # AC1 — search_users (target_user_id 없음 — path param 부재)
     @router.get(
         "/users",
         dependencies=[
             Depends(audit_admin_action(action="user_search", target_resource="users")),
         ],
     )
     async def search_users(...):  # 본문 변경 0
         ...

     # AC2 — get_user_detail
     @router.get(
         "/users/{user_id}",
         dependencies=[
             Depends(audit_admin_action(action="user_profile_view", target_resource="users")),
         ],
     )
     async def get_user_detail(...):
         ...

     # AC3 — list_user_meals
     @router.get(
         "/users/{user_id}/meals",
         dependencies=[
             Depends(audit_admin_action(action="user_meal_history_view", target_resource="meals")),
         ],
     )
     async def list_user_meals(...):
         ...

     # AC4 — list_user_meal_analyses
     @router.get(
         "/users/{user_id}/meal-analyses",
         dependencies=[
             Depends(audit_admin_action(action="user_feedback_history_view", target_resource="meal_analyses")),
         ],
     )
     async def list_user_meal_analyses(...):
         ...

     # AC5 — patch_user_profile (write — 본 audit dep commit이 admin UPDATE보다 *먼저* 실행)
     @router.patch(
         "/users/{user_id}",
         dependencies=[
             Depends(audit_admin_action(action="user_profile_edit", target_resource="users")),
         ],
     )
     async def patch_user_profile(...):
         ...

     # AC6 — delete_user_meal (target_resource_id=meal_id from path)
     @router.delete(
         "/users/{user_id}/meals/{meal_id}",
         status_code=status.HTTP_204_NO_CONTENT,
         dependencies=[
             Depends(audit_admin_action(action="admin_meal_delete", target_resource="meals")),
         ],
     )
     async def delete_user_meal(...):
         ...
     ```
   - **docstring forward stub 제거** (각 endpoint + 모듈):
     - 모듈 docstring 23-28행 *"Story 7.3 forward stub..."* 단락 → 삭제 후 *"Story 7.3 SOT: 본 모듈 모든 endpoint는 `Depends(audit_admin_action(...))` wire 완료."* 1줄로 대체.
     - AC1 search_users docstring 272-274행 *"Story 7.3 forward: ..."* 단락 → 삭제(7.4 forward는 유지).
     - AC2 get_user_detail 360행 *"Story 7.3 forward: ..."* → 삭제.
     - AC3 list_user_meals 395행 → 삭제.
     - AC4 list_user_meal_analyses 481행 → 삭제.
     - AC5 patch_user_profile 552행 → 삭제.
     - AC6 delete_user_meal 606-607행 → 삭제.
   - **본문 변경 0 invariant** — 6 endpoint 핸들러 body(SQL/응답 모델/예외 raise)는 *완전 동일* — 데코레이터 + docstring만 변경. 회귀 0건 보존(Story 7.2 ~45 단위 테스트 + 8 patches re-verified 일관).
   - **dep cache 정합 검증**(integration smoke): `audit_admin_action` 반환 dep이 transitive `Depends(current_admin)`을 포함하지만 endpoint 시그니처의 `Depends(current_admin)`와 dep cache 공유 → DB SELECT `users WHERE id=...` 1회만 실행(스토리 7.1 CR W4 패턴 정합 — 본 스토리는 SQL query log 추가 검증 0건, Story 8 perf hardening 시 EXPLAIN 회귀 가드 도입).

4. **AC4 — audit_logs append-only DB trigger 검증** (FR37 — invariant SOT, epics.md:917 정합)
   **Given** AC1 alembic 0022 신규 `audit_logs_append_only_guard` PL/pgSQL function + `audit_logs_append_only` BEFORE UPDATE/DELETE trigger, **When** SQL UPDATE/DELETE 직접 시도, **Then**:
   - **UPDATE 차단 검증** `api/tests/db/test_audit_log_append_only.py:test_audit_log_update_raises_exception`:
     ```python
     # ARRANGE: audit_logs에 1행 INSERT
     audit_id = uuid.uuid4()
     await db.execute(insert(AuditLog).values(
         id=audit_id,
         actor_id=admin_user.id,
         actor_email_masked="a***@example.com",
         action="user_search",
         path="/v1/admin/users",
         method="GET",
         request_id="test-req",
     ))
     await db.commit()

     # ACT + ASSERT: UPDATE 시도 → DBAPIError(P0001) raise
     with pytest.raises(Exception) as exc_info:
         await db.execute(
             update(AuditLog).where(AuditLog.id == audit_id).values(action="user_profile_view")
         )
         await db.commit()
     # error message에 *"audit_logs is append-only: UPDATE operation forbidden"* 포함
     assert "append-only" in str(exc_info.value)
     ```
   - **DELETE 차단 검증** `test_audit_log_delete_raises_exception` — 동일 패턴(action만 DELETE):
     ```python
     with pytest.raises(Exception) as exc_info:
         await db.execute(delete(AuditLog).where(AuditLog.id == audit_id))
         await db.commit()
     assert "append-only" in str(exc_info.value)
     assert "DELETE" in str(exc_info.value)
     ```
   - **INSERT 정상 통과** `test_audit_log_insert_succeeds` — INSERT 1건 + SELECT 1건 hit 확인(trigger가 INSERT는 미차단 invariant).
   - **TRUNCATE 분기 — out of scope**: `TRUNCATE`는 row-level trigger를 발동 X (statement-level만). 본 트리거는 row-level이라 TRUNCATE는 미차단 — operational concern, app code path 도달 0(Story 8 운영 권한 SOP에서 명시).
   - **alembic 0022 trigger drop/recreate 회귀 가드** `test_alembic_0022_trigger_drop_and_recreate_round_trip`:
     - upgrade → trigger 존재(pg_trigger SELECT) → downgrade → trigger 미존재 → upgrade → trigger 다시 존재.

5. **AC5 — audit 인덱스 검증 (시간/액터/대상 3 인덱스 SOT)** (FR37 — search infrastructure, Story 7.4 forward 준비)
   **Given** AC1 alembic 0022 `idx_audit_logs_occurred_at` + `idx_audit_logs_actor_id_occurred_at` + `idx_audit_logs_target_user_id_occurred_at` partial WHERE, **When** alembic upgrade 후 인덱스 확인, **Then**:
   - **인덱스 3건 존재 확인** `test_alembic_0022_creates_three_indexes_with_correct_definitions`:
     - `idx_audit_logs_occurred_at` — `(occurred_at DESC)` btree.
     - `idx_audit_logs_actor_id_occurred_at` — `(actor_id, occurred_at DESC)` composite btree.
     - `idx_audit_logs_target_user_id_occurred_at` — `(target_user_id, occurred_at DESC) WHERE target_user_id IS NOT NULL` partial btree.
     - pg_indexes view query로 indexdef 문자열 contains assertion.
   - **partial WHERE 효과** `test_audit_log_partial_index_excludes_null_target_user_id`:
     - 5건 audit row INSERT (target_user_id=NULL 3건 + 5건 1건 + 5건 1건 = mixed).
     - `EXPLAIN SELECT WHERE target_user_id = ... ORDER BY occurred_at DESC` → `idx_audit_logs_target_user_id_occurred_at` hit 가시(execution plan parsing — Story 7.2 NFR-P9 검증 패턴 정합).
     - Story 7.4 *self-audit `actor_id=me`* + *target lookup* 두 흐름 모두 인덱스 hit.
   - **NFR-P9 의장 검증 (forward — Story 7.4)**: 본 스토리는 *기록(write)* infrastructure만 — *검색(read) ≤ 1초* 의장 검증은 Story 7.4 `GET /v1/admin/audit-logs` endpoint 신설 시 1만 row synthetic data + EXPLAIN 회귀 가드 도입. 본 스토리는 *인덱스 자체 존재 + partial WHERE 정합*만 검증(인프라 분기 책임 명료화).

6. **AC6 — admin.py 6 endpoint integration audit 기록 회귀 가드** (FR37 — end-to-end SOT)
   **Given** AC1-AC5 산출물 + Story 7.2 `test_admin_users.py` ~45 케이스, **When** `api/tests/api/v1/test_admin_audit_log.py` 신규 1파일 + ~24 케이스 작성, **Then**:
   - **endpoint별 audit 기록 검증** (6 endpoint × 평균 3 케이스 = 18 케이스):
     - `test_search_users_creates_audit_row` — admin JWT + `GET /v1/admin/users?q=foo` 200 → `audit_logs` 1건 + 11 필드 검증(actor_id=admin.id / actor_email_masked / action="user_search" / target_user_id=None / target_resource="users" / target_resource_id=None / path="/v1/admin/users" / method="GET" / ip / request_id / user_agent).
     - `test_get_user_detail_creates_audit_row_with_target_user_id` — `GET /v1/admin/users/{user_id}` 200 → audit row + target_user_id matches.
     - `test_list_user_meals_creates_audit_row` — `GET /v1/admin/users/{user_id}/meals` → action="user_meal_history_view" + target_resource="meals" + target_user_id matches.
     - `test_list_user_meal_analyses_creates_audit_row` — action="user_feedback_history_view" + target_resource="meal_analyses".
     - `test_patch_user_profile_creates_audit_row` — `PATCH /v1/admin/users/{user_id}` 200 → action="user_profile_edit" + target_resource="users".
     - `test_delete_user_meal_creates_audit_row_with_target_resource_id` — `DELETE .../meals/{meal_id}` 204 → action="admin_meal_delete" + target_resource="meals" + target_resource_id=meal_id.
     - `test_*_creates_audit_row_with_masked_actor_email` — 각 endpoint 후 actor_email_masked가 `mask_email(admin.email)`과 일치.
     - `test_*_creates_audit_row_with_request_id_from_middleware` — 6 endpoint 모두 `request_id` 컬럼이 `RequestIdMiddleware`가 발급한 UUID 형식 또는 클라이언트 송신 `X-Request-ID`.
     - `test_delete_user_meal_audit_row_persists_even_when_meal_not_found_404` — `MealNotFoundError` 분기에서도 audit row 존재(*시도 자체*가 audit 대상 — FR37 *조회·수정 액션* 정합).
   - **transitive 연쇄 검증** (4 케이스):
     - `test_admin_endpoint_without_token_returns_401_and_no_audit_row` — admin 토큰 부재 → 401 + audit_logs 0건(epics.md:914 *"admin 토큰 없으면 audit 미발동"* 정합).
     - `test_admin_endpoint_user_role_jwt_returns_403_and_no_audit_row` — role=user JWT → 403 + audit_logs 0건.
     - `test_admin_endpoint_ip_block_returns_403_and_no_audit_row` — `ADMIN_IP_ALLOWLIST=["1.2.3.4/32"]` + client_ip=0.0.0.0 → 403 + audit_logs 0건.
     - `test_admin_endpoint_expired_token_returns_401_and_no_audit_row` — admin JWT 만료(`exp` 과거) → 401 + audit_logs 0건.
   - **fail-open 검증** (2 케이스):
     - `test_admin_endpoint_succeeds_when_audit_insert_db_error` — `audit_service.record_admin_action`에 `db.execute`가 raise되도록 monkeypatch → endpoint 본문 200 + audit_logs 0건 + logger.error 호출 가시.
     - `test_admin_endpoint_fail_open_does_not_leak_exception_in_response` — fail-open 시 response payload는 정상 200(audit infra 장애를 클라이언트에 노출 X).
   - **회귀 0건** (3 케이스):
     - `test_existing_admin_user_search_responses_unchanged_after_audit_wire` — Story 7.2 ~45 테스트 PASS 후 본 스토리 추가 변경(데코레이터 + docstring) 후에도 응답 schema/JSON wire 동형(snapshot diff 0).
     - `test_admin_whoami_creates_no_audit_row` — `GET /v1/auth/admin/whoami` 200 → audit_logs 0건(Story 7.1 docstring 580행 *"audit 기록 대상 X"* 정합).
     - `test_admin_exchange_creates_no_audit_row` — `POST /v1/auth/admin/exchange` 200 → audit_logs 0건(auth lifecycle endpoint 미포함 정합).

## Tasks / Subtasks

- [x] AC1 — `audit_logs` 테이블 + ORM + alembic 0022 + ENUM 7 값 (FR37 기록 매체 SOT)
  - [x] `api/app/db/models/audit_log.py` 신규 — 13 컬럼 ORM + 3 `__table_args__` 인덱스 + `AuditLogAction` Literal + `AUDIT_LOG_ACTION_VALUES` Final tuple.
  - [x] `api/app/db/models/__init__.py` 수정 — `from app.db.models.audit_log import AuditLog` 추가 + `__all__`에 "AuditLog" 등재(알파벳순).
  - [x] `api/alembic/versions/0022_create_audit_logs.py` 신규 — `down_revision="0021_admin_users_search_indexes"` + ENUM create + table create + 3 인덱스 + trigger function + trigger 모두 upgrade + downgrade 대응.
  - [x] `api/tests/alembic/test_alembic_0022_round_trip.py` 신규 — pg_catalog 쿼리로 13 컬럼 + ENUM 7값 + 3 인덱스 정의 + trigger/function + FK ondelete invariant 6 케이스 검증. CLI 수동 alembic downgrade -1/upgrade head 회귀 검증 0 errors.

- [x] AC2 — `audit_admin_action` factory Dependency + `record_admin_action` service (FR37 dep 연쇄 SOT)
  - [x] `api/app/api/deps.py` 수정 — `audit_admin_action(action, target_resource=None)` factory 함수 추가 (기존 함수 변경 0). lazy import로 `app.services.audit_service` 순환 회피.
  - [x] `api/app/services/audit_service.py` 신규 — `record_admin_action` async 함수 + 3 helper(`_extract_request_id`/`_coerce_ip`/`_extract_path_param_uuid`) + fail-open `contextlib.suppress(Exception)` rollback + structlog ERROR.
  - [x] `api/tests/services/test_audit_service.py` 신규 — 8 케이스(필드 11개 검증 + 마스킹 + path param + request_id contextvars + fail-open).
  - [x] `api/tests/api/test_audit_admin_action_dep.py` 신규 — 4 케이스(factory invocation 격리 + admin 토큰 부재/role!=admin/IP 가드 차단 3 분기 transitive 연쇄).

- [x] AC3 — `admin.py` 6 endpoint wire + docstring forward stub 제거 (Story 7.2 forward closure)
  - [x] `api/app/api/v1/admin.py` 수정 — 6 endpoint 데코레이터에 `dependencies=[Depends(audit_admin_action(...))]` 1줄 추가 + 모듈 docstring + 6 endpoint docstring의 *Story 7.3 forward stub* 단락 제거 + import 추가(`audit_admin_action`). 본문 변경 0건 invariant.
  - [x] `api/tests/api/v1/test_admin_users.py` 회귀 가드(Story 7.2 46 케이스) — 모두 PASS 보존(`uv run pytest tests/api/v1/test_admin_users.py` 46 passed).

- [x] AC4 — audit_logs append-only DB trigger 검증 (epics.md:917 invariant)
  - [x] `api/tests/db/test_audit_log_append_only.py` 신규 — UPDATE/DELETE 차단(P0001 ERRCODE 검증) + INSERT 정상 통과 + partial index EXPLAIN 4 케이스.

- [x] AC5 — audit 인덱스 3건 검증 (epics.md:918 search infrastructure)
  - [x] AC1 alembic 0022 회귀 가드 — `idx_audit_logs_occurred_at` + `idx_audit_logs_actor_id_occurred_at` + `idx_audit_logs_target_user_id_occurred_at` partial WHERE 3건 정의 검증.
  - [x] `EXPLAIN` 분석 회귀 가드 — partial index hit 검증(`test_audit_log_partial_index_excludes_null_target_user_id`).

- [x] AC6 — admin.py 6 endpoint integration audit 기록 회귀 가드 (FR37 end-to-end SOT)
  - [x] `api/tests/api/v1/test_admin_audit_log.py` 신규 — 15 케이스(endpoint별 8 + transitive 추가 1 expired-token + fail-open 2 + 회귀 3 + nonexistent_user fail-open 1).
  - [x] 기존 `test_admin_users.py`(Story 7.2) 회귀 0건 — 데코레이터 추가 후 46 케이스 모두 PASS + JSON response schema 동형 보존.

- [x] 백엔드 빌드 게이트
  - [x] `uv run ruff check api` — 0 errors.
  - [x] `uv run ruff format api --check` — 0 errors.
  - [x] `uv run mypy api` — 0 errors (110 source files).
  - [x] `uv run pytest` — 1318 passed / 11 skipped / 0 failed + 신규 37 케이스(AC1 6 + AC2 12 + AC4 3 + AC5 1 + AC6 15) + coverage 89.06% (Story 7.2 baseline 88.98% 유지/상승).
  - [x] `uv run alembic upgrade head` + `alembic downgrade -1` + `alembic upgrade head` — 0 errors (수동 CLI 검증).

- [x] OpenAPI 자동 생성 (회귀 0건)
  - [x] `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` — admin.py 6 operation의 response schema 변경 0건. 데코레이터 `dependencies=[...]`만 추가 + docstring forward stub 제거이므로 schema 동형 자동 보존.
  - [x] `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 갱신 diff = -24 lines (`Story 7.3 forward` 단락 12줄씩 제거) — operation schema 변경 0건.
  - [x] `pnpm tsc --noEmit` web + mobile 모두 0 errors.

- [x] Sprint status 갱신
  - [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` — `7-3-audit-log-자동-기록-연쇄: ready-for-dev → in-progress → review → done` 전이 + `last_updated: 2026-05-11` + Story 7.3 done 코멘트 1단락(Story 7.2 코멘트 위에 prepend).

### Review Findings

3-layer CR 결과 (Blind Hunter / Edge Case Hunter / Acceptance Auditor — 2026-05-11):
- Raw 발견 28건 → dedup 22건 → triage **patch 5 / defer 3 / dismiss 14**.
- Acceptance Auditor: AC1-AC6 모두 pass, violations 0건.

#### Patch (적용 완료)

- [x] [Review][Patch] P1 — fail-open 테스트가 `logger.error` 호출을 assert 하지 않음 [api/tests/api/v1/test_admin_audit_log.py:301-360] — `audit_service.logger` patch로 `audit.record_admin_action.failed` event + `exc_info=True` invariant 검증 추가. `cache_logger_on_first_use=True` 때문에 `structlog.testing.capture_logs`는 우회됨 → mock patch 사용.
- [x] [Review][Patch] P2 — `_coerce_ip` IPv4-mapped IPv6 미정규화 [api/app/services/audit_service.py:_coerce_ip] — `addr.ipv4_mapped` 분기 추가. `check_admin_ip_allowed`(Story 1.2 SOT)와 동일 정규화 정합. 회귀 가드 `test_record_admin_action_ipv4_mapped_ipv6_is_normalized_to_ipv4`.
- [x] [Review][Patch] P3 — request_id 길이/제어문자 미정제 [api/app/services/audit_service.py:_extract_request_id, _sanitize_audit_text] — newline/NUL/길이 폭증 adversarial payload에 대해 제어문자(0x00-0x1f + 0x7f) strip + 128자 cap. 회귀 가드 `test_record_admin_action_request_id_strips_control_chars_and_caps_length`.
- [x] [Review][Patch] P4 — user_agent NUL byte/무제한 길이 [api/app/services/audit_service.py:record_admin_action] — `_sanitize_audit_text(..., _USER_AGENT_MAX_LEN=1024)` 적용. Postgres text NUL 거부 → fail-open silent drop 회피. 회귀 가드 2건(`test_record_admin_action_user_agent_nul_byte_is_stripped` + `test_record_admin_action_user_agent_only_control_chars_becomes_null`).
- [x] [Review][Patch] P5 — `/v1/admin/*` 신규 endpoint audit wire 누락 정적 가드 [api/tests/api/test_admin_routes_audit_coverage.py:신규] — `APIRoute.dependant.dependencies`에서 `audit_admin_action._dep` qualname 식별 + scope 외 SOT(`/v1/auth/admin/whoami`, `/v1/auth/admin/exchange`)는 명시 allowlist. 3 케이스(factory self-test + business wire 강제 + exclusion intent).
- [x] [Review][Patch] G1 — `except Exception` broad catch + nested `contextlib.suppress` rollback 흡수 (Gemini Code Assist 권고 — PR #42 inline review) [api/app/services/audit_service.py:113-141] — `except SQLAlchemyError`로 좁혀 DB/세션 장애만 fail-open, `TypeError`/`AttributeError` 등 코딩 버그는 노출. `db.rollback()` 자체 실패 시에도 `audit.record_admin_action.rollback_failed` 별도 ERROR 로깅으로 session 문제 신호 운영 가시 보존. **Re-evaluation**: 초기 CR triage에서 X2(broad catch)/X13(rollback-of-rollback) dismiss 판단을 외부 코드리뷰 신호 통합으로 재고 — anti-pattern 검출 정합. 신규 회귀 가드 `test_record_admin_action_does_not_swallow_programming_bugs` 1 케이스 추가. 기존 fail-open 테스트 4건의 `RuntimeError` simulant를 `OperationalError`(SQLAlchemyError 하위)로 변경.

#### Defer (deferred-work.md DF143-145로 forward)

- [x] [Review][Defer] D1 — `target_user_id` FK 위반 시 audit silent drop + attempted-vs-verified target [api/app/services/audit_service.py:91 + DS notes 970] — Story 8.4 운영 polish forward (FK 제거 + NULL fallback 검토). 이미 `test_patch_user_profile_with_nonexistent_user_id_fails_open` invariant 문서화 완료. **DF143**.
- [x] [Review][Defer] D2 — `actor_id ON DELETE RESTRICT` cron purge 실패 모니터링 부재 [api/app/db/models/audit_log.py:158-162 + alembic 0022:127-130] — Story 5.2 30일 grace 도달 시 cron 실패 alert 부재. Story 8.4/8.5 *audit DB role rotation SOP* forward (Deviation 1 spec 920행 명시). **DF144**.
- [x] [Review][Defer] D3 — alembic 0022 downgrade가 append-only 불변식 우회 [api/alembic/versions/0022_create_audit_logs.py:downgrade] — `drop_table(audit_logs)` 무차별 row 파괴 + ENUM `DROP TYPE` non-CASCADE. Story 8.4 audit DB role separation 시점에 DDL 권한 분리로 forward. **DF145**.

#### Dismiss (14건 — false-positive / 설계 의도 / 가치<비용)

설계 의도 명시(7건): 사전 commit(attempt-as-audit) / `except Exception` broad catch(fail-open SOT) / factory `_dep` identity per call(현 override 사용처 0건) / brittle 테스트(정상 동작) / structlog contextvars 격리(가설적) / `path` 컬럼 redundancy(설계 선택) / `target_user_id` 비-UUID `/me` alias(scope 외).
이미 다른 테스트에서 커버(2건): `enable_seqscan=OFF` partial WHERE → round-trip DDL test에서 literal 검증 / Story 7.2 schema 회귀 top-level only → `test_admin_users.py` 46 케이스에서 full schema 보장.
가치<비용(3건): ENUM downgrade CASCADE(downgrade rare) / SAVEPOINT nested txn(현 fixture 검증됨) / TRUNCATE vs DELETE fixture(conftest 이미 TRUNCATE).
forward 가능하나 local fix 부재(2건): 422 validation 전 audit 기록(DS 명시 attempt-as-audit) / rollback-of-rollback session-broken(별도 session_maker 분리는 Story 8 forward).

memory `feedback_no_dismiss_comment_for_false_positive` 정합 — PR 코멘트로 dismiss 사유 부착 안 함.

## Dev Notes

### 핵심 설계 결정

#### Story 1.2 + 7.1 + 7.2 SOT 재사용 (백엔드 admin auth core 변경 0건)

본 스토리는 **백엔드 admin JWT/검증/dep core 변경 0건** + **admin.py 6 endpoint 본문 변경 0건** + **신규 영역 5건만**(audit_log.py ORM + alembic 0022 + audit_service.py + deps.py `audit_admin_action` factory + admin.py 데코레이터 wire). Story 1.2/7.1/7.2가 이미 `current_admin`/`current_admin_claims`/`require_admin_ip_allowed`/admin JWT/8h TTL/`bn_admin_access` cookie/`AdminRoleRequiredError`/`AdminIpBlockedError`/admin business action 6 endpoint를 갖췄다 — *재발명 절대 금지*.

#### `audit_admin_action` factory Dependency — `dependencies=[...]` 데코레이터 wire 패턴

**대안 A — 핸들러 시그니처에 `Depends(audit_admin_action(...))` 추가**: 거부함. 6 endpoint 핸들러 시그니처가 변경 → Story 7.2 회귀 가드 ~45 케이스가 signature mock 패치 의무 + fail-open silent return을 핸들러가 인지할 의무 없음(audit는 side-effect만 — 핸들러에 audit row 반환 의무 0).

**대안 B — `dependencies=[Depends(audit_admin_action(...))]` 데코레이터 wire** *(채택)*: FastAPI 표준 — *side-effect-only* dep을 핸들러 시그니처 외 wire. 6 endpoint 본문 변경 0건 + Story 7.2 ~45 케이스 회귀 0건. dep cache가 동일 request scope의 `Depends(current_admin)`를 단일 instance로 공유(SQL N+1 회피).

**대안 C — 미들웨어 (`AuditAdminMiddleware`)**: 거부함. URL prefix 매칭(`/v1/admin/*`)이 brittle + admin route 외 admin business action(`/v1/auth/admin/whoami` 같은 exclusion case) 분기 의무가 미들웨어에 누적되면 maintenance 부담. architecture.md:308 *"미들웨어보다 좁고 의도 명확"* 정합.

**대안 D — decorator `@audit("user_search")`**: 거부함. architecture.md:308 *"디코레이터보다 FastAPI 표준 정합"* 명시.

#### `audit_admin_action ↔ current_admin` 자동 연쇄 (transitive chain)

`audit_admin_action` factory가 반환한 dep 내부에 `Annotated[User, Depends(current_admin)]` 명시 → FastAPI가 dep resolution graph에서 `current_admin`을 transitively 호출. admin 토큰 부재(401) 또는 role!=admin(403) 또는 IP 가드 차단(403) 시 `current_admin` 단계에서 raise → audit INSERT 미발동(epics.md:914 *"admin 토큰 없으면 audit 미발동"* 정합).

핸들러 시그니처에 이미 `Annotated[User, Depends(current_admin)]`이 있어도 FastAPI dep cache가 같은 dep callable을 단일 instance로 캐싱 — DB SELECT `users WHERE id=...` 1회만 실행(Story 7.1 CR W4 transitive 패턴 정합).

#### audit 실패 격리 — fail-open vs fail-closed

**대안 A — fail-closed**(audit INSERT 실패 → 500 RFC 7807 raise): 거부함. 단일 DB 가용성(Railway managed Postgres) 일시 장애 시 admin business action(거버넌스 SLA — B3 KPI)이 같이 차단되면 *audit infra 자체가 SPOF*. audit가 *증거 보존*이지 *권한 게이트*가 아니라는 epics.md:909 *"B2B 외주 신뢰 카드(누가 무엇을 봤는지 추적 가능)"* 정합 — *추적 가능*은 best-effort 의무, *권한 게이트*는 `current_admin` 책임.

**대안 B — fail-open + Sentry alert** *(채택)*: audit INSERT 실패 → `db.rollback()` + `logger.error(exc_info=True)` + Sentry 자동 capture(SDK before_send → NFR-S5 마스킹 정합) + 본 함수 silent return + 핸들러 진행. 운영자는 Sentry alert + structlog ERROR로 즉시 인지 + audit DB 분리(Story 8) 시점에 dual session_maker로 가용성 분리.

**대안 C — Outbox 패턴 (audit row를 별 큐에 enqueue + 비동기 sweep)**: 거부함. 1인 8주 YAGNI + Redis/RabbitMQ 큐 인프라 추가 + sweep worker 추가 = ROI 0. Story 7 scope 외(Story 8 운영 polish forward — Sentry 알람 임계치 N건/분 도달 시점).

#### `audit_logs` 컬럼 13개 — `target_resource_id` 별 컬럼 vs JSON

**대안 A — `target` JSON 컬럼**(`{"resource": "meals", "id": "..."}`) 1개: 거부함. JSON 인덱스(GIN) 추가 비용 + 검색 쿼리(`target->>'id' = ...`)가 SQL planner에서 plain column equality보다 어려움. Story 7.4 *"이 meal에 대한 모든 audit"* 검색 패턴에서 hit률 저하.

**대안 B — `target_resource`(Text) + `target_resource_id`(UUID NULL) 2 컬럼** *(채택)*: 컬럼 직교 + UUID column type-safe + 직접 인덱싱 가능. epics.md:915 *"target_user_id, target_resource"* 명시 + target_resource_id는 admin_meal_delete 케이스(meal_id) 흡수 — 컬럼 폭증 0(현 6 action 모두 user_id + 최대 1 sub-resource_id로 표현 가능).

#### actor_email vs actor_email_masked — 평문 보관 거부

**대안 A — actor_email 평문 컬럼 + 응답 시점에 마스킹**: 거부함. NFR-S5 *"민감정보 마스킹 — 단일 함수로 양 출력 스트림 동시 적용"* 정합 위반 + audit row dump(예: data export — Story 5.3 jsons CSV) 시 평문 이메일 누출 risk.

**대안 B — actor_email_masked 컬럼만 (`mask_email(admin.email)` 시점 영속화)** *(채택)*: NFR-S5 single-source-of-mask invariant + audit row 자체가 마스킹 state — Story 7.4 plaintext 토글 시점에 *actor*(=현 admin) email은 *자기 자신 정보*이므로 self-audit 화면에서 `request.state.user.email` 평문 노출(현 admin은 자기 이메일을 안다 — 정합). target_user의 email은 7.4 별 endpoint에서 plaintext 분기.

#### Postgres ENUM vs Text for action 컬럼

**대안 A — Text + CHECK 제약**: 거부함. enum 값 7개 + 미래 *user_pii_view*(7.4) + 운영 polish action(예: `user_data_export_view` — 8.x forward) 추가 시 CHECK alter migrations 의무 + 코드 ↔ DB sync invariant 약화.

**대안 B — Postgres ENUM** *(채택)*: type-safe + 자동 sync(ENUM 변경 시 alembic migration 의무). payment_logs `payment_logs_event_type_enum` 패턴 1:1 정합. mypy + ORM Literal 동기로 신규 action 추가 시 코드 + alembic + tests 3 지점이 컴파일 단계에서 차단.

#### audit_admin_action 미적용 대상 — `admin_whoami` + `admin_exchange`

**Story 7.1 `auth.py:admin_whoami`**: *읽기 전용 echo* — admin meta-info(자기 user_id/email/role/token_expires_at) 조회는 *business data 액션*이 아닌 *세션 introspection*. Story 7.1 docstring 580행 *"Story 7.3 audit log 기록 대상 X (admin meta-info 조회는 enum scope 제외)"* 명시. enum에 `admin_session_introspect` 추가는 추적 가치 vs 노이즈 trade-off에서 후자 우세(Web `(admin)/admin/layout.tsx` server-side guard 호출이 매 페이지 로드마다 발동 — audit row 노이즈 폭발).

**Story 1.2 `auth.py:admin_exchange`**: user JWT → admin JWT 교환 — *인증 lifecycle* endpoint(`current_admin` 미적용 — `current_user`만 사용, role==admin 검증 후 admin token 발급). epics.md:996 *"관리자의 모든 조회·수정 액션"* scope 외 + audit chain의 *admin 토큰 보유* 전제 위반(exchange는 admin 토큰을 *생성*).

**Story 1.2 admin logout + admin refresh**: refresh 미지원(8h TTL) + logout은 쿠키 clear만(stateless) — audit 가치 0.

#### `request_id` 추출 — structlog contextvars vs Request 헤더

**대안 A — `request.headers["X-Request-ID"]` 직접 read**: 거부함. middleware `_accept_or_generate` 분기 후 *normalized* request_id는 response 헤더에만 echo — request 객체의 헤더는 *inbound raw*. middleware가 invalid format(`!@#$`)을 거부하고 UUID4를 새로 발급한 경우 raw header에는 `!@#$`가 그대로 잔존 → audit row가 invalid id로 오염.

**대안 B — `structlog.contextvars.get_contextvars().get("request_id")`** *(채택)*: middleware가 `bound_contextvars(request_id=request_id)` 컨텍스트매니저로 bind된 *정규화된* 값. middleware 미통과(테스트 직접 dep 호출 등) fallback `"unknown"`. structlog SOT 정합(structlog가 이미 모든 log line의 SOT).

#### audit row 트랜잭션 격리 — write endpoint와 read endpoint 분기

**Story 7.2 admin.py 6 endpoint 트랜잭션 패턴**:
- *Read* endpoint(검색/상세/식단 이력/피드백 이력): `db.commit()` 호출 없음 — `get_db_session` 종료 시 자동 close(rollback if no commit).
- *Write* endpoint(PATCH/DELETE): `db.commit()` 명시 호출 후 응답.

`audit_admin_action` dep은 `record_admin_action`에서 `await db.commit()` 즉시 호출 — read endpoint에서도 audit row가 persistent 보존. write endpoint는 dep commit + 핸들러 commit 2회 commit(SQLAlchemy `expire_on_commit=False` lifespan SOT라 session 재사용 가능 — Story 1.2 lifespan 패턴 정합).

**원자성 trade-off**: dep commit이 핸들러 UPDATE보다 *먼저* 실행(FastAPI dep resolution 순서 — `dependencies=[...]`이 핸들러 본문보다 선행). 핸들러 UPDATE 실패 시 audit row는 이미 commit돼서 *시도 사실*이 영구 기록 — FR37 *"관리자의 모든 조회·수정 액션"* 정합(*시도*도 액션이며, 거버넌스 추적 측에서는 시도 자체가 가치). write 실패 시 audit row 단독 잔존은 *false positive* 위험이 아닌 *over-recording*(보수적 안전).

#### audit_logs 트리거 채택 — DB role 분리는 Story 8 forward

epics.md:917 *"INSERT 외 권한 없음 (DB role 분리 또는 트리거)"* — 둘 다 선택지로 명시. 1인 8주 ROI 비교:

- **DB role 분리**: Railway managed Postgres에서 별 role(audit_writer) 생성 + connection 분리(dual `session_maker`) + audit_logs `GRANT INSERT ONLY` + 일반 app role은 `REVOKE UPDATE, DELETE` — Railway secrets에 두 connection string + .env.example 변경 + production fail-closed 무신뢰 검증 의무. 운영 부담 ↑.
- **DB trigger** *(채택)*: 단일 DDL(`CREATE FUNCTION` + `CREATE TRIGGER`) — alembic 0022에 흡수 + 회귀 가드 단위 테스트(`pytest.raises`)로 SQL-level invariant 검증. 1인 8주 정합 + Story 7 scope 내 closure 가능.

DB role 분리는 Story 8.4/8.5 *운영 polish + 클라우드 hardening* 시점에 도입(README 1페이지 SOP — *audit DB role rotation*). 트리거는 *application-level + DB-level 이중 안전판*으로 미래 role 분리 후에도 보존 가치 있음.

### 라이브러리·프레임워크 요구

- **백엔드**:
  - `sqlalchemy` 2.x async — `insert(AuditLog).values(...)` ORM 패턴(payment_service.py 1:1 정합).
  - `alembic` — 0022 신규 migration + ENUM/trigger DDL.
  - `python-jose[cryptography]` — Story 1.2 baseline 재사용.
  - `pydantic` v2 — 본 스토리는 새 Pydantic 모델 0건(audit_log은 internal — 외부 API schema 미공개, Story 7.4가 공개).
  - 표준 라이브러리: `ipaddress.ip_address` (INET coercion), `uuid` (path param parsing + UUID PK), `structlog.contextvars` (request_id 추출).
- **테스트**:
  - `pytest` + `pytest-asyncio` + `httpx.AsyncClient` — Story 1.2/7.1/7.2 baseline 재사용.
  - `pytest.raises` — trigger invariant SQL-level 검증.
- **Web**: 본 스토리 web 변경 0건(Story 7.4 책임).
- **Mobile**: 본 스토리 mobile 변경 0건(admin은 web-only).

### 회귀 보존 SOT (절대 변경 금지)

- `api/app/api/deps.py:current_admin` + `current_admin_claims` + `require_admin_ip_allowed` — Story 1.2 + 7.1 SOT. 본 스토리는 *재사용*만 (`audit_admin_action`이 transitive 포함).
- `api/app/api/v1/admin.py` 6 endpoint 핸들러 *본문* — Story 7.2 SOT. 본 스토리는 *데코레이터* + *docstring forward stub 단락*만 변경 — SQL/응답 모델/예외 흐름 변경 0건.
- `api/app/core/masking.py:mask_email` — Story 7.2 SOT. 본 스토리는 *재사용*만(`audit_service.record_admin_action`에서 import).
- `api/app/core/proxy.py:get_real_client_ip` — Story 3.9 SOT(CR P1 정합). 본 스토리는 *재사용*만.
- `api/app/core/middleware.py:RequestIdMiddleware` — Story 3.x SOT. 본 스토리는 *contextvars consumer*만.
- `api/app/api/v1/auth.py:admin_whoami` + `admin_exchange` — Story 1.2 + 7.1 SOT. 본 스토리는 *audit 대상 미포함* 명시(docstring 580행 의도 보존).
- `api/app/db/models/user.py`/`meal.py`/`meal_analysis.py` — Story 1.5+/2.1+/3.7 SOT. 본 스토리는 *FK target*만 사용(`actor_id`/`target_user_id` FK to users.id).
- alembic 0001-0021 — 이전 스토리 SOT. 본 스토리는 *0022 추가*만(기존 head=0021에 append).

### 직전 스토리(7.2) 학습

- **CR 결과 4건 patch 즉시 적용** (memory `feedback_defer_vs_dismiss_in_cr`) — 본 스토리 CR도 동일 분류 규칙 적용. 가치 < 비용 / YAGNI / UX 데이터 부재는 dismiss.
- **dismiss 코멘트 회피** (memory `feedback_no_dismiss_comment_for_false_positive`) — PR 코멘트는 redundant ceremony. 본 스토리 CR도 false-positive에는 코멘트 X.
- **CR 종료 직전 sprint-status `review → done`** (memory `feedback_cr_done_status_in_pr_commit`) — 본 스토리도 PR commit에 status 갱신 포함 — chore PR 강제 회피.
- **Story 7.2 알림 3 필드 silent 누락 패턴**: Pydantic response model `extra="forbid"` 정합으로 spec line ↔ 모델 ↔ helper 3 지점 누락 사전 차단. 본 스토리는 *AuditLog ORM* 13 컬럼 ↔ alembic 0022 ↔ `record_admin_action` INSERT.values() 3 지점 정합 verify checklist 필수.
- **Story 7.2 case-insensitive UUID prefix 분기**: Postgres `uuid::text`는 항상 소문자. 본 스토리는 `request.path_params["user_id"]`가 *URL path*에서 직접 추출 — FastAPI 표준이 string 그대로 전달 + `uuid.UUID()` parser가 case-insensitive로 동작(Python 표준 라이브러리 — `UUID("ABC...")` == `UUID("abc...")`). audit row의 target_user_id는 normalized UUID(canonical lowercase hex)로 저장 invariant.
- **Story 7.2 web 테스트 deferred 처리** — 본 스토리는 web 변경 0건이라 N/A.
- **`current_admin` transitive 체인** (Story 7.1 CR W4 patch) — 본 스토리 `audit_admin_action` factory가 transitive 포함 + endpoint 시그니처의 `Depends(current_admin)`와 dep cache 공유(SQL N+1 회피).
- **alembic round-trip 회귀 가드** (Story 6.1+/6.2/6.3/7.2 패턴) — 본 스토리 0022도 동일 패턴(up/down/up + pg_catalog 쿼리).

### 환경 변수 추가

본 스토리 신규 환경 변수 0건. Story 1.2/3.9/7.1 기존(`API_BASE_URL` / `ADMIN_IP_ALLOWLIST` / `ENVIRONMENT`) 재사용만.

### Project Structure Notes

- Alignment with `architecture.md:308` *"Audit log 위치 — FastAPI Dependency `Depends(audit_admin_action)` admin 라우터에 일괄"* — 본 스토리에서 신설(6 endpoint 데코레이터 wire).
- Alignment with `architecture.md:370` *"`audit_admin_action` dependency는 `admin_user_jwt_required` dependency에 자동 연쇄 — admin 토큰 없으면 audit 미발동"* — `audit_admin_action` factory가 transitive `Depends(current_admin)` 포함으로 자동 연쇄.
- Alignment with `architecture.md:547` *"모든 admin 라우터는 `Depends(audit_admin_action)` 명시"* — 본 스토리 admin.py 6 endpoint 모두 wire + `auth.py:admin_whoami`/`admin_exchange`는 의도적 미적용(scope 외 — docstring 명시).
- Alignment with `architecture.md:686` `app/db/models/audit_log.py` — 본 스토리에서 신설.
- Alignment with `architecture.md:701` `app/services/audit_service.py` — 본 스토리에서 신설.
- Alignment with `architecture.md:661` `app/api/deps.py:audit_admin_action` — 본 스토리에서 신설(기존 `current_admin`/`require_admin_ip_allowed` SOT 옆에 추가).
- Alignment with `architecture.md:882` *"Admin/Audit (FR35-39) | `admin.py` | `audit_service.py` + admin role decorator | `audit_log`"* — 본 스토리에서 4 지점 모두 wire 완료.
- Alignment with `architecture.md:891` *"Audit log 자동 기록 (FR37) | `app/api/deps.py:audit_admin_action` Dependency + `services/audit_service.py`"* — 본 스토리에서 신설.
- Alignment with `architecture.md:392` *"테이블 — snake_case + 복수 — `audit_logs`"* — 본 스토리에서 신설.
- Alignment with `architecture.md:299` *"`audit_logs` ER 골격"* — `users` ↔ `audit_logs`(actor_id + target_user_id 2 FK) 관계 구축.
- **Deviation 1**: epics.md:917 *"DB role 분리 또는 트리거"* 둘 다 명시 — 본 스토리는 *트리거* 채택(1인 8주 ROI). DB role 분리는 Story 8.4/8.5 운영 polish forward로 명시(README *audit DB role rotation SOP*).
- **Deviation 2**: epics.md:918 *"audit_logs 1만 건 가정 검색 ≤ 1초"* — 본 스토리는 *인덱스 인프라*만 신설(3 인덱스 + partial WHERE). 실 검색 endpoint(`GET /v1/admin/audit-logs`) + 1만 row synthetic data EXPLAIN 검증은 Story 7.4 책임(read 흐름 분리).
- **Deviation 3**: epics.md:915 컬럼 명세는 `target_user_id`/`target_resource` 2개 — 본 스토리는 `target_resource_id`(UUID NULL) 1개 추가 = 3개. 사유: `admin_meal_delete` 케이스에서 `meal_id` 식별 의무(현 admin.py:606-607 forward stub 명시). epics.md는 *최소* 명세 — 컬럼 추가는 거버넌스 가시성 ↑ + 회귀 0(미사용 컬럼은 NULL 허용).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-7-Story-7.3 — Audit log 자동 기록 + dependency 자동 연쇄]
- [Source: _bmad-output/planning-artifacts/epics.md#FR37 — 관리자 모든 액션 audit log 자동 기록]
- [Source: _bmad-output/planning-artifacts/epics.md#NFR-S7 — Admin role JWT 별 secret + audit log 자동 기록]
- [Source: _bmad-output/planning-artifacts/architecture.md#authn-authz — Audit log 위치 `Depends(audit_admin_action)` admin 라우터에 일괄]
- [Source: _bmad-output/planning-artifacts/architecture.md#cross-component-dependencies — audit_admin_action ↔ admin_user_jwt_required 자동 연쇄]
- [Source: _bmad-output/planning-artifacts/architecture.md#enforcement-guidelines — 모든 admin 라우터는 Depends(audit_admin_action) 명시]
- [Source: _bmad-output/planning-artifacts/architecture.md#requirements-to-structure — FR37 매핑 (`deps.audit_admin_action` + `services/audit_service.py` + `audit_log` 모델)]
- [Source: _bmad-output/planning-artifacts/prd.md#FR37 — 관리자 모든 조회·수정 액션 audit 기록 (시점·액터·액션·대상)]
- [Source: _bmad-output/planning-artifacts/prd.md#NFR-S5 — 민감정보 마스킹 (actor_email 마스킹 SOT 재사용)]
- [Source: _bmad-output/planning-artifacts/prd.md#NFR-S7 — Admin role JWT + audit 자동 기록]
- [Source: api/app/api/deps.py:current_admin — Story 1.2 + 7.1 transitive IP 가드 + JWT + DB role 재확인 SOT (audit_admin_action이 transitive 포함)]
- [Source: api/app/api/v1/admin.py — Story 7.2 6 endpoint SOT (본 스토리는 데코레이터 + docstring 변경만, 본문 0건)]
- [Source: api/app/api/v1/admin.py:23-28 — Story 7.3 forward stub 단락 (본 스토리에서 제거)]
- [Source: api/app/api/v1/admin.py:272-274 — search_users action="user_search" forward stub]
- [Source: api/app/api/v1/admin.py:360 — get_user_detail action="user_profile_view" forward stub]
- [Source: api/app/api/v1/admin.py:395 — list_user_meals action="user_meal_history_view" forward stub]
- [Source: api/app/api/v1/admin.py:481 — list_user_meal_analyses action="user_feedback_history_view" forward stub]
- [Source: api/app/api/v1/admin.py:552 — patch_user_profile action="user_profile_edit" forward stub]
- [Source: api/app/api/v1/admin.py:606-607 — delete_user_meal action="admin_meal_delete" + target_resource_id=meal_id forward stub]
- [Source: api/app/api/v1/auth.py:572-591 — admin_whoami audit 대상 X (Story 7.1 580행 명시)]
- [Source: api/app/api/v1/auth.py:542-566 — admin_exchange 인증 lifecycle endpoint (audit 대상 X)]
- [Source: api/app/core/masking.py:mask_email — Story 7.2 NFR-S5 SOT (actor_email_masked 영속화 재사용)]
- [Source: api/app/core/proxy.py:get_real_client_ip — Story 3.9 CR P1 SOT (ip 컬럼 영속화 재사용)]
- [Source: api/app/core/middleware.py:RequestIdMiddleware — Story 3.x SOT (request_id contextvars bind)]
- [Source: api/app/db/models/payment_log.py — Story 6.1 audit-trail 13 컬럼 + 3 인덱스 패턴 1:1 정합]
- [Source: api/alembic/versions/0019_payment_logs.py — Story 6.1 ENUM + 테이블 + 인덱스 alembic 패턴]
- [Source: api/alembic/versions/0020_payment_logs_event_unique.py — Story 6.3 partial UNIQUE 패턴 (audit는 partial WHERE for target_user_id NULL 제외)]
- [Source: api/alembic/versions/0021_admin_users_search_indexes.py — Story 7.2 head SOT (0022 down_revision)]
- [Source: _bmad-output/implementation-artifacts/7-1-관리자-로그인-admin-jwt-가드.md — Story 7.1 admin auth baseline SOT]
- [Source: _bmad-output/implementation-artifacts/7-2-관리자-사용자-검색-이력-수정.md — Story 7.2 admin.py 6 endpoint SOT + masking.py SOT]
- [Source: _bmad-output/implementation-artifacts/sprint-status.yaml — `epic-7: in-progress` + `7-3-...: backlog → ready-for-dev` 진입]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

### Completion Notes List

- 2026-05-11 (Amelia, CS): Story 7.3 컨텍스트 작성 완료. Branch `story/7.3-audit-log` 분기 완료(master 기준). Epic 7 세 번째 스토리 — `7-3-...: backlog → ready-for-dev` 갱신 의무. **본 스토리는 admin auth core SOT(Story 1.2 + 7.1 + 7.2) 변경 0건 + admin.py 6 endpoint 핸들러 본문 변경 0건** — Story 7.2 ~45 회귀 테스트 보존 invariant. 신규 5 영역: (1) `app/db/models/audit_log.py`(13 컬럼 ORM + 3 인덱스 + 7-value ENUM Literal), (2) `alembic 0022`(테이블 + ENUM + trigger + 3 인덱스 + round-trip), (3) `app/api/deps.py:audit_admin_action`(factory + transitive `current_admin`), (4) `app/services/audit_service.py:record_admin_action`(single-INSERT + fail-open + 4 helper), (5) `app/api/v1/admin.py` 6 endpoint 데코레이터 `dependencies=[Depends(audit_admin_action(...))]` wire + docstring forward stub 제거. **scope 외**: `auth.py:admin_whoami`/`admin_exchange`는 audit 미적용(Story 7.1 docstring 580행 정합 + 인증 lifecycle scope 분리). Story 7.4 forward: `user_pii_view` ENUM 값은 본 스토리에서 등록 + 실 wire(원문 보기 토글 endpoint)는 7.4. `GET /v1/admin/audit-logs` self-audit endpoint + 1만 row EXPLAIN 검증은 Story 7.4. **append-only 구현**: DB trigger 채택(DB role 분리는 Story 8.4/8.5 forward). **fail-open 정책**: audit INSERT 실패 시 silent log.error + business action 진행(B3 KPI SLA 우선 + Story 8 audit DB 분리 시점에 dual session_maker로 가용성 분리). **dep cache 정합**: `audit_admin_action`이 transitive `Depends(current_admin)` 포함 + endpoint 시그니처 `Depends(current_admin)`와 dep cache 공유(SQL N+1 회피 — Story 7.1 CR W4 패턴 정합). **신규 의존성 0건** + **신규 환경 변수 0건** — Story 1.2/7.1/7.2 baseline 재사용. **회귀 0건**: admin.py 핸들러 본문 변경 0 + Story 7.2 OpenAPI schema 동형 보존(데코레이터 `dependencies=[...]`만 추가).

- 2026-05-11 (Amelia, DS): Story 7.3 구현 완료, Status → review. **신규 백엔드 5 파일**: `audit_log.py` ORM(13 컬럼 + 3 인덱스 + 7-value ENUM Literal) / `alembic 0022_create_audit_logs.py`(테이블 + ENUM + trigger function + 트리거 + 3 인덱스) / `audit_service.py:record_admin_action`(fail-open + 3 helper + `contextlib.suppress(Exception)` rollback) / `deps.py:audit_admin_action`(factory + transitive `current_admin`) / `admin.py` 6 endpoint 데코레이터 wire. **수정 4 파일**: `db/models/__init__.py`(AuditLog 등재) + `admin.py`(데코레이터 + import + docstring forward stub 제거) + `deps.py`(factory 추가) + `conftest.py`(TRUNCATE에 audit_logs prepend — actor_id RESTRICT FK 회피). **신규 테스트 5 파일 37 케이스**: `test_alembic_0022_round_trip.py` 6(스키마/ENUM/인덱스/트리거/FK ondelete) + `test_audit_log_append_only.py` 4(INSERT/UPDATE/DELETE 트리거 + partial index EXPLAIN) + `test_audit_service.py` 8(필드 11개 + 마스킹 + path param + contextvars + fail-open) + `test_audit_admin_action_dep.py` 4(factory + transitive 3 실패 분기) + `test_admin_audit_log.py` 15(endpoint별 8 + expired-token 1 + fail-open 2 + 회귀 3 + nonexistent_user 1). **빌드 게이트 통과**: ruff/format/mypy 0 errors + pytest 1318 passed/11 skipped/0 failed + coverage 89.06% (Story 7.2 baseline 88.98% 유지) + alembic up/down/up 0 errors + web/mobile tsc 0 errors + OpenAPI diff -24 lines(forward stub 단락 제거만 — operation schema 변경 0건). **회귀 0건**: `test_admin_users.py` 46 케이스 모두 PASS. **알려진 design caveat (Story 8 forward)**: `target_user_id` FK 위반 시 audit row 미기록 — nonexistent user_id 접근은 fail-open로 silent drop. 명시 회귀 가드(`test_patch_user_profile_with_nonexistent_user_id_fails_open`)로 invariant 문서화. Story 8.4 운영 polish에서 target_user_id FK 제거 + NULL fallback 검토 (audit 가시성 vs FK invariant trade-off 재고).

### File List

**Backend (api/) — 신규 3 파일 + 수정 4 파일**:

- `api/app/db/models/audit_log.py` (신규) — AuditLog ORM(13 컬럼) + `AUDIT_LOG_ACTION_VALUES` Final tuple + `AuditLogAction` Literal + 3 `__table_args__` Index.
- `api/app/services/audit_service.py` (신규) — `record_admin_action` async 함수 + 3 helper(`_extract_request_id` / `_coerce_ip` / `_extract_path_param_uuid`) + fail-open `contextlib.suppress(Exception)` rollback + structlog logger.
- `api/alembic/versions/0022_create_audit_logs.py` (신규) — `audit_logs_action_enum` 7-value ENUM + audit_logs 테이블 + 3 인덱스(+ partial WHERE) + `audit_logs_append_only_guard` PL/pgSQL function + BEFORE UPDATE/DELETE trigger. `down_revision="0021_admin_users_search_indexes"`.
- `api/app/api/deps.py` (수정) — `audit_admin_action(action, target_resource=None)` factory 함수 추가 + `AuditLogAction` import + 모듈 docstring 갱신. 기존 함수 변경 0건. lazy import로 audit_service 순환 회피.
- `api/app/db/models/__init__.py` (수정) — `from app.db.models.audit_log import AuditLog` + `__all__`에 "AuditLog" 등재.
- `api/app/api/v1/admin.py` (수정) — 6 endpoint 데코레이터에 `dependencies=[Depends(audit_admin_action(action=..., target_resource=...))]` 1줄 wire + 모듈 docstring(23-28행) + 6 endpoint docstring(272-274/360/395/481/552/606-607)의 *Story 7.3 forward stub* 단락 제거 + `from app.api.deps import audit_admin_action` import 추가. 본문 변경 0건.
- `api/tests/conftest.py` (수정) — TRUNCATE 명령에 `audit_logs` prepend(actor_id RESTRICT FK 회피 + 명시 per-test 격리). 1줄 코멘트 추가.

**Backend tests (api/tests/) — 신규 5 파일 (37 케이스)**:

- `api/tests/services/test_audit_service.py` (신규) — `record_admin_action` 8 케이스(11 필드 검증 + 마스킹 + path param + request_id contextvars + fail-open).
- `api/tests/api/test_audit_admin_action_dep.py` (신규) — factory dep 4 케이스(invocation 격리 + admin 인증 실패 3 분기 transitive 연쇄).
- `api/tests/db/test_audit_log_append_only.py` (신규) — trigger 3 케이스(UPDATE/DELETE 차단 + INSERT 정상) + partial index EXPLAIN 1 케이스 = 4 케이스.
- `api/tests/api/v1/test_admin_audit_log.py` (신규) — 15 케이스(endpoint별 8 + expired-token 연쇄 1 + fail-open 2 + 회귀 3 + nonexistent_user fail-open 1).
- `api/tests/alembic/test_alembic_0022_round_trip.py` (신규) + `__init__.py` (신규 빈 패키지) — 6 케이스(스키마 13 컬럼 + ENUM 7값 + 3 인덱스 정의 + 트리거 function 존재 + actor_id RESTRICT + target_user_id SET NULL).

**OpenAPI 자동 생성 (수정 2 파일 — diff -24 lines, operation schema 변경 0건)**:

- `web/src/lib/api-client.ts` (자동 생성 갱신) — admin.py 6 operation의 docstring forward stub 단락 제거만(12줄). operation schema/필드/응답 모델 변경 0건. `pnpm tsc --noEmit` 0 errors.
- `mobile/lib/api-client.ts` (자동 생성 갱신) — 동일 패턴 12줄 제거. mobile tsc 0 errors.

**Sprint status (수정 1 파일)**:

- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `7-3-audit-log-자동-기록-연쇄: ready-for-dev → in-progress → review` 전이 + `last_updated: 2026-05-11` + Story 7.3 review 코멘트 1단락(Story 7.2 코멘트 위에 prepend).

### Change Log

- 2026-05-11 — Story 7.3 ready-for-dev (Amelia, CS).
- 2026-05-11 — Story 7.3 review — AC1-AC6 구현 + 빌드 게이트 통과(ruff/format/mypy 0 errors + pytest 1318 passed/coverage 89.06% + alembic up/down/up 0 errors + web/mobile tsc 0 errors + OpenAPI diff -24 lines forward-stub docstring 제거만). 신규 백엔드 3 파일 + 수정 4 파일 + 신규 테스트 5 파일 37 케이스. Story 7.2 회귀 46 케이스 모두 PASS (admin.py 본문 변경 0건 invariant 보존). (Amelia, DS).
- 2026-05-11 — Story 7.3 done — 3-layer CR 통과 + patch 5건 적용 + defer 3건 (DF143-145) forward. pytest 1325 passed/coverage 89.08%/ruff·format·mypy 0 errors. (Amelia, CR).
- 2026-05-11 — Story 7.3 follow-up — PR #42 Gemini Code Assist 권고 통합 patch G1 적용(`except Exception` → `except SQLAlchemyError` + rollback 실패 별도 로깅). 신규 회귀 가드 1 케이스(`test_record_admin_action_does_not_swallow_programming_bugs`). 기존 fail-open 테스트 4건의 simulant 타입을 `OperationalError`로 갱신. pytest 1326 passed/coverage 89.06%/ruff·format·mypy 0 errors. CI 8 jobs 모두 pass(alembic-dry-run/lint-format-api/openapi-diff/test-api/typecheck-api/typecheck-mobile/typecheck-web). (Amelia, CR follow-up).
- 2026-05-11 — Story 7.3 done — 3-layer CR 통과(Acceptance Auditor AC1-AC6 violations 0 + Blind Hunter 13 + Edge Case Hunter 15 raw, dedup 22, triage patch 5/defer 3/dismiss 14). **Patch 5건 적용**: P1 fail-open `logger.error` invariant assert(mock patch — cache_logger_on_first_use 우회) / P2 IPv4-mapped IPv6 INET 정규화 / P3 request_id 제어문자 strip + 128자 cap / P4 user_agent NUL strip + 1024자 cap / P5 `/v1/admin/*` audit wire 정적 가드 신규 테스트(3 케이스). **신규 테스트 7 케이스 추가** (test_audit_service 4 + test_admin_routes_audit_coverage 3) — pytest 1325 passed (Story 7.3 baseline 1318 → +7) / coverage 89.08% (baseline 89.06% 유지/상승). **Defer 3건** (DF143/DF144/DF145) deferred-work.md 등재. Story 7.2 회귀 0건 보존. (Amelia, CR).
- 2026-05-11 — Story 7.3 follow-up — PR #42 Gemini Code Assist 권고 통합 patch G1 적용(`except Exception` → `except SQLAlchemyError` + rollback 실패 별도 로깅). 초기 CR에서 X2/X13 dismiss 판단을 외부 코드리뷰 신호 통합으로 재고 — anti-pattern 검출 정합. 신규 회귀 가드 1 케이스. 기존 fail-open 4 테스트 simulant 타입 갱신. pytest 1326 passed / coverage 89.06% / CI 8/8 pass. (Amelia, CR follow-up).
