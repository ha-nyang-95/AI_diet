---
stepsCompleted: ['step-01-validate-prerequisites', 'step-02-design-epics', 'step-03-create-stories', 'step-04-final-validation']
workflowComplete: true
completionDate: 2026-04-27
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
project_name: AI_diet
product_name: BalanceNote
---

# AI_diet (BalanceNote) - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for AI_diet (BalanceNote), decomposing the requirements from the PRD and Architecture into implementable stories.

**Frame:** 외주 영업용 포트폴리오 (학습용 X, 상용 SaaS X). 우선순위는 *영업 통과 가능성*. 9포인트 데모 + 외주 인수인계(Docker 1-cmd, 8시간 부팅) + 컴플라이언스 안전판이 1차 가치 증명 경로.

**UX Design 별도 문서 없음** — PRD/스토리에 흡수(사용자 명시 결정).

## Requirements Inventory

### Functional Requirements

**1. Identity & Account**

- **FR1.** 엔드유저는 Google OAuth로 가입·로그인하고 동일 계정으로 모바일·웹 양쪽에 인증된 채 진입할 수 있다.
- **FR2.** 엔드유저는 자기 건강 프로필(나이, 체중, 신장, 활동 수준, `health_goal` 4종 [`weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management`], 식약처 22종 알레르기 다중 선택)을 입력할 수 있다.
- **FR3.** 엔드유저는 자기 건강 프로필을 언제든 수정할 수 있고 변경은 이후 모든 분석에 즉시 반영된다.
- **FR4.** 엔드유저는 모바일 또는 웹 어디서나 로그아웃할 수 있다.
- **FR5.** 엔드유저는 자기 계정을 삭제(회원 탈퇴)할 수 있다. 시스템은 PIPA 외 관련법 보존 의무 항목 외 모든 사용자 데이터를 즉시 파기한다.

**2. Privacy, Compliance & Disclosure**

- **FR6.** 엔드유저는 첫 진입 시 표준 디스클레이머(한·영)를 확인하고 약관 동의 + 개인정보 동의(PIPA 민감정보, 별도 분리)를 통과한 뒤에만 핵심 기능에 진입할 수 있다.
- **FR7.** 엔드유저는 PIPA 2026.03.15 자동화 의사결정 동의를 별도로 수행하며, 미수신 사용자에 대해 시스템은 자동 분석(`evaluate_fit`/`generate_feedback`) 호출을 차단하고 안내 화면을 노출한다.
- **FR8.** 엔드유저는 약관·개인정보 처리방침·디스클레이머 한·영 텍스트를 앱·웹 어디서나 다시 열람할 수 있다.
- **FR9.** 엔드유저는 자기 식단·피드백·프로필 데이터를 표준 형식(JSON 또는 CSV)으로 다운로드할 수 있다 (PIPA 정보주체 권리).
- **FR10.** 엔드유저는 알림·카메라·사진첩 권한을 거부한 경우에도 빈 화면이 아닌 상황별 안내 화면과 설정 deep link를 제공받는다.
- **FR11.** 시스템은 모든 분석 피드백 카드 푸터에 *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 디스클레이머를 노출한다.

**3. Meal Logging**

- **FR12.** 엔드유저는 모바일에서 식단을 *텍스트* 또는 *사진*으로 입력할 수 있다.
- **FR13.** 엔드유저는 자기 식단 기록을 조회·수정·삭제할 수 있다.
- **FR14.** 엔드유저는 일별 식단 기록(식사 + 매크로 + 피드백 요약 + `fit_score`)을 한 화면에서 시간순으로 볼 수 있다.
- **FR15.** 엔드유저는 사진 업로드 시 OCR 결과로 추출된 음식 항목을 확인하고 수정한 후 분석을 시작할 수 있다.
- **FR16.** 엔드유저는 오프라인 상태에서 텍스트 식단을 입력하면 큐잉되어 온라인 복귀 시 자동 sync된다.

**4. AI Nutrition Analysis (Self-RAG + 인용형 피드백)**

- **FR17.** 시스템은 입력된 식사를 다단계 분석 파이프라인(음식 항목 추출 → 영양 검색 → 검색 신뢰도 평가 → 사용자 프로필 조회 → 적합도 평가 → 피드백 생성)으로 처리한다.
- **FR18.** 시스템은 음식 영양 검색 신뢰도가 임계값 미달 시 쿼리를 재작성하고 1회 재검색하는 자가-검증 패턴을 수행한다.
- **FR19.** 시스템은 한국식 음식명 변형(예: "짜장면" / "자장면")을 통합 매칭하여 동일 항목으로 인식한다.
- **FR20.** 시스템은 음식 인식 신뢰도가 재검색 후에도 낮으면 사용자에게 *"이게 ◯◯이 맞나요?"* 형태의 재질문을 보내 모호성을 해소한다.
- **FR21.** 시스템은 사용자 건강 목표·매크로 적합도·칼로리 적합도·알레르기·영양 균형을 통합하여 0-100 *건강 목표 부합도 점수*를 산출한다.
- **FR22.** 시스템은 사용자 알레르기 항목과 식사 매칭 발견 시 점수 0과 *알레르기 위반* 사유를 반환하고 매크로/칼로리 점수를 무시한다.
- **FR23.** 시스템은 분석 결과를 한국 1차 출처(보건복지부 KDRIs / 대한비만학회 / 대한당뇨병학회 / 식약처 식품영양성분 DB) 인용을 포함한 자연어 피드백으로 생성한다.
- **FR24.** 시스템은 모든 권고 텍스트에 *(출처: 기관명, 문서명, 연도)* 패턴을 포함하며, 누락 시 후처리에서 재생성 또는 안전 워딩으로 치환한다.
- **FR25.** 시스템은 식약처 광고 금지 표현(진단·치료·예방·완화)을 가드레일로 필터링하고 안전 대안 워딩으로 치환한다.
- **FR26.** 엔드유저는 분석 결과를 모바일 채팅 UI에서 스트리밍 텍스트로 점진 수신한다.
- **FR27.** 시스템은 메인 LLM 호출 실패 시 보조 LLM(별도 벤더)으로 자동 전환하여 분석을 완료한다.

**5. Engagement & Notifications**

- **FR28.** 엔드유저는 첫 사용 시 *디스클레이머 → 약관 동의 → 사용법 안내(2-3 화면) → 건강 프로필 입력*의 온보딩 튜토리얼을 순차 통과한다.
- **FR29.** 시스템은 사용자 설정 시간(기본 저녁 8시) 후 30분 경과 + 당일 식단 미입력 시 자동 푸시 nudge를 전송한다.
- **FR30.** 엔드유저는 푸시 알림을 ON/OFF로 토글하고, 알림 시간을 변경할 수 있다.
- **FR31.** 엔드유저가 푸시 알림을 탭하면 모바일 식단 입력 화면으로 직행한다.

**6. Insights & Reporting**

- **FR32.** 엔드유저는 웹에서 자기 주간 리포트(7일 매크로 비율 추이 / 칼로리 vs TDEE / 단백질 g/kg 일별 추이 / 알레르기 노출 횟수)를 차트로 조회한다.
- **FR33.** 엔드유저는 주간 리포트에서 *"다음 주 권장 매크로 조정"* 인사이트 카드를 한국 1차 출처 인용과 함께 본다.
- **FR34.** 엔드유저는 다음 주 매크로/칼로리 목표를 설정 화면에서 조정할 수 있고, 변경은 미기록 nudge 룰과 모바일 권장 표시에 자동 반영된다.

**7. Administration & Audit Trust**

- **FR35.** 관리자는 일반 사용자와 분리된 admin role 인증으로 웹 관리자 화면에 진입한다.
- **FR36.** 관리자는 사용자 검색·식단 이력 조회·피드백 로그 조회·프로필 수정을 수행할 수 있다.
- **FR37.** 시스템은 관리자의 모든 조회·수정 액션을 *시점·액터·액션·대상*으로 audit log에 기록한다.
- **FR38.** 관리자는 자기 활동 로그를 관리자 화면에서 직접 조회할 수 있다 (self-audit).
- **FR39.** 시스템은 관리자가 사용자 데이터를 조회할 때 민감정보(이메일·체중·알레르기 상세)를 기본 마스킹 표시하고, 명시적 *원문 보기* 액션 시에만 해제한다.

**8. Subscription & Payment**

- **FR40.** 엔드유저는 정기결제 1플랜을 sandbox 결제 화면에서 신청·해지할 수 있다.
- **FR41.** 엔드유저는 자기 결제 영수증과 이용내역을 조회할 수 있다.
- **FR42.** 시스템은 결제 webhook을 받아 구독 상태를 갱신하고 결제 이벤트 이력을 기록한다.

**9. Operations & Handover**

- **FR43.** 시스템은 동일 입력 LLM 응답과 음식 검색 결과를 캐시 계층으로 응답 시간을 단축한다.
- **FR44.** 시스템은 사용자별 호출 횟수 제한과 LangGraph 호출 별도 제한을 적용하여 비용·악용을 방어한다.
- **FR45.** 시스템은 분석 노드 실패·외부 API 실패·DB 에러를 에러 트래킹에 자동 수집하며 민감정보를 마스킹한다.
- **FR46.** 시스템은 표준 OpenAPI 명세를 통해 모든 endpoint를 외주 인수인계 가능한 형태로 문서화한다.
- **FR47.** 시스템은 1-command 컨테이너 부팅으로 데이터베이스·벡터 검색·캐시·API·시드 데이터를 일괄 시작할 수 있다.
- **FR48.** 외주 클라이언트 개발자는 README + 컨테이너 부팅 명령만으로 1일 내 로컬 환경을 구축하고 자체 데이터 통합을 시도할 수 있다.

### NonFunctional Requirements

**Performance**

- **NFR-P1.** 모바일 식단 입력 → 피드백 도착 종단 지연 (사진 OCR 포함): p50 ≤ 4초 / p95 ≤ 8초
- **NFR-P2.** 모바일 식단 입력 → 피드백 도착 (텍스트 only): p50 ≤ 2.5초 / p95 ≤ 5초
- **NFR-P3.** 스트리밍 첫 토큰 도착(TTFT): p50 ≤ 1.5초 / p95 ≤ 3초
- **NFR-P4.** LangGraph 6노드 단일 호출(Self-RAG 미발동): 평균 ≤ 3초
- **NFR-P5.** LangGraph + Self-RAG 1회 재검색 추가 지연: + ≤ 2초
- **NFR-P6.** 음식 RAG pgvector 검색 응답 (캐시 miss): p95 ≤ 200ms
- **NFR-P7.** 음식 RAG 캐시 hit 응답: p95 ≤ 30ms
- **NFR-P8.** Web 주간 리포트 7일 데이터 초기 로딩: ≤ 1.5초
- **NFR-P9.** Web 관리자 사용자 검색 (1만 건 가정): ≤ 1초
- **NFR-P10.** API endpoint p95 응답 시간 (분석 외): ≤ 500ms

**Security**

- **NFR-S1.** 모든 통신 TLS 1.2+ 강제 + HSTS + HTTP 308 redirect
- **NFR-S2.** JWT access 30일 / refresh 90일. 모바일 Secure storage(Keychain/Keystore), 웹 httpOnly Secure 쿠키
- **NFR-S3.** 사용자 비밀번호 자체 저장 없음(Google OAuth 단독)
- **NFR-S4.** Rate limit: 사용자별 분당 60 / 시간당 1,000. LangGraph 분당 10. 초과 HTTP 429
- **NFR-S5.** 민감정보(체중·신장·알레르기·식단 raw_text) 로그·Sentry·전송 페이로드 모두 마스킹 (Sentry beforeSend hook)
- **NFR-S6.** Postgres at-rest 암호화 — Railway 표준 디스크 암호화 의존 (컬럼 단위 추가 암호화 Growth)
- **NFR-S7.** Admin role JWT 별 secret + 짧은 만료(8시간) + audit log 자동 기록(FR37)
- **NFR-S8.** 관리자 화면 IP 화이트리스트 — 외주 클라이언트별 옵션(MVP 강제 X)
- **NFR-S9.** 외부 LLM API 키 환경 변수 + Railway secrets. 코드/로그/git 노출 0
- **NFR-S10.** 외주 인수 시 키 회전 SOP 명문화 — README 1페이지

**Reliability & Availability**

- **NFR-R1.** 가용성 Railway SLA 99.9% (월 다운타임 ≤ 43분). 멀티-AZ X(1인 anti-pattern)
- **NFR-R2.** LLM 듀얼 fallback — OpenAI 실패 시 Anthropic 자동 전환. 양쪽 실패 시 안내
- **NFR-R3.** Structured Output 파싱 실패 시 Pydantic 검증 + retry 1회 + error edge fallback. 노드 isolation
- **NFR-R4.** DB 다운 시 503 + 안내. 단순 일별 기록 조회는 모바일 로컬 캐시(7일치) 읽기 전용
- **NFR-R5.** 백업: Postgres 일별 7일 보존(Railway 표준)
- **NFR-R6.** Sentry 노드 실패·외부 API 실패·DB 에러 자동 알림. 일별 비용 임계치 알림

**Scalability**

- **NFR-Sc1.** MVP baseline: 동시 100명 / DAU 1,000명까지 단일 Railway 노드 + 단일 Postgres + Redis로 처리
- **NFR-Sc2.** Web 트래픽 Vercel CDN 의존
- **NFR-Sc3.** 외주 인수 후 10배 성장 시 Railway scale-up + Postgres replica + Redis cluster 마이그레이션 가이드 README 명시
- **NFR-Sc4.** LLM 비용 보호 — Redis 캐시 + rate limit + 일별 임계치 초과 시 알림 + 자동 차단

**Accessibility (baseline — 풀 WCAG AA는 외주 클라이언트별 강화)**

- **NFR-A1.** 모바일 스크린리더(VoiceOver/TalkBack) 호환 — 모든 인터랙티브 요소에 accessibility label
- **NFR-A2.** 색상 대비 본문 4.5:1, 큰 텍스트 3:1 (WCAG AA 기준). 디자인 토큰에 통과 색상만
- **NFR-A3.** 폰트 스케일 시스템 폰트 크기 변경 반응. 최소 12pt + 200% 확대 깨지지 않음
- **NFR-A4.** 색상 단독 정보 전달 금지 — fit_score는 색상 + 숫자 + 텍스트 라벨 동시 표시
- **NFR-A5.** Web 키보드 내비게이션(Tab 순서 자연). 차트 데이터 테이블 fallback

**User Experience & Coaching Voice**

- **NFR-UX1.** Coaching Tone — 긍정·동기부여 + 행동심리 코칭 톤 (Noom-style). 비난·낙담·도덕적 판단 표현 금지
- **NFR-UX2.** 행동 제안형 마무리 강제 — 모든 피드백은 *현재 평가* + *다음 행동 제안* 두 부분. 부재 시 후처리 재생성
- **NFR-UX3.** 수치는 보조 카드 — 단순 매크로 수치는 채팅 본문이 아닌 별도 데이터 카드(접힘 가능)
- **NFR-UX4.** 의학 어휘 회피 — "치료/처방/진단/예방/완화" 금지 → "관리/안내/참고/도움이 될 수 있는"
- **NFR-UX5.** 한국 문화 맥락 — 시스템 프롬프트에 한국 식사 패턴(아침-점심-저녁 비중 25/35/30, 회식·외식) 컨텍스트 주입
- **NFR-UX6.** 디스클레이머와 톤의 균형 — 본문은 자연어 코칭, 푸터는 1줄

**Localization**

- **NFR-L1.** 1차 언어 한국어. 모든 UI·디스클레이머·약관·피드백 한국어
- **NFR-L2.** 영문 보조 — 디스클레이머·약관 풀텍스트 영문판 1세트 (글로벌 데모 / B2B 답변용). UI 영문화 OUT
- **NFR-L3.** 통화·날짜 한국 표준 (KRW 정수 / YYYY-MM-DD / 24시간)
- **NFR-L4.** Out of MVP: 풀 다국어(영문 UI / 일문 / 중문)

**Maintainability & Testability**

- **NFR-M1.** 핵심 경로 Pytest 커버리지 ≥ 70% (T7 KPI). LangGraph 6노드 + fit_score + 알레르기 가드 + 광고 가드 + 핵심 API
- **NFR-M2.** README 5섹션 표준 — Quick start / Architecture / 데이터 모델 / 영업 답변 5종 closing FAQ / AWS·GCP·Azure 마이그레이션 + PG 연동 가이드
- **NFR-M3.** SOP 4종 표준 — 의료기기 미분류 / PIPA 동의서 / 디스클레이머 한·영 / 식약처 광고 가드
- **NFR-M4.** Swagger/OpenAPI 자동 생성 + 모든 endpoint 요청·응답 스키마 + 에러 코드 명세
- **NFR-M5.** 환경 변수 표준화 — `.env.example`에 모든 필요 변수 + 설명. `.env`는 gitignore
- **NFR-M6.** Docker Compose 로컬 = 컨테이너 (W1부터). 환경 차이 차단
- **NFR-M7.** 외주 클라이언트 신규 개발자 onboarding ≤ 8시간 (B3 KPI)
- **NFR-M8.** 데이터 모델 표준성 — 식약처 영양 키 + KDRIs `health_goal` enum + 22종 알레르기 enum이 갈아끼우기 쉬운 추상 계층 분리

**Compliance & Regulatory**

- **NFR-C1.** 의료기기 미분류 통과 — SOP 1장 + 영업 답변 1페이지 (B1·B4)
- **NFR-C2.** PIPA 2026.03.15 자동화 의사결정 동의 — 별도 동의 UI(FR7) + 미동의 시 분석 차단(FR7) + 동의서 템플릿 (B4)
- **NFR-C3.** 식약처 광고 금지 표현 가드 — T10 KPI(테스트 케이스 ≥ 10건 통과)
- **NFR-C4.** 디스클레이머 한·영 노출 — 온보딩 + 결과 카드 푸터 + 약관 페이지 + 설정 화면 4 위치
- **NFR-C5.** 알레르기 22종 무결성 — W1 시드 시점 식약처 표시기준 별표 검증 + enum 갱신 SOP. fit_score 0점 트리거 검증

**Integration**

- **NFR-I1.** 식약처 OpenAPI 장애 시 통합 자료집 ZIP fallback 또는 USDA FoodData Central 백업
- **NFR-I2.** OpenAI/Anthropic 한쪽 장애 시 다른 한쪽 자동 전환
- **NFR-I3.** OCR(OpenAI Vision) 장애 시 *"사진 인식 일시 장애 — 텍스트로 다시 입력"* 안내 (graceful degradation)
- **NFR-I4.** 결제 sandbox(Toss/Stripe) 장애는 영업 데모 외 영향 미미

### Additional Requirements

**Starter Templates & Bootstrap (W1 day1 — Story 1.1)**

- `pnpm create next-app@latest web --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --turbopack` (Next.js 16.2.4)
- `npx create-expo-app@latest mobile --template default` (Expo SDK 54)
- `/api` — 수동 minimal scaffold via `uv init --python 3.13` + 의존성 설치 (FastAPI / LangGraph 1.1.9 / langchain-openai / langchain-anthropic / SQLAlchemy 2.0.49 async / asyncpg / pgvector / pydantic-settings / redis / httpx / tenacity / sentry-sdk / python-jose / passlib / slowapi / apscheduler / langgraph-checkpoint-postgres / sse-starlette)
- 단일 repo + multi-folder (`/mobile`, `/web`, `/api`, `/docker`, `/scripts`, `/docs`, `/.github/workflows`) — 워크스페이스 X (외주 인수 마찰 회피)

**Infrastructure & Database**

- PostgreSQL 17 + `pgvector/pgvector:pg17` 이미지 (HNSW 인덱스 0.8.2)
- 단일 `public` schema (앱 데이터) + 별 `lg_checkpoints` schema (LangGraph AsyncPostgresSaver)
- Alembic autogenerate + 수동 review + main 머지 시 `alembic upgrade head` 자동 실행
- Redis (rate limit + 캐시) — 키 네임스페이스: `cache:llm:*` (24h), `cache:food:*` (7d), `cache:user:*` (1h), `cache:rl:*`
- Cloudflare R2 (이미지 — presigned URL write, CDN public read)
- Docker Compose 1-cmd 부팅 — postgres + redis + api + seed (one-shot) + healthcheck + dependency wait

**Data Models (한국 표준 통합 — 차별화 카드 #3)**

- `food_nutrition.nutrition` jsonb — 식약처 OpenAPI 응답 키 그대로 (`energy_kcal`, `carbohydrate_g`, `protein_g`, `fat_g`, `sugar_g`, `sodium_mg` 등)
- `food_nutrition.embedding vector(1536)` HNSW + `knowledge_chunks.embedding vector(1536)` HNSW (별 인덱스로 튜닝 자유)
- `users.allergies text[]` + DB CHECK 제약(식약처 22종 enum)
- `users.health_goal` Postgres ENUM (4종)
- `food_aliases (alias, canonical_name)` — 음식명 정규화 사전 + DB 시드 + runtime 갱신
- `knowledge_chunks` 메타데이터: `source`, `authority_grade` (식약처/복지부/대비/대당/질병관리청), `topic`, `applicable_health_goals text[]`, `published_year`
- KDRIs AMDR 매크로 룰 — `health_goal` enum별 lookup table
- Soft delete — `users.deleted_at` 마킹 → 30일 grace → 물리 파기 cron

**LangGraph 6노드 + Self-RAG**

- 노드: `parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → (분기) `rewrite_query` 재검색 / `needs_clarification` 사용자 재질문 → `fetch_user_profile` → `evaluate_fit` (Claude 보조) → `generate_feedback` (스트리밍 + 인용 + 가드)
- 모든 노드 출력 Pydantic 모델 검증 + tenacity retry 1회 + error edge fallback (노드 isolation)
- LangGraph state 영속성 — `langgraph-checkpoint-postgres` AsyncPostgresSaver (`lg_checkpoints` schema)
- 듀얼-LLM router (`llm_router.py`) — OpenAI GPT-4o-mini 메인 + Anthropic Claude 보조 + fallback (NFR-R2)

**RAG Seeds**

- 음식 영양 DB ≥ 1,500-3,000건 (식약처 식품영양성분 DB OpenAPI 시드, 한식 우선) — `scripts/seed_food_db.py`
- 가이드라인 미니 지식베이스 ≥ 50-100 chunks — KDRIs 2020 + 대한비만학회 9판 + 대한당뇨병학회 매크로 + 질병관리청 표준 — `scripts/seed_guidelines.py`
- Chunking 모듈 재사용 (`/api/app/rag/chunking/{pdf,html,markdown}.py`) — 외주 인수 시 클라이언트 PDF 자동 시드 인터페이스 제공

**API & Communication Patterns**

- REST + JSON, URL path `/v1/*`, snake_case 양방향 wire format
- 에러 표준 RFC 7807 Problem Details (`application/problem+json`)
- SSE 프로토콜 `sse-starlette` `EventSourceResponse` — 이벤트 타입 `token` / `citation` / `done` / `error` (종료는 `done` 또는 `error` 1회)
- SSE polling fallback — RN 끊김 ≥ 임계 시 1.5초 polling 자동 강등 (헤더 `X-Stream-Mode: sse|polling`). W4 day1 spike 결정
- OpenAPI 클라이언트 자동 생성 — `openapi-typescript` (`pnpm gen:api` 스크립트, `gen_openapi_clients.sh`) — web/mobile 공용
- Idempotency — 결제 webhook + 식단 입력에 `Idempotency-Key` 헤더
- CORS — Web 도메인만 명시 화이트리스트
- Cursor-based pagination (offset 미사용)
- ISO 8601 UTC + Z 날짜 / KRW integer / boolean true·false / Pydantic Optional은 null (응답 키 누락 금지)

**Security & Auth**

- Google OAuth Authorization Code (백엔드 token 교환). 모바일 `expo-auth-session` / Web 백엔드 redirect
- JWT 분리: user (HS256, access 30일/refresh 90일) ↔ admin (HS256, access 8시간, refresh 없음, 별 secret + 별 issuer claim)
- Token 저장: 모바일 `expo-secure-store`, Web httpOnly + Secure + SameSite=Strict 쿠키
- PIPA 동의 게이트 — `app/api/deps.py:require_consent` Dependency가 `evaluate_fit`/`generate_feedback` 진입 차단 → LLM 비용 0 보호
- Audit log — `Depends(audit_admin_action)` admin 라우터에 일괄 + `audit_admin_action` ↔ `admin_user_jwt_required` 자동 연쇄
- 민감정보 마스킹 — Sentry `before_send` hook + structlog processor (양 출력 스트림 동일 적용)
- Rate limit — `slowapi` + Redis backend, 3-tier (분당/시간당/LangGraph 별도) 슬라이딩 윈도우, 429 + `Retry-After`
- Secrets — Railway secrets (prod/staging) + `.env.local` (gitignored, dev). `.env.example` 커밋. 키 회전 SOP

**Operations & Observability**

- Sentry SDK (Python + RN + Next.js) — LangGraph 노드 transaction tracing (노드 단위 span)
- structlog JSON 로깅 (필수 필드: `timestamp/level/request_id/user_id(masked)/event/module/version`) + 마스킹 processor 동일 적용
- 일별 비용 cron — GitHub Actions cron (매일 09:00 KST) — OpenAI/Anthropic Usage API + Railway billing → Slack/Discord webhook + Sentry custom event (`daily-cost-alert.yml`)
- Healthcheck endpoints — `/healthz` (liveness, DB ping) + `/readyz` (readiness, DB+Redis+pgvector index)
- 백업 — Railway Postgres 일별 7일. 회원 탈퇴 grace 30일 데이터는 별 dump bucket (R2) 후 파기

**CI Gate (PR 시 자동 차단)**

- GitHub Actions `ci.yml` — ① ruff lint+format ② mypy(api) ③ pytest + coverage ≥ 70% ④ tsc --noEmit (web/mobile) ⑤ openapi schema diff 게이트 ⑥ Alembic dry-run을 PR 코멘트
- Pre-commit hooks — ruff + eslint + tsc --noEmit
- main 머지 시 Vercel(Web) + Railway(API) 자동 배포

**Cron Scheduling — APScheduler (in-process)**

- `app/workers/scheduler.py` — `AsyncIOScheduler` instance + FastAPI lifespan에 시작/종료
- Jobs: `nudge_scheduler.py` (매일 19:30/20:30 KST 미기록 푸시) + `soft_delete_purge.py` (30일 grace 만료 시 물리 파기)
- 1인 8주 정합 — 별 외부 cron 무필요

**Compliance Workflow Artifacts (docs/)**

- SOP 4종 — `01-medical-device-classification.md` / `02-pipa-automated-decision-consent.md` / `03-disclaimer-ko-en.md` / `04-fda-style-ad-expression-guard.md`
- FAQ 5종 (영업 답변 closing) — `01-differentiation` / `02-medical-device` / `03-customization` / `04-feasibility-8-weeks` / `05-maintenance`
- Runbook 3종 — `deployment.md` / `secret-rotation.md` / `incident-response.md`
- 22종 갱신 검증 SOP — `scripts/verify_allergy_22.py` (분기 1회 식약처 별표 PDF 검증)

**Demo & Sales Material (W8)**

- 9포인트 데모 시나리오 영상 5종 (병원 / 보험 / 식품 / 스타트업 / 제약 페르소나별, 무편집 1회 촬영 검증)
- 포트폴리오 랜딩 페이지 — 데모 영상 임베드 + SOP 4종 + FAQ 5종 다운로드
- 영업 자료 패키지 — Brief 요약 1페이지 + 차별화 카드 4종 + 데모 영상 5종 + SOP 4종 + FAQ 5종

**Permission UX (FR10 보강)**

- `mobile/lib/permissions.ts` — 권한 상태 hook (`useCameraPermission`, `useMediaLibraryPermission`, `useNotificationPermission`)
- `mobile/features/onboarding/PermissionDeniedView.tsx` — 표준 안내 + `Linking.openSettings()` deep link

### UX Design Requirements

해당 없음. UX 산출물 별도 문서는 사용자 명시 결정에 따라 OUT (PRD/Architecture/Story AC에 흡수). 가시 UX 완성도 8개 항목(로그아웃/회원 탈퇴/온보딩 약관/디스클레이머 강화/설정 화면/알림 설정/프로필 수정/관리자 권한 분리)은 FR1-FR48 안에 명시 포함되어 있어 별도 UX-DR 추출 불필요.

### FR Coverage Map

- **FR1** (Google OAuth + JWT): Epic 1
- **FR2** (건강 프로필 입력 — 나이/체중/신장/활동/`health_goal`/22종 알레르기): Epic 1
- **FR3** (건강 프로필 수정 — 변경 즉시 분석 반영): Epic 5
- **FR4** (모바일·웹 로그아웃): Epic 1
- **FR5** (회원 탈퇴 — PIPA 외 보존 의무 외 즉시 파기): Epic 5
- **FR6** (디스클레이머 + 약관 + 개인정보 동의 PIPA 민감정보 별도 분리 게이트): Epic 1
- **FR7** (자동화 의사결정 동의 + 미동의 시 분석 차단 게이트): Epic 1
- **FR8** (약관/처리방침/디스클레이머 재열람): Epic 1
- **FR9** (자기 데이터 JSON/CSV 다운로드 — PIPA 권리): Epic 5
- **FR10** (권한 거부 시 안내 화면 + 설정 deep link): Epic 2
- **FR11** (분석 카드 푸터 디스클레이머 *"건강 목표 부합도 점수 — 의학적 진단 아님"*): Epic 1 (텍스트·컴포넌트 정립) — Epic 3 적용
- **FR12** (식단 텍스트/사진 입력): Epic 2
- **FR13** (식단 CRUD): Epic 2
- **FR14** (일별 식단·매크로·피드백·fit_score 시간순 화면): Epic 2
- **FR15** (사진 OCR 결과 확인·수정 후 분석 시작): Epic 2
- **FR16** (오프라인 텍스트 큐잉 + 온라인 자동 sync): Epic 2
- **FR17** (다단계 분석 파이프라인 6노드): Epic 3
- **FR18** (검색 신뢰도 미달 시 쿼리 재작성·1회 재검색): Epic 3
- **FR19** (한국식 음식명 변형 통합 매칭): Epic 3
- **FR20** (재검색 후에도 낮으면 사용자 재질문): Epic 3
- **FR21** (0-100 *건강 목표 부합도 점수* 통합 산출): Epic 3
- **FR22** (알레르기 매칭 시 점수 0 + 사유 단락): Epic 3
- **FR23** (한국 1차 출처 인용 자연어 피드백): Epic 3
- **FR24** (모든 권고에 *(출처)* 패턴 + 후처리 검증): Epic 3
- **FR25** (식약처 광고 금지 표현 가드 + 안전 워딩 치환): Epic 3
- **FR26** (모바일 채팅 UI 스트리밍 점진 수신 SSE): Epic 3
- **FR27** (메인 LLM 실패 시 보조 LLM 자동 전환): Epic 3
- **FR28** (온보딩 튜토리얼 디스클레이머 → 약관 → 사용법 2-3 화면 → 프로필): Epic 1
- **FR29** (미기록 nudge 자동 푸시): Epic 4
- **FR30** (알림 ON/OFF + 시간 변경): Epic 4
- **FR31** (푸시 탭 → 식단 입력 화면 직행): Epic 4
- **FR32** (Web 주간 리포트 4종 차트): Epic 4
- **FR33** (인사이트 카드 *"다음 주 권장 매크로 조정"* + 1차 출처 인용): Epic 4
- **FR34** (다음 주 매크로/칼로리 목표 조정 → nudge·권장 표시 자동 반영): Epic 4
- **FR35** (admin role 분리 인증): Epic 7
- **FR36** (관리자 사용자 검색·식단·피드백·프로필 수정): Epic 7
- **FR37** (관리자 모든 액션 audit log 자동 기록 — 시점·액터·액션·대상): Epic 7
- **FR38** (관리자 self-audit 화면): Epic 7
- **FR39** (사용자 데이터 기본 마스킹 + *원문 보기* 액션 시 해제): Epic 7
- **FR40** (정기결제 1플랜 sandbox 신청·해지): Epic 6
- **FR41** (영수증·이용내역 조회): Epic 6
- **FR42** (결제 webhook 수신 + 구독 상태 갱신 + 이력 기록): Epic 6
- **FR43** (LLM 응답 + 음식 검색 캐시): Epic 1 (Redis 인프라) → Epic 8 (정교화)
- **FR44** (사용자별 + LangGraph 별도 호출 횟수 제한): Epic 1 (slowapi 셋업) → Epic 8 (정교화)
- **FR45** (Sentry 자동 수집 + 민감정보 마스킹): Epic 1 (SDK + before_send) → Epic 8 (정교화)
- **FR46** (OpenAPI 명세 — 인수인계 가능): Epic 1 (FastAPI 자동) → Epic 8 (정리·예시·에러 명세)
- **FR47** (Docker 1-cmd 컨테이너 부팅 일괄 시작): Epic 1 (Story 1.1) → Epic 8 (hardening)
- **FR48** (README + 부팅 명령 → 1일 내 환경 구축 + 자체 데이터 통합): Epic 8
- **FR49** (LangSmith 외부 옵저버빌리티 + 평가 데이터셋 회귀 + 마스킹): Epic 3 (Story 3.8 셋업·통합) → Epic 8 (영업 자료 보드 1포인트, Story 8.6)

49/49 FR 매핑 완료.

## Epic List

### Epic 1: 기반 인프라 + 인증 + 온보딩·동의

사용자가 안전하게 가입하고 약관·개인정보·자동화 의사결정 동의 + 디스클레이머 + 사용법 튜토리얼을 통과한 뒤 건강 프로필을 등록한 상태로 핵심 기능에 진입할 수 있다. PIPA 동의 게이트가 본 epic에서 박혀 Epic 3 분석 호출 전 차단되어 LLM 비용 0 보호가 작동한다. Story 1.1은 Architecture 명시 부트스트랩(Docker Compose + Postgres+pgvector + Redis + FastAPI/Web/Mobile init + Sentry + slowapi + CI 게이트). Cross-cutting 인프라(캐시·rate limit·Sentry·Swagger·Docker)를 본 epic에서 셋업하고 Epic 8에서 정교화한다.

**FRs covered:** FR1, FR2, FR4, FR6, FR7, FR8, FR11, FR28, FR43, FR44, FR45, FR46, FR47

### Epic 2: 식단 입력 + 일별 기록 + 권한 흐름

사용자가 모바일에서 식단을 텍스트 또는 사진으로 기록하고 일별 이력(식사 + 매크로 + 피드백 요약 + fit_score)을 시간순으로 조회·수정·삭제하며, 카메라·사진첩 권한 거부 시에도 빈 화면이 아닌 상황별 안내와 설정 deep link를 받는다. OCR(OpenAI Vision)이 항목 추출 후 사용자 확인을 거치며, 오프라인 텍스트 입력은 큐잉되어 온라인 복귀 시 자동 sync된다. AI 분석 트리거는 Epic 3에서 결합되지만 본 epic의 식단 기록 자체는 분석 없이도 standalone 동작한다. 권한 거부 안내 표준 컴포넌트(`PermissionDeniedView.tsx`)는 본 epic에서 정립되어 Epic 4 푸시 권한 흐름에서도 재사용된다.

**FRs covered:** FR10, FR12, FR13, FR14, FR15, FR16

### Epic 3: AI 영양 분석 (Self-RAG + 인용 피드백)

시스템이 입력된 식사를 LangGraph 6노드(`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → `fetch_user_profile` → `evaluate_fit` → `generate_feedback`)로 분석하고, 한국 1차 출처(KDRIs/대비/대당/식약처) 인용 + 식약처 광고 표현 가드 + 듀얼-LLM(OpenAI 메인 + Claude 보조) fallback이 적용된 자연어 피드백을 모바일 채팅 UI에 SSE 스트리밍으로 제공한다. 검색 신뢰도가 임계값 미달일 때는 Self-RAG 쿼리 재작성 + 1회 재검색을 수행하고, 그래도 모호하면 *"이게 ◯◯이 맞나요?"* 형태로 사용자에게 재질문한다. fit_score(Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15)는 알레르기 위반 발견 시 즉시 0점으로 단락된다. 본 epic 끝(W3)에 LangSmith 외부 옵저버빌리티가 통합되어 6노드·LLM·RAG 호출이 마스킹된 트레이스로 자동 캡처되고 한식 100건 평가 데이터셋이 회귀 평가용으로 업로드된다.

**FRs covered:** FR17, FR18, FR19, FR20, FR21, FR22, FR23, FR24, FR25, FR26, FR27, FR49

### Epic 4: 알림(nudge) + Web 주간 리포트

사용자가 식단 미기록 시 설정한 시간 + 30분 후 푸시 nudge를 받아 탭하면 식단 입력 화면으로 직행하고, 알림을 ON/OFF로 토글하거나 시간을 변경할 수 있다. Web에서 주간 리포트 4종 차트(매크로 비율 / 칼로리 vs TDEE / 단백질 g/kg / 알레르기 노출)와 한국 1차 출처 인용 *"다음 주 권장 매크로 조정"* 인사이트 카드를 통해 다음 주 매크로/칼로리 목표를 조정하면 nudge 룰과 모바일 권장 표시에 자동 반영된다. APScheduler in-process 스케줄러로 매일 19:30/20:30 KST 잡 등록.

**FRs covered:** FR29, FR30, FR31, FR32, FR33, FR34

### Epic 5: 계정 관리 + PIPA 권리 (프로필 수정·탈퇴·내보내기)

사용자가 자기 건강 프로필을 언제든 수정하고(변경은 이후 모든 분석에 즉시 반영), 회원 탈퇴 시 모든 데이터가 30일 grace 후 물리 파기되며, 자기 식단·피드백·프로필을 표준 형식(JSON 또는 CSV)으로 다운로드한다. Soft delete(`users.deleted_at`) 마킹 → 30일 grace → `soft_delete_purge.py` worker 물리 파기. 모바일 + Web 양쪽 화면 제공.

**FRs covered:** FR3, FR5, FR9

### Epic 6: 결제/구독 sandbox

사용자가 정기결제 1플랜을 sandbox 결제 화면에서 신청·해지하고, 자기 영수증·이용내역을 조회하며, 시스템은 결제 webhook을 멱등 처리(`Idempotency-Key`)하여 구독 상태와 결제 이벤트 이력을 갱신한다. Toss Payments(한국 우선) 또는 Stripe(글로벌). PG 본 계약·세금정산은 OUT(README 가이드 1페이지). PRD W7 4-5일 배정.

**FRs covered:** FR40, FR41, FR42

### Epic 7: 관리자 + Audit Trust

관리자가 별 admin role JWT(별 secret + 8시간 만료)로 Web 관리자 화면에 진입해 사용자 검색·식단 이력·피드백 로그 조회·프로필 수정을 수행하고, 모든 조회·수정 액션이 audit log(시점·액터·액션·대상·IP·request_id)에 자동 기록된다. 관리자는 자기 활동 로그를 self-audit으로 직접 본다. 사용자 민감정보(이메일·체중·알레르기 상세)는 기본 마스킹 표시되고, 명시적 *원문 보기* 액션 시에만 해제된다. `Depends(audit_admin_action)` ↔ `admin_user_jwt_required` 자동 연쇄로 admin 토큰 없으면 audit 미발동.

**FRs covered:** FR35, FR36, FR37, FR38, FR39

### Epic 8: 운영·인수인계 패키지 + 영업 자료

외주 클라이언트 개발자가 README + Docker 1-cmd 부팅 명령만으로 8시간 내 로컬 환경을 구축하고 자체 데이터 통합을 시도하며, 영업 발주자는 SOP 4종 + FAQ 5종 + 데모 영상 5종으로 1차 영업 답변(차별화/인허가/적용/8주 가능성/유지보수)을 즉시 받는다. SOP 4종(의료기기 미분류/PIPA 동의서/디스클레이머 한·영/식약처 광고 가드) + FAQ 5종 + Runbook 3종(deployment/secret-rotation/incident-response) + `verify_allergy_22.py` 분기 SOP. 일별 비용 cron(`daily-cost-alert.yml`). 클라우드 배포 hardening(Vercel/Railway/R2 + HSTS). Sentry/Swagger/Rate limit/캐시 정교화. 9포인트 데모 영상 5종(고객사 페르소나별, 무편집 1회 촬영) + 포트폴리오 랜딩 페이지 + 영업 자료 패키지.

**FRs covered:** FR43 (정교화), FR44 (정교화), FR45 (정교화), FR46 (정리·예시·에러 명세), FR47 (hardening), FR48

## Epic 1: 기반 인프라 + 인증 + 온보딩·동의

사용자가 안전하게 가입하고 약관·개인정보·자동화 의사결정 동의 + 디스클레이머 + 사용법 튜토리얼을 통과한 뒤 건강 프로필을 등록한 상태로 핵심 기능에 진입할 수 있다. PIPA 동의 게이트가 본 epic에서 박혀 Epic 3 분석 호출 전 차단되어 LLM 비용 0 보호가 작동한다. Cross-cutting 인프라(캐시·rate limit·Sentry·Swagger·Docker 1-cmd)를 본 epic에서 셋업하고 Epic 8에서 정교화한다.

### Story 1.1: 프로젝트 부트스트랩 (Docker 1-cmd + 풀스택 골격 + CI 게이트)

As a 외주 클라이언트 개발자(인수인계 대상),
I want git clone 후 `docker compose up` 1-cmd로 풀스택 환경(Postgres+pgvector+Redis+FastAPI+seed)이 부팅되고 PR 시 ruff·mypy·pytest·tsc·openapi diff 게이트가 자동 작동하기를,
So that README + 8시간 내 로컬 환경 구축 + 자체 데이터 통합이 가능한 인수인계 가능 산출물의 토대가 박힌다.

**Acceptance Criteria:**

**Given** 빈 디렉토리 + 본 repo clone, **When** `docker compose up`, **Then** Postgres 17 + pgvector 0.8.2 + Redis + FastAPI(`localhost:8000`) + seed one-shot 컨테이너가 일괄 부팅되며 healthcheck 통과까지 ≤ 10분
**And** Web Next.js 16.2.4(Tailwind + TS + App Router + Turbopack) `pnpm dev` → `localhost:3000` 응답
**And** Mobile Expo SDK 54 `pnpm start` → 빈 라우팅 화면 동작 (Expo Router file-based)
**And** API에 `/healthz`(DB ping) + `/readyz`(DB+Redis+pgvector index) + `/docs`(Swagger) 모두 200
**And** Sentry SDK + structlog + before_send 마스킹 hook + slowapi + Redis backend 초기 셋업 완료
**And** `.env.example`에 모든 필요 변수 + 설명 + 권장 값 기재 + `.env`는 gitignore
**And** GitHub Actions `ci.yml` PR 게이트 — ruff lint+format + mypy(api) + pytest + coverage ≥ 70% + tsc --noEmit(web/mobile) + openapi schema diff + Alembic dry-run을 PR 코멘트로 자동 실행 + 실패 시 머지 차단
**And** main 브랜치 머지 시 Vercel(Web) + Railway(API) 자동 배포 + Alembic `upgrade head` 자동 실행
**And** `.gitignore` + `.editorconfig` + 루트 `AGENTS.md` + `web/AGENTS.md`(자동 생성) + `pyproject.toml`(ruff 룰셋) + `.eslintrc.json` 모두 커밋

### Story 1.2: Google OAuth 로그인 + JWT user/admin 분리 + 로그아웃

As a 엔드유저,
I want Google 계정으로 모바일·웹 양쪽에 가입·로그인하고 어디서나 로그아웃하기를,
So that 비밀번호 별도 관리 없이 안전하게 진입하고 종료할 수 있다.

**Acceptance Criteria:**

**Given** Google Workspace 계정, **When** 모바일 또는 Web에서 *Google로 계속하기* 탭, **Then** Authorization Code flow로 백엔드가 id_token 검증 → 자체 user JWT(HS256, access 30일/refresh 90일) 발급
**And** 모바일은 `expo-secure-store`(Keychain/Keystore) 저장, Web은 httpOnly + Secure + SameSite=Strict 쿠키 저장
**And** admin role 매핑된 사용자에 대해 별 secret + 별 issuer claim의 admin JWT(access 8시간, refresh 없음) 분리 발급 — 일반 user JWT와 혼용 차단
**And** 401 수신 시 클라이언트 인터셉터가 refresh 토큰 1회 재발급 시도 → 실패 시 로컬 토큰 클리어 + 로그인 화면 라우팅
**And** *로그아웃* 액션 시 `/v1/auth/logout` 호출 + 로컬 secure store / 쿠키 클리어 + 로그인 화면 라우팅
**And** 로그아웃 후 보호된 라우트 진입 시도 시 자동 로그인 화면 redirect

### Story 1.3: 약관·개인정보 동의(PIPA 민감정보 별도) + 디스클레이머 한·영 4-surface

As a 엔드유저,
I want 첫 진입 시 디스클레이머 + 약관 동의 + 개인정보 동의(민감정보 별도)를 통과하고 앱·웹 어디서나 다시 열람하기를,
So that 의료기기 미분류 + PIPA 민감정보 처리 의무를 충족한 상태로 핵심 기능에 진입하고 권리 행사 시 텍스트를 재확인할 수 있다.

**Acceptance Criteria:**

**Given** 신규 사용자 첫 진입, **When** 약관 동의 화면 진입, **Then** 표준 디스클레이머 한국어 풀텍스트(research 3.4) + 약관 + 개인정보 처리방침이 *각각 별도 동의*로 표시되며 PIPA 민감정보(체중·신장·알레르기·식사 기록)는 *별도 분리* 동의 항목으로 노출
**And** 동의 미통과 시 핵심 기능 진입 차단 + 동의 화면으로 강제 라우팅
**And** 동의 통과 시 `consents` 테이블에 동의 항목·시점·버전 기록
**And** `DisclaimerFooter` 컴포넌트가 *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 1줄을 모든 분석 결과 카드 푸터에 노출 (Epic 3 사용)
**And** 모바일 설정 → *디스클레이머 보기* 또는 Web `/legal/disclaimer`에서 한국어 풀텍스트 재열람 가능
**And** Web `/en/legal/{disclaimer,terms,privacy}` 라우트에서 영문 풀텍스트 표시 (글로벌 데모용, NFR-L2)
**And** `GET /v1/legal/{disclaimer,terms,privacy}` 엔드포인트로 한·영 텍스트 조회 가능 (FR8)

### Story 1.4: 자동화 의사결정 동의 + PIPA 게이트 dependency

As a 엔드유저,
I want PIPA 2026.03.15 자동화 의사결정 동의를 별도로 수행하기를,
So that 미동의 시 시스템이 자동 분석 호출을 차단하고 안내 화면을 노출함으로써 LLM 비용·법적 의무를 모두 보호받는다.

**Acceptance Criteria:**

**Given** 신규 또는 기존 사용자, **When** 자동화 의사결정 동의 화면 진입, **Then** 처리 항목·이용 목적·보관 기간·제3자 제공(없음)·LLM 외부 처리(OpenAI/Anthropic) 5섹션 명세 + *자동화 의사결정 동의* 별도 체크 노출
**And** 동의 시 `consents.automated_decision_consent_at` + 동의서 버전 기록
**And** `Depends(require_automated_decision_consent)` dependency가 `/v1/analysis/stream` 등 분석 라우터에 적용 → 미동의 사용자가 호출 시 RFC 7807 응답(`type=consent-required`, `code=consent.automated_decision.missing`, status 403) + 모바일/Web 안내 화면 노출
**And** 미동의 사용자가 식단 입력 후 분석 시도 시 LangGraph 호출 *전*에 차단되어 LLM 비용 0
**And** 사용자가 설정에서 동의 철회 액션 시 즉시 분석 차단 + `consents.automated_decision_revoked_at` 기록

### Story 1.5: 건강 프로필 입력 (나이/체중/신장/활동/health_goal/22종 알레르기)

As a 엔드유저,
I want 나이·체중·신장·활동 수준·`health_goal` 4종 중 1개·식약처 22종 알레르기 다중 선택을 입력하기를,
So that 시스템이 BMR/TDEE 계산과 알레르기 가드의 기반이 되는 내 건강 프로필을 갖게 된다.

**Acceptance Criteria:**

**Given** 동의 통과 + 미입력 사용자, **When** 건강 프로필 입력 화면 진입, **Then** 나이(정수) / 체중(kg, 0.1 단위) / 신장(cm, 정수) / 활동 수준(Sedentary/Light/Moderate/Active/Very Active enum) / `health_goal`(4종 single select) / 식약처 22종 알레르기(다중 select) 폼 노출
**And** `react-hook-form` + `zod` 검증으로 잘못된 값(예: 음수 체중) inline 에러 메시지
**And** 22종 알레르기 옵션은 `domain/allergens.py` 식약처 별표 22종 enum과 1:1 매핑 + DB CHECK 제약으로 무결성 보장
**And** `POST /v1/users/me/profile` 호출 시 `users` 테이블 저장 + `health_goal`은 Postgres ENUM 컬럼 + 22종은 `text[]` + CHECK
**And** 활동 수준·`health_goal` 선택은 색상 + 텍스트 라벨 동시 표시 (NFR-A4 색약 대응)
**And** 폰트 스케일 200%(NFR-A3)에서도 폼 레이아웃 깨지지 않음 + 모든 입력 가능

### Story 1.6: 온보딩 튜토리얼 (디스클레이머 → 약관 → 사용법 → 프로필)

As a 엔드유저,
I want 첫 사용 시 디스클레이머 → 약관·개인정보 동의 → 사용법 안내(2-3 화면) → 건강 프로필 입력의 순차 흐름을 통과하기를,
So that 첫 사용 시 멈춤 없이 핵심 기능에 진입할 수 있다.

**Acceptance Criteria:**

**Given** 신규 사용자 Google 로그인 직후, **When** 모바일 진입, **Then** 라우터가 `/onboarding/disclaimer` → `/terms` → `/privacy` → `/automated-decision` → `/tutorial` → `/profile` 순차 진행
**And** 사용법 튜토리얼 2-3 화면(*"사진 한 장으로 식단 분석"* / *"한국 1차 출처 인용 피드백"* / *"디스클레이머 — 의학적 진단 아님"*) 노출 + *건너뛰기* 옵션 (단 동의·프로필은 강제)
**And** 프로필 입력 완료 시 `(tabs)/meals` 라우팅 + `users.onboarded_at` 기록
**And** 기존 사용자(`onboarded_at` 있음) 재로그인 시 온보딩 스킵 → 바로 `(tabs)/meals` 진입
**And** 온보딩 중 앱 종료 후 재시작 시 마지막 통과 화면으로 복귀 (Expo Router state 보존)

## Epic 2: 식단 입력 + 일별 기록 + 권한 흐름

사용자가 모바일에서 식단을 텍스트/사진으로 기록하고 일별 이력을 시간순으로 조회·수정·삭제하며, 카메라·사진첩 권한 거부 시에도 빈 화면이 아닌 안내를 받는다. OCR(OpenAI Vision)이 항목 추출 후 사용자 확인을 거치며, 오프라인 텍스트 입력은 큐잉 후 자동 sync된다. AI 분석 트리거는 Epic 3에서 결합되지만 본 epic은 standalone 동작.

### Story 2.1: 식단 텍스트 입력 + CRUD

As a 엔드유저,
I want 모바일에서 식단을 텍스트로 입력하고 조회·수정·삭제하기를,
So that 사진을 찍지 않아도 빠르게 한 끼를 기록할 수 있다.

**Acceptance Criteria:**

**Given** 동의 + 프로필 완료된 사용자, **When** `(tabs)/meals/input`에서 텍스트(예: *"삼겹살 1인분, 김치찌개, 소주 2잔"*) 입력 + 저장, **Then** `POST /v1/meals` → `meals` 테이블 저장 + `(tabs)/meals/index` 일별 기록에 즉시 표시
**And** 기존 식단 카드 탭 → 수정 시 `PATCH /v1/meals/{meal_id}`로 raw_text 갱신 + 분석 결과는 invalidate 표시(*"수정됨 — 다시 분석 가능"*)
**And** 삭제 액션 + 사용자 확인 시 `DELETE /v1/meals/{meal_id}` + soft delete(`meals.deleted_at`) + 일별 기록에서 제거
**And** 빈 일별 기록 시 표준 빈 화면 *"기록 없음 — 첫 식단을 입력하세요"* + CTA 노출
**And** 네트워크 에러 시 표준 에러 화면(*"오류 — 다시 시도"*) + retry 버튼

### Story 2.2: 식단 사진 입력 + 카메라/사진첩 권한 흐름 + 거부 안내

As a 엔드유저,
I want 식단을 사진으로 촬영하거나 갤러리에서 선택해 업로드하고, 권한 거부 시에도 빈 화면이 아닌 안내를 받기를,
So that 손쉬운 시각 기록 + 권한 거부 후에도 서비스가 막히지 않는 완성도를 경험한다.

**Acceptance Criteria:**

**Given** 식단 입력 화면, **When** 사용자가 *카메라* 탭, **Then** `mobile/lib/permissions.ts`의 `useCameraPermission` hook이 권한 요청 → 허용 시 카메라 → 촬영 → R2 presigned URL upload → `meals.image_key` 저장
**And** 사용자가 *갤러리* 탭 시 `useMediaLibraryPermission` 권한 요청 후 허용 시 사진첩에서 1장 선택 → R2 업로드
**And** 카메라 권한 거부 시 `PermissionDeniedView` 표준 컴포넌트가 *"카메라가 필요해요 — 설정에서 허용하면 사진 촬영이 가능합니다"* + `Linking.openSettings()` deep link + *"갤러리 선택"* fallback CTA
**And** 사진첩 권한 거부 시 동일 패턴 + *"카메라 촬영"* 또는 *"텍스트 입력"* fallback CTA
**And** R2 업로드 시 백엔드 presigned URL write + read는 CDN 직접(인증 토큰 불필요한 public read)
**And** R2 업로드 실패 시 *"이미지 업로드 실패 — 다시 시도"* + Sentry 자동 수집

### Story 2.3: OCR Vision 추출 + 사용자 확인·수정 카드

As a 엔드유저,
I want 사진 업로드 직후 시스템이 OCR로 추출한 음식 항목을 확인·수정하고 분석을 시작하기를,
So that 잘못 인식된 항목을 미리 바로잡아 분석 정확도가 떨어지지 않는다.

**Acceptance Criteria:**

**Given** 사진 업로드 완료, **When** 클라이언트가 `parse_meal` OCR 사전 호출 또는 분석 stream 진입 직전, **Then** OpenAI Vision API 호출 → 음식 항목 + 추정 양 + `confidence` 필드 반환
**And** OCR 결과 *"짜장면 1인분, 군만두 4개 인식됨 — 맞으신가요?"* 확인 카드 노출 — 항목 추가/삭제/양 수정 가능
**And** OCR 신뢰도 임계값(예: 0.6) 미만 시 사용자 확인 카드 강제 노출(자동 진행 차단)
**And** 사용자 확인·수정 후 *분석 시작* 탭 시 `parsed_items`가 Epic 3 LangGraph 입력으로 전달
**And** OpenAI Vision 장애 시 *"사진 인식 일시 장애 — 텍스트로 다시 입력해주세요"* 안내 (NFR-I3 graceful degradation)
**And** OCR 응답 시간 p95 ≤ 4초 (NFR-P1 일부)

### Story 2.4: 일별 식단 기록 화면 (시간순)

As a 엔드유저,
I want 일별 식단 기록을 한 화면에서 시간순으로 보기를,
So that 오늘의 식사·매크로·피드백 요약·fit_score를 한눈에 확인하고 다음 끼를 결정할 수 있다.

**Acceptance Criteria:**

**Given** `(tabs)/meals/index` 진입, **When** 사용자가 날짜 선택(기본 오늘), **Then** 해당일 모든 식단이 시간(아침→저녁)순 카드 리스트 표시
**And** 식단 카드는 식사 텍스트 또는 사진 썸네일 + 매크로 요약(탄/단/지 g) + 피드백 요약 1줄 + fit_score(색상 + 숫자 + 텍스트 라벨, NFR-A4) 노출
**And** 카드 탭 시 `(tabs)/meals/[meal_id].tsx` 채팅 SSE 화면(Epic 3) 이동
**And** 데이터 없음 시 표준 빈 화면 *"오늘 기록 없음 — 첫 식단을 입력하세요"* CTA
**And** 7일치 로컬 캐시 보유 시 오프라인에서 마지막 7일은 읽기 전용 표시 (NFR-R4 + FR16 정합)
**And** 폰트 스케일 200%(NFR-A3)에서 카드 레이아웃 깨지지 않음

### Story 2.5: 오프라인 텍스트 큐잉 + 온라인 자동 sync

As a 엔드유저,
I want 오프라인 상태에서 텍스트로 식단을 입력하면 큐잉되어 온라인 복귀 시 자동 sync되기를,
So that 회식·이동·약한 신호 환경에서도 기록이 끊기지 않는다.

**Acceptance Criteria:**

**Given** 오프라인 상태, **When** 텍스트 식단 입력 + 저장, **Then** `mobile/lib/offline-queue.ts`가 AsyncStorage 큐에 저장 + UI에 *"동기화 대기 중"* 배지 표시
**And** 네트워크 복귀 감지 시 큐를 순차 flush → `POST /v1/meals` → 성공 시 큐에서 제거 + 배지 해제
**And** sync 실패(서버 에러) 시 큐 잔존 + 지수 backoff 재시도 정책 3회
**And** 사진 입력은 오프라인 큐잉 대상 아님 — 오프라인에서 사진 시도 시 *"사진은 온라인에서 처리 가능 — 텍스트 입력 또는 온라인 시 다시 시도"* 안내
**And** 같은 항목 sync 중복 방지 — `Idempotency-Key`(client-generated UUID) 헤더로 멱등 처리

## Epic 3: AI 영양 분석 (Self-RAG + 인용 피드백)

시스템이 입력 식사를 LangGraph 6노드 + Self-RAG 재검색·재질문 + 듀얼-LLM fallback + 한국 1차 출처 인용 + 광고 표현 가드를 통해 SSE 스트리밍 채팅으로 분석한다. fit_score는 알레르기 위반 시 즉시 0점 단락. 영업 차별화 카드(한국 1차 출처 RAG / Self-RAG / 듀얼-LLM / 인용형 피드백)가 본 epic에서 코드 위치로 박힘. 마지막 W3 슬롯(Story 3.8)에 LangSmith 외부 옵저버빌리티 + 한식 100건 평가 데이터셋이 통합되어 *"LLM 동작을 추적·평가할 수 있다"* 운영 카드가 영업 자료(Story 8.6)로 연결된다.

### Story 3.1: 음식 영양 RAG 시드 + food_aliases 정규화 사전 + pgvector HNSW

As a 1인 개발자(시드 작업) / 외주 인수 클라이언트(시드 표준 활용),
I want 식약처 식품영양성분 DB OpenAPI 기반 1,500-3,000건 한식 우선 음식 영양 데이터를 시드하고 정규화 사전을 구성하기를,
So that LangGraph `retrieve_nutrition` 노드가 식약처 표준 키 jsonb + HNSW 임베딩 검색으로 한국식 음식명 변형(짜장면/자장면)을 통합 매칭할 수 있다.

**Acceptance Criteria:**

**Given** `scripts/seed_food_db.py` 실행, **When** 식약처 OpenAPI 호출, **Then** 한식 우선 1,500-3,000건이 `food_nutrition`에 시드 — `nutrition` jsonb는 식약처 응답 키 그대로 (`energy_kcal`, `carbohydrate_g`, `protein_g`, `fat_g`, `sugar_g`, `sodium_mg` 등)
**And** 식약처 OpenAPI 장애 시 통합 자료집 ZIP fallback 또는 USDA FoodData Central 백업 시드 가능 (NFR-I1, R7)
**And** `food_nutrition.embedding vector(1536)` HNSW 인덱스 생성 + 검색 응답 p95 ≤ 200ms (NFR-P6)
**And** `food_aliases (alias text, canonical_name text)` 테이블 시드 — *짜장면/자장면*, *김치찌개/김치 찌개*, *떡볶이/떡뽁이* 등 핵심 변형 ≥ 50건 + unique 제약
**And** Docker Compose seed one-shot 컨테이너에서 `docker compose up`만으로 자동 시드 (FR47 정합)

### Story 3.2: 가이드라인 RAG 시드 + chunking 모듈

As a 1인 개발자 / 외주 인수 클라이언트,
I want KDRIs 2020 + 대한비만학회 9판 + 대한당뇨병학회 매크로 권고 + 질병관리청 표준을 50-100 chunks로 시드하고 chunking 모듈을 재사용 가능 인터페이스로 구성하기를,
So that `generate_feedback`이 한국 1차 출처를 직접 인용하고 외주 인수 시 클라이언트 PDF 자동 시드가 가능하다.

**Acceptance Criteria:**

**Given** `scripts/seed_guidelines.py` 실행, **When** PDF·HTML 입력, **Then** `app/rag/chunking/{pdf,html,markdown}.py` 재사용 모듈로 chunking → `knowledge_chunks`에 50-100 chunks 시드
**And** 각 chunk 메타데이터 `source` (식약처/복지부/대비/대당/질병관리청) + `authority_grade` + `topic` + `applicable_health_goals text[]` + `published_year` 모두 기록
**And** `knowledge_chunks.embedding vector(1536)` HNSW 인덱스 + `applicable_health_goals` 필터 적용 top-K 검색 가능
**And** chunking 모듈은 인터페이스로 격리 — 외주 인수 클라이언트가 자체 PDF를 동일 모듈로 chunking → 시드 가능 (Vision-stage 자동 파이프라인의 토대; 본 MVP는 수동 1회 호출)
**And** `scripts/verify_allergy_22.py`가 식약처 별표 22종 갱신 검증 SOP를 분기 1회 실행 가능 (R8)

### Story 3.3: LangGraph 6노드 + Self-RAG 분기 + AsyncPostgresSaver

As a 시스템 엔지니어,
I want LangGraph 6노드(`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → `fetch_user_profile` → `evaluate_fit` → `generate_feedback`) + Self-RAG `rewrite_query` 재검색 분기를 AsyncPostgresSaver로 영속화하기를,
So that 재시작·세션 분리에도 분석 흐름이 끊기지 않으며 한 노드 실패가 전체 파이프라인을 멈추지 않는다.

**Acceptance Criteria:**

**Given** `app/graph/pipeline.py`, **When** `StateGraph(MealAnalysisState)` 컴파일, **Then** 6노드 + Self-RAG 분기(`evaluate_retrieval_quality` → `rewrite_query` → `retrieve_nutrition` 재검색, 1회 한도) 정상 컴파일
**And** `langgraph-checkpoint-postgres` AsyncPostgresSaver 셋업 — 같은 PG의 별 schema `lg_checkpoints`에 영속화 (Alembic 외, lib `.setup()` 호출). 본 schema와 격리되어 마이그레이션 충돌 차단
**And** 모든 노드 출력은 Pydantic 모델 검증 — 실패 시 tenacity exponential backoff 1회 retry → 실패 시 error edge fallback (노드별 isolation)
**And** 노드 단위 Sentry transaction tracing — 각 노드 실패 자동 수집 + span 분리
**And** 100회 연속 호출 부하 테스트 시 실패율 ≤ 2% (T1 KPI)
**And** LangGraph 6노드 단일 호출(Self-RAG 미발동) 평균 ≤ 3초 (NFR-P4) + Self-RAG 1회 재검색 추가 ≤ 2초 (NFR-P5)

### Story 3.4: 음식명 정규화 매칭 + 임베딩 fallback + Self-RAG 재질문

As a 시스템 엔지니어,
I want `retrieve_nutrition`이 정규화 사전 1차 매칭 → 임베딩 fallback → 재검색 후에도 신뢰도 미달 시 사용자 재질문을 트리거하기를,
So that "짜장면" / "자장면" / "포케볼" 같은 한국식 변형 + 모호 항목에 대한 환각률을 낮추고 책임 추적성을 높인다.

**Acceptance Criteria:**

**Given** 입력 음식명, **When** `retrieve_nutrition`, **Then** `food_aliases.alias` 1차 lookup → `canonical_name` 정규화 → `food_nutrition` 검색
**And** 정규화 미스 시 `food_nutrition.embedding` HNSW top-3 임베딩 fallback
**And** top-3 매칭 신뢰도(`retrieval_confidence`) 임계값(예: 0.6) 미만 시 `evaluate_retrieval_quality`가 *재검색 분기* → `rewrite_query`(예: "포케볼" → "연어 포케 / 참치 포케 / 베지 포케")로 쿼리 분기 재작성 → 1회 재검색
**And** 재검색 후에도 신뢰도 미달 시 `needs_clarification = True` → SSE 채팅에 *"이게 ◯◯이 맞나요? (1) 연어 (2) 참치 (3) 채소 — 양은 한 그릇(약 400g)인가요?"* 형태 재질문 표시
**And** 사용자 응답 수신 시 AsyncPostgresSaver checkpoint 복귀 → `parse_meal` 갱신 → 재분석 진행
**And** 한식 100건 테스트셋(짜장면/자장면 등 변형 포함)에서 정규화 + 임베딩 + 재질문 결합 정확도 ≥ 90% (T3 KPI)

### Story 3.5: fit_score 알고리즘 + 알레르기 위반 단락

As a 엔드유저(데모 페르소나),
I want 매크로·칼로리·알레르기·균형이 통합된 0-100 *건강 목표 부합도 점수*를 받고, 알레르기 위반 시 즉시 0점으로 단락되기를,
So that 단일 점수로 한 끼의 건강 목표 정합 정도를 직관적으로 파악하고 알레르기 위반은 절대 안전 우선으로 처리받는다.

**Acceptance Criteria:**

**Given** `evaluate_fit` 노드 (Claude 보조 LLM), **When** `domain/fit_score.py` 알고리즘, **Then** Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 0-100 가중 합산
**And** Mifflin-St Jeor BMR + 활동 수준 TDEE 계산 (`domain/bmr.py`) 단위 테스트 ≥ 10건 통과
**And** KDRIs AMDR `health_goal` enum별 매크로 룰 (`domain/kdris.py`) lookup table에서 사용자 목표에 맞는 권장 비율 적용
**And** 알레르기 위반 매칭 발견 (`users.allergies` ∩ `parsed_items` ≠ ∅) 시 즉시 `fit_score = 0` + `fit_reason = "allergen_violation"` + 매크로/칼로리 점수 무시 (단락)
**And** 22종 알레르기 enum (`domain/allergens.py`) + DB CHECK 제약 — 식약처 별표 22종 무결성 (NFR-C5)
**And** 알레르기 위반 케이스 단위 테스트 ≥ 22건(각 알레르기 1건) 100% 통과
**And** fit_score UI 표시는 색상 + 숫자 + 텍스트 라벨 동시 (NFR-A4)

### Story 3.6: 인용형 피드백 + 광고 표현 가드 + 듀얼-LLM router

As a 엔드유저,
I want 피드백 텍스트에 한국 1차 출처(KDRIs / 대비학회 / 대당학회 / 식약처) 인용이 모두 포함되고 식약처 광고 금지 표현(진단·치료·예방·완화)은 자동 필터링되며, 메인 LLM 장애 시 보조 LLM으로 자동 전환되기를,
So that *책임 추적 가능한 권고*가 영업 차별화 카드로 작동하고 단일 LLM 의존 리스크가 제거된다.

**Acceptance Criteria:**

**Given** `generate_feedback` 노드 시스템 프롬프트, **Then** `knowledge_chunks` retrieve 결과의 `source` 메타데이터를 명시 주입(자유 인용 금지) + *(출처: 기관명, 문서명, 연도)* 패턴 강제
**And** 출력 텍스트 후처리 — 인용 패턴 누락 발견 시 정규식 검증 → 재생성 1회 → 실패 시 안전 워딩 자동 치환
**And** 100건 샘플에서 인용 형식 누락 < 1% (T4 KPI)
**And** 광고 금지 표현 가드 (`domain/ad_expression_guard.py`) — 정규식 패턴 매칭(*진단/치료/예방/완화/처방*) → 위반 발견 시 LLM 재생성 1회 또는 안전 워딩 치환(*"관리/안내/참고/도움이 될 수 있는"*)
**And** T10 KPI 테스트 케이스 ≥ 10건(광고 금지 표현 회피) 100% 통과
**And** Coaching Tone(NFR-UX1 Noom-style) + 행동 제안 마무리(NFR-UX2) — 모든 피드백은 *현재 평가* + *다음 행동 제안* 두 부분 강제 + 부재 시 후처리 재생성
**And** `generate_feedback` 시스템 프롬프트에 한국 식사 패턴 컨텍스트(아침-점심-저녁 비중 25/35/30, 회식·외식 빈도, 한국 임상 자료 인용 자연 포함) 주입 강제 (NFR-UX5)
**And** 듀얼-LLM router(`adapters/llm_router.py`) — OpenAI GPT-4o-mini 메인 호출 시 tenacity 3회(1s/2s/4s) backoff → 최종 실패 시 Anthropic Claude 자동 전환 (NFR-R2)
**And** 양쪽 LLM 모두 실패 시 *"AI 서비스 일시 장애 — 잠시 후 다시 시도해주세요"* + Sentry 알림
**And** Redis LLM 응답 캐시(`cache:llm:{sha256(meal_text+profile_hash)}`, 24h TTL) — 동일 입력 재호출 시 캐시 hit + LLM 비용 0 (FR43)

### Story 3.7: 모바일 SSE 스트리밍 채팅 UI + polling fallback + 디스클레이머 푸터

As a 엔드유저,
I want 분석 결과를 모바일 채팅 UI에서 한 글자씩 흐르는 스트리밍으로 받고, 끊김 시 polling으로 자동 강등되며 결과 카드 푸터에 디스클레이머가 노출되기를,
So that 결과를 빠르고 매끄럽게 받으면서 의학적 진단 오해를 막을 수 있다.

**Acceptance Criteria:**

**Given** `(tabs)/meals/[meal_id].tsx`(`ChatStreaming.tsx`), **When** 사용자가 분석 시작, **Then** `react-native-sse`로 `POST /v1/analysis/stream` 연결 → SSE 이벤트 수신
**And** SSE 이벤트 종류 — `event: token`(LLM 델타) / `event: citation`(출처 메타) / `event: done`(`final_fit_score` 등) / `event: error`(RFC 7807) — 각각 UI 처리
**And** `done` 또는 `error` 둘 중 하나 1회 수신 시 클라이언트 연결 종료 (이중 종료 방지)
**And** TTFT(첫 토큰) p50 ≤ 1.5초 / p95 ≤ 3초 (NFR-P3)
**And** 5분 세션 50회 부하 테스트 시 끊김 ≤ 1회 (T5 KPI)
**And** SSE 끊김 ≥ 임계 시 `event: error` 수신 후 1.5초 polling(`/v1/analysis/{id}` GET) 자동 강등 + 헤더 `X-Stream-Mode: polling` 명시 (R2)
**And** 분석 결과 카드 하단에 `DisclaimerFooter`(Story 1.3 컴포넌트)가 *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 1줄 노출 (FR11 적용)
**And** 매크로 수치는 보조 카드(NFR-UX3) — 단순 g/kcal는 채팅 본문이 아닌 별도 데이터 카드(접힘 가능)
**And** 종단 지연(사진 OCR 포함) p50 ≤ 4초 / p95 ≤ 8초 (NFR-P1)

### Story 3.8: LangSmith 외부 옵저버빌리티 통합 + 한식 100건 평가 데이터셋

As a 1인 개발자(운영) / 외주 발주자(영업 카드 검증),
I want LangGraph 6노드 + LLM 호출 + RAG 검색을 LangSmith로 자동 트레이싱하고, 한식 100건 평가 데이터셋으로 회귀 평가를 돌리며, 트레이스 송신 전 민감정보가 마스킹되기를,
So that 프로덕션 LLM 동작·품질·추세를 영업 보드로 입증하면서 PIPA·식약처 컴플라이언스를 깨지 않는다.

**Acceptance Criteria:**

**Given** `api/pyproject.toml`에 `langsmith` 추가, **When** `LANGCHAIN_TRACING_V2=true` + `LANGSMITH_API_KEY` + `LANGSMITH_PROJECT=balancenote-dev|prod` env 설정, **Then** LangGraph 6노드(`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → `rewrite_query` → `fetch_user_profile` → `evaluate_fit` → `generate_feedback`) + Self-RAG 재검색 + LLM 호출 + RAG 검색이 native 자동 트레이싱으로 100% 캡처 (NFR-O1)
**And** `app/core/observability.py:mask_run` hook이 LangSmith client에 부착 — 체중·신장·알레르기·식단 raw_text·user_id를 송신 전 마스킹 (NFR-O2, NFR-S5 룰셋 1지점 재사용)
**And** PR CI에 마스킹 누락 정적 검사 스텝 추가 — 마스킹 대상 키가 trace inputs/outputs에 평문으로 빠지면 fail
**And** `scripts/upload_eval_dataset.py` 실행 시 Story 3.4 한식 100건 테스트셋(짜장면/자장면 변형 포함)이 LangSmith Dataset(`balancenote-korean-foods-v1`)으로 업로드 (NFR-O3)
**And** PR 옵션 스텝 `langsmith evaluate` — 정확도 < 90% 시 PR 코멘트 경고(권장; 자동 머지 차단은 OUT)
**And** `.env.example`에 `LANGSMITH_API_KEY=`, `LANGSMITH_PROJECT=balancenote-dev`, `LANGCHAIN_TRACING_V2=false` 기본값 + 주석 설명. Railway secrets에 prod 키 등록 SOP를 README *"API key 회전 절차"*에 추가 (NFR-S10 결합)
**And** 로컬 개발은 `LANGCHAIN_TRACING_V2=false` 기본 — 개발자 수동 ON. 스테이징/프로덕션은 true 강제
**And** 개인정보처리방침에 *제3자 제공·국외 이전(LangSmith·미국)* 항목 1줄 추가, 마스킹 후 송신으로 PII 0 명시 (NFR-O5)
**And** LangSmith 보드의 공개 read-only 링크 1세트를 `docs/observability/langsmith-dashboard.md`에 기록 — Story 8.6 영업 자료에서 인용
**And** 본 스토리는 W3 Integration 슬롯에서 진행 — Story 3.3(LangGraph 6노드) 완료 후 (`after: bmad-create-epics-and-stories` 흐름상 3.3 먼저), 1인 개발자 추가 비용 ≈ 0.5–1일

## Epic 4: 알림(nudge) + Web 주간 리포트

사용자가 미기록 푸시를 받아 식단 입력 화면으로 직행하고, Web에서 4종 차트 + 인용 인사이트로 다음 주 매크로 목표를 조정하면 nudge 룰과 모바일 권장 표시에 자동 반영된다. APScheduler in-process 스케줄러로 매일 19:30/20:30 KST 잡 등록.

### Story 4.1: 알림 설정 (ON/OFF + 시간 변경) + 푸시 권한 흐름

As a 엔드유저,
I want 푸시 알림을 ON/OFF로 토글하고 알림 시간(기본 저녁 8시)을 변경하며, 권한 거부 시에도 안내를 받기를,
So that 내 라이프스타일에 맞는 nudge 정책을 직접 결정한다.

**Acceptance Criteria:**

**Given** 모바일 `(tabs)/settings/notifications`, **When** 사용자가 ON/OFF 토글, **Then** `PATCH /v1/notifications/settings`로 `notifications_enabled` 갱신
**And** 알림 시간 변경 시 `notification_time`(예: `19:00`) 갱신 + APScheduler에 다음 사이클부터 반영
**And** 첫 푸시 권한 요청 시점(온보딩 종료 직후 또는 첫 미기록 후) `useNotificationPermission` 권한 요청 — 거부 시 `PermissionDeniedView`(Story 2.2 컴포넌트 재사용) + *"설정에서 알림 허용 시 미기록 nudge가 동작합니다"* + `Linking.openSettings()` deep link
**And** 권한 OFF 상태에서 알림 설정 화면에 *"알림 허용 안 됨 — 설정 열기"* 배너 표시
**And** 알림 ON + 권한 OK 시 `nudge_scheduler.py`가 사용자 설정 시간 + 30분 사이클에 사용자 포함

### Story 4.2: APScheduler nudge 미기록 푸시 + 딥링크

As a 엔드유저,
I want 설정 시간 + 30분 경과 + 당일 식단 미입력 시 푸시 알림을 받고 탭하면 식단 입력 화면으로 직행하기를,
So that 회식·이동 등으로 입력을 깜빡한 날에도 일관성을 유지할 수 있다.

**Acceptance Criteria:**

**Given** `app/workers/nudge_scheduler.py` AsyncIOScheduler 잡, **When** 매일 사용자별 시간 + 30분 경과 + 당일 `meals` 0건, **Then** Expo Notifications 푸시 발송 (`expo_push.py` adapter)
**And** FastAPI lifespan에서 서버 시작 시 `AsyncIOScheduler.start()` + 종료 시 `shutdown()` (in-process, Railway 단일 노드 정합)
**And** 푸시 메시지 *"오늘 저녁 미기록 — 1분 안에 빠른 입력으로 일주일 일관성 유지하세요"*
**And** 사용자가 푸시 탭 시 Expo Router deep link 처리 → 모바일 앱이 `(tabs)/meals/input` 직행
**And** `notifications_enabled = false` 또는 푸시 권한 OFF 사용자는 잡 대상에서 제외
**And** 동일 날 이미 푸시 1건 발송 시 중복 발송 차단

### Story 4.3: Web 주간 리포트 4종 차트

As a 엔드유저,
I want Web에서 7일치 매크로 비율 추이 / 칼로리 vs TDEE / 단백질 g/kg 일별 추이 / 알레르기 노출 횟수를 차트로 보기를,
So that 한 주 패턴을 시각적으로 파악하고 다음 주 행동을 결정할 수 있다.

**Acceptance Criteria:**

**Given** Web `/dashboard/weekly`, **When** 사용자 진입(Google OAuth 로그인 상태), **Then** `GET /v1/reports/weekly?from=...&to=...` → 7일치 데이터 반환
**And** Recharts 4종 차트 (`features/reports/{Macro,Calorie,Protein,AllergyExposure}Chart.tsx`) — (1) 일별 매크로 비율 스택 / (2) 일별 칼로리 vs TDEE 라인 / (3) 단백질 g/kg 일별 추이(`health_goal=weight_loss` 1.2-1.6 권장 라인) / (4) 알레르기(예: 복숭아) 노출 횟수 막대
**And** 7일 데이터 초기 로딩 ≤ 1.5초 (NFR-P8) — Next.js RSC SSR + TanStack Query
**And** 키보드 Tab 내비게이션으로 모든 차트 자연 Tab 순서로 접근 가능 (NFR-A5)
**And** 스크린리더 접근 — 각 차트에 데이터 테이블 fallback (NFR-A5)
**And** 데이터 없음(빈 주) 시 *"이번 주 기록이 없습니다 — 모바일에서 첫 식단을 입력하세요"* 빈 화면

### Story 4.4: 인사이트 카드 + 매크로 목표 조정 + 자동 반영

As a 엔드유저,
I want 주간 리포트에서 *"다음 주 권장 매크로 조정"* 인사이트 카드를 한국 1차 출처 인용과 함께 보고, 다음 주 매크로/칼로리 목표를 조정하면 nudge 룰과 모바일 권장 표시에 자동 반영되기를,
So that 분석 → 인사이트 → 행동의 사이클이 손이 떨어지는 곳에서 닫힌다.

**Acceptance Criteria:**

**Given** 주간 리포트 페이지, **When** 데이터 로딩 완료, **Then** *"단백질 평균 55g/일 — 목표 80g 미달. 다음 주 매끼 단백질 +20g 시도해보세요. (출처: 보건복지부 2020 KDRIs, 대한비만학회 2024)"* 인사이트 카드 노출
**And** 인사이트 텍스트는 모든 권고에 *(출처: ...)* 패턴 + 광고 가드 적용 (FR24, FR25)
**And** 사용자가 *"매크로/칼로리 목표 조정"* 액션 시 설정 페이지 진입 → `PATCH /v1/users/me/macro_goal` 폼(탄/단/지 비율 + 일일 칼로리 또는 매끼 단백질 g) 노출
**And** 목표 변경 저장 시 `users.macro_goal` 갱신 + Redis `cache:user:{user_id}:profile` invalidate + 다음 분석부터 권장 표시 갱신
**And** nudge 룰 자동 반영 — 매끼 단백질 +20g 미니 챌린지가 nudge 메시지에 자동 통합 (예: *"오늘 저녁 단백질 25g 챌린지 진행 중 — 입력하세요"*)

## Epic 5: 계정 관리 + PIPA 권리 (프로필 수정·탈퇴·내보내기)

사용자가 자기 건강 프로필을 수정하고, 회원 탈퇴 시 30일 grace 후 물리 파기되며, 자기 식단/피드백/프로필을 표준 형식(JSON/CSV)으로 다운로드한다.

### Story 5.1: 건강 프로필 수정

As a 엔드유저,
I want 내 건강 프로필(나이/체중/신장/활동/`health_goal`/22종 알레르기)을 언제든 수정하고 변경이 이후 모든 분석에 즉시 반영되기를,
So that 체중 변화·목표 전환·알레르기 추가 등 라이프 변화를 분석에 곧바로 통합한다.

**Acceptance Criteria:**

**Given** 모바일 `(tabs)/settings/profile` 또는 Web `/settings`, **When** 사용자 진입, **Then** 현재 프로필이 prefill된 폼 노출
**And** 사용자 수정 + 저장 시 `PATCH /v1/users/me` → `users` 갱신 + `profile_updated_at` 타임스탬프 + Redis `cache:user:{user_id}:profile` invalidate
**And** 프로필 변경 후 다음 식단 분석에서 BMR/TDEE/매크로 룰/알레르기 가드 모두 갱신된 값 사용 (FR3 즉시 반영)
**And** 22종 알레르기 다중 선택 변경 시 DB CHECK 제약 + 22종 enum 무결성 (Story 1.5 정합)
**And** `react-hook-form` + `zod` inline 에러 검증
**And** 일반 사용자 자기 수정은 audit 대상 아님 (자기 데이터 권리 — 관리자 수정만 audit 대상, Epic 7)

### Story 5.2: 회원 탈퇴 + soft delete + 30일 grace + 물리 파기 worker

As a 엔드유저,
I want 모바일 또는 Web에서 회원 탈퇴를 요청하면 30일 grace 후 모든 데이터가 물리 파기되기를,
So that PIPA 정보주체 권리(즉시 삭제 의무)를 보장받으며 단순 실수 탈퇴에 대한 30일 회복 창구를 갖는다.

**Acceptance Criteria:**

**Given** 모바일 `(tabs)/settings/account-delete` 또는 Web `/account/delete`, **When** 사용자가 탈퇴 액션 + 명시 확인 다이얼로그(*"탈퇴 시 30일 후 모든 데이터가 영구 파기됩니다"*) + 사유 선택(선택), **Then** `DELETE /v1/users/me` 호출
**And** soft delete — `users.deleted_at` 마킹 + 즉시 로그인 차단(401) + JWT 무효화
**And** `app/workers/soft_delete_purge.py` AsyncIOScheduler 잡이 매일 새벽 `users.deleted_at + 30일 < now()` 사용자에 대해 cascade 파기(`meals`, `meal_analyses`, `consents`, `subscriptions`, `payment_logs`, `notifications`)
**And** 물리 파기 직전 사용자 데이터 dump를 별 R2 bucket에 30일 추가 보관 후 자동 파기 (NFR-R5 + C6 정합)
**And** 30일 grace 내 사용자가 같은 Google 계정으로 재로그인 시도 시 *"탈퇴 진행 중 — N일 후 영구 파기됩니다. 복구를 원하면 고객문의로 연락하세요"* 안내 (자동 복구 X — 1인 운영 단순화)
**And** 탈퇴 후에도 PIPA 외 관련법 보존 의무 항목(`consents`, `payment_logs` 일부)은 별 보존 영역에 격리

### Story 5.3: 데이터 내보내기 (JSON/CSV)

As a 엔드유저,
I want 내 식단·피드백·프로필 데이터를 JSON 또는 CSV로 다운로드하기를,
So that PIPA 정보주체 권리(데이터 이전·열람권)를 행사할 수 있고 외부 도구로 분석할 수 있다.

**Acceptance Criteria:**

**Given** 모바일 `(tabs)/settings/data-export` 또는 Web `/account/export`, **When** 사용자 액션, **Then** 형식 선택(JSON/CSV) + *"데이터 준비 중"* 안내
**And** `GET /v1/users/me/export?format=json` 또는 `?format=csv` 호출 시 `data_export_service.py`가 사용자 식단(`meals`) + 피드백(`meal_analyses`) + 프로필(`users` 자기 데이터 마스킹 없음) 통합 파일 반환
**And** JSON 형식은 식약처 표준 키 jsonb 그대로 + ISO 8601 UTC 날짜 + 한국어 enum 값 그대로
**And** CSV 형식은 UTF-8 BOM + 한국어 헤더(*"날짜, 식사, 매크로, fit_score, 피드백 요약, 출처"*) + 줄바꿈 LF
**And** 다운로드 응답 `Content-Disposition: attachment; filename="balancenote_export_{user_id}_{yyyy-mm-dd}.{json|csv}"`
**And** 대용량(예: 1년치 ≥ 10MB) 시 스트리밍 응답 + 메모리 보호
**And** 자기 데이터 권리 행사이므로 audit log 미기록

## Epic 6: 결제/구독 sandbox

사용자가 정기결제 1플랜을 sandbox 결제 화면에서 신청·해지하고, 영수증·이용내역을 조회하며, 시스템은 webhook을 멱등 처리한다. PG 본 계약·세금정산은 OUT(README 가이드 1페이지).

### Story 6.1: 정기결제 sandbox 신청 + 1플랜

As a 엔드유저,
I want 정기결제 1플랜(예: 월 9,900원)을 sandbox 결제 화면에서 신청하기를,
So that 외주 클라이언트가 자체 구독 모델을 입혀나갈 수 있는 결제 흐름의 기준 구현을 확인할 수 있다.

**Acceptance Criteria:**

**Given** 모바일 또는 Web 결제 화면, **When** 사용자가 *구독 시작* 액션, **Then** Toss Payments 또는 Stripe sandbox 결제 위젯 노출 (README에 둘 다 가이드)
**And** sandbox 카드 정보 입력 + 결제 승인 시 `POST /v1/payments/subscribe` → `subscriptions` 테이블에 `status=active` + `started_at` + `plan=monthly` 기록
**And** `Idempotency-Key` 헤더로 동일 요청 재시도 멱등 처리 (FR42 정합)
**And** 모바일은 App Store IAP 정책 정합 — MVP는 외부 웹 결제 우선 (App Review 정책 — *"앱 외부 결제 가능"* 화면만 노출 또는 deep link)
**And** KRW integer 통화 표기 (NFR-L3) — 9,900원 (소수 미사용)
**And** 결제 실패 시 RFC 7807 에러(`type=payment-failed`) + 사용자 안내 + Sentry 자동 수집

### Story 6.2: 구독 해지 + 영수증·이용내역 조회

As a 엔드유저,
I want 구독을 언제든 해지하고 자기 영수증·이용내역을 조회하기를,
So that 결제 투명성 + 사용자 권리(약관 명시 해지권)를 보장받는다.

**Acceptance Criteria:**

**Given** 결제 설정 화면, **When** 사용자가 *해지* 액션 + 명시 확인, **Then** `POST /v1/payments/cancel` → `subscriptions.status=cancelled` + `cancelled_at` 기록 + 다음 결제일까지 활성 (즉시 차단 X — 표준 정기결제 패턴)
**And** 영수증·이용내역 조회 화면에서 `GET /v1/payments/history` → `payment_logs`의 사용자 결제 이력(시점·금액·상태) 반환 + 영수증 링크 (Toss/Stripe sandbox 영수증 URL)
**And** 해지 후 다음 결제 주기 도래 시 webhook 처리(Story 6.3)로 `subscriptions.status=expired`
**And** README에 *"PG 본 계약·세금처리 가이드"* 1페이지 명문화 (NFR-M2 5섹션 일부)

### Story 6.3: 결제 webhook + Idempotency-Key 멱등 + 이력

As a 시스템,
I want Toss/Stripe webhook을 수신해 구독 상태를 갱신하고 결제 이벤트 이력을 멱등 처리로 기록하기를,
So that 결제 비동기 흐름이 신뢰성 있게 동작하고 외주 인수 시 클라이언트가 즉시 본 PG로 전환 가능하다.

**Acceptance Criteria:**

**Given** Toss 또는 Stripe webhook (`POST /v1/payments/webhook`), **When** 결제 성공 / 실패 / 환불 이벤트 수신, **Then** 시그니처 검증 → `subscriptions` 상태 갱신 + `payment_logs`에 이벤트 1건 추가
**And** `Idempotency-Key` 헤더(또는 PG provider event_id)로 동일 이벤트 중복 수신 시 무시 + 200 응답 (Stripe/Toss 표준 retry 정합)
**And** webhook 처리 시간 지연 시 PG 표준 retry 정책에 의존 — 우리는 ack 빠른 응답 우선 + 후처리는 BackgroundTasks
**And** webhook 시그니처 검증 실패 시 401 + Sentry 알림 (잠재적 위조 시도)
**And** 결제 webhook 단위 테스트 (성공/실패/환불 + 멱등 재전송 각 1건) 100% 통과

## Epic 7: 관리자 + Audit Trust

관리자가 별 admin role JWT(별 secret + 8시간 만료)로 Web 관리자 화면에 진입해 사용자 검색·식단 이력·프로필 수정을 수행하고, 모든 액션이 audit log에 자동 기록된다. 사용자 민감정보는 기본 마스킹 + 명시적 *원문 보기* 액션 시에만 해제 + 그 액션 자체도 audit 기록.

### Story 7.1: 관리자 로그인 + admin role JWT 분리 + 가드

As a 관리자(병원 의료정보팀 등),
I want 일반 사용자와 분리된 admin role 인증으로 Web 관리자 화면에 진입하기를,
So that 권한 침범 위험을 차단하고 관리자 액션의 책임 범위를 명확히 분리한다.

**Acceptance Criteria:**

**Given** Web `/admin/login`, **When** 관리자 Google OAuth 로그인 + admin role 매핑된 사용자, **Then** admin JWT(별 secret + 별 issuer claim, access 8시간, refresh 없음) 발급
**And** admin role 매핑은 별 관리 — 코드/DB 시드 또는 별 admin lookup table 통해 1인 개발자 명시 부여 (일반 사용자 자기 등록 X)
**And** Web `middleware.ts` admin route guard로 `(admin)` route group 진입 시 admin JWT 검증 → 미통과 시 `/admin/login` redirect
**And** admin 8시간 만료 시 refresh 미지원 → 즉시 admin 로그인 화면 redirect
**And** user JWT를 admin route에 시도 시 403 + RFC 7807 에러
**And** IP 화이트리스트 옵션 — MVP는 강제 X (NFR-S8) — 환경 변수로 켜기 가능 (외주 클라이언트별)

### Story 7.2: 관리자 사용자 검색 + 식단·피드백 이력 + 프로필 수정

As a 관리자,
I want Web 관리자 화면에서 사용자를 검색하고 식단 이력·피드백 로그·프로필을 조회·수정하기를,
So that 사용자 문의 응대 및 데이터 거버넌스 운영이 가능하다.

**Acceptance Criteria:**

**Given** Web `/admin/users`, **When** admin 진입, **Then** 사용자 검색 폼(이메일·user_id 일부, 마스킹된 결과) + 결과 테이블 노출
**And** `GET /v1/admin/users?q=...` 검색 응답 시간 — 1만 건 가정에서 ≤ 1초 (NFR-P9)
**And** 사용자 클릭 → 상세 페이지에서 식단 이력(`meals`)·피드백 로그(`meal_analyses`)·프로필(`users`) 표시 — 민감정보(이메일·체중·알레르기 상세)는 기본 마스킹
**And** 관리자 프로필 수정 액션 시 `PATCH /v1/admin/users/{user_id}` + audit log 자동 기록 (Story 7.3)
**And** 관리자 식단 삭제 요청 처리 시 `DELETE` 가능 (B2B 운영 케이스) + audit log 기록
**And** 반응형 (NFR-Sc2 + 영업 시연 환경 다양) — 모바일 폭(360px) ~ 데스크톱(1440px+) 모두 대응

### Story 7.3: Audit log 자동 기록 + dependency 자동 연쇄

As a 시스템 / 외주 발주자,
I want 관리자의 모든 조회·수정 액션이 시점·액터·액션·대상·IP·request_id로 audit log에 자동 기록되기를,
So that B2B 외주 신뢰 카드(누가 무엇을 봤는지 추적 가능)가 작동한다.

**Acceptance Criteria:**

**Given** `app/api/deps.py:audit_admin_action` Dependency, **Then** 모든 admin 라우터에 `Depends(audit_admin_action)` 명시
**And** `audit_admin_action` ↔ `admin_user_jwt_required` 자동 연쇄 — admin 토큰 없으면 audit 미발동 (정합성)
**And** 라우터 호출 시 `audit_logs` 테이블에 (`occurred_at`, `actor_id`, `actor_email_masked`, `action`, `target_user_id`, `target_resource`, `path`, `method`, `ip`, `request_id`, `user_agent`) 기록
**And** 단순 조회 액션도 기록 — `action=user_meal_history_view`, `user_profile_view` 등 enum
**And** audit log는 변경 불가 (append-only) — `INSERT` 외 권한 없음 (DB role 분리 또는 트리거)
**And** audit_logs 1만 건 가정 검색 — 시간/액터/대상별 인덱스로 응답 ≤ 1초

### Story 7.4: Self-audit 화면 + 민감정보 마스킹 + 원문 보기 토글

As a 관리자,
I want 내 활동 로그를 self-audit으로 직접 보고, 사용자 민감정보는 기본 마스킹된 채 명시적 *원문 보기* 액션 시에만 해제하기를,
So that 자기 감사가 가능하고 부주의한 민감정보 노출이 차단된다.

**Acceptance Criteria:**

**Given** Web `/admin/audit-logs`, **When** admin 진입, **Then** `GET /v1/admin/audit-logs?actor_id=me` → 자기 활동 로그 시간순 표시
**And** 다른 admin 활동 조회 시도 시 `actor_id` 권한 분리 — 1인 개발자 owner 외 admin은 자기 활동만 (외주 클라이언트별 조정 옵션)
**And** 사용자 검색 결과 카드 — 이메일은 `j***@example.com`, 체중은 `**kg`, 알레르기 상세는 `*** *건* 등록`으로 마스킹 (NFR-S5 + Sentry 마스킹 패턴 일관)
**And** 관리자 *원문 보기* 토글 액션 + 사용자 명시 확인 시 마스킹 해제 + 해당 액션 자체가 audit log에 `action=user_pii_view` 기록 (FR39)
**And** 5분 비활동 후 마스킹 자동 복원
**And** Sentry breadcrumbs / structlog는 원문 보기 액션의 payload를 마스킹된 채로만 로깅 (이중 안전판)

## Epic 8: 운영·인수인계 패키지 + 영업 자료

외주 클라이언트 개발자가 README + Docker 1-cmd만으로 8시간 내 부팅하고, 영업 발주자는 SOP 4종 + FAQ 5종 + 데모 영상 5종으로 1차 영업 답변을 즉시 받는다. Sentry/Swagger/Rate limit/캐시 정교화 + 클라우드 배포 hardening + 일별 비용 cron + Runbook 3종.

### Story 8.1: SOP 4종 작성 (의료기기·PIPA·디스클레이머·광고 가드)

As a 외주 발주자(영업 미팅 시점) / 인수 클라이언트,
I want SOP 4종(의료기기 미분류 입장 / PIPA 동의서 템플릿 / 디스클레이머 한·영 / 식약처 광고 가드)을 docs/sop/에서 즉시 다운로드 가능하기를,
So that *"의료기기 인허가 필요한가?"* / *"PIPA 동의서는 어떻게 받나?"* 같은 영업 자리 첫 질문에 1차 답변이 가능하다.

**Acceptance Criteria:**

**Given** `docs/sop/01-medical-device-classification.md`, **Then** 식약처 *"의료기기와 개인용 건강관리(웰니스)제품 판단기준"* 저위해도 일상 건강관리 명시 예시 인용 + 회피 의무 표현(진단/처방/약물 권고) + `fit_score` 명명·범위 + UI 푸터 노출 위치 + 외주 인허가 자문 1차 답변 자료
**And** `docs/sop/02-pipa-automated-decision-consent.md` — PIPA 2026.03.15 시행 사실 + 처리 항목/이용 목적/보관 기간/제3자 제공/LLM 외부 처리/자동화 의사결정 동의 5섹션 템플릿 + CPO 표기 + 입법예고 추적 SOP
**And** `docs/sop/03-disclaimer-ko-en.md` — 한국어 풀텍스트(research 3.4) + 영문 풀텍스트(*"NOT INTENDED TO DIAGNOSE..."*) + 4 노출 위치 매핑 + FDA Warning Letter 시사점 (기능·디자인이 의료 목적 아님 동시 입증)
**And** `docs/sop/04-fda-style-ad-expression-guard.md` — 식약처 광고 금지 표현 패턴 + 안전 워딩 매핑 표 + 정규식 + 단위 테스트 케이스 ≥ 10건
**And** 모든 SOP는 GitHub Markdown + 1차 출처 URL 인용 (research 산출물 정합)
**And** Web 포트폴리오 페이지에서 SOP 4종 다운로드 링크 노출 (Story 8.6)

### Story 8.2: FAQ 5종 closing 영업 답변 작성

As a 외주 발주자(영업 미팅 시점),
I want 차별화 / 의료기기 인허가 / 우리 회사 적용 / 8주 가능성 / 유지보수 5종 closing 답변을 ≥ 1페이지씩 즉시 받기를,
So that 첫 미팅에서 *"왜 이 외주를 선택해야 하는가"* 5축 답변이 일관되게 진행된다.

**Acceptance Criteria:**

**Given** `docs/faq/01-differentiation.md`, **Then** 한국 1차 출처 RAG + Self-RAG + 듀얼-LLM + 외주 인수인계 4 차별화 카드 + 글로벌 앱(Noom/MFP/Yazio/Cronometer) 비교 매트릭스
**And** `docs/faq/02-medical-device.md` — 의료기기 미분류 입장 + SOP 1 인용 + DTx 인허가 트랙 분리 답변
**And** `docs/faq/03-customization.md` — 외주 클라이언트별 어댑터 패턴(식품기업 SKU / 보험사 인센티브 / 병원 EMR / 스타트업 PoC 변형) + LangGraph 노드 단위 교체 가능 설명
**And** `docs/faq/04-feasibility-8-weeks.md` — W1-W8 phasing + IN 25 / OUT 9 + 1인 anti-pattern 회피 + Risk Mitigation R1-R10
**And** `docs/faq/05-maintenance.md` — README 5섹션 + Docker 1-cmd + 키 회전 SOP + Runbook 3종 + AWS/GCP/Azure 마이그레이션 가이드
**And** 각 FAQ는 1차 출처 URL 인용 + 코드/문서 링크
**And** 영업 미팅에서 즉시 다운로드 가능 (PDF 또는 Markdown)

### Story 8.3: README 5섹션 + AGENTS.md (1차 인수인계 표준)

As a 외주 클라이언트 신규 개발자,
I want README 5섹션 + 루트 AGENTS.md를 따라 8시간 내 로컬 환경을 구축하고 자체 데이터 통합을 시도하기를,
So that 인수인계 가능성(B3 KPI)이 검증된 운영 산출물 표준이 박힌다.

**Acceptance Criteria:**

**Given** `README.md` Quick start 섹션, **Then** `git clone` → `.env.example` 채우기 → `docker compose up` → 8분 내 부팅 → Swagger `/docs` 호출까지 단계별 명시
**And** Architecture 섹션 — LangGraph 6노드 다이어그램(Mermaid) + 듀얼-LLM router + Self-RAG 분기 + AsyncPostgresSaver + cross-cutting 7개
**And** 데이터 모델 섹션 — 식약처 표준 jsonb 키 + KDRIs `health_goal` enum + 22종 알레르기 + `food_aliases` 정규화 패턴 (외주 갈아끼우기 가이드)
**And** FAQ 섹션 — docs/faq/ 5종 링크 + 영업 답변 5종 closing 요약
**And** 마이그레이션 가이드 섹션 — Railway → AWS/GCP/Azure 절차 + PG 본 계약·세금정산 가이드 + 보안 점검 체크리스트
**And** 루트 `AGENTS.md` — BalanceNote-specific 컨텍스트(차별화 4 카드 + 25 IN + cross-cutting + 패턴 룰)를 AI 에이전트가 즉시 흡수 가능한 형태로
**And** Web `web/AGENTS.md`(Next.js 자동 생성)에 BalanceNote-specific 추가
**And** 외부 개발자 1명 검증(가능 시) 시 README + Docker만으로 ≤ 8시간 부팅 + 1시간 내 자체 데이터 통합 (B3 KPI, J7)

### Story 8.4: 운영 polish (Sentry·Swagger·Rate limit·LLM 캐시·표준 빈/로딩/에러 일괄)

As a 외주 인수 클라이언트 / 운영자,
I want Sentry 룰 정교화·Swagger 정리·Rate limit 정교화·LLM 캐시 정교화·표준 빈/로딩/에러 화면 일괄 적용이 운영 산출물 수준이기를,
So that *"내가 인수받아도 운영할 수 있다"*는 신뢰가 코드와 화면에 박힌다.

**Acceptance Criteria:**

**Given** Sentry 룰 정교화, **Then** LangGraph 노드별 transaction span + 외부 API 실패·DB 에러 카테고리 분리 + before_send 마스킹 + 알림 채널 연동 (Slack/Discord webhook)
**And** Swagger/OpenAPI 정리 — 전 endpoint + 요청/응답 예시 + 에러 코드 명세(RFC 7807 type 카탈로그) + 인증 헤더 가이드
**And** Rate limit 정교화 — slowapi + Redis 슬라이딩 윈도우 3-tier(분당 60 / 시간당 1,000 / LangGraph 분당 10) + 429 응답 + `Retry-After` 헤더 + 단위 테스트 ≥ 5건
**And** LLM 캐시 정교화 — `cache:llm:{sha256(meal_text+profile_hash)}` 24h TTL + `cache:food:{normalized_name}` 7d + 프로필 수정 시 `cache:user:*` invalidate + 캐시 hit 응답 ≤ 30ms (NFR-P7)
**And** 표준 빈/로딩/에러 화면 일괄 적용 — 모든 화면(`(auth)` / `(tabs)` / Web `(public)/(user)/(admin)`)에 동일 패턴 — *"기록 없음 — CTA"* / 즉시 스피너 → 500ms 후 스켈레톤 → 콘텐츠 / *"오류 — 다시 시도"*
**And** 모바일 `(tabs)/settings/about.tsx` 앱 정보 화면 — 앱 버전 + 빌드 정보 + OSS 라이선스 고지 (license-checker 자동 생성)
**And** 분석 외 API endpoint p95 ≤ 500ms (NFR-P10) — Sentry transaction tracing으로 회귀 검증 + 위반 시 Sentry 알림
**And** 디자인 토큰 색상 대비 WCAG AA 통과 검증 (본문 4.5:1, 큰 텍스트 3:1, NFR-A2) — 모든 화면 일괄 적용 시 토큰 기반으로 자동 통과 + 1회 수동 spot check
**And** 모바일 모든 인터랙티브 요소(`<TouchableOpacity>`/`<Pressable>`/`<Button>` 등)에 `accessibilityLabel` prop 채움 + iOS VoiceOver / Android TalkBack 1회 수동 검증 통과 (NFR-A1)
**And** Pytest 커버리지 ≥ 70% (NFR-M1, T7 KPI) — CI 게이트가 실패 시 차단

### Story 8.5: 클라우드 배포 hardening + Docker hardening + 일별 비용 cron + Runbook 3종

As a 1인 개발자 / 외주 인수 클라이언트,
I want 프로덕션 배포가 HSTS·healthcheck·multi-stage Docker로 hardening되고 일별 LLM/Railway 비용 알림 cron이 작동하며 Runbook 3종이 운영 단계 SOP를 제공하기를,
So that 비용 폭증·보안 약점·운영 사고에 대한 사전 차단·사후 대응이 즉시 가능하다.

**Acceptance Criteria:**

**Given** `docker/Dockerfile.api` multi-stage build, **Then** 빌드 단계 + 실행 단계 분리 + 이미지 크기 최소화 + healthcheck `/healthz` 정합
**And** `docker-compose.yml` dependency wait — `api`는 `postgres`·`redis` healthy 후 시작 + healthcheck + volume mount 분리
**And** Vercel(Web) + Railway(API + Postgres + Redis) + Cloudflare R2(이미지) prod 배포 — HTTPS·HSTS·CORS 화이트리스트 + Rate limit 활성 + Sentry prod 환경 분리 + 환경 변수 Railway secrets 이전
**And** GitHub Actions `daily-cost-alert.yml`(매일 09:00 KST cron) — OpenAI/Anthropic Usage API + Railway billing API 호출 → Slack/Discord webhook + Sentry custom event + 일별 임계치 초과 시 자동 차단(NFR-Sc4)
**And** `docs/runbook/deployment.md` — 배포 절차 + 롤백 절차 + Alembic migration 안전 가이드
**And** `docs/runbook/secret-rotation.md` — API 키 회전 절차(OpenAI/Anthropic/Toss/Stripe/Google OAuth) + 권장 주기 (NFR-S10)
**And** `docs/runbook/incident-response.md` — 외부 API 장애 / DB 다운 / LLM 비용 폭증 / 보안 침해 시나리오별 대응 절차

### Story 8.6: 9포인트 데모 영상 5종 + 포트폴리오 랜딩 페이지 + 영업 자료 패키지

As a 외주 발주자 5종 (병원·보험·식품·스타트업·제약),
I want 우리 도메인 페르소나에 맞춘 9포인트 데모 영상과 SOP 4종 + FAQ 5종이 묶인 포트폴리오 랜딩 페이지를 즉시 받기를,
So that 첫 미팅 후 1주 내 외주 견적 의사결정에 도달할 수 있다.

**Acceptance Criteria:**

**Given** 9포인트 데모 시나리오 5종 영상(병원/보험/식품/스타트업/제약 페르소나별, 각 ≤ 5분), **Then** 무편집 1회 촬영 + 사진 입력 → Self-RAG 재질문 → 인용형 피드백 → 푸시 nudge → 주간 리포트 → 관리자 화면 → README/Swagger 9포인트 모두 라이브 동작 (B2 KPI)
**And** 포트폴리오 랜딩 페이지 (Web `/`) — 데모 영상 5종 임베드 + 차별화 4 카드 요약 + SOP 4종 / FAQ 5종 다운로드 + GitHub repo 링크 + 1인 개발자 영업 연락처 + LangSmith 보드 read-only 공개 링크 1세트(NFR-O4)
**And** 영업 자료 패키지(zip 다운로드) — Brief 요약 1페이지 + 차별화 카드 4종 PDF + 데모 영상 5종 링크 + SOP 4종 + FAQ 5종 + 의료기기 미분류 SOP + PIPA 동의서 + 디스클레이머 한·영 + LangSmith 보드 스크린샷·평가 데이터셋 결과 1포인트(FR49 / NFR-O4)
**And** 영업 미팅 첫 5분 — 차별화 카드 4 요약 + 1차 출처 인용 사례 1건 + Docker 1-cmd 라이브 부팅(클라이언트 노트북에서) 가능
**And** W8 회귀 테스트 1회전 — T1-T10 KPI 통과 검증 + 8주 통과 체크리스트 모두 만족
**And** 25 IN 항목 모두 라이브 환경 동작 + 9포인트 데모 100% 끊김 없이 진행 가능

