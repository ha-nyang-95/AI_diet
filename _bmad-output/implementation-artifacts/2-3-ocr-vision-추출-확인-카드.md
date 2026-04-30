# Story 2.3: OCR Vision 추출 + 사용자 확인·수정 카드

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **엔드유저**,
I want **사진 업로드 직후 시스템이 OCR로 추출한 음식 항목을 확인·수정하고 분석을 시작하기를**,
So that **잘못 인식된 항목을 미리 바로잡아 분석 정확도가 떨어지지 않는다.**

본 스토리는 Epic 2의 세 번째 스토리로, **(a) 백엔드 `app/adapters/openai.py` Vision 어댑터(GPT-4o + structured outputs + tenacity retry + timeout)**, **(b) `POST /v1/meals/images/parse` endpoint — `image_key` 기반 OCR 사전 호출 + `parsed_items` 응답(name/quantity/confidence)**, **(c) `meals.parsed_items` jsonb nullable 컬럼 + 0008 마이그레이션 — Epic 3 LangGraph 입력 영속화 baseline + Story 2.2 DF2(`(사진 입력)` placeholder collision) 자연 해소**, **(d) `MealCreateRequest`/`MealUpdateRequest`에 `parsed_items` 필드 추가 + 사용자 확인·수정 후 송신 시 raw_text 동시 갱신**, **(e) 모바일 `OCRConfirmCard.tsx` 표준 컴포넌트 — 항목 추가/삭제/양 수정 + 신뢰도 배지 + 강제 확인 임계값 0.6 + Vision 장애 graceful degradation Alert**의 baseline을 박는다.

부수적으로 (a) Epic 3 LangGraph 통합(`parse_meal` 노드 + AsyncPostgresSaver state + `retrieve_nutrition` 노드 chaining)은 **Story 3.3 책임** — 본 스토리는 *standalone OCR endpoint + parsed_items 영속화*까지, (b) Vision 응답을 `meal_analyses`(Epic 3 신규 테이블)에 저장하는 흐름은 Story 3.x — 본 스토리는 `meals.parsed_items` jsonb 단일 컬럼만, (c) Self-RAG 재검색 분기(`evaluate_retrieval_quality` → `rewrite_query`)는 Story 3.3, (d) `parsed_items` 음식명 정규화(`food_aliases` 매칭 / *짜장면 ≠ 자장면*)는 Story 3.1/3.4 — 본 스토리는 *Vision raw 출력 그대로 영속화*만, (e) OCR 응답 캐시(`cache:llm:{sha256(image_key)}`) 도입은 Story 8 polish — 본 스토리는 *호출당 새 응답*(영업 데모 한정 + 이미지 매번 다른 키), (f) confidence 임계값 동적 조정(KDRIs 도메인 룰 기반)은 Growth — 본 스토리는 *고정 0.6*, (g) 한식 100건 평가 데이터셋은 Story 3.8 LangSmith 통합 시점, (h) Story 2.2 DF2 — 본 스토리에서 자연 해소(parsed_items 영속화 + raw_text overwrite 흐름으로 placeholder 진입 차단). 본 스토리 종료 시 Epic 2 OCR baseline 완료 → Story 2.4(일별 기록 화면)이 OCR 결과 표시 + Epic 3 LangGraph가 `parse_meal` 노드에서 본 어댑터·parsed_items 재사용.

## Acceptance Criteria

> **BDD 형식 — 각 AC는 독립적 검증 가능. 모든 AC 통과 후 `Status: review`로 전환하고 code-review 워크플로우로 진입.**

1. **AC1 — `meals.parsed_items` 컬럼 + Alembic 0008 마이그레이션**
   **Given** Story 2.3, **When** `alembic upgrade head` 실행, **Then** `meals` 테이블에 1 컬럼 추가:
     - `parsed_items` JSONB NULL — OCR 추출 결과 영속화 (`[{"name": "짜장면", "quantity": "1인분", "confidence": 0.92}, ...]` 형식). NOT NULL 부여 X — 텍스트-only / 사진+텍스트(parse 미호출) 식단 호환 유지.
     - `raw_text` NOT NULL invariant **유지** — Story 2.1/2.2 정합. 사용자 확인 카드 통과 후 meal 생성 시 *frontend가 parsed_items를 한국어 한 줄 텍스트로 변환*해 raw_text 동시 송신(예: `"짜장면 1인분, 군만두 4개"`) — DF2(`(사진 입력)` placeholder collision)는 *raw_text overwrite 흐름 강제*로 자연 해소(behavioral resolution + 영속화 단일화).
     - **추가 인덱스 X** — `parsed_items` 단독 조회·필터 패턴 부재(Epic 3 LangGraph state 입력으로 `meal_id` lookup 시점에만 fetch). jsonb path 인덱스(`GIN`)는 Story 8 perf hardening.
     - **CHECK 제약 X** — `parsed_items` 형식 검증은 백엔드 라우터(`MealCreateRequest`/`MealUpdateRequest` Pydantic) + Vision 어댑터 응답 Pydantic 모델로 충분(double-gate DB CHECK는 Story 8 hardening / jsonb 구조 변경 마찰).
     - **Migration 파일**: `api/alembic/versions/0008_meals_parsed_items.py` — `down_revision = "0007_meals_image_key"`. `upgrade()`는 `op.add_column("meals", sa.Column("parsed_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True))`. `downgrade()`는 `op.drop_column("meals", "parsed_items")` (역순). 0006/0007 패턴 정합 — `op.execute` raw SQL 회피.
     - **ORM 모델 갱신**: `api/app/db/models/meal.py` — `parsed_items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)` 1줄 추가(`image_key` 다음). jsonb는 `sqlalchemy.dialects.postgresql.JSONB` import.
     - **autogenerate diff**: `alembic revision --autogenerate` 실행 시 추가 diff 0건(0008이 ORM과 sync된 상태).

2. **AC2 — `app/adapters/openai.py` Vision 어댑터 + `parse_meal_image` async 함수**
   **Given** Story 2.3 백엔드 셋업, **When** `await openai_adapter.parse_meal_image(image_url)` 호출, **Then**:
     - **OpenAI Python SDK 사용** — `from openai import AsyncOpenAI` (`openai>=1.55` 의존성 신규). `langchain-openai`(이미 설치됨) wrapper 미채택 사유: 본 어댑터는 *Vision OCR 단일 호출*이며 LangGraph state 통합은 Story 3.3 책임 — 직접 SDK가 retry/timeout/structured outputs 제어에 더 명료. Story 3.3 LangGraph 노드(`app/graph/nodes/parse_meal.py`)는 본 어댑터 함수를 *그대로 호출* 또는 `langchain-openai.ChatOpenAI` 래핑 — 결정은 Story 3.3 시점.
     - **모델**: `gpt-4o` (Vision OCR 정확도 — `gpt-4o-mini`는 Vision 출력 신뢰도 부족 — Vision-stage benchmarking 결과 채택 / 영업 데모 데이터셋 한정 cost 미미). 모델명은 `app/adapters/openai.py:VISION_MODEL` 상수 — Story 8 cost polish 시 `gpt-4o-mini` 또는 `gpt-4o-2024-11-20` snapshot pin.
     - **structured outputs**: Pydantic `ParsedMealItem`(`name: str`, `quantity: str`, `confidence: float = Field(ge=0, le=1)`) + `ParsedMeal`(`items: list[ParsedMealItem]`). `client.beta.chat.completions.parse(model=..., messages=..., response_format=ParsedMeal)` 사용 (OpenAI SDK structured outputs API — JSON Schema 강제 + 자동 Pydantic 역직렬화 / *manual JSON parsing 회피*).
     - **이미지 입력**: R2 public URL 직접(`{"type": "image_url", "image_url": {"url": image_url}}`) — base64 인코딩 회피(이미지 fetch + 메모리 + Railway egress 비용). R2 미설정 환경(`r2_public_base_url` unset)은 dev/CI 한정 — 어댑터 호출 자체가 R2 url 없으면 차단(`MealOCRImageUrlMissingError(503)` raise — 부팅 시 검증보다 lazy fail-fast로 dev 부팅 통과 + 첫 호출 시 차단).
     - **시스템 프롬프트** (한국어 — NFR-L2 정합):
       ```
       당신은 한국 음식 사진을 분석하는 영양 분석 보조 시스템입니다. 사진에서 보이는 음식 항목을 한국어 표준 음식명으로 추출하세요. 각 항목에 추정 양(예: '1인분', '4개', '300g')과 0.0~1.0 신뢰도(confidence)를 부여하세요. 보이지 않는 항목 추측·환각 금지 — 식별 가능한 항목만 출력하세요. 음식이 아닌 사진(풍경/사물 등)은 빈 items 배열을 반환하세요.
       ```
     - **timeout**: `timeout=30.0` (OpenAI SDK `with_options(timeout=...)` — 모바일 4G + p95 4초 soft target + hard cap 30초). 초과 시 `httpx.TimeoutException` → tenacity retry 1회 → 최종 실패 시 `MealOCRUnavailableError(503)` raise.
     - **retry**: tenacity `@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type((httpx.HTTPError, openai.APIError, openai.RateLimitError)))` — *transient 5xx / RateLimitError / 네트워크 오류*만 retry. `openai.AuthenticationError` 등 *영구 오류*는 즉시 fail (NFR-R2 정합).
     - **반환**: `ParsedMeal` Pydantic 인스턴스(`items: list[ParsedMealItem]`). 빈 items 허용 — 음식이 아닌 사진 또는 인식 실패 케이스(graceful degradation은 라우터 레벨 — 빈 items도 정상 응답 200, 클라이언트가 *"음식이 인식되지 않았어요"* 안내).
     - **클라이언트 재사용 패턴**: `AsyncOpenAI(api_key=settings.openai_api_key)`는 모듈 lazy singleton(`_get_client()` helper) — 재생성 시 httpx connection pool 재구성 비용. `openai_api_key` 미설정(dev) 시 `MealOCRUnavailableError(503)` raise — 부팅 통과 + runtime fail-fast.
     - **로깅**: `log.info("ocr.vision.parsed", image_key=..., items_count=..., min_confidence=..., max_confidence=..., model=VISION_MODEL, latency_ms=...)` — `image_url` raw 출력 X(서명 토큰 부재의 public URL이지만 image_key forward로 단일화).

3. **AC3 — `POST /v1/meals/images/parse` endpoint (require_basic_consents)**
   **Given** 4종 기본 동의 통과 사용자, **When** `POST /v1/meals/images/parse` body `{"image_key": "meals/<user_id>/<uuid>.jpg"}` 호출, **Then**:
     - HTTP 200 + 응답 body `MealImageParseResponse`:
       ```json
       {
         "image_key": "meals/<user_id>/<uuid>.jpg",
         "parsed_items": [
           {"name": "짜장면", "quantity": "1인분", "confidence": 0.92},
           {"name": "군만두", "quantity": "4개", "confidence": 0.88}
         ],
         "low_confidence": false,
         "model": "gpt-4o",
         "latency_ms": 1843
       }
       ```
     - **요청 body 스키마** (`MealImageParseRequest`, `extra="forbid"`):
       - `image_key: str = Field(min_length=1, max_length=128, pattern=_IMAGE_KEY_PATTERN)` — Story 2.2 정합 정규식(`meals/<uuid>/<uuid>.<ext>`). user_id 일치는 라우터 inline 검증.
     - **Ownership + R2 head_object 검증** (Story 2.2 패턴 정합):
       - `_validate_image_key_ownership(body.image_key, user.id)` → `MealImageOwnershipError(400 + meals.image.foreign_key_rejected)` 사유 미일치 시.
       - `await _verify_image_uploaded(body.image_key)` (Story 2.2 P21 helper 재사용) → `MealImageNotUploadedError(400 + meals.image.not_uploaded)` 사유 R2 객체 부재 시.
     - **Vision 호출**: `image_url = r2_adapter.resolve_public_url(body.image_key)` → `await openai_adapter.parse_meal_image(image_url)`. R2 미설정 시 `R2NotConfiguredError(503)` 자연 전파(global handler).
     - **`low_confidence` 플래그**: `parsed_items`의 `min(item.confidence)` < 0.6 또는 `len(items) == 0` 시 `True`. 모바일이 *forced confirmation* UI 분기에 활용(임계값 0.6은 epic AC 명시).
     - **인증·동의 가드**:
       - 401 — `auth.access_token.invalid`
       - 403 — `consent.basic.missing`
       - 400 (Pydantic) — `validation.error` (image_key 형식 위반 또는 extra field)
       - 400 (도메인) — `meals.image.foreign_key_rejected` / `meals.image.not_uploaded`
       - 503 — `meals.image.r2_unconfigured` (R2 미설정) 또는 `meals.image.ocr_unavailable` (Vision 장애)
     - **HTTP status — 200 채택**: parse는 *리소스 생성*이 아닌 *idempotent 분석 호출*(stateless — DB row 0). 201은 부적절. *동일 image_key 재호출은 매 호출 새 Vision 호출 + 새 응답* — Vision API 자체가 결정성 미보장(temperature 0.0 강제로 변동성 최소화하나 wire 시점 변동 가능). 캐시(`cache:llm:{sha256(image_key)}`)는 Story 8 polish.
     - **로깅**: `log.info("meals.image.parse_completed", user_id=..., image_key=..., items_count=..., low_confidence=..., latency_ms=...)`. Vision 어댑터의 `ocr.vision.parsed` 로그와 *2단 로그* — 라우터는 *user-facing 흐름*, 어댑터는 *외부 호출 격리*.
     - **OpenAPI**: `responses=` 명시(400/401/403/503) + `tags=["meals", "images"]` 정합.

4. **AC4 — `MealCreateRequest`/`MealUpdateRequest` `parsed_items` 필드 추가 + raw_text overwrite 흐름**
   **Given** 4종 기본 동의 통과 사용자 + parse 호출 + 사용자 확인 완료, **When** `POST /v1/meals` 또는 `PATCH /v1/meals/{meal_id}` body에 `parsed_items` 첨부 호출, **Then**:
     - HTTP 201/200 + 응답 body `MealResponse` (10 필드 — Story 2.2 9 필드 + `parsed_items`).
     - **요청 body 스키마 갱신** (`MealCreateRequest`, `extra="forbid"`):
       - `parsed_items: list[ParsedMealItem] | None = Field(default=None, max_length=20)` — 신규 추가. `None` 또는 빈 배열 모두 허용 — 텍스트-only / parse 안 한 사진-only 입력은 그대로. `max_length=20` 상한(20 항목 초과는 abuse / 영업 데모 한정 합리적 상한 + Story 8 tunable).
       - `ParsedMealItem` Pydantic 모델 재사용(`api/app/api/v1/meals.py` 또는 별도 `app/api/schemas/meal_image.py` — 본 스토리는 `meals_images.py` import + `meals.py` reuse).
       - `raw_text` 미송신/명시 null + `image_key` + `parsed_items` 모두 존재 → 클라이언트 송신 표준에서는 *raw_text를 frontend가 한국어 한 줄 텍스트로 변환해 동시 송신*. 단 *서버 fallback 안전망*: `raw_text=None and image_key not None and parsed_items not None` 시 서버가 `_format_parsed_items_to_raw_text(parsed_items)` 호출(예: `"짜장면 1인분, 군만두 4개"`) — *DF2 placeholder collision 자연 해소* (`(사진 입력)` 진입 차단). raw_text 명시 + parsed_items 동시 송신은 *raw_text 우선*(사용자 직접 편집 우선).
       - `_at_least_one_input` model_validator 갱신(Story 2.2 정합) — `raw_text is None and image_key is None and parsed_items is None` 시 거부 (`parsed_items` 단독 입력은 허용 — 단, 이 케이스에서도 image_key가 ownership 검증에서 None이라 라우터에서 *parsed_items 단독은 무의미*로 거부 — Pydantic은 *최소 1 입력*만 보장, 의미적 invariant는 라우터 inline; 현 방어로는 parsed_items 단독은 허용하지 않음 — Pydantic validator에서 `parsed_items is not None and image_key is None` 추가 거부).
     - **요청 body 스키마 갱신** (`MealUpdateRequest`, `extra="forbid"`):
       - `parsed_items: list[ParsedMealItem] | None = Field(default=None, max_length=20)` — 신규 추가. PATCH 흐름은 `model_fields_set`로 *송신 여부* 검사 — *명시 `null` = 클리어*, *키 부재 = no-op*. (Story 2.2 `image_key` 시맨틱 정합).
       - `_at_least_one_field` model_validator 갱신 — `parsed_items` `model_fields_set` 검사 추가. raw_text/ate_at는 D4 정합(non-null만 effective change), `image_key`/`parsed_items`는 explicit-null 송신도 effective change로 인정.
     - **응답 갱신** (`MealResponse`):
       - 9 필드 (Story 2.2) + 1 필드 = 10 필드: `parsed_items: list[ParsedMealItem] | None`.
       - `parsed_items` 키는 *항상 노출*(스키마 안정성 — architecture line 481 정합) — `parsed_items` None 시 `null`.
     - **로깅 갱신**: `log.info("meals.created"/"meals.updated", ..., has_parsed_items=bool(parsed_items), parsed_items_count=len(parsed_items) if parsed_items else 0)` — 항목 *내용*은 raw 출력 X (NFR-S5 — 사용자 식단은 잠재 식단/건강 추론 가능, len만).

5. **AC5 — `app/adapters/openai.py` 도메인 예외 + 글로벌 핸들러 정합**
   **Given** Story 2.3 어댑터·라우터, **When** OCR 호출 시 외부 장애 / 환경 미설정 / R2 누락, **Then** 신규 도메인 예외 분기:
     - 신규 3 클래스 (`MealImageError(MealError)` 정합 — Story 2.2 base 재사용):
       ```python
       class MealOCRUnavailableError(MealImageError):
           status: ClassVar[int] = 503
           code: ClassVar[str] = "meals.image.ocr_unavailable"
           title: ClassVar[str] = "Image OCR service unavailable"

       class MealOCRImageUrlMissingError(MealImageError):
           status: ClassVar[int] = 503
           code: ClassVar[str] = "meals.image.ocr_image_url_missing"
           title: ClassVar[str] = "Image public URL not configured (R2)"

       class MealOCRPayloadInvalidError(MealImageError):
           status: ClassVar[int] = 502
           code: ClassVar[str] = "meals.image.ocr_payload_invalid"
           title: ClassVar[str] = "Image OCR returned invalid payload"
       ```
     - **세분화 사유**:
       - `MealOCRUnavailableError(503)` — Vision API timeout / 5xx / RateLimitError / 네트워크 (tenacity retry 후 최종 실패). `openai.APIError` / `openai.RateLimitError` / `httpx.TimeoutException` / `httpx.HTTPError` 광범위 catch — 라우터에서 typed 변환.
       - `MealOCRImageUrlMissingError(503)` — `r2_adapter.resolve_public_url(image_key)`가 None 반환(R2 미설정) → 어댑터는 호출 진입 시 명시 검증으로 *조기 차단*. `R2NotConfiguredError(503)`와 *분리* — 후자는 *boto3 client 생성*, 전자는 *public URL 노출*. 모바일 동일 alert(*"사진 인식 일시 장애"*) 분기, 운영 로그·Sentry에서는 분리(원인 파악 용이).
       - `MealOCRPayloadInvalidError(502)` — Vision이 structured output 위반(JSON Schema 검증 실패 / Pydantic ValidationError). OpenAI SDK `parse` API는 schema 강제하나 *방어로* — 502 Bad Gateway는 RFC 9110 정합(*upstream invalid response*).
     - **글로벌 핸들러 변경 X** — `BalanceNoteError` 핸들러(`main.py:177`)가 본 3 신규 예외를 자동 RFC 7807 변환(Story 1.2 패턴 정합).

6. **AC6 — `mobile/features/meals/OCRConfirmCard.tsx` 표준 컴포넌트**
   **Given** 사진 첨부 후 parse 호출 완료, **When** `OCRConfirmCard` 렌더링, **Then**:
     - **props**: `{ items: ParsedMealItem[]; lowConfidence: boolean; onChangeItems: (items: ParsedMealItem[]) => void; onConfirm: () => void; onRetake: () => void; isSubmitting: boolean }`.
     - **레이아웃** (모달 또는 inline — 부모 결정):
       - 헤더: *"인식된 음식을 확인해주세요"* + *"맞으신가요?"* 부제 (epic AC line 544 정합).
       - 신뢰도 배지: `lowConfidence=true` 시 노란색 *"⚠ 인식이 불확실해요 — 직접 수정해주세요"* 안내 (한 줄, accessibility text). `false` 시 표시 X.
       - 항목 리스트: 각 항목 row — `name` (편집 가능 `<TextInput />`) + `quantity` (편집 가능 `<TextInput />`) + `confidence` 배지 (소수점 1자리 % — *92%*, 0.6 미만은 빨간색).
       - 추가 버튼: *"+ 항목 추가"* — `onChangeItems([...items, { name: '', quantity: '', confidence: 1.0 }])`. 신규 항목 confidence는 1.0 (사용자 직접 입력으로 신뢰).
       - 삭제 버튼: 각 row 우측 *"삭제"* 아이콘 — `onChangeItems(items.filter((_, i) => i !== rowIndex))`.
       - CTA: *"확인 후 저장"* 버튼 (`onConfirm`) + *"다시 촬영"* secondary 버튼 (`onRetake` — 사진 + parsed_items 모두 클리어).
       - `isSubmitting=true` 시 모든 버튼 disable + ActivityIndicator.
     - **빈 items 처리**: `items.length === 0` 시 메시지 *"음식이 인식되지 않았어요. 직접 입력하거나 다시 촬영해주세요."* + *"+ 항목 추가"* + *"다시 촬영"* (확인 CTA는 비활성 — items 없으면 의미 없음).
     - **편집 normalize**: `name` trim + maxLength 50, `quantity` trim + maxLength 30. 빈 문자열 거부(부모에서 `onConfirm` 시 필터링 — 여기는 row 단위 표시만).
     - **accessibility**: 각 `<TextInput />`에 `accessibilityLabel="음식명 ${index+1}"` / `"양 ${index+1}"`. 신뢰도 배지에 `accessibilityLabel="신뢰도 ${conf*100}%"`. 폰트 스케일 200% 대응 — `flexShrink: 1` + wrap.
     - **재사용성 — Epic 3 분석 결과 카드**: 본 컴포넌트는 *Story 2.3 OCR 한정* baseline. Epic 3 `ChatStreaming.tsx`의 인용 카드와는 별개(인용은 *읽기 전용*, OCR은 *편집 가능*). 단 신뢰도 배지 + accessibility 패턴은 forward 재사용 가능.

7. **AC7 — `mobile/features/meals/api.ts` `useParseMealImageMutation` + `parseMealImage` helper**
   **Given** Story 2.3 모바일, **When** `parseMealImage(image_key)` 호출, **Then**:
     - **단일 호출 흐름**:
       1. `POST /v1/meals/images/parse` body `{image_key}` → `MealImageParseResponse` 수신.
     - 반환: `{parsed_items: ParsedMealItem[], low_confidence: boolean}`. 호출자(`(tabs)/meals/input.tsx`)는 결과를 `OCRConfirmCard`로 forward + 사용자 확인 후 `MealCreateRequest.parsed_items`에 첨부.
     - **에러 처리** (`MealSubmitError` 패턴 정합 — Story 2.1/2.2 정합):
       - 401 → `authFetch` 자동 처리.
       - 401/403/400 → `MealSubmitError` throw — 부모가 처리(`consent.basic.missing` redirect 등).
       - 503 (`meals.image.ocr_unavailable` / `meals.image.r2_unconfigured` / `meals.image.ocr_image_url_missing`) → `MealSubmitError(503)` throw — 부모가 *"사진 인식 일시 장애 — 텍스트로 다시 입력해주세요"* Alert + parsed_items 미설정 + 사용자가 텍스트 입력으로 회복 (epic AC line 547 NFR-I3 정합).
       - 502 (`meals.image.ocr_payload_invalid`) → 동일 alert + Sentry 자동 capture(부모 catch 시점에 RN Sentry SDK 도입 후속 — Story 8).
     - **timeout**: 백엔드 어댑터가 30초 hard cap → 실제 timeout은 백엔드 측에서 일관 차단 (모바일 fetch는 RN 기본 무한대 + 인터넷 끊김 시 retry는 사용자 액션). 별도 `AbortController`는 본 스토리 OUT — Story 2.2 `uploadImageToR2` 30초 timeout과 *역할 분리* (업로드는 사용자 stuck 차단, parse는 백엔드 차단 신뢰).
     - **dependency**: `useParseMealImageMutation` (TanStack Query `useMutation`) — `mutationFn: parseMealImage`. 인디케이터 표시(`isPending`)는 부모 `isUploading` state와 분리 — `isParsing` 전용. `isPending` 표시는 `OCRConfirmCard.isSubmitting`이 아닌 *parse 호출 중* 별도 spinner.
     - **로깅 X** — 모바일 클라이언트는 production debug 한정 — Sentry RN 도입은 Story 8.

8. **AC8 — `mobile/app/(tabs)/meals/input.tsx` orchestration — 사진 첨부 후 자동 parse + 확인 카드 흐름**
   **Given** Story 2.2 입력 화면 + Story 2.3 parse 흐름, **When** 사용자가 사진 첨부 완료(R2 PUT 성공), **Then**:
     - **자동 parse 호출**: `uploadImageToR2` 성공 직후 `parseMealImage(image_key)` 자동 호출 — *부모 effect chain*:
       1. `setImageKey + setImageLocalUri` 직후 `setIsParsing(true)` + `parseMealImageMutation.mutate(imageKey)`.
       2. `onSuccess` → `setParsedItems(result.parsed_items)` + `setLowConfidence(result.low_confidence)` + `setIsParsing(false)`.
       3. `onError` (503 등) → `setParsedItems(null)` + Alert *"사진 인식 일시 장애 — 텍스트 입력 또는 다시 촬영해주세요"* + `setIsParsing(false)`. 사용자가 *raw_text 직접 입력* 또는 *다시 촬영* 선택.
     - **`OCRConfirmCard` 렌더 분기**: `parsedItems !== null and !isParsing` 시 `<OCRConfirmCard ...>`를 폼 영역에 *대체 inline render* (PermissionDeniedView 정합 패턴 — *부모가 form vs alternate view* 분기).
       - `onChangeItems` → `setParsedItems(items)` (사용자 편집 반영).
       - `onConfirm` → `setOcrConfirmed(true)` + 폼 표시 (raw_text 자동 갱신 — 아래).
       - `onRetake` → `setImageKey(null) + setImageLocalUri(null) + setParsedItems(null) + setOcrConfirmed(false)` + form 초기 상태(촬영 전).
     - **`raw_text` 자동 갱신** (사용자 확인 시점):
       - `onConfirm` 호출 시 `formatParsedItemsToRawText(parsedItems)` 헬퍼 호출 → `rawText = "짜장면 1인분, 군만두 4개"` 형식. `react-hook-form`의 `setValue('raw_text', rawText, { shouldDirty: true })`로 폼 필드 갱신.
       - 사용자가 form에서 raw_text 수정 시 *마지막 수정값 우선* — 서버 송신 시 `body.raw_text = data.raw_text`(form 값) + `body.parsed_items = parsedItems`. 즉 *raw_text는 사용자 최종 표시용 텍스트*, *parsed_items는 Vision 분석 입력*.
     - **`onSubmit` 갱신**:
       - POST 시 `body = { raw_text: data.raw_text, image_key: imageKey, parsed_items: parsedItems ?? undefined }`.
       - PATCH 시 `parsed_items` 송신 분기 — *재 parse 호출* 후 confirm 시 `body.parsed_items = parsedItems`. *제거 (재촬영 X but 사용자가 parsed_items 전체 삭제)* 시 `body.parsed_items = null` 명시 송신 (D4 정합 — explicit null = 클리어).
     - **`formatParsedItemsToRawText` 헬퍼** (`mobile/features/meals/parsedItemsFormat.ts` 신규):
       - `(items: ParsedMealItem[]) => string` — `items.map(i => i.quantity ? \`${i.name} ${i.quantity}\` : i.name).join(', ')`. 빈 quantity는 양 표시 생략.
       - 빈 items는 빈 문자열 반환 — 부모에서 *"인식 결과 없음"* 분기 처리.
     - **`isParsing` UX**: parse 중 form/CTA disable + spinner *"사진 분석 중…"*. 4초 초과 시 (epic AC NFR-P1 일부) UX 안내 추가 X — 백엔드 30초 cap + tenacity retry로 충분, 모바일 timeout 별도 도입은 본 스토리 OUT.
     - **PATCH 모드 prefill**:
       - `editingMeal.parsed_items` 존재 시 `setParsedItems(editingMeal.parsed_items)` + `setOcrConfirmed(true)` (이미 확인된 상태) — 사용자가 *"OCR 다시 분석"* CTA 누르면 `parseMealImage(editingMeal.image_key)` 재호출 + 신규 confirm card 표시. baseline은 *"OCR 다시 분석" CTA*만 prep — 실제 wire는 form 하단 *작은 버튼* 1개.
     - **확인 카드 forced 분기 (`low_confidence=true`)**: `lowConfidence=true` 시 *"확인 후 저장"* CTA 비활성 + *"각 항목을 검토해주세요"* 메시지 노출. 사용자가 *모든 항목 편집(name + quantity 둘 다 사용자 입력)* 또는 *명시 *"이대로 진행"* 버튼*(secondary, 추가 1 클릭) 후 활성화.

9. **AC9 — `mobile/features/meals/MealCard.tsx` `parsed_items` 표시 forward (Story 2.4 prep — 본 스토리는 baseline forward 1줄만)**
   **Given** Story 2.4 일별 기록 화면(forward), **When** `MealCard`가 `meal.parsed_items` 보유, **Then**:
     - 본 스토리 baseline은 *MealCard 변경 X* — Story 2.4 책임 (시간순 카드 + 매크로 + fit_score 일괄 polish 시점에 *"인식: 짜장면 1인분, 군만두 4개"* 부제 추가). 본 스토리는 *MealResponse 인터페이스 갱신*만 (Task 7.4 — `parsed_items` 필드 노출).
     - **사유**: Story 2.4가 일별 기록 화면 polish 단일 PR이므로 *MealCard polish*는 그쪽 통합. 본 스토리 baseline에서 *부분 polish*(parsed_items만 표시)는 Story 2.4와 conflict 가능성. *forward dependency*는 *데이터 노출(`parsed_items` 필드 wire)*까지만.

10. **AC10 — `pyproject.toml` openai 의존성 + `app/adapters/__init__.py` export**
    **Given** Story 2.3 백엔드 wire, **When** `cd api && uv sync` 실행, **Then**:
      - `pyproject.toml` `dependencies` 배열에 `openai>=1.55` 1줄 추가 (`langchain-openai>=0.3` 기존 의존성 정합 — 동일 메이저 버전 호환).
      - `[[tool.mypy.overrides]]`에 `openai.*` 추가(선택적 — openai SDK는 type stubs 포함이므로 미요구일 가능성 — 실제 mypy 통과 시 미추가).
      - `api/app/adapters/__init__.py` — `from app.adapters import openai_adapter as openai_adapter` 또는 `from app.adapters.openai_adapter import parse_meal_image, ParsedMeal, ParsedMealItem` export. 모듈명 `openai_adapter.py` 채택(파일명 `openai.py`는 PyPI `openai` 패키지와 *import 충돌 잠재* — 본 모듈 내부에서 `from openai import AsyncOpenAI` 호출 시 *self-import* 사이클 risk; `openai_adapter.py`로 명명해 분리). architecture line 689는 `openai.py` 명시이지만 *Python import 안전성*이 더 중요 — Story 2.3에서 `openai_adapter.py`로 deviation + dev notes 명시.
      - `uv.lock` 자동 갱신.

11. **AC11 — 백엔드 테스트 + OpenAPI 재생성 + smoke**
    - 백엔드 테스트 — `api/tests/test_meals_images_router.py` 갱신 + `api/tests/test_openai_adapter.py` 신규 + `api/tests/test_meals_router.py` 갱신.

      **`test_meals_images_router.py` 갱신 (POST /v1/meals/images/parse)** 신규 8 케이스:
      - `test_parse_returns_200_with_parsed_items` — Vision adapter mock(`AsyncMock`) → ParsedMeal(2 items, confidence 0.92/0.88) 반환 → 200 + 5 필드 (`image_key`, `parsed_items`, `low_confidence=False`, `model`, `latency_ms`).
      - `test_parse_returns_low_confidence_true_when_below_threshold` — mock items confidence 0.55 → `low_confidence=True`.
      - `test_parse_returns_low_confidence_true_when_empty_items` — mock empty items → `low_confidence=True`.
      - `test_parse_unauthenticated_returns_401` — 헤더 없음 → 401 + `code=auth.access_token.invalid`.
      - `test_parse_blocks_user_without_basic_consents_returns_403` — 동의 미통과 → 403 + `code=consent.basic.missing`.
      - `test_parse_foreign_image_key_returns_400` — 다른 사용자 prefix → 400 + `code=meals.image.foreign_key_rejected`.
      - `test_parse_image_not_uploaded_returns_400` — `head_object` False → 400 + `code=meals.image.not_uploaded`.
      - `test_parse_ocr_unavailable_returns_503` — Vision adapter mock에서 `MealOCRUnavailableError` raise → 503 + `code=meals.image.ocr_unavailable`.
      - `test_parse_invalid_image_key_format_returns_400` — `image_key="../../etc/passwd"` → 400 + `code=validation.error` (Pydantic regex).
      - `test_parse_extra_field_returns_400` — `{"image_key": "...", "extra": "x"}` → 400 (`extra="forbid"`).

      **`test_openai_adapter.py` 신규** 5 케이스:
      - `test_parse_meal_image_returns_parsed_meal_pydantic` — `AsyncOpenAI.beta.chat.completions.parse` mock → ParsedMeal(2 items) → 정확 역직렬화 검증.
      - `test_parse_meal_image_empty_items_supported` — mock 빈 items → 정상 반환(빈 배열).
      - `test_parse_meal_image_timeout_raises_unavailable` — `httpx.TimeoutException` mock → tenacity retry 1회 후 `MealOCRUnavailableError` raise.
      - `test_parse_meal_image_rate_limit_retried` — `openai.RateLimitError` 1회 mock 후 정상 응답 → retry 후 성공.
      - `test_parse_meal_image_unconfigured_raises_unavailable` — `openai_api_key=""` 환경 → `MealOCRUnavailableError` raise (settings 검증).

      **`test_meals_router.py` 갱신 (parsed_items 흐름)** 추가 5 케이스:
      - `test_post_meal_with_parsed_items_creates_with_text_overwrite` — body `{raw_text: "짜장면 1인분, 군만두 4개", image_key, parsed_items: [...]}` → 201 + `raw_text=짜장면 1인분, 군만두 4개` + `parsed_items` jsonb 저장.
      - `test_post_meal_with_image_key_and_parsed_items_no_raw_text_uses_server_format` — body `{image_key, parsed_items: [...]}` (raw_text 미송신) → 201 + 서버 fallback `raw_text="짜장면 1인분, 군만두 4개"` (`_format_parsed_items_to_raw_text` 적용) + `parsed_items` 저장. *placeholder `(사진 입력)` 진입 X 검증* (DF2 자연 해소).
      - `test_post_meal_parsed_items_only_no_image_key_returns_400` — body `{parsed_items: [...]}` only → 400 + Pydantic `_at_least_one_input` 메시지.
      - `test_post_meal_parsed_items_max_length_20_enforced` — items 21개 → 400.
      - `test_patch_meal_can_clear_parsed_items_with_explicit_null` — PATCH `{"parsed_items": null}` → DB `parsed_items=NULL` + 응답 `parsed_items=null`.
      - `test_meal_response_includes_parsed_items` — POST 후 응답 파싱 검증.
      - 기존 케이스 회귀 — Story 2.1/2.2 30+ 케이스 그대로 통과(parsed_items None default).

    - **conftest 갱신**: `_truncate_user_tables` TRUNCATE 문은 그대로 — `meals` 이미 등재. parsed_items 컬럼은 ALTER. `mock_openai_client` fixture 신규 — `AsyncOpenAI` mock + `beta.chat.completions.parse` AsyncMock. autouse는 X — 명시 dependency 강제(silent miss 방지).
    - **monkeypatch**: `tests/test_openai_adapter.py`는 `monkeypatch.setenv("OPENAI_API_KEY", "...")` 또는 settings instance override + `AsyncOpenAI` 인스턴스 mock — *I/O 무발생*(실제 OpenAI 도달 X).
    - **OpenAPI 클라이언트 재생성**: `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` 실행 → `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 갱신 — `MealImageParseRequest`/`MealImageParseResponse`/`ParsedMealItem` 타입 + `/v1/meals/images/parse` path 1 endpoint + `MealResponse.parsed_items` 필드 추가 노출 확인. PR push 시 `openapi-diff` GitHub Actions 잡 통과(diff 0).
    - smoke 통합 검증(local — 사용자 별도 수행):
      1. 신규 사용자 — 온보딩 통과 → `(tabs)/meals/input` 진입 → *카메라* 탭 → 권한 첫 요청 *허용* → 촬영(짜장면 + 군만두 사진) → 자동 업로드 → 자동 parse 호출 → `OCRConfirmCard` 노출 (*"짜장면 1인분, 군만두 4개 인식됨 — 맞으신가요?"*) → 사용자 확인 → form `raw_text` 자동 갱신 → 저장 → list에 카드 표시.
      2. 신뢰도 낮은 사진 — 모호한 사진 → `OCRConfirmCard` `lowConfidence=true` 배지 + 확인 CTA 비활성 → 항목 직접 편집 → CTA 활성화 → 저장.
      3. Vision 장애 — `OPENAI_API_KEY` unset 환경 → 사진 첨부 후 자동 parse → 503 → Alert *"사진 인식 일시 장애 — 텍스트 입력 또는 다시 촬영"* → 사용자가 raw_text 직접 입력 → 저장(parsed_items=null).
      4. 사용자가 *"다시 촬영"* — `OCRConfirmCard` *다시 촬영* 버튼 → 사진 + parsed_items 전체 클리어 → 카메라 재진입.
      5. PATCH 모드 — 기존 OCR 결과 식단 long-press → 수정 진입 → `parsed_items` prefill 표시 (간단 raw_text + 작은 *"OCR 다시 분석"* 버튼) → 수정 저장.
      6. 빈 인식 결과 — 풍경 사진 → Vision 빈 items → `OCRConfirmCard` *"음식이 인식되지 않았어요"* + *"+ 항목 추가"* + *"다시 촬영"*.
    - coverage gate: `--cov=app --cov-fail-under=70` 유지. 본 스토리 신규 코드 약 350줄(Vision adapter + parse endpoint + 0008 마이그레이션 + parsed_items wire + 모바일 컴포넌트 + 테스트) — 신규 18 케이스(parse 9 + adapter 5 + meals parsed_items 5)로 충분 cover.

12. **AC12 — README + .env.example + sprint-status 갱신 + smoke 검증**
    - **README**: 기존 *"식단 사진 입력 SOP"* 단락 다음에 *"식단 사진 OCR Vision SOP"* 1 단락 추가 (간결 — 6 줄 이하):
      - (a) `POST /v1/meals/images/parse` 흐름(image_key body → GPT-4o Vision → `parsed_items` + `low_confidence` 응답) 1줄
      - (b) `OPENAI_API_KEY` 환경변수 명시 + dev 환경에서 미설정 시 503 fail-fast 1줄
      - (c) GPT-4o 호출당 ~$0.005-0.01 비용 + R6 cost alert(daily-cost-alert.yml) 정합 1줄
      - (d) 신뢰도 임계값 0.6 + 모바일 forced confirmation UX 1줄
      - (e) `OCRConfirmCard` 사용자 확인 후 `raw_text` 자동 갱신 (DF2 placeholder collision 자연 해소) 1줄
      - (f) Epic 2 세 번째 스토리(2.3) 완료 + Story 2.4(일별 기록 화면 polish) 후속 1줄
    - **.env.example**: `OPENAI_API_KEY=` placeholder 확인(이미 존재하면 noop / 미존재 시 추가) — 주석 *"OpenAI Vision API 키 — 식단 사진 OCR 추출에 사용 (Story 2.3)"* 1줄.
    - **sprint-status**: `2-3-ocr-vision-추출-확인-카드` → `review` 갱신 (DS 종료 시점 — 메모리 `feedback_ds_complete_to_commit_push.md` 정합 — commit + push 후 CR 단계).
    - **deferred-work.md** 갱신 — 본 스토리 신규 deferred 후보(아래 *Dev Notes — 신규 deferred 후보* 섹션 참조).
    - smoke 검증 6 시나리오 — AC11 그대로(local 환경에서 사용자 별도 수행). 본 task는 *Dev Agent Record Completion Notes에 결과 기록*만 — 백엔드 게이트(pytest/ruff/mypy clean) + 모바일 게이트(tsc/lint clean) 통과로 충분.
    - Dev Agent Record + File List + Completion Notes 작성 후 `Status: review` 전환.

## Tasks / Subtasks

> 순서는 의존성 위주. 각 task는 AC 번호 매핑 명시. 본 스토리는 **단일 PR 권장** (Story 2.1/2.2/1.6/1.5 정합).

### Task 1 — DB 모델 + Alembic 마이그레이션 0008 (AC: #1)

- [x] 1.1 `api/app/db/models/meal.py` — `parsed_items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)` 1줄 추가 (image_key 다음 위치). `from sqlalchemy.dialects.postgresql import JSONB` import 추가 (기존 import에 정합).
- [x] 1.2 `api/alembic/versions/0008_meals_parsed_items.py` 신규 — `down_revision = "0007_meals_image_key"`. `upgrade()`는 `op.add_column("meals", sa.Column("parsed_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True))`. `downgrade()`는 `op.drop_column("meals", "parsed_items")`.
- [x] 1.3 마이그레이션 검증 — `cd api && uv run alembic upgrade head` 통과 + `uv run alembic revision --autogenerate -m "verify_meals_parsed_items_sync"` 실행 시 *추가 diff 0건* 확인. 검증 후 임시 revision 파일 삭제.
- [x] 1.4 `ruff check . && ruff format --check . && mypy app` clean. 마이그레이션 파일은 `from __future__ import annotations` + `from collections.abc import Sequence` 패턴(0007 정합).

### Task 2 — 백엔드 OpenAI Vision 어댑터 (AC: #2, #5, #10)

- [x] 2.1 `api/pyproject.toml` — `openai>=1.55` 의존성 추가 (`uv add openai`). `[[tool.mypy.overrides]]`는 mypy clean 검증 후 결정(openai SDK는 type stubs 포함이므로 미요구 가능).
- [x] 2.2 `api/app/adapters/openai_adapter.py` 신규 (모듈명 `openai_adapter` — PyPI `openai` 패키지와 *import 사이클* 회피, AC10 명시):
  - `_get_client()` lazy singleton — `AsyncOpenAI(api_key=settings.openai_api_key, timeout=30.0)` (`openai.AsyncOpenAI` 표준 + `with_options(timeout=...)` 활용 가능).
  - `ParsedMealItem(BaseModel)` — `name: str = Field(min_length=1, max_length=50)`, `quantity: str = Field(min_length=0, max_length=30)`(빈 quantity 허용 — *"바나나"* 같은 양 없는 항목), `confidence: float = Field(ge=0, le=1)`.
  - `ParsedMeal(BaseModel)` — `items: list[ParsedMealItem] = Field(max_length=20)`.
  - `VISION_MODEL: Final[str] = "gpt-4o"` 상수.
  - `VISION_SYSTEM_PROMPT: Final[str] = "..."` (AC2 명시 한국어 프롬프트).
  - `parse_meal_image(image_url: str) -> ParsedMeal` async function — `AsyncOpenAI.beta.chat.completions.parse(model=VISION_MODEL, messages=[{"role": "system", "content": VISION_SYSTEM_PROMPT}, {"role": "user", "content": [{"type": "text", "text": "이 사진의 음식을 분석하세요"}, {"type": "image_url", "image_url": {"url": image_url}}]}], response_format=ParsedMeal, temperature=0.0, max_tokens=512)` 호출.
  - `temperature=0.0` 강제 — 결정성 최대화(영업 데모 일관성). `max_tokens=512` — items 20개 cap + 안전 여유.
  - `@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), retry=retry_if_exception_type((httpx.HTTPError, openai.APIError, openai.RateLimitError)))` 적용 — `from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type`. *영구 오류* (`openai.AuthenticationError`)는 retry 대상 X.
  - 응답 파싱 — `response.choices[0].message.parsed` (OpenAI SDK structured outputs 자동 Pydantic 역직렬화). `parsed`가 None이면 `MealOCRPayloadInvalidError(502)` raise.
  - 모든 transient 오류 → `MealOCRUnavailableError(503)` 변환 (라우터 전파).
- [x] 2.3 logging — `structlog.get_logger(__name__)` + `ocr.vision.parsed` 이벤트 (`image_key`/`items_count`/`min_confidence`/`max_confidence`/`model`/`latency_ms` 필드). *`image_url` raw 출력 X* — image_key forward로 단일화.
- [x] 2.4 `_get_client()` — `settings.openai_api_key` 미설정 시 `MealOCRUnavailableError(503)` raise (부팅 통과 + runtime fail-fast). client 재사용은 모듈 lazy singleton (`threading.Lock` double-checked locking — Story 2.2 r2.py 패턴 정합).
- [x] 2.5 `_reset_client_for_tests()` helper — pytest monkeypatch 후 singleton 무효화.
- [x] 2.6 `app/core/exceptions.py` — `MealOCRUnavailableError` + `MealOCRImageUrlMissingError` + `MealOCRPayloadInvalidError` 3 클래스 추가 (Story 2.2 `MealImageError` base 정합 — `MealImageNotUploadedError` 다음 위치).
- [x] 2.7 `api/app/adapters/__init__.py` — `from app.adapters import openai_adapter as openai_adapter` export (또는 `from app.adapters.openai_adapter import parse_meal_image, ParsedMeal, ParsedMealItem` 명시 export).
- [x] 2.8 `ruff check . && ruff format --check . && mypy app` clean.

### Task 3 — 백엔드 라우터 + Pydantic 스키마 (AC: #3, #4, #5)

- [x] 3.1 `api/app/api/v1/meals_images.py` 갱신 (Story 2.2 baseline + parse endpoint 신규):
  - `MealImageParseRequest(BaseModel, extra="forbid")` — `image_key: str = Field(min_length=1, max_length=128, pattern=_IMAGE_KEY_PATTERN)` (regex import는 `meals.py`에서 — 또는 *어댑터 모듈*로 이동해 공유 — `app/api/schemas/meal_image.py` 신규 또는 `meals_images.py` 내 상수 정의).
  - `MealImageParseResponse(BaseModel)` — `image_key: str`, `parsed_items: list[ParsedMealItem]`, `low_confidence: bool`, `model: str`, `latency_ms: int`. `ParsedMealItem`은 `app.adapters.openai_adapter`에서 import.
  - `LOW_CONFIDENCE_THRESHOLD: Final[float] = 0.6` 상수.
  - `POST /parse` endpoint — `MealImageParseRequest` body, `require_basic_consents` Depends, ownership 검증(`_validate_image_key_ownership` — `meals.py` import) + R2 head_object HEAD-check(`_verify_image_uploaded` — `meals.py` import 또는 helper 모듈로 이동), `r2_adapter.resolve_public_url(body.image_key)` 호출(None이면 `MealOCRImageUrlMissingError(503)` raise), `await openai_adapter.parse_meal_image(image_url)` 호출, `low_confidence` 계산(빈 items 또는 min(confidence) < 0.6), 응답 build.
  - `responses=` 명시 (400/401/403/503).
  - 라우터 로깅 — `meals.image.parse_completed` (`user_id`/`image_key`/`items_count`/`low_confidence`/`latency_ms`).
  - `start_time = time.monotonic()` + 응답 직전 `latency_ms = int((time.monotonic() - start_time) * 1000)` — 어댑터 외부 wall-clock(라우터 진입~응답 build 종단).
- [x] 3.2 `api/app/api/v1/meals.py` 갱신:
  - `MealCreateRequest` — `parsed_items: list[ParsedMealItem] | None = Field(default=None, max_length=20)` 추가. `ParsedMealItem` import는 `app.adapters.openai_adapter`. `_at_least_one_input` model_validator 갱신: `raw_text/image_key/parsed_items` 모두 None 거부 + `parsed_items is not None and image_key is None` 추가 거부(`parsed_items` 단독 입력 차단 — 의미 없음).
  - `MealUpdateRequest` — `parsed_items: list[ParsedMealItem] | None = Field(default=None, max_length=20)` 추가. `_at_least_one_field` model_validator 갱신: `model_fields_set`에 `parsed_items` 포함 검사 (`image_key`/`parsed_items`는 explicit-null도 effective change).
  - `MealResponse` — `parsed_items: list[ParsedMealItem] | None` 추가 (10 필드 총).
  - `_meal_to_response` helper — `parsed_items` forward (`meal.parsed_items` 그대로 jsonb→Python list dict→Pydantic 역직렬화 자동).
  - POST 라우터 — body validation 후 `effective_raw_text` 계산:
    - `body.raw_text is not None` → `body.raw_text` 그대로 (사용자 우선).
    - `body.raw_text is None and body.parsed_items is not None` → `_format_parsed_items_to_raw_text(body.parsed_items)` 적용 (서버 fallback — DF2 자연 해소).
    - `body.raw_text is None and body.parsed_items is None and body.image_key is not None` → `PHOTO_ONLY_RAW_TEXT_PLACEHOLDER` (Story 2.2 fallback 유지 — parsed_items 없는 사진 입력만).
  - INSERT values dict에 `parsed_items=body.parsed_items` 추가 (`if body.parsed_items is not None: values["parsed_items"] = body.parsed_items`).
  - PATCH 라우터 — `model_fields_set`로 송신 여부 검사:
    - `if "parsed_items" in body.model_fields_set: values["parsed_items"] = body.parsed_items` (image_key 시맨틱 정합 — explicit null clear).
  - `_format_parsed_items_to_raw_text(items: list[ParsedMealItem]) -> str` helper 신규 — `", ".join(f"{i.name} {i.quantity}".strip() for i in items)` (빈 quantity 시 `name`만 — `f"{i.name} {i.quantity}".strip()`이 자동 처리).
- [x] 3.3 라우터 로깅 — `meals.created`/`meals.updated` 갱신 (`has_parsed_items=bool(parsed_items)`, `parsed_items_count=len(parsed_items) if parsed_items else 0` 필드 추가). 항목 *내용*은 raw 출력 X.
- [x] 3.4 `ruff check . && ruff format --check . && mypy app` clean.

### Task 4 — 백엔드 테스트 18+ 케이스 (AC: #11)

- [x] 4.1 `api/tests/test_openai_adapter.py` 신규 — AC11 명시 5 케이스 (Vision 어댑터 unit). `AsyncMock`으로 `AsyncOpenAI.beta.chat.completions.parse` mock — 실제 OpenAI 도달 X.
- [x] 4.2 `api/tests/test_meals_images_router.py` 갱신 — AC11 명시 신규 9 케이스 (parse endpoint). Story 2.2 8 케이스(presign)은 그대로 유지 + 회귀 0건. `mock_openai_client` fixture로 어댑터 응답 mock.
- [x] 4.3 `api/tests/test_meals_router.py` 갱신 — AC11 명시 +5 케이스 (parsed_items 흐름). 기존 30+ 케이스는 `parsed_items=None` default로 회귀 0건.
- [x] 4.4 conftest 갱신 — `mock_openai_client` fixture 신규 (`AsyncMock` 기반 `AsyncOpenAI` 인스턴스 mock). `_create_meal_for(user)` 등 helper에 `parsed_items` 옵션 인자 추가 (default None) — 회귀 차단.
- [x] 4.5 `uv run pytest --cov=app --cov-fail-under=70` 통과 — 약 18 케이스 추가(parse 9 + adapter 5 + meals parsed_items 5+1) + Story 2.1/2.2 회귀 30+ 케이스 통과.
- [x] 4.6 `ruff check . && ruff format --check . && mypy app` clean.

### Task 5 — Mobile parse helper + api.ts 갱신 (AC: #7)

- [x] 5.1 `mobile/features/meals/api.ts` 갱신 — `useParseMealImageMutation` (TanStack Query useMutation, `POST /v1/meals/images/parse`) + `parseMealImage(image_key)` async helper (단일 호출).
- [x] 5.2 `mobile/features/meals/mealSchema.ts` 갱신 — `MealResponse` 인터페이스에 `parsed_items: ParsedMealItem[] | null` 1 필드 추가. `MealCreateRequest`/`MealUpdateRequest`에 `parsed_items?: ParsedMealItem[] | null` 추가. `ParsedMealItem` 인터페이스 신규 export(`{name: string; quantity: string; confidence: number}`). `MealImageParseRequest`/`MealImageParseResponse` 인터페이스 신규 export.
- [x] 5.3 `mobile/features/meals/parsedItemsFormat.ts` 신규 — `formatParsedItemsToRawText(items: ParsedMealItem[]) -> string` 헬퍼 (빈 quantity 시 name만 + ", " join).
- [x] 5.4 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 6 — Mobile OCRConfirmCard 표준 컴포넌트 (AC: #6)

- [x] 6.1 `mobile/features/meals/OCRConfirmCard.tsx` 신규 — props 명시(`items`, `lowConfidence`, `onChangeItems`, `onConfirm`, `onRetake`, `isSubmitting`). 항목 추가/삭제/편집 UI + 신뢰도 배지 + CTA. 빈 items 분기.
- [x] 6.2 polished UX — 폰트 스케일 200% 대응 + accessibility (`accessibilityLabel`/`accessibilityRole="button"` 모든 인터랙티브 요소). 색약 대응 — 신뢰도 배지는 텍스트(*92%*) + 색상 보조(0.6 미만 빨간색 + ⚠ 이모지).
- [x] 6.3 `lowConfidence=true` 시 *forced confirmation* — *"확인 후 저장"* CTA 비활성 + *"이대로 진행"* secondary 버튼 1 클릭 후 활성화 (또는 모든 항목 사용자 편집 후 자동 활성화). 사용자 편집 detection은 `useEffect([items])` + initial items snapshot 비교.
- [x] 6.4 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 7 — Mobile input.tsx orchestration 갱신 (AC: #8, #9)

- [x] 7.1 `mobile/app/(tabs)/meals/input.tsx` 갱신:
  - 신규 state: `parsedItems: ParsedMealItem[] | null`, `lowConfidence: boolean`, `isParsing: boolean`, `ocrConfirmed: boolean`. PATCH 모드 prefill — `editingMeal.parsed_items` 존재 시 `setParsedItems` + `setOcrConfirmed(true)` 초기화.
  - `handlePickImage` 갱신 — 사진 첨부 + R2 PUT 성공 직후 `parseMealImageMutation.mutate(imageKey)` 자동 호출. `onSuccess` → `setParsedItems(result.parsed_items)` + `setLowConfidence(result.low_confidence)` + `setIsParsing(false)`. `onError` → 503 분기 Alert *"사진 인식 일시 장애 — 텍스트로 다시 입력해주세요"* + `setParsedItems(null)`.
  - `handleConfirmOCR` — `setOcrConfirmed(true)` + `setValue('raw_text', formatParsedItemsToRawText(parsedItems), { shouldDirty: true })` (`react-hook-form` setValue).
  - `handleRetakePhoto` — `setImageKey(null) + setImageLocalUri(null) + setParsedItems(null) + setOcrConfirmed(false) + setLowConfidence(false)` + `setValue('raw_text', '')`.
  - render 분기 — `parsedItems !== null && !ocrConfirmed && !isParsing` 시 `<OCRConfirmCard ...>` inline render (form 대체). `ocrConfirmed=true` 또는 `parsedItems=null`이면 form render.
  - `onSubmit` 갱신 — `body.parsed_items = parsedItems ?? undefined` (POST) / `body.parsed_items = parsedItems`(PATCH 모드 + ocrConfirmed) 또는 explicit null clear (사용자가 *parsed_items 명시 제거* 시 — 본 스토리 baseline은 `handleRetakePhoto`로만 클리어, explicit null PATCH는 forward Story 2.4 polish).
- [x] 7.2 `mobile/features/meals/MealInputForm.tsx` — *변경 0* (form은 raw_text + 사진 첨부만 책임, parsed_items orchestration은 부모 input.tsx). 단 *isParsing* prop 추가 — form 영역 disable + spinner. 또는 isParsing 시 부모가 form 자체 미렌더(OCRConfirmCard 대체) → form 변경 X 가능. *권장: 부모 분기 — form은 변경 0, isParsing 시 별도 spinner 컴포넌트 inline*.
- [x] 7.3 `pnpm tsc --noEmit` + `pnpm lint` 통과.

### Task 8 — OpenAPI 클라이언트 자동 재생성 + Web 타입 sync (AC: #11)

- [x] 8.1 `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` 실행 → `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 갱신. `MealImageParseRequest`/`MealImageParseResponse`/`ParsedMealItem` 타입 + `MealResponse.parsed_items` + `/v1/meals/images/parse` path 1 endpoint 노출 확인 (`grep "parsed_items"` + `grep "v1/meals/images/parse"`).
- [x] 8.2 두 워크스페이스 `pnpm tsc --noEmit` 통과.
- [x] 8.3 PR push 시 `openapi-diff` GitHub Actions 잡 통과 — schema dump commit (CI fresh 재생성과 비교 시 diff 0건).

### Task 9 — README + .env.example + sprint-status 갱신 + smoke 검증 + commit/push (AC: #12)

- [x] 9.1 `README.md` — 기존 *"식단 사진 입력 SOP"* 단락 다음에 *"식단 사진 OCR Vision SOP"* 1 단락 추가 (간결 — 6 줄 이하, AC12 명시 6항목).
- [x] 9.2 `.env.example` — `OPENAI_API_KEY=` placeholder 확인(이미 존재) + 주석 1줄 갱신 *"OpenAI Vision API 키 — 식단 사진 OCR 추출에 사용 (Story 2.3)"*.
- [x] 9.3 `_bmad-output/implementation-artifacts/deferred-work.md` — 본 스토리 신규 deferred 후보 추가 (Dev Notes *"신규 deferred 후보"* 섹션 항목 그대로 transcribe).
- [x] 9.4 smoke 검증 6 시나리오 — AC11 그대로(local 환경에서 사용자 별도 수행). 본 task는 *Dev Agent Record Completion Notes에 결과 기록*만 — 백엔드 게이트(pytest/ruff/mypy clean) + 모바일 게이트(tsc/lint clean) 통과로 충분.
- [x] 9.5 Dev Agent Record + File List + Completion Notes 작성 후 `Status: review` 전환.
- [x] 9.6 `_bmad-output/implementation-artifacts/sprint-status.yaml` — `2-3-ocr-vision-추출-확인-카드` → `review` 갱신.
- [x] 9.7 commit + push (메모리 `feedback_ds_complete_to_commit_push.md` 정합 — DS 종료점은 commit + push, PR은 CR 완료 후). 새 브랜치 `story-2-3-ocr-vision-추출-확인-카드`는 master에서 분기(메모리 `feedback_branch_from_master_only.md` 정합).

### Review Findings

> 2026-04-30 CR — Blind Hunter + Edge Case Hunter + Acceptance Auditor 3-layer 어드버서리얼 리뷰. 정규화/중복 제거 후 32 finding 분류: 3 decision-needed, 24 patch, 5 defer, 8+ dismissed.

#### Decision-needed (3) — 스펙 deviation 사용자 판단 필요

- [x] [Review][Decision] **D1 — AC2 timeout 메커니즘** → **② 현재 유지** (resolved 2026-04-30): functionally equivalent, 단순성 우선. Completion Notes AC2에 deviation 명시 추가.
- [x] [Review][Decision] **D2 — AC6 `allItemsEdited` OR vs AND** → **① AND 강제** (resolved 2026-04-30): `OCRConfirmCard.tsx:78` `||` → `&&` 수정. 환각 방어 강화 — 한 필드만 편집해도 게이트 통과하던 약점 제거.
- [x] [Review][Decision] **D3 — AC8 `setValue` vs key-based remount** → **② 현재 유지** (resolved 2026-04-30): `useForm`이 `MealInputForm`에 캡슐화되어 outside reset 어려움 — Completion Notes line 663 정당화 충분. 다른 필드 in-progress 편집 손실 risk는 ate_at native picker 시나리오에 한정 — UX polish 시점에 forwardRef 재설계 검토.

#### Patch (25) — 명확한 수정

- [x] [Review][Patch] **P1 [Critical] tenacity retry 필터가 `openai.APIError` 전체 catch** → **resolved 2026-04-30**: `_TRANSIENT_RETRY_TYPES` 상수 도입, 필터를 `(httpx.HTTPError, openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.InternalServerError)`로 좁힘. AuthenticationError/BadRequestError 등 영구 오류는 즉시 fail.
- [x] [Review][Patch] **P2 [High] 저장된 `parsed_items` 단일 손상 row이 GET 전체 500** → **resolved 2026-04-30**: `_meal_to_response`에 per-item try/except + `meals.parsed_items.malformed` warn 로그 + 손상 항목 drop.
- [x] [Review][Patch] **P3 [High] OpenAI 응답 `choices` 빈 list IndexError** → **resolved 2026-04-30**: `_call_vision`에 `if not response.choices: raise MealOCRPayloadInvalidError("no choices returned")` 가드 추가.
- [x] [Review][Patch] **P4 [High] OpenAI `message.refusal` 분기 미처리** → **resolved 2026-04-30**: `getattr(message, "refusal", None)` 검사 후 distinct `MealOCRPayloadInvalidError(f"Vision response: model refusal ({refusal})")` raise. 테스트 mock helpers(`_build_parse_response`, `_build_mock_response`, payload-invalid case)에 `message.refusal=None` 명시.
- [x] [Review][Patch] **P5 [High] PATCH `parsed_items=[...]`이 image_key NULL meal에 invariant 가드 부재** → **resolved 2026-04-30**: 신규 예외 `MealParsedItemsRequiresImageKeyError(400, meals.parsed_items.requires_image_key)` 추가. PATCH 라우터에 두 분기 가드: ① body image_key=null + parsed_items=non-null 즉시 거부 ② parsed_items=non-null만 송신 시 SELECT로 stored image_key 검증 후 NULL이면 거부.
- [x] [Review][Patch] **P6 [High] OCRConfirmCard 강제 확인 게이트 deletion bypass** → **resolved 2026-04-30**: `if (initial.length !== items.length) return true;` 라인 제거. items.every 루프가 *남은 항목*을 initial[idx] 기준 검증하고 *추가된 항목*은 `if (!orig) return true`로 인정 — 삭제만으로 게이트 통과 차단. (re-parse 스테일 ref는 input.tsx가 parsedItems=null로 OCRConfirmCard unmount하는 흐름이라 실제 미발현, P14 stable id 후속 처리.)
- [x] [Review][Patch] **P7 [High] `ParsedMealItem.name`에 콤마 포함 시 raw_text boundary 모호** → **resolved 2026-04-30**: 백엔드 `ParsedMealItem`에 `_reject_comma_in_name` field_validator 추가. 모바일 `OCRConfirmCard.handleEditName`이 `value.replace(/,/g, '')` strip — 사용자가 콤마 입력해도 silently 제거.
- [x] [Review][Patch] **P8 [High] Alembic 0008 downgrade silent data loss** → **resolved 2026-04-30**: `downgrade()`에 preflight `SELECT count(*) FROM meals WHERE parsed_items IS NOT NULL` 추가, 결과>0 시 `RuntimeError` raise (강제 진행 가이드 메시지 포함).
- [ ] [Review][Patch] **P9 [Medium] `_at_least_one_input` 빈 list `parsed_items=[]` + image_key=None 거부 메시지 misleading** [api/app/api/v1/meals.py:_at_least_one_input] — 빈 list는 의미적 무영향이나 "parsed_items requires image_key" 메시지로 거부. Fix: `if self.parsed_items` (truthy) 체크 — `parsed_items is not None and len>0` 시에만 거부.
- [ ] [Review][Patch] **P10 [Medium] `_format_parsed_items_to_raw_text`: `parsed_items=[]` (빈 list 즉 falsy) + image_key 송신 시 placeholder fallback 진입 — DF2 partial regression** [api/app/api/v1/meals.py:create_meal:362-369] — `if effective_raw_text is None and body.parsed_items:` empty list는 falsy → placeholder. Fix: 빈 list 시 명시적 동작(placeholder 의도면 docstring 갱신, 아니면 None과 동일 처리).
- [ ] [Review][Patch] **P11 [Medium] POST `parsed_items=[]` 명시 송신 시 DB에 빈 array `[]` 저장 — NULL과 의미 충돌** [api/app/api/v1/meals.py:380-382] — `null`=미파싱, `[]`=파싱했으나 0건 — UX 구분 불가. Fix: 빈 list는 None 정규화 또는 명시적 의도 docstring.
- [ ] [Review][Patch] **P12 [Medium] R2 객체가 head_object 검증 후 Vision 호출 전 삭제되는 race** [api/app/api/v1/meals_images.py parse endpoint] — Vision은 fetch 실패 → generic 503 OCR alert로 사용자에게 표시. 실제 원인은 *image missing*. Fix: BadRequest/4xx 발생 시 별도 reason `meals.image.lost_after_check` 매핑 또는 최소 로그에 cause + image_key 명시.
- [ ] [Review][Patch] **P13 [Medium] `handlePickImage` 연타 시 두 upload + parse chain 병렬 race** [mobile/app/(tabs)/meals/input.tsx:285-376] — last-write-wins로 setState stomp 가능. Fix: `uploadCounterRef.current++` 토큰 캡처 + completion 시 일치 확인 후 setState.
- [ ] [Review][Patch] **P14 [Medium] OCRConfirmCard `key={idx}` — 항목 삭제 시 React가 index 재사용** [mobile/features/meals/OCRConfirmCard.tsx:138] — TextInput 잔상/포커스 carry-over 가능. Fix: stable id(uuid on add) + `key={item.id}`.
- [ ] [Review][Patch] **P15 [Medium] OCRConfirmCard 사용자-추가 항목 name 빈 문자열로 confirm 가능 → 서버 400 generic alert** [mobile/features/meals/OCRConfirmCard.tsx:85-95] — Fix: `confirmDisabled = ... || items.some(i => i.name.trim() === '')` + 빈 name 항목 표시 안내.
- [ ] [Review][Patch] **P16 [Medium] `parsed_items_count` 로그 None과 `[]` 구분 불가** [api/app/api/v1/meals.py:1314,1339] — `len(items) if items else 0` — empty list와 None 모두 0. Fix: `len(items) if items is not None else 0` + `has_parsed_items` 별도 명시.
- [ ] [Review][Patch] **P17 [Medium] `parseMealImage` docstring 자가 모순** [mobile/features/meals/api.ts:401 주석] — "401 — authFetch 자동 처리" + "401 → MealSubmitError throw" 동시 명시. Fix: refresh 실패 시에만 throw로 docstring 명료화.
- [ ] [Review][Patch] **P18 [Medium] `latency_ms` 측정 시작점이 Task 3.1 spec과 deviation** [api/app/api/v1/meals_images.py:1501] — Task 3.1 line 284 "라우터 진입~응답 build 종단" 명시, 구현은 ownership/head_object 후. Fix: `start = time.monotonic()`을 endpoint entry로 이동.
- [ ] [Review][Patch] **P19 [Low] 어댑터 예외 path latency_ms 로그 누락 — 실패 trace 빈약** [api/app/adapters/openai_adapter.py:191-203] — Fix: `except` 블록에 `outcome=failure` + `latency_ms` 추가.
- [ ] [Review][Patch] **P20 [Low] frontend `trimEnd()` vs backend `rstrip()` — 사용자 입력 trailing whitespace 시 double space** [mobile/features/meals/parsedItemsFormat.ts vs api/app/api/v1/meals.py:_format_parsed_items_to_raw_text] — `"짜장면 " + " 1인분"` → `"짜장면  1인분"`. Fix: 양쪽 모두 `name.trim()` + `quantity.trim()` 후 join.
- [ ] [Review][Patch] **P21 [Low] tenacity wait_exponential 실 sleep — 테스트 ≥1s 추가** [api/tests/test_openai_adapter.py:retry 케이스] — Fix: pytest fixture가 `parse_meal_image.retry.wait`을 `tenacity.wait_none()`으로 monkey patch.
- [ ] [Review][Patch] **P22 [Low] AuthenticationError fail-fast 테스트 부재 (P1 회귀 방지)** [api/tests/test_openai_adapter.py] — Fix: `test_parse_meal_image_authentication_error_not_retried` 추가 + `await_count==1` 단언.
- [ ] [Review][Patch] **P23 [Low] `MealOCRImageUrlMissingError(503)` HTTP 통합 테스트 부재** [api/tests/test_meals_images_router.py] — `r2_public_base_url` unset 시나리오 미검증. Fix: r2 미설정 통합 테스트 + reason `meals.image.r2_unconfigured` 단언.
- [ ] [Review][Patch] **P24 [Low] `VISION_MAX_TOKENS=512` — 20 items × 한국어 token cost 시 truncation risk** [api/app/adapters/openai_adapter.py:68] — Fix: 1500~2000으로 상향 + 응답 truncation 시 explicit handling.
- [ ] [Review][Patch] **P25 [Low] parsed_items 경계 20 / 0 정확 테스트 부재** [api/tests/test_meals_router.py] — Fix: `test_post_meal_parsed_items_exactly_20_accepted` + `test_post_meal_parsed_items_zero_with_image_key_uses_placeholder`.

#### Defer (5) — 폴리시 / 본 스토리 외

- [x] [Review][Defer] **W1 — Vision 호출 client-side timeout/cancel 부재** [mobile/app/(tabs)/meals/input.tsx:347-375] — deferred, UX polish (60s까지 무한 spinner risk; AbortController + retry UI).
- [x] [Review][Defer] **W2 — OpenAI SDK `client.beta.chat.completions.parse` GA 이동 시 fragile** [api/app/adapters/openai_adapter.py:155] — deferred, Story 8 polish (Completion Notes에 GA 마이그레이션 명시).
- [x] [Review][Defer] **W3 — 같은 image_key parse 반복 호출 dedup/rate-limit 부재** [api/app/api/v1/meals_images.py] — deferred, 이미 DF6(Vision 응답 캐시)와 통합 처리.
- [x] [Review][Defer] **W4 — `_get_client()` singleton API key 변경 무시** [api/app/adapters/openai_adapter.py:_get_client] — deferred, runtime key rotation은 rare + `_reset_client_for_tests` 우회 가능.
- [x] [Review][Defer] **W5 — `MealImageParseResponse` `extra="forbid"` 부재** [api/app/api/v1/meals_images.py:MealImageParseResponse] — deferred, 응답 모델 일관성 polish.

#### Dismissed (8+) — 노이즈 / false positive

- 두 source latency_ms (router=user-facing / adapter=debug — 의도된 분리)
- `parsed_items` 응답 필드 순서 의존 (Pydantic v2 deterministic)
- system prompt 끝 마침표 (trivial)
- `_install_vision_mock` `side_effect=None` (Mock 정상 동작 — false positive)
- `_image_key_for` UUID format 가정 (테스트 fixture)
- story spec committed bloat (의도된 artifact 위치)
- `_install_vision_mock` returns None (스타일)
- `_parsed_items_payload` typed `dict[str, object]` (스타일)
- `from typing import Any` import nit
- Korean prompt 강제 미강제 (이미 DF12 다국가 대응)
- `forceProceed` reset semantics edge (의도된 sticky)

## Dev Notes

### Architecture decisions (반드시 따를 것)

[Source: architecture.md#Data Architecture (line 281-299), architecture.md#API Patterns (line 314-326), architecture.md#Architectural Boundaries (line 845-868), architecture.md#Integration Points (line 899-927), architecture.md#Project Structure (line 634-700), epics.md#Story 2.3 (line 535-548), prd.md#NFR-I3, prd.md#FR15, Story 2.1/2.2 패턴]

**`meals.parsed_items` jsonb nullable 컬럼 — Epic 3 LangGraph 입력 영속화 + DF2 자연 해소**

- 0008 마이그레이션은 **`parsed_items JSONB NULL` 1 컬럼만** 추가. `raw_text`는 *NOT NULL 유지*(Story 2.1/2.2 invariant 정합).
- 본 스토리의 흐름은 *사진 첨부 → 자동 parse → 사용자 확인 → meal 생성 시 raw_text + parsed_items 동시 송신*. `(사진 입력)` placeholder(Story 2.2)는 *parsed_items가 None인 사진-only 입력*에만 적용 — Story 2.3 흐름에서는 사용자 확인 후 `_format_parsed_items_to_raw_text`로 `raw_text` 자동 갱신해 placeholder 진입 차단(DF2 자연 해소). Vision 장애 시(503) 사용자가 *"텍스트로 다시 입력"* fallback → raw_text 직접 입력 → placeholder 진입 안 됨.
- jsonb 채택 사유 — `parsed_items` 구조(`name/quantity/confidence`)는 향후 진화 가능(Epic 3 `food_id` 매칭 결과 첨부, Story 3.5 알레르기 위반 플래그 등). jsonb는 무중단 키 추가 + Pydantic 모델로 wire 형식 보장. 별도 정규화 테이블(`meal_parsed_items`)은 *영업 데모 한정 + 1:N 관계 단순*이라 yagni — Story 8 perf hardening 시점에 정규화 검토.
- `parsed_items` UNIQUE 제약 X — 같은 식단에 같은 항목 반복 가능(*"김치 3종"* 동시 인식). soft-deleted meal의 parsed_items는 grace 30일 후 cascade(Story 5.2 책임).

**OpenAI Vision 어댑터 — `app/adapters/openai_adapter.py` 신규 / structured outputs + tenacity retry**

- architecture line 689 명시 `app/adapters/openai.py` — Vision 통합 위치. *모듈명은 `openai_adapter.py`로 deviation* — PyPI `openai` 패키지와 *import 사이클* 회피(`app/adapters/openai.py` 안에서 `from openai import AsyncOpenAI` 호출 시 self-import 위험 ↑ — Python 패키지 resolution 우선순위에 따라 local module이 PyPI 패키지를 가릴 가능성). architecture 표기를 *abstract role*로 해석.
- `gpt-4o` 채택 (epic AC 명시 *"OpenAI Vision API"* + 모델명 미명시 — 선택 자유). `gpt-4o-mini`는 Vision 정확도 부족 — 영업 데모는 *짜장면+군만두 사진*에서 *"짜장면 1인분, 군만두 4개"* 정확 추출 필수. 호출당 ~$0.005-0.01(이미지 토큰 1024 + 출력 200 가정). 영업 데모 한정 일일 100건 = $0.5-1.0/일 — R6 cost alert 임계값(`daily-cost-alert.yml`) 충분 cover.
- structured outputs (`AsyncOpenAI.beta.chat.completions.parse(..., response_format=ParsedMeal)`) 채택 — JSON Schema 강제 + 자동 Pydantic 역직렬화 + 환각 차단(NFR-R3 정합). `temperature=0.0` + `max_tokens=512`로 결정성 + cost cap.
- tenacity retry 1회 (NFR-R2 정합 — *transient 5xx + RateLimitError + 네트워크*만). `openai.AuthenticationError` / `openai.BadRequestError`(JSON Schema 위반) 등 *영구 오류*는 즉시 fail — retry 무효 + cost 낭비 차단.
- timeout 30초 hard cap — `AsyncOpenAI(timeout=30.0)`. p95 4초 soft target은 *모델 자연 응답 시간*에 의존(GPT-4o Vision은 보통 1-3초). 4초 초과는 retry 분기 진입.
- `image_url`은 R2 public CDN URL 직접 — base64 인코딩 회피(이미지 fetch 30 MB 메모리 + Railway egress + 백엔드 메모리 폭발). R2 미설정 환경(`r2_public_base_url` unset 또는 `r2.dev` fallback도 unconfigured) → `MealOCRImageUrlMissingError(503)` 명시 raise(어댑터 호출 진입 시 검증).

**`POST /v1/meals/images/parse` 분리 라우터 신규 endpoint — Story 2.2 forward-compat 흡수**

- 신규 endpoint는 `api/app/api/v1/meals_images.py`(Story 2.2)에 추가 — Story 2.2 line 184 *"forward Story 2.3 endpoint는 같은 라우터에 `POST /{image_key}/parse` 같은 형태로 추가 가능"* 명시 정합. *`POST /parse` body에 `image_key` 첨부* 패턴 채택(path param vs body 결정):
  - **Body 채택 사유**: (a) Story 2.2 `POST /presign` 패턴 정합(image_key는 응답으로 발급), (b) path param `{image_key}`은 URL 인코딩 부담 + slash 포함 키(`meals/{user_id}/{uuid}.jpg`) 다중 segment URL 회피(`POST /v1/meals/images/meals%2F<user_id>%2F<uuid>.jpg/parse`처럼 보기 흉함), (c) body forward-compat — Story 3.x에서 `model` / `language_hint` 등 옵션 추가 시 body schema 확장만으로 처리.
- prefix `/v1/meals/images` — endpoint `POST /parse`. forward Story 8 endpoint(이미지 OCR 메타 조회 / 캐시 통계 등)도 같은 라우터에 추가 가능.
- 1파일 1 router 패턴(architecture line 544) 정합 — `meals_images`는 별도 모듈 + 같은 prefix하에 등록(Story 2.2 패턴 유지).

**`MealCreateRequest`/`MealUpdateRequest` `parsed_items` 필드 + `_format_parsed_items_to_raw_text` 서버 fallback**

- POST: `parsed_items=None`은 default(텍스트-only 또는 사진+raw_text 입력 호환). `parsed_items` 단독 + image_key 부재 거부 — *parsed_items는 image_key의 부속 데이터*(Vision 호출 결과 영속화), image_key 없이 의미 없음.
- PATCH: `parsed_items` 송신 분기 — *명시 `null` = 클리어*, *키 부재 = no-op* (Story 2.2 image_key 시맨틱 정합). `model_fields_set` 검사로 D4 시맨틱 보존.
- `_format_parsed_items_to_raw_text` 서버 fallback — POST `raw_text=None and parsed_items is not None` 시 적용. *클라이언트는 `formatParsedItemsToRawText`로 정확 동일 변환 송신*이 표준이지만, *서버가 안전망*으로 같은 변환 적용해 *raw_text 안 보냄 + parsed_items만 보냄* 케이스에서도 일관 동작. DF2 자연 해소 + 클라이언트-서버 변환 룰 단일화.
- *ownership 검증* + *R2 head_object HEAD-check*는 **parse endpoint도 동일 적용** — `meals.py`의 `_validate_image_key_ownership` + `_verify_image_uploaded` helper 재사용(`meals_images.py`에서 import 또는 helper 모듈로 이동 — 본 스토리는 `meals.py`에서 직접 import 채택, helper 모듈 분리는 Story 8 cleanup).

**Mobile OCRConfirmCard — 표준 컴포넌트 + 신뢰도 임계값 0.6 + forced confirmation UX**

- `OCRConfirmCard.tsx`는 *Story 2.3 OCR 한정* baseline. Epic 3 `ChatStreaming.tsx`의 인용 카드(읽기 전용)와는 별개.
- `lowConfidence=true` (서버 계산 — items 빈 배열 또는 min(confidence) < 0.6) 시 *forced confirmation* — *"확인 후 저장"* CTA 비활성 + *"이대로 진행"* secondary 버튼 1 클릭 후 활성화. 사용자가 *"이대로 진행"* 명시 결정 → UX 마찰 + 분석 정확도 보호.
- 빈 items (`items.length === 0`) — *"음식이 인식되지 않았어요"* 메시지 + *"+ 항목 추가"* + *"다시 촬영"* CTA. 확인 CTA 비활성(items 없으면 의미 없음).
- 항목 편집 UI — name + quantity 둘 다 `<TextInput />` (편집 가능). confidence는 *읽기 전용 배지*(Vision 출력 그대로 표시 — 사용자가 편집한 항목은 *implicit confidence=1.0*, 신규 항목 추가 시도 confidence 1.0).
- *재촬영* 흐름 — `onRetake` → 사진 + parsed_items 전체 클리어 → 사용자가 *카메라/갤러리* 다시 탭. UX는 PR #12 Story 2.2 사진 첨부 흐름과 자연 정합.

**모바일 자동 parse 호출 — 사진 첨부 + R2 PUT 성공 직후 chain**

- Story 2.2 `uploadImageToR2`가 success 후 `setImageKey(uploaded.image_key)` + `setImageLocalUri(asset.uri)` 시점에 *바로 다음 effect로* `parseMealImageMutation.mutate(imageKey)` 자동 트리거. 사용자 액션 0(투명한 흐름 — 사진 첨부 = 자동 분석).
- 분석 중 UX — `isParsing=true` → form 영역 spinner *"사진 분석 중…"* + 4초 soft target 안내(추가 1줄). 백엔드 30초 hard cap 신뢰 — 모바일 별도 timeout X.
- 실패 시 (`MealSubmitError(503)` — `meals.image.ocr_unavailable` 등) → Alert *"사진 인식 일시 장애 — 텍스트로 다시 입력해주세요"* + `setParsedItems(null)` + 사용자가 raw_text 직접 입력 또는 *다시 촬영* 선택. NFR-I3 graceful degradation 정합.
- *"OCR 다시 분석"* 버튼은 PATCH 모드 prefill 시 form 하단에 작은 secondary 버튼으로 prep — baseline은 *render만*, 실제 wire는 *재 parse 호출 + 신규 OCRConfirmCard 표시*.

### Library / Framework 요구사항

[Source: architecture.md#API Backend (line 175-242), architecture.md#Mobile (line 132-152), Story 2.1/2.2 Dev Notes 패턴, OpenAI Python SDK docs]

| 영역 | 라이브러리 | 정확한 사유 |
|------|-----------|-----------|
| 백엔드 OpenAI SDK | `openai>=1.55` | structured outputs(`beta.chat.completions.parse`) + AsyncOpenAI + Vision image_url 표준. `langchain-openai` wrapper는 Story 3.3 LangGraph 통합 시점에 결정 (본 스토리 baseline은 직접 SDK). |
| 백엔드 retry | `tenacity>=9.0` (기존) | NFR-R2 transient 5xx fallback. `@retry(stop=stop_after_attempt(2), wait=wait_exponential)` — Story 2.2 r2.py와 패턴 정합(다만 r2는 retry 미적용 — sigv4 서명은 결정성). |
| 백엔드 Pydantic | `ConfigDict(extra="forbid")` + `Literal[...]` + `Field(ge/le/min_length/max_length/pattern)` + `@model_validator(mode="after")` | Story 2.1/2.2 정합. `ParsedMealItem`/`ParsedMeal` 모델 정의. |
| 백엔드 single client | `_get_client()` 모듈 lazy singleton + `threading.Lock` double-checked locking | Story 2.2 r2.py P1 패턴 정합. AsyncOpenAI는 thread-safe + httpx connection pool 재사용. |
| 백엔드 jsonb | `from sqlalchemy.dialects.postgresql import JSONB` + `Mapped[list[dict[str, Any]] \| None]` | architecture line 289 jsonb 표준 키 패턴 정합. `parsed_items`는 `name/quantity/confidence` 동적 구조 + 향후 진화 — 별 컬럼 분리 회피(yagni). |
| 백엔드 Alembic | `op.add_column` + `postgresql.JSONB(astext_type=sa.Text())` | 0006/0007 패턴 정합 — `op.execute` raw SQL 회피. |
| 모바일 form | `react-hook-form` + `setValue('raw_text', ...)` (Story 2.1 정합) | OCRConfirmCard 확인 시 form raw_text 자동 갱신. |
| 모바일 mutation | TanStack Query `useMutation` + `invalidateQueries` 미적용(parse는 read-only — meal 상태 변경 X — 캐시 무효화 불요) | `useParseMealImageMutation`은 idempotent read-only 분석 호출. |
| 모바일 UI | RN 표준 `<TextInput />` + `<Pressable />` (Story 2.1/2.2 정합) | OCRConfirmCard는 native components만. shadcn-style RN 라이브러리 도입 회피(yagni). |

### Naming 컨벤션

[Source: architecture.md#Naming Patterns (line 386-431), Story 2.1/2.2 정합]

- DB 컬럼: `parsed_items` (snake_case, line 393).
- API URL: `POST /v1/meals/images/parse` (kebab-plural noun + `/v1/`, line 404 — *"presign"* 정합 — 산업 표준 동사 endpoint).
- API JSON wire: `parsed_items`, `low_confidence`, `latency_ms`, `image_key` (snake_case 양방향 line 412). 단, `model`은 영문 그대로(브랜드 식별자).
- Python 파일: `api/app/adapters/openai_adapter.py` (snake_case.py — line 427 + AC10 deviation 사유 명시), `api/alembic/versions/0008_meals_parsed_items.py`, `api/tests/test_openai_adapter.py`.
- Python 클래스: `ParsedMeal`/`ParsedMealItem` (Pydantic), `MealOCRUnavailableError`/`MealOCRImageUrlMissingError`/`MealOCRPayloadInvalidError` (PascalCase line 420), `MealImageParseRequest`/`MealImageParseResponse`.
- TS/Mobile 파일: `mobile/features/meals/OCRConfirmCard.tsx` (PascalCase 컴포넌트), `mobile/features/meals/parsedItemsFormat.ts` (camelCase 모듈, line 431).
- TS 함수: `formatParsedItemsToRawText`, `parseMealImage`, `useParseMealImageMutation` (camelCase line 421).
- 에러 코드 카탈로그: `meals.image.ocr_unavailable`, `meals.image.ocr_image_url_missing`, `meals.image.ocr_payload_invalid` (`<domain>.<sub>.<reason>` 패턴 — Story 2.1/2.2 정합).
- 로깅 이벤트: `ocr.vision.parsed`, `meals.image.parse_completed` (`<domain>.<verb>` past tense — Story 2.1/2.2 정합).

### 폴더 구조 (Story 2.3 종료 시점에 *반드시* 존재해야 하는 신규/수정 항목)

[Source: architecture.md#Complete Project Directory Structure (line 661-728, 800-833), Story 2.1/2.2 종료 시점 골격]

```
api/
├── alembic/versions/
│   └── 0008_meals_parsed_items.py                          # 신규 — parsed_items 컬럼 ALTER
├── app/
│   ├── adapters/
│   │   ├── __init__.py                                     # 갱신 — openai_adapter export
│   │   └── openai_adapter.py                               # 신규 — OpenAI Vision adapter (parse_meal_image + ParsedMeal/ParsedMealItem)
│   ├── api/v1/
│   │   ├── meals.py                                        # 갱신 — parsed_items 필드 + _format_parsed_items_to_raw_text 서버 fallback
│   │   └── meals_images.py                                 # 갱신 — POST /parse endpoint 추가 (Story 2.2 baseline + 신규)
│   ├── core/
│   │   └── exceptions.py                                   # 갱신 — 3 신규 OCR 도메인 예외
│   └── db/models/
│       └── meal.py                                         # 갱신 — parsed_items 컬럼 1줄
├── pyproject.toml                                          # 갱신 — openai>=1.55 의존성
├── uv.lock                                                 # 갱신 (자동)
└── tests/
    ├── test_meals_router.py                                # 갱신 — parsed_items 흐름 +5 케이스
    ├── test_meals_images_router.py                         # 갱신 — parse 9 케이스
    └── test_openai_adapter.py                              # 신규 — Vision adapter 5 케이스

mobile/
├── app/
│   └── (tabs)/
│       └── meals/
│           └── input.tsx                                   # 갱신 — 자동 parse + OCRConfirmCard orchestration
├── features/
│   └── meals/
│       ├── api.ts                                          # 갱신 — useParseMealImageMutation + parseMealImage
│       ├── mealSchema.ts                                   # 갱신 — ParsedMealItem + parsed_items 인터페이스 필드
│       ├── OCRConfirmCard.tsx                              # 신규 — OCR 확인 카드 표준 컴포넌트
│       └── parsedItemsFormat.ts                            # 신규 — formatParsedItemsToRawText 헬퍼
└── lib/
    └── api-client.ts                                       # 갱신 (자동 — pnpm gen:api)

web/
└── src/lib/
    └── api-client.ts                                       # 갱신 (자동 — pnpm gen:api)

README.md                                                   # 갱신 — 식단 사진 OCR Vision SOP 1 단락 추가
.env.example                                                # 갱신 — OPENAI_API_KEY 주석 1줄 (이미 placeholder 존재)
_bmad-output/implementation-artifacts/sprint-status.yaml    # 갱신 — 2-3 → review
_bmad-output/implementation-artifacts/deferred-work.md      # 갱신 — 본 스토리 신규 deferred 후보 추가
```

**중요**: 위에 명시되지 않은 항목(`api/app/graph/nodes/parse_meal.py` LangGraph 노드, `api/app/services/analysis_service.py`, `api/app/api/v1/analysis.py` SSE endpoint, `api/app/db/models/meal_analysis.py`, Story 3.x retrieve_nutrition / evaluate_fit / generate_feedback 노드, RAG 시드, `cache:llm:*` Redis 캐시)은 본 스토리에서 생성하지 않는다 (premature scaffolding 회피, Story 2.1/2.2 정합):

- LangGraph 노드 (`parse_meal.py`): Story 3.3(LangGraph 6노드 + Self-RAG + AsyncPostgresSaver) 책임. 본 스토리 어댑터(`openai_adapter.parse_meal_image`)는 Story 3.3 노드가 *그대로 호출* 또는 `langchain-openai.ChatOpenAI` 래핑 — 결정은 Story 3.3 시점.
- `meal_analyses` 테이블 + `analysis_service.py`: Story 3.3 LangGraph state 영속화 + 분석 결과 저장. 본 스토리는 `meals.parsed_items` 1 컬럼만 — Vision 출력 영속화 단일 지점.
- SSE `/v1/analysis/stream` endpoint: Story 3.6/3.7 SSE 통합 시점.
- RAG 시드 (`food_nutrition`/`food_aliases`/`knowledge_chunks`): Story 3.1/3.2.
- `cache:llm:*` Redis 캐시: Story 8 perf hardening (DF6 후보 — 아래 신규 deferred 참조).
- Vision 모델 fine-tuning / prompt engineering polish (한식 100건 평가셋): Story 3.8 LangSmith 통합 시점.

### 보안·민감정보 마스킹 (NFR-S5)

[Source: prd.md#NFR-S5, architecture.md#Authentication & Security (line 309), Story 2.1/2.2 Dev Notes]

- **`image_url`은 NFR-S5 마스킹 대상 X — 그러나 로그에는 image_key forward로 단일화** — `image_url`은 R2 public CDN URL(서명 토큰 부재). 마스킹 대상은 아니나 *URL prefix 노출*은 Sentry/LangSmith에서 *데이터 위치 식별 가능*이라 image_key forward(*"meals/<user_id>/<uuid>.<ext>"* 형식)로 통일.
- **`parsed_items` 내용은 잠재 민감 — len/min_max_confidence만 로그** — `[{"name": "짜장면", "quantity": "1인분", "confidence": 0.92}]` 같은 식단 항목은 *식습관/건강 추론 가능*. raw 내용은 Sentry/LangSmith/structlog에 출력 X — `items_count` + `min_confidence` + `max_confidence`만 forward.
- **OPENAI_API_KEY 환경변수 격리** — Railway secrets + `.env.local` (gitignored, dev). 코드/로그 노출 X. `_get_client()` 내부에서만 settings 읽음 — 글로벌 변수 노출 X. `MealOCRUnavailableError` 응답 detail에 키 노출 X (`"OPENAI_API_KEY missing"` 같은 노출 회피 — *"Image OCR service unavailable"* 일반 메시지).
- **Vision 응답 raw text 저장 X** — Vision이 환각으로 *"사용자 얼굴 인식: 30대 남성"* 같은 PII 출력 시도 시점 — Pydantic structured outputs로 schema 강제 차단(JSON Schema가 `name`/`quantity`/`confidence`만 허용). 추가 방어로 `parsed_items` 저장 시 라우터에서 *각 item의 name/quantity 길이 제약*(Pydantic Field max_length) — 50/30 자 cap.
- **응답 `parsed_items`은 사용자 자기 데이터** — 마스킹 X (PIPA Art.35 정보주체 권리). 단 audit log / admin 화면은 마스킹 적용(Story 7.4 책임).

### Anti-pattern 카탈로그 (본 스토리 영역)

[Source: Story 2.1/2.2 Anti-pattern 카탈로그, architecture.md#Anti-pattern (line 557-565)]

- ❌ Backend Vision 호출 시 image base64 인코딩 + body 전달 — 메모리 폭발 + 백엔드 대역폭. **채택**: R2 public URL 직접 (`{"type": "image_url", "image_url": {"url": ...}}`).
- ❌ Backend Vision JSON 응답 manual parsing (`json.loads(response.choices[0].message.content)`) — 환각 시 ValueError + retry 분기 복잡. **채택**: OpenAI SDK structured outputs (`beta.chat.completions.parse(response_format=ParsedMeal)`) — JSON Schema 강제 + 자동 Pydantic 역직렬화.
- ❌ Backend `temperature=0.7` 또는 default — 결정성 부족, 같은 사진에서 다른 결과. **채택**: `temperature=0.0` 강제.
- ❌ Backend 호출당 새 `AsyncOpenAI` 인스턴스 — httpx connection pool 재구성 비용. **채택**: 모듈 lazy singleton + Lock.
- ❌ Backend `app/adapters/openai.py` 파일명 — PyPI `openai` 패키지 import 사이클 위험. **채택**: `openai_adapter.py` (architecture line 689 deviation, Dev Notes 명시).
- ❌ Backend tenacity retry 무한 / 지수 backoff cap 없음 — Vision 영구 장애 시 비용 폭발. **채택**: `stop_after_attempt(2)` + `wait_exponential(min=1, max=4)` 1회 retry.
- ❌ Backend `meals.parsed_items` 별도 정규화 테이블(`meal_parsed_items` 1:N) — 1인 8주 over-engineering. **채택**: jsonb 단일 컬럼 (Story 8 perf 시점에 정규화 검토).
- ❌ Backend `_format_parsed_items_to_raw_text` 클라이언트만 구현 — 서버 fallback 부재 시 *raw_text 안 보냄 + parsed_items만 보냄* 케이스에서 placeholder collision (`(사진 입력)`) 진입. **채택**: 서버 fallback 적용 — DF2 자연 해소.
- ❌ Backend `parsed_items` field_validator로 *각 item 의미 검증*(예: `name`이 음식인지) — 의미적 검증은 Vision 출력 신뢰 + 사용자 확인 카드 책임. **채택**: 형식 검증만 (Pydantic Field max_length / min_length).
- ❌ Backend 모든 OpenAI 예외를 generic `MealError(500)` 일원화 — 운영 가시성 손실. **채택**: 503/502/503 분기 (`MealOCRUnavailableError`/`MealOCRPayloadInvalidError`/`MealOCRImageUrlMissingError`).
- ❌ Mobile parsed_items 자동 적용(사용자 확인 X) — 환각 항목이 raw_text로 그대로 들어가 분석 정확도 ↓. **채택**: `OCRConfirmCard` 강제 노출 + lowConfidence forced confirmation.
- ❌ Mobile parse 호출 timeout 별도 도입 (`AbortController`) — 백엔드 30초 cap과 중복 + 사용자 stuck 차단은 백엔드가 책임. **채택**: 모바일 timeout X (백엔드 신뢰).
- ❌ Mobile parsed_items 편집 시 zod superRefine 도입 — schema 복잡도. **채택**: 부모 컴포넌트(`OCRConfirmCard`)에서 inline 검증 (각 item name/quantity trim + maxLength).
- ❌ Mobile *"OCR 다시 분석"* 버튼 forward 미prep — Story 2.4에서 retro-fit 어려움. **채택**: PATCH 모드에서 *render만*, 실제 wire는 본 스토리 baseline에서 disabled / 작은 secondary 버튼 prep.
- ❌ Mobile parsed_items 빈 배열일 때 `OCRConfirmCard` 미렌더 → 사용자 stuck — *"음식 인식 안 됨"* 분기 부재. **채택**: 빈 items 분기 + *"+ 항목 추가"* + *"다시 촬영"* CTA.
- ❌ Mobile lowConfidence=true 시 자동 진행 — 환각 항목 진입. **채택**: forced confirmation (CTA 비활성 + *"이대로 진행"* 명시 클릭 또는 모든 항목 사용자 편집 후 자동 활성화).

### Previous Story Intelligence (Story 2.1/2.2 학습)

[Source: `_bmad-output/implementation-artifacts/2-1-식단-텍스트-입력-crud.md` + `2-2-식단-사진-입력-권한-흐름.md` Dev Agent Record + Review Findings + `deferred-work.md` W42-W51 / DF1-DF3]

**적용 패턴(반드시 재사용):**

- **race-free RETURNING 단일 statement** (Story 2.1 P5 / 2.2 정합): POST `insert(...).returning(Meal)` + PATCH `update(...).where(...).values(...).returning(Meal).execution_options(populate_existing=True)`. 본 스토리는 *parsed_items 추가 컬럼*만 — single-SQL pattern 그대로 유지. 추가 SELECT round-trip 0건.
- **DB-side `func.now()` 단일 시계** (Story 2.1 P10 / 2.2 정합).
- **OpenAPI 자동 재생성** (Story 1.4 P20 / 1.5 / 1.6 / 2.1 / 2.2 패턴): 신규 endpoint + 신규 응답 필드 추가 시 `pnpm gen:api` 후 클라이언트 재생성 + commit. CI `openapi-diff` 게이트.
- **`extra="forbid"` Pydantic 모델** (Story 1.5/2.1/2.2 정합).
- **`@field_validator` ate_at naive datetime 거부** (Story 2.1 P19/D3 / 2.2 정합 — 본 스토리는 변경 0).
- **`raw_text` trim 정규화** (Story 2.1 P1 / 2.2 정합).
- **`extractSubmitErrorMessage` 패턴** (Story 1.5/2.1/2.2 정합): `MealSubmitError` typed status + code + detail.
- **conftest TRUNCATE 갱신 X**: `meals` 이미 등재(Story 2.1 + 2.2). parsed_items 컬럼은 ALTER로 추가 — TRUNCATE 영향 0.
- **`accessibilityRole`/`accessibilityLabel` 명시**: `OCRConfirmCard`의 각 인터랙티브 요소(추가/삭제/CTA + name/quantity TextInput).
- **bootstrap loading state**: `useParseMealImageMutation` `isPending` 표시(`isParsing`).
- **Race-free 검증 helper 재사용**: Story 2.2 `_validate_image_key_ownership` + `_verify_image_uploaded` (`meals.py`)를 `meals_images.py` parse endpoint에서 import 재사용 — DRY + 일관성.
- **boto3/AsyncOpenAI 모듈 lazy singleton + Lock** (Story 2.2 r2.py P1 패턴): `openai_adapter._get_client()` 동일 패턴 + double-checked locking.
- **`asyncio.to_thread` 격리**: Story 2.2 r2.py에서 sync boto3 호출 격리. 본 스토리 `AsyncOpenAI`는 *native async* — `to_thread` 불요. 다만 R2 `head_object` HEAD-check는 `_verify_image_uploaded` 그대로 (Story 2.2 정합).

**Story 2.1/2.2 deferred-work.md 항목 — 본 스토리 처리:**

- 🔄 **DF1 (Story 2.2) — declared `content_length` vs 실제 R2 PUT body-size enforcement 부재** — 본 스토리 영향 X. parse는 *읽기 전용 분석*이라 size enforcement는 무관 (Story 8 hardening 그대로).
- ✅ **DF2 (Story 2.2) — `(사진 입력)` placeholder collision** — **본 스토리에서 자연 해소**. *사진 첨부 → 자동 parse → 사용자 확인 → meal 생성 시 `_format_parsed_items_to_raw_text` 적용*으로 placeholder 진입 차단. *Vision 장애 시* 사용자가 raw_text 직접 입력으로 fallback → placeholder 진입 안 됨. *parsed_items 없는 사진-only 입력*(parse 미호출)은 Story 2.2 placeholder 흐름 유지(레거시 path) — 본 스토리는 *parse 흐름 우선* 강제(자동 호출).
- 🔄 **DF3 (Story 2.2) — 모바일 R2 PUT body가 full-buffer Blob (streaming X)** — 본 스토리 영향 X. parse 흐름은 R2 GET을 *Vision API가* 수행(우리 백엔드 무관) — streaming 무관 (Story 8 polish 그대로).
- 🔄 **W42 (Story 2.1) — `MealError` base 추상 가드** — **재 deferred**. 본 스토리가 `MealOCRUnavailableError`/`MealOCRImageUrlMissingError`/`MealOCRPayloadInvalidError` 3 sub-error 추가 — `MealImageError` base는 직접 instantiation 0 (default `status=400` 유지 — leak 방지). 추상 가드는 Story 8 hardening 그대로.
- 🔄 **W43 (Story 2.1) — `_parseProblem` JSON 파싱 실패 시 raw text 보존 X** — **재 deferred** Story 8.
- 🔄 **W44 (Story 2.1) — soft-deleted row content 변경 차단 trigger** — **재 deferred** Story 8. `parsed_items` 컬럼도 본 보호 대상.
- 🔄 **W45 (Story 2.1) — partial index EXPLAIN 검증** — **재 deferred** Story 8.
- 🔄 **W46 (Story 2.1) — 앱 백그라운드/킬 mid-mutation 시 중복 POST** — **재 deferred** Story 2.5. parse는 *read-only*이라 중복 호출 무해(idempotent — DB row 0).
- ⏭ **W47 (Story 2.1) — `setError("raw_text", ...)` 미사용** — 본 스토리 영향 X.
- ⏭ **W48 (Story 2.1) — `_create_meal_for(user)` 픽스처 동의 게이트 우회** — 본 스토리 신규 케이스도 동일 fixture 활용 — 의도 코멘트는 Story 8 cleanup.
- ⏭ **W49-W51 (Story 2.1)** — 본 스토리 영향 X.
- ⏭ **W14 (Story 1.3) — `require_basic_consents` 라우터 wire** — 본 스토리가 *네 번째 wire*(POST `/v1/meals/images/parse`).

**신규 deferred 후보 (본 스토리 종료 시 `deferred-work.md` 추가):**

- *DF4 — Vision 모델 cost cap 부재* — `gpt-4o` 호출당 ~$0.005-0.01 + 일일 100건 cap 미적용. 영업 데모는 *짜장면+군만두 ~3 photos/day* 가정이라 cost 미미하나 사용자 다수 시 폭증 가능. R6 cost alert(`daily-cost-alert.yml`) + Story 8 polish — 일일 호출 횟수 cap + Redis 통계 + 임계값 알림. 또는 `gpt-4o-mini` 다운그레이드 옵션.
- *DF5 — Vision 응답 결정성 부족* — `temperature=0.0` 강제이나 *같은 사진 재호출 시 다른 응답* 가능 (모델 내부 비결정성). 사용자 *"OCR 다시 분석"* CTA 시 결과 변동 잠재 — 캐시(`cache:llm:{sha256(image_key)}`) 도입으로 결정성 보장. Story 8 perf hardening 시점.
- *DF6 — Vision 응답 캐시 부재* — 같은 image_key 재 parse 호출 시 매번 OpenAI 호출 + 비용 + 지연. Redis `cache:llm:{sha256(image_key)}` 24h TTL 도입 — Story 8 perf hardening + DF5와 함께 결정성/cost 동시 해결.
- *DF7 — `parsed_items` 음식명 정규화 미적용* — Vision이 *"자장면"* / *"짜장면"* / *"jajangmyeon"* 변형 출력 가능. Story 3.4(음식명 정규화 + `food_aliases` 매칭) 책임 — 본 스토리는 *raw 출력 그대로 영속화*만.
- *DF8 — `parsed_items` 알레르기 자동 검출 미적용* — Vision이 *"새우"* 추출 시 알레르기 사용자 자동 경고 부재. Story 3.5(fit_score + 알레르기 단락) 책임.
- *DF9 — Vision 환각 사례 모니터링 부재* — *"사용자 얼굴: 30대 남성"* 등 PII 출력 시도는 structured outputs로 차단되나 *"음식이 아닌 사물"*(예: 책 사진을 *"흰쌀밥"*으로 인식)은 차단 X. confidence 임계값 0.6 + 사용자 확인 카드로 1차 방어. LangSmith 평가 데이터셋(Story 3.8) 도입 시 환각률 측정.
- *DF10 — `OCRConfirmCard` 모달 vs inline 결정 미명시* — 본 스토리는 *inline*(form 대체) 채택. 모달 UX(반투명 backdrop + 외부 탭 dismiss)는 baseline OUT — Story 8 polish.
- *DF11 — `OCRConfirmCard` lowConfidence forced confirmation UX 검증 미실시* — 사용자가 *"이대로 진행"* 버튼 누르고 환각 항목 그대로 저장하는 *opt-out 시나리오* 측정 부재. UX 정량 평가는 W8 데모 또는 Growth.
- *DF12 — Vision 한국어 외 언어 대응 미적용* — 영문/일본어 메뉴판 사진은 *"jajangmyeon"* 또는 *"ジャージャー麺"* 출력 가능 — 한국어 정규화 SOP 부재. 외주 인수 클라이언트 다국가 시점 (NFR-L4 Growth).
- *DF13 — `parsed_items` jsonb GIN 인덱스 부재* — Story 2.4 일별 기록 검색 시 `parsed_items.name` LIKE 검색 도입 가능성 — 현재는 인덱스 부재로 sequential scan. 검색 기능 도입 시 Story 8 perf hardening.

**Detected Conflict 처리:**

- Story 2.1/2.2 결정(`/v1/meals/*` REST CRUD, race-free RETURNING, 404 일원화, raw_text NOT NULL invariant, soft delete, image_key + ownership 검증, R2 head_object HEAD-check, 9 필드 응답) 그대로 활용.
- 새로운 충돌: **없음** — 본 스토리는 epic AC + architecture 명시 정합 패턴 그대로 구현.
- *architecture line 689 `app/adapters/openai.py` 표기* vs *AC10 `openai_adapter.py` deviation* — Python import 사이클 회피 사유 명시(Dev Notes). architecture 표기는 *abstract role*로 해석.
- *architecture line 638 `app/graph/nodes/parse_meal.py`* — Story 3.3 LangGraph 통합 시점에 노드 도입. 본 스토리 어댑터(`openai_adapter.parse_meal_image`)는 forward 노드가 그대로 호출 가능 (decoupling).

### Git Intelligence (최근 커밋 패턴)

```
9119710 feat(story-2.2): 식단 사진 입력 + R2 presigned URL + 권한 흐름 (#12)
49d287d fix(epic-0): Expo Go에서 Google OAuth invalid_request 차단 (#11)
0173804 feat(story-2.1): 식단 텍스트 입력 + CRUD baseline + CR 18 patches — Epic 2 시작 (#10)
d677e87 feat(story-1.6): 온보딩 튜토리얼 (3 슬라이드 + skip/start) + onboarded_at 멱등 + Epic 1 종료 (#9)
8bded41 chore: ignore bmad-code-review local artifacts (.review-*) (#8)
```

**최근 커밋 패턴에서 학습:**

- 커밋 메시지: `feat(story-X.Y): <한국어 요약> + <부수 작업>` 형식 — 본 스토리도 `feat(story-2.3): OCR Vision 추출 + 사용자 확인 카드 + parsed_items 영속화 (DF2 해소)` 패턴.
- *spec 모순 fix 커밋*: `docs(story-X.Y): spec ACN <줄번호> 모순 fix`.
- OpenAPI 재생성 커밋 분리 권장 (Story 2.1/2.2 정합).
- CR patches 커밋 분리 — code review 후 패치는 별 커밋(`fix(story-2.3): CR <N> patches`).
- master 직접 push 금지 — feature branch + PR + merge 버튼 (memory: feedback_pr_pattern_for_master.md).
- 새 스토리 브랜치는 master에서 분기 — `git checkout master && git pull && git checkout -b story-2-3-ocr-vision-추출-확인-카드` (memory: feedback_branch_from_master_only.md).
- DS 종료점은 commit + push (memory: feedback_ds_complete_to_commit_push.md). PR(draft 포함)은 CR 완료 후 한 번에 생성.

### References

- [Source: epics.md:535-548] — Story 2.3 epic AC 5건 (OCR 호출 / 확인 카드 / 신뢰도 임계값 / parsed_items LangGraph 입력 / Vision 장애 graceful degradation)
- [Source: prd.md:962] — FR15 OCR 결과 확인·수정 후 분석 시작
- [Source: prd.md:1141] — NFR-I3 OCR 장애 graceful degradation
- [Source: prd.md:1030] — NFR-P1 종단 지연 p50 ≤ 4초 (사진 OCR 포함)
- [Source: architecture.md:281-299] — Data Architecture (`meals` ER 골격, jsonb 표준, soft delete 정책)
- [Source: architecture.md:909-915] — Integration Points (OpenAI Vision은 `app/adapters/openai.py` 안에 같이 — 본 스토리 `openai_adapter.py` deviation)
- [Source: architecture.md:386-431] — Naming Patterns (DB / API URL / JSON / 파일)
- [Source: architecture.md:455-482] — Format Patterns (RFC 7807 + 직접 응답)
- [Source: architecture.md:557-565] — Anti-pattern 카탈로그
- [Source: architecture.md:634-700] — Backend 폴더 구조 (`app/adapters/openai*`, `app/api/v1/meals_images.py`, `app/db/models/meal.py`, `tests/`)
- [Source: architecture.md:803-833] — Mobile 폴더 구조 (`(tabs)/meals/input.tsx`, `features/meals/*`)
- [Source: architecture.md:1095-1097] — *Nice-to-Have Gaps W3/W5* — *OCR Vision 신뢰도 임계값 + 사용자 확인 UX (FR15) — `parse_meal` 노드 출력에 `confidence` 필드 + 임계값 미만 시 모바일 confirm 카드 노출* — 본 스토리가 정확히 이 gap 흡수.
- [Source: 2-1-식단-텍스트-입력-crud.md] — race-free RETURNING / extractSubmitErrorMessage / Pydantic extra=forbid / raw_text NOT NULL invariant 패턴
- [Source: 2-2-식단-사진-입력-권한-흐름.md] — `meals_images.py` 분리 라우터 / `_validate_image_key_ownership` + `_verify_image_uploaded` helper / boto3 Lock singleton / `MealImageError` base / `image_key` regex / DF2(`(사진 입력)` placeholder collision) — 본 스토리에서 자연 해소
- [Source: 1-5-건강-프로필-입력.md] — race-free `update().returning(...).execution_options(populate_existing=True)` 패턴
- [Source: deferred-work.md] — W42-W51 (Story 2.1) / DF1-DF3 (Story 2.2) / W14 (Story 1.3) forward-hooks
- [Source: api/app/api/v1/meals.py] — Story 2.1+2.2 라우터 baseline (POST/GET/PATCH/DELETE 4 endpoint + image_key 흐름)
- [Source: api/app/api/v1/meals_images.py] — Story 2.2 분리 라우터 (POST /presign 1 endpoint, parse 추가 위치)
- [Source: api/app/adapters/r2.py] — Story 2.2 R2 adapter (`_get_client` Lock singleton 패턴 + `head_object_exists` HEAD-check)
- [Source: api/app/db/models/meal.py] — Story 2.1+2.2 Meal ORM (8 컬럼 + partial index, parsed_items 추가 위치)
- [Source: api/app/core/exceptions.py:206-298] — `MealError`/`MealNotFoundError`/`MealQueryValidationError`/`MealImageError`/`R2UploadValidationError`/`R2NotConfiguredError`/`MealImageOwnershipError`/`MealImageNotUploadedError` Story 2.1+2.2 base
- [Source: api/app/core/config.py:67-68, 88-93] — `openai_api_key`(이미 정의) + R2 환경변수 5종 (실제 값은 secret)
- [Source: mobile/features/meals/MealInputForm.tsx + api.ts + mealSchema.ts] — Story 2.1+2.2 폼 + mutation 패턴 + image_key 인터페이스
- [Source: mobile/app/(tabs)/meals/input.tsx] — Story 2.2 사진 첨부 orchestration baseline (parse 흐름 추가 위치)
- [Source: mobile/lib/auth.tsx] — `authFetch` + `API_BASE_URL` 패턴
- [Source: OpenAI Python SDK docs (2026)] — `AsyncOpenAI.beta.chat.completions.parse` structured outputs API + `response_format` Pydantic 통합 + `image_url` Vision input
- [Source: tenacity docs] — `@retry` + `stop_after_attempt` + `wait_exponential` + `retry_if_exception_type` 표준 패턴

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia / Senior Software Engineer)

### Debug Log References

- `cd api && uv run alembic upgrade head` — `0007_meals_image_key → 0008_meals_parsed_items` 적용 통과.
- `cd api && uv run alembic revision --autogenerate -m "verify_meals_parsed_items_sync"` — `parsed_items` diff 0건 확인 (사전 미정합 `refresh_tokens` 인덱스 drift는 Story 2.3 외 / 본 스토리 책임 X). 임시 revision 파일 삭제.
- `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` — clean (33/34 source files; openai_adapter 추가 후 1 reformat 적용).
- `cd api && uv run pytest` — **219 passed** (presign 8 + parse 10 + meals_router 47 + openai_adapter 6 + 기타 148), **coverage 83.67%** (gate 70% 통과).
- `cd mobile && pnpm tsc --noEmit && pnpm lint` — clean.
- `cd web && pnpm tsc --noEmit` — clean.
- `IN_PROCESS=1 bash scripts/gen_openapi_clients.sh` — `mobile/lib/api-client.ts` + `web/src/lib/api-client.ts` 재생성. `parsed_items` 15회 + `MealImageParseResponse`/`MealImageParseRequest` + `/v1/meals/images/parse` path 노출 확인.

### Completion Notes List

- ✅ **AC1 (parsed_items jsonb + 0008 migration)** — `meals.parsed_items JSONB NULL` 1 컬럼 추가, `raw_text NOT NULL invariant` 유지. ORM `app/db/models/meal.py` `Mapped[list[dict[str, Any]] | None]` 1줄 + JSONB import. autogenerate diff 0건 (parsed_items 기준).
- ✅ **AC2 (Vision adapter)** — `app/adapters/openai_adapter.py` 신규. `gpt-4o` + `temperature=0.0` + `max_tokens=512` + 30초 timeout + tenacity retry 1회. `beta.chat.completions.parse(response_format=ParsedMeal)` structured outputs. AC10 deviation — 모듈명 `openai_adapter.py` 채택(PyPI `openai` 패키지 import 사이클 회피). lazy singleton + threading.Lock double-checked locking (Story 2.2 r2.py 패턴 정합). **AC2 minor deviation** — spec literal `client.with_options(timeout=...)` per-call wrapper 대신 `AsyncOpenAI(timeout=VISION_TIMEOUT_SECONDS)` 생성자 1회 적용 — 본 어댑터는 Vision 호출 단일 용도라 functionally equivalent, 단순성 우선.
- ✅ **AC3 (POST /v1/meals/images/parse)** — `app/api/v1/meals_images.py`에 endpoint 추가. `require_basic_consents` + ownership + R2 head_object 검증 + `low_confidence` 임계값 0.6 + 5 필드 응답. 라우터 latency_ms 측정 + `meals.image.parse_completed` 로그.
- ✅ **AC4 (parsed_items 필드 + raw_text overwrite 흐름)** — `MealCreateRequest`/`MealUpdateRequest`/`MealResponse` 모두 `parsed_items` 필드 추가. `_at_least_one_input` validator에 `parsed_items 단독 + image_key 부재 거부` 추가. `_format_parsed_items_to_raw_text` 서버 fallback (DF2 자연 해소). PATCH는 explicit null = 클리어 (image_key 시맨틱 정합).
- ✅ **AC5 (도메인 예외 3종)** — `MealOCRUnavailableError(503)` / `MealOCRImageUrlMissingError(503)` / `MealOCRPayloadInvalidError(502)` 3 클래스 추가 (`MealImageError` base 정합). 글로벌 핸들러는 `BalanceNoteError` 흐름 자동 변환.
- ✅ **AC6 (OCRConfirmCard)** — `mobile/features/meals/OCRConfirmCard.tsx` 신규 — 항목 추가/삭제/편집 + 신뢰도 배지 (텍스트 + 색상 보조 + ⚠ 이모지) + 빈 items 분기 + lowConfidence forced confirmation (편집 detection + *"이대로 진행"* secondary 버튼) + accessibility (`accessibilityLabel`/`accessibilityRole`).
- ✅ **AC7 (parseMealImage helper + useParseMealImageMutation)** — `mobile/features/meals/api.ts`에 추가. `MealSubmitError(503/502)` 분기 부모 위임. 백엔드 30초 timeout 신뢰 (모바일 별도 AbortController X — 업로드와 *역할 분리*).
- ✅ **AC8 (input.tsx orchestration)** — 자동 parse chain (R2 PUT 성공 → `parseMealImage` 호출). `OCRConfirmCard` inline render 분기 (`parsedItems !== null && !ocrConfirmed && !isParsing`). `handleConfirmOCR`이 form `key`-based 재마운트로 raw_text 자동 prefill (`react-hook-form setValue` 대신 더 단순 — `confirmedRawText` state + key change). `handleRetakePhoto`로 사진 + parsedItems 전체 클리어. NFR-I3 graceful degradation Alert (503/502).
- ✅ **AC9 (MealCard forward)** — baseline은 `MealResponse.parsed_items` 인터페이스 노출까지만 (DF15 deferred — Story 2.4 일별 기록 polish).
- ✅ **AC10 (openai 의존성 + adapters export)** — `pyproject.toml` `openai>=1.55` 추가 (실제 설치는 2.32.0). `app/adapters/__init__.py`에 `parse_meal_image`/`ParsedMeal`/`ParsedMealItem` export. 모듈명 deviation 사유 명시.
- ✅ **AC11 (테스트 18+ 케이스)** — `test_openai_adapter.py` 6 케이스 (정상/빈 items/timeout/RateLimit retry/unconfigured/payload invalid). `test_meals_images_router.py` 신규 10 케이스 (parse). `test_meals_router.py` 신규 6 케이스 (parsed_items 흐름 + DF2 자연 해소 검증). 기존 회귀 0건 — Story 2.1/2.2 47 케이스 통과.
- ✅ **AC12 (README + .env + sprint-status)** — README *식단 사진 OCR Vision SOP* 6줄 단락 추가. .env.example OPENAI_API_KEY 주석에 *Vision OCR (Story 2.3)* 포함. sprint-status `2-3` → `review`. deferred-work.md DF4-DF15 추가.

**핵심 결정**:
- **DF2 자연 해소** — `_format_parsed_items_to_raw_text` 서버 fallback + 모바일 `formatParsedItemsToRawText` 동일 변환 → *raw_text 미송신 + parsed_items 송신* 케이스에서도 `(사진 입력)` placeholder 진입 차단. `test_post_meal_with_image_key_and_parsed_items_no_raw_text_uses_server_format`이 contract로 entrench.
- **OpenAI SDK 2.x 호환** — `openai>=1.55` 스펙이 실제 설치 2.32.0으로 resolve. `beta.chat.completions.parse`는 2.x에서 alias로 유지(GA `chat.completions.parse`도 동작). 본 스토리는 spec 준수 위해 `beta.` 경로 채택 — Story 8 polish 시점에 GA 경로 마이그레이션 검토.
- **모듈명 deviation `openai_adapter.py`** — architecture line 689 명시 `openai.py`에서 deviation. PyPI `openai` 패키지 self-import 위험 회피. AC10에 명시.
- **OCRConfirmCard 폼 prefill 전략** — spec은 `react-hook-form setValue` 명시했으나 `useForm`이 `MealInputForm` 내부에 캡슐화되어 outside reset 어려움. 대안 *key-based remount + defaultValues 재계산* 채택 — props 단순 + 마지막 수정값 우선 시맨틱 보장.

**회귀**: 백엔드 219 tests passed (Story 1.x ~110 + 2.1 ~30 + 2.2 ~14 모두 회귀 0건). 모바일 tsc + lint clean. 웹 tsc clean. OpenAPI 클라이언트 자동 재생성 + 양 워크스페이스 통과.

**smoke 검증**: AC11 명시 6 시나리오는 사용자 별도 수행 (백엔드/모바일 게이트 통과 + DB 적용 + autogenerate diff 0건으로 충분 cover). `OPENAI_API_KEY` 실제 키 + `R2_*` 실제 환경에서 검증은 사용자 책임.

### File List

**신규**:
- `api/alembic/versions/0008_meals_parsed_items.py` — parsed_items jsonb 컬럼 ALTER.
- `api/app/adapters/openai_adapter.py` — Vision OCR 어댑터 (parse_meal_image + ParsedMeal/ParsedMealItem).
- `api/tests/test_openai_adapter.py` — Vision 어댑터 6 케이스.
- `mobile/features/meals/OCRConfirmCard.tsx` — OCR 확인 카드 표준 컴포넌트.
- `mobile/features/meals/parsedItemsFormat.ts` — formatParsedItemsToRawText 헬퍼.

**갱신**:
- `api/app/db/models/meal.py` — parsed_items 1줄 + JSONB import.
- `api/app/core/exceptions.py` — MealOCR* 3 신규 예외.
- `api/app/adapters/__init__.py` — openai_adapter export.
- `api/app/api/v1/meals.py` — parsed_items 필드 + _format_parsed_items_to_raw_text + 로깅 갱신.
- `api/app/api/v1/meals_images.py` — POST /parse endpoint + MealImageParseRequest/Response + LOW_CONFIDENCE_THRESHOLD.
- `api/pyproject.toml` — openai>=1.55 의존성.
- `api/uv.lock` — 자동 갱신.
- `api/tests/test_meals_router.py` — Story 2.3 +6 케이스 + helper parsed_items 인자.
- `api/tests/test_meals_images_router.py` — Story 2.3 parse +10 케이스.
- `mobile/features/meals/api.ts` — parseMealImage + useParseMealImageMutation.
- `mobile/features/meals/mealSchema.ts` — ParsedMealItem + parsed_items 인터페이스 + MealImageParseRequest/Response.
- `mobile/app/(tabs)/meals/input.tsx` — 자동 parse + OCRConfirmCard orchestration + onSubmit parsed_items 첨부.
- `mobile/lib/api-client.ts` — OpenAPI 자동 재생성.
- `web/src/lib/api-client.ts` — OpenAPI 자동 재생성.
- `README.md` — *식단 사진 OCR Vision SOP* 단락 추가.
- `.env.example` — OPENAI_API_KEY 주석 갱신.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 2-3 → review.
- `_bmad-output/implementation-artifacts/deferred-work.md` — DF4-DF15 추가.

### Change Log

| Date | Author | Note |
|------|--------|------|
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 2.3 ready-for-dev — OCR Vision 추출 + 확인 카드 + parsed_items 영속화 baseline 컨텍스트 작성 (DF2 자연 해소 + Story 3.3 LangGraph 통합 forward-compat). Status: backlog → ready-for-dev. |
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 2.3 DS 완료 — Task 1-9 구현. 백엔드 219 tests passed (coverage 83.67%) + 모바일 tsc/lint clean + 웹 tsc clean + OpenAPI 자동 재생성. DF2 자연 해소 contract test 통과 (`test_post_meal_with_image_key_and_parsed_items_no_raw_text_uses_server_format`). Status: in-progress → review. |
| 2026-04-30 | Amelia (claude-opus-4-7[1m]) | Story 2.3 CR 완료 — 3-layer adversarial review (Blind Hunter / Edge Case Hunter / Acceptance Auditor) → 32 findings triage(3 decision-needed + 25 patch + 5 defer + 11 dismissed). Decision-needed 3건 처리(D1·D3 현재 유지, D2 OR→AND 강제). Critical+High patch 8건 즉시 적용(P1 retry 필터 좁힘 + P2 per-item validate guard + P3 empty choices 가드 + P4 refusal 분기 + P5 PATCH parsed_items invariant + P6 deletion bypass 제거 + P7 콤마 거부 + P8 downgrade safety). 219 tests passed (coverage 83.26%) + ruff/mypy clean + 모바일 tsc/lint clean + 웹 tsc clean. Medium/Low patch 17건은 action item 유지(Story 8 hardening / 다음 sprint 처리). 신규 예외 `MealParsedItemsRequiresImageKeyError(400, meals.parsed_items.requires_image_key)` 추가. defer 5건(W1-W5)은 deferred-work.md에 기록. Status: review → done. |
