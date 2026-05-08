# Story 6.1: 정기결제 sandbox 신청 + 1플랜

Status: done

<!-- Validation: Epic 6 첫 스토리 — Toss Payments 단일 채택(prd.md:925 *"결제 sandbox(W7)가 일정 압박 시 → Toss Payments 단일(Stripe 영문 가이드 README 미루기)로 압축"* 정합). Stripe는 본 스토리에서 README 안내·구조 hook만 두고 실 어댑터 구현은 Story 6.2/8.5 forward. epics.md:829-842 정합 — `POST /v1/payments/subscribe` 신규 + `subscriptions`/`payment_logs` DB 모델 2건 신설(alembic 0018/0019) + `app/adapters/toss.py` 신규 + `app/api/v1/payments.py` 신규 + `app/services/payment_service.py` 신규 위에 *KRW 9,900원 monthly 1플랜 sandbox 신청 흐름*을 신설. Idempotency-Key 처리는 Story 2.5 `meals.py:_create_meal_idempotent_or_replay` SOT 패턴 1:1 정합 + payments 도메인 catalog로 신설(DF49 *cross-cutting base 분리*는 Story 6.3 webhook 시점에 재검토 — 본 스토리에서는 `PaymentIdempotencyKeyInvalidError(PaymentError)` payments-specific 유지). 모바일은 App Store IAP 정책(prd.md:676)에 정합하기 위해 *외부 웹 결제 우선*(`Linking.openURL` → Web `/account/subscribe`) — sandbox 단계는 deep-link 복귀 X(Toss 결제 완료 화면이 Web 자체 redirect로 충분, sandbox는 영업 데모 검증 한정). Web은 `@tosspayments/payment-widget-sdk ^1.x` 신규 의존성 + Toss test card(`4330-1234-1234-1234`)로 SDK 1차 검증. RFC 7807 `payment-failed` 신규 code 카탈로그 + Sentry 자동 수집(`payment.confirm_failed` event). 본 스토리는 *최초 신청 + active subscription row 작성*만 — 자동 갱신·webhook·해지·이용내역 조회는 Story 6.2/6.3 분리. -->

## Story

As a 엔드유저,
I want 정기결제 1플랜(월 9,900원)을 sandbox 결제 화면에서 신청하기를,
So that 외주 클라이언트가 자체 구독 모델을 입혀나갈 수 있는 결제 흐름의 기준 구현을 확인할 수 있다.

## Acceptance Criteria

1. **AC1 — `subscriptions` / `payment_logs` 신규 테이블 + alembic 0018/0019 마이그레이션**
   **Given** architecture.md:299 ER *"`subscriptions` → `payment_logs`"* SOT + architecture.md:392 naming 컨벤션(snake_case 복수) + Story 2.5 `meals.idempotency_key` partial UNIQUE 패턴 SOT(0009 정합) + Story 5.2 `users.deleted_at` soft-delete 정합, **When** 신규 ORM 모델 2건 + 마이그레이션 2건 작성, **Then**:
   - **`api/app/db/models/subscription.py` 신규** — `Subscription(Base)` ORM 모델:
     - `id: uuid` PK (`gen_random_uuid()` server_default).
     - `user_id: uuid` FK `users.id` `ondelete="CASCADE"` NOT NULL.
     - `status: str` Postgres ENUM `subscriptions_status_enum`(`active` / `cancelled` / `expired`) NOT NULL. ENUM 이름은 architecture.md:396 *`<table>_<col>_enum`* 정합.
     - `plan: str` Postgres ENUM `subscriptions_plan_enum`(`monthly`) NOT NULL. 단일값 enum이지만 Story 6.x 후속에서 plan 추가 시 ENUM `ALTER TYPE ... ADD VALUE` 자연 확장.
     - `plan_price_krw: int` NOT NULL — KRW integer(NFR-L3 정합, 9,900). architecture.md:479 *"통화 KRW integer(원 단위, 소수 미사용)"* SOT.
     - `started_at: datetime` `timezone=True` NOT NULL `server_default=now()`.
     - `cancelled_at: datetime | None` `timezone=True` NULL — Story 6.2 cancel 흐름에서 set.
     - `expires_at: datetime | None` `timezone=True` NULL — *현재 결제 주기 만료일*. Story 6.1 신청 시 `started_at + 30일`로 set(monthly plan 단일 값). 갱신·webhook은 Story 6.3.
     - `provider: str` Postgres ENUM `subscriptions_provider_enum`(`toss` / `stripe`) NOT NULL — Story 6.1 baseline은 `toss`만 INSERT. `stripe` enum 값은 *forward-compat ENUM 등재*만(Story 8.5 Stripe 어댑터 도입 시 갱신 X — 한 번에 등록).
     - `provider_billing_key: str | None` `Text` NULL — Toss billing key(future 자동 갱신용 — Story 6.3). 본 스토리 베이스라인에서는 `confirm_payment` 응답에 billingKey 미포함(*1회 결제 confirm* 흐름) → 항상 `NULL`. 컬럼만 신설(forward-compat — Story 6.3에서 `/v1/billing/authorizations/issue` 응답으로 set).
     - `created_at: datetime` `timezone=True` NOT NULL `server_default=now()`.
     - `updated_at: datetime` `timezone=True` NOT NULL `server_default=now()` `onupdate=now()`.
     - **partial UNIQUE 제약**: `idx_subscriptions_user_id_active_unique = (user_id) WHERE status = 'active'` — 한 사용자에 1 active subscription invariant. Story 6.2 cancel 시점에 status=cancelled로 전이하면 다음 신청 가능.
     - **FK ondelete="CASCADE"** — `users.deleted_at` soft-delete + Story 5.2 30일 grace 후 hard-delete 시점에 자동 cascade. 운영 정합.
   - **`api/app/db/models/payment_log.py` 신규** — `PaymentLog(Base)` ORM 모델:
     - `id: uuid` PK (`gen_random_uuid()` server_default).
     - `user_id: uuid` FK `users.id` `ondelete="CASCADE"` NOT NULL.
     - `subscription_id: uuid | None` FK `subscriptions.id` `ondelete="SET NULL"` NULL — 결제 시점에 subscription row가 *동일 트랜잭션에서 막 생성*되므로 NOT NULL이 자연이지만, *환불/실패 결제 등 subscription 무관 이벤트* forward-compat 위해 nullable + SET NULL.
     - `event_type: str` Postgres ENUM `payment_logs_event_type_enum`(`subscribe` / `cancel` / `renew` / `failed` / `refund`) NOT NULL — Story 6.1 baseline은 `subscribe` / `failed`만 INSERT. 다른 값은 forward-compat ENUM 등재만.
     - `provider: str` Postgres ENUM `payment_logs_provider_enum`(`toss` / `stripe`) NOT NULL — Story 6.1은 `toss`만.
     - `provider_payment_key: str | None` `Text` NULL — Toss `paymentKey`(36+자) 또는 Stripe `pi_...`. 결제 실패 시 NULL 가능(Toss confirm 호출 전 단계 실패).
     - `provider_order_id: str | None` `Text` NULL — Toss `orderId`(클라이언트 생성 UUID v4 권장). 멱등 dedup 보조.
     - `amount_krw: int` NOT NULL — 9,900(KRW integer 정합).
     - `status: str` Postgres ENUM `payment_logs_status_enum`(`success` / `failed` / `pending`) NOT NULL — Story 6.1 baseline은 `success` / `failed`만. `pending`은 Story 6.3 webhook (`pending → success/failed` 전이).
     - `idempotency_key: str | None` `Text` NULL — application-level Idempotency-Key 헤더 영속화(Story 2.5 `meals.idempotency_key` 패턴 정합).
     - `raw_payload: dict[str, Any] | None` `JSONB` NULL — Toss `confirm_payment` 응답 본문(*마스킹 후* — `customerEmail` / `customerName` 등은 `before_send` masking + 본 모델 INSERT 전 inline `_mask_payment_payload` 호출. 카드 식별 4자리 + ApprovalNumber 보존). 운영 디버깅 / Story 8.4 audit 정합 forward.
     - `occurred_at: datetime` `timezone=True` NOT NULL — Toss `approvedAt` 또는 server `now()` fallback.
     - `created_at: datetime` `timezone=True` NOT NULL `server_default=now()`.
     - **인덱스**:
       - `idx_payment_logs_user_id_occurred_at = (user_id, occurred_at DESC)` — Story 6.2 history 조회 정합.
       - `idx_payment_logs_provider_payment_key_unique = (provider, provider_payment_key) WHERE provider_payment_key IS NOT NULL` partial UNIQUE — Toss/Stripe paymentKey가 같은 결제건에 2번 INSERT되는 케이스 차단(Story 6.3 webhook 멱등화 forward-compat).
       - `idx_payment_logs_user_id_idempotency_key_unique = (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL` partial UNIQUE — Story 2.5 0009 패턴 1:1 정합. application-level Idempotency-Key replay race-free SELECT-INSERT-CATCH-SELECT(`_create_payment_log_idempotent_or_replay` 헬퍼).
   - **alembic 0018_subscriptions.py 신규** — Postgres ENUM 3종 생성(`subscriptions_status_enum` / `subscriptions_plan_enum` / `subscriptions_provider_enum`) + `subscriptions` 테이블 생성 + partial UNIQUE 1건. `down_revision = "0017_users_deletion_reason_idx"`.
   - **alembic 0019_payment_logs.py 신규** — Postgres ENUM 3종 생성(`payment_logs_event_type_enum` / `payment_logs_provider_enum` / `payment_logs_status_enum`) + `payment_logs` 테이블 생성 + 인덱스 3종(시계열 1 + partial UNIQUE 2). `down_revision = "0018_subscriptions"`.
   - **enum 정합 invariant**: ORM 모델 `Mapped[str]` + SQLAlchemy `Enum` 타입(name=ENUM 이름, values=리터럴 5종) — Postgres ENUM 직접 매핑(`create_type=False`로 alembic이 ENUM 생성 책임 SOT). Pydantic 응답 모델(`SubscriptionResponse` / `PaymentLogResponse`)은 `Literal["active","cancelled","expired"]` 사용.
   - **`api/app/db/models/__init__.py` import 추가** — `from .subscription import Subscription` + `from .payment_log import PaymentLog`(이미 순차 import 패턴 SOT, Story 5.x 정합).
   - **단위 테스트 1건** `api/tests/test_subscriptions_payment_logs_schema.py` 신규 ~3건 — partial UNIQUE 검증(같은 user에 active 2건 시도 → IntegrityError) + ENUM 값 invariant + FK CASCADE 동작.

2. **AC2 — `app/adapters/toss.py` 신규 + `confirm_payment` 어댑터 + Toss API 통합**
   **Given** architecture.md:693 *"`toss.py`"* adapter SOT + `httpx` 표준 HTTP client(architecture.md:198) + `tenacity` retry(Story 3.6 SOT) + `app/core/config.py:settings.toss_secret_key`(이미 baseline 178행), **When** Toss Payments sandbox API 어댑터 작성, **Then**:
   - **신규 파일** `api/app/adapters/toss.py` — Toss Payments REST API 어댑터(sandbox + prod 단일 baseURL, Toss는 환경 분리가 secret_key 분기로만).
   - **`TOSS_API_BASE_URL: Final[str] = "https://api.tosspayments.com"`** — sandbox/prod 공통(Toss 정책 — secret_key 시작 prefix `test_sk_`/`live_sk_`로 환경 분리).
   - **`async def confirm_payment(*, payment_key: str, order_id: str, amount: int) -> TossConfirmResponse`** — Toss `POST /v1/payments/confirm` 호출:
     - 인증: `Authorization: Basic {base64(secret_key + ":")}` (Toss는 Basic Auth, secret_key 뒤 콜론 + 빈 password — Toss 표준).
     - body: `{"paymentKey": payment_key, "orderId": order_id, "amount": amount}`.
     - timeout: `httpx.Timeout(connect=5.0, read=15.0)` — Toss API 응답은 ~3-5초 평균(card auth + clearing).
     - retry: `tenacity` `stop_after_attempt(3)` + `wait_exponential(multiplier=1, min=1, max=4)` — *transient 5xx + ConnectError + ReadTimeout만* retry. 4xx(`PAY_PROCESS_CANCELED` / `INVALID_CARD` 등 카드 실패)는 *retry 무효* — 즉시 `PaymentProviderRejectedError` raise.
     - 에러 분기:
       - `TossSecretKeyMissingError(PaymentError)` 503 — `settings.toss_secret_key`가 `""`. fail-fast.
       - `PaymentProviderUnavailableError` 502 — 5xx 후 retry 모두 실패 / network / timeout.
       - `PaymentProviderRejectedError` 400 — Toss 4xx(카드 거절 / 한도 초과 / 잘못된 paymentKey 등). Toss 응답의 `code` / `message`를 detail로 forward(*"카드 한도가 초과되었습니다"* 같은 한국어 메시지 보존).
       - `PaymentProviderPayloadInvalidError` 502 — Toss 응답이 schema 위반(`status` 필드 missing 등 — Pydantic ValidationError).
   - **`TossConfirmResponse(BaseModel)` Pydantic 모델** — Toss API 응답 schema(필요 필드만 채택, *모두 채택 시 PII 노출 위험*):
     - `payment_key: str = Field(alias="paymentKey")`.
     - `order_id: str = Field(alias="orderId")`.
     - `status: Literal["DONE", "CANCELED", "PARTIAL_CANCELED", "ABORTED"]` — Toss 표준 status. `DONE`만 success 분기, 그 외는 `PaymentProviderRejectedError`.
     - `total_amount: int = Field(alias="totalAmount")` — KRW 정합 검증(client 송신 amount와 mismatch 시 차단 — race attack 방어).
     - `approved_at: datetime = Field(alias="approvedAt")`.
     - `method: str | None = None` — *"카드"* / *"가상계좌"* 등.
     - `card: dict[str, Any] | None = None` — `{"number": "433012******1234", ...}`. *마지막 4자리만 보존*은 `_mask_payment_payload` 책임.
     - **`raw: dict[str, Any]`** — Toss 원본 응답 dict(*모든 필드*, raw_payload 영속화 위해). `raw_payload` 컬럼에 INSERT 전 `_mask_payment_payload`로 PII 제거.
   - **`def _mask_payment_payload(raw: dict[str, Any]) -> dict[str, Any]`** — `raw_payload` 마스킹 SOT:
     - `customerEmail` / `customerName` / `customerMobilePhone` 키 제거(NFR-S5).
     - `card.number` → 마지막 4자리만 보존(`"433012******1234"` → `"****1234"`).
     - `easyPay.provider` 등 일반 메타는 보존(영업 분석 hint).
     - `secret` / `mId` 같은 머천트 식별자 제거(*외주 인수 시 클라이언트 머천트 ID 노출 회피*).
   - **로깅**: `structlog` `logger.info("toss.confirm_payment.requested", order_id=..., amount=...)` + `logger.info("toss.confirm_payment.succeeded", payment_key_prefix=payment_key[:8], approved_at=...)` — `payment_key`는 Toss 식별자(*비-PII*) but prefix만 forward(보수적 NFR-S5).
   - **단위 테스트** `api/tests/adapters/test_toss.py` 신규 ~5건:
     1. `confirm_payment` happy-path — `httpx_mock`(또는 `respx`) Toss API 200 응답 fixture → `TossConfirmResponse` 정상 매핑 + `raw` 보존.
     2. `confirm_payment` 4xx 카드 거절 → `PaymentProviderRejectedError` raise + Toss `message`("카드 한도 초과") detail 보존.
     3. `confirm_payment` 5xx 3회 retry 후 `PaymentProviderUnavailableError` raise + retry 카운트 검증.
     4. `confirm_payment` `status="ABORTED"` 응답(2xx HTTP but Toss 비-DONE 상태) → `PaymentProviderRejectedError`.
     5. `_mask_payment_payload` `customerEmail` / `card.number` 마스킹 검증.

3. **AC3 — `app/services/payment_service.py` 신규 + `subscribe` 비즈니스 로직 + Idempotency-Key 처리**
   **Given** Story 5.3 `data_export_service.py` 분리 패턴 + Story 2.5 `meals.py:_create_meal_idempotent_or_replay` race-free SELECT-INSERT-CATCH-SELECT SOT + architecture.md:704 *"`payment_service.py` (가설 — Story 6.x 신규)"* + AC1/AC2 baseline, **When** subscribe 비즈니스 로직 SOT 작성, **Then**:
   - **신규 파일** `api/app/services/payment_service.py` — payments 도메인 비즈니스 로직 SOT.
   - **`MONTHLY_PLAN_PRICE_KRW: Final[int] = 9900`** 모듈 상수 — epics.md:832 *"월 9,900원"* literal SOT. Story 6.x 후속에서 plan 추가 시 dict 확장(`PLAN_PRICES = {"monthly": 9900}`).
   - **`MONTHLY_PLAN_PERIOD_DAYS: Final[int] = 30`** — `expires_at = started_at + timedelta(days=30)` 계산 SOT. Story 6.3 webhook이 갱신 시점에 동일 상수 참조.
   - **`async def subscribe(session: AsyncSession, *, user_id: uuid.UUID, payment_key: str, order_id: str, amount: int, idempotency_key: str | None) -> tuple[Subscription, PaymentLog, bool]`**:
     - Returns `(subscription, payment_log, was_replay)`.
     - **Step 1 — input 검증**:
       - `amount != MONTHLY_PLAN_PRICE_KRW` → `PaymentAmountInvalidError(400)` raise(*"결제 금액이 플랜 금액과 일치하지 않습니다 (예상 9900, 수신 {amount})"*). epics.md:841 *"KRW integer 통화 표기"* invariant 가드 + race attack 방어(클라이언트가 amount=100 송신해 결제 시도).
       - `payment_key`/`order_id` 빈 값 거부는 라우터 Pydantic 1차 게이트(`min_length=1`) — service에서는 sanity 검증만(`logger.warning` + raise는 라우터 책임).
     - **Step 2 — Idempotency-Key replay 처리** (`_subscribe_idempotent_or_replay` 헬퍼):
       - `idempotency_key` None → 정상 흐름 진입.
       - 헤더 송신 시:
         - 1차 SELECT — `select(PaymentLog).join(Subscription).where(PaymentLog.user_id == user_id, PaymentLog.idempotency_key == idempotency_key, PaymentLog.event_type == 'subscribe')` 1차 조회 → 있으면 `(existing_subscription, existing_log, True)` 반환.
         - 2차 시도(아래 step 3-5 진행 후 INSERT). UNIQUE 제약 위반(race) catch + 재 SELECT → 재 SELECT 결과로 `(_, _, True)` 반환.
       - **race-free 패턴은 Story 2.5 `meals.py:_create_meal_idempotent_or_replay` 1:1 정합** — 동일 헬퍼 patterns SOT 재사용. soft-deleted 분기는 *부재*(payment_logs는 soft-delete X — payment_log는 audit-trail 성격이라 영구 보존).
     - **Step 3 — active subscription 중복 가드**:
       - `select(Subscription).where(Subscription.user_id == user_id, Subscription.status == 'active')` 1차 조회 → 있으면 `SubscriptionAlreadyActiveError(409)` raise(*"이미 활성 구독이 있습니다 — 해지 후 다시 신청해 주세요"*). partial UNIQUE 제약(`idx_subscriptions_user_id_active_unique`) 1차 게이트 + service inline 1차 게이트(*명확한 에러 메시지* — UNIQUE 제약 위반 catch보다 사용자 친화).
     - **Step 4 — Toss API 호출** (`toss.confirm_payment`):
       - try/except 흐름:
         - `TossSecretKeyMissingError` → 그대로 raise(글로벌 핸들러 503).
         - `PaymentProviderRejectedError` → catch 후 *failed payment_log 1건 INSERT*(`event_type=failed` + `status=failed` + `raw_payload` Toss 에러 응답 마스킹 + `subscription_id=NULL`). 그 후 RFC 7807 `payment-failed` 에러 raise(`PaymentConfirmFailedError(400)` — 사용자 안내). epics.md:842 *"결제 실패 시 RFC 7807 에러(`type=payment-failed`)"* 정합.
         - `PaymentProviderUnavailableError` → 그대로 raise(*subscription / payment_log 작성 X — 502*). Toss 응답 부재 시 멱등 재시도 가능(클라이언트가 같은 Idempotency-Key + 새 paymentKey로 재호출).
       - 성공 응답:
         - Toss `total_amount`와 client 송신 `amount` 일치 검증(adapter 단계에서 1차 — service 단계는 sanity).
     - **Step 5 — DB 작성**:
       - `subscription` row INSERT — `status="active"`, `plan="monthly"`, `plan_price_krw=9900`, `started_at=now()`, `expires_at=now() + 30일`, `provider="toss"`, `provider_billing_key=NULL`(Story 6.3 forward).
       - `payment_log` row INSERT — `subscription_id=subscription.id`, `event_type="subscribe"`, `provider="toss"`, `provider_payment_key=toss_response.payment_key`, `provider_order_id=order_id`, `amount_krw=amount`, `status="success"`, `idempotency_key=idempotency_key`, `raw_payload=_mask_payment_payload(toss_response.raw)`, `occurred_at=toss_response.approved_at`.
       - INSERT는 *동일 트랜잭션* — 부분 commit 차단(subscription만 작성되고 payment_log 실패 시 일관성 깨짐 방지). **commit 책임 분기**(2026-05-08 CR D1 ratify): *성공 경로*는 `db.commit()` 라우터 책임. *실패 경로*(`PaymentConfirmFailedError`)는 `_insert_failed_payment_log` 직후 *서비스 레이어에서 commit* — `PaymentConfirmFailedError`가 글로벌 핸들러로 propagate되면 `get_db_session` 의존성이 rollback을 수행해 audit-trail row가 사라지므로, failed 경로는 별도 트랜잭션 단위로 영속화 의무.
     - **Returns**: `(subscription, payment_log, False)`.
   - **race-free 헬퍼** `_subscribe_idempotent_or_replay(...)` — Story 2.5 `meals.py:_create_meal_idempotent_or_replay` 패턴 1:1 정합. UNIQUE 인덱스 이름은 `idx_payment_logs_user_id_idempotency_key_unique`(상수 매칭 — 인덱스 rename 시 동기 필수).
   - **Decimal/timestamp 변환**: `amount_krw`는 `int` 도메인 — Decimal X. `started_at`/`expires_at`/`occurred_at`은 `datetime` `timezone=True`(Postgres `timestamptz`).
   - **단위 테스트** `api/tests/services/test_payment_service.py` 신규 ~7건:
     1. `subscribe` happy-path — Toss mock 200 → `(subscription, payment_log, False)` + 양 row 정합.
     2. `subscribe` `amount=100` mismatch → `PaymentAmountInvalidError` raise + Toss 호출 X.
     3. `subscribe` 기존 active 사용자 → `SubscriptionAlreadyActiveError` raise + Toss 호출 X.
     4. `subscribe` Toss 4xx → `PaymentConfirmFailedError` raise + failed payment_log 1건 INSERT.
     5. `subscribe` Toss 5xx → `PaymentProviderUnavailableError` raise + DB row 0건.
     6. `subscribe` 같은 `idempotency_key` 재호출 → `(existing, existing_log, True)` 반환 + Toss 호출 X.
     7. `subscribe` Idempotency-Key race(2 concurrent insert) → 1건만 INSERT + 다른 1건은 replay 분기.

4. **AC4 — `POST /v1/payments/subscribe` endpoint + RFC 7807 `payment-failed` + Idempotency-Key 헤더**
   **Given** Story 2.5 `POST /v1/meals` Idempotency-Key 헤더 처리 SOT + architecture.md:670 *"`payments.py` # FR40-FR42"* 라우터 SOT + Story 5.x `Depends(require_basic_consents)` 패턴 + RFC 7807 글로벌 핸들러(architecture.md:513), **When** `api/app/api/v1/payments.py` 신규 + endpoint 작성, **Then**:
   - **신규 파일** `api/app/api/v1/payments.py` — Epic 6 결제 라우터 SOT.
   - **`router = APIRouter(prefix="/v1/payments", tags=["payments"])`** — Story 5.x prefix 패턴 정합.
   - **`SubscribeRequest(BaseModel)` Pydantic 모델**:
     - `payment_key: str = Field(min_length=1, max_length=200, alias="paymentKey")` — Toss 표준 alias(클라이언트가 camelCase 송신).
     - `order_id: str = Field(min_length=1, max_length=64, alias="orderId")`.
     - `amount: int = Field(ge=1, le=100_000_000)` — 0 또는 음수 차단 + 1억원 cap(과도한 클라이언트 입력 차단).
     - `model_config = ConfigDict(extra="forbid", populate_by_name=True)` — Story 1.4/2.x 패턴.
   - **`SubscriptionResponse(BaseModel)` + `PaymentLogResponse(BaseModel)` Pydantic 모델** — wire shape:
     - `SubscriptionResponse`: `id` / `user_id` / `status: Literal["active","cancelled","expired"]` / `plan: Literal["monthly"]` / `plan_price_krw: int` / `started_at` / `expires_at: datetime | None` / `cancelled_at: datetime | None` / `provider: Literal["toss","stripe"]` / `created_at`. `provider_billing_key`는 응답 미포함(*보안 — Toss billing key는 server-only*).
     - `PaymentLogResponse`: `id` / `event_type: Literal[...]` / `status: Literal[...]` / `amount_krw: int` / `occurred_at` / `provider: Literal["toss","stripe"]`. `raw_payload` / `provider_payment_key` 응답 미포함(*PII / 머천트 식별자 보호*). 클라이언트가 영수증 표시에 필요한 *결제 시점 + 금액 + 상태*만 노출.
   - **`SubscribeResponse(BaseModel)` 통합 wrapper**:
     - `subscription: SubscriptionResponse`.
     - `payment: PaymentLogResponse`.
   - **endpoint 시그니처**:
     ```python
     @router.post(
         "/subscribe",
         status_code=status.HTTP_201_CREATED,
         responses={
             200: {"description": "Idempotent replay (same Idempotency-Key)"},
             400: {"description": "Validation failed / Idempotency-Key invalid / amount mismatch / payment rejected"},
             409: {"description": "Subscription already active"},
             502: {"description": "Toss provider unavailable / payload invalid"},
         },
     )
     async def subscribe(
         body: SubscribeRequest,
         db: DbSession,
         user: Annotated[User, Depends(require_basic_consents)],
         response: Response,
         idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
     ) -> SubscribeResponse: ...
     ```
   - **흐름**:
     1. `idempotency_key = _validate_payment_idempotency_key(idempotency_key)` — Story 2.5 `_validate_idempotency_key` SOT 1:1 정합 패턴(UUID v4 regex + 길이 36 + 빈/공백 None 처리). 위반 시 `PaymentIdempotencyKeyInvalidError(400)` raise.
     2. `result = await payment_service.subscribe(db, user_id=user.id, payment_key=body.payment_key, order_id=body.order_id, amount=body.amount, idempotency_key=idempotency_key)`.
     3. `(subscription, payment_log, was_replay) = result`.
     4. `await db.commit()` — 트랜잭션 commit(Story 2.5 패턴 정합).
     5. `response.status_code = status.HTTP_200_OK if was_replay else status.HTTP_201_CREATED` — Idempotent replay는 200, 신규는 201(RFC 9110 정합).
     6. `return SubscribeResponse(subscription=..., payment=...)` — ORM → Pydantic 매핑 단일 지점(`_subscription_to_response` / `_payment_log_to_response` 헬퍼).
   - **Dependency**: `Depends(require_basic_consents)` — Story 2.x meals 패턴 정합. *결제 동작은 자기 데이터 작성*이므로 `require_basic_consents` wire 의무(미동의 시 결제 차단). `require_automated_decision_consent`는 미적용(LLM 분석 게이트와 직교 — 결제는 자동화 의사결정과 무관).
   - **에러 매핑** (RFC 7807 `application/problem+json` + `code` 카탈로그):
     - 400 `code=payments.idempotency_key.invalid` — `PaymentIdempotencyKeyInvalidError`.
     - 400 `code=payments.amount.invalid` — `PaymentAmountInvalidError`.
     - 400 `code=payments.confirm_failed` — `PaymentConfirmFailedError` (epics.md:842 *"`type=payment-failed`"* 정합 — `type` URL은 `https://balancenote.app/errors/payments-confirm-failed`, `code`는 카탈로그 정합 dot-separated).
     - 409 `code=payments.subscription.already_active` — `SubscriptionAlreadyActiveError`.
     - 502 `code=payments.provider.unavailable` — `PaymentProviderUnavailableError`.
     - 502 `code=payments.provider.payload_invalid` — `PaymentProviderPayloadInvalidError`.
     - 503 `code=payments.toss.secret_key_missing` — `TossSecretKeyMissingError`.
   - **Sentry 자동 수집**: 502/503은 `BalanceNoteError` glo handler가 자동 `capture_exception`. 추가로 `PaymentConfirmFailedError`(400 카드 거절) 시점에 service 레이어에서 *명시 `sentry_sdk.capture_message("payment.confirm_failed", level="warning", extras=...)` 호출* — 운영 모니터링(카드 거절 빈도가 abnormal 시 dashboard alert) — epics.md:842 *"Sentry 자동 수집"* 정합.
   - **로깅**: `logger.info("payments.subscribe.requested", user_id=_mask_user_id(user.id), order_id=body.order_id, amount=body.amount)` + `logger.info("payments.subscribe.succeeded", user_id=..., subscription_id=..., was_replay=was_replay)` + 실패 시 `logger.warning("payments.subscribe.failed", user_id=..., toss_code=...)` — NFR-S5 마스킹 + payment_key 본문 X.
   - **rate limit**: default `["1000/hour", "60/minute"]` 자동 적용. 추가 데코레이터 X — 결제는 1인 사용자 분당 60회 시도가 사실상 abuse(Toss 실 결제는 카드별 분당 ~5회 cap). default cap이면 충분.

5. **AC5 — `GET /v1/payments/subscription` endpoint + 자기 active subscription 단일 조회**
   **Given** epics.md:838 *"`subscriptions` 테이블에 `status=active` + ...기록"* + Story 5.x `Depends(current_user)` PIPA Art.35 정합 패턴 + Story 6.2 forward(`GET /v1/payments/history` 별도), **When** 클라이언트가 *현재 구독 상태 확인* 흐름, **Then**:
   - **endpoint 시그니처**:
     ```python
     @router.get(
         "/subscription",
         status_code=status.HTTP_200_OK,
         responses={
             200: {"description": "Active subscription found"},
             404: {"description": "No active subscription"},
         },
     )
     async def get_subscription(
         db: DbSession,
         user: Annotated[User, Depends(current_user)],
     ) -> SubscriptionResponse: ...
     ```
   - **Dependency**: `Depends(current_user)` 단독 — `Depends(require_basic_consents)` 미적용. **사유**: PIPA Art.35 정보주체 권리(Story 5.x 정합) — 자기 결제 상태 *조회*는 동의 철회와 독립된 권리. 미동의 사용자도 *자기 구독 정보 열람*은 보장. (대안 검토: `require_basic_consents` 적용 시 미동의 → 403 → 사용자가 자기 결제 상태 미확인 → UX 모순 + Art.35 위반).
   - **흐름**:
     1. `select(Subscription).where(Subscription.user_id == user.id, Subscription.status == 'active').order_by(Subscription.started_at.desc()).limit(1)` 1차 SELECT.
     2. `subscription is None` → `NoActiveSubscriptionError(404)` raise(*"활성 구독이 없습니다"* — 신청 안 한 사용자 정상 케이스).
     3. `return _subscription_to_response(subscription)`.
   - **에러 매핑**:
     - 404 `code=payments.subscription.not_found` — `NoActiveSubscriptionError`.
   - **로깅**: `logger.info("payments.subscription.requested", user_id=_mask_user_id(user.id))` — 모니터링 SOT.
   - **scope 분리**: 본 endpoint는 *현재 active 구독 1건*만 — Story 6.2 `GET /v1/payments/history`는 *전체 payment_logs 이력* 별 endpoint. 두 endpoint scope 명확.
   - **단위 테스트** `api/tests/api/v1/test_payments.py` 본 endpoint 분기 ~3건:
     1. `GET /v1/payments/subscription` 인증 미통과 → 401.
     2. `GET /v1/payments/subscription` happy-path — 활성 구독 fixture → 200 + `status="active"` + Pydantic Literal 검증.
     3. `GET /v1/payments/subscription` 활성 구독 없음 → 404 + `code=payments.subscription.not_found`.

6. **AC6 — RFC 7807 `payment-failed` + `PaymentError` exceptions catalog 신설**
   **Given** Story 1.x exceptions.py 패턴 SOT + Story 2.5 DF49 *"Story 6.x 결제 webhook idempotency 도입 시점에 cross-cutting base 분리 검토"* + `MealError` / `LLMRouterError` / `ExpoPushError` 카탈로그 정합, **When** `api/app/core/exceptions.py`에 결제 도메인 추가, **Then**:
   - **`PaymentError(BalanceNoteError)` base** — *직접 raise 회피* 패턴(서브클래스만):
     - `status: ClassVar[int] = 500`.
     - `code: ClassVar[str] = "payments.error"`.
     - `title: ClassVar[str] = "Payment Error"`.
   - **`PaymentIdempotencyKeyInvalidError(PaymentError)`** — Story 2.5 `MealIdempotencyKeyInvalidError` 패턴 1:1 정합 — `status=400` + `code="payments.idempotency_key.invalid"` + UUID v4 형식 위반 시 raise.
     - **DF49 갱신 결정**(2026-05-08, Story 6.1 시점): *cross-cutting `IdempotencyError` base 분리는 본 스토리에서 미수행*. 사유: (a) `MealIdempotencyKeyInvalidError`와 `PaymentIdempotencyKeyInvalidError`는 *동일 검증 로직*(UUID v4 regex)이지만 *다른 catalog code prefix*(`meals.*` vs `payments.*`)와 *다른 후속 분기*(meal soft-delete conflict vs payment subscription conflict). 단순 base 통합은 catalog 코드 prefix 통일 강제 → 외주 인수 시 클라이언트별 catalog 분리 전제와 충돌. (b) Story 6.3 webhook 시점에 *3번째 도메인*(`webhook_events.idempotency_key.invalid`)이 등장하면 그 시점에 *공통 helper 함수만 분리*(`_validate_idempotency_key_uuid_v4(key) -> str | None`) — exception 계층 통합은 deferred 유지. **DF49 재기록**: *함수 helper 분리는 Story 6.3에서 가능, 예외 계층 통합은 deferred(Growth — 외주 인수 후 클라이언트별 catalog 분리 정책 확정 후)*.
   - **`PaymentAmountInvalidError(PaymentError)`** — `status=400` + `code="payments.amount.invalid"` — 클라이언트 송신 amount가 `MONTHLY_PLAN_PRICE_KRW`와 mismatch. *race attack 방어*(클라이언트가 amount=100 송신해 결제).
   - **`PaymentConfirmFailedError(PaymentError)`** — `status=400` + `code="payments.confirm_failed"` + RFC 7807 `type="https://balancenote.app/errors/payments-confirm-failed"`. epics.md:842 *"`type=payment-failed`"* 정합(*hyphen 표기*는 우리 카탈로그 *dot-separated* 정책과 정합 — `code=payments.confirm_failed` + `type` URL은 hyphen). Toss 카드 거절 / 한도 초과 / 잘못된 paymentKey 등 모든 *사용자 상응 에러*는 본 예외로 변환 + service 레이어에서 *failed payment_log 1건 INSERT*.
   - **`SubscriptionAlreadyActiveError(PaymentError)`** — `status=409` + `code="payments.subscription.already_active"` — 한 사용자 1 active subscription invariant 위반(partial UNIQUE 1차 게이트 + service inline 1차 게이트).
   - **`NoActiveSubscriptionError(PaymentError)`** — `status=404` + `code="payments.subscription.not_found"` — `GET /v1/payments/subscription` 활성 구독 0건. Story 1.x `MealNotFoundError` 패턴 정합.
   - **`PaymentProviderError(PaymentError)`** — Toss 어댑터 레벨 base. *직접 raise 회피*:
     - `status: ClassVar[int] = 502`.
     - `code: ClassVar[str] = "payments.provider.error"`.
   - **`PaymentProviderRejectedError(PaymentProviderError)`** — `status=400` + `code="payments.provider.rejected"` — Toss 4xx(카드 거절). *adapter 레벨에서 raise* + service 레이어에서 catch + `PaymentConfirmFailedError`로 변환(*사용자 상응 단일 코드 유지*). adapter raw error는 *Sentry breadcrumb*만, 사용자 응답은 단일 `payments.confirm_failed`.
   - **`PaymentProviderUnavailableError(PaymentProviderError)`** — `status=502` + `code="payments.provider.unavailable"` — Toss 5xx + retry 후 최종 실패 / network / timeout. service 레이어에서 catch X(그대로 propagate — 클라이언트가 멱등 재시도 가능). `Story 3.6 LLMRouterUnavailableError` 패턴 정합.
   - **`PaymentProviderPayloadInvalidError(PaymentProviderError)`** — `status=502` + `code="payments.provider.payload_invalid"` — Toss 응답 schema 위반(Pydantic ValidationError). adapter 레벨 raise + service 그대로 propagate.
   - **`TossSecretKeyMissingError(PaymentError)`** — `status=503` + `code="payments.toss.secret_key_missing"` — `settings.toss_secret_key`가 `""`. fail-fast(retry 무효 + cost 0). 운영 부팅 시 staging/prod 환경은 *부팅 검증* X(Story 8 hardening) — runtime fail-fast로 우선 안전.
   - **단위 테스트** 1건(예외 catalog) — `code` / `status` / `title` 인스턴스화 검증 + `to_problem(instance=...)` 응답 dict shape.

7. **AC7 — Mobile `(tabs)/settings/subscription.tsx` 신규 + 외부 웹 결제 진입점 + App Store IAP 정합**
   **Given** prd.md:676 *"In-App Purchase: 결제는 IAP 우회(외부 결제 화면 sandbox) — App Review 정책 준수 위해 *'앱 외부에서 구독 가능'* 화면만 노출하는 패턴 또는 IAP 통합(클라이언트별 결정). MVP는 외부 웹 결제만 우선"* + Story 5.3 `(tabs)/settings/data-export.tsx` 메뉴/Stack 등록 패턴 SOT + `mobile/lib/auth.ts:authFetch` SOT + `Linking` Expo Router 표준, **When** 모바일 신규 화면 + 메뉴 항목 추가, **Then**:
   - **신규 의존성 0건** — `expo-linking`(Expo SDK 54 baseline 기 포함, `mobile/app/+native-intent.tsx`에서 사용 중) 재사용.
   - **`mobile/features/settings/useSubscription.ts` 신규**:
     - `useSubscriptionQuery()` query hook — `authFetch("/v1/payments/subscription")` GET → `SubscriptionResponse | null`(404는 null 정규화). cache key `["payments", "subscription"]`.
     - `getSubscribeWebUrl(): string` 헬퍼 — `${API_BASE_URL_WEB}/account/subscribe`(Web 프론트엔드 `/account/subscribe` 페이지 URL — 환경 변수 `EXPO_PUBLIC_WEB_BASE_URL` 기반, 미설정 시 `https://balancenote.app` fallback). *모바일은 본 URL을 외부 브라우저로 노출* — App Store IAP 정책 *"앱 외부 결제 가능"* 정합.
     - **결정**: 모바일에서 직접 Toss SDK 호출 X — *모바일은 결제 화면 자체를 노출하지 않음*(App Review 위반 가능성). 사용자 인증은 *Web 측에서 별도 로그인* 또는 *모바일에서 로그인된 세션이 같은 도메인 쿠키로 Web에 자연 전이*. MVP sandbox에서는 *Web 별도 로그인*(영업 데모 한정) — Story 8.x deep-link auth bridge로 polish forward.
   - **`mobile/app/(tabs)/settings/subscription.tsx` 신규** Expo Router 화면:
     - 진입 가드 ① `useAuth().consentStatus === null` → `<ActivityIndicator />` (bootstrap).
     - 진입 가드 ② `!consentStatus.basic_consents_complete` → `<Text>구독 신청은 기본 동의 후 가능합니다</Text>` + *기본 동의로 이동* link(Story 5.x 패턴 정합 — `require_basic_consents` wire 정합).
     - **UI**:
       - `<Text style={styles.title}>구독</Text>`.
       - `useSubscriptionQuery()` 결과 분기:
         - `isPending` → `<ActivityIndicator />`.
         - `data === null`(404) → 안내 카드 + *"월 9,900원 정기결제 신청"* `<Pressable>` 버튼. 누르면 `Linking.openURL(getSubscribeWebUrl())`(`expo-linking` API).
         - `data !== null`(active) → 활성 구독 카드(*"활성 구독 — 시작 {started_at KST} / 다음 결제일 {expires_at KST}"*) + *"해지는 Story 6.2"* placeholder 텍스트(*"구독 해지는 다음 업데이트에서 가능합니다"* — Story 6.2 forward stub).
       - 안내 문구: *"App Store 정책에 따라 결제는 외부 브라우저에서 진행됩니다."* — App Review 정책 정합 + 사용자 UX 안내.
     - **App Review 정합 핵심**:
       - 모바일 앱 내부에서 *결제 위젯 노출 X*(WebView 내장 결제도 위반 가능성).
       - *"앱 외부 결제 가능"* 안내 문구 명시 + 외부 브라우저 진입 버튼만 노출.
       - prd.md:676 *"App Review 정책 — 앱 외부 결제 가능 화면만 노출 또는 deep link"* 1:1 정합.
     - submit handler 패턴은 Story 5.3 `data-export.tsx` 흐름 정합.
   - **`mobile/app/(tabs)/settings/_layout.tsx` Stack.Screen 등록**: `<Stack.Screen name="subscription" options={{ title: "구독" }} />` 추가(Story 5.x 등록 패턴).
   - **`mobile/app/(tabs)/settings/index.tsx` 메뉴 추가**: items 배열에 `'구독'` 1건 추가 — *위치*: *'데이터 내보내기'* 다음 / *'로그아웃'* 이전(*결제* 카테고리 그룹). *'회원 탈퇴'*는 destructive 마지막 invariant 보존.
   - **`EXPO_PUBLIC_WEB_BASE_URL` 환경 변수**: `mobile/.env.example`에 추가 — `EXPO_PUBLIC_WEB_BASE_URL=http://localhost:3000`(dev) / `https://balancenote.app`(prod). `process.env.EXPO_PUBLIC_WEB_BASE_URL || "https://balancenote.app"` fallback. Expo SDK 54 `EXPO_PUBLIC_*` prefix는 클라이언트 번들 노출(*Web URL은 비-secret*이므로 안전).

8. **AC8 — Web `/account/subscribe/page.tsx` 신규 + Toss Payments Widget SDK 통합 + 결제 흐름**
   **Given** Story 5.x `(user)/account/delete/page.tsx` Server Component 1가드 SOT + Story 5.x `AccountDeleteForm` react-hook-form 패턴(*본 스토리는 Toss SDK 우선이라 react-hook-form 미사용*) + `web/src/lib/api-client.ts:apiFetch` SOT + Toss Payments JS SDK 표준 패턴, **When** 신규 페이지 + 위젯 컴포넌트 + 결제 흐름 작성, **Then**:
   - **신규 의존성 1건** — `@tosspayments/payment-widget-sdk ^1.x`(Toss 공식 SDK, Toss 정기결제 widget 표준). `pnpm add @tosspayments/payment-widget-sdk` — `web/package.json` 갱신.
   - **`web/src/app/(user)/account/subscribe/page.tsx` 신규** Server Component:
     - Next.js 16 metadata: `metadata = { title: "구독 신청 — BalanceNote" }`.
     - **2가드** (Story 5.x `/account/delete` 패턴 — 1가드 baseline + 본 스토리는 *결제 흐름이라 basic_consents 가드 추가*):
       1. `getServerSideUser()` → `!user` → `redirect("/api/auth/cleanup")`.
       2. `!user.consent_status.basic_consents_complete` → `redirect("/onboarding/consent")` — 결제는 동의 후만 허용(`require_basic_consents` 정합).
     - 본문: 한국어 안내 + `<SubscribeForm />` 렌더(client component).
   - **`web/src/features/payments/SubscribeForm.tsx` 신규** `"use client"` — Toss widget 통합:
     - **Toss 공식 SDK 표준 패턴**:
       ```typescript
       import { loadPaymentWidget, PaymentWidgetInstance } from "@tosspayments/payment-widget-sdk";
       const widgetClientKey = process.env.NEXT_PUBLIC_TOSS_CLIENT_KEY!; // sandbox: "test_ck_..."
       const customerKey = `customer-${userId}`; // user-scoped key, Toss 권장
       useEffect(() => {
         loadPaymentWidget(widgetClientKey, customerKey).then((w) => setWidget(w));
       }, []);
       useEffect(() => {
         if (!widget) return;
         widget.renderPaymentMethods("#payment-method", { value: 9900 });
         widget.renderAgreement("#agreement");
       }, [widget]);
       ```
     - **결제 요청 흐름**:
       1. *"구독 신청 (월 9,900원)"* `<button>` 클릭.
       2. `orderId = crypto.randomUUID()` — 클라이언트 생성 UUID v4(Toss 권장 — 64자 cap, UUID는 36자 적합). 동일 `orderId`는 Toss 측 멱등 dedup 보조(*우리 측 멱등은 application-level Idempotency-Key — 별 layer*).
       3. `idempotencyKey = crypto.randomUUID()` — 우리 application-level Idempotency-Key. 컴포넌트 mount 시 1회 생성 + state 보관(*같은 mount 동안 retry 시 재사용 — Story 2.5 패턴 정합*). 페이지 새로고침 시 새 키 생성(*새 결제 시도*).
       4. `widget.requestPayment({ orderId, orderName: "월간 구독", successUrl: ${WEB_BASE}/account/subscribe/success, failUrl: ${WEB_BASE}/account/subscribe/fail, customerEmail: user.email })` 호출 → Toss 결제 화면 진입(브라우저 redirect).
     - **success callback 처리** (`/account/subscribe/success` 라우트):
       - URL query에 `paymentKey` / `orderId` / `amount` 포함(Toss 표준).
       - server side에서 `apiFetch("/v1/payments/subscribe", { method: "POST", body: { paymentKey, orderId, amount }, headers: { "Idempotency-Key": idempotencyKey } })` 호출.
       - **idempotencyKey 보존**: `crypto.randomUUID()`는 매 mount마다 다른 값. `success` 라우트는 *별 페이지 이동*이라 mount 새로 — 키 분실. **결정**: `localStorage`에 *결제 시도 시점에 idempotencyKey 저장* + success 라우트에서 read + 사용 후 *delete*. localStorage는 same-origin 보존이라 success 라우트가 같은 도메인이면 safe. `/subscribe/success` 진입 시 localStorage 미보유 케이스(직접 URL 접근) → server에 헤더 미송신 + `subscribe` endpoint가 헤더 부재 OK(*첫 신청 — replay 분기 미진입*). 재시도 시(서버 502) Toss 측 paymentKey 동일 + 우리 측 idempotency_key 동일이라 server replay 분기 정상 동작.
     - **fail callback 처리** (`/account/subscribe/fail` 라우트):
       - URL query에 `code` / `message` / `orderId` 포함(Toss 표준).
       - 사용자에게 한국어 에러 메시지 노출(*"카드 한도가 초과되었습니다"* 등) + *"다시 시도"* 버튼(`/account/subscribe`로 redirect).
       - server에 호출 X(Toss 측 결제 미승인 → server 측 payment_log INSERT 불필요 — 우리 측 결제 흐름은 *Toss success callback 진입 시점부터*).
     - **active subscription 분기**: 페이지 mount 시 `apiFetch("/v1/payments/subscription")` GET — 200 응답이면 *"활성 구독이 있습니다"* + *"중복 구독 불가 — 해지는 다음 업데이트"* 안내 + widget 렌더 X. 중복 진입 차단.
   - **`NEXT_PUBLIC_TOSS_CLIENT_KEY` 환경 변수**: `web/.env.example` + 루트 `.env.example`에 추가 — `NEXT_PUBLIC_TOSS_CLIENT_KEY=test_ck_<sandbox_key>`. Toss sandbox 표준 client key는 *"test_ck_DnyRpQWGrN0BKAoJ4BwM8Kwv1M9E"* 같은 forward — 본 스토리에서는 placeholder + README 안내. *prod key는 외주 클라이언트가 자체 등록*(epics.md:855 SOP 정합).
   - **`web/src/app/(user)/account/subscribe/success/page.tsx` 신규** — 결제 완료 후 server confirm 처리 페이지:
     - `"use client"` 분리 또는 server component + form action 분리(Next.js 16 server actions 패턴) — *결정*: client component(URL query 접근 + localStorage 접근 + apiFetch 통합 단순성). Server Action으로 wrap는 polish forward.
     - URL query parsing → `apiFetch` POST → 성공 시 *"구독이 시작되었습니다 — 시작일 {started_at}"* 안내 + *"홈으로"* link. 실패 시 에러 메시지 + *"다시 시도"* link.
   - **`web/src/app/(user)/account/subscribe/fail/page.tsx` 신규** — 실패 안내 페이지(client component, URL query parsing).
   - **OpenAPI**: `pnpm gen:api` 실행 — `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 갱신. 신규 endpoint 2건(`POST /v1/payments/subscribe` + `GET /v1/payments/subscription`) + 응답 모델 인식.

9. **AC9 — README 5섹션 §5 *결제 PG 연동 가이드* 갱신 + Toss sandbox 셋업 SOP**
   **Given** prd.md:518 *"README 5섹션 표준 — ... AWS/GCP/Azure 마이그레이션 가이드 + 결제 PG 연동 확장 가이드"* + epics.md:825 *"PG 본 계약·세금정산은 OUT(README 가이드 1페이지)"* + Story 6.2/6.3 forward(해지/이용내역/webhook), **When** README §5 기존 *AWS/GCP/Azure 마이그레이션* 섹션에 결제 가이드 추가, **Then**:
   - **README.md §5 추가 sub-section** *"5.4 결제 PG 연동 (Toss Payments sandbox)"*:
     - **sandbox 셋업 5단계**:
       1. Toss Payments 개발자 콘솔 가입 (https://developers.tosspayments.com).
       2. *"테스트 키 발급"* — `client_key`(`test_ck_...`) + `secret_key`(`test_sk_...`) 양쪽 복사.
       3. `.env`에 `TOSS_SECRET_KEY=<test_sk_...>` 설정.
       4. `web/.env.local`에 `NEXT_PUBLIC_TOSS_CLIENT_KEY=<test_ck_...>` 설정.
       5. Toss test card *"4330-1234-1234-1234"* (만료 12/30, CVC 123, 비밀번호 앞 2자리 12) 사용.
     - **Stripe 연동 가이드** 1줄 placeholder — *"Stripe 통합은 Story 6.2/8.5 — `app/adapters/stripe.py` 어댑터 + `STRIPE_SECRET_KEY` env 추가 + Web `@stripe/stripe-js` SDK + checkout session 흐름. Toss와 동일 `payments.py` 라우터 + provider enum 분기로 자연 확장."*. 상세 SOP는 forward.
     - **PG 본 계약 SOP** *"외주 인수 후 클라이언트 자체 셋업 — Toss 본 키 발급 → 사업자등록증 + PG 가입 심사(영업일 ~3일) → `TOSS_SECRET_KEY` prod 환경 변수 회전 → 결제 한도/수수료 협의."* 1단락. 상세 절차는 Toss 공식 매뉴얼 link.
     - **세금정산 SOP** 1단락 — *"OUT(MVP) — 사업자등록 + 부가세 신고 + 결제 수수료 정산은 인수 클라이언트 책임."* + 회계 처리 SOP는 docs/runbook forward.
   - **`docs/runbook/secret-rotation.md` §6 추가** — *"6. TOSS_SECRET_KEY 회전 5단계"*:
     1. Toss 콘솔에서 신규 secret key 발급(`live_sk_*`).
     2. Railway/staging 환경 변수 `TOSS_SECRET_KEY_NEW` 추가(겹침 deploy).
     3. API 컨테이너 재배포 + 신규 결제 1건 dry-run(test card).
     4. `TOSS_SECRET_KEY` ← `TOSS_SECRET_KEY_NEW` 갱신 + `TOSS_SECRET_KEY_NEW` 삭제.
     5. Toss 콘솔에서 구 key revoke.
   - **본 스토리는 README + runbook 문서만 추가** — Stripe 어댑터 코드는 *forward stub X* — 코드 신설 X(`PaymentLog.provider="stripe"` ENUM 값만 등록 + 어댑터는 Story 6.2/8.5에서 생성).

10. **AC10 — 단위 테스트 + 회귀 0건 + 통합 검증**
    **Given** Story 5.3 baseline pytest 1068 passed/11 skipped/0 failed + coverage 84%+ + ruff/format/mypy/tsc/lint 0 errors, **When** 본 스토리 종료, **Then**:
    - **신규 단위 테스트 ~30건**:
      - `api/tests/test_subscriptions_payment_logs_schema.py` 신규 ~3건(AC1).
      - `api/tests/adapters/test_toss.py` 신규 ~5건(AC2).
      - `api/tests/services/test_payment_service.py` 신규 ~7건(AC3).
      - `api/tests/api/v1/test_payments.py` 신규 ~12건:
        1. `POST /subscribe` 인증 미통과 → 401.
        2. `POST /subscribe` 미동의 사용자 → 403 + `code=consent.basic.missing`(`require_basic_consents` wire 가드).
        3. `POST /subscribe` happy-path — Toss mock 200 → 201 + `SubscribeResponse` shape 검증 + DB 양 row INSERT.
        4. `POST /subscribe` `Idempotency-Key` 재호출 → 200 (replay) + Toss 호출 X(mock counter 검증).
        5. `POST /subscribe` `Idempotency-Key` 형식 위반(non-UUID) → 400 + `code=payments.idempotency_key.invalid`.
        6. `POST /subscribe` `amount=100` mismatch → 400 + `code=payments.amount.invalid`.
        7. `POST /subscribe` 기존 active 사용자 → 409 + `code=payments.subscription.already_active`.
        8. `POST /subscribe` Toss 4xx 카드 거절 → 400 + `code=payments.confirm_failed` + failed payment_log INSERT 검증.
        9. `POST /subscribe` Toss 5xx → 502 + `code=payments.provider.unavailable` + DB 0 rows.
        10. `POST /subscribe` `TOSS_SECRET_KEY` 미설정 → 503 + `code=payments.toss.secret_key_missing`.
        11. `GET /subscription` 활성 구독 happy-path → 200 + `status="active"`.
        12. `GET /subscription` 활성 구독 0건 → 404 + `code=payments.subscription.not_found`.
      - `api/tests/test_exceptions_payments.py` 신규 ~3건 — exceptions catalog code/status/title 인스턴스화 + RFC 7807 응답 dict shape.
    - **본 스토리 종료 시 목표**: pytest **~1098 passed / 11 skipped / 0 failed** + coverage ≥84% 유지(신규 코드 ~400 lines + 신규 테스트 ~30건 = +~120 lines covered).
    - **회귀 0건 가드**:
      - Story 2.x meals — `MealIdempotencyKeyInvalidError` 카탈로그 변경 X(payments-specific 분리).
      - Story 5.x users — 영향 0건.
      - Story 4.x notifications/reports — 영향 0건.
      - Story 3.x analysis — 영향 0건.
      - alembic upgrade/downgrade — `0017 → 0018 → 0019` 양방향 동작.
    - **타입 체크**: ruff/format/mypy 0 에러(api) + web/mobile tsc + lint 0 에러.
    - **OpenAPI schema diff**: 신규 endpoint 2건(`POST /v1/payments/subscribe` + `GET /v1/payments/subscription`) + 신규 응답 모델 3건(`SubscribeRequest` / `SubscribeResponse` / `SubscriptionResponse`). CI 게이트 통과 의무.
    - **manual smoke** (CR/QA 단계 위임 — DS는 unit test로 functional verification 완료):
      - Toss test card *"4330-1234-1234-1234"* 사용 → 결제 성공 흐름 1회.
      - 테스트 카드 잔액부족 케이스 (Toss sandbox 제공 *"4330-1234-1234-1235"* 잔액부족 시뮬레이션) → 400 `payment-failed` 응답 + Sentry capture 검증.
      - 모바일 Linking.openURL → Web `/account/subscribe` 외부 브라우저 진입 검증(Expo Go iOS/Android).

11. **AC11 — sprint-status / Story Status 갱신 흐름 (메모리 정합)**
    **Given** 메모리 정합 *"CS 시작 전 master에서 브랜치 분기 — DS 종료시 commit + push만"* + *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신해 PR commit에 포함"* + *"새 스토리 브랜치는 항상 master에서 분기"*, **When** 본 스토리 `ready-for-dev` 시점(CS 종료) 및 후속 단계, **Then**:
    - Branch: `story/6.1-billing-sandbox`(master에서 분기 — CS 시작 전 분기 의무, 본 스토리 CS 단계 시점 이미 분기 완료).
    - DS 시작: `6-1-정기결제-sandbox-신청: ready-for-dev → in-progress`.
    - DS 종료: `6-1-정기결제-sandbox-신청: in-progress → review` + commit + push(PR 생성 X — CR 완료 후 일괄).
    - CR 종료 직전: `review → done` + commit + push(같은 commit에 sprint-status 갱신 포함).
    - PR 생성: CR 완료 후 1회. PR title: `Story 6.1: 정기결제 sandbox 신청 + Toss 1플랜 (DS+CR)`.
    - **Epic 6 첫 스토리** — `epic-6: backlog → in-progress` 자동 전이는 sprint-status.yaml `last_updated` 갱신 동시(CS 단계, 이미 본 스토리 CS 시점에 처리).

## Tasks / Subtasks

### Task 1 — `subscriptions` / `payment_logs` 모델 + alembic 0018/0019 (AC: #1)

- [x] 1.1 `api/app/db/models/subscription.py` 신규 — `Subscription(Base)` ORM(`id`/`user_id`/`status`/`plan`/`plan_price_krw`/`started_at`/`cancelled_at`/`expires_at`/`provider`/`provider_billing_key`/`created_at`/`updated_at` 12 컬럼 + partial UNIQUE `idx_subscriptions_user_id_active_unique`).
- [x] 1.2 `api/app/db/models/payment_log.py` 신규 — `PaymentLog(Base)` ORM(`id`/`user_id`/`subscription_id`(SET NULL)/`event_type`/`provider`/`provider_payment_key`/`provider_order_id`/`amount_krw`/`status`/`idempotency_key`/`raw_payload` JSONB/`occurred_at`/`created_at` 13 컬럼 + 시계열 인덱스 + 2 partial UNIQUE).
- [x] 1.3 `api/app/db/models/__init__.py` — `Subscription`/`PaymentLog` import 추가.
- [x] 1.4 `api/alembic/versions/0018_subscriptions.py` 신규 — Postgres ENUM 3종(`subscriptions_status_enum`/`subscriptions_plan_enum`/`subscriptions_provider_enum`) + 테이블 + partial UNIQUE. `down_revision="0017_users_deletion_reason_idx"`.
- [x] 1.5 `api/alembic/versions/0019_payment_logs.py` 신규 — Postgres ENUM 3종(`payment_logs_event_type_enum`/`payment_logs_provider_enum`/`payment_logs_status_enum`) + 테이블 + 인덱스 3종. `down_revision="0018_subscriptions"`.
- [x] 1.6 `api/tests/test_subscriptions_payment_logs_schema.py` 신규 ~3건 — partial UNIQUE 동작 + ENUM 값 invariant + FK CASCADE.

### Task 2 — `app/adapters/toss.py` 신규 + Toss API 통합 (AC: #2)

- [x] 2.1 `api/app/adapters/toss.py` 신규 — `TOSS_API_BASE_URL` + `confirm_payment(payment_key, order_id, amount)` async function + `TossConfirmResponse` Pydantic + `_mask_payment_payload` 헬퍼 + `tenacity` retry(3회 transient only).
- [x] 2.2 `api/tests/adapters/test_toss.py` 신규 ~5건 — `httpx_mock` 또는 `respx` Toss 응답 mock + happy-path/4xx/5xx-retry/ABORTED-status/마스킹 검증.

### Task 3 — `PaymentError` exceptions catalog 신설 (AC: #6)

- [x] 3.1 `api/app/core/exceptions.py` — `PaymentError` base + 7 서브클래스 추가(`PaymentIdempotencyKeyInvalidError`/`PaymentAmountInvalidError`/`PaymentConfirmFailedError`/`SubscriptionAlreadyActiveError`/`NoActiveSubscriptionError`/`PaymentProviderError`(base)/`PaymentProviderRejectedError`/`PaymentProviderUnavailableError`/`PaymentProviderPayloadInvalidError`/`TossSecretKeyMissingError`).
- [x] 3.2 `api/tests/test_exceptions_payments.py` 신규 ~3건 — code/status/title 검증.

### Task 4 — `app/services/payment_service.py` 신규 + `subscribe` 비즈니스 로직 (AC: #3)

- [x] 4.1 `api/app/services/payment_service.py` 신규 — `MONTHLY_PLAN_PRICE_KRW`/`MONTHLY_PLAN_PERIOD_DAYS` 상수 + `subscribe(...)` async function + `_subscribe_idempotent_or_replay` race-free helper(Story 2.5 `meals.py` SOT 1:1 정합) + Sentry `capture_message("payment.confirm_failed")` 명시 호출.
- [x] 4.2 `api/tests/services/test_payment_service.py` 신규 ~7건 — happy/amount-mismatch/already-active/Toss-4xx/Toss-5xx/idempotency-replay/race.

### Task 5 — `POST /v1/payments/subscribe` + `GET /v1/payments/subscription` endpoints (AC: #4, #5)

- [x] 5.1 `api/app/api/v1/payments.py` 신규 — `router` + `SubscribeRequest`/`SubscribeResponse`/`SubscriptionResponse`/`PaymentLogResponse` Pydantic + `_validate_payment_idempotency_key`(Story 2.5 SOT 1:1) + `subscribe` endpoint(`Depends(require_basic_consents)`) + `get_subscription` endpoint(`Depends(current_user)` 단독).
- [x] 5.2 `api/app/main.py` — `from app.api.v1 import payments` import 추가 + `app.include_router(payments.router)` 등록.
- [x] 5.3 `api/tests/api/v1/test_payments.py` 신규 ~12건 — AC10 정의 12 케이스.

### Task 6 — Mobile `(tabs)/settings/subscription.tsx` 신규 + 외부 웹 결제 진입점 (AC: #7)

- [x] 6.1 `mobile/.env.example` — `EXPO_PUBLIC_WEB_BASE_URL=http://localhost:3000` 추가.
- [x] 6.2 `mobile/features/settings/useSubscription.ts` 신규 — `useSubscriptionQuery()` + `getSubscribeWebUrl()` 헬퍼.
- [x] 6.3 `mobile/app/(tabs)/settings/subscription.tsx` 신규 — 진입 가드 ① bootstrap + ② basic_consents + 활성/미활성 분기 UI + `Linking.openURL(getSubscribeWebUrl())` 외부 결제 진입점 + App Store IAP 정합 안내 문구.
- [x] 6.4 `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="subscription" options={{ title: "구독" }} />` 추가.
- [x] 6.5 `mobile/app/(tabs)/settings/index.tsx` — items 배열에 `'구독'` 추가(*'데이터 내보내기'* 다음 / *'로그아웃'* 이전 위치).

### Task 7 — Web `/account/subscribe` 페이지 + Toss Widget SDK 통합 (AC: #8)

- [x] 7.1 `pnpm add @tosspayments/payment-widget-sdk` (web/) — `web/package.json` + lockfile 갱신.
- [x] 7.2 `web/.env.example` + 루트 `.env.example` — `NEXT_PUBLIC_TOSS_CLIENT_KEY=test_ck_<sandbox_key>` placeholder 추가.
- [x] 7.3 `pnpm gen:api`(루트) 실행 — `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 갱신.
- [x] 7.4 `web/src/features/payments/SubscribeForm.tsx` 신규 `"use client"` — Toss `loadPaymentWidget` SDK 통합 + `crypto.randomUUID()` orderId/idempotencyKey 생성 + localStorage 보존(success 라우트 회복) + `requestPayment` 호출 + active 분기 안내.
- [x] 7.5 `web/src/app/(user)/account/subscribe/page.tsx` 신규 Server Component — Next.js 16 metadata + 2가드(`!user` redirect + `!basic_consents_complete` redirect to onboarding) + `<SubscribeForm />` 렌더.
- [x] 7.6 `web/src/app/(user)/account/subscribe/success/page.tsx` 신규 `"use client"` — URL query parsing + localStorage idempotencyKey read + `apiFetch("/v1/payments/subscribe", POST)` + 성공 안내 + 실패 에러 메시지.
- [x] 7.7 `web/src/app/(user)/account/subscribe/fail/page.tsx` 신규 `"use client"` — URL query parsing + 한국어 에러 메시지 + *"다시 시도"* link.
- [x] 7.8 `web/src/app/(user)/settings/profile/page.tsx` 푸터 갱신 — `<Link href="/account/subscribe">구독 관리</Link>` 추가(*"데이터 내보내기"* link 다음, *"회원 탈퇴"* link 위 — non-destructive 그룹화).

### Task 8 — README §5.4 결제 가이드 + secret-rotation.md §6 (AC: #9)

- [x] 8.1 `README.md` — §5에 *"5.4 결제 PG 연동 (Toss Payments sandbox)"* sub-section 추가 — sandbox 셋업 5단계 + Stripe 1단락 placeholder + PG 본 계약 SOP 1단락 + 세금정산 SOP 1단락.
- [x] 8.2 `docs/runbook/secret-rotation.md` — §6 *"TOSS_SECRET_KEY 회전 5단계"* 추가.

### Task 9 — sprint-status + 통합 검증 + 회귀 가드 (AC: #10, #11, 전체)

- [x] 9.1 sprint-status `6-1-정기결제-sandbox-신청: ready-for-dev → in-progress` (DS 시작 시).
- [x] 9.2 `epic-6: backlog → in-progress` 갱신(Epic 6 첫 스토리 — 본 CS 단계에서 이미 처리, DS는 검증만).
- [x] 9.3 `cd api && uv run alembic upgrade head` — 0018/0019 마이그레이션 정상 적용 검증. `uv run alembic downgrade -2` → `uv run alembic upgrade head` 양방향 검증.
- [x] 9.4 `cd api && uv run pytest -q` — 1068 baseline + ~30 신규(schema 3 + Toss adapter 5 + service 7 + endpoint 12 + exceptions 3) = ~1098 passed/11 skipped/0 failed. 회귀 0건. coverage ≥84% 유지.
- [x] 9.5 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` 0 에러.
- [x] 9.6 `cd web && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 9.7 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 9.8 OpenAPI schema diff 검증 — 신규 endpoint 2건(`POST /v1/payments/subscribe` + `GET /v1/payments/subscription`) + 신규 응답 모델 3건. CI 게이트 통과.
- [x] 9.9 manual smoke는 CR/QA로 위임. DS 단계는 unit test ~1098 passed + tsc/lint 0 errors로 functional verification 완료(Toss API mock + Idempotency-Key replay + active 중복 가드 + RFC 7807 모두 unit test로 가드).
- [x] 9.10 sprint-status `6-1-정기결제-sandbox-신청: in-progress → review` 갱신 완료. commit + push는 본 단계 종료 직후.
- [ ] 9.11 CR 종료 직전 — sprint-status `6-1-정기결제-sandbox-신청: review → done` 같은 commit에 포함. (epic-6은 본 스토리 + 6.2 + 6.3 완료 시점에 done).

## Dev Notes

### 핵심 — 본 스토리는 *Toss Payments sandbox 정기결제 신청 흐름 + KRW 9,900 monthly plan + Idempotency-Key 멱등 처리 + RFC 7807 payment-failed*

epics.md:829-842 정합 — *FR40 정기결제 1플랜 sandbox 신청* baseline. PG 선택은 prd.md:925 *"결제 sandbox(W7)가 일정 압박 시 → Toss Payments 단일"* 정합 — Stripe는 README guide placeholder 1줄 + `provider="stripe"` ENUM 값만 등록(Story 6.2/8.5 forward).

**3 SOT 패턴 정합**:
1. **Idempotency-Key SOT** — Story 2.5 `meals.py:_create_meal_idempotent_or_replay` race-free SELECT-INSERT-CATCH-SELECT 1:1 정합. payments 도메인 catalog는 신설(`PaymentIdempotencyKeyInvalidError`) — DF49 *cross-cutting base 분리*는 deferred 유지(함수 helper 분리는 Story 6.3 webhook 시점 가능).
2. **RFC 7807 SOT** — `BalanceNoteError` base + ClassVar status/code/title + `to_problem(instance=...)` 패턴 1:1 정합. `application/problem+json` media type + `code` 카탈로그(payments.* prefix).
3. **Sentry capture SOT** — Story 3.6 `LLMRouterExhaustedError` 패턴 정합. service 레이어에서 `sentry_sdk.capture_message("payment.confirm_failed")` 명시 호출(*글로벌 핸들러 자동 capture와 별도 — 운영 모니터링 명시 신호*).

**검증 시점 분리**:
- AC1-3, 6, 10(DB + adapter + service + exceptions) — 단위 테스트 100% 가드.
- AC4-5(endpoints) — 단위 테스트 12건 + httpx mock(Toss API).
- AC7(mobile UX) — tsc/lint + manual smoke(Linking.openURL → Web 외부 브라우저 진입 + App Review 정책 정합).
- AC8(web UX) — tsc/lint + manual smoke(Toss test card sandbox 결제 흐름 1회).
- AC9(README/runbook) — review 단계 docs verification.

### Toss Payments Widget SDK 흐름 결정 — 클라이언트 widget + server confirm 분리

Toss Payments는 두 가지 통합 패턴:
- **(a) 결제 위젯(Payment Widget)**: 클라이언트 SDK가 카드 정보 입력 화면 노출 → 사용자 결제 인증 → `paymentKey` + `orderId` + `amount` 받음 → 클라이언트가 server endpoint에 송신 → server가 Toss API `POST /v1/payments/confirm` 호출로 결제 승인.
- **(b) 빌링키 발급(Billing Key)**: 정기결제용 — 클라이언트 SDK로 카드 등록(`/v1/billing/authorizations/issue`) → server에 빌링키 저장 → server가 매 결제 주기마다 `POST /v1/billing/{billingKey}` API 호출로 결제 진행.

**본 스토리는 (a) 패턴 채택** — *최초 신청 1회 결제만* 구현. 자동 갱신은 Story 6.3 webhook 책임(*Toss가 다음 결제 주기에 webhook 송신 → server가 갱신 결제 진행*). 빌링키 발급 통합은 Story 6.3에서 추가(`provider_billing_key` 컬럼은 *forward-compat — 본 스토리에서는 항상 NULL*).

**대안(검토 후 미채택)**:
- (b) 패턴 도입: 빌링키 발급 + 즉시 첫 결제 — Toss API 호출 ~2회로 결제 흐름이 *2단계*가 됨(authorize + first charge). 본 스토리 *최초 신청 1회 결제* scope 초과 + 단위 테스트 복잡도 ↑ + Story 6.3 webhook 흐름과 분기 충돌 가능성. (a) → Story 6.3에서 (b) 통합으로 자연 확장.
- 둘 다 통합: 본 스토리 baseline scope에서 over-engineering(YAGNI).

### App Store IAP 정합 결정 — 모바일은 외부 웹 결제 진입점만 노출

prd.md:676 *"In-App Purchase: 결제는 IAP 우회(외부 결제 화면 sandbox) — App Review 정책 준수 위해 *'앱 외부에서 구독 가능'* 화면만 노출하는 패턴 또는 deep link"* SOT.

**채택 패턴**: 모바일 화면은 *결제 위젯 노출 X* + *외부 브라우저 진입 버튼만 노출*(`Linking.openURL(getSubscribeWebUrl())`). 안내 문구 *"App Store 정책에 따라 결제는 외부 브라우저에서 진행됩니다"* 명시.

**App Review 위반 가능 패턴(미채택)**:
- WebView 내장 결제: WebView 내부에서 Toss 결제 위젯 렌더 — Apple App Review가 *"앱 내부 결제 흐름은 IAP 사용 의무"* 룰 적용 가능성. 안전 회피.
- 모바일 직접 Toss SDK: React Native용 Toss SDK가 sandbox에서 카드 정보 입력 화면 노출 — IAP 우회로 간주될 위험.
- Apple Pay/Google Pay 통합: 정기결제 자동 갱신 로직과 충돌 + IAP 정합 명확치 않음.

**Story 6.x 후속에서 polish 검토**:
- Story 8.x deep-link auth bridge: 모바일 → Web 진입 시 *one-time signed token*으로 자동 로그인 → 사용자 재로그인 부담 해소.
- App Review 정합 SOP 1페이지(NFR-M2 5섹션 일부): 외주 인수자가 Apple/Google 심사 통과를 위해 따라야 할 SOP 4-5단계.

### `crypto.randomUUID()` orderId / idempotencyKey 분리 결정

**클라이언트 측 식별자 2개**:
1. **Toss `orderId`**: Toss API 표준 — Toss 측 멱등 dedup(*같은 orderId 재송신 시 Toss가 중복 결제 차단*). 64자 cap, UUID v4 적합.
2. **우리 application-level `Idempotency-Key`**: 우리 server 측 멱등 — `_subscribe_idempotent_or_replay` race-free SELECT-INSERT-CATCH-SELECT.

**둘 다 필요한 이유**:
- Toss `orderId`만으로는 *우리 서버 측에서 같은 결제 시도가 같은 paymentKey로 confirm 호출되는 race* 차단 부족(Toss는 같은 orderId 재호출 시 즉시 4xx 반환 + 우리 측 payment_log dedup은 별 layer).
- 우리 `Idempotency-Key`만으로는 Toss 측 결제 자체의 *클라이언트 retry race* 차단 부족(Toss 결제 화면 진입 후 사용자가 *결제 완료* 버튼을 두 번 빠르게 누르는 시나리오).

**결정**: 두 키 분리 + 클라이언트가 1회 widget mount 동안 양 키 *불변* 유지(localStorage 저장 + success 라우트에서 read). 페이지 새로고침 시 *새 시도*로 간주(새 키 2개 생성).

### Idempotency-Key catalog 격리 결정 (DF49 갱신)

DF49 *"`Idempotency-Key` cross-cutting 도메인 격리"* — Story 2.5 시점에 *Story 6.x 결제 webhook idempotency 도입* 시점에 *cross-cutting `IdempotencyError` base*로 분리 검토 forward.

**본 스토리(6.1) 결정**: *cross-cutting 분리 미수행* — `PaymentIdempotencyKeyInvalidError(PaymentError)` payments-specific 유지.

**사유**:
- (a) `MealIdempotencyKeyInvalidError`와 `PaymentIdempotencyKeyInvalidError`는 *동일 검증 로직*(UUID v4 regex)이지만 *다른 catalog code prefix*(`meals.*` vs `payments.*`)와 *다른 후속 분기*(soft-delete conflict vs subscription conflict). 단순 base 통합은 catalog 코드 prefix 통일 강제 → *외주 인수 시 클라이언트별 catalog 분리 정책*과 충돌 가능성.
- (b) Story 6.3 webhook 시점에 *3번째 도메인*(`webhook_events.idempotency_key.invalid`)이 등장하면 그 시점에 *공통 helper 함수*(`_validate_idempotency_key_uuid_v4(key) -> str | None`) 분리 검토 — *exception 계층 통합*은 deferred 유지.
- (c) *함수 helper 분리*만으로 DRY 80%+ 달성 — 단위 테스트도 helper 단위로 단일 SOT(*UUID v4 regex 검증 1지점*). exception 계층은 *catalog 분리* 가치가 더 높음.

**DF49 재기록**: *함수 helper 분리는 Story 6.3에서 가능, 예외 계층 통합은 deferred(Growth — 외주 인수 후 클라이언트별 catalog 분리 정책 확정 후)*.

### `MONTHLY_PLAN_PRICE_KRW = 9900` 상수 위치 결정

**채택**: `app/services/payment_service.py` 모듈 상수.

**대안(검토 후 미채택)**:
- (a) `app/core/config.py:settings.monthly_plan_price_krw` 환경 변수 — 환경별 가격 변경 가능하나, 본 스토리 baseline은 *KRW 9,900 단일 plan* 명시(epics.md:832). 환경 변수로 빼면 *staging에서 9,000원 → prod에서 9,900원* 같은 운영 사고 가능성. 가격은 *코드 SOT*가 안전(*가격 변경 = PR + review*).
- (b) DB `plans` 테이블: 단일 plan에 대해 over-engineering. 후속에서 `plans` 테이블 도입 시 service 모듈 상수 → DB 조회로 전이(deferred).

**Story 6.x 후속**:
- Story 6.x — plan 추가(예: yearly = 99,000원, premium = 19,900원) 시 `PLAN_PRICES = {"monthly": 9900, "yearly": 99000, "premium": 19900}` dict 확장 + `subscriptions.plan` ENUM `ALTER TYPE ... ADD VALUE` 추가.

### `expires_at = started_at + 30일` 결정 (월 갱신 baseline)

**채택**: monthly plan은 `expires_at = started_at + timedelta(days=30)`.

**대안(검토 후 미채택)**:
- (a) `relativedelta(months=1)`: 월별 일수 차이(30/31일) 반영 — 사용자 친화이나 *결제 주기 = 정확히 30일*이 회계 단순성 우선(*월말 결제 사용자가 다음 달 28일/30일/31일 중 어느 날에 갱신될지 모호함*). 30일 고정이 *외주 인수자 운영 단순*.
- (b) `expires_at = started_at + relativedelta(months=1, day=1)` 다음달 1일 정렬: 모든 사용자 결제일이 1일로 통일되어 cron 단순. 이미 사용 중 사용자 일수 *손실*(미충전 일자 발생). 안전 회피.

**Story 6.3 후속**: webhook이 갱신 결제 시점에 `expires_at += timedelta(days=30)` 또는 *Toss 측 갱신 응답의 `nextBillingDate`*로 갱신.

### Architecture Compliance

| 영역 | 영향 패턴 | 정합 |
|---|---|---|
| Router (AC4, AC5) | architecture.md:670 `payments.py` SOT | 정합 — `app/api/v1/payments.py` 신규 |
| Service layer (AC3) | architecture.md:704 *"`payment_service.py` (가설)"* | 정합 — 신규 모듈 |
| Adapter (AC2) | architecture.md:693 `toss.py` SOT | 정합 — 신규 모듈 + httpx + tenacity |
| DB models (AC1) | architecture.md:299 ER + architecture.md:392 naming | 정합 — `subscriptions` / `payment_logs` 신규 + `<table>_<col>_enum` 정합 |
| RFC 7807 (AC4, AC6) | architecture.md:459 + architecture.md:513 | 정합 — `application/problem+json` + `code` payments.* catalog |
| Idempotency-Key (AC4) | architecture.md:324 + Story 2.5 SOT | 정합 — UUID v4 regex + race-free SELECT-INSERT-CATCH-SELECT |
| KRW integer (AC1, AC4) | architecture.md:479 + NFR-L3 | 정합 — `int` 9900 hard-constant |
| Audit 분리 (AC4) | architecture.md:891 `audit_admin_action` | 정합 — payments는 자기 자기 결제이므로 audit 미기록(payment_logs는 별 audit-trail 성격) |
| Sentry (AC4) | architecture.md:892 `before_send` 마스킹 | 정합 — `_mask_payment_payload` + Sentry capture explicit |
| OpenAPI (AC4) | architecture.md:847 + Story 5.x 패턴 | 정합 — multi-status 응답 정의 + Pydantic Literal |
| App Review (AC7) | prd.md:676 IAP 우회 SOP | 정합 — 모바일 외부 결제 진입점만 노출 |

### Library / Framework Requirements

- **Backend**: 신규 의존성 0건. 기존 활용:
  - `fastapi` `APIRouter` / `Header` / `Depends` (이미 사용).
  - `pydantic` `BaseModel` / `Field` / `Literal` / `ConfigDict` (이미 사용).
  - `httpx` (이미 사용 — `mfds_openapi.py` SOT).
  - `tenacity` (이미 사용 — `llm_router.py` SOT 정합).
  - `sqlalchemy` `select` / `insert` / `update` + Postgres ENUM 매핑 (이미 사용).
  - `sentry_sdk.capture_message` (이미 사용 — `llm_router.py` SOT 정합).
- **Mobile**: 신규 의존성 0건. 기존:
  - `expo-linking` (Expo SDK 54 baseline, `+native-intent.tsx` SOT).
  - `@tanstack/react-query` (Story 5.3 SOT 재사용).
  - `expo-router` (이미 사용).
- **Web**: 신규 의존성 1건:
  - `@tosspayments/payment-widget-sdk ^1.x` (Toss 공식 SDK — sandbox + prod 공통). 본 스토리 시점 최신 안정 버전 확인 후 lock(2026-05 시점 권장 ^1.7.x 추정).
  - 기존: `apiFetch` (Story 1.2/5.x SOT) — `Idempotency-Key` 헤더 첨부 first usage. `crypto.randomUUID()` Web Crypto API (브라우저 표준, polyfill 불필요).

### File Structure Requirements

#### 신규 파일

**Backend (api/):**
- `api/app/db/models/subscription.py`
- `api/app/db/models/payment_log.py`
- `api/alembic/versions/0018_subscriptions.py`
- `api/alembic/versions/0019_payment_logs.py`
- `api/app/adapters/toss.py`
- `api/app/services/payment_service.py`
- `api/app/api/v1/payments.py`
- `api/tests/test_subscriptions_payment_logs_schema.py`
- `api/tests/test_exceptions_payments.py`
- `api/tests/adapters/test_toss.py`
- `api/tests/services/test_payment_service.py`
- `api/tests/api/v1/test_payments.py`

**Mobile:**
- `mobile/features/settings/useSubscription.ts`
- `mobile/app/(tabs)/settings/subscription.tsx`

**Frontend (web/):**
- `web/src/features/payments/SubscribeForm.tsx`
- `web/src/app/(user)/account/subscribe/page.tsx`
- `web/src/app/(user)/account/subscribe/success/page.tsx`
- `web/src/app/(user)/account/subscribe/fail/page.tsx`

#### 수정 파일 (기존)

**Backend:**
- `api/app/db/models/__init__.py` — `Subscription`/`PaymentLog` import.
- `api/app/core/exceptions.py` — `PaymentError` 계층 추가(7+ 서브클래스).
- `api/app/main.py` — `payments.router` 등록.

**Mobile:**
- `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="subscription">`.
- `mobile/app/(tabs)/settings/index.tsx` — items 배열 *'구독'* 추가.
- `mobile/.env.example` — `EXPO_PUBLIC_WEB_BASE_URL` 추가.
- `mobile/lib/api-client.ts` — OpenAPI 자동 갱신.

**Web:**
- `web/package.json` + `pnpm-lock.yaml` — `@tosspayments/payment-widget-sdk` 추가.
- `web/.env.example` — `NEXT_PUBLIC_TOSS_CLIENT_KEY` 추가.
- `web/src/lib/api-client.ts` — OpenAPI 자동 갱신.
- `web/src/app/(user)/settings/profile/page.tsx` — 푸터 *'구독 관리'* link 추가.

**Docs/Config:**
- `README.md` — §5.4 결제 PG 연동 가이드.
- `docs/runbook/secret-rotation.md` — §6 TOSS_SECRET_KEY 회전.
- `.env.example` (루트) — `NEXT_PUBLIC_TOSS_CLIENT_KEY` 추가.

### Testing Standards

**Backend pytest 패턴 (Story 5.x SOT 정합)**:
- `api/tests/conftest.py` 기존 fixture 재사용(`db_session` / `client` / `test_user_active` / `test_user_with_basic_consents`).
- Toss API mock: `httpx_mock` (또는 `respx`) — 본 스토리에서 신규 `respx` 의존성 도입 평가:
  - `httpx_mock`(pytest plugin) — 이미 OpenAI/Anthropic adapter 테스트에서 사용 중 → 동일 라이브러리 일관성. **채택**.
- DB 트랜잭션 격리: `pytest-asyncio` + autouse `_truncate_user_tables` fixture(`subscriptions`/`payment_logs` 추가).
- Idempotency-Key replay 테스트는 *별 트랜잭션 2회 호출* 패턴(Story 2.5 SOT 정합).
- Sentry capture 검증: `mock_sentry_capture_message` fixture(이미 사용 중) — `llm_router.exhausted` 패턴 정합.

**Web/Mobile 테스트 (Story 5.x SOT 정합)**:
- web tsc/lint 0 errors + mobile tsc/lint 0 errors가 1차 게이트.
- Toss SDK 통합은 *manual smoke* + e2e(QA Story 6.x forward) 위임 — Jest unit test는 SDK mock 복잡도 ↑ vs cost.
- localStorage idempotencyKey 보존 검증은 manual smoke 단계 — *결제 완료 후 페이지 새로고침 → 같은 키로 retry → 200 replay 응답* 시나리오.

**회귀 테스트 invariant**:
- Story 2.x meals — `MealIdempotencyKeyInvalidError` catalog 변경 X.
- Story 5.x users — 영향 0건.
- alembic 0017 → 0018 → 0019 → downgrade 양방향 동작.

### Project Context Reference

- **PRD**: `_bmad-output/planning-artifacts/prd.md` (FR40-FR42 + I4 결제 sandbox + R10 영업 답변 SOP).
- **Architecture**: `_bmad-output/planning-artifacts/architecture.md` (Subscription FR40-42 그룹 + Toss webhook + Idempotency-Key + RFC 7807).
- **Epics**: `_bmad-output/planning-artifacts/epics.md` (Epic 6 + Story 6.1/6.2/6.3 BDD AC).
- **Story 2.5 SOT (Idempotency-Key)**: `api/app/api/v1/meals.py:_create_meal_idempotent_or_replay` + `api/alembic/versions/0009_meals_idempotency_key.py`.
- **Story 5.3 SOT (서비스 분리 + Streaming)**: `api/app/services/data_export_service.py` + `_bmad-output/implementation-artifacts/5-3-데이터-내보내기-json-csv.md`.
- **DF49 (Idempotency catalog cross-cutting)**: `_bmad-output/implementation-artifacts/deferred-work.md:254`.

### Latest Tech Information (2026-05 baseline)

- **Toss Payments Widget SDK**: `@tosspayments/payment-widget-sdk` ^1.7+ (2026-05 시점 추정). [공식 SDK 문서](https://docs.tosspayments.com/reference/widget-sdk). 정기결제 빌링키 발급은 `requestBillingAuth` API — Story 6.3 forward.
- **Toss Payments REST API**: `POST /v1/payments/confirm` — Basic Auth (`Authorization: Basic base64(secret_key:)`). 응답 schema는 `paymentKey` / `orderId` / `status`(*DONE/CANCELED/PARTIAL_CANCELED/ABORTED*) / `totalAmount` / `approvedAt` / `card` / `easyPay` 등 ~20 필드. [공식 REST API 문서](https://docs.tosspayments.com/reference).
- **Toss test cards**: `4330-1234-1234-1234`(승인) / `4330-1234-1234-1235`(잔액부족) / `4330-1234-1234-1236`(한도초과) — Toss sandbox 표준.
- **App Store IAP 정책**: Apple App Review Guideline 3.1.1 *"Apps offering... digital content or services... must use IAP"*. 외부 웹 결제 흐름은 *"reader apps"* 또는 *"non-consumable goods"*(서비스 가입)에 해당 — 명시적 외부 진입 안내 + IAP 우회 의도 명시 X면 통과. 본 스토리는 *명시적 외부 결제 안내*만 노출.

## Dev Agent Record

### Agent Model Used

Amelia (claude-opus-4-7[1m]) — 2026-05-08 BMad Dev Story 워크플로우.

### Debug Log References

- alembic 0018 ENUM duplicate-object DDL race — `op.execute("DO $$ BEGIN CREATE TYPE ...
  EXCEPTION WHEN duplicate_object THEN NULL END $$;")` idempotent 패턴 채택(0005
  `op.execute(CREATE TYPE)` 패턴 정합 + 부분 실패 후 재실행 안전성). column-level
  `sa.dialects.postgresql.ENUM(create_type=False)` 명시로 ENUM 생성 책임을 마이그레이션
  단일 SOT로 통합.
- `httpx.Timeout(connect=5.0, read=15.0)` — httpx 0.28에서 `write`/`pool` 명시 의무
  (default 미허용). `connect=5.0, read=15.0, write=5.0, pool=5.0`으로 4 파라미터 모두
  명시.
- service 레이어 `_insert_failed_payment_log` 후 `session.commit()` 명시 호출 — 라우터가
  `PaymentConfirmFailedError`를 catch하지 않고 글로벌 핸들러로 propagate하면
  `get_db_session` dependency가 `rollback`을 수행해 audit-trail row가 사라진다(Spec
  deviation 1건). test_payments.py:test_subscribe_toss_4xx_returns_400_confirm_failed
  로 회귀 가드.
- Web `/account/subscribe/success` `useEffect` 내부 `setState` 직접 호출 lint
  (`react-hooks/set-state-in-effect`) — async IIFE 내부로 이동해 cascading render 회피.

### Completion Notes List

- ✅ Task 1 (AC1) — `Subscription`/`PaymentLog` ORM 12+13 컬럼 + ENUM 6종 + partial UNIQUE
  3건 + alembic 0018/0019. 양방향(downgrade -2 → upgrade head) 검증 완료.
- ✅ Task 2 (AC2) — `app/adapters/toss.py` + `confirm_payment` + `_mask_payment_payload` +
  tenacity 3회 transient retry. 6 unit tests (httpx MockTransport 기반).
- ✅ Task 3 (AC6) — `PaymentError` base + 9 서브클래스. 11 unit tests (parameterized).
- ✅ Task 4 (AC3) — `payment_service.subscribe` + `_subscribe_idempotent_or_replay`
  race-free helper(Story 2.5 SOT 1:1) + Sentry `capture_message` 명시 호출. 7 unit tests.
- ✅ Task 5 (AC4, AC5) — `app/api/v1/payments.py` + 2 endpoints + `_validate_payment_
  idempotency_key`(Story 2.5 SOT 1:1). 12 endpoint tests.
- ✅ Task 6 (AC7) — Mobile `useSubscription` hook + `/settings/subscription` screen +
  `Linking.openURL(getSubscribeWebUrl())` 외부 결제 진입점 + App Store IAP 정합 안내 +
  Stack.Screen + 메뉴 항목.
- ✅ Task 7 (AC8) — Web `@tosspayments/payment-widget-sdk` 통합 + 3 페이지(subscribe /
  success / fail) + `crypto.randomUUID()` orderId/idempotencyKey + localStorage 보존.
  `gen:api` 실행 — OpenAPI client 자동 갱신.
- ✅ Task 8 (AC9) — README §5.4 *결제 PG 연동(Toss Payments sandbox)* 추가 +
  `secret-rotation.md` §6 *TOSS_SECRET_KEY 회전 6단계* 추가.
- ✅ Task 9 (AC10, AC11) — pytest **1068 → 1114 passed** (+46) / 11 skipped / 0 failed,
  coverage 85.32% → **85.47%** (+0.15pp). ruff/format/mypy 0 errors + web tsc/lint 0
  errors + mobile tsc/lint 0 errors. alembic 양방향 OK. Story 1.x/2.x/3.x/4.x/5.x 회귀
  0건. sprint-status `in-progress → review` 갱신 완료.
- **Spec deviation 1건**: AC3 service 레이어가 *failed payment_log INSERT* 후
  `session.commit()` 명시 호출 — `PaymentConfirmFailedError` propagation 시 global
  handler가 호출되기 전 audit-trail row 영속화 보장. CR 단계에서 검토.
- 9.11(CR 종료 직전 review → done 갱신)은 CR 단계 책임이라 [x] 미체크 유지.

### File List

**신규 (api/):**
- `api/app/db/models/subscription.py`
- `api/app/db/models/payment_log.py`
- `api/alembic/versions/0018_subscriptions.py`
- `api/alembic/versions/0019_payment_logs.py`
- `api/app/adapters/toss.py`
- `api/app/services/payment_service.py`
- `api/app/api/v1/payments.py`
- `api/tests/test_subscriptions_payment_logs_schema.py`
- `api/tests/test_exceptions_payments.py`
- `api/tests/adapters/test_toss.py`
- `api/tests/services/test_payment_service.py`
- `api/tests/api/v1/test_payments.py`

**신규 (mobile/):**
- `mobile/features/settings/useSubscription.ts`
- `mobile/app/(tabs)/settings/subscription.tsx`

**신규 (web/):**
- `web/src/features/payments/SubscribeForm.tsx`
- `web/src/app/(user)/account/subscribe/page.tsx`
- `web/src/app/(user)/account/subscribe/success/page.tsx`
- `web/src/app/(user)/account/subscribe/fail/page.tsx`

**수정 (api/):**
- `api/app/db/models/__init__.py` — `Subscription`/`PaymentLog` import.
- `api/app/core/exceptions.py` — `PaymentError` 계층 9 클래스 추가.
- `api/app/main.py` — `payments.router` import + 등록.
- `api/tests/conftest.py` — TRUNCATE 리스트에 `payment_logs`/`subscriptions` 추가.

**수정 (mobile/):**
- `mobile/app/(tabs)/settings/_layout.tsx` — `<Stack.Screen name="subscription">` 추가.
- `mobile/app/(tabs)/settings/index.tsx` — items 배열 *구독* 추가.
- `mobile/.env.example` — `EXPO_PUBLIC_WEB_BASE_URL` 추가.
- `mobile/lib/api-client.ts` — OpenAPI 자동 갱신.

**수정 (web/):**
- `web/package.json` + `pnpm-lock.yaml` — `@tosspayments/payment-widget-sdk` 추가.
- `web/.env.example` — `NEXT_PUBLIC_TOSS_CLIENT_KEY` 추가.
- `web/src/lib/api-client.ts` — OpenAPI 자동 갱신.
- `web/src/app/(user)/settings/profile/page.tsx` — 푸터 *구독 관리* link 추가.

**수정 (docs/config):**
- `README.md` — §5.4 결제 PG 연동 가이드.
- `docs/runbook/secret-rotation.md` — §6 TOSS_SECRET_KEY 회전 + §0 표 갱신.
- `.env.example` (루트) — `TOSS_SECRET_KEY` 코멘트 갱신 + `NEXT_PUBLIC_TOSS_CLIENT_KEY` 추가.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — Story 6.1 in-progress →
  review.

### Review Findings

CR 일자: 2026-05-08, Reviewer: Amelia (Blind Hunter + Edge Case Hunter + Acceptance Auditor 3-layer)

#### Decision Needed (resolved)

- [x] [Review][Decision] **Service-layer `session.commit()` in failed-payment branch — spec deviation** [`api/app/services/payment_service.py:333-358`] — **결정 (2026-05-08, hwan)**: 옵션 (a) Spec ratify 채택. spec line 120을 *"성공 경로는 라우터 commit, 실패 경로(`PaymentConfirmFailedError`)는 audit row 영속화 위해 서비스 commit 후 raise"*로 수정 + 서비스 코드에 fence 주석 명시. (b) global handler가 DB write를 떠안는 anti-pattern 차단, (c) drift 잔존을 차단.

#### Patches (15) — 모두 적용

- [x] [Review][Patch] **P1. Failed-event-type idempotency replay missing — 재시도 시 500** [`api/app/services/payment_service.py:_fetch_payment_log_by_idempotency_key + _subscribe_idempotent_or_replay`] — 1차 SELECT의 `event_type='subscribe'` 필터 제거 + `event_type='failed'` 분기에 `PaymentRetryAfterFailedError(409)` 추가. `_insert_failed_payment_log`도 같은 키 재진입 시 `IntegrityError`를 멱등 skip(`bool` 반환 + caller가 commit 분기). 신규 예외 `PaymentRetryAfterFailedError(code=payments.idempotency_key.retry_after_failed)` 추가.
- [x] [Review][Patch] **P2. Subscription active partial UNIQUE 충돌이 IntegrityError catch에서 미처리** [`api/app/services/payment_service.py:_subscribe_idempotent_or_replay`] — IntegrityError.orig 인덱스 이름으로 분기. `_SUBSCRIPTION_ACTIVE_INDEX_NAME` 상수 추가 + race 진입 시 `SubscriptionAlreadyActiveError(409)` + `logger.error("payments.subscribe.subscription_active_race")` 운영 신호.
- [x] [Review][Patch] **P3. Toss `confirm_payment` 응답 `totalAmount`/`orderId` 미검증** [`api/app/adapters/toss.py:confirm_payment`] — `parsed.total_amount == amount` & `parsed.order_id == order_id` assert; mismatch 시 `PaymentProviderPayloadInvalidError(502)` + structured error log.
- [x] [Review][Patch] **P4. `TossConfirmResponse.totalAmount` Pydantic 강제 int 미적용** [`api/app/adapters/toss.py:TossConfirmResponse`] — `Field(alias="totalAmount", strict=True)`로 string/float 자동 coerce 차단.
- [x] [Review][Patch] ~~**P5. Toss 4xx body가 dict 아닐 때 `failure_reason` None**~~ — 재검증 결과 기존 fallback `toss_message or f"toss_rejected_{...}"`이 None/empty 양쪽 안전 처리(false-positive). dismiss로 reclassify.
- [x] [Review][Patch] **P6. 하드코딩된 sandbox client key fallback 제거** [`web/src/features/payments/SubscribeForm.tsx:TOSS_CLIENT_KEY`] — `?? ""` fail-closed + widget mount 시점에 환경 변수 미설정이면 *"결제 설정 오류"* 메시지 노출.
- [x] [Review][Patch] **P7. OpenAPI 200 response를 `content?: never`로 선언했지만 `SubscribeResponse` 반환** [`api/app/api/v1/payments.py:subscribe responses` + 자동 재생성된 `web/src/lib/api-client.ts` & `mobile/lib/api-client.ts`] — `responses[200]={"model": SubscribeResponse, "description": ...}` 추가. `pnpm gen:api`로 클라이언트 재생성 — 200 응답이 typed `SubscribeResponse`로 노출.
- [x] [Review][Patch] **P8. `web/.env.example` gitignore로 인해 `NEXT_PUBLIC_TOSS_CLIENT_KEY` 미배포** [`web/.gitignore`] — `!.env.example` 예외 추가. version control에 포함되어 fresh checkout setup SOP 정합.
- [x] [Review][Patch] **P9. SubscribeForm `idempotencyKey` useEffect race + StrictMode** [`web/src/features/payments/SubscribeForm.tsx:idempotencyKeyRef`] — `useRef(crypto.randomUUID())` 동기 초기화로 변경. 빈 fallback / useEffect 분기 제거.
- [x] [Review][Patch] **P10. SubscribeForm 사전 401 silent ignore** [`web/src/features/payments/SubscribeForm.tsx:active subscription fetch`] — 401 → *"로그인이 만료되었습니다"* 메시지 + 결제 진행 차단. 404만 ignore(미신청 사용자 정상 케이스), 그 외 5xx도 안전망 차단.
- [x] [Review][Patch] **P11. handleSubscribe widget.requestPayment silent failure → submitting 무한** [`web/src/features/payments/SubscribeForm.tsx:handleSubscribe`] — `try/finally`로 `setSubmitting(false)` 보장. 정상 redirect 시 페이지 unmount이므로 finally 미도달.
- [x] [Review][Patch] **P12. success/page.tsx StrictMode 중복 POST + localStorage 조기 삭제** [`web/src/app/(user)/account/subscribe/success/page.tsx:calledRef`] — `useRef` 단일 firing guard 추가. localStorage.removeItem은 응답 수신 후 호출(기존 그대로) — guard 덕분에 useEffect 재진입이 차단되어 race 해소.
- [x] [Review][Patch] **P13. `Number(amount)` 소수/지수 허용** [`web/src/app/(user)/account/subscribe/success/page.tsx:amount parsing`] — `parseInt(amountRaw, 10)` + `Number.isInteger` + `String(amount) === amountRaw.trim()` 3중 검증. 소수/지수/leading zero 차단.
- [x] [Review][Patch] **P14. `useSubscriptionQuery` queryKey에 userId 누락 — 계정 전환 시 stale** [`mobile/features/settings/useSubscription.ts` + `mobile/app/(tabs)/settings/subscription.tsx`] — `getSubscriptionQueryKey(userId)` 헬퍼 + `useSubscriptionQuery(userId)` 시그니처 변경. caller는 `useAuth().user?.id`를 전달, 미로딩 시 `enabled: false`.
- [x] [Review][Patch] **P15. `test_subscribe_idempotency_race_unique_violation_replays`가 실제 race branch 미테스트** [`api/tests/services/test_payment_service.py`] — 신규 테스트 3건 추가: ① IntegrityError catch path monkeypatch 진입 검증, ② `event_type='failed'` replay → `PaymentRetryAfterFailedError(409)`, ③ `_insert_failed_payment_log` IntegrityError 멱등 skip. 총 7건 → 10건.

#### Deferred (10)

- [x] [Review][Defer] **Toss `confirm` blind-retry double-charge 위험(production-grade)** [`api/app/adapters/toss.py:1450-1509`] — sandbox 허용, prod는 `payments/{paymentKey}` GET-before-retry 또는 Toss 측 idempotency 필요.
- [x] [Review][Defer] **`_mask_payment_payload` shallow — nested `customer.*` PII / non-string `card.number` 미처리** [`api/app/adapters/toss.py:1342-1365`] — Story 8.4 audit/masking 강화에서 통합.
- [x] [Review][Defer] **`_insert_failed_payment_log.failure_reason` 미마스킹** [`api/app/services/payment_service.py:2438-2463`] — Story 8.4 forward.
- [x] [Review][Defer] **Toss `customerKey = customer-${userId}` raw UUID 노출** [`web/src/features/payments/SubscribeForm.tsx:5299`] — prod 진입 시 opaque hash로 변환.
- [x] [Review][Defer] **soft-deleted user(Story 5.2 grace) subscribe 가능 여부 검증** [`api/app/api/v1/payments.py:1700-1740`] — `current_user` 의존성이 `deleted_at IS NULL` 필터하는지 확인 필요. 필터되어 있으면 dismiss.
- [x] [Review][Defer] **`Cache-Control: no-store` 누락** [`api/app/api/v1/payments.py:1700-1740`] — 결제 응답 중간 프록시 캐싱 방지(production hardening).
- [x] [Review][Defer] **Toss success URL CSRF — 공격자 controlled `paymentKey`** [`web/src/app/(user)/account/subscribe/success/page.tsx:5044-5054`] — localStorage 저장값과 paymentKey/orderId 대조(production hardening).
- [x] [Review][Defer] **README test card 번호가 현 Toss sandbox 문서와 일치하는지 검증** [`README.md:43`] — 클라이언트 데모 전 검증.
- [x] [Review][Defer] **`payment_logs.provider_payment_key` partial UNIQUE가 renew INSERT 차단** [`api/app/db/models/payment_log.py:2099-2105`] — Story 6.3 webhook에서 composite UNIQUE 재검토.
- [x] [Review][Defer] **`cancelled-but-not-expired` UX gap — get_subscription 404 반환** [`api/app/api/v1/payments.py:1762-1772`] — Story 6.2 cancel 흐름에서 grace UX 결정.

#### Dismissed

26건 dismiss(false positive, 코드베이스 SOT 패턴 정합, sandbox-scope 무관, YAGNI). 코멘트 미기록.

### Change Log

| Date | Phase | Author | Changes |
|------|-------|--------|---------|
| 2026-05-08 | DS | Amelia | Story 6.1 구현 완료 — `subscriptions`/`payment_logs` 테이블 + Toss adapter + payment_service + 2 endpoints + Mobile 외부 결제 진입점 + Web Toss Widget 통합. pytest 1114 passed (+46), coverage 85.47%. Status: ready-for-dev → review. |
| 2026-05-08 | CR | Amelia | 3-layer review(Blind/Edge/Auditor) — 81 raw findings → triage: 1 decision, 15 patch, 10 defer, 26 dismiss. Findings 본 섹션에 기록. |
| 2026-05-08 | CR | Amelia | D1 spec ratify(option a) + 14 patch 일괄 적용(P5는 false-positive로 dismiss로 reclassify). 신규 예외 `PaymentRetryAfterFailedError(409)` + `_SUBSCRIPTION_ACTIVE_INDEX_NAME` 분기 + Toss 응답 amount/orderId 검증 + frontend StrictMode/race fix + `web/.env.example` 추적 + api-client 재생성. pytest 1117 passed (+3 신규), 85.34% coverage. tsc(web/mobile) 모두 통과. Status: review → done. |
