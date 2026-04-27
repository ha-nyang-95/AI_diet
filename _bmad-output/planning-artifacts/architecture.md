---
stepsCompleted: ['step-01-init', 'step-02-context', 'step-03-starter', 'step-04-decisions', 'step-05-patterns', 'step-06-structure', 'step-07-validation', 'step-08-complete']
workflowComplete: true
status: 'complete'
completedAt: 2026-04-27
lastStep: 8
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/product-brief-BalanceNote-2026-04-26.md
  - _bmad-output/planning-artifacts/research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md
workflowType: 'architecture'
project_name: 'AI_diet'
product_name: 'BalanceNote'
user_name: 'hwan'
date: 2026-04-26
frame: '외주 영업용 포트폴리오 (학습용 X, 상용 SaaS X)'
---

# Architecture Decision Document — BalanceNote (저장소: AI_diet)

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements (49 FR / 9 capability 그룹):**

1. *Identity & Account* (FR1-5) — Google OAuth 단독 + JWT + 회원 탈퇴 → 비번 저장 표면 0
2. *Privacy/Compliance/Disclosure* (FR6-11) — PIPA 동의 게이트 + 디스클레이머 노출 + 데이터 내보내기 + 권한 거부 안내
3. *Meal Logging* (FR12-16) — 텍스트/사진 CRUD + 오프라인 큐잉(텍스트만)
4. *AI Nutrition Analysis* (FR17-27) — **6노드 LangGraph + Self-RAG 재검색 + 인용형 SSE 스트리밍 + 듀얼-LLM fallback** (이 그룹이 architectural 핵심)
5. *Engagement & Notifications* (FR28-31) — Expo 푸시 nudge + 온보딩 튜토리얼
6. *Insights & Reporting* (FR32-34) — Web 주간 리포트 4종 차트 + 인사이트 카드
7. *Administration & Audit Trust* (FR35-39) — admin role 분리 + 자동 audit log + 민감정보 마스킹
8. *Subscription & Payment* (FR40-42) — Toss/Stripe sandbox 정기결제 + webhook
9. *Operations & Handover* (FR43-48) — 캐시 + Rate limit + Sentry + Swagger + Docker 1-cmd

**Non-Functional Requirements (architecturally driving):**

- **Performance:** TTFT ≤ 1.5초 / 종단 p50 ≤ 4초 (사진 OCR 포함) / Self-RAG +2초 / pgvector p95 ≤ 200ms — **스트리밍 + 캐시 + RAG 인덱스 설계가 직접 결정**
- **Security:** JWT user/admin 분리 + Sentry beforeSend 마스킹 + Rate limit 3-tier(분당/시간당/LangGraph 별도)
- **Reliability:** LLM 듀얼 fallback / Pydantic retry 1회 / 노드 isolation / 양쪽 LLM 장애 시 안내
- **Scalability:** MVP baseline 100동시/1K DAU, 외주 인수 후 10x 마이그레이션 가이드(README) — *현재 단계 over-engineering 금지*
- **UX/Coaching Voice:** Noom-style 코칭 톤 + 행동 제안 마무리 강제 + 의학 어휘 회피 — `generate_feedback` 시스템 프롬프트 + 후처리 가드의 결합
- **Compliance:** 의료기기 미분류 / PIPA 2026.03.15 / 식약처 광고 표현 / 22종 알레르기 / 디스클레이머 — **5개가 cross-cutting**
- **Maintainability:** Pytest ≥ 70% / README 5섹션 / SOP 4종 / Docker Compose 1-cmd / 표준 추상 계층

**Scale & Complexity:**

- 도메인 복잡도: **high** (멀티 컴포넌트 풀스택 + LangGraph orchestration + 컴플라이언스 4축)
- 기술 도메인: **mobile-led full-stack** (RN 주축 + Next.js 보조 + FastAPI + AI 파이프라인)
- 컴포넌트 수: **7개** (RN, Next.js 사용자, Next.js 관리자, FastAPI, Postgres+pgvector, Redis, R2)
- IN 항목 수: 25 (UIUX 가시 영역 + 컴플라이언스 + 운영 산출물 모두 포함)

### Technical Constraints & Dependencies

**고정된 기술 스택 (PRD에 박힘 — Architecture는 이를 starter로 수용):**

- Frontend: React Native + Expo (managed workflow) / Next.js App Router + Recharts
- Backend: FastAPI + LangGraph + Pydantic
- Data: PostgreSQL + pgvector / Redis / Cloudflare R2
- LLM: OpenAI GPT-4o-mini (메인) + Anthropic Claude (보조) + OpenAI Vision (OCR)
- Hosting: Vercel(Web) + Railway(BE/DB/Redis) + Cloudflare R2(이미지)
- Ops: Docker Compose + Sentry + Pytest + Swagger

**외부 의존성:**

- 식약처 식품영양성분 DB OpenAPI (1차 시드) + 통합 자료집 ZIP (백업) + USDA FoodData Central (2차 백업)
- 보건복지부 KDRIs 2020 / 대한비만학회 9판 / 대한당뇨병학회 매크로 권고 (수동 chunking)
- OpenAI / Anthropic API
- Toss Payments 또는 Stripe (sandbox)
- Apple Developer($99/년) + Google Play($25 1회)

**도메인·법률 제약:**

- 의료기기 미분류 — 식약처 저위해도 일상 건강관리 명시 예시 정확 일치 필수 (진단성 발언 전면 차단)
- PIPA 2026.03.15 자동화 의사결정 동의 의무 — 미동의 시 분석 차단 게이트
- 식약처 식품 표시 22종 알레르기 도메인 무결성 — fit_score 0점 즉시 단락
- 식약처 광고/표시 금지 표현 가드레일 — 후처리 정규식 + 안전 워딩 치환

**비기술 제약:**

- 1인 8주 일정 → MSA / Kafka / 자체 LLM Fine-tuning / 풀 논문 RAG anti-pattern
- 외주 인수인계 가능성 ≥ 사용자 활성화 KPI — *코드 외 운영 산출물도 architectural artifact*

### Cross-Cutting Concerns

| # | Concern | 영향 컴포넌트 | Architectural 결정 필요 영역 |
|---|---------|------------|---------------------------|
| 1 | **컴플라이언스 가드 4종** (PIPA 동의/광고 표현/알레르기/디스클레이머) | RN + Next.js + FastAPI + DB | 미들웨어 vs decorator vs 후처리 — 위치 결정 |
| 2 | **인증/권한** (user/admin JWT 분리 + audit log) | RN + Next.js + FastAPI + Redis | 토큰 secret 분리 + audit AOP 위치 |
| 3 | **관측성** (Sentry + 구조화 로깅 + 비용 알림 + 민감정보 마스킹) | 전체 | beforeSend hook + 일별 비용 cron 위치 |
| 4 | **회복탄력성** (LLM fallback + SSE polling + Pydantic retry + DB 503) | FastAPI + RN + LangGraph | 어댑터/회로차단기 패턴 |
| 5 | **캐시/Rate limit** (LLM 응답 해시 + 음식 검색 + 3-tier 슬라이딩 윈도우) | FastAPI + Redis | 캐시 키 표준 + 무효화 정책 |
| 6 | **데이터 권리** (PIPA 내보내기 + 회원 탈퇴 즉시 파기) | RN + Next.js + FastAPI + DB | cascade 정책 + 백업 보존 의무 |
| 7 | **한국 도메인 표준** (식약처 키 jsonb + KDRIs enum + 22종) | DB schema + LangGraph + FastAPI | enum/lookup vs DB seed 분리 |
| 8 | **종단 SSE 스트리밍** (FastAPI → RN react-native-sse + Next.js) | RN + Next.js + FastAPI | polling fallback 사전 결정 |

## Starter Template Evaluation

### Primary Technology Domain

**Mobile-led full-stack** — RN 모바일(주축) + Next.js 웹(보조) + FastAPI 백엔드(LangGraph 6노드 호스트). PRD가 스택을 이미 고정했으므로 본 단계는 *bootstrap 패턴 결정*에 집중.

### Repo 구조 결정

**선택:** **단일 repo + multi-folder (워크스페이스 없음)** — `/mobile`, `/web`, `/api`, `/docker`, `/scripts`, `/.github/workflows`

**근거:**

- 외주 인수인계 가치(B3 KPI) — 클라이언트가 자기 백엔드/프론트로 부분 교체 시 워크스페이스 인수 강제 회피
- Docker Compose 1-cmd 부팅(FR47, NFR-M6)과 자연 정합 — 컴포넌트 경계가 폴더 = 컨테이너
- 1인 8주에 Turborepo/Nx ROI 의문 (TS 빌드 캐싱 가치 < 학습/유지비)
- Python(api) ↔ TS(mobile/web) 워크스페이스 통합 불가 — 반쪽짜리 monorepo는 안티패턴

**TS 타입 공유 정책:** `/api`의 Swagger/OpenAPI를 단일 출처로, `openapi-typescript` 또는 `openapi-typescript-codegen`으로 `/web`·`/mobile`에 클라이언트 생성. `pnpm gen:api` 스크립트 1개로 양쪽 sync.

### 검토한 Starter 옵션 (요약)

| 옵션 | 채택 여부 | 사유 |
|------|---------|-----|
| `create-next-app@latest` (16.2.4) | ✅ | 공식, App Router/Turbopack/Tailwind/TS 디폴트, AGENTS.md 자동 생성 |
| `create-expo-app@latest` (SDK 54) | ✅ | 공식, SDK 54 + TS 기본 포함, EAS 호환 |
| 수동 minimal API scaffold (uv + FastAPI + LangGraph 1.1.9) | ✅ | 패턴 자유 + 1인 8주에 학습 곡선 0 + 외주 인수 시 클라이언트 추적 용이 |
| `wassim249/fastapi-langgraph-agent-production-ready-template` | ❌ 참고만 | mem0 + 단일 agent 패턴 강제 — 본 산출물(2종 RAG + 듀얼-LLM) 정합 안 됨 |
| `tiangolo/full-stack-fastapi-template` | ❌ | Vue/SQLModel 전제 — RN+Next.js와 충돌 |
| Turborepo monorepo / pnpm workspace | ❌ | 외주 클라이언트가 워크스페이스 인수 강제 — handover 마찰 |

### Component-별 Starter

#### `/mobile` — React Native (Expo SDK 54)

**Initialization Command:**

```bash
npx create-expo-app@latest mobile --template default
```

**Starter가 제공하는 결정:**

- TypeScript 디폴트 포함
- Expo Router (file-based routing) — 우리 흐름(온보딩 → 식단 입력 → 채팅 → 일별 기록 → 설정)에 적합
- EAS Build 호환 (W7 배포 시 Apple TestFlight + Google Play Internal Testing 직행)
- Expo Notifications/Camera/Image Picker 통합 — IN #3, #9, M5 권한 흐름 즉시 가능

**추가 의존성 (수동 설치):**

- `react-native-sse` — FR26 SSE 스트리밍 (R2 risk: W4 day1 spike 후 polling fallback 결정)
- `@react-native-async-storage/async-storage` — FR16 오프라인 큐잉
- `react-native-reanimated`, `react-native-gesture-handler` — Expo 표준 동반

#### `/web` — Next.js 16.2.4

**Initialization Command:**

```bash
pnpm create next-app@latest web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --turbopack
```

**Starter가 제공하는 결정:**

- App Router 디폴트 (Server Components + Route Handlers + Parallel Routes 활용 가능)
- Turbopack 디폴트 빌드러너
- Tailwind CSS v3 + ESLint + TypeScript
- `AGENTS.md` 자동 생성 — 외주 인수 시 AI 에이전트 컨텍스트 카드로 활용
- Import alias `@/*`

**추가 의존성:**

- `recharts` — FR32 4종 차트 (NFR-P8: 7일 데이터 ≤ 1.5초)
- `@tanstack/react-query` — 서버 상태 관리 (admin 사용자 검색·audit log 조회)
- 인증: Google OAuth Next.js 측은 백엔드 JWT를 httpOnly 쿠키로 교환받는 패턴 — `next-auth` 의존 회피(직접 구현이 더 명료)

#### `/api` — FastAPI + LangGraph (수동 minimal scaffold)

**Bootstrap 명령:**

```bash
mkdir api && cd api
uv init --python 3.13
uv add fastapi[standard] langgraph langchain langchain-openai langchain-anthropic
uv add sqlalchemy[asyncio] alembic asyncpg pgvector pydantic-settings
uv add redis httpx tenacity sentry-sdk python-jose[cryptography] passlib
uv add langsmith
uv add --dev pytest pytest-asyncio ruff mypy
```

**제공 패턴 (수동 결정):**

- **언어/런타임:** Python 3.13 (LangGraph 1.1.9 권장 + Python 3.14 옵션)
- **패키지 매니저:** `uv` (pip/poetry 대비 10x 속도 + lock 파일 표준)
- **ORM:** SQLAlchemy 2.x async + Alembic — pgvector 직접 통합(SQLModel은 jsonb 식약처 키 표준 다루기 더 번거로움)
- **검증:** Pydantic v2 (LangGraph Structured Output 표준)
- **린팅:** ruff (포맷+린트 단일 도구)
- **테스트:** pytest + pytest-asyncio (NFR-M1: 핵심 경로 ≥ 70%)
- **에러 트래킹:** sentry-sdk + beforeSend hook으로 민감정보 마스킹
- **HTTP 클라이언트:** httpx (식약처 OpenAPI · OpenAI · Anthropic · Toss/Stripe webhook)
- **Retry/회로차단기:** tenacity (NFR-R2 LLM fallback)
- **LLM 옵저버빌리티:** `langsmith` SDK + `LANGCHAIN_TRACING_V2` env (LangGraph/LangChain native 자동 트레이싱 — 노드·LLM·RAG 호출 캡처, NFR-O1)

**Chunking 모듈 — 외주 인수인계 인터페이스로 설계 (Architecture 추가 결정 1):**

가이드라인 RAG의 *수동 chunking* (PRD W2 결정)을 그대로 유지하되, chunking 코드를 *재사용 가능 모듈*로 분리:

- `/api/app/rag/chunking/` — PDF/HTML/텍스트 입력 → 메타데이터 부착 chunks 출력 (인터페이스 1개)
- `/scripts/seed_guidelines.py` — MVP에서 위 모듈을 1회 수동 호출 (KDRIs/대비/대당 PDF)
- 외주 인수 시 같은 모듈을 *클라이언트 PDF 자동 파이프라인*으로 재사용 가능 → 영업 카드 (차별화 #4 + Journey 7 식품기업 자사 SKU 통합과 정합). 자동화 인프라 자체는 MVP OUT 유지.

#### `/docker` — Docker Compose 1-cmd 부팅

**Bootstrap:** 수동 작성 (`docker-compose.yml` + `Dockerfile.api`)

**서비스 구성:**

- `postgres` (with pgvector via `pgvector/pgvector:pg16` 이미지)
- `redis` (alpine)
- `api` (FastAPI, dev volume mount)
- `seed` (one-shot 컨테이너 — 식약처 OpenAPI 1.5K-3K건 + 가이드라인 50-100 chunks)

**healthcheck + dependency wait** 적용 — `api`는 `postgres`/`redis` healthy 후 시작.

#### `/.github/workflows` — CI 게이트 (Architecture 추가 결정 2)

PRD의 Vercel/Railway *push-to-deploy* 자동 배포는 그대로. 추가로 **PR 시 테스트 게이트** 1개 워크플로우:

- `ci.yml` — PR 시 ① ruff lint+format check ② pytest ③ 커버리지 ≥ 70% 미달 시 fail
- mobile/web은 lint + typecheck만 (E2E는 W8 데모 전 수동)
- NFR-M1을 *수치로만 적지 않고* CI에서 강제 → B3 외주 인수인계 신뢰 카드 +1
- 1인 8주 추가 비용 ≈ 0.5일

#### LangSmith 외부 옵저버빌리티 (Architecture 추가 결정 3)

PRD FR49 + NFR-O1~O5 대응. *서비스에 임베드하지 않고* 외부 SaaS(LangSmith) 활용 — 운영 LLM 트레이싱·평가·회귀를 영업 카드로 입증.

- **SDK·통합 방식:** `langsmith` Python 패키지 + `LANGCHAIN_TRACING_V2=true` env. LangGraph 1.1.9는 LangSmith와 native 통합 — 별도 wrapping 코드 거의 0. 추가 캡처가 필요한 도메인 함수(`fit_score`, `food normalize`)는 `@traceable` 데코레이터 1줄.
- **마스킹 (NFR-O2):** `app/core/observability.py:mask_run` hook으로 run inputs/outputs에서 민감정보(체중·신장·알레르기·식단 raw_text) 마스킹 → LangSmith client `client.update_run` 또는 `langsmith.Client(hide_inputs=..., hide_outputs=...)` 콜백 부착. NFR-S5 마스킹 룰을 1지점에서 재사용 (Sentry beforeSend hook과 동일 룰셋 import).
- **Env·Secrets:** `LANGSMITH_API_KEY`(secret), `LANGSMITH_PROJECT=balancenote-prod|dev`, `LANGCHAIN_TRACING_V2=true|false` (로컬 개발은 false 기본, 스테이징/프로덕션 true). `.env.example` + Railway secrets 표준.
- **평가 데이터셋 (NFR-O3):** `scripts/upload_eval_dataset.py` — Story 3.4의 한식 100건 테스트셋(짜장면/자장면 변형)을 LangSmith Dataset으로 1회 업로드. PR CI에 `evaluate` 회귀 스텝 옵션(권장, 강제 X) — 정확도 ≥ 90% 미달 시 PR 코멘트 경고.
- **위치:** `app/core/observability.py` (마스킹 hook + 클라이언트 셋업) + `scripts/upload_eval_dataset.py` (1회용). `app/adapters/`에는 두지 않음 — LangSmith는 비즈니스 호출이 아닌 cross-cutting tracing 인프라.
- **OUT (MVP):** Self-hosted LangSmith, 사용자 노출 대시보드, 자동 머지 차단(권장 경고만).
- **1인 8주 추가 비용:** ≈ 0.5–1일 (W3 Integration 슬롯 흡수). LangSmith Free tier 5K trace/month로 MVP·데모 충분.

### 예상 폴더 구조 (Top-level)

```
AI_diet/
├── mobile/                    # Expo SDK 54
├── web/                       # Next.js 16
├── api/                       # FastAPI + LangGraph 1.1.9
│   ├── app/
│   │   ├── core/              # config, security, middleware, PIPA 동의 게이트, observability (LangSmith 마스킹 hook)
│   │   ├── domain/            # 식약처/KDRIs/22종 enum, fit_score 알고리즘
│   │   ├── graph/             # LangGraph 6노드 + Self-RAG 분기
│   │   ├── rag/
│   │   │   ├── chunking/      # 재사용 모듈 (Architecture 결정 1)
│   │   │   ├── food/          # 음식 RAG (식약처 1.5K-3K건)
│   │   │   └── guidelines/    # 가이드라인 RAG (KDRIs/대비/대당, 50-100 chunks)
│   │   ├── api/               # FastAPI routers
│   │   ├── db/                # SQLAlchemy + Alembic migrations
│   │   └── adapters/          # OpenAI/Anthropic/Vision/Toss/식약처 OpenAPI
│   └── tests/
├── docker/                    # docker-compose.yml + Dockerfiles
├── scripts/                   # seed_food_db.py, seed_guidelines.py, gen_openapi_clients.sh
├── docs/                      # SOP 4종 + 영업 답변 5종 closing FAQ
├── .github/workflows/         # ci.yml (Architecture 결정 2)
├── .env.example
└── README.md
```

**Note:** 프로젝트 초기화는 첫 구현 스토리(Story 1.1)로. 8주 W1 day1 spike에 Docker 1-cmd 부팅 검증(R5 mitigation) 포함.

## Core Architectural Decisions

### Decision Priority

- **Critical (구현 차단):** Data 스키마 / LangGraph 영속성 / Auth 분리 / SSE 프로토콜 / 환경 분리
- **Important (아키텍처 형성):** 캐싱 키 표준 / Audit 위치 / 에러 표준 / 모바일 state / 관측성
- **Deferred (Post-MVP):** 컬럼 단위 암호화 / 멀티-AZ / 풀 다국어 / EMR 어댑터 / 결제 정식 PG / WCAG AA 인증

### Data Architecture

| 결정 | 선택 | 이유 / 영향 |
|------|------|-----------|
| **DB 엔진** | PostgreSQL 17.x + `pgvector/pgvector:pg17` (pgvector 0.8.2) | Railway 표준. PG 18은 Railway 정식 지원 후 마이그레이션. pgvector 0.8.2 HNSW 병렬 빌드 안정 |
| **Schema** | `public` 단일 schema | 1인 8주에 멀티-스키마 ROI 0. 외주 인수 단순 |
| **ORM** | SQLAlchemy 2.0.49 async + asyncpg | LangGraph async 노드 정합. SQLModel은 식약처 jsonb 키 정밀 다루기 번거로움 |
| **Migration** | Alembic — autogenerate + 수동 review 강제 | 1인 8주 충분. PR 시 review 게이트로 destructive 차단 |
| **`food_nutrition.nutrition` jsonb 표준 키** | 식약처 OpenAPI 응답 키 그대로 (`energy_kcal`, `carbohydrate_g`, `protein_g`, `fat_g`, `sugar_g`, `sodium_mg`, ...) | 차별화 #3 + Journey 7. 외주 인수 시 변환 코스트 0. 키 추가 jsonb 무중단 |
| **`users.allergies`** | `text[]` + DB CHECK 제약(22종 enum) | 식약처 표시기준 22종 무결성 + 다중 선택 |
| **`health_goal`** | Postgres ENUM (`weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management`) | 4종 고정. KDRIs AMDR 매크로 룰 lookup table 1:1 매핑 |
| **음식명 정규화 사전** | `food_aliases` 테이블 (alias text, canonical_name text) — DB 시드 + runtime 갱신 | 외주 클라이언트가 자기 메뉴 별칭 추가 시 코드 배포 불필요 |
| **2종 RAG 인덱스** | `food_nutrition.embedding vector(1536)` HNSW + `knowledge_chunks.embedding vector(1536)` HNSW | 검색 패턴 다름(top-K vs filtered top-K by `applicable_health_goals`). 별 인덱스가 튜닝 자유 |
| **`knowledge_chunks` 메타데이터** | `source`, `authority_grade`(식약처/복지부/대비/대당/질병관리청), `topic`, `applicable_health_goals text[]`, `published_year` | FR23-FR24 인용형 답변의 출처 메타데이터를 시스템 프롬프트에 주입 |
| **LangGraph state 영속성** | `langgraph-checkpoint-postgres` AsyncPostgresSaver — 같은 PG의 별 schema `lg_checkpoints` | J2 Self-RAG 재질문이 사용자 응답 대기 가능. 인메모리는 재시작·세션 분리에 취약 |
| **캐시 키 네임스페이스** | `cache:llm:{sha256(meal_text+profile_hash)}` (24h) / `cache:food:{normalized_name}` (7d) / `cache:user:{user_id}:profile` (1h) / `cache:rl:{user_id}:{tier}` | 무효화: 프로필 수정 시 `cache:user:*` 패턴 + LLM은 hash 변경으로 자동 |
| **Soft delete** | 사용자 데이터: 회원 탈퇴 시 `users.deleted_at` 마킹 → 30일 grace → 물리 파기 cron | FR5 + C6 데이터 보존 정책 |

**핵심 ER 골격:** `users` → `consents` / `meals` → `meal_analyses` / `food_nutrition` / `knowledge_chunks` / `food_aliases` / `subscriptions` → `payment_logs` / `audit_logs` / `notifications`. (스키마 상세는 step-06)

### Authentication & Security

| 결정 | 선택 | 이유 / 영향 |
|------|------|-----------|
| **OAuth flow** | Authorization Code (백엔드 token 교환). 모바일 `expo-auth-session` / Web 백엔드 redirect | Implicit flow 회피. 백엔드가 Google id_token 검증 → 자체 JWT |
| **JWT 분리** | 별 secret + 별 issuer claim. `user`: HS256 access 30일/refresh 90일. `admin`: HS256 access 8시간/refresh 없음 + IP 화이트리스트 옵션 | NFR-S2, NFR-S7. 혼용 차단 |
| **Token 저장** | 모바일 `expo-secure-store` (Keychain/Keystore). Web httpOnly + Secure + SameSite=Strict 쿠키 | NFR-S2 |
| **Audit log 위치** | FastAPI Dependency `Depends(audit_admin_action)` admin 라우터에 일괄. payload는 path/method/actor/target/IP/request_id | 미들웨어보다 좁고 의도 명확. 디코레이터보다 FastAPI 표준 정합 |
| **민감정보 마스킹** | Sentry `before_send` hook + structlog processor — 정규식으로 이메일/체중/식단 raw_text/알레르기 항목 마스킹 | NFR-S5. 단일 함수로 양 출력 스트림 동시 적용 |
| **Secret 관리** | Railway secrets (prod/staging) + `.env.local` (gitignored, dev). `.env.example` 커밋. 키 회전 SOP README 1페이지 | NFR-S9, NFR-S10 |
| **PIPA 동의 게이트** | FastAPI Dependency `Depends(require_automated_decision_consent)` → `evaluate_fit`/`generate_feedback` 진입 차단 → 안내 응답 | FR7. 게이트 위치를 라우터 dependency로 박아 우회 불가 |
| **Rate limit** | slowapi + Redis backend — 3-tier 키 (분당 60 / 시간당 1000 / LangGraph 분당 10). 429 + Retry-After | NFR-S4. Redis 슬라이딩 윈도우 |

### API & Communication Patterns

| 결정 | 선택 | 이유 / 영향 |
|------|------|-----------|
| **API style** | REST + JSON (GraphQL 미채택) | 1인 8주에 GraphQL ROI 0. RESTful + Swagger가 외주 인수 표준 |
| **API 버전** | URL path `/v1/*` | forward compat. 외주 인수 후 v2 점진 전환 |
| **에러 표준** | RFC 7807 Problem Details — `application/problem+json` + `type/title/status/detail/instance` + 우리 확장 `code` | 외주 인수 시 클라이언트 에러 핸들링 표준화 |
| **SSE 프로토콜** | `sse-starlette` `EventSourceResponse` — `event: token` (델타) / `event: citation` (인용) / `event: done` / `event: error` | FR26, NFR-P3. 명시적 이벤트 타입 → 모바일 파싱 단순 |
| **SSE polling fallback** | W4 day1 spike 결과 — RN SSE 끊김 ≥ 임계 시 1.5초 polling 자동 강등. 헤더 `X-Stream-Mode: sse|polling` 명시 | R2 mitigation |
| **OpenAPI 클라이언트 생성** | `openapi-typescript` (web/mobile 공용) — `pnpm gen:api` 스크립트 build 전 자동 sync | step-03 단일 출처 정책 정합 |
| **Idempotency** | 결제 webhook + 식단 입력에 `Idempotency-Key` 헤더 권장 (Stripe/Toss 표준) | FR42 재시도 안전성 |
| **CORS** | Web 도메인만 명시 화이트리스트. 모바일은 CORS 비대상 (네이티브) | NFR-S1 정합 |

### Frontend Architecture

| 결정 | 선택 | 이유 / 영향 |
|------|------|-----------|
| **모바일 server state** | TanStack Query `@tanstack/react-query` + Expo Router file-based | 캐시·재시도·무효화·dedup 표준. 1인 검증 패턴 |
| **모바일 client state** | `useState`/`useReducer` + 필요 시 `zustand` (소규모) | Redux/Jotai/Recoil 도입 회피. 1인 8주 anti-pattern |
| **모바일 form** | `react-hook-form` + `zod` 검증 | 건강 프로필·식단 입력 polish |
| **Web RSC vs Client** | App Router 디폴트 RSC. 차트/관리자 검색/admin form은 Client Components (`"use client"`) | NFR-P8. 정적 페이지(약관/처리방침/디스클레이머)는 RSC SSR 1.5초 |
| **Web UI 라이브러리** | shadcn/ui (선택적 컴포넌트만) + Tailwind | 풀 디자인 시스템 도입 회피(브리프 OUT 정합). 관리자/리포트 패널 표준화 |
| **Web 차트** | recharts (PRD 박힘) — 4종 차트 (매크로 비율 / 칼로리 vs TDEE / 단백질 g/kg / 알레르기 노출) | FR32, NFR-P8 |
| **모바일 SSE** | `react-native-sse` 1차 / `EventSource` polyfill 우회 / polling fallback | R2 |
| **i18n** | 한국어 1차. 디스클레이머·약관만 영문 풀텍스트 — Web에서는 별 라우트 `/en/legal/*`. UI 영문화 OUT | NFR-L2 |

### Infrastructure & Deployment

| 결정 | 선택 | 이유 / 영향 |
|------|------|-----------|
| **호스팅 토폴로지** | Vercel(Web) + Railway(API + Postgres + Redis) + Cloudflare R2(이미지) + Expo EAS(Mobile build) | PRD 고정. 1인 8주 정합 |
| **환경 분리** | dev (Docker Compose 로컬) / staging (Railway preview env, GitHub PR push 자동) / prod (Railway prod, main 브랜치 push 자동) | NFR-M5, NFR-M6 |
| **배포 게이트** | GitHub Actions PR 워크플로우 — ① ruff lint+format ② mypy(api) ③ pytest + coverage ≥ 70% ④ tsc --noEmit (web/mobile) ⑤ openapi schema diff. main 머지 시 Vercel/Railway 자동 배포 | step-03 결정 2 정합 |
| **DB 마이그레이션 게이트** | Alembic `--sql` dry-run을 PR 코멘트 표시. main 머지 시 Railway 배포 hook에서 `alembic upgrade head` 자동 실행 | 무중단 보장 |
| **로깅** | structlog JSON → stdout → Railway 로그 집계. 로컬은 console renderer | NFR-S5 마스킹 processor 동일 적용 |
| **에러/트레이싱** | Sentry SDK (Python + RN + Next.js). LangGraph 노드 transaction tracing — 노드 단위 span | NFR-R6, T8 |
| **일별 비용 알림** | GitHub Actions cron (매일 09:00 KST) — OpenAI/Anthropic Usage API + Railway billing API → Slack/Discord webhook + Sentry custom event | R6, NFR-Sc4. 1인이 cost runaway 즉시 인지 |
| **백업** | Railway Postgres 일별 7일 보존 (표준). 회원 탈퇴 grace 30일 데이터는 별 dump bucket(R2) 보관 후 파기 | NFR-R5, FR5 |
| **헬스체크** | `/healthz` (liveness, DB ping) + `/readyz` (readiness, DB+Redis+pgvector index OK) | Railway healthcheck 표준 |

### Decision Impact Analysis

**Implementation Sequence (W1 spike 우선순위):**

1. PostgreSQL + pgvector 컨테이너 + Alembic 초기 마이그레이션 (W1 day1 R5/R7 spike)
2. SQLAlchemy 2.0 async + asyncpg 연결 + 첫 모델 `users` (W1 day2)
3. Google OAuth + JWT 분리 + Sentry beforeSend hook (W1 day3-5)
4. `langgraph-checkpoint-postgres` AsyncPostgresSaver 셋업 (W2 day1)
5. 음식 RAG 시드(식약처 OpenAPI) + `food_aliases` (W1-W2 spike R4/R7)
6. SSE `EventSourceResponse` + RN `react-native-sse` 통신 검증 (W4 day1 R2 spike)
7. slowapi + Redis 3-tier (W6)
8. GitHub Actions CI + 일별 비용 cron (W7)

**Cross-Component Dependencies:**

- `langgraph-checkpoint-postgres` schema는 Alembic 관리 외 (lib `.setup()` 호출). 두 schema 공존
- `audit_admin_action` dependency는 `admin_user_jwt_required` dependency에 자동 연쇄 — admin 토큰 없으면 audit 미발동
- PIPA 동의 게이트는 `evaluate_fit`/`generate_feedback` 라우터 dependency에 들어가므로 LangGraph 호출 *전* 차단 — LLM 비용 0 보호
- OpenAPI 클라이언트 자동 생성은 백엔드 schema 변경 시 모바일/웹 빌드 둘 다 영향 → CI에서 `openapi schema diff` 게이트로 우발적 breaking change 차단

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

본 프로젝트에서 두 명의 AI 에이전트(또는 외주 인수 후 클라이언트 개발자)가 다르게 결정해서 충돌하기 쉬운 영역 5개:

1. **Naming** — DB(snake_case) ↔ TS(camelCase) 경계 / API URL plural 여부 / 컴포넌트 폴더 구조
2. **Structure** — 테스트 위치 / feature vs type 조직 / 라우터 분할
3. **Format** — JSON wire format(snake vs camel) / 날짜 / 페이지네이션 / 에러
4. **Communication** — SSE 이벤트 타입 / 로깅 레벨·필드 / Idempotency-Key
5. **Process** — 에러 글로벌 핸들링 / 로딩 상태 / 리트라이 / 인증 401 흐름

### Naming Patterns

#### Database (Postgres / SQLAlchemy / Alembic)

| 항목 | 규칙 | 예시 |
|------|-----|------|
| 테이블 | snake_case + 복수 | `users`, `meals`, `meal_analyses`, `food_nutrition`, `knowledge_chunks`, `food_aliases`, `audit_logs`, `consents`, `subscriptions`, `payment_logs`, `notifications` |
| 컬럼 | snake_case | `user_id`, `created_at`, `deleted_at`, `nutrition` (jsonb), `embedding` (vector) |
| FK | `<referenced_table_singular>_id` | `user_id`, `meal_id` |
| 인덱스 | `idx_<table>_<columns>` | `idx_meals_user_id_ate_at`, `idx_food_nutrition_embedding` |
| Enum | `<table>_<col>_enum` | `users_health_goal_enum` |

이유: Postgres 표준 + 식약처 jsonb 키와 자연 정합.

#### API URL

| 항목 | 규칙 | 예시 |
|------|-----|------|
| 엔드포인트 | REST kebab-plural noun + `/v1/` | `GET /v1/meals`, `POST /v1/meals`, `GET /v1/users/me`, `GET /v1/admin/audit-logs`, `POST /v1/analysis/stream` |
| Path param | `{id}` (FastAPI 표준) | `/v1/meals/{meal_id}` |
| Query | snake_case | `?cursor=abc&limit=20&from_date=2026-04-01` |

#### JSON Wire Format

| 항목 | 규칙 | 이유 |
|------|-----|------|
| 키 | **snake_case 양방향** (요청·응답 모두) | Python/Pydantic 자연 정합 + 식약처 jsonb 키 통일 + OpenAPI 생성 SDK가 자동 매핑 |

**Anti-pattern:** Pydantic `alias_generator=to_camel` 도입 → 양방향 추적 비용 증가, 1인 8주 anti-pattern.

#### Code 명명 (언어별 idiom 존중)

| 언어 | 함수/변수 | 클래스/타입 | 상수 |
|------|---------|-----------|------|
| Python (api) | snake_case | PascalCase | UPPER_SNAKE |
| TypeScript (web/mobile) | camelCase | PascalCase | UPPER_SNAKE |

#### 파일명

| 종류 | 규칙 | 예시 |
|------|-----|------|
| Python | snake_case.py | `meal_service.py` |
| React 컴포넌트 | PascalCase.tsx | `MealCard.tsx` |
| 그 외 TS | kebab-case.ts | `api-client.ts` |
| Next.js 라우트 폴더 | kebab-case | `/dashboard/weekly` |
| Expo Router 파일 | kebab-case.tsx + 표준 | `_layout.tsx`, `index.tsx`, `meal-detail.tsx` |

### Structure Patterns

#### Feature-based 조직 (web/mobile)

- **선택:** `features/<domain>/` 단위로 컴포넌트·hooks·API 클라이언트 collocated
- **예시:** `features/meals/MealCard.tsx`, `features/meals/useMealMutation.ts`, `features/meals/api.ts`
- **이유:** 외주 인수 시 도메인 경계로 분할·교체 용이. type-based(`components/`, `hooks/`) 흩어짐 회피
- **공통 유틸:** `lib/` (예: `lib/auth.ts`, `lib/format.ts`)

#### API 라우터 분할 (FastAPI)

- **선택:** `app/api/v1/<domain>.py` 도메인별 1파일 1 APIRouter
- **파일 목록:** `auth.py`, `users.py`, `meals.py`, `analysis.py`, `reports.py`, `admin.py`, `payments.py`, `legal.py`, `notifications.py`
- **공통 dependency:** `app/api/deps.py` (`current_user`, `require_admin`, `require_consent`)

#### 테스트 위치

| 컴포넌트 | 위치 | 패턴 | 이유 |
|---------|-----|-----|-----|
| 백엔드 (api) | `tests/` 미러 구조 | `tests/test_meals.py`, `tests/graph/test_evaluate_fit.py` | pytest 표준 |
| 프론트엔드 (web/mobile) | co-located | `features/meals/MealCard.test.tsx` | Jest/Vitest 표준 |

### Format Patterns

#### API 응답

- **wrapper 없음.** 성공은 직접 응답 객체. 에러는 RFC 7807 Problem Details
- **성공 예시:** `{"id": "m_123", "ate_at": "2026-04-27T12:30:00Z", "fit_score": 62, ...}`
- **에러 예시:**
  ```json
  {
    "type": "https://balancenote.app/errors/consent-required",
    "title": "Automated decision consent required",
    "status": 403,
    "code": "consent.automated_decision.missing",
    "detail": "Please grant automated decision consent before requesting AI analysis.",
    "instance": "/v1/analysis/stream"
  }
  ```
- **이유:** OpenAPI 표준 + 외주 인수 시 클라이언트 SDK 단순화

#### 데이터 형식

| 항목 | 규칙 |
|------|-----|
| 날짜 | ISO 8601 UTC + Z (`2026-04-27T14:23:11Z`). 한국 시간 변환은 클라이언트 책임 |
| 통화 | KRW integer (원 단위, 소수 미사용) |
| Boolean | `true`/`false` (정수 0/1 금지) |
| Null | Pydantic `Optional` 필드는 `null`. 응답에서 키 누락 금지 (스키마 안정성) |
| 페이지네이션 | cursor-based (`?cursor=...&limit=20`). 응답에 `next_cursor`. offset 미사용 |

### Communication Patterns

#### SSE 이벤트 (FR26 + step-04 결정)

| 이벤트 | payload | 의미 |
|-------|---------|-----|
| `token` | `{"delta": "..."}` | LLM 스트림 델타 |
| `citation` | `{"source": "...", "authority_grade": "..."}` | 인용 출처 메타 |
| `done` | `{"final_fit_score": 62, ...}` | 정상 완료 |
| `error` | RFC 7807 Problem Details | 에러 |

**종료 규칙:** `done` 또는 `error` 둘 중 하나는 반드시 1회. 클라이언트는 둘 중 하나 수신 시 연결 종료.

#### 로깅

- **레벨:** `DEBUG`(로컬만) / `INFO`(요청·응답 메타) / `WARNING`(폴백 발동) / `ERROR`(실패) / `CRITICAL`(서비스 다운 위험)
- **필수 필드:** `timestamp`, `level`, `request_id`, `user_id`(마스킹), `event`, `module`, `version`
- **레퍼런스:** structlog JSON processor로 일괄 적용. Sentry breadcrumb도 동일

#### 헤더 컨벤션

- **표준 RFC 헤더 우선:** `Idempotency-Key`, `Authorization`, `Content-Type`, `Retry-After`
- **우리 확장만 X- 사용:** `X-Stream-Mode` (sse|polling), `X-Request-Id` (서버 발급, 응답에 echo)
- **Anti-pattern:** `X-` prefix 남용 (RFC 6648 deprecated)

### Process Patterns

#### 에러 핸들링

- **백엔드 글로벌 핸들러:** FastAPI `@app.exception_handler(Exception)` → RFC 7807 변환 + Sentry capture
- **도메인 예외 계층:** `BalanceNoteError` → `ConsentMissingError`, `AllergenViolationError`, `LLMUnavailableError`, `RetrievalLowConfidenceError` 등
- **프론트:** TanStack Query `onError` → 토스트(사용자 메시지) + Sentry `captureException`
- **LangGraph 노드:** Pydantic 검증 → retry 1회 → error edge fallback

#### 로딩 상태

- TanStack Query `isPending` / `isFetching` 명확 구분 사용
- UI 룰: 즉시 스피너 → 500ms 초과 시 스켈레톤 → 콘텐츠. 표준 빈/에러 화면 (PRD AC)
- **Anti-pattern:** 로딩 boolean 자체 관리 (TanStack Query 표준 활용)

#### 리트라이 정책

| 컴포넌트 | 정책 |
|---------|-----|
| LLM 호출 | tenacity exponential backoff 3회 (1s, 2s, 4s) + 최종 실패 시 듀얼-LLM fallback |
| DB | asyncpg deadlock retry 1회 |
| SSE | 클라이언트가 `event: error` 수신 → 1.5초 후 polling 강등 (`/v1/analysis/{id}` GET) |
| Webhook | Stripe/Toss는 자체 retry — 우리는 `Idempotency-Key`로 중복 처리 멱등화 |

#### 인증 401 흐름

- **선택:** 클라이언트 인터셉터 — 401 수신 시 refresh 토큰으로 1회 재발급 시도 → 실패 시 로컬 토큰 클리어 + 로그인 화면 라우팅
- **Admin:** refresh 미지원이므로 401 즉시 admin 로그인 화면

### Enforcement Guidelines

#### 모든 AI 에이전트가 따라야 할 룰

- 새 테이블·컬럼은 위 Naming 컨벤션 위반 시 PR review에서 차단
- API 응답에 wrapper 추가 금지 (RFC 7807 에러 외 직접 응답)
- 새 라우터는 `app/api/v1/<domain>.py` 1파일 1 router
- 새 React 컴포넌트는 `features/<domain>/`에 PascalCase로
- 모든 LangGraph 노드 출력은 Pydantic 모델로 검증
- 모든 admin 라우터는 `Depends(audit_admin_action)` 명시

#### 자동 강제

- **ruff** (Python lint+format) — 룰셋 `pyproject.toml`에 commit
- **eslint + prettier** (TS) — 룰셋 `.eslintrc.json` commit
- **pre-commit hooks** — ruff + eslint + tsc --noEmit
- **CI 게이트** — step-04 결정한 GitHub Actions 워크플로우
- **`AGENTS.md`** (Next.js 자동 생성) + 프로젝트 루트에 BalanceNote-specific 추가 — AI 에이전트 컨텍스트 카드

#### Anti-pattern 카탈로그 (피해야 할 것)

- API 응답 wrapper `{data, error}` 추가
- Pydantic `alias_generator=to_camel`로 wire format 변경
- 컴포넌트 type-based 조직(`components/`, `hooks/`)
- 도메인 예외 없이 generic `HTTPException` 남발
- 401 시 페이지 새로고침으로 회복 (refresh flow 우회)
- offset 페이지네이션
- `X-Custom-Header` 남용

## Project Structure & Boundaries

### Complete Project Directory Structure

```
AI_diet/
├── README.md
├── AGENTS.md                            # AI 에이전트 컨텍스트 카드
├── .env.example
├── .gitignore
├── .editorconfig
├── docker-compose.yml                   # FR47 Docker 1-cmd 부팅
├── .github/
│   └── workflows/
│       ├── ci.yml                       # PR 게이트 (ruff + mypy + pytest + tsc + openapi diff)
│       └── daily-cost-alert.yml         # 일별 비용 cron (R6, NFR-Sc4)
├── docker/
│   ├── Dockerfile.api
│   └── postgres-init/
│       └── 01-pgvector.sql              # CREATE EXTENSION vector
├── scripts/
│   ├── seed_food_db.py                  # 식약처 OpenAPI 시드 (W1)
│   ├── seed_guidelines.py               # KDRIs/대비/대당 chunking 시드 (W2)
│   ├── upload_eval_dataset.py           # 한식 100건 LangSmith Dataset 업로드 (W3, NFR-O3)
│   ├── gen_openapi_clients.sh           # pnpm gen:api 래퍼
│   └── verify_allergy_22.py             # 식약처 별표 22종 갱신 검증 SOP (R8)
├── docs/
│   ├── sop/
│   │   ├── 01-medical-device-classification.md   # 의료기기 미분류 SOP (B4)
│   │   ├── 02-pipa-automated-decision-consent.md # PIPA 동의서 템플릿 (B4)
│   │   ├── 03-disclaimer-ko-en.md                # 디스클레이머 한·영 (B4)
│   │   └── 04-fda-style-ad-expression-guard.md   # 식약처 광고 가드 (B4)
│   ├── faq/
│   │   ├── 01-differentiation.md                 # 영업 답변 closing #1
│   │   ├── 02-medical-device.md                  # closing #2
│   │   ├── 03-customization.md                   # closing #3
│   │   ├── 04-feasibility-8-weeks.md             # closing #4
│   │   └── 05-maintenance.md                     # closing #5
│   └── runbook/
│       ├── deployment.md
│       ├── secret-rotation.md
│       └── incident-response.md
├── api/                                  # FastAPI + LangGraph
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── alembic.ini
│   ├── .python-version
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                       # FastAPI app entry
│   │   ├── core/
│   │   │   ├── config.py                 # Pydantic Settings (.env)
│   │   │   ├── security.py               # JWT user/admin 분리, OAuth flow
│   │   │   ├── logging.py                # structlog + 마스킹 processor
│   │   │   ├── sentry.py                 # before_send hook
│   │   │   ├── middleware.py             # request_id, CORS
│   │   │   └── exceptions.py             # 도메인 예외 계층 + RFC 7807 핸들러
│   │   ├── domain/                       # 외주 인수 갈아끼우기 계층
│   │   │   ├── enums.py
│   │   │   ├── allergens.py              # 식약처 22종 lookup (C4)
│   │   │   ├── kdris.py                  # KDRIs AMDR 매크로 룰
│   │   │   ├── fit_score.py              # 0-100 알고리즘 (FR21)
│   │   │   ├── bmr.py                    # Mifflin-St Jeor + TDEE
│   │   │   └── ad_expression_guard.py    # 식약처 광고 가드 (C5)
│   │   ├── graph/
│   │   │   ├── __init__.py
│   │   │   ├── state.py                  # MealAnalysisState (TypedDict)
│   │   │   ├── nodes/
│   │   │   │   ├── parse_meal.py
│   │   │   │   ├── retrieve_nutrition.py
│   │   │   │   ├── evaluate_retrieval_quality.py    # Self-RAG 분기 (FR18)
│   │   │   │   ├── rewrite_query.py                 # 재작성 (FR19)
│   │   │   │   ├── fetch_user_profile.py
│   │   │   │   ├── evaluate_fit.py                  # FR21-FR22, Claude 보조
│   │   │   │   └── generate_feedback.py             # FR23-FR26 스트리밍·인용
│   │   │   ├── edges.py
│   │   │   ├── pipeline.py               # StateGraph 구성
│   │   │   └── checkpointer.py           # AsyncPostgresSaver (lg_checkpoints schema)
│   │   ├── rag/
│   │   │   ├── chunking/                 # 재사용 모듈 (외주 인수 인터페이스)
│   │   │   │   ├── pdf.py
│   │   │   │   ├── html.py
│   │   │   │   └── markdown.py
│   │   │   ├── food/
│   │   │   │   ├── search.py             # 정규화 + 임베딩 fallback (FR19)
│   │   │   │   ├── normalize.py          # food_aliases 매칭
│   │   │   │   └── seed.py
│   │   │   └── guidelines/
│   │   │       ├── search.py             # filtered top-K
│   │   │       └── seed.py
│   │   ├── api/
│   │   │   ├── deps.py                   # current_user, require_admin, require_consent, audit_admin_action
│   │   │   └── v1/
│   │   │       ├── auth.py               # FR1, FR4
│   │   │       ├── users.py              # FR2-FR3, FR5, FR9
│   │   │       ├── meals.py              # FR12-FR16
│   │   │       ├── analysis.py           # FR17-FR27 (SSE)
│   │   │       ├── reports.py            # FR32-FR34
│   │   │       ├── notifications.py      # FR29-FR31
│   │   │       ├── admin.py              # FR35-FR39
│   │   │       ├── payments.py           # FR40-FR42
│   │   │       ├── legal.py              # FR6-FR8, FR11
│   │   │       └── consents.py           # FR7
│   │   ├── db/
│   │   │   ├── session.py                # async engine
│   │   │   ├── base.py                   # SQLAlchemy declarative base
│   │   │   └── models/
│   │   │       ├── user.py
│   │   │       ├── consent.py
│   │   │       ├── meal.py
│   │   │       ├── meal_analysis.py
│   │   │       ├── food_nutrition.py
│   │   │       ├── knowledge_chunk.py
│   │   │       ├── food_alias.py
│   │   │       ├── subscription.py
│   │   │       ├── payment_log.py
│   │   │       ├── audit_log.py
│   │   │       └── notification.py
│   │   ├── adapters/                     # 외부 통합 격리
│   │   │   ├── openai.py                 # GPT-4o-mini, Vision
│   │   │   ├── anthropic.py              # Claude
│   │   │   ├── llm_router.py             # 듀얼-LLM fallback (NFR-R2)
│   │   │   ├── mfds_openapi.py           # 식약처
│   │   │   ├── toss.py
│   │   │   ├── stripe.py
│   │   │   ├── r2.py                     # Cloudflare R2
│   │   │   └── expo_push.py
│   │   ├── services/
│   │   │   ├── meal_service.py
│   │   │   ├── analysis_service.py       # graph.pipeline 래퍼
│   │   │   ├── notification_service.py
│   │   │   ├── audit_service.py
│   │   │   └── data_export_service.py    # PIPA 권리 (FR9)
│   │   └── workers/
│   │       ├── nudge_scheduler.py        # 미기록 푸시 (FR29)
│   │       └── soft_delete_purge.py      # 30일 grace 후 물리 파기
│   └── tests/
│       ├── conftest.py
│       ├── test_auth.py
│       ├── test_meals.py
│       ├── test_analysis.py
│       ├── test_admin.py
│       ├── test_payments.py
│       ├── domain/
│       │   ├── test_fit_score.py
│       │   ├── test_bmr.py
│       │   ├── test_allergens.py
│       │   └── test_ad_expression_guard.py
│       ├── graph/
│       │   ├── test_pipeline.py
│       │   ├── test_self_rag.py
│       │   └── nodes/
│       │       ├── test_parse_meal.py
│       │       ├── test_retrieve_nutrition.py
│       │       ├── test_evaluate_fit.py
│       │       └── test_generate_feedback.py
│       └── rag/
│           ├── test_food_search.py
│           └── test_chunking.py
├── web/                                  # Next.js 16
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── .env.example
│   ├── AGENTS.md                         # Next.js 자동 생성
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx                  # 랜딩
│   │   │   ├── (public)/
│   │   │   │   ├── login/page.tsx
│   │   │   │   └── legal/
│   │   │   │       ├── disclaimer/page.tsx
│   │   │   │       ├── terms/page.tsx
│   │   │   │       └── privacy/page.tsx
│   │   │   ├── en/legal/                 # NFR-L2 영문
│   │   │   │   ├── disclaimer/page.tsx
│   │   │   │   ├── terms/page.tsx
│   │   │   │   └── privacy/page.tsx
│   │   │   ├── (user)/
│   │   │   │   ├── dashboard/weekly/page.tsx     # FR32 주간 리포트
│   │   │   │   ├── settings/page.tsx
│   │   │   │   └── account/
│   │   │   │       ├── delete/page.tsx           # FR5
│   │   │   │       └── export/page.tsx           # FR9
│   │   │   └── (admin)/
│   │   │       └── admin/
│   │   │           ├── login/page.tsx
│   │   │           ├── users/page.tsx            # FR36
│   │   │           ├── audit-logs/page.tsx       # FR37-FR38
│   │   │           └── layout.tsx                # admin role 가드
│   │   ├── features/
│   │   │   ├── auth/
│   │   │   ├── reports/
│   │   │   │   ├── WeeklyReport.tsx
│   │   │   │   ├── MacroChart.tsx
│   │   │   │   ├── CalorieChart.tsx
│   │   │   │   ├── ProteinChart.tsx
│   │   │   │   └── AllergyExposureChart.tsx
│   │   │   ├── settings/
│   │   │   ├── admin/
│   │   │   │   ├── UserSearch.tsx
│   │   │   │   └── AuditLogTable.tsx
│   │   │   └── legal/
│   │   ├── lib/
│   │   │   ├── api-client.ts             # 생성된 OpenAPI 클라이언트
│   │   │   ├── auth.ts
│   │   │   ├── format.ts
│   │   │   └── query-client.ts           # TanStack Query
│   │   ├── components/
│   │   │   └── ui/                       # shadcn/ui 선택적
│   │   └── middleware.ts                 # admin route guard
│   └── tests/                            # co-located *.test.tsx in features/
├── mobile/                               # Expo SDK 54
│   ├── package.json
│   ├── app.json
│   ├── tsconfig.json
│   ├── .env.example
│   ├── app/                              # Expo Router
│   │   ├── _layout.tsx
│   │   ├── index.tsx                     # 인증 분기
│   │   ├── (auth)/
│   │   │   ├── login.tsx                 # FR1
│   │   │   └── onboarding/
│   │   │       ├── disclaimer.tsx        # FR6
│   │   │       ├── terms.tsx
│   │   │       ├── privacy.tsx
│   │   │       ├── automated-decision.tsx # FR7
│   │   │       ├── tutorial.tsx          # FR28
│   │   │       └── profile.tsx           # FR2
│   │   ├── (tabs)/
│   │   │   ├── _layout.tsx
│   │   │   ├── meals/
│   │   │   │   ├── index.tsx             # FR14 일별 기록
│   │   │   │   ├── input.tsx             # FR12-FR15
│   │   │   │   └── [meal_id].tsx         # 채팅 SSE (FR26)
│   │   │   └── settings/
│   │   │       ├── index.tsx
│   │   │       ├── profile.tsx           # FR3
│   │   │       ├── notifications.tsx     # FR30
│   │   │       ├── disclaimer.tsx        # FR8
│   │   │       ├── terms.tsx
│   │   │       ├── privacy.tsx
│   │   │       ├── data-export.tsx       # FR9
│   │   │       ├── account-delete.tsx    # FR5
│   │   │       └── about.tsx
│   │   └── +not-found.tsx
│   ├── features/
│   │   ├── auth/
│   │   ├── meals/
│   │   │   ├── MealInput.tsx
│   │   │   ├── ChatStreaming.tsx         # react-native-sse (FR26)
│   │   │   ├── DailyMealList.tsx
│   │   │   └── api.ts
│   │   ├── notifications/
│   │   ├── onboarding/
│   │   └── settings/
│   ├── lib/
│   │   ├── api-client.ts
│   │   ├── auth.ts
│   │   ├── secure-store.ts
│   │   ├── offline-queue.ts              # FR16 텍스트 큐잉
│   │   └── push.ts                       # Expo Notifications
│   └── assets/
└── _bmad-output/                         # BMad 산출물
    └── planning-artifacts/
        ├── product-brief-BalanceNote-2026-04-26.md
        ├── prd.md
        ├── architecture.md               # 본 문서
        └── research/
```

### Architectural Boundaries

#### API 경계

- **외부:** `/v1/*` REST + Swagger `/docs` + SSE `/v1/analysis/stream`
- **인증 경계:** `Depends(current_user)` (일반) / `Depends(require_admin)` (admin) / `Depends(require_consent)` (PIPA 자동화 동의 게이트, FR7)
- **데이터 접근:** SQLAlchemy ORM via `app/db/` — services 외에서 직접 모델 import 금지

#### 컴포넌트 경계 (Frontend)

- **Web:** `middleware.ts`가 `(admin)` route group 진입 차단 (admin JWT 검증)
- **Mobile:** `app/index.tsx`가 인증 상태에 따라 `(auth)` 또는 `(tabs)`로 분기
- **상태 경계:** server state는 TanStack Query만 / client state는 컴포넌트 로컬 + 필요 시 zustand

#### 서비스 경계 (Backend)

- **Routers:** 1파일 1 APIRouter, 도메인별 분리, 라우터는 service layer만 호출
- **Services:** 도메인 비즈니스 로직 — DB + adapters 조합. 라우터·LangGraph 노드 둘 다에서 재사용 가능
- **LangGraph:** `app/graph/`에 격리 — `analysis_service.py`가 thin wrapper로 노출
- **Adapters:** 외부 API는 `app/adapters/*.py`에 격리 — services에서만 호출, 라우터 직접 호출 금지

#### 데이터 경계

- **Postgres:** `public` schema(앱 데이터) + `lg_checkpoints` schema(LangGraph). 두 schema 격리로 마이그레이션 충돌 차단
- **Redis 키 네임스페이스:** `cache:llm:*`, `cache:food:*`, `cache:user:*`, `cache:rl:*` — 무효화 패턴 분리
- **R2:** 이미지 write는 백엔드 presigned URL, read는 CDN 직접 (인증 토큰 불필요한 public read)

### Requirements to Structure Mapping

#### Capability 그룹 → 라우터·서비스·DB 모델

| FR 그룹 | 라우터 | Services / Domain | DB 모델 |
|---------|-------|------------------|---------|
| Identity & Account (FR1-5) | `auth.py`, `users.py` | `app/core/security.py` | `user`, `consent` |
| Privacy/Compliance (FR6-11) | `legal.py`, `consents.py`, `users.py` | `data_export_service.py` | `consent` |
| Meal Logging (FR12-16) | `meals.py` | `meal_service.py` + `r2.py` adapter + `offline-queue.ts` (mobile) | `meal` |
| AI Analysis (FR17-27) | `analysis.py` | `analysis_service.py` + `app/graph/*` + `app/rag/*` + `domain/fit_score.py` + `llm_router.py` | `meal_analysis`, `food_nutrition`, `knowledge_chunk`, `food_alias` |
| Engagement (FR28-31) | `notifications.py` | `notification_service.py` + `nudge_scheduler.py` worker + `expo_push.py` adapter | `notification` |
| Insights (FR32-34) | `reports.py` | report aggregation queries | (조회 only) |
| Admin/Audit (FR35-39) | `admin.py` | `audit_service.py` + admin role decorator | `audit_log` |
| Subscription (FR40-42) | `payments.py` | `toss.py` / `stripe.py` adapter | `subscription`, `payment_log` |
| Operations (FR43-49) | (전체 횡단) | `core/{config,security,logging,sentry,observability,middleware}`, slowapi, Swagger, `langsmith` SDK | (전체) |

#### Cross-cutting Concerns → 위치

| Concern | 위치 |
|---------|-----|
| PIPA 동의 게이트 (FR7) | `app/api/deps.py:require_consent` Dependency |
| Audit log 자동 기록 (FR37) | `app/api/deps.py:audit_admin_action` Dependency + `services/audit_service.py` |
| 민감정보 마스킹 (NFR-S5) | `app/core/logging.py` structlog processor + `app/core/sentry.py` before_send hook + `app/core/observability.py` LangSmith run mask hook (NFR-O2) |
| LLM 옵저버빌리티 (FR49 / NFR-O1~O5) | `app/core/observability.py` (LangSmith client + 마스킹 hook) + `LANGCHAIN_TRACING_V2` env + LangGraph native 통합 + `scripts/upload_eval_dataset.py` |
| 광고 표현 가드 (C5, T10) | `app/domain/ad_expression_guard.py` + `generate_feedback` 노드 후처리 |
| 알레르기 22종 무결성 (C4) | `app/domain/allergens.py` + DB CHECK 제약 + `scripts/verify_allergy_22.py` SOP |
| Rate limit (NFR-S4) | slowapi middleware + Redis backend, 라우터 데코레이터 단위 |
| 디스클레이머 노출 (FR11) | mobile `(tabs)/settings/disclaimer.tsx` + `(auth)/onboarding/disclaimer.tsx` + 분석 결과 카드 푸터 |

### Integration Points

#### 내부 통신

- HTTP REST + SSE between mobile/web ↔ api
- LangGraph 노드 간: TypedDict state 전달 (`MealAnalysisState`)
- BackgroundTasks: cron 스케줄링 (FastAPI BackgroundTasks + APScheduler 또는 외부 cron)

#### 외부 통합

- **OpenAI/Anthropic** — `app/adapters/{openai,anthropic}.py` + `llm_router.py` (듀얼-LLM fallback, NFR-R2)
- **OpenAI Vision** — `openai.py` 안에 같이
- **식약처 OpenAPI** — `app/adapters/mfds_openapi.py` (W1 시드)
- **Toss/Stripe webhook** — `app/api/v1/payments.py:webhook` + `Idempotency-Key` 멱등화
- **Cloudflare R2** — `app/adapters/r2.py` (presigned URL 발급)
- **Expo Notifications** — `app/adapters/expo_push.py` + cron scheduler
- **LangSmith** — `app/core/observability.py` (마스킹 hook + 클라이언트 셋업, `LANGCHAIN_TRACING_V2` env로 native 자동 트레이싱, FR49 / NFR-O1~O5)

#### 데이터 흐름 — 분석 핵심 경로

1. Mobile `meals/input.tsx` → `POST /v1/meals` (이미지는 R2 presigned URL 직접 업로드 후 키 전달)
2. Mobile → `POST /v1/analysis/stream` (SSE)
3. `analysis_service.run()` → `graph.pipeline.ainvoke(state)` (with PostgresSaver)
4. 노드 시퀀스: `parse_meal` → `retrieve_nutrition` (food RAG) → `evaluate_retrieval_quality` → (분기) `rewrite_query` → 재 retrieve / `needs_clarification` → `fetch_user_profile` → `evaluate_fit` (Claude 보조) → `generate_feedback` (인용 + 가드 + 스트리밍)
5. SSE `event: token` 스트림 → mobile `ChatStreaming.tsx`가 점진 렌더
6. `event: done` 시 `meal_analyses`에 결과 저장 + `event: citation` 메타 표시
7. 알레르기 위반 발견 시 `evaluate_fit`이 즉시 score=0 단락

### Development Workflow Integration

- **개발 서버:** Docker Compose 1-cmd 부팅 → api(`localhost:8000`) + postgres(`5432`) + redis(`6379`) + seed 컨테이너 실행
- **Web 개발:** `pnpm dev` (Next.js Turbopack, `localhost:3000`) — api는 도커 또는 별도 실행
- **Mobile 개발:** `pnpm start` (Expo dev server) — Expo Go 또는 development build
- **빌드 프로세스:** Web은 Vercel 자동 빌드 / Mobile은 EAS Build / API는 Railway Docker 빌드
- **배포 구조:** main 브랜치 머지 → Vercel + Railway 자동 배포. PR은 staging preview 자동 생성

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**

- 듀얼-LLM(OpenAI+Claude) ↔ `llm_router.py` 어댑터 ↔ tenacity retry ↔ NFR-R2 fallback — 일관 정합
- LangGraph 6노드 ↔ `langgraph-checkpoint-postgres` ↔ Self-RAG 재검색 ↔ J2 재질문 — 일관 정합
- snake_case 양방향 wire format ↔ Python idiom ↔ 식약처 jsonb 키 ↔ OpenAPI 자동 매핑 — 일관 정합
- PIPA 동의 게이트 ↔ `Depends(require_consent)` ↔ FR7 자동 차단 — LLM 비용 0 보호 작동

**Pattern Consistency:**

- Naming(snake_case DB + camelCase TS + PascalCase 컴포넌트) ↔ 언어 idiom 표준 정합
- Feature-based 조직 ↔ 외주 인수 시 도메인 분할 가치 정합
- Services → Adapters → External 단방향 의존성 ↔ 어댑터 패턴 정합

**Structure Alignment:**

- `app/domain/` 격리 ↔ "외주 인수 갈아끼우기" 차별화 카드 정합
- `(public)/(user)/(admin)` route groups ↔ 인증 경계 정합
- `lg_checkpoints` schema 분리 ↔ 마이그레이션 충돌 차단 정합

### Requirements Coverage Validation ✅

**FR Coverage Matrix (48/48):**

| FR 그룹 | FR # | 구현 위치 |
|---------|------|---------|
| Identity | FR1, FR4 | `api/v1/auth.py` + `core/security.py` + mobile `(auth)/login.tsx` |
| Identity | FR2, FR3 | `api/v1/users.py` + mobile `(auth)/onboarding/profile.tsx` + `(tabs)/settings/profile.tsx` |
| Identity | FR5 | `api/v1/users.py:DELETE` + soft delete + `workers/soft_delete_purge.py` + mobile `account-delete.tsx` + web `/account/delete` |
| Privacy | FR6 | mobile `(auth)/onboarding/{disclaimer,terms,privacy}.tsx` + `consents.py` |
| Privacy | FR7 | `consents.py` + `deps.require_consent` 게이트 + mobile `automated-decision.tsx` |
| Privacy | FR8 | `legal.py` + mobile `(tabs)/settings/{disclaimer,terms,privacy}.tsx` + web `(public)/legal/*` + `en/legal/*` |
| Privacy | FR9 | `users.py:export` + `data_export_service.py` + mobile `data-export.tsx` + web `/account/export` |
| Privacy | FR10 | mobile `lib/permissions.ts` + `features/onboarding/PermissionDeniedView.tsx` (gap 보강) |
| Privacy | FR11 | mobile 분석 결과 카드 푸터 컴포넌트 (`features/meals/ChatStreaming.tsx` 내부) |
| Meals | FR12-15 | `meals.py` + `meal_service.py` + `r2.py` adapter + mobile `meals/input.tsx` + Vision `openai.py` adapter |
| Meals | FR16 | mobile `lib/offline-queue.ts` (AsyncStorage) |
| Analysis | FR17 | `app/graph/pipeline.py` + 6 노드 |
| Analysis | FR18 | `nodes/evaluate_retrieval_quality.py` + `nodes/rewrite_query.py` |
| Analysis | FR19 | `rag/food/normalize.py` + `food_aliases` 테이블 |
| Analysis | FR20 | `app/graph/edges.py` `needs_clarification` 분기 |
| Analysis | FR21 | `domain/fit_score.py` (Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15) |
| Analysis | FR22 | `domain/fit_score.py` 알레르기 위반 즉시 0점 단락 + `domain/allergens.py` |
| Analysis | FR23-24 | `nodes/generate_feedback.py` + `knowledge_chunks` 메타데이터 + 후처리 인용 검증 |
| Analysis | FR25 | `domain/ad_expression_guard.py` + `generate_feedback` 후처리 |
| Analysis | FR26 | SSE `sse-starlette` + mobile `react-native-sse` + `ChatStreaming.tsx` |
| Analysis | FR27 | `adapters/llm_router.py` 듀얼-LLM fallback |
| Engagement | FR28 | mobile `(auth)/onboarding/tutorial.tsx` |
| Engagement | FR29 | `workers/nudge_scheduler.py` (APScheduler) + `expo_push.py` adapter |
| Engagement | FR30 | `notifications.py` + mobile `(tabs)/settings/notifications.tsx` |
| Engagement | FR31 | mobile push handler + Expo Router deep link |
| Reports | FR32 | `reports.py` + web `features/reports/{Macro,Calorie,Protein,AllergyExposure}Chart.tsx` |
| Reports | FR33 | `reports.py` aggregation + 인사이트 카드 |
| Reports | FR34 | `notifications.py` + 권장 매크로 룰 갱신 |
| Admin | FR35 | `api/v1/admin.py` + admin JWT 분리 (`core/security.py`) |
| Admin | FR36 | `admin.py:users` 검색 라우터 |
| Admin | FR37 | `deps.audit_admin_action` Dependency + `services/audit_service.py` + `audit_log` 모델 |
| Admin | FR38 | `admin.py:audit_logs` self-audit 화면 |
| Admin | FR39 | 관리자 화면 마스킹 — Web `features/admin/UserSearch.tsx` 마스킹 토글 |
| Subscription | FR40-42 | `payments.py` + `toss.py`/`stripe.py` adapter + `subscription`/`payment_log` 모델 |
| Operations | FR43 | Redis cache + 키 네임스페이스 표준 |
| Operations | FR44 | slowapi + Redis backend 3-tier rate limit |
| Operations | FR45 | Sentry SDK + `sentry.py:before_send` 마스킹 |
| Operations | FR46 | FastAPI 자동 OpenAPI + `/docs` |
| Operations | FR47 | `docker-compose.yml` + seed 컨테이너 |
| Operations | FR48 | README 5섹션 + Docker + Swagger |

**NFR Coverage:**

- **Performance (NFR-P1-P10):** SSE 프로토콜 + pgvector HNSW + Redis 캐시 + Next.js Turbopack/RSC + cursor pagination
- **Security (NFR-S1-S10):** TLS+HSTS + JWT user/admin 분리 + 마스킹 processor + slowapi + Railway secrets + 키 회전 SOP
- **Reliability (NFR-R1-R6):** 듀얼-LLM fallback + Pydantic+retry+error edge + DB 503 안내 + Sentry + 일별 백업
- **Scalability (NFR-Sc1-Sc4):** baseline 100 동시/1K DAU + Vercel CDN + Redis 캐시 + 일별 비용 알림 + README 마이그레이션 가이드
- **Accessibility (NFR-A1-A5):** Implementation Patterns에 a11y 룰 추가 (gap 보강) — RN accessibility props 표준화 + 색상 대비 4.5:1/3:1 + 키보드 내비게이션 + 차트 데이터 테이블 fallback
- **UX/Coaching Voice (NFR-UX1-UX6):** `generate_feedback` 시스템 프롬프트 + `ad_expression_guard` 후처리 결합
- **Localization (NFR-L1-L4):** 한국어 1차 + `/en/legal/*` 라우트 영문 풀텍스트
- **Maintainability (NFR-M1-M8):** Pytest 70% CI 게이트 + README 5섹션 + SOP 4종 + Docker dev parity + 도메인 추상 계층
- **Compliance (NFR-C1-C5):** 모두 SOP 4종 + 게이트·가드·CHECK 제약·디스클레이머 4-surface 노출로 매핑

**Compliance C1-C6 Coverage:**

| Compliance | 위치 |
|-----------|-----|
| C1 의료기기 미분류 | SOP 1 + `domain/ad_expression_guard.py` + `fit_score` 명명 + 영업 답변 FAQ #2 |
| C2 PIPA 자동화 의사결정 | `consents.py` + `deps.require_consent` + SOP 2 + mobile `automated-decision.tsx` |
| C3 디스클레이머 한·영 | SOP 3 + 4 surface (onboarding, footer, settings, web legal) |
| C4 22종 알레르기 | `domain/allergens.py` + DB CHECK 제약 + `scripts/verify_allergy_22.py` SOP |
| C5 광고 표현 가드 | `domain/ad_expression_guard.py` + `generate_feedback` 후처리 |
| C6 데이터 보존·파기 | `workers/soft_delete_purge.py` (30일 grace) + Sentry 30일 보존 + Postgres 7일 백업 |

**7 Journeys → 추적성:**

- J1 (모바일 happy path) → FR1+2+3+4+5+6+7+12+15+17+21+23+26
- J2 (Self-RAG 재질문) → FR18+19+20
- J3 (푸시 nudge → 빠른 진입) → FR29+30+31
- J4 (Web 주간 리포트) → FR32+33+34
- J5 (외주 영업 데모) → B1+B2 + 운영 산출물 + Docker 1-cmd
- J6 (Admin audit) → FR35+36+37+38+39
- J7 (외주 인수 후 클라이언트) → FR47+48 + 한국 표준 추상 계층

**R1-R10 Risk Mitigation 위치:**

| 리스크 | Mitigation 위치 |
|-------|-----------------|
| R1 음식명 매칭 | `rag/food/normalize.py` + `food_aliases` + 임베딩 fallback |
| R2 RN SSE | `react-native-sse` + polling fallback + W4 day1 spike |
| R3 Structured Output | Pydantic + tenacity retry + error edge fallback |
| R4 영양 DB 시드 | `scripts/seed_food_db.py` + 통합 자료집 ZIP fallback + USDA 백업 |
| R5 로컬↔클라우드 | Docker Compose dev parity (W1부터) |
| R6 LLM 비용 폭증 | Redis 캐시 + GPT-4o-mini 메인 + `daily-cost-alert.yml` |
| R7 식약처 API 장애 | 통합 자료집 ZIP fallback + USDA 백업 |
| R8 22종 갱신 | `scripts/verify_allergy_22.py` 분기 SOP |
| R9 PIPA 시행령 갱신 | 분기 모니터링 SOP (docs/sop) |
| R10 진단성 발언 요구 | C1+C5 + 영업 답변 FAQ #2 |

### Implementation Readiness Validation ✅

**Decision Completeness:**

- 모든 critical 결정 라이브러리·버전 명시 (PostgreSQL 17 / pgvector 0.8.2 / SQLAlchemy 2.0.49 / LangGraph 1.1.9 / Next.js 16.2.4 / Expo SDK 54)
- W1 day1 spike 우선순위 (R5/R7) → W4 day1 (R2) → W7 (배포·결제) 명시
- Cross-component dependency 4건 명시 (lg_checkpoints schema, audit dep 연쇄, PIPA 게이트 위치, OpenAPI schema diff CI)

**Structure Completeness:**

- Top-level 폴더 8개 + api/web/mobile 각 detailed sub-tree
- 48 FR이 모두 특정 파일/모듈에 매핑
- Cross-cutting 7개가 모두 위치 명시

**Pattern Completeness:**

- Naming · Structure · Format · Communication · Process 5개 카테고리 + Anti-pattern 카탈로그
- Accessibility 패턴 추가 (gap 보강)

### Gap Analysis Results — 보강 결과

**Important Gaps (보강 완료):**

1. **Accessibility 패턴 추가 (NFR-A1-A5):**
   - 모바일: 모든 인터랙티브 요소에 `accessibilityLabel` + `accessibilityRole` 명시
   - 색상 대비 4.5:1(본문) / 3:1(큰 텍스트) — Tailwind 토큰에 통과 색상만
   - fit_score는 색상 + 숫자 + 텍스트 라벨 동시 표시 (색약 대응)
   - Web 키보드 Tab 순서 자연 + 차트는 데이터 테이블 fallback
   - PR 시 `eslint-plugin-jsx-a11y` (web) + RN 표준 props 검증

2. **권한 거부 안내 화면 재사용 컴포넌트 (FR10):**
   - `mobile/lib/permissions.ts` — 권한 상태 hook (`useCameraPermission`, `useMediaLibraryPermission`, `useNotificationPermission`)
   - `mobile/features/onboarding/PermissionDeniedView.tsx` — 표준 안내 + Linking.openSettings() deep link
   - 각 권한 거부 시 권한별 안내 메시지 + 설정 가이드

3. **Cron 스케줄링 메커니즘 (FR29):**
   - **APScheduler 채택** (`apscheduler[asyncio]`)
   - `app/workers/scheduler.py`에 AsyncIOScheduler 인스턴스화 + FastAPI lifespan에 시작/종료
   - `nudge_scheduler.py` 작업은 매일 19:30/20:30 KST에 등록 (사용자 알림 시간 + 30분)
   - 1인 8주 정합: in-process, Railway 단일 노드, 별 외부 cron 무필요

**Nice-to-Have Gaps (W3/W5 구현 시 결정):**

4. OCR Vision 신뢰도 임계값 + 사용자 확인 UX (FR15) — `parse_meal` 노드 출력에 `confidence` 필드 + 임계값 미만 시 모바일 confirm 카드 노출
5. shadcn/ui 컴포넌트 화이트리스트 — 사용 시점에 점진 결정 (`components/ui/` 추가 시)

### Architecture Completeness Checklist

- ✅ Project context 분석 + scale/complexity 평가 + technical constraints + cross-cutting 7개
- ✅ Critical 결정 모두 버전 명시 + tech stack 완비 + integration patterns + 성능 고려
- ✅ Naming · Structure · Format · Communication · Process · Accessibility 패턴 + Anti-pattern 카탈로그
- ✅ 완전한 디렉토리 트리 + 컴포넌트 경계 + 통합 지점 + 48 FR 매핑

### Architecture Readiness Assessment

**Overall Status:** ✅ **READY FOR IMPLEMENTATION**

**Confidence Level:** **HIGH** — 모든 라이브러리·버전 검증, 48 FR + NFR + 컴플라이언스 + 7 Journey + R1-R10 리스크 모두 매핑 완료.

**Key Strengths:**

- 한국 표준(식약처 22종/KDRIs/jsonb 키) 도메인 추상 계층 — 외주 인수 시 갈아끼우기 가능
- 듀얼-LLM + Self-RAG + 인용 가드 — 영업 차별화 카드 4종이 코드 위치로 박힘
- PIPA 동의 게이트가 *분석 호출 전* 차단 — LLM 비용 0 보호
- Docker Compose 1-cmd + GitHub Actions PR 게이트 — 외주 인수 8시간 부팅 KPI 직접 측정 가능

**Areas for Future Enhancement (Post-MVP / 외주 첫 사이클 후):**

- 컬럼 단위 암호화 (NFR-S6 Growth)
- WCAG AA 풀 인증 (NFR-A6)
- 풀 다국어 UI (NFR-L4)
- 멀티-AZ + Postgres replica + Redis cluster (NFR-Sc3)
- 가이드라인 RAG 자동 chunking 파이프라인 (chunking 모듈 재사용 → 외주 클라이언트 PDF 자동 시드)
- A/B 테스트 인프라 (Growth)
- EMR 어댑터 (병원 클라이언트)

### Implementation Handoff

**AI Agent Guidelines:**

- 본 architecture.md를 단일 출처(single source of truth)로 사용
- 결정 변경 시 PR review에서 이 문서 갱신 필수
- 새 컴포넌트는 위 디렉토리 트리 + naming/format/structure 패턴 정합 검증
- 모든 admin 라우터는 `Depends(audit_admin_action)` 명시
- 모든 분석 호출은 `Depends(require_consent)` 게이트 통과
- 모든 LangGraph 노드 출력은 Pydantic 모델로 검증
- API 응답에 wrapper 추가 금지 (RFC 7807 에러 외 직접 응답)

**First Implementation Priority (W1 day1 — Story 1.1):**

```bash
# 1. 프로젝트 폴더 부트스트랩
mkdir -p AI_diet/{api,web,mobile,docker,scripts,docs,.github/workflows}
cd AI_diet

# 2. Web 부트스트랩
pnpm create next-app@latest web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --turbopack

# 3. Mobile 부트스트랩
npx create-expo-app@latest mobile --template default

# 4. API 부트스트랩
mkdir api && cd api
uv init --python 3.13
uv add fastapi[standard] langgraph langchain langchain-openai langchain-anthropic
uv add sqlalchemy[asyncio] alembic asyncpg pgvector pydantic-settings
uv add redis httpx tenacity sentry-sdk python-jose[cryptography] passlib slowapi
uv add apscheduler langgraph-checkpoint-postgres sse-starlette
uv add --dev pytest pytest-asyncio ruff mypy

# 5. Docker Compose + pgvector 컨테이너 부팅 검증 (W1 day1 R5/R7 spike)
docker compose up

# 6. 첫 Alembic migration — users 테이블
alembic revision --autogenerate -m "init users table"
alembic upgrade head
```




