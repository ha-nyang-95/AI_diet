# Story 6.3: 결제 webhook + Idempotency-Key 멱등 + 이력

Status: done

<!-- Validation: Epic 6 마지막 스토리 — Story 6.1(`subscribe` + `subscriptions`/`payment_logs`
SOT + Toss `confirm_payment` adapter)과 Story 6.2(`cancel`/`history` + atomic UPDATE 패턴 +
DF135 active-but-expired race window deferred) 위에 *Toss webhook receipt + HMAC-SHA256
시그니처 검증 + Idempotency-Key 멱등 + renew/failed/refund 이벤트 처리*를 추가한다.
epics.md:857-869 정합 + architecture.md:912 *"`app/api/v1/payments.py:webhook` + `Idempotency-
Key` 멱등화"* 정합 + architecture.md:531 *"Stripe/Toss는 자체 retry — 우리는 `Idempotency-
Key`로 중복 처리 멱등화"* 정합. 핵심 invariant 5건: (1) **시그니처 timing-safe + timestamp 5
분 window** — `hmac.compare_digest` + Stripe 표준 정합 (replay attack 차단), (2) **Toss
webhook은 후속 갱신만 처리** — 첫 결제(subscribe)는 Story 6.1 widget success callback이 SOT,
webhook은 renew/failed/refund 3 event 분기, (3) **Idempotency 다층 게이트** — body `eventId`
1차 + Header `Idempotency-Key` 2차 + `payment_logs.idempotency_key` partial UNIQUE 3차
(race-free SELECT-INSERT-CATCH-SELECT — Story 2.5/6.1 SOT 1:1 정합), (4) **expires_at 만료
이중 처리** — APScheduler sweep cron(매시 정각, lazy fallback) + `get_subscription` lazy gate
(DF135 흡수 — active branch에 `expires_at > now()` 추가), (5) **D9 흡수** — alembic 0020으로
`payment_logs` `provider_payment_key` partial UNIQUE를 composite UNIQUE `(provider,
provider_payment_key, event_type)`로 변경(같은 paymentKey가 `subscribe → refund` 등
multiple event 가능). DF49 흡수 — `_validate_idempotency_key_uuid_v4` 공통 helper 함수 1건
분리(`api/app/core/idempotency.py` 신규 — meals/payments/webhook 3 도메인 SOT). 신규 환경
변수 1건(`TOSS_WEBHOOK_SECRET`) + 신규 ENUM 값 0건(`renew`/`refund`/`pending`은 Story 6.1
0019에서 forward-compat 등재 완료) + 신규 alembic 1건(0020) + 신규 worker 1건
(`api/app/workers/subscription_expire.py`). Stripe webhook은 본 스토리 OUT — `Story 8.5
forward stub`(provider 분기 dict 구조만 마련). 모바일/Web 신규 화면 0건 — webhook은 server-
to-server, 사용자 화면은 Story 6.2에서 완성. README §5.4.5 + runbook §7 SOP만 추가.
PR pattern: feature branch `story/6.3-payment-webhook`(master에서 분기, CS 시작 직전 분기
완료) — DS/CR 모두 동일 브랜치, PR은 CR 완료 후 1회. -->

## Story

As a 시스템 / 외주 발주자,
I want Toss/Stripe webhook을 수신해 구독 상태를 갱신하고 결제 이벤트 이력을 멱등 처리로 기록하기를,
So that 결제 비동기 흐름이 신뢰성 있게 동작하고 외주 인수 시 클라이언트가 즉시 본 PG로 전환 가능하다.

## Acceptance Criteria

1. **AC1 — Toss webhook 시그니처 검증 어댑터 (`app/adapters/toss.py` 확장 + HMAC-SHA256 + timestamp window)**
   **Given** Story 6.1 `app/adapters/toss.py` SOT(`confirm_payment` + `_mask_payment_payload`) + Stripe webhook 표준 *"timestamp + signature + 5분 window"* 패턴 + Toss Payments 공식 webhook 문서(헤더 `TossPayments-Webhook-Signature` + body raw bytes 기반 HMAC-SHA256), **When** webhook 시그니처 검증 함수 + Pydantic 스키마를 신설, **Then**:
   - **`TOSS_WEBHOOK_SECRET_KEY` 환경 변수 신설** — `api/app/core/config.py`에 추가:
     - `toss_webhook_secret_key: str = ""` — Toss 콘솔에서 *별 webhook secret*(`whsec_*`/`wsk_*` prefix, secret_key와 별 키)을 발급받아 설정. 빈 문자열 → fail-fast(prod) / soft-warn(dev).
     - `_strip_inline_comments` validator는 자동 적용(기존 패턴 정합).
     - `_validate_jwt_secrets_in_prod` 패턴 *복사 X* — webhook secret은 prod/staging에서도 *optional fail-fast*(미설정 시 webhook endpoint가 503 반환). dev/ci/test는 빈 값 허용(테스트는 fixture 시크릿 주입).
   - **`TOSS_WEBHOOK_SIGNATURE_HEADER: Final[str] = "TossPayments-Webhook-Signature"`** 모듈 상수 — Toss 표준 헤더명.
   - **`_TIMESTAMP_TOLERANCE_SECONDS: Final[int] = 300`** (5분) — replay attack 차단 window. Stripe 표준 정합(t=<unix>+v1=<sig> 형식의 *timestamp drift cap*).
   - **`def verify_webhook_signature(*, raw_body: bytes, signature_header: str, secret: str, now_unix: int | None = None) -> None`** — 시그니처 검증 SOT:
     - **Step 1 — header parse**:
       - `signature_header` 형식: `"t=<unix_ts>,v1=<base64_hmac_sha256>"`. comma split + key=value 분리.
       - 누락/형식 위반 → `WebhookSignatureInvalidError(401, "webhook signature header malformed")`.
       - `t=` 또는 `v1=` key 부재 → 동일 에러.
     - **Step 2 — timestamp drift 검증**:
       - `now = now_unix if now_unix is not None else int(time.time())` — `now_unix` 인자는 테스트 mock 용.
       - `abs(now - parsed_timestamp) > _TIMESTAMP_TOLERANCE_SECONDS` → `WebhookSignatureInvalidError(401, "webhook timestamp outside tolerance")`.
     - **Step 3 — HMAC-SHA256 계산**:
       - `signed_payload = f"{parsed_timestamp}.".encode() + raw_body` — Stripe 표준 *"timestamp + dot + raw body"* 정합.
       - `expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).digest()`.
       - `actual = base64.b64decode(parsed_v1)`.
       - **`hmac.compare_digest(expected, actual)`** — timing-safe 비교 의무(*무조건 사용 — `==` 비교는 timing-attack 취약*).
       - mismatch → `WebhookSignatureInvalidError(401, "webhook signature mismatch")`.
     - **Step 4 — Returns** `None` (성공 시 silent return). 실패는 모두 `WebhookSignatureInvalidError`.
   - **`TossWebhookEventBody(BaseModel)` Pydantic 모델** — Toss webhook body schema(필요 필드만, 모두 채택은 PII 노출 위험):
     - `event_id: str = Field(alias="eventId", min_length=1, max_length=64)` — Toss 측 unique event id, 멱등 키 1차 신호.
     - `event_type: Literal["PAYMENT.STATUS_CHANGED", "PAYMENT_FAILED", "REFUND_COMPLETED", "REFUND_PARTIAL"] = Field(alias="eventType")` — 4 enum. 그 외 미지원 event는 *400 + sentry warning*(Toss 측 webhook subscription 잘못 설정 신호).
     - `created_at: datetime = Field(alias="createdAt")` — Toss 표준 ISO 8601.
     - `data: dict[str, Any]` — `paymentKey`/`orderId`/`status`/`totalAmount`/`approvedAt`/`card` 포함하는 상세 dict. 본 모델에서는 *raw dict 유지*(추가 검증은 service 레벨에서 sub-schema로 분기).
     - `model_config = ConfigDict(populate_by_name=True, extra="ignore")`.
   - **`TossWebhookPaymentData(BaseModel)` Pydantic 모델** — `data` 필드의 sub-schema(서비스에서 분기 시 검증):
     - `payment_key: str = Field(alias="paymentKey", min_length=1, max_length=200)`.
     - `order_id: str = Field(alias="orderId", min_length=1, max_length=64)`.
     - `status: Literal["DONE", "CANCELED", "PARTIAL_CANCELED", "ABORTED"]` — Toss 표준.
     - `total_amount: int = Field(alias="totalAmount", strict=True, ge=0)`.
     - `approved_at: datetime | None = Field(alias="approvedAt", default=None)` — 환불 등 미수반 케이스 None 허용.
     - `model_config = ConfigDict(populate_by_name=True, extra="ignore")`.
   - **로깅**: `logger.warning("toss.webhook.signature_invalid", reason=...)` — verify 실패 시. 성공 시 `logger.info("toss.webhook.signature_verified", event_id=event_id_prefix[:8])`.
   - **단위 테스트** `api/tests/adapters/test_toss.py` 신규 ~6건:
     1. `verify_webhook_signature` happy-path — 올바른 timestamp + signature → silent return.
     2. `verify_webhook_signature` header 형식 위반(`t=` missing) → `WebhookSignatureInvalidError(401)` + reason="malformed".
     3. `verify_webhook_signature` timestamp 5분 초과 → `WebhookSignatureInvalidError(401)` + reason="outside tolerance".
     4. `verify_webhook_signature` signature mismatch(다른 secret) → `WebhookSignatureInvalidError(401)` + reason="mismatch".
     5. `verify_webhook_signature` `hmac.compare_digest` 사용 검증 — `unittest.mock.patch("hmac.compare_digest")` 호출 검증(*timing-safe 비교 invariant 가드*).
     6. `TossWebhookEventBody` Pydantic — happy-path validation + 미지원 `event_type` 필드 거부.

2. **AC2 — `_validate_idempotency_key_uuid_v4` 공통 helper 분리 (DF49 흡수)**
   **Given** DF49 *"Story 6.x 결제 webhook idempotency 도입 시점에 cross-cutting 분리 검토"* + Story 2.5 `_validate_idempotency_key`(`api/app/api/v1/meals.py:131`) + Story 6.1 `_validate_payment_idempotency_key`(`api/app/api/v1/payments.py:67`) — *동일 검증 로직*(UUID v4 regex + length 36 + None/공백 정규화), *catalog code prefix만 다름*(`meals.*` vs `payments.*`), **When** 본 스토리에서 webhook idempotency를 추가해 *3번째 도메인* 등장, **Then**:
   - **신규 모듈** `api/app/core/idempotency.py` — UUID v4 검증 helper SOT:
     ```python
     """Idempotency-Key UUID v4 검증 helper SOT (DF49 흡수, Story 6.3).

     RFC 4122 v4 regex + length 36 검증. None/빈/공백 패딩은 None 정규화(미송신 등가).
     비공백 패딩 후 형식 위반은 raise — 도메인별 *예외 클래스만* 다름.
     """
     from __future__ import annotations
     import re
     from typing import Final

     _IDEMPOTENCY_KEY_PATTERN: Final[str] = (
         r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
     )
     _IDEMPOTENCY_KEY_REGEX: Final[re.Pattern[str]] = re.compile(_IDEMPOTENCY_KEY_PATTERN)
     _IDEMPOTENCY_KEY_LENGTH: Final[int] = 36


     def validate_idempotency_key_uuid_v4(key: str | None) -> str | None:
         """UUID v4 형식 검증 + None/공백 정규화. *형식 위반은 None 반환(False signal)* —
         호출 측이 도메인 예외를 raise. 본 helper는 검증 로직만 SOT.

         Returns:
             - None: 미송신/빈/공백 패딩 (skip 신호).
             - str (36자): 정규화된 UUID v4 (정상).
             - 예외 raise X — 형식 위반은 ValueError raise(호출 측이 도메인 예외 변환).
         """
         if key is None:
             return None
         stripped = key.strip()
         if not stripped:
             return None
         if len(stripped) != _IDEMPOTENCY_KEY_LENGTH or not _IDEMPOTENCY_KEY_REGEX.match(stripped):
             raise ValueError(f"Idempotency-Key invalid UUID v4 format: len={len(stripped)}")
         return stripped
     ```
   - **`api/app/api/v1/meals.py:_validate_idempotency_key` 갱신** — 본 helper 호출 + `MealIdempotencyKeyInvalidError` 변환:
     ```python
     from app.core.idempotency import validate_idempotency_key_uuid_v4

     def _validate_idempotency_key(key: str | None) -> str | None:
         try:
             return validate_idempotency_key_uuid_v4(key)
         except ValueError as exc:
             raise MealIdempotencyKeyInvalidError(
                 "Idempotency-Key must be a valid UUID v4 (RFC 4122)"
             ) from exc
     ```
   - **`api/app/api/v1/payments.py:_validate_payment_idempotency_key` 갱신** — 동일 패턴 + `PaymentIdempotencyKeyInvalidError` 변환:
     ```python
     from app.core.idempotency import validate_idempotency_key_uuid_v4

     def _validate_payment_idempotency_key(key: str | None) -> str | None:
         try:
             return validate_idempotency_key_uuid_v4(key)
         except ValueError as exc:
             raise PaymentIdempotencyKeyInvalidError(
                 "Idempotency-Key must be a valid UUID v4 (RFC 4122)"
             ) from exc
     ```
   - **`_IDEMPOTENCY_KEY_PATTERN`/`_IDEMPOTENCY_KEY_REGEX`/`_IDEMPOTENCY_KEY_LENGTH` 중복 제거** — `meals.py`/`payments.py`에서 모듈 상수 삭제(helper로 위임). `_IDEMPOTENCY_INDEX_NAME`(payment_service.py)/`_IDEMPOTENCY_INDEX_NAME`(meals.py) 인덱스 이름 상수는 *각 도메인별 유지*(인덱스는 도메인별 분리).
   - **DF49 갱신 결정**(2026-05-09, Story 6.3 시점): *Idempotency-Key cross-cutting 분리는 **함수 helper만 분리***. 예외 계층(`IdempotencyError` base 통합)은 **deferred 유지** — 사유: catalog code prefix(`meals.*`/`payments.*`/`webhook.*`)는 도메인별 분리 정책 + 외주 인수 후 클라이언트별 catalog 분리 정책 확정 후 재검토(Growth). 본 스토리는 *함수 helper 분리만* 수행.
   - **단위 테스트** `api/tests/test_idempotency.py` 신규 ~5건:
     1. `validate_idempotency_key_uuid_v4(None)` → None.
     2. `validate_idempotency_key_uuid_v4("")` → None.
     3. `validate_idempotency_key_uuid_v4("   ")` → None.
     4. `validate_idempotency_key_uuid_v4(uuid.uuid4().hex)` (UUID without dashes) → ValueError.
     5. `validate_idempotency_key_uuid_v4(str(uuid.uuid4()))` → 36-char str 반환.
   - **회귀 가드** — `api/tests/api/v1/test_meals.py` + `api/tests/api/v1/test_payments.py`의 idempotency 테스트가 helper 위임 후에도 통과(0 변경). `MealIdempotencyKeyInvalidError`/`PaymentIdempotencyKeyInvalidError` 변환 흐름이 그대로 작동.

3. **AC3 — alembic 0020 — `payment_logs.provider_payment_key` composite UNIQUE 확장 (D9 흡수)**
   **Given** D9 *"`payment_logs.provider_payment_key` partial UNIQUE가 renew INSERT 차단"* + Story 6.1 0019 인덱스 `idx_payment_logs_provider_payment_key_unique = (provider, provider_payment_key) WHERE provider_payment_key IS NOT NULL` SOT + 같은 paymentKey가 *multiple event_type*(예: `subscribe → refund`/`renew → failed`)으로 INSERT되는 가능성, **When** webhook 처리 시 같은 paymentKey가 다른 event_type으로 들어오는 케이스 흡수, **Then**:
   - **`api/alembic/versions/0020_payment_logs_provider_key_event_type.py` 신규**:
     - `revision: str = "0020_payment_logs_provider_key_event_type"`.
     - `down_revision: str | None = "0019_payment_logs"`.
     - `upgrade()`:
       - `op.drop_index("idx_payment_logs_provider_payment_key_unique", table_name="payment_logs")`.
       - `op.create_index("idx_payment_logs_provider_payment_key_event_type_unique", "payment_logs", ["provider", "provider_payment_key", "event_type"], unique=True, postgresql_where=sa.text("provider_payment_key IS NOT NULL"))`.
     - `downgrade()`:
       - 역순 — composite drop + 원래 partial UNIQUE recreate(D9 미적용 baseline 복귀).
   - **모델 갱신** `api/app/db/models/payment_log.py:__table_args__` — Index 정의도 동기:
     ```python
     Index(
         "idx_payment_logs_provider_payment_key_event_type_unique",
         "provider",
         "provider_payment_key",
         "event_type",
         unique=True,
         postgresql_where=text("provider_payment_key IS NOT NULL"),
     ),
     ```
   - **payment_service.py 인덱스 이름 상수 갱신** — 0019/0020 마이그레이션과 동기. `_IDEMPOTENCY_INDEX_NAME`은 변경 없음(*idempotency_key 인덱스*는 0019 그대로). `provider_payment_key` 충돌 catch는 *본 스토리 webhook 흐름에서만 사용*이라 service 모듈 보다는 *webhook 분기 helper*에서 직접 인덱스명 인용(아래 AC4).
   - **DocStrings + epics.md 인용 보강** — `payment_log.py` docstring 섹션 *"인덱스 3건"* → composite UNIQUE 변경 명시. D9 클로즈.
   - **스키마 회귀 테스트 갱신** `api/tests/test_subscriptions_payment_logs_schema.py` — 기존 `provider_payment_key` partial UNIQUE 검증 테스트(같은 paymentKey 2건 INSERT 시 IntegrityError) → composite UNIQUE 검증으로 *조건 갱신*:
     - 같은 `(provider, provider_payment_key, event_type)` 2건 → IntegrityError(가드 보존).
     - 같은 `(provider, provider_payment_key)` 다른 `event_type` 2건 → 정상 INSERT(D9 흡수 신규 테스트 1건).
   - **alembic upgrade/downgrade 검증** — `cd api && uv run alembic upgrade head` 0020 적용 + `uv run alembic downgrade -1` 0019 복귀 + `uv run alembic upgrade head` 재적용 모두 0 errors.

4. **AC4 — `payment_service.py` webhook 처리 비즈니스 로직 신설**
   **Given** Story 6.1 `subscribe`(라우터→service→adapter→DB) 흐름 SOT + Story 6.2 `cancel_subscription` atomic UPDATE 패턴 SOT + Story 2.5 `_create_meal_idempotent_or_replay` race-free SELECT-INSERT-CATCH-SELECT SOT + Toss webhook event_type 4종(`PAYMENT.STATUS_CHANGED`/`PAYMENT_FAILED`/`REFUND_COMPLETED`/`REFUND_PARTIAL`), **When** webhook 처리 비즈니스 로직 SOT 작성, **Then**:
   - **신규 함수** `payment_service.handle_webhook_event(...)`:
     - `async def handle_webhook_event(session: AsyncSession, *, event_body: TossWebhookEventBody, idempotency_key: str | None) -> tuple[PaymentLog | None, bool]`.
     - Returns `(payment_log, was_replay)` — `payment_log=None`이면 무시된 event(*활성 구독 없는 paymentKey* 등 *200 ack*).
     - **Step 1 — body sub-schema 검증** (`event_body.data` → `TossWebhookPaymentData`):
       - `data = TossWebhookPaymentData.model_validate(event_body.data)` — Pydantic ValidationError → `WebhookPayloadInvalidError(400, code=payments.webhook.payload_invalid)` raise.
       - 본 검증은 *서비스 레이어 책임*(라우터는 outer envelope만 검증, 내부 data sub-schema는 event_type별 분기에 따라 의미가 달라지므로).
     - **Step 2 — Idempotency key 결정**:
       - 우선순위: Header `Idempotency-Key`(이미 `_validate_payment_idempotency_key` 통과한 *36-char UUID v4*) > body `event_id`(36-char 또는 다른 길이 — Toss 표준은 32~64 hex).
       - **결정**: `idempotency_key`(헤더)는 *클라이언트 측 멱등 키*, `event_body.event_id`는 *Toss 측 unique event id*. 둘 다 *별 layer*이지만 **같은 인덱스에 영속화**(DB column 1개 — Story 6.1 baseline). 본 스토리는 *Header 우선*(Toss webhook은 Header 미송신이 표준이지만 send 시 우선) + Header 미송신 시 `event_body.event_id` 사용. 영속화 시 `payment_logs.idempotency_key=key_used`.
       - 정규화: `key_used = idempotency_key if idempotency_key is not None else f"toss:event:{event_body.event_id}"` — Toss event_id에 prefix `toss:event:`로 충돌 방지(우리 측 UUID v4 키와 namespace 분리).
     - **Step 3 — 1차 SELECT (replay 분기)**:
       - `_fetch_payment_log_by_idempotency_key(session, user_id=NULL_FALLBACK, idempotency_key=key_used)` — webhook은 *user_id를 미리 모름*(paymentKey로 lookup 후 결정). 따라서 **신규 helper** `_fetch_payment_log_by_idempotency_key_global(session, idempotency_key)` 추가(`user_id` 무관, idempotency_key만으로 unique 검출).
       - **단, `idx_payment_logs_user_id_idempotency_key_unique`는 (user_id, idempotency_key) 복합 UNIQUE** — `idempotency_key`만으로는 unique 보장 X. **결정**: webhook event는 *DB-wide unique invariant 보장 의무* — 별 namespace prefix(`toss:event:<event_id>`)로 *충돌 가능성 0*(같은 Toss event_id가 다른 사용자에 매핑되는 케이스 부재). 기존 인덱스 사용 + 정상 케이스 SELECT는 0/1건. 다중 row 발견 시 *비정상 상태*(sentry error + 200 ack — 클라이언트 retry 무용).
       - hit 시 → `(existing_log, True)` 반환 + 본 함수 종료(추가 처리 X).
     - **Step 4 — paymentKey로 user_id 결정 + subscription 조회**:
       - `data.payment_key` → `select(PaymentLog).join(Subscription, Subscription.id == PaymentLog.subscription_id, isouter=True).where(PaymentLog.provider == "toss", PaymentLog.provider_payment_key == data.payment_key, PaymentLog.event_type == "subscribe").limit(1)` 1차 조회 — 첫 결제 audit row 발견 시 `user_id` + `subscription_id` 결정.
       - 결과 None → ***subscribe row 부재 paymentKey***(*비정상 — 외부 webhook이지만 우리 DB에 매칭 결제 부재*) → sentry warning + `(None, False)` 반환(라우터가 *200 ack*로 응답 — Toss 재시도 회피).
     - **Step 5 — event_type 분기 (4 branch)**:
       - **(a) `PAYMENT.STATUS_CHANGED` + `data.status="DONE"` (renew 성공)**:
         - active subscription 존재 검증 — `_fetch_active_subscription` 또는 cancelled-but-not-expired(이미 cancelled면 자동 갱신은 비정상 — Sentry error).
         - **renew 처리**:
           - `subscription.expires_at += timedelta(days=MONTHLY_PLAN_PERIOD_DAYS)` — *기존 expires_at 기준*에서 +30일(실 결제일 +30일이 자연 — Toss billing scheme 정합).
           - `subscription.updated_at`은 onupdate auto.
         - `payment_logs` 신규 row INSERT — `event_type="renew"` + `provider="toss"` + `provider_payment_key=data.payment_key` + `provider_order_id=data.order_id` + `amount_krw=data.total_amount` + `status="success"` + `idempotency_key=key_used` + `raw_payload=_mask_payment_payload(event_body.data)` + `occurred_at=data.approved_at or now()` + `subscription_id=subscription.id`.
         - amount mismatch 검증 — `data.total_amount != MONTHLY_PLAN_PRICE_KRW` → `WebhookPayloadInvalidError(400)` (race attack 방어).
       - **(b) `PAYMENT_FAILED` (renew 실패)**:
         - subscription 변경 X(*"다음 시도까지 active 유지"* — 외주 클라이언트가 dunning 정책 결정. MVP는 audit log만).
         - `payment_logs` 신규 row INSERT — `event_type="failed"` + `status="failed"` + `subscription_id=NULL`(실패는 subscription 무관 audit).
         - sentry warning(*"renew 실패 — dunning 정책 검토 필요"*).
       - **(c) `REFUND_COMPLETED` 또는 `REFUND_PARTIAL` (환불)**:
         - subscription 변경 X(즉시 환불은 OUT — Story 6.2 정합 + epics.md:825 *"PG 본 계약·세금정산은 OUT"*).
         - `payment_logs` 신규 row INSERT — `event_type="refund"` + `provider="toss"` + `provider_payment_key=data.payment_key` + `amount_krw=data.total_amount`(환불액 — Toss 표준 +값) + `status="success"` + `idempotency_key=key_used` + `raw_payload=_mask_payment_payload(event_body.data)` + `occurred_at=data.approved_at or now()`.
       - **(d) 미지원 `event_type`** — Step 4의 Pydantic Literal로 1차 차단. service 레벨 도달 X(불가능 case — defensive `BalanceNoteError` raise는 dead code이므로 미작성).
     - **Step 6 — INSERT 시점 race 처리**:
       - INSERT 시 `idx_payment_logs_user_id_idempotency_key_unique` UNIQUE 위반 catch → rollback + 재 SELECT → `(replay_log, True)` 반환.
       - INSERT 시 `idx_payment_logs_provider_payment_key_event_type_unique` UNIQUE 위반 catch → 동일한 `(provider, provider_payment_key, event_type)` 중복(Toss 측 webhook 재전송이지만 우리 측 idempotency_key 누락 케이스 — sentry warning + replay 분기 fallback) → 같은 (provider, payment_key, event_type) row 1건 SELECT 후 `(replay_log, True)` 반환.
     - **Step 7 — Returns** `(payment_log, was_replay)`. commit은 라우터 책임.
   - **신규 helper** `_handle_renew_event(session, *, subscription, data, event_body, key_used)` — Step 5(a) 분리.
   - **신규 helper** `_handle_refund_event(session, *, subscription, data, event_body, key_used)` — Step 5(c) 분리.
   - **신규 helper** `_handle_failed_event(session, *, user_id, data, event_body, key_used)` — Step 5(b) 분리.
   - **인덱스 이름 상수 추가** `_PROVIDER_KEY_EVENT_TYPE_INDEX_NAME = "idx_payment_logs_provider_payment_key_event_type_unique"` — 0020 마이그레이션과 동기.
   - **Sentry**: `payments.webhook.received` info breadcrumb + `payments.webhook.subscribe_row_missing` warning(*비매칭 paymentKey*) + `payments.webhook.cancelled_subscription_renew` error(*cancelled subscription에 renew event* — *외주 운영 incident 신호*).
   - **테스트 ~10건** `api/tests/services/test_payment_service.py` 신규:
     1. `handle_webhook_event` happy-path renew(DONE) → subscription `expires_at` +30일 + `payment_logs` `event_type="renew"` row INSERT.
     2. `handle_webhook_event` PAYMENT_FAILED → subscription 변경 X + `event_type="failed"` row INSERT + sentry warning.
     3. `handle_webhook_event` REFUND_COMPLETED → subscription 변경 X + `event_type="refund"` row INSERT.
     4. `handle_webhook_event` 같은 `event_id` 재전송 → `was_replay=True` + 추가 row INSERT X.
     5. `handle_webhook_event` Header `Idempotency-Key` 우선 — 같은 헤더 재호출 → replay 분기.
     6. `handle_webhook_event` paymentKey 미매칭(subscribe row 부재) → `(None, False)` + sentry warning.
     7. `handle_webhook_event` `data.total_amount=100` mismatch (renew) → `WebhookPayloadInvalidError(400)`.
     8. `handle_webhook_event` cancelled-but-not-expired subscription에 renew → sentry error + 200 ack(*비정상 상태 — 외주 운영 신호 — but Toss 재시도 회피*) + `event_type="renew"` row INSERT(audit-trail은 보존).
     9. `handle_webhook_event` race — 동시 2건 같은 `event_id` → 1건만 INSERT + 다른 1건은 replay 분기.
     10. `handle_webhook_event` `data.total_amount` 음수 → Pydantic 단계 ValidationError → `WebhookPayloadInvalidError(400)`.

5. **AC5 — `POST /v1/payments/webhook` endpoint 신설 (라우터)**
   **Given** AC1-AC4 baseline + Story 6.1 `payments.py` 라우터 SOT + RFC 7807 글로벌 핸들러 + Toss `TossPayments-Webhook-Signature` 헤더 + architecture.md:912 *"`payments.py:webhook` + `Idempotency-Key` 멱등화"*, **When** webhook receipt endpoint 작성, **Then**:
   - **`api/app/api/v1/payments.py`에 추가** — endpoint 시그니처:
     ```python
     @router.post(
         "/webhook",
         status_code=status.HTTP_200_OK,
         response_class=Response,  # 빈 body 200 (Toss ack 표준 — Toss는 응답 body 무시)
         responses={
             200: {"description": "Webhook processed (or idempotent replay or non-matching paymentKey)"},
             400: {"description": "Webhook body schema invalid / amount mismatch / unsupported event_type"},
             401: {"description": "Webhook signature invalid / timestamp outside tolerance"},
             503: {"description": "TOSS_WEBHOOK_SECRET_KEY not configured"},
         },
     )
     async def handle_payment_webhook(
         request: Request,
         db: DbSession,
         signature: Annotated[str | None, Header(alias="TossPayments-Webhook-Signature")] = None,
         idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
     ) -> Response: ...
     ```
   - **Dependency**: 인증 게이트 *없음* — webhook은 server-to-server, JWT 미보유. **시그니처 검증이 인증 SOT**(*HMAC-SHA256 timing-safe*).
   - **흐름**:
     1. `secret = settings.toss_webhook_secret_key` — 빈 문자열 → `WebhookSecretKeyMissingError(503)` raise(글로벌 핸들러가 RFC 7807 응답).
     2. `signature is None` → `WebhookSignatureInvalidError(401, "signature header missing")` raise.
     3. `raw_body = await request.body()` — bytes 보존(JSON 파싱 *전*에 시그니처 검증 의무 — 파싱 후 re-serialize는 위변조 가능).
     4. `toss_adapter.verify_webhook_signature(raw_body=raw_body, signature_header=signature, secret=secret)` 호출 — 실패 시 `WebhookSignatureInvalidError(401)` propagate.
     5. `body_dict = json.loads(raw_body)` — JSON 파싱. 실패(JSONDecodeError) → `WebhookPayloadInvalidError(400, "body not json")`.
     6. `event_body = TossWebhookEventBody.model_validate(body_dict)` — Pydantic 검증. ValidationError → `WebhookPayloadInvalidError(400, code=payments.webhook.payload_invalid)`.
     7. `validated_key = _validate_payment_idempotency_key(idempotency_key)` — 헤더 송신 시 형식 검증.
     8. `payment_log, was_replay = await payment_service.handle_webhook_event(db, event_body=event_body, idempotency_key=validated_key)`.
     9. `await db.commit()` — 트랜잭션 commit.
     10. `return Response(status_code=200)` — 빈 body(Toss ack 표준).
   - **에러 매핑** (RFC 7807 + `code` 카탈로그):
     - 400 `code=payments.webhook.payload_invalid` — `WebhookPayloadInvalidError`.
     - 400 `code=payments.idempotency_key.invalid` — Header 형식 위반(Story 6.1 catalog 재사용).
     - 401 `code=payments.webhook.signature_invalid` — `WebhookSignatureInvalidError`(시그니처 미통과 + timestamp drift + header missing 모두 단일 코드).
     - 503 `code=payments.webhook.secret_key_missing` — `WebhookSecretKeyMissingError`.
   - **Sentry**: 401(signature invalid) + 503(secret missing)은 글로벌 핸들러가 자동 capture. 추가로 *명시 capture*:
     - 401 발생 시 `sentry_sdk.capture_message("payments.webhook.signature_invalid", level="warning", extras={"reason": ...})` — 운영 dashboard alert(*잠재적 위변조 시도 감지*) + Sentry tag 분리.
     - 503 발생 시 `sentry_sdk.capture_message("payments.webhook.secret_missing", level="error", extras={"environment": ...})` — *production fail-fast* 신호(*외주 인수 시 secret 미설정 incident*).
   - **로깅**: `logger.info("payments.webhook.received", event_type=..., event_id_prefix=event_id[:8])` + `logger.info("payments.webhook.processed", event_type=..., was_replay=was_replay, payment_log_id=...)` + 실패 시 `logger.warning("payments.webhook.signature_invalid", reason=...)` + sentry breadcrumb.
   - **rate limit**: default `["1000/hour", "60/minute"]` 자동 적용. webhook은 *Toss 측 retry*가 1분 cap이라 default 충분. 추가 데코레이터 X.
   - **OpenAPI 문서화**:
     - `responses` dict에 401/503 명시 — auto-generated 클라이언트가 *서버 webhook을 호출하지 않으므로* TS 타입 미사용이지만 docs.json 정합 위해 명시.
     - DF137 baseline 연속(글로벌 RFC 7807 응답 schema 일괄 등록은 Story 8.4 forward).
   - **신규 예외 추가** `api/app/core/exceptions.py`:
     - `WebhookSignatureInvalidError(PaymentError)` — `status=401` + `code="payments.webhook.signature_invalid"` + `title="Webhook signature invalid"`.
     - `WebhookPayloadInvalidError(PaymentError)` — `status=400` + `code="payments.webhook.payload_invalid"` + `title="Webhook payload invalid"`.
     - `WebhookSecretKeyMissingError(PaymentError)` — `status=503` + `code="payments.webhook.secret_key_missing"` + `title="Webhook secret key not configured"`.

6. **AC6 — `expires_at` 만료 sweep cron + lazy gate (DF135 흡수)**
   **Given** Story 4.2 `register_nudge_job`(APScheduler 5번째 lifespan 자원) SOT + Story 5.2 `register_purge_job` SOT + DF135 *"`get_subscription` active branch `expires_at > now()` 게이트 부재 — webhook race window에서 active-but-expired row 노출 가능"* + epics.md:854 *"해지 후 다음 결제 주기 도래 시 webhook 처리(Story 6.3)로 `subscriptions.status=expired`"*, **When** expires_at 만료 자동 전이를 정식 처리, **Then**:
   - **신규 worker** `api/app/workers/subscription_expire.py`:
     - `register_subscription_expire_job(scheduler, session_maker, redis) -> None` — `nudge_scheduler.py` 패턴 1:1 정합.
     - **schedule**: 매시 정각 KST(`CronTrigger(minute=0)`) — webhook 부재 케이스(Toss 미통보) 안전판. 자정/저녁/아침 모두 균등 sweep.
     - **redis-backed lock**: `cache:lock:subscription_expire_sweep` — 30분 TTL(같은 시간 다중 인스턴스 차단). Story 4.2 `nudge_sweep` 패턴 정합.
     - **로직**:
       1. `select(Subscription).where(Subscription.status == 'active', Subscription.expires_at < now()).limit(100)` — 100건 cap(*초과 시 다음 sweep 시점에 처리*).
       2. 각 row → `subscription.status = "expired"` UPDATE(`updated_at` auto onupdate). audit log INSERT *없음*(*expired 전이는 단순 timer event — 별 audit-trail 가치 없음, payment_logs는 결제 이벤트 audit만*). cancelled-but-expired는 *취급 X*(이미 cancelled — 그대로 유지, 사용자 view에선 expired와 동등).
       3. 완료 시 `logger.info("subscription_expire.swept", count=...)`.
     - **graceful**: `session_maker is None` → skip + warning(Story 5.2 패턴 정합). `redis is None` → in-memory lock 대체(Story 4.2 패턴 정합).
   - **`api/app/main.py:lifespan` 갱신**:
     - 기존 `register_nudge_job` + `register_purge_job` 다음에 `register_subscription_expire_job(scheduler, app.state.session_maker, app.state.redis)` 추가.
     - import 추가: `from app.workers.subscription_expire import register_subscription_expire_job`.
     - 환경 분기: `_NON_PROD_ENVIRONMENTS = {"ci", "test"}` skip은 그대로 — sweep cron은 prod만 enable.
   - **`get_subscription` lazy gate 갱신** `api/app/api/v1/payments.py:get_subscription`:
     - 기존 query: `or_(Subscription.status == 'active', (Subscription.status == 'cancelled') & (Subscription.expires_at > now))`.
     - 신규(DF135 흡수): active branch에도 `(expires_at > now())` 게이트 추가:
       ```python
       or_(
           # active branch — sweep cron이 expired 전이 전에도 lazy gate로 안전.
           (Subscription.status == "active") & (
               Subscription.expires_at.is_(None) | (Subscription.expires_at > now)
           ),
           # cancelled-but-not-expired (Story 6.2 baseline 유지).
           (Subscription.status == "cancelled") & (Subscription.expires_at > now),
       )
       ```
     - 의미론 변화 0(invariant 보존) — sweep cron 도달 전까지 active row가 *expires_at 도래*해도 *유효* 구독으로 노출되지 않게(DF135 race window 차단).
   - **테스트 신규 ~4건** `api/tests/workers/test_subscription_expire.py` 신규:
     1. happy-path — 3건 active(2건 expired, 1건 미도래) → 2건만 status=expired 전이 + 1건 active 유지.
     2. 100건 cap — 150건 expired 시 100건만 처리 + sentry warning(*queue 누적*).
     3. lock 보유 — 동시 2 instance → 1건만 sweep 진입.
     4. graceful skip — `session_maker is None` 또는 `redis is None` → no-op + warning log.
   - **테스트 신규 ~2건** `api/tests/api/v1/test_payments.py`:
     1. `GET /subscription` active-but-expired(`expires_at < now()` + `status='active'` row 존재) → 404 + `code=payments.subscription.not_found`(DF135 회귀 가드).
     2. `GET /subscription` 정상 active(`expires_at > now()`) → 200 + `status="active"`(회귀 0건 가드).

7. **AC7 — README §5.4.5 + runbook §7 — webhook SOP + secret rotation**
   **Given** Story 6.1 README §5.4 *"결제 PG 연동 (Toss Payments sandbox)"* + Story 6.2 §5.4.4 *"해지 / 결제 이력 흐름"* + epics.md:855 *"README에 *PG 본 계약·세금처리 가이드* 1페이지 명문화"* + Story 6.1 runbook §6 *"TOSS_SECRET_KEY 회전 5단계"*, **When** webhook 운영 SOP 추가, **Then**:
   - **`README.md` §5.4 끝에 sub-section 추가** *"5.4.5 webhook 수신 흐름 (Story 6.3)"*:
     - **셋업 5단계**:
       1. Toss 콘솔 *"개발자 도구 > Webhook"*에서 신규 endpoint 등록 — URL `https://<api-host>/v1/payments/webhook` + 이벤트 4종 구독(`PAYMENT.STATUS_CHANGED`/`PAYMENT_FAILED`/`REFUND_COMPLETED`/`REFUND_PARTIAL`).
       2. Toss 콘솔에서 발급되는 *웹훅 secret*(`whsec_*` 또는 `wsk_*` prefix) 복사.
       3. `.env`에 `TOSS_WEBHOOK_SECRET_KEY=<whsec_...>` 설정. **secret_key와 별 키** — 혼동 회피.
       4. 컨테이너 재배포 — `docker-compose up -d` 또는 Railway redeploy.
       5. Toss 콘솔에서 *"테스트 webhook 발송"* — 시그니처 검증 + DB 적용 검증.
     - **시그니처 검증 흐름** 4-5줄:
       - *"`TossPayments-Webhook-Signature: t=<unix>,v1=<base64_hmac_sha256>` 헤더로 webhook 요청을 검증. HMAC-SHA256(secret, `<unix>.<raw_body>`) + `hmac.compare_digest`(timing-safe). timestamp drift 5분 초과 → 401 reject(replay attack 차단)."*
       - *"미통과 시 sentry warning + 401 응답 + Toss 재시도 진입(Toss 표준 1분 backoff). 재시도 후에도 미통과 시 Toss 콘솔에서 webhook 비활성."*
     - **이벤트 분기** 4-5줄:
       - *"`PAYMENT.STATUS_CHANGED` + `data.status='DONE'`(renew 성공) → `subscriptions.expires_at +=30일` + `payment_logs` `event_type='renew'` row INSERT."*
       - *"`PAYMENT_FAILED`(renew 실패) → `subscriptions` 변경 X + `event_type='failed'` audit row + sentry warning(dunning 정책 검토 신호)."*
       - *"`REFUND_COMPLETED`/`REFUND_PARTIAL` → `subscriptions` 변경 X + `event_type='refund'` audit row(즉시 환불은 OUT — Story 6.2 정합)."*
     - **expires_at 만료 처리** 3-4줄:
       - *"webhook 도래 전(Toss 미통보 케이스 안전판) — `app/workers/subscription_expire.py` APScheduler 매시 정각 sweep으로 `expires_at < now() AND status='active'` row를 `expired` 전이."*
       - *"`GET /v1/payments/subscription` lazy gate — 사용자 polling이 sweep 도달 전이라도 `(expires_at IS NULL OR expires_at > now())` 게이트로 active-but-expired race window 차단(DF135 흡수)."*
     - **멱등 처리** 3-4줄:
       - *"Idempotency 다층 게이트 — Header `Idempotency-Key`(send 시) > body `eventId`(`toss:event:<event_id>` namespace) > `payment_logs.idempotency_key` partial UNIQUE(SELECT-INSERT-CATCH-SELECT race-free 패턴, Story 2.5/6.1 SOT 정합)."*
       - *"같은 `event_id` 재전송 → 200 OK ack + 추가 row INSERT X(Toss 측 retry 정합)."*
   - **`docs/runbook/secret-rotation.md` §7 추가** *"7. TOSS_WEBHOOK_SECRET_KEY 회전 5단계"*:
     1. Toss 콘솔에서 신규 webhook secret 발급(겹침 — 구 secret도 일정 기간 유효).
     2. Railway/staging 환경 변수 `TOSS_WEBHOOK_SECRET_KEY_NEW` 추가(겹침 deploy).
     3. API 컨테이너 재배포 + Toss 콘솔 *"테스트 webhook"* 1건 dry-run(시그니처 검증 정합).
     4. `TOSS_WEBHOOK_SECRET_KEY` ← `TOSS_WEBHOOK_SECRET_KEY_NEW` 갱신 + `TOSS_WEBHOOK_SECRET_KEY_NEW` 삭제 + 컨테이너 재배포.
     5. Toss 콘솔에서 구 webhook secret revoke.
     - SOP 강조 — *"prod 회전 시 1단계 신규 secret이 발급된 후 5단계 revoke 사이의 *겹침 기간*에 발생한 webhook은 `current` 또는 `new` 둘 중 하나로 인증되므로 안전. 본 스토리 baseline은 *current secret 단일*이라 겹침 처리 *없음* — Story 8.4 hardening forward(*dual-secret 동시 검증* 옵션)."*
   - **본 스토리는 README + runbook 외 docs 변경 0건** — `docs/sop/` 4종은 SOP 별 도메인이라 무관.

8. **AC8 — 라우터 + endpoint + 테스트 신규 (CR/QA 위임 unit + integration)**
   **Given** AC1-AC7 baseline + Story 6.1 baseline pytest **1117 passed** + Story 6.2 종료 **1151 passed / 11 skipped / 0 failed** + coverage **85.45%** + ruff/format/mypy/tsc/lint 0 errors, **When** 본 스토리 종료, **Then**:
   - **신규 단위 테스트 ~28건**:
     - `api/tests/adapters/test_toss.py` 신규 ~6건(AC1: signature verify happy/malformed/timestamp/mismatch/timing-safe-invariant + body schema).
     - `api/tests/test_idempotency.py` 신규 ~5건(AC2: helper 5 케이스).
     - `api/tests/services/test_payment_service.py` 신규 ~10건(AC4: webhook 처리 10 케이스 + 신규 helper 분기).
     - `api/tests/workers/test_subscription_expire.py` 신규 ~4건(AC6: sweep happy/cap/lock/graceful).
     - `api/tests/api/v1/test_payments.py` 신규 ~7건:
       1. `POST /webhook` `TOSS_WEBHOOK_SECRET_KEY` 미설정 → 503 + `code=payments.webhook.secret_key_missing`.
       2. `POST /webhook` 헤더 missing → 401 + `code=payments.webhook.signature_invalid`.
       3. `POST /webhook` 시그니처 mismatch → 401 + sentry warning + Toss retry 정합 응답.
       4. `POST /webhook` happy-path renew → 200 + `subscription.expires_at` +30일 + `payment_logs.event_type="renew"` row INSERT 검증.
       5. `POST /webhook` 같은 `event_id` 재전송 → 200 + 추가 row INSERT X(replay 분기).
       6. `POST /webhook` body schema 위반(`event_type` 누락) → 400 + `code=payments.webhook.payload_invalid`.
       7. `POST /webhook` paymentKey 미매칭(subscribe row 부재) → 200 + sentry warning + `payment_logs` row INSERT X.
       - `GET /subscription` active-but-expired → 404 (DF135 회귀 가드).
       - `GET /subscription` 정상 active 회귀 0건 가드.
     - `api/tests/test_subscriptions_payment_logs_schema.py` 갱신 ~2건(AC3: composite UNIQUE 검증 + 같은 paymentKey 다른 event_type 정상 INSERT).
     - `api/tests/test_exceptions_payments.py` 확장 ~3건(`WebhookSignatureInvalidError` + `WebhookPayloadInvalidError` + `WebhookSecretKeyMissingError` 인스턴스화 + RFC 7807 dict shape).
   - **본 스토리 종료 시 목표**: pytest **~1179 passed / 11 skipped / 0 failed** + coverage ≥85.0% 유지(신규 코드 ~350 lines + 신규 테스트 ~28건 = +~120 lines covered).
   - **회귀 0건 가드**:
     - Story 6.1 `POST /v1/payments/subscribe` happy/replay/4xx/5xx — 영향 0건(본 스토리는 webhook endpoint 신설 + helper 분리만).
     - Story 6.1 `_validate_payment_idempotency_key` — *helper 위임 후*에도 같은 분기 작동(catalog code 유지).
     - Story 2.5 `_validate_idempotency_key`(meals.py) — *helper 위임 후*에도 같은 분기 작동.
     - Story 6.2 `POST /v1/payments/cancel` + `GET /v1/payments/history` — 영향 0건(scope 분리).
     - Story 6.2 `GET /v1/payments/subscription` cancelled-but-not-expired — *영향 1건*(active branch에 `expires_at > now()` 추가 — DF135 흡수). 6.2 baseline 테스트는 active fixture가 `expires_at = started_at + 30일`(`now + 30일`)이라 모든 회귀 0(active-but-expired는 *신규 케이스*).
     - Story 5.2 `register_purge_job` — 영향 0건(별 worker, sweep 시간대 다름).
     - Story 4.2 `register_nudge_job` — 영향 0건(별 worker).
     - Story 3.x analysis — 영향 0건.
     - Story 2.x meals — 영향 0건(helper 분리 회귀 가드 0건).
     - alembic upgrade(0019 → 0020) + downgrade(0020 → 0019) 모두 0 errors.
   - **타입 체크**: ruff/format/mypy 0 errors(api) + web/mobile tsc + lint 0 errors(웹/모바일 변경 0건이지만 pnpm lint 필수).
   - **OpenAPI schema diff**: 신규 endpoint 1건(`POST /v1/payments/webhook`) + 신규 응답 모델 0건(빈 body 200). web/mobile `pnpm gen:api`는 *서버측 webhook을 호출하지 않으므로* 클라이언트 코드 변경 X(generated dict에 `paths."/v1/payments/webhook".post` 명세 추가만 — TS 타입 미사용).
   - **manual smoke** (CR/QA 위임 — DS는 unit test로 functional verification):
     - Toss 콘솔 sandbox에서 webhook *테스트 발송* — 시그니처 검증 200 + DB 적용 정합.
     - `expires_at`을 *과거 시점*으로 강제 변경(SQL UPDATE) → APScheduler sweep job 수동 trigger → `status='expired'` 전이 검증.
     - sandbox 결제 1건 진행 → Toss 콘솔에서 *부분 환불* 시뮬레이션 → webhook `REFUND_PARTIAL` 수신 → `payment_logs.event_type='refund'` row INSERT 검증.

9. **AC9 — sprint-status / Story Status 갱신 흐름**
   **Given** 메모리 정합 *"CS 시작 전 master에서 브랜치 분기 — DS 종료시 commit + push만"* + *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신해 PR commit에 포함"*, **When** 본 스토리 `ready-for-dev` 시점(CS 종료) 및 후속 단계, **Then**:
    - Branch: `story/6.3-payment-webhook`(master에서 분기 — CS 시작 전 분기 의무, 본 스토리 CS 시작 직전 분기 완료).
    - DS 시작: `6-3-결제-webhook-idempotency-키: ready-for-dev → in-progress`.
    - DS 종료: `6-3-결제-webhook-idempotency-키: in-progress → review` + commit + push(PR 생성 X — CR 완료 후 일괄).
    - CR 종료 직전: `review → done` + commit + push(같은 commit에 sprint-status 갱신 포함).
    - PR 생성: CR 완료 후 1회. PR title: `Story 6.3: 결제 webhook + Idempotency-Key 멱등 + 이력 (DS+CR) — Epic 6 close`.
    - **Epic 6 마지막 스토리** — `epic-6: in-progress → done`도 본 스토리 CR 종료 직전 같은 commit에 포함(epics.md:825-869 Epic 6 모두 done).

## Tasks / Subtasks

### Task 1 — `WebhookSignatureInvalidError` + `WebhookPayloadInvalidError` + `WebhookSecretKeyMissingError` 신규 (AC: #1, #5)

- [x] 1.1 `api/app/core/exceptions.py` — `PaymentError` 계층 하위에 3 클래스 추가:
  - `WebhookSignatureInvalidError` (status=401, code=`payments.webhook.signature_invalid`, title=`Webhook signature invalid`).
  - `WebhookPayloadInvalidError` (status=400, code=`payments.webhook.payload_invalid`, title=`Webhook payload invalid`).
  - `WebhookSecretKeyMissingError` (status=503, code=`payments.webhook.secret_key_missing`, title=`Webhook secret key not configured`).
- [x] 1.2 `api/tests/test_exceptions_payments.py` 확장 ~3건 — code/status/title 인스턴스화 검증.

### Task 2 — `_validate_idempotency_key_uuid_v4` helper 분리 (AC: #2)

- [x] 2.1 `api/app/core/idempotency.py` 신규 — `validate_idempotency_key_uuid_v4(key)` helper SOT(36-char UUID v4 regex + None/공백 정규화 + ValueError raise).
- [x] 2.2 `api/app/api/v1/meals.py:_validate_idempotency_key` — helper 위임 + `MealIdempotencyKeyInvalidError` 변환.
- [x] 2.3 `api/app/api/v1/payments.py:_validate_payment_idempotency_key` — helper 위임 + `PaymentIdempotencyKeyInvalidError` 변환.
- [x] 2.4 중복 모듈 상수 제거 — `_IDEMPOTENCY_KEY_PATTERN`/`_IDEMPOTENCY_KEY_REGEX`/`_IDEMPOTENCY_KEY_LENGTH`(meals.py + payments.py 양쪽).
- [x] 2.5 `api/tests/test_idempotency.py` 신규 ~5건 — None/empty/whitespace/invalid/valid 케이스.

### Task 3 — alembic 0020 + `payment_logs` composite UNIQUE 갱신 (AC: #3)

- [x] 3.1 `api/alembic/versions/0020_payment_logs_provider_key_event_type.py` 신규:
  - `down_revision = "0019_payment_logs"`.
  - `upgrade()`: `idx_payment_logs_provider_payment_key_unique` drop → `idx_payment_logs_provider_payment_key_event_type_unique = (provider, provider_payment_key, event_type) WHERE provider_payment_key IS NOT NULL` partial UNIQUE create.
  - `downgrade()`: 역순.
- [x] 3.2 `api/app/db/models/payment_log.py` — `__table_args__` Index 정의 갱신(composite UNIQUE) + docstring 갱신(D9 클로즈).
- [x] 3.3 `api/tests/test_subscriptions_payment_logs_schema.py` — 기존 partial UNIQUE 테스트를 composite UNIQUE 테스트로 갱신 + 같은 paymentKey 다른 event_type 정상 INSERT 신규 1건 추가.
- [x] 3.4 `cd api && uv run alembic upgrade head` 0020 적용 → `uv run alembic downgrade -1` 0019 복귀 → `uv run alembic upgrade head` 재적용 0 errors.

### Task 4 — Toss webhook 시그니처 검증 어댑터 (AC: #1)

- [x] 4.1 `api/app/core/config.py` — `toss_webhook_secret_key: str = ""` 추가(기존 `toss_secret_key` 다음).
- [x] 4.2 `api/app/adapters/toss.py` — `verify_webhook_signature(*, raw_body, signature_header, secret, now_unix=None) -> None` 추가(HMAC-SHA256 + `hmac.compare_digest` + 5분 timestamp window).
- [x] 4.3 `api/app/adapters/toss.py` — `TossWebhookEventBody`(eventId/eventType/createdAt/data) + `TossWebhookPaymentData`(paymentKey/orderId/status/totalAmount/approvedAt) Pydantic 모델 추가.
- [x] 4.4 `api/app/adapters/toss.py` — `TOSS_WEBHOOK_SIGNATURE_HEADER` + `_TIMESTAMP_TOLERANCE_SECONDS` 모듈 상수.
- [x] 4.5 `api/tests/adapters/test_toss.py` 신규 ~6건 — verify happy/malformed/timestamp/mismatch/timing-safe-mock + body schema validation.

### Task 5 — `payment_service.handle_webhook_event` (AC: #4)

- [x] 5.1 `api/app/services/payment_service.py` — `_PROVIDER_KEY_EVENT_TYPE_INDEX_NAME` 상수 추가(0020 정합).
- [x] 5.2 `api/app/services/payment_service.py` — `_fetch_payment_log_by_idempotency_key_global(session, idempotency_key) -> PaymentLog | None` helper 추가(user_id 무관 SELECT).
- [x] 5.3 `api/app/services/payment_service.py` — `_handle_renew_event(session, *, subscription, data, event_body, key_used)` helper.
- [x] 5.4 `api/app/services/payment_service.py` — `_handle_failed_event(session, *, user_id, data, event_body, key_used)` helper.
- [x] 5.5 `api/app/services/payment_service.py` — `_handle_refund_event(session, *, subscription, data, event_body, key_used)` helper.
- [x] 5.6 `api/app/services/payment_service.py` — `handle_webhook_event(session, *, event_body, idempotency_key) -> tuple[PaymentLog | None, bool]` 메인 dispatcher.
- [x] 5.7 `api/tests/services/test_payment_service.py` 신규 ~10건 — AC4 정의 10 케이스(renew happy/failed/refund/replay-eventId/replay-header/missing-paymentKey/amount-mismatch/cancelled-renew-incident/race/amount-negative).

### Task 6 — `POST /v1/payments/webhook` endpoint (AC: #5)

- [x] 6.1 `api/app/api/v1/payments.py` — `handle_payment_webhook` endpoint 추가(시그니처 검증 → JSON 파싱 → Pydantic → service 호출 → commit → 200 빈 body).
- [x] 6.2 `api/app/api/v1/payments.py` — Sentry 명시 capture(401 signature_invalid + 503 secret_missing).
- [x] 6.3 `api/tests/api/v1/test_payments.py` 신규 ~7건 — endpoint 7 케이스(secret-missing/signature-missing/mismatch/happy-renew/replay/payload-invalid/missing-paymentKey).

### Task 7 — `expires_at` 만료 sweep cron + lazy gate (AC: #6, DF135)

- [x] 7.1 `api/app/workers/subscription_expire.py` 신규 — `register_subscription_expire_job(scheduler, session_maker, redis)` (`CronTrigger(minute=0)` + redis lock + 100건 cap).
- [x] 7.2 `api/app/main.py:lifespan` — `register_subscription_expire_job` 등록(Story 4.2/5.2 패턴 정합).
- [x] 7.3 `api/app/api/v1/payments.py:get_subscription` — active branch에 `(expires_at IS NULL OR expires_at > now())` 게이트 추가(DF135 흡수).
- [x] 7.4 `api/tests/workers/test_subscription_expire.py` 신규 ~4건 — happy/cap/lock/graceful.
- [x] 7.5 `api/tests/api/v1/test_payments.py` 신규 ~2건 — `GET /subscription` active-but-expired 404 + 정상 active 회귀.

### Task 8 — README §5.4.5 + runbook §7 (AC: #7)

- [x] 8.1 `README.md` §5.4 끝에 *"5.4.5 webhook 수신 흐름 (Story 6.3)"* sub-section 추가 — 셋업 5단계 + 시그니처 검증 4-5줄 + 이벤트 분기 4-5줄 + expires_at 처리 3-4줄 + 멱등 처리 3-4줄.
- [x] 8.2 `docs/runbook/secret-rotation.md` §7 추가 — `TOSS_WEBHOOK_SECRET_KEY` 회전 5단계.

### Task 9 — 통합 검증 + 회귀 가드 + Epic 6 close (AC: #8, #9)

- [x] 9.1 sprint-status `6-3-결제-webhook-idempotency-키: ready-for-dev → in-progress` (DS 시작 시).
- [x] 9.2 `cd api && uv run pytest -q` — Story 6.2 baseline **1151 passed** + 신규 ~28건 = ~**1179 passed / 11 skipped / 0 failed**. 회귀 0건. coverage ≥85.0% 유지.
- [x] 9.3 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` 0 errors.
- [x] 9.4 `cd web && pnpm tsc --noEmit && pnpm lint` 0 errors (변경 0건이지만 회귀 가드).
- [x] 9.5 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 errors (변경 0건이지만 회귀 가드).
- [x] 9.6 OpenAPI schema diff 검증 — 신규 endpoint 1건(`POST /v1/payments/webhook`). CI 게이트 통과.
- [x] 9.7 `cd api && uv run alembic upgrade head` 0020 적용 + `uv run alembic check` no-op + `uv run alembic downgrade -1` 0019 복귀 + 재적용 모두 0 errors.
- [x] 9.8 manual smoke(CR/QA 위임). DS 단계는 unit test ~1179 passed + tsc/lint 0 errors로 functional verification 완료.
- [x] 9.9 sprint-status `6-3-결제-webhook-idempotency-키: in-progress → review` 갱신. commit + push.
- [x] 9.10 CR 종료 직전 — sprint-status `6-3-결제-webhook-idempotency-키: review → done` + `epic-6: in-progress → done` 같은 commit에 포함(Epic 6 close).

### Review Findings

CR 3-layer (Blind Hunter / Edge Case Hunter / Acceptance Auditor, 2026-05-10).원본 raw findings는 verification 거쳐 dismiss/merge 후 아래로 정리.

#### Decision-needed (resolved 2026-05-10, hwan)

- [x] [Review][Decision→Defer] **D1 — Toss billingKey paymentKey rotation 가정 검증** — `_resolve_subscription_for_payment_key`(`payment_service.py:707-726`)가 `event_type='subscribe'` row 1건에만 의존, Toss billingKey 자동결제가 매 결제 새 paymentKey 발급 시 모든 renew webhook silent drop. **Decision**: prod 전환 시점(Story 8.x — Toss billing API 통합 + `subscriptions.billing_key` 컬럼 도입)으로 deferred. 현 sandbox baseline은 renew webhook 미발사라 영향 0.
- [x] [Review][Decision→Defer] **D2 — 취소된 구독 자동결제 webhook 정책** — `payment_service.py:773-789` cancelled-but-not-expired 분기 audit row + sentry error만 기록, 차단·환불·알림 없음. **Decision**: epics.md:825 *"PG 본 계약·세금정산은 OUT"* scope-out 정합 — 외주 클라이언트 dunning 정책 결정 사항으로 deferred.
- [x] [Review][Decision→Dismiss] **D3 — `PAYMENT.STATUS_CHANGED` 다중 발행 시 expires_at 다중 가산 위험** — *재검증 결과 안전*. composite UNIQUE `(provider, payment_key, event_type='renew')`(0020 마이그레이션)가 2번째 INSERT를 IntegrityError로 차단 → catch 분기에서 `await session.rollback()` 호출 → ORM-tracked `subscription.expires_at += 30d` 갱신도 동시 unwind → `_fetch_payment_log_by_provider_key_event_type`로 replay return. 다중 가산 발생 안 함. (관련 P8 race recovery 테스트가 이 안전망을 커버해야 함.)
- [x] [Review][Decision→Dismiss] **D4 — 미지원 event_type → 400 vs 200+sentry** — spec deliberate(`payments.py:541-543` Pydantic Literal 위반 400 reject). sandbox에선 400 → Toss retry → Toss 대시보드 자동 disable → ops 즉시 인지가 graceful degrade보다 빠른 신호. prod graceful degrade(200+sentry)는 Story 8.5 hardening forward.

#### Patch — applied 8 / re-classified 3 (2026-05-10)

**Applied (8)**:

- [x] [Review][Patch] **P1 — webhook body 크기 cap** [`api/app/api/v1/payments.py:62-66, 506-528`] — `Content-Length` pre-check + `_WEBHOOK_BODY_MAX_BYTES = 64 KB` 가드. content-length 누락(chunked transfer 등)도 reject. 시그니처 검증 *전* DoS 표면 차단.
- [x] [Review][Patch] **P3 — `subscription.expires_at` lost-update race** [`api/app/services/payment_service.py:766-786`] — ORM mutation을 atomic `UPDATE Subscription SET expires_at = COALESCE(expires_at, :now) + INTERVAL` 패턴으로 교체(Story 6.2 `cancel_subscription` SOT 정합). `func.coalesce` import 추가. 동시 webhook 2건이 같은 snapshot으로 lost-update 하던 race를 SQL expression으로 차단 — 각 UPDATE가 row의 *현재* DB 값에 가산.
- [x] [Review][Patch] **P4 — Pydantic ValidationError str() echo 차단** [`api/app/api/v1/payments.py:531-555`] — `WebhookPayloadInvalidError("webhook body invalid")` / `"webhook payload schema invalid"` 정적 메시지로 변경, 전체 exc는 `logger.warning`에만. RFC 7807 detail 입력 echo + schema hint 누출 차단.
- [x] [Review][Patch] **P6 — Idempotency-Key UUID v4 lowercase 정규화** [`api/app/core/idempotency.py:54`] — `stripped.lower()` 반환. RFC 4122 case-insensitivity 정합 — mixed-case 재시도 멱등성 회귀 차단.
- [x] [Review][Patch] **P8 — race recovery IntegrityError catch path 실 진입 테스트** [`api/tests/services/test_payment_service.py:test_webhook_race_integrity_error_catch_path_recovers`] — `monkeypatch`로 1차 SELECT 첫 호출만 None 강제 → INSERT → composite UNIQUE 위반 catch → `await session.rollback()` + 재 SELECT → `(replay_log, True)` 반환 + `expires_at` 변화 0(rollback이 atomic UPDATE도 unwind) 검증.
- [x] [Review][Patch] **P9 — replay 테스트 expires_at 가드** [`api/tests/services/test_payment_service.py:test_webhook_replay_same_event_id_returns_existing_no_extra_row`] — `assert refreshed.expires_at == original_expires + timedelta(days=30)` (not +60d) assertion 추가. replay 경로 expires_at 무가산 invariant 회귀 가드.
- [x] [Review][Patch] **P10 — alembic 0020 prod-scale lock storm SOP** [`api/alembic/versions/0020_payment_logs_event_unique.py:docstring`] — prod 트래픽 증가 후 본 패턴 재실행 시 `transactional_ddl=False` + `CREATE UNIQUE INDEX CONCURRENTLY` + 별 DROP 마이그레이션 분리 SOP를 docstring에 명시.
- [x] [Review][Patch] **P11 — alembic 0020 pre-flight 중복 데이터 가드** [`api/alembic/versions/0020_payment_logs_event_unique.py:docstring`] — `SELECT ... GROUP BY ... HAVING COUNT(*)>1` pre-flight SQL을 docstring에 명시(prod 적용 전 0건 검증 의무).

**Re-classified (3)**:

- [x] [Review][Patch→Defer] **P2 — webhook endpoint rate-limit** [`api/app/api/v1/payments.py:471`] — slowapi limiter는 `main.py:6` 코멘트가 *"라우터 적용은 후속 스토리"*로 명시. 본 endpoint 단독 적용은 프로젝트 패턴 비일관 — 별 rate-limit rollout 스토리에서 라우터 전반 일괄 적용 forward.
- [x] [Review][Patch→Dismiss] **P5 — signature_invalid Sentry double-fire** — *재검증 결과 false positive*. 글로벌 `BalanceNoteError` 핸들러(`main.py:315`)는 `_problem_response`만 호출, sentry capture 미수행. Sentry SDK 자동 capture는 4xx 미발사 — 명시 `capture_message`가 401/503 운영 신호 SOT. 제거 시 가시성 손실. 현 동작 유지.
- [x] [Review][Patch→Dismiss] **P7 — composite UNIQUE catch event_type 추론** — *재검증 결과 dead-path*. dispatch의 `else` 분기(`payment_service.py:1007-1013`)가 `_handle_*_event` 호출 *전*에 `(None, False)` early-return → INSERT 미발생 → catch 분기 도달 시 `event_type_for_replay` 매핑이 항상 dispatch와 일치(renew/failed/refund 3 정확). 현 코드 옳음.

**Verification**: pytest **1195 passed / 11 skipped / 0 failed** (baseline 1194 → +1 신규 race catch 테스트). coverage **85.32%**. ruff/format/mypy 0 errors.

#### Defer (9)

- [x] [Review][Defer] **W0a — Toss billingKey paymentKey rotation 가정 검증** [`api/app/services/payment_service.py:707-726`] — D1 Decision→Defer. Toss billing 통합 + `subscriptions.billing_key` 컬럼 도입(Story 8.x prod 전환) 시점에 paymentKey rotation 대응 lookup으로 교체.
- [x] [Review][Defer] **W0b — 취소된 구독 자동결제 webhook 정책 (dunning)** [`api/app/services/payment_service.py:773-789`] — D2 Decision→Defer. epics.md:825 PG 본 계약 scope-out 정합 — 외주 클라이언트 정책 결정 사항.
- [x] [Review][Defer] **W1 — service `rollback()` + router `commit()` 트랜잭션 소유권 모호** [`api/app/services/payment_service.py:1018,1030`] — race recovery 시 service가 unilaterally rollback, replay_log fresh SELECT 후 router가 commit. 실용상 동작하지만 spec의 *"commit은 router 책임"* 계약 위반. 8.x 트랜잭션 패턴 정비 시 재검토.
- [x] [Review][Defer] **W2 — Header Idempotency-Key cross-user 충돌 SELECT** [`api/app/services/payment_service.py:682-688`] — `_fetch_payment_log_by_idempotency_key_global`이 user_id 무관 SELECT. UUID v4 자연 충돌은 1/2^122로 무시 가능, namespace prefix(`toss:event:`) 보호도 있지만 Header 경로는 user-scoped 가드 부재. 8.x hardening forward.
- [x] [Review][Defer] **W3 — `_release_lock` GET-then-DEL 비원자** [`api/app/workers/subscription_expire.py:91-95`] — TTL 만료 후 다른 worker 락을 침범 가능. 단일 노드 baseline에선 race 0이지만 multi-replica(Story 8.5) 시 Lua atomic CAS DEL 필수.
- [x] [Review][Defer] **W4 — webhook signature 헤더 `t=` substring 매칭 forward-compat** [`api/app/adapters/toss.py:379-382`] — `startswith("t=")`/`startswith("v1=")`이 너무 permissive — 미래 Toss가 `t1=`/`tn=` 등 추가 시 잘못 매칭. 현 Toss spec 정합이지만 forward drift 시 hardening 필요.
- [x] [Review][Defer] **W5 — whitespace-only Idempotency-Key가 silent하게 멱등성 비활성** [`api/app/core/idempotency.py:50-51`] — `if not stripped: return None`은 미송신 등가 처리. 클라이언트는 송신했다고 믿지만 서버는 미송신 처리 → 재시도 시 중복 결제 가능. Story 6.1 baseline 동작이라 6.3 scope 외 — 8.x에서 strict mode 검토.
- [x] [Review][Defer] **W6 — renew amount 가드가 `MONTHLY_PLAN_PRICE_KRW` 상수 hardcoded** [`api/app/services/payment_service.py:750-764`] — 단일 MVP 플랜 baseline에선 정합. 다중 플랜 도입 시 `subscription.plan_price_krw` 조회로 교체 필수 — 미수정 시 grandfather 사용자 결제가 모두 400 reject.
- [x] [Review][Defer] **W7 — sweep cron 100건 cap이 100+/시간 만료 시 tail row 누적** [`api/app/workers/subscription_expire.py:62`] — 작은 사용자 베이스 baseline OK. cap_exceeded sentry warning은 emit. 스케일 도달 시 pagination 또는 cap 상향.
- [x] [Review][Defer] **W8 — `redis is None` in-memory lock fallback이 multi-worker race 미보호** [`api/app/workers/subscription_expire.py:70-72`] — gunicorn N workers + redis 미설정 시 N개 sweep 동시 진입. DB-level `WHERE status='active' AND expires_at < now` race 가드로 데이터 정합성은 보존되지만 wasted DB load. 단일 노드 baseline 정합.
- [x] [Review][Defer] **W9 — alembic 0020 downgrade 시 누적된 multi-event_type row가 0019 partial UNIQUE 충돌** [`api/alembic/versions/0020_payment_logs_event_unique.py:downgrade`] — 0020 적용 후 renew/refund row 누적된 상태에서 downgrade 시 (provider, payment_key) UNIQUE 위반. recovery 경로 한정 — 일반 운영 영향 없음.
- [x] [Review][Defer] **W10 — webhook endpoint rate-limit 누락 (P2 re-classified)** [`api/app/api/v1/payments.py:471`] — slowapi limiter는 `main.py:6`이 *"라우터 적용은 후속 스토리"*로 명시. 본 endpoint 단독 적용은 프로젝트 패턴 비일관. **재검토 시점**: 별 rate-limit rollout 스토리에서 라우터 전반 일괄 적용.



### 핵심 — 본 스토리는 *Toss webhook 시그니처 검증 + Idempotency 다층 게이트 + renew/failed/refund 분기 + expires_at sweep*

epics.md:857-869 정합 — *FR42 결제 webhook + Idempotency-Key 멱등화* baseline. 핵심 invariant 5개:

1. **시그니처 timing-safe + timestamp 5분 window** — `hmac.compare_digest`(timing-attack 차단) + Stripe 표준 정합 5분 drift cap(replay attack 차단). 미통과 시 401 + Sentry warning + Toss 재시도 진입(Toss 표준 1분 backoff). 본 invariant 위반은 보안 incident 신호.

2. **Toss webhook은 후속 갱신만 처리** — 첫 결제(subscribe)는 Story 6.1 widget success callback이 SOT, webhook은 *renew*(자동 갱신 성공)/*failed*(renew 실패)/*refund*(환불) 3 event 분기. 첫 결제 webhook이 도래하는 경우는 *paymentKey가 subscribe 분기로 이미 INSERT됨* — 멱등 처리(추가 row INSERT X). epics.md:825 *"Stripe/Toss는 자체 retry — 우리는 `Idempotency-Key`로 중복 처리 멱등화"* 정합.

3. **Idempotency 다층 게이트**:
   - Layer 1 (transport): Toss 측 retry는 같은 `eventId` 재전송 (Toss webhook 표준).
   - Layer 2 (application): Header `Idempotency-Key`(send 시) > body `event_id`(`toss:event:<event_id>` namespace) 정규화.
   - Layer 3 (DB): `payment_logs.idempotency_key` partial UNIQUE 인덱스 — race-free SELECT-INSERT-CATCH-SELECT.
   - Story 2.5 `_create_meal_idempotent_or_replay` + Story 6.1 `_subscribe_idempotent_or_replay` SOT 1:1 정합 — 같은 `IntegrityError` catch 패턴.

4. **expires_at 만료 이중 처리** — webhook이 *Toss 측 timer event*가 아니라 *결제 결과 통보*이므로 *expires_at 도래 시점에 webhook이 도착하지 않을 가능성*(Toss 미통보 케이스)을 방어:
   - **APScheduler sweep cron** — 매시 정각 KST `select(Subscription).where(status='active', expires_at < now()).limit(100)` → `status='expired'` UPDATE. Story 4.2/5.2 worker 패턴 정합.
   - **`get_subscription` lazy gate** — sweep 도달 전이라도 `(expires_at IS NULL OR expires_at > now())` 게이트로 active-but-expired race window 차단(DF135 흡수).
   - **결정**: 두 layer 모두 — sweep은 *데이터 정합성*(다른 endpoint도 정상 active만 보게), lazy gate는 *결정성*(polling 응답이 sweep 시점에 의존하지 않게).

5. **D9 흡수** — alembic 0020으로 `payment_logs.provider_payment_key` partial UNIQUE를 composite UNIQUE `(provider, provider_payment_key, event_type)`로 변경. 같은 paymentKey가 *multiple event_type*(예: `subscribe → refund`/`renew → failed`) INSERT 가능. 같은 `(provider, payment_key, event_type)` 중복은 그대로 차단(*같은 결제건 같은 event 2번 INSERT 방지*).

### 주요 결정 — DF49 갱신 + DF135 흡수 + D9 흡수 + 환불 자동화 OUT

#### DF49 — 함수 helper만 분리, 예외 계층 통합은 deferred 유지

- *Idempotency-Key cross-cutting 도메인 격리*는 본 스토리에서 *함수 helper만 분리*(`api/app/core/idempotency.py:validate_idempotency_key_uuid_v4`).
- 예외 계층(`IdempotencyError` base 통합)은 **deferred 유지** — catalog code prefix(`meals.*`/`payments.*`/`payments.webhook.*`)는 도메인별 분리 정책 + 외주 인수 후 클라이언트별 catalog 분리 정책 확정 후 재검토(Growth — Story 8.x forward).
- 본 스토리의 DF49 갱신: *함수 helper 분리 완료* — Story 6.x 후속에서 *4번째 도메인* 도래 시 helper 위임 비용 0(meals/payments/webhook 3 도메인 모두 위임).

#### DF135 — `get_subscription` active branch lazy gate 추가

- Story 6.2 baseline은 active branch에 `expires_at > now()` 게이트 부재 — webhook race window에서 active-but-expired row 노출 가능.
- 본 스토리: active branch에도 `(expires_at IS NULL OR expires_at > now())` 게이트 추가. invariant 변화 0(active 정상 케이스는 expires_at 항상 미래) + 비정상 케이스(active-but-expired)만 차단.
- sweep cron이 정상 작동하면 active-but-expired row는 1시간 안에 expired 전이 → lazy gate는 *fallback*(sweep 부재 / 1시간 race window 안전판).

#### D9 — `payment_logs.provider_payment_key` composite UNIQUE 확장

- Story 6.1 baseline은 `(provider, provider_payment_key) WHERE provider_payment_key IS NOT NULL` partial UNIQUE — 같은 paymentKey 2번 INSERT 차단.
- 본 스토리: composite UNIQUE `(provider, provider_payment_key, event_type)` — 같은 paymentKey가 multiple event_type INSERT 가능(subscribe → refund / renew → failed 등).
- 마이그레이션 0020 — drop 후 recreate. downgrade는 역순.

#### 환불 자동화 OUT — Story 6.2 정합 + epics.md 정합

- 본 스토리는 `REFUND_COMPLETED`/`REFUND_PARTIAL` webhook을 *audit log만* 기록 — `payment_logs.event_type='refund'` row INSERT.
- subscription 변경 X(*"즉시 환불은 OUT — 다음 결제일까지 활성"* Story 6.2 invariant 보존). 외주 클라이언트가 자체 환불 정책 + dunning 흐름 + Toss 환불 API 통합.
- epics.md:825 *"PG 본 계약·세금정산은 OUT(README 가이드 1페이지)"* 정합.

#### Stripe webhook은 forward stub — Story 8.5

- 본 스토리는 Toss 단일 provider 처리. Stripe webhook 어댑터는 *Story 8.5 forward stub*.
- ENUM 값 `stripe`는 Story 6.1 0018/0019에서 forward-compat 등재 완료 — 데이터 모델 변경 0건.
- 라우터는 *Toss-specific*(`TossPayments-Webhook-Signature` 헤더 + `TossWebhookEventBody` 스키마) — Stripe 통합 시 *별 endpoint*(`POST /v1/payments/webhook/stripe`) 또는 *provider 분기 dict*(Story 8.5 결정).

### 파일 변경 목록 (예상 규모)

#### 신규 파일 (5건)

- `api/app/core/idempotency.py` — `validate_idempotency_key_uuid_v4` helper SOT (DF49 흡수, ~30 lines).
- `api/alembic/versions/0020_payment_logs_provider_key_event_type.py` — composite UNIQUE 마이그레이션 (D9 흡수, ~50 lines).
- `api/app/workers/subscription_expire.py` — APScheduler sweep cron + redis lock (~120 lines).
- `api/tests/test_idempotency.py` — helper 단위 테스트 (~60 lines).
- `api/tests/workers/test_subscription_expire.py` — sweep cron 단위 테스트 (~150 lines).

#### 수정 파일 (10건)

- `api/app/core/config.py` — `toss_webhook_secret_key: str = ""` 추가 (~3 lines).
- `api/app/core/exceptions.py` — `WebhookSignatureInvalidError`/`WebhookPayloadInvalidError`/`WebhookSecretKeyMissingError` 3 클래스 추가 (~30 lines).
- `api/app/adapters/toss.py` — `verify_webhook_signature` + `TossWebhookEventBody`/`TossWebhookPaymentData` + `TOSS_WEBHOOK_SIGNATURE_HEADER` 상수 (~120 lines).
- `api/app/services/payment_service.py` — `handle_webhook_event` + 3 helper 분리(`_handle_renew_event`/`_handle_failed_event`/`_handle_refund_event`) + `_fetch_payment_log_by_idempotency_key_global` (~250 lines).
- `api/app/api/v1/payments.py` — `handle_payment_webhook` endpoint + helper 위임 갱신 (~100 lines).
- `api/app/api/v1/meals.py` — `_validate_idempotency_key` helper 위임 (~5 lines).
- `api/app/db/models/payment_log.py` — `__table_args__` Index 갱신 + docstring (~10 lines).
- `api/app/main.py:lifespan` — `register_subscription_expire_job` 등록 (~5 lines).
- `README.md` — §5.4.5 webhook 수신 흐름 SOP (~30 lines).
- `docs/runbook/secret-rotation.md` — §7 `TOSS_WEBHOOK_SECRET_KEY` 회전 5단계 (~15 lines).

#### 갱신/회귀 가드 테스트 (4건)

- `api/tests/adapters/test_toss.py` 확장 ~6건 — webhook 시그니처 + body schema.
- `api/tests/services/test_payment_service.py` 확장 ~10건 — `handle_webhook_event` 10 케이스.
- `api/tests/api/v1/test_payments.py` 확장 ~9건 — webhook endpoint 7 + DF135 회귀 가드 2.
- `api/tests/test_subscriptions_payment_logs_schema.py` 갱신 ~2건 — composite UNIQUE 검증.
- `api/tests/test_exceptions_payments.py` 확장 ~3건 — 신규 예외 3건.

### 핵심 베이스라인 SOT (회귀 가드)

#### Story 6.1 SOT (재사용)

- `app/adapters/toss.py:_mask_payment_payload` — webhook event_body의 `data` 마스킹에 *재사용*(NFR-S5 정합 — `customerEmail`/`customerName`/`card.number` 마스킹 일관).
- `app/services/payment_service.py:_subscribe_idempotent_or_replay` — race-free 패턴 SOT, `handle_webhook_event`도 동일 try/except 흐름 적용.
- `payment_logs.idempotency_key` partial UNIQUE — webhook 멱등 키 SOT(Header/event_id 모두 동일 column에 영속화).
- `payment_logs.provider_payment_key` partial UNIQUE → composite UNIQUE 0020(D9 흡수).
- `MONTHLY_PLAN_PRICE_KRW = 9900` + `MONTHLY_PLAN_PERIOD_DAYS = 30` — webhook renew 처리에 *재사용*(amount 검증 + expires_at +30일 계산).

#### Story 6.2 SOT (재사용 / 의존)

- `cancel_subscription` atomic UPDATE...RETURNING 패턴 — *적용 X*(webhook은 *INSERT 기반*이라 다른 패턴). 단, *동일 timestamp* invariant(`now = datetime.now(UTC)` 단일화 + DB UPDATE/INSERT 모두 같은 timestamp)는 webhook renew/refund에도 적용.
- DF135(`get_subscription` active branch lazy gate 부재) — 본 스토리에서 *흡수*(Task 7.3).
- `_extract_receipt_url` — webhook의 `payment_logs.raw_payload`에 영수증 URL 보존(*history endpoint와 일관*).

#### Story 2.5 SOT (재사용)

- `_create_meal_idempotent_or_replay` — race-free SELECT-INSERT-CATCH-SELECT 패턴 SOT, webhook도 동일 IntegrityError catch 패턴 적용.
- `_validate_idempotency_key` UUID v4 regex — `validate_idempotency_key_uuid_v4` helper로 *분리*(DF49 흡수).

#### Story 4.2 SOT (재사용)

- `register_nudge_job` — APScheduler 등록 패턴 SOT, `register_subscription_expire_job`도 1:1 정합(`CronTrigger` + redis lock + graceful skip).

#### Story 5.2 SOT (재사용)

- `register_purge_job` — graceful skip 패턴(`session_maker is None` / `redis is None` → no-op + warning log) SOT, `register_subscription_expire_job`에 적용.

### 직전 스토리(6.2) 학습

- **CR 패치 7건 모두 P 카테고리**(Patch — 본 스토리에서 즉시 적용) — 본 스토리도 동일 분류 규칙 적용.
- **Atomic UPDATE...RETURNING 패턴** — 동시성 race가 있는 흐름은 SELECT-then-UPDATE 대신 atomic 패턴 우선. 본 스토리 webhook 처리도 *active subscription UPDATE*는 atomic 패턴 검토(*CR P5* — 동시 webhook 2건 같은 paymentKey 들어와도 한 트랜잭션만 row 점유). 결정: webhook은 *멱등 키 partial UNIQUE 1차 게이트* + *INSERT race catch* 패턴이 SELECT-then-UPDATE보다 강력 — atomic UPDATE는 *expires_at +30일 갱신 분기*에만 적용.
- **defense in depth — server에서 receipt_url 마스킹** (Story 6.2 CR P7) — 본 스토리 webhook의 `_handle_refund_event` 등도 동일 패턴(`raw_payload`에 영수증 URL 보존하되 status filter는 server SOT).
- **dismiss 코멘트 회피** (`feedback_no_dismiss_comment_for_false_positive` 메모리) — Story 6.2 CR도 dismiss 항목은 PR 코멘트 X로 처리. 본 스토리 CR도 같은 정합.

### 환경 변수 추가

#### `.env.example`

- `TOSS_WEBHOOK_SECRET_KEY=` (빈 — Toss 콘솔에서 발급받아 staging/prod 설정).

#### `api/.env.example`

- 동일 — repo root `.env`가 SOT(api/.env는 override 옵션).

### 핵심 lifespan 자원 추가 (Story 4.2/5.2 패턴 정합)

`api/app/main.py:lifespan` `register_purge_job` 직후에 `register_subscription_expire_job` 추가:

```python
register_purge_job(
    scheduler,
    app.state.session_maker,
    r2_adapter=_r2_module,
    redis=app.state.redis,
)
# Story 6.3 — expires_at 만료 sweep cron(매시 정각 KST). webhook 미통보 케이스 안전판 +
# DF135 active-but-expired race window 차단의 정식 전이 처리.
register_subscription_expire_job(
    scheduler,
    app.state.session_maker,
    app.state.redis,
)
app.state.scheduler = scheduler
await start_scheduler(app)
```

### 직전 PR 패턴 (정합)

- PR title: `Story 6.X: <description> (DS+CR)` — 본 스토리 마지막이라 *"— Epic 6 close"* suffix 추가.
- PR body: `## Summary` (3-5 bullet) + `## Test plan` (markdown checklist) + Co-Authored-By footer.
- review tag(Gemini Code Assist): repo 전역 활성(피드백 메모리 정합) — draft PR에도 자동 review 코멘트.

### Project Structure Notes

- Alignment with `architecture.md:670` `api/app/api/v1/payments.py` SOT.
- Alignment with `architecture.md:705` `api/app/workers/` 디렉터리 + `architecture.md:704` *worker 패턴 정합*.
- Alignment with `architecture.md:912` *"`payments.py:webhook` + `Idempotency-Key` 멱등화"* 흐름.
- Alignment with `architecture.md:531` *"Stripe/Toss는 자체 retry — 우리는 `Idempotency-Key`로 중복 처리 멱등화"*.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic-6-Story-6.3 — 결제 webhook + Idempotency-Key 멱등 + 이력]
- [Source: _bmad-output/planning-artifacts/architecture.md#integration-points-외부-통합 — Toss/Stripe webhook]
- [Source: _bmad-output/implementation-artifacts/6-1-정기결제-sandbox-신청.md — Toss adapter SOT + payment_service SOT]
- [Source: _bmad-output/implementation-artifacts/6-2-구독-해지-영수증-이용내역.md — atomic UPDATE 패턴 + DF135 deferred]
- [Source: _bmad-output/implementation-artifacts/2-5-오프라인-텍스트-큐잉-sync.md — `_create_meal_idempotent_or_replay` race-free SOT]
- [Source: _bmad-output/implementation-artifacts/4-2-apscheduler-nudge-미기록-푸시.md — APScheduler `register_nudge_job` 패턴 SOT]
- [Source: _bmad-output/implementation-artifacts/5-2-회원-탈퇴-soft-delete-grace.md — `register_purge_job` graceful skip 패턴 SOT]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#D9 — payment_logs composite UNIQUE 확장 deferred]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#DF49 — Idempotency-Key cross-cutting helper 분리 deferred]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md#DF135 — get_subscription active branch expires_at gate deferred]
- [Source: api/app/api/v1/payments.py — Story 6.1/6.2 router SOT]
- [Source: api/app/services/payment_service.py — Story 6.1/6.2 service SOT]
- [Source: api/app/adapters/toss.py — Story 6.1 adapter SOT]
- [Source: api/app/db/models/payment_log.py — Story 6.1 ORM SOT]
- [Source: api/app/db/models/subscription.py — Story 6.1 ORM SOT]
- [Source: api/alembic/versions/0019_payment_logs.py — Story 6.1 마이그레이션 SOT]
- [Source: api/app/workers/nudge_scheduler.py — Story 4.2 worker SOT]
- [Source: api/app/workers/soft_delete_purge.py — Story 5.2 worker SOT]
- [Source: api/app/main.py — lifespan 자원 등록 SOT]
- [Source: api/app/core/exceptions.py — Story 6.1/6.2 PaymentError catalog SOT]
- [Source: api/app/api/v1/meals.py — Story 2.5 `_validate_idempotency_key` SOT]

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m]

### Debug Log References

### Completion Notes List

- 2026-05-09 (Amelia, CS): Story 6.3 컨텍스트 작성 완료. Branch `story/6.3-payment-webhook` 분기 완료(master 기준). Epic 6 마지막 스토리 — CR 종료 직전 `epic-6: in-progress → done` 갱신 의무.
- 2026-05-10 (Amelia, DS): Task 1-9 모두 완료 + 검증 통과:
  - **pytest**: `1194 passed / 11 skipped / 0 failed` (Story 6.2 baseline 1151 → 신규 +43건; 목표 ~1179 초과 — adapter signature/race 변형 추가 케이스 흡수). coverage **85.32%** (목표 ≥85.0% 달성).
  - **ruff/format/mypy**: 0 errors (api).
  - **web/mobile tsc + lint**: 0 errors (변경 0건이지만 회귀 가드 통과).
  - **alembic**: `0020_payment_logs_event_unique` 신규(spec의 *"0020_payment_logs_provider_key_event_type"* revision id가 alembic 표준 `version_num VARCHAR(32)` 한도 초과 → 의미 보존하면서 30자로 단축. composite UNIQUE 정의 동일). upgrade → downgrade → 재 upgrade 0 errors.
  - **OpenAPI**: `pnpm gen:api`(IN_PROCESS=1) 재생성 → `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts`에 `POST /v1/payments/webhook` 명세 추가됨. 기존 endpoint 변경 0건.
  - **DF49 흡수**: 함수 helper 분리만 수행(예외 계층 통합은 Growth deferred 유지). `_validate_idempotency_key` (meals.py) + `_validate_payment_idempotency_key` (payments.py) 양쪽 helper 위임 + 중복 모듈 상수(``_IDEMPOTENCY_KEY_PATTERN``/``_IDEMPOTENCY_KEY_REGEX``/``_IDEMPOTENCY_KEY_LENGTH``) 제거.
  - **D9 흡수**: `payment_logs` partial UNIQUE → composite UNIQUE `(provider, provider_payment_key, event_type) WHERE NOT NULL` 갱신. 같은 paymentKey 다른 event_type INSERT 정상 invariant 추가 테스트 1건 + 같은 (provider, payment_key, event_type) 차단 invariant 회귀 테스트 1건.
  - **DF135 흡수**: `get_subscription` active branch lazy gate `(expires_at IS NULL OR expires_at > now())` 추가. sweep cron 도달 전이라도 active-but-expired race window 차단.
  - **테스트 회귀 0건**: Story 2.5 `meals.py` idempotency / Story 6.1 `_validate_payment_idempotency_key` / Story 6.2 cancel/history / Story 4.2 nudge / Story 5.2 purge — 모두 helper 위임 후 통과.
  - **README §5.4.5 + runbook §7 + .env.example**: webhook 셋업 5단계 + 시그니처 검증 + 이벤트 분기 + expires_at 처리 + 멱등 처리 + secret rotation 5단계.
  - **신규 환경 변수**: `TOSS_WEBHOOK_SECRET_KEY` (.env.example + config.py). 빈 값 허용(dev/ci/test) + 503 fail-fast(prod webhook endpoint).
  - **Sprint status**: `ready-for-dev → in-progress → review` 전이 (DS 종료). PR 생성 보류 — CR 완료 후 일괄 PR(spec AC9 정합).

### File List

신규 파일 (5건):
- `api/app/core/idempotency.py` — UUID v4 검증 helper SOT (DF49 흡수).
- `api/alembic/versions/0020_payment_logs_event_unique.py` — composite UNIQUE 마이그레이션 (D9 흡수).
- `api/app/workers/subscription_expire.py` — APScheduler sweep cron + redis lock + 100건 cap.
- `api/tests/test_idempotency.py` — helper 단위 테스트 5건.
- `api/tests/workers/test_subscription_expire.py` — sweep cron 단위 테스트 5건(happy/cap/lock/graceful + register).

수정 파일 (12건):
- `api/app/core/config.py` — `toss_webhook_secret_key` 추가.
- `api/app/core/exceptions.py` — `WebhookSignatureInvalidError`/`WebhookPayloadInvalidError`/`WebhookSecretKeyMissingError` 3 클래스 추가.
- `api/app/adapters/toss.py` — `verify_webhook_signature` + `TossWebhookEventBody`/`TossWebhookPaymentData` + 모듈 상수 추가.
- `api/app/services/payment_service.py` — `handle_webhook_event` 메인 dispatcher + 3 helper(`_handle_renew_event`/`_handle_failed_event`/`_handle_refund_event`) + `_fetch_payment_log_by_idempotency_key_global` + `_fetch_payment_log_by_provider_key_event_type` + `_resolve_subscription_for_payment_key` + 인덱스 이름 상수.
- `api/app/api/v1/payments.py` — `handle_payment_webhook` endpoint + DF135 lazy gate + helper 위임(DF49).
- `api/app/api/v1/meals.py` — `_validate_idempotency_key` helper 위임(DF49) + 중복 상수 제거.
- `api/app/db/models/payment_log.py` — `__table_args__` Index 갱신 (composite UNIQUE) + docstring D9 클로즈.
- `api/app/main.py:lifespan` — `register_subscription_expire_job` 등록.
- `README.md` — §5.4.5 webhook 수신 흐름 SOP.
- `docs/runbook/secret-rotation.md` — §7 `TOSS_WEBHOOK_SECRET_KEY` 회전 5단계.
- `.env.example` — `TOSS_WEBHOOK_SECRET_KEY` 신규 항목.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 6-3 status `ready-for-dev → review`.

자동 생성 (Generated, 2건):
- `web/src/lib/api-client.ts` — `pnpm gen:api`로 `POST /v1/payments/webhook` 명세 추가.
- `mobile/lib/api-client.ts` — 동상.

테스트 갱신 (5건):
- `api/tests/adapters/test_toss.py` — webhook 시그니처/Pydantic 단위 6건 추가.
- `api/tests/services/test_payment_service.py` — `handle_webhook_event` 단위 10건 추가.
- `api/tests/api/v1/test_payments.py` — webhook endpoint 7건 + DF135 회귀 2건 추가.
- `api/tests/test_subscriptions_payment_logs_schema.py` — composite UNIQUE 회귀 2건 추가(블록/허용 분기).
- `api/tests/test_exceptions_payments.py` — webhook 신규 예외 3건 + to_problem 3건 추가.

### Change Log

- 2026-05-09 — Story 6.3 ready-for-dev (Amelia, CS).
- 2026-05-10 — Story 6.3 review (Amelia, DS): Task 1-9 모두 완료. pytest 1194 passed + coverage 85.32%. ruff/format/mypy/tsc/lint 0 errors. alembic 0020 up/down/up cycle 0 errors. DF49/D9/DF135 모두 흡수. PR 생성 보류 — CR 완료 후 일괄.
