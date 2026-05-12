from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 모노레포 루트의 단일 `.env`를 SOT로 사용 — cwd가 `api/`든 root든 상관없이 동일하게 로드.
# api/app/core/config.py → parents[3] == repo root.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"
_API_LOCAL_ENV = Path(__file__).resolve().parents[2] / ".env"

# JWT audience — 단일 수신 서비스 식별자. platform 구분(mobile/web)은 별도 custom claim.
JWT_USER_AUDIENCE = "balancenote-api"
JWT_ADMIN_AUDIENCE = "balancenote-admin"

# Token TTL (초)
USER_ACCESS_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30일
USER_REFRESH_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60  # 90일
ADMIN_ACCESS_TOKEN_TTL_SECONDS = 8 * 60 * 60  # 8시간

# Story 5.2 — 회원 탈퇴 후 30일 grace 기간(epics.md:798 + architecture.md:351 SOT).
# auth.py(detail 합성)와 workers/soft_delete_purge.py(cutoff 계산) 양쪽이 import.
# 모듈 의존성 역전 방지(api → workers 회피)를 위해 core/config로 위치.
PURGE_GRACE_DAYS = 30

# 서버 측 비-prod 환경(쿠키 Secure flag 분기 등에서 사용).
NON_SECURE_COOKIE_ENVIRONMENTS = frozenset({"dev", "ci", "test"})

# Google id_token 허용 issuer (RFC 정합 — 두 표기 모두 발급됨).
GOOGLE_ID_TOKEN_ALLOWED_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


class Settings(BaseSettings):
    # env_file 우선순위: repo root `.env`(공유) → `api/.env`(개별 override). 후자가 있으면 덮어씀.
    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT_ENV), str(_API_LOCAL_ENV)),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # python-dotenv는 디폴트로 인라인 `# 주석`을 미지원 — `KEY=    # 빈값 주석` 라인은 lstrip 후
    # `# 빈값 주석`이 값으로 박힌다(BadDsn/etc 회귀). pre-validator로 정리:
    # 1) 값에 공백 + `#`이 있으면 그 이전까지를 값으로(`KEY=foo # comment` → `foo`).
    # 2) 정리 후 값이 `#`로 시작하면 (= 원래 라인에 실값이 없고 주석만 있던 케이스) 빈 문자열.
    @model_validator(mode="before")
    @classmethod
    def _strip_inline_comments(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, str):
                trimmed = re.sub(r"\s+#.*$", "", value).strip()
                if trimmed.startswith("#"):
                    trimmed = ""
                cleaned[key] = trimmed
            else:
                cleaned[key] = value
        return cleaned

    # --- Infra ---
    # 디폴트는 로컬 dev(`uv run uvicorn`)용 localhost. Docker 컨테이너 내부에서는
    # docker-compose.yml의 environment 블록이 `@postgres:5432` / `@redis:6379`로 override.
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    # 테스트 전용 DB — dev `app` DB와 분리. conftest.py의 autouse `_truncate_user_tables`
    # fixture가 매 테스트마다 users/meals/consents/refresh_tokens를 TRUNCATE하기 때문에
    # 분리하지 않으면 `pytest` 1회만 돌려도 dev에서 입력한 사용자·식단·동의 기록이 전부
    # 소실됨. CI는 ``DATABASE_URL_TEST`` env로 override 가능. **이름에 ``_test``가 포함되지
    # 않으면 conftest.py가 abort** — dev DB로 잘못 가리키는 사고 차단.
    database_url_test: str = "postgresql+asyncpg://app:app@localhost:5432/app_test"
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM ---
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # --- LangSmith ---
    langsmith_api_key: str = ""
    langsmith_project: str = "balancenote-dev"
    langchain_tracing_v2: bool = False

    # --- LangGraph Self-RAG (Story 3.3) ---
    # `evaluate_retrieval_quality` 노드의 분기 임계값 — `retrieval_confidence < threshold`
    # AND `rewrite_attempts < 1` 시 `rewrite_query` 재검색. prd.md line 610 baseline 0.6
    # (W2 spike 튜닝 후 prod 환경별 override 가능).
    self_rag_confidence_threshold: float = 0.6
    # LangGraph `compile(debug=...)` 토글 — dev에서만 True 권장(SSE 디버깅 정합).
    langgraph_debug: bool = False

    # --- Food RAG (Story 3.4) ---
    # ``search_by_embedding`` HNSW top-K 상한 — NFR-P6 ≤ 200ms 정합 + cost 보호. 환경
    # 변수 ``FOOD_RETRIEVAL_TOP_K`` override 가능 (NFR-O3 식약처 데이터 지속 갱신 정합).
    food_retrieval_top_k: int = 3
    # ``request_clarification`` 노드의 옵션 상한 — UI 카드 4건 안 (NFR-A1 정합). 환경
    # 변수 ``CLARIFICATION_MAX_OPTIONS`` override 가능.
    clarification_max_options: int = 4

    # --- Dual-LLM router (Story 3.6) ---
    # 메인 LLM — OpenAI ``gpt-4o-mini`` (cost 1/15 vs ``gpt-4o``, 한국어 coaching 톤
    # 충분). Story 3.8 LangSmith eval 결과 기반 ``gpt-4o`` 또는 ``gpt-4.1`` 승격 검토
    # 가능 — env override만으로 전환.
    llm_main_model: str = "gpt-4o-mini"
    # 보조 LLM — Anthropic ``claude-haiku-4-5-20251001`` (2026-05 시점 최신 Haiku, cost/
    # latency 균형 우선). Story 3.8 eval 결과로 Sonnet 4.6 승격 검토 가능.
    llm_fallback_model: str = "claude-haiku-4-5-20251001"
    # Redis LLM 캐시 TTL — FR43 baseline 24h(86400s). cost 폭발 차단(동일 식단+프로필
    # 재호출 시 LLM 0회).
    llm_cache_ttl_seconds: int = 86400
    # Router 전체 wall-time 예산 (CR MJ-22) — 초기 호출 + 최대 3회 regen +
    # OpenAI 3-attempt + Anthropic 3-attempt × 30s SDK timeout 누적이 worst-case
    # ~189s에 달함. ``asyncio.wait_for`` outer deadline로 차단(p95 mobile 4s 정합).
    llm_router_total_budget_seconds: int = 25

    # --- Vision 비용·캐시·결정성 (Story 3.9 AC6, AC7) ---
    # ``cache:llm:vision:{sha256(image_key)}`` Redis 24h TTL — 동일 image_key 재호출 시
    # OpenAI Vision 호출 0회 + ``parse_meal_image`` 결정성 보장(LLM 환각 방지).
    vision_cache_ttl_seconds: int = 86400
    # ``cost:vision:daily:{YYYY-MM-DD}`` Redis 카운터 — KST 자정 기준 일일 cap.
    # cap 도달 시 ``gpt-4o`` → ``gpt-4o-mini`` 다운그레이드 + Sentry warning.
    vision_daily_cost_cap_usd: float = 5.0
    # ``gpt-4o-mini`` 다운그레이드 후의 추가 cap — 도달 시 ``MealOCRUnavailableError``
    # raise + 사용자에게 *"오늘은 사진 분석 한도에 도달했어요"* 안내.
    vision_fallback_cost_cap_usd: float = 1.0

    # --- Analysis SSE / polling (Story 3.7) ---
    # SSE 본문 token chunking — 한국어 코칭 톤 평균 200-400자 + 24자 / 30ms로
    # 5-10초 자연 streaming UX(epic line 679 정합). True LLM-token streaming은
    # Story 8.4 polish.
    analysis_token_chunk_chars: int = 24
    analysis_token_chunk_interval_ms: int = 30
    # SSE 끊김 시 polling 강등 흐름의 클라이언트 interval. 서버는 ``Retry-After``
    # 헤더 hint(ceil)로 노출. architecture line 322 정합.
    analysis_polling_interval_seconds: float = 1.5
    # polling 최대 시도 횟수 — 30회 × 1.5초 ≈ 45초 cap(LLM 25s outer + 안전 여유).
    analysis_polling_max_attempts: int = 30

    # --- JWT (사용자 / 관리자 분리) ---
    jwt_user_secret: str = "dev-user-secret-please-rotate"
    jwt_admin_secret: str = "dev-admin-secret-please-rotate"
    jwt_user_issuer: str = "balancenote-user"
    jwt_admin_issuer: str = "balancenote-admin"

    # --- Sentry ---
    sentry_dsn: str = ""

    # --- Google OAuth ---
    # Web confidential client — `client_secret`과 함께 사용.
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Native public clients — PKCE only(client_secret 없음). dev/native build에서 필수.
    # Google Console에서 "Android"/"iOS" application type으로 별개 client 등록 필요.
    # 비어있으면 mobile platform 요청은 web client_id로 fallback (Expo Go/legacy 호환).
    google_oauth_android_client_id: str = ""
    google_oauth_ios_client_id: str = ""

    # --- Storage provider (Story 8.5) ---
    # `r2` (default, 외주 인수 옵션 보존) | `supabase` (Render+Supabase prod 패턴).
    # `r2_*` 5종은 R2 분기에서만 사용, `supabase_*` 3종은 Supabase 분기에서만 사용.
    # 어느 분기든 함수 시그니처(`create_presigned_upload`/`head_object_exists`/
    # `resolve_public_url`)는 동일 — 호출처 변경 0.
    storage_provider: str = Field(
        default="r2",
        description="r2 | supabase",
    )

    # --- Cloudflare R2 ---
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "balancenote-meals"
    r2_public_base_url: str = ""
    # Story 5.2 — 회원 탈퇴 30일 grace 시점에 사용자 데이터 JSON dump를 보관하는 별도
    # bucket(R2). 미설정 시 dump skip + 운영 SOP 1줄(Cloudflare 콘솔 lifecycle policy로
    # 30일 후 자동 객체 삭제 — NFR-R5/C6 정합). dev/CI는 env 미설정 → graceful skip.
    r2_purge_dump_bucket: str = ""

    # --- Supabase Storage (Story 8.5) ---
    # `storage_provider=supabase` 분기에서 사용. dev/CI/test는 빈 값 허용 — fail-fast는
    # `_get_supabase_client()`이 runtime에 raise. Render prod env vars 주입은 Story 8.5
    # AC10 `.env.production.example` SOT 참조.
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_storage_bucket: str = "meals"

    # --- Expo ---
    expo_access_token: str = ""

    # --- 식약처 OpenAPI ---
    mfds_openapi_key: str = ""

    # --- 결제 ---
    toss_secret_key: str = ""
    # Story 6.3 — Toss webhook secret. ``TOSS_SECRET_KEY``와 *별 키*(Toss 콘솔에서
    # webhook용 별도 발급 — ``whsec_*``/``wsk_*`` prefix). 빈 문자열이면 webhook
    # endpoint가 503 ``payments.webhook.secret_key_missing`` 반환(runtime fail-fast).
    # dev/ci/test는 빈 값 허용(테스트는 fixture 시크릿 주입). prod/staging *부팅 검증*은
    # Story 8 hardening forward — 현 baseline은 runtime fail-fast로 우선 안전.
    toss_webhook_secret_key: str = ""

    # --- 환경 ---
    # ``dev``(default) | ``staging`` | ``prod`` | ``production`` | ``ci`` | ``test``.
    # Story 8.5: Render dashboard에서 ``ENVIRONMENT=production`` 표기 사용 — JWT 검증/
    # Sentry environment tag 모두 ``prod``와 동일 효력(``_validate_jwt_secrets_in_prod``
    # 분기 합집합). Sentry 측은 ``settings.environment`` 그대로 tag로 forward (sentry.py).
    environment: str = Field(
        default="dev",
        description="dev | staging | prod | production | ci | test",
    )

    # --- CORS (Story 1.2) ---
    # comma-separated. dev 디폴트는 Web 로컬(http://localhost:3000) + Expo Go(http://localhost:8081).
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8081"]
    )

    # --- Admin IP allowlist (Story 7.1, NFR-S8) ---
    # comma-separated CIDR(IPv4/IPv6 모두 지원). 빈 list → 화이트리스트 비활성(MVP
    # default — 외주 클라이언트별 옵션). 잘못된 CIDR 형식은 부팅 시 ValueError raise
    # (fail-fast — 잘못된 설정으로 prod 가동 차단).
    admin_ip_allowlist: list[str] = Field(default_factory=list)

    @field_validator("admin_ip_allowlist", mode="before")
    @classmethod
    def _split_admin_ip_allowlist(cls, v: str | list[str] | None) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            cidrs = [cidr.strip() for cidr in v.split(",") if cidr.strip()]
        else:
            cidrs = list(v)
        for cidr in cidrs:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError as exc:
                raise ValueError(f"invalid admin IP allowlist CIDR {cidr!r}: {exc}") from exc
        return cidrs

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: str | list[str] | None) -> list[str]:
        if v is None or v == "":
            return ["http://localhost:3000", "http://localhost:8081"]
        if isinstance(v, str):
            origins = [origin.strip() for origin in v.split(",") if origin.strip()]
        else:
            origins = list(v)
        # `allow_credentials=True`와 wildcard 조합은 브라우저가 거부 → runtime 회귀.
        # 또한 `null` origin은 sandboxed iframe 등에서 위장 가능 — 명시 거부.
        for origin in origins:
            if origin in {"*", "null"}:
                raise ValueError(f"CORS origin {origin!r} is forbidden with credentials")
            if not (origin.startswith("http://") or origin.startswith("https://")):
                raise ValueError(f"CORS origin must include http(s):// schema (got {origin!r})")
        return origins

    @model_validator(mode="after")
    def _validate_jwt_secrets_in_prod(self) -> Settings:
        # prod + production + staging 환경은 dev secret 차단 — staging은 prod-mirror 데이터
        # 노출 가능성이라 동일 강도 검증 적용. ``production`` 별칭은 Story 8.5(Render dashboard
        # 표기 정합 — `.env.production.example`이 `ENVIRONMENT=production` 사용) 흡수.
        # dev/ci/test는 디폴트 dev secret 허용 — 부팅 fail 회피.
        if self.environment not in {"prod", "production", "staging"}:
            return self
        if not self.jwt_user_secret or self.jwt_user_secret.startswith("dev-"):
            raise ValueError("jwt_user_secret must be set to a non-dev value in prod/staging")
        if not self.jwt_admin_secret or self.jwt_admin_secret.startswith("dev-"):
            raise ValueError("jwt_admin_secret must be set to a non-dev value in prod/staging")
        if self.jwt_user_secret == self.jwt_admin_secret:
            raise ValueError("jwt_user_secret and jwt_admin_secret must differ")
        return self


settings = Settings()
