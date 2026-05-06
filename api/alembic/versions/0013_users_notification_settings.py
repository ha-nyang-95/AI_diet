"""0013_users_notification_settings — Story 4.1.

``users`` 테이블에 알림 설정 4컬럼 + CHECK 제약 1건 + partial UNIQUE index 1건 추가.

4 컬럼 (Story 4.2 APScheduler nudge의 baseline 자원):

- ``notifications_enabled``  ``BOOLEAN NOT NULL DEFAULT true``
    PIPA Art.22(3) marketing 동의는 별 게이트지만, 본 nudge는 *서비스 이행*(미기록 알림은
    식단 관리 서비스 본연 기능 — 마케팅 메시지 X) → opt-out 모델 정합. 사용자 ON/OFF
    토글로 즉시 차단 가능.

- ``notification_time``  ``TIME NOT NULL DEFAULT '20:00:00'``
    KST 기준 *알림 시간* — 서버 cron이 ``notification_time + 30분`` 시점에 미기록 push
    발송 (Story 4.2). 본 마이그레이션은 컬럼만 박고 cron 소비는 Story 4.2 책임.

- ``notification_timezone``  ``TEXT NOT NULL DEFAULT 'Asia/Seoul'``
    IANA tz 식별자. Story 4.2가 APScheduler ``timezone='Asia/Seoul'`` SOT로 사용. MVP는
    한국 사용자 한정 — 변경 UI는 본 스토리 OUT(Story 8.4 polish forward).

- ``expo_push_token``  ``TEXT NULL``
    Expo push token (``ExponentPushToken[xxx]`` 형식). 단일 device만 보유(MVP 단순화 —
    multi-device support는 Story 8.4 polish forward).

CHECK 제약 1건:

- ``ck_users_notification_time_kst_format``
    ``notification_time IS NULL OR EXTRACT(SECOND FROM notification_time) = 0``
    분 단위 정렬 강제(초·분초 자유 입력 차단, APScheduler 일별 잡 안정성). ``IS NULL OR``
    분기는 Story 1.5 ``ck_users_age``/``ck_users_weight_kg`` 패턴 정합 — column이 NOT NULL
    이라도 defense-in-depth로 명시.

    **스펙 deviation 메모 (2026-05-06, DS Amelia)**: AC1 원본 스펙은 regex ``^[0-2][0-9]:
    [0-5][0-9]:00$``로 분 단위 정렬을 강제하나, SQLAlchemy text parser가 ``:00`` 시퀀스를
    named bind param으로, ``$``를 numeric paramstyle 위치 placeholder로 해석해 regex가
    런타임에 깨지는 회귀 발생. 의미 동등한 ``EXTRACT(SECOND FROM time) = 0`` 표현으로
    대체 — *seconds 필드(소수 포함)가 0이어야 함*은 *0초·소수 0*과 동치(``20:00:00`` 통과,
    ``20:30:45`` 차단, ``20:00:00.5`` 차단). 부차 효과는 동일 + parser 회귀 없음.

partial UNIQUE index 1건:

- ``ux_users_expo_push_token_active``
    ``ON users (expo_push_token) WHERE expo_push_token IS NOT NULL AND deleted_at IS NULL``
    동일 device가 여러 user에 매핑되는 회귀 차단(예: 사용자 A 로그아웃 후 동일 device에서
    사용자 B 로그인 시 B의 token이 A를 unset). ``deleted_at IS NULL`` 분기는 soft-delete된
    사용자의 token이 활성 사용자와 충돌하는 회귀 차단.

기본값 부여 시 lock window는 ms 수준(8주 MVP user count <100 — 별도 백필 SOP 무필요).

downgrade는 index drop → CHECK drop → 컬럼 drop 4 (역순) — Story 1.5 패턴 정합.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_users_notification_settings"
down_revision: str | None = "0012_create_meal_analyses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NOTIFICATION_TIME_CHECK_NAME = "ck_users_notification_time_kst_format"
# Story 4.1 spec deviation: regex 기반 (``... ~ '^[0-2][0-9]:[0-5][0-9]:00$'``)이
# SQLAlchemy text parser의 named bind(``:00``) + numeric paramstyle(``$``) 충돌로 깨짐.
# ``EXTRACT(SECOND FROM time) = 0``으로 의미 동등 표현 사용 (docstring 상세 메모 참조).
_NOTIFICATION_TIME_CHECK_SQL = (
    "notification_time IS NULL OR EXTRACT(SECOND FROM notification_time) = 0"
)
_EXPO_PUSH_TOKEN_INDEX_NAME = "ux_users_expo_push_token_active"


def upgrade() -> None:
    # 1) 4 컬럼 ADD — server_default로 기존 row 자동 백필.
    op.add_column(
        "users",
        sa.Column(
            "notifications_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notification_time",
            sa.Time(timezone=False),
            nullable=False,
            server_default=sa.text("'20:00:00'"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notification_timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Asia/Seoul'"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("expo_push_token", sa.Text(), nullable=True),
    )

    # 2) CHECK 제약 1건 — 분 단위 정렬 강제 (EXTRACT 기반 — docstring deviation 메모 참조).
    op.create_check_constraint(
        _NOTIFICATION_TIME_CHECK_NAME,
        "users",
        _NOTIFICATION_TIME_CHECK_SQL,
    )

    # 3) partial UNIQUE index — token 충돌 + soft-delete 사용자 회귀 차단.
    op.create_index(
        _EXPO_PUSH_TOKEN_INDEX_NAME,
        "users",
        ["expo_push_token"],
        unique=True,
        postgresql_where=sa.text("expo_push_token IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    # index drop → CHECK drop → 컬럼 drop 역순 (Story 1.5 패턴 정합).
    op.drop_index(_EXPO_PUSH_TOKEN_INDEX_NAME, table_name="users")
    op.drop_constraint(_NOTIFICATION_TIME_CHECK_NAME, "users", type_="check")
    op.drop_column("users", "expo_push_token")
    op.drop_column("users", "notification_timezone")
    op.drop_column("users", "notification_time")
    op.drop_column("users", "notifications_enabled")
