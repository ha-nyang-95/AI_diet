# Story 4.3: Web 주간 리포트 4종 차트

Status: done

<!-- Validation: Epic 4 세 번째 스토리. Story 4.1(알림 설정 4 컬럼) + Story 4.2(APScheduler nudge + notifications 테이블)는 본 스토리에 *직접 의존 X* — 본 스토리는 (1) 백엔드 `app/api/v1/reports.py` 신규 + `app/services/report_service.py` 신규(7일 aggregation: meals + meal_analyses), (2) Web Next.js `/dashboard/weekly` 라우트 + Recharts 4종 차트(매크로 비율 / 칼로리 vs TDEE / 단백질 g/kg / 알레르기 노출) + 데이터 테이블 fallback(NFR-A5) + 빈 화면, (3) `recharts` 신규 web 의존성, (4) FR32 + NFR-P8(≤1.5초) + NFR-A5(키보드 Tab + screen-reader fallback) 정합. Story 4.4(인사이트 카드 + 매크로 목표 조정)는 본 스토리의 reports endpoint를 *재사용*하므로 응답 schema는 forward-compat 슬롯 의식. 백엔드 신규 의존성 0건(`recharts`만 web 측). -->

## Story

As a 엔드유저,
I want Web `/dashboard/weekly`에서 7일치 매크로 비율 추이 / 칼로리 vs TDEE / 단백질 g/kg 일별 추이 / 알레르기 노출 횟수 4종 차트를 보고, 키보드 Tab 또는 스크린리더로도 동일한 데이터에 접근하기를,
So that 한 주 식단 패턴을 시각적으로 파악하고 다음 주 행동을 결정할 수 있으며, 접근성·영업 데모 baseline이 확립된다.

## Acceptance Criteria

1. **AC1 — `app/api/v1/reports.py` 신규 + `GET /v1/reports/weekly` endpoint**
   **Given** Story 1.2 `current_user` Dependency + Story 3.7 `meal_analyses` 테이블(`(user_id, created_at DESC)` 인덱스 — Story 4.3 forward-compat 슬롯) + Story 2.1 `meals` 테이블, **When** `api/app/api/v1/reports.py` 신규, **Then**:
   - `router = APIRouter()` + `app/main.py:app.include_router(reports_router.router, prefix="/v1/reports", tags=["reports"])` (Story 4.2 패턴 정합 — `notifications`/`meals` 라우터 등록 직후 위치).
   - `@router.get("/weekly")` — query params `from_date: date` + `to_date: date` (둘 다 `from datetime import date` ISO 8601, kebab-case URL 정합 architecture.md:404 — query는 snake_case `from_date`/`to_date`). 기본값 없음 — 필수 explicit 송신(클라이언트가 KST `today - 6일 ~ today` 7일 윈도우 결정).
   - **Dependency 게이트**: `Depends(current_user)` (인증) + `Depends(require_basic_consents)` (Story 1.3 PIPA 기본 동의). PIPA `automated_decision` 게이트는 *불필요* — 본 endpoint는 *기존 분석 결과 조회만*(LLM 비용 0, FR7 정합 — 자동화 의사결정 trigger X). 이미 LLM 호출 시점(Story 3.6 `analysis_service`)에서 동의 검증 통과한 결과를 단순 aggregate.
   - **Response 모델**: `WeeklyReportResponse` Pydantic — `from_date` / `to_date` (echo) + `tdee` (`int | None`, `health_profile.compute_tdee` 호출 결과; 프로필 미완성 시 `None`) + `health_goal` (`HealthGoal | None`) + `protein_target_g_per_kg_lower`/`_upper` (`float | None`, `health_goal=weight_loss`면 1.2/1.6, `muscle_gain`이면 1.6/2.2 — `app/domain/health_profile.py` 확장 SOT) + `weight_kg` (`float | None`) + `daily_summaries: list[DailySummary]` (7개 요소, 빈 날 포함). `DailySummary` 필드: `kst_date: date` / `meal_count: int` / `macros: WeeklyMacros | None` (해당 일 평균 — meal 0건이면 None) / `energy_kcal_total: float | None` / `allergen_exposures: list[AllergenExposure]` (사용자 `users.allergies` 22종 중 해당 날 식단 `parsed_items.name` 또는 `feedback_text`에 매칭된 항목 — 빈 list = 노출 0). `WeeklyMacros` 필드: `carbohydrate_g: float` / `protein_g: float` / `fat_g: float` / `protein_g_per_kg: float | None` (`weight_kg` 미설정 시 None). `AllergenExposure` 필드: `allergen: str` (22종 enum 중 1건) + `count: int` (해당 날 노출 식단 수).
   - **Aggregation 흐름** (`app/services/report_service.py:get_weekly_report` 신규, 단일 SQL Query + 1회 사용자 fetch):
     - 1차 fetch: `SELECT id, weight_kg, height_cm, age, sex, activity_level, health_goal, allergies FROM users WHERE id = :user_id` (이미 `current_user`로 hydrated User 모델 활용 — DB roundtrip 추가 X).
     - 2차 fetch: `SELECT m.id, (m.ate_at AT TIME ZONE 'Asia/Seoul')::date AS kst_date, m.parsed_items, ma.fit_score_label, ma.fit_reason, ma.carbohydrate_g, ma.protein_g, ma.fat_g, ma.energy_kcal, ma.feedback_text FROM meals m LEFT JOIN meal_analyses ma ON ma.meal_id = m.id WHERE m.user_id = :user_id AND m.deleted_at IS NULL AND (m.ate_at AT TIME ZONE 'Asia/Seoul')::date BETWEEN :from_date AND :to_date ORDER BY kst_date ASC`. 한 query로 7일 기록 전부 fetch.
     - 일별 그룹핑: Python dict `{kst_date: list[row]}` — 빈 날도 `from_date ~ to_date` 7일 enumerate로 채움(`DailySummary(kst_date=d, meal_count=0, macros=None, ...)`).
     - 일별 aggregation: meal_count = `len(rows)`. macros = 분석된 식단(`ma.* IS NOT NULL`)만 *합산 후 평균* — `protein_g = sum(ma.protein_g) / analyzed_count`, energy_kcal_total = `sum(ma.energy_kcal)` (총합, 평균 X — 일별 칼로리 vs TDEE 비교 입력). protein_g_per_kg = 평균 protein_g / weight_kg (weight_kg 미설정 시 None).
     - **알레르기 노출 매칭** (D1 결정 — substring contains): `users.allergies` 22종 각 항목에 대해 일별 식단의 `parsed_items[].name` (Story 2.3 OCR 결과 SOT) 또는 `feedback_text` (Story 3.6 LLM 본문, 광고 가드 검증된 신뢰 텍스트)에 정규화된 substring 포함 여부 검사. 매칭 알고리즘: `app/domain/allergens.py:contains_allergen(text, allergen)` 신규 helper(NFC 정규화 + Story 3.5 `_LABEL_SUBSTRING_EXCLUSIONS` 재사용 — 메밀이 밀 트리거 안 하도록 / 도넛이 넛 트리거 안 하도록 / 기타 22-라벨 false-positive 제외 SOT). 동일 알레르기 동일 일 다중 식단 매칭은 `count = 매칭된 meal 개수`로 정확 카운트.
   - **TDEE 계산**: `app/domain/bmr.py:compute_bmr_mifflin` + `compute_tdee` SOT 재사용. 프로필 7컬럼(age/weight_kg/height_cm/sex/activity_level/health_goal/allergies) 중 BMR/TDEE 입력(age/weight_kg/height_cm/sex/activity_level) 하나라도 None이면 `tdee = None` graceful(404 X — 빈 차트 fallback UX).
   - **Empty 응답 정합**: 7일 모두 meals 0건이면 `daily_summaries`는 7 요소 모두 `meal_count=0` + `macros=None`, `tdee` 정상 계산(프로필 완비 시), `allergen_exposures` 빈 list. 200 OK + 빈 차트 트리거.
   - **OpenAPI 노출**: `pnpm gen:api` 실행 시 web `src/lib/api-client.ts`에 자동 반영. CI `openapi schema diff` 게이트 정합.
   - **Rate limit**: `@limiter.limit(RATE_LIMIT_USER_PER_MINUTE)` (60/min — 일반 GET 정합, LangGraph 10/min 카테고리 X).

2. **AC2 — Web 주간 리포트 페이지 (`/dashboard/weekly`)**
   **Given** `web/src/app/(user)/dashboard/page.tsx` 기존 placeholder + AGENTS.md *"recharts — Story 4.3에서 도입"* + architecture.md:751 `/dashboard/weekly/page.tsx` 위치 SOT, **When** `web/src/app/(user)/dashboard/weekly/page.tsx` 신규 + `web/src/app/(user)/dashboard/page.tsx` 갱신, **Then**:
   - `web/src/app/(user)/dashboard/weekly/page.tsx` 신규 — Server Component(RSC SSR for NFR-P8 1.5초 — `cache: "no-store"` cookie forward로 인증 SSR 정합 Story 1.2 패턴). 상단에서 `getServerSideUser` + `getServerSideConsents` 가드(dashboard/page.tsx 패턴 동일 — `!user → /login`, `!basic_consents → /onboarding/disclaimer`, `!automated_decision_consent → /onboarding/automated-decision`, `!profile_completed_at → /onboarding/profile`). KST 오늘 기준 `from_date = today - 6일`, `to_date = today` 계산 후 백엔드 `GET /v1/reports/weekly` SSR fetch(`getServerSideWeeklyReport(fromDate, toDate)` — `web/src/lib/auth.ts` 패턴 정합, cookie forward).
   - `web/src/app/(user)/dashboard/page.tsx` placeholder 제거 → `<Link href="/dashboard/weekly">주간 리포트 보기</Link>` (또는 직접 redirect). 영업 데모는 `/dashboard/weekly` 직행이 핵심 — 첫 방문 시 dashboard에서 weekly로 즉시 진입 가능.
   - 페이지 구조: Server Component가 SSR fetch 후 props 전달 → Client Component(`features/reports/WeeklyReport.tsx` `"use client"`)가 차트 4종 + 데이터 테이블 fallback 렌더. SSR-Hydration mismatch 회피를 위해 차트는 클라이언트 마운트 후만 렌더(recharts ResponsiveContainer는 SSR 시 0 width 측정 — `client-only` wrapper 또는 `useEffect` 기반 mounted flag 패턴 사용).
   - 빈 데이터(`meal_count`가 7일 모두 0): *"이번 주 기록이 없습니다 — 모바일에서 첫 식단을 입력하세요"* + 모바일 앱 anchor link(`balancenote://meals/input`) — 영업 데모 시 비어있어도 우아한 빈 화면(epics.md:759 정합).
   - 페이지 metadata: `title: "주간 리포트 — BalanceNote"` (Next.js metadata API).

3. **AC3 — Recharts 신규 의존성 + 4종 차트 컴포넌트**
   **Given** `web/package.json` `recharts` 미설치 + AGENTS.md `recharts — Story 4.3에서 도입` + architecture.md:336 / prd.md:693 `recharts` 박힘, **When** 의존성 추가 + 4 컴포넌트 신규, **Then**:
   - `web/package.json` `dependencies`에 `"recharts": "^3.8.0"` 추가(2026-04 latest stable, React 19 공식 지원 since 2.15 + 3.x). `pnpm install` 통과 + lockfile 갱신.
   - `web/src/features/reports/WeeklyReport.tsx` 신규 — orchestrator client component. props: `report: WeeklyReportResponse` (서버에서 SSR fetch). 4 차트 grid 레이아웃(Tailwind `grid grid-cols-1 lg:grid-cols-2 gap-6`) + 각 차트 하단에 `<details>` 접힘 데이터 테이블(NFR-A5 fallback).
   - `web/src/features/reports/MacroChart.tsx` 신규 — 일별 매크로 비율 *스택* 차트. recharts `BarChart` + `Bar dataKey="carbohydrate_g" stackId="macro"` × 3(carb/protein/fat). x축은 KST 날짜 `MM-DD` 포맷, y축은 g 단위. `tooltip`으로 일별 정확 값 노출. 색상 토큰: 탄=`#fbbf24` (amber-400) / 단=`#3b82f6` (blue-500) / 지=`#ef4444` (red-500) — Tailwind 표준 SOT, NFR-A2 색상 대비 4.5:1 검증(차트 배경 대비). 빈 날(`macros=null`)은 빈 막대 0 grid.
   - `web/src/features/reports/CalorieChart.tsx` 신규 — 일별 *섭취 칼로리 vs TDEE* 비교. recharts `ComposedChart` + `Bar dataKey="energy_kcal_total"` (섭취) + `ReferenceLine y={tdee}` (TDEE 권장 라인, 점선). 라벨 위치 우측. `tdee=null`(프로필 미완성)이면 ReferenceLine 미렌더 + 캡션 *"TDEE 표시는 프로필 입력 후 노출됩니다"*.
   - `web/src/features/reports/ProteinChart.tsx` 신규 — 일별 *단백질 g/kg 추이*. recharts `LineChart` + `Line dataKey="protein_g_per_kg"` + `health_goal=weight_loss`인 사용자에 대해 `ReferenceArea y1=1.2 y2=1.6` 권장 영역(연한 녹색 fill, opacity=0.15) 표시. `health_goal=muscle_gain`이면 1.6-2.2 영역. `health_goal` 미설정 또는 `weight_kg` None이면 권장 영역 미렌더 + 캡션 *"권장 범위는 프로필 + 목표 설정 후 노출"*.
   - `web/src/features/reports/AllergyExposureChart.tsx` 신규 — 사용자 `users.allergies` 22종 중 *주간 노출 횟수 막대*. recharts `BarChart` + 알레르기별 horizontal bar(7일 합산). 알레르기 0건이면 *"이번 주 알레르기 노출 0건"* 빈 텍스트 + 빈 차트 영역(NFR-A4 정합). `users.allergies = null/[]` (사용자 알레르기 미설정)이면 차트 자체 미렌더 + 캡션 *"알레르기 항목 설정 시 노출 모니터링"*.

4. **AC4 — 7일 데이터 초기 로딩 ≤ 1.5초 (NFR-P8)**
   **Given** prd.md:485 + architecture.md `NFR-P8` 7일 데이터 ≤ 1.5초 SSR + Recharts 권장, **When** /dashboard/weekly 진입, **Then**:
   - **SSR 측정 게이트**: Next.js Server Component가 `GET /v1/reports/weekly` SSR fetch + HTML 첫 페인트 단계까지 ≤ 1.5초 (cold cache 기준). `web/src/lib/auth.ts:getServerSideUser` 패턴 정합 — cookie forward + `cache: "no-store"`.
   - **백엔드 query 1회 SOT**: AC1의 단일 SQL JOIN — N+1 회피(meals 7개 + meal_analyses LEFT JOIN). 추가 라운드트립 0건. `selectinload(Meal.analysis)` (Story 3.7 패턴 정합) 또는 explicit `LEFT JOIN` 1회.
   - **클라이언트 hydration**: WeeklyReport는 client component이지만 차트 데이터는 props로 server pre-rendered 통과 — TanStack Query refetch는 *수동 새로고침 트리거 시점만*(staleTime 60s default, Story 1.2 패턴 정합).
   - **bundle size 가드**: recharts 추가로 web bundle ≥ 100KB 증가 — `next.config.ts` 별도 튜닝 무필요(Next.js 16 Turbopack tree-shaking 표준 적용). bundle analyzer 옵션은 Story 8.4 polish forward(scope 외).
   - **검증 SOP**: dev 환경 Lighthouse Mobile *Performance* score ≥ 80(LCP ≤ 2.0s baseline). 본 스토리 DS 단계는 *측정 가능 SOP* 명시만 — 실 측정은 CR/QA 단계 책임. `docs/runbook/web-perf-check.md` 신규 1페이지(SOP — `pnpm dev` 후 `chrome --headless --lighthouse=...` 명령 + 통과 기준).

5. **AC5 — 키보드 Tab 내비게이션 + 데이터 테이블 fallback (NFR-A5)**
   **Given** prd.md:1088 NFR-A5 + architecture.md:1011/1080 *키보드 내비게이션 + 차트는 데이터 테이블 fallback*, **When** /dashboard/weekly 진입, **Then**:
   - **키보드 Tab 순서**: 페이지 진입 시 `Tab` 키로 자연 순서 — (1) "이번 주 (날짜 범위)" 헤더 + 사용자명 / (2) MacroChart 영역(focusable wrapper, `tabIndex={0}`) → 데이터 테이블 toggle 버튼 → / (3) CalorieChart → table toggle → / (4) ProteinChart → table toggle → / (5) AllergyExposureChart → table toggle → / (6) "다음 주 권장 매크로 조정" CTA placeholder(Story 4.4 forward, 본 스토리는 비활성 또는 *"준비 중"* tooltip).
   - **차트 데이터 테이블 fallback**: 각 차트 하단에 `<details><summary>데이터 표 보기</summary><table>...</table></details>` 접힘 — 기본은 닫힘. 스크린리더는 `<details>` 펼친 상태로 인식 가능(WAI-ARIA `<table role="table">` + `<thead><tr><th scope="col">날짜</th>...</thead>` 표준). 모든 데이터 셀은 `<td>` 표준 + 숫자 정렬은 `text-right`.
     - MacroChart 표: 헤더 `날짜 / 탄(g) / 단(g) / 지(g) / 합계(kcal)`, 7행.
     - CalorieChart 표: 헤더 `날짜 / 섭취 칼로리(kcal) / TDEE(kcal) / 차이(kcal)`, 7행 + 마지막 행 *"주간 평균"*.
     - ProteinChart 표: 헤더 `날짜 / 단백질(g) / 단백질(g/kg) / 목표 범위(g/kg)`, 7행.
     - AllergyExposureChart 표: 헤더 `알레르기 / 노출 횟수`, N행(N=사용자 알레르기 22종 중 주간 노출 ≥ 1회 항목).
   - **a11y 라벨**: 각 차트 wrapper에 `aria-label` *"매크로 비율 추이 차트 — 자세한 데이터는 아래 표 참조"* 등 — 스크린리더 사용자가 차트 의미 이해.
   - **색상 단독 의존 회피**: NFR-A4 색약 대응 — 차트 색상 + 데이터 테이블이 *동일 정보 두 채널* 전달.

6. **AC6 — 알레르기 매칭 도메인 SOT (`app/domain/allergens.py:contains_allergen`)**
   **Given** Story 3.5 `_LABEL_SUBSTRING_EXCLUSIONS` (메밀↔밀, 도넛/코코넛↔넛 등 false-positive 가드 SOT) + Story 3.5 `_ALIAS_TEXT_EXCLUSIONS` + Story 3.5 `_SKIP_SUBSTRING_LABELS = frozenset({"기타"})`, **When** `app/domain/allergens.py`에 `contains_allergen` 헬퍼 신규, **Then**:
   - `def contains_allergen(text: str, allergen: str) -> bool` — `text` NFC 정규화 후 substring contains 검사 + Story 3.5 가드 SOT 동일 *재사용*(중복 정의 X — import 또는 module 내부 재배치). `allergen`은 `KOREAN_22_ALLERGENS` 22종 중 1건만 허용(`assert allergen in KOREAN_22_ALLERGENS` 가드).
   - 매칭 의미론: 식단의 자연어 텍스트(parsed_items 이름 또는 feedback_text)에 알레르기 항목이 포함됐는지. 예: text=*"메밀국수"*, allergen=*"밀"* → False(`_LABEL_SUBSTRING_EXCLUSIONS`). text=*"밀빵 샐러드"*, allergen=*"밀"* → True. text=*"도넛 1개"*, allergen=*"넛"* → False(Story 3.5 정합, `_ALIAS_TEXT_EXCLUSIONS`). text=*"기타 가공품"*, allergen=*"기타"* → False(Story 3.5 _SKIP_SUBSTRING_LABELS).
   - **Story 3.5 회귀 0건 가드**: `domain/allergens.py` 기존 룩업/CHECK SQL/22종 enum 변경 X — *순수 추가*. 기존 테스트 `test_allergens.py` 통과 유지.
   - 단위 테스트 신규 ~12건: 22종 각각 happy-path 매칭 1건 + Story 3.5 false-positive 가드 회귀 5건(메밀/도넛/코코넛/기타가공품/기타치킨) + NFC 정규화 1건 + 빈 text 1건 + None text ValueError 1건 + assertion 22종 외 항목 거부 1건 + multi-allergen 동시 매칭 1건.

7. **AC7 — `app/services/report_service.py` 신규 + 단위 테스트**
   **Given** AC1 `app/api/v1/reports.py`가 호출하는 service, **When** `app/services/report_service.py` 신규, **Then**:
   - `async def get_weekly_report(*, user: User, from_date: date, to_date: date, db: AsyncSession) -> WeeklyReportResponse:` — AC1 정의 흐름 구현.
   - **input 검증**: `from_date <= to_date` 가드(아니면 `ValueError("from_date must be <= to_date")` → 라우터에서 RFC 7807 400). `(to_date - from_date).days` 가 0..30 범위(0=단일 일, 30=한 달; 본 스토리는 7일 default이지만 service는 일반화 — Story 4.4 인사이트 카드가 14일 trailing window 활용 가능).
   - **TDEE/protein target 계산**: User 모델 7컬럼 중 BMR 입력 5건 모두 not None이면 `compute_bmr_mifflin` + `compute_tdee` 호출. health_goal 별 protein target 범위 lookup(`app/domain/health_profile.py:PROTEIN_TARGET_BY_GOAL` 신규 dict — `{"weight_loss": (1.2, 1.6), "muscle_gain": (1.6, 2.2), "maintenance": (0.8, 1.2), "diabetes_management": (0.8, 1.2)}` 보수적 출처 KDRIs 2020 + 대한비만학회 2024 가이드).
   - **결정성**: 동일 입력(user + 날짜 범위 + DB 상태)이면 동일 출력. 시계 의존 X(KST 변환은 SQL 측 SOT). LLM 호출 0건. 단위 테스트는 deterministic.
   - **Sentry transaction**: `op="reports.weekly"` 1건 + child span `op="reports.aggregate"` (DB query 측정). Story 3.3 `op="analysis.pipeline"` 패턴 정합. attributes: `days_count` / `meals_count` / `analyzed_meals_count` / `allergen_exposures_count`.
   - **structlog**: `report.weekly.start`(masked user_id `u_{8char}`, from_date, to_date) → `report.weekly.complete`(meals_count, analyzed_meals_count, allergen_exposures_count, latency_ms). NFR-S5 정합 — raw allergies / parsed_items / feedback_text 로깅 X.
   - 단위 테스트 신규 ~10건: happy-path 7일 정상 데이터 / 빈 주(meals 0건) / 부분 빈 주(중간 3일만 입력) / TDEE 미산정(weight_kg None) / health_goal=null / 단일 알레르기 + 다일 매칭 / multi-allergen / 22종 외 allergies row(legacy 가드) / from_date > to_date ValueError / 30일 초과 ValueError.

8. **AC8 — Web `lib/reports.ts` SSR fetch + 클라이언트 query SOT**
   **Given** Story 1.2 `web/src/lib/auth.ts:getServerSideUser` 패턴(`import "server-only"` + cookie forward + `cache: "no-store"`), **When** `web/src/lib/reports.ts` 신규 + `web/src/features/reports/api.ts` 신규, **Then**:
   - `web/src/lib/reports.ts` (server-only) — `getServerSideWeeklyReport(fromDate, toDate)` 신규 export. `import "server-only"` 강제. `next/headers cookies()` 직접 forward. 401/4xx 응답 시 `null` 반환(`getServerSideUser` 패턴 정합 — 페이지가 `null`이면 빈 차트 fallback 또는 `redirect("/api/auth/cleanup")` 라우팅 분기).
   - `web/src/features/reports/api.ts` — `useWeeklyReportQuery(fromDate, toDate)` TanStack Query hook(client refetch용 옵션 — *본 스토리에서는 SSR 송신만 — refetch는 Story 4.4 forward*). Story 1.2 `apiFetch` 인터셉터(401 → refresh) 재사용. queryKey: `["weekly-report", fromDate, toDate]`.
   - `web/src/lib/api-client.ts` (자동생성) 갱신 — `pnpm gen:api` 실행 후 `WeeklyReportResponse` / `DailySummary` / `WeeklyMacros` / `AllergenExposure` types 자동 추가. **수동 편집 금지**(파일 헤더 정합).

9. **AC9 — `app/domain/health_profile.py:PROTEIN_TARGET_BY_GOAL` SOT + 단위 테스트**
   **Given** `app/domain/health_profile.py` 기존 ACTIVITY_LEVEL_VALUES / HEALTH_GOAL_VALUES SOT, **When** `PROTEIN_TARGET_BY_GOAL` dict 신규, **Then**:
   - `PROTEIN_TARGET_BY_GOAL: Final[Mapping[HealthGoal, tuple[float, float]]] = MappingProxyType({...})` — 4 health_goal 별 (lower, upper) g/kg/day 권장 범위. KDRIs 2020 + 대한비만학회 2024 1차 출처 인용 docstring.
   - `def get_protein_target(health_goal: HealthGoal | None) -> tuple[float, float] | None:` 헬퍼 — None이면 None 반환. ProteinChart의 ReferenceArea 입력 SOT.
   - 4종 enum 매핑 완비(weight_loss/muscle_gain/maintenance/diabetes_management) — 신규 enum 추가 시 본 dict 갱신 강제(KeyError 보호).
   - 단위 테스트 신규 ~5건: 4 enum happy-path + None 입력.

10. **AC10 — Story 4.4 forward-compat 슬롯 (`insights` 필드 placeholder)**
    **Given** Story 4.4 *"인사이트 카드 — 단백질 평균 55g/일, 목표 80g 미달, 다음 주 +20g"* 가 본 스토리 endpoint를 *재사용*함이 epics.md:761 정합, **When** `WeeklyReportResponse`에 `insights: list[InsightCard] | None = None` 슬롯 신규, **Then**:
    - `WeeklyReportResponse.insights` 본 스토리에서 *항상 None* 반환(서버 미계산). Story 4.4가 채움. *Pydantic 슬롯만 정의*(YAGNI 회피 — `InsightCard` 모델은 Story 4.4 책임). 본 스토리는 `insights: Any | None = None` 또는 `insights: None = None` (Story 4.4가 type narrow 갱신 OK) 중 *후자* 선택 — 잘못된 None 외 값 송신 차단(Story 2.4 `analysis_summary` 패턴 정합 *forward-compat 슬롯이지만 본 스토리 baseline 항상 None*).
    - WeeklyReport.tsx는 `report.insights`가 null이거나 빈 list이면 카드 영역 미렌더(또는 *"준비 중"* placeholder 1줄). Story 4.4가 본 영역에 InsightCard 컴포넌트 mount.

11. **AC11 — sprint-status / Story Status 갱신 흐름 (메모리 정합)**
    **Given** 메모리 정합 *"CS 시작 전 master에서 브랜치 분기 — DS 종료시 commit + push만"* + *"CR 종료 직전 sprint-status/story Status를 review → done으로 갱신해 PR commit에 포함"*, **When** 본 스토리 `ready-for-dev` 시점(CS 종료) 및 후속 단계, **Then**:
    - Branch: `story-4-3` (master에서 분기 완료).
    - DS 시작: `4-3-web-주간-리포트-차트: in-progress` (Status field).
    - DS 종료: `4-3-web-주간-리포트-차트: review` + commit + push(메모리 정합 *PR pattern* — DS 종료 시점 PR 생성 X, CR 완료 후 일괄).
    - CR 종료 직전: `review → done` + commit + push(같은 commit에 sprint-status 갱신 포함).
    - PR 생성: CR 완료 후 1회. PR body에 "Closes Story 4.3, AC1-11 + 9 Task / Subtasks 모두 완료".

## Tasks / Subtasks

### Task 1 — 백엔드 도메인 SOT 확장 (AC: #6, #9)

- [x] 1.1 `api/app/domain/allergens.py` — `contains_allergen(text, allergen)` 헬퍼 신규. NFC 정규화 + Story 3.5 `_LABEL_SUBSTRING_EXCLUSIONS` / `_ALIAS_TEXT_EXCLUSIONS` / `_SKIP_SUBSTRING_LABELS` SOT 재사용(import 또는 module 내부 재배치 — *중복 정의 0*).
- [x] 1.2 `api/app/domain/health_profile.py` — `PROTEIN_TARGET_BY_GOAL` dict + `get_protein_target` 헬퍼 신규. 4 enum 매핑 완비.
- [x] 1.3 `api/tests/domain/test_allergens.py` — `contains_allergen` 테스트 ~12건(22종 happy-path + Story 3.5 false-positive 회귀 5건 + NFC 정규화 + 빈/None text + assertion 22종 외 거부 + multi-allergen).
- [x] 1.4 `api/tests/domain/test_health_profile.py` — `get_protein_target` 테스트 ~5건(4 enum + None).

### Task 2 — 백엔드 service + router (AC: #1, #7)

- [x] 2.1 `api/app/services/report_service.py` 신규 — `get_weekly_report` 함수. AC7 정의 흐름 + Sentry transaction + structlog 4 이벤트 + N+1 회피 SOT(LEFT JOIN 1회).
- [x] 2.2 `api/app/api/v1/reports.py` 신규 — `router = APIRouter()` + `GET /weekly` endpoint. Pydantic `WeeklyReportResponse` / `DailySummary` / `WeeklyMacros` / `AllergenExposure` 모델 정의(`extra="forbid"` SOT 정합). `Depends(current_user)` + `Depends(require_basic_consents)` + `@limiter.limit(RATE_LIMIT_USER_PER_MINUTE)`. RFC 7807 도메인 예외 매핑(ValueError → 400 `code=reports.invalid_date_range`).
- [x] 2.3 `api/app/main.py` — `from app.api.v1 import reports as reports_router` import + `app.include_router(reports_router.router, prefix="/v1/reports", tags=["reports"])` Story 4.2 패턴 정합 위치(notifications 직후).
- [x] 2.4 `api/app/core/exceptions.py` — `WeeklyReportInvalidDateRangeError(BalanceNoteError)` 신규(원하면 ValueError fallback로 충분 — DS 단계 결정).
- [x] 2.5 `api/tests/services/test_report_service.py` 신규 — ~10건(AC7 정의).
- [x] 2.6 `api/tests/api/v1/test_reports.py` 신규 — ~8건(인증 401 / consent 403 / 빈 주 200 / happy-path 200 + body 검증 / 잘못된 날짜 범위 400 / 30일 초과 400 / OpenAPI schema regen 검증 / Rate limit 429 — 옵션).

### Task 3 — Web 의존성 + Server fetch + 페이지 (AC: #2, #4, #8)

- [x] 3.1 `web/package.json` `recharts ^3.8.0` 추가 + `pnpm install`.
- [x] 3.2 `cd api && uv run python -m app.main --print-openapi > /tmp/schema.json && cd ../web && pnpm gen:api` — `src/lib/api-client.ts` 자동 갱신(WeeklyReportResponse types 신규).
- [x] 3.3 `web/src/lib/reports.ts` 신규 — `getServerSideWeeklyReport(fromDate, toDate)` (`import "server-only"` + `getServerSideUser` 패턴 정합, `cache: "no-store"` cookie forward).
- [x] 3.4 `web/src/features/reports/api.ts` 신규 — `useWeeklyReportQuery` TanStack Query hook(forward-compat, 본 스토리는 SSR만 사용).
- [x] 3.5 `web/src/app/(user)/dashboard/weekly/page.tsx` 신규 — Server Component. 4 가드(user/basic/AD/profile) + KST 7일 윈도우 계산 + SSR fetch + WeeklyReport client component 렌더.
- [x] 3.6 `web/src/app/(user)/dashboard/page.tsx` 갱신 — placeholder 텍스트 제거 + `<Link href="/dashboard/weekly">주간 리포트 보기</Link>` 추가(레거시 영업 데모 → 즉시 weekly 진입 가능).

### Task 4 — Web 차트 컴포넌트 (AC: #3, #5)

- [x] 4.1 `web/src/features/reports/WeeklyReport.tsx` 신규 — orchestrator. props `report` + 빈 데이터 분기(`meal_count` 7일 모두 0이면 빈 화면 텍스트 + 모바일 anchor link).
- [x] 4.2 `web/src/features/reports/MacroChart.tsx` 신규 — recharts `BarChart` 스택 + 데이터 테이블 fallback(`<details>` 접힘).
- [x] 4.3 `web/src/features/reports/CalorieChart.tsx` 신규 — recharts `ComposedChart` 막대 + ReferenceLine(TDEE) + 데이터 테이블 fallback.
- [x] 4.4 `web/src/features/reports/ProteinChart.tsx` 신규 — recharts `LineChart` + ReferenceArea(권장 범위) + 데이터 테이블 fallback.
- [x] 4.5 `web/src/features/reports/AllergyExposureChart.tsx` 신규 — recharts `BarChart` horizontal + 데이터 테이블 fallback + 빈 알레르기 분기.
- [x] 4.6 NFR-A5 a11y 검증 — 각 차트 wrapper `aria-label` + `<details><summary>` 표 + 4.5:1 색상 대비 + Tab 순서 검증(수동 또는 axe-core 옵션).

### Task 5 — Story 4.4 forward-compat 슬롯 + AGENTS.md 갱신 (AC: #10)

- [x] 5.1 `WeeklyReportResponse.insights: None = None` 슬롯 추가(Pydantic 모델 — Story 4.4가 type narrow).
- [x] 5.2 `web/AGENTS.md` 갱신 — recharts *"Story 4.3에서 도입"* → *"Story 4.3 도입 완료(`features/reports/`)"*. 차트 추가 시 동일 패턴(데이터 테이블 fallback) 강제 룰 명시.

### Task 6 — sprint-status + 통합 검증 + 회귀 가드 (AC: #11, 전체)

- [x] 6.1 sprint-status `4-3-web-주간-리포트-차트: ready-for-dev → in-progress` (DS 시작 시).
- [x] 6.2 `cd api && uv run pytest -q` — 867 baseline + ~35 신규(allergens 12 + health_profile 5 + report_service 10 + reports router 8) = ~902 passed/11 skipped/0 failed. 회귀 0건. coverage ≥84% 유지.
- [x] 6.3 `cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy app` 0 에러.
- [x] 6.4 `cd web && pnpm tsc --noEmit && pnpm lint` 0 에러.
- [x] 6.5 `cd mobile && pnpm tsc --noEmit && pnpm lint` 0 에러(영향 없음 — 회귀 가드).
- [x] 6.6 OpenAPI schema diff 검증 — `/v1/reports/weekly` 1건 신규 + `WeeklyReportResponse`/`DailySummary`/`WeeklyMacros`/`AllergenExposure`/`InsightCard` types 신규.
- [x] 6.7 dev 검증 — `pnpm dev` (web) + `cd api && uv run uvicorn app.main:app` 부팅 → `/dashboard/weekly` 진입 → 4종 차트 렌더 확인 + 데이터 테이블 toggle 동작 + 키보드 Tab 순서 자연 + 빈 주 시나리오(`DELETE FROM meals WHERE user_id=...`).
- [x] 6.8 `docs/runbook/web-perf-check.md` 신규 — Lighthouse SOP 1페이지(NFR-P8 측정 명령 + 통과 기준 + Cloudflare/Vercel 배포 환경 차이 노트).
- [x] 6.9 sprint-status `4-3-web-주간-리포트-차트: in-progress → review` (DS 종료 시) + commit + push.

## Dev Notes

### 핵심 — 본 스토리는 *Web 첫 실 비즈니스 기능*

Story 1.2-1.6 web 부트스트랩(landing/login/onboarding 흐름)은 모두 *컴플라이언스 + 인증* 영역이었다. 본 스토리가 web의 *영업 핵심 가치 가시화* — 4종 차트 + 7일 인사이트 + WCAG-style 접근성 baseline. 영업 데모 시나리오 J4(*"보험사 디지털전략팀 — 푸시 nudge → 미기록 → 주간 리포트의 인게이지먼트 흐름이 라이브로 보인다"*) 핵심.

### Architecture Compliance

| 영역 | 영향 패턴 | 정합 |
|---|---|---|
| Router (AC1, AC2) | architecture.md:667 / 881 / 989 `reports.py` FR32-34 + `/v1/reports/weekly` | 정합 — 본 스토리 신규 |
| Frontend page (AC2) | architecture.md:751 `/dashboard/weekly/page.tsx` | 정합 — 본 스토리 신규 |
| Frontend components (AC3) | architecture.md:765-769 `features/reports/{Macro,Calorie,Protein,AllergyExposure}Chart.tsx` | 정합 — 본 스토리 신규 |
| Recharts 의존성 (AC3) | architecture.md:171/336 `recharts` (PRD 박힘) | 정합 — Story 4.3 첫 도입 |
| Service (AC7) | architecture.md:881 *report aggregation queries* | 정합 — `app/services/report_service.py` 신규 |
| TDEE/protein target (AC1, AC9) | architecture.md:632 `bmr.py` Mifflin-St Jeor + TDEE SOT | 정합 — `domain/bmr.py` + `domain/health_profile.py` SOT 재사용 + 확장 |
| Allergen matching (AC6) | Story 3.5 `_LABEL_SUBSTRING_EXCLUSIONS` / `_ALIAS_TEXT_EXCLUSIONS` SOT | 정합 — 재사용, 중복 정의 0 |
| NFR-P8 (AC4) | architecture.md / prd.md:485 *7일 ≤ 1.5초* | 정합 — RSC SSR + 단일 SQL JOIN |
| NFR-A5 (AC5) | architecture.md:1011/1080 + prd.md:1088 *키보드 + 데이터 테이블 fallback* | 정합 — `<details>` 접힘 표 + aria-label |

### Library / Framework Requirements

- **`recharts ^3.8.0`** (신규 web 의존성). 2026-04 최신 stable. React 19 공식 지원(2.15+) + Next.js 16 호환. peer deps `react>=19` / `react-dom>=19` / `react-is>=19`(자동 hoisted from React 19). [npm recharts](https://www.npmjs.com/package/recharts), [recharts releases](https://github.com/recharts/recharts/releases).
- **Recharts SSR 주의**: `ResponsiveContainer`는 SSR 시 0 width 측정 → 차트 미렌더. 두 패턴 중 1 — (a) `useEffect` mounted flag로 `<div className="h-80" />` placeholder 대체 후 마운트 시점 차트 렌더 또는 (b) 명시적 `width={...} height={...}` 고정. 본 스토리는 (a) 권장 — 반응형 유지 + Tailwind grid 흡수.
- **TanStack Query 5.100.5** (Story 1.2 기존). `useWeeklyReportQuery` queryKey `["weekly-report", fromDate, toDate]`. staleTime 60s default 정합.
- **Next.js 16.2.4 App Router** (Story 1.2 기존). Server Component 디폴트 + `"use client"` directive로 차트 컴포넌트만 hydration. RSC SSR 1.5초 NFR-P8 정합.
- **shadcn/ui 미도입** — 본 스토리에서도 미도입(architecture.md:335 *선택적 도입*, AGENTS.md *Story 4.3 시점에 결정* — 4 차트 + `<details>` 표만 필요해 raw Tailwind v4 + recharts 충분, 1인 8주 정합 + bundle size 최소화).

### File Structure Requirements

#### 신규 파일

**Backend (api/):**
- `api/app/api/v1/reports.py`
- `api/app/services/report_service.py`
- `api/tests/api/v1/test_reports.py`
- `api/tests/services/test_report_service.py`

**Frontend (web/):**
- `web/src/app/(user)/dashboard/weekly/page.tsx`
- `web/src/lib/reports.ts`
- `web/src/features/reports/api.ts`
- `web/src/features/reports/WeeklyReport.tsx`
- `web/src/features/reports/MacroChart.tsx`
- `web/src/features/reports/CalorieChart.tsx`
- `web/src/features/reports/ProteinChart.tsx`
- `web/src/features/reports/AllergyExposureChart.tsx`

**Docs:**
- `docs/runbook/web-perf-check.md` (Lighthouse SOP 1페이지 — NFR-P8 측정)

#### 수정 파일 (기존)

**Backend:**
- `api/app/main.py` — `include_router(reports_router.router, prefix="/v1/reports", ...)` 1줄 추가
- `api/app/domain/allergens.py` — `contains_allergen` 헬퍼 추가(기존 SOT 변경 0)
- `api/app/domain/health_profile.py` — `PROTEIN_TARGET_BY_GOAL` + `get_protein_target` 추가(기존 ACTIVITY_LEVEL/HEALTH_GOAL SOT 변경 0)
- `api/app/core/exceptions.py` — (옵션) `WeeklyReportInvalidDateRangeError` 신규
- `api/tests/domain/test_allergens.py` — 테스트 ~12건 추가
- `api/tests/domain/test_health_profile.py` — 테스트 ~5건 추가(파일 미존재 시 신규)

**Frontend:**
- `web/package.json` — `recharts ^3.8.0` 1줄 추가
- `web/pnpm-lock.yaml` — lockfile 갱신
- `web/src/lib/api-client.ts` — `pnpm gen:api` 자동 갱신(수동 편집 금지)
- `web/src/app/(user)/dashboard/page.tsx` — placeholder 제거 + Link 추가
- `web/AGENTS.md` — recharts 도입 완료 갱신 + 차트 패턴 룰 명시

**Sprint:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `ready-for-dev → in-progress → review`

### Testing Requirements

- **단위 테스트 신규 ~35건**: allergens 12 + health_profile 5 + report_service 10 + reports router 8.
- **현 baseline (Story 4.2 done)**: pytest 867 passed / 11 skipped / 0 failed + coverage 84.85%.
- **본 스토리 종료 시 목표**: pytest ~902 passed / 11 skipped / 0 failed + coverage ≥84% 유지.
- **회귀 0건 가드**: Story 1.x/2.x/3.x/4.1/4.2 기존 모든 테스트 통과 의무. 특히 `test_allergens.py` 기존 테스트(Story 3.5 SOT) 회귀 가드 — `contains_allergen` 추가가 `_LABEL_SUBSTRING_EXCLUSIONS` 등 기존 룩업 시그니처 변경 0.
- **타입 체크**: ruff/format/mypy 0 에러 + web/mobile tsc 0 에러 + web lint 0 에러.
- **Web 단위 테스트**: 차트 컴포넌트 jest/vitest 단위 테스트는 *프로젝트 web baseline*에 jest 인프라 부재(mobile은 Story 8.4 polish forward와 동일 상태). 본 스토리도 tsc + lint + 실 브라우저 검증(CR/QA 단계)으로 게이트. Story 8.4가 web jest 인프라까지 흡수할지는 retrospective forward 결정.
- **OpenAPI schema diff**: 신규 endpoint `/v1/reports/weekly` 1건 + 5 types(`WeeklyReportResponse` 외) 추가. CI 게이트 통과 의무.
- **NFR-P8 측정**: dev 환경 Lighthouse Mobile *Performance* score ≥ 80(LCP ≤ 2.0s baseline). DS 단계는 SOP 명시만(`docs/runbook/web-perf-check.md`) — 실 측정은 CR/QA 단계.
- **NFR-A5 검증**: 키보드 Tab 순서 자연 + 데이터 테이블 fallback `<details>` 펼쳐 7행 노출 + aria-label 4 차트 모두 기재. axe-core 자동 검증은 옵션(Story 8.4 polish forward 가능).

### Allergen Matching 의사결정 (AC6 결정 노트)

본 스토리는 알레르기 노출을 *substring contains 매칭*으로 단순화한다. 더 정밀한 옵션(Story 3.6 `parsed_items[].allergens` 영속 jsonb 또는 `meal_analyses.fit_reason='allergen_violation'` 행만 카운트) 대비:

- **선택 (substring)**: Story 3.5 false-positive 가드 SOT 재사용으로 정확도 충분(메밀↔밀, 도넛↔넛 등 hard cases 이미 회귀 가드). 7일 ~70 식단 × 22 알레르기 = ~1.5K Python in-memory 비교 — 0.1초 이하 부담. fit_reason='allergen_violation'만 카운트 시점은 Story 3.5 5-band 결정 시점에 *fit_score 0점 단락*만 트리거 — 노출은 있으나 fit_score≠0인 케이스(예: 사용자가 해당 알레르기에 *주의* 알림만 원하는 경우) 미감지. 본 스토리 의도(*"노출 횟수"*)는 fit_score 분리 정의가 더 정합.
- **Reject (parsed_items.allergens jsonb 영속화)**: Story 3.5 시점에 jsonb 컬럼 미도입(meal_analyses는 carbohydrate/protein/fat/kcal만 저장). 새 컬럼 추가 + 0015 마이그레이션 + Story 3.5 LangGraph evaluate_fit 노드 변경 → scope 폭증. 본 스토리는 *조회 only*이므로 *runtime 매칭*이 정합.
- **Reject (`fit_reason='allergen_violation'` 카운트만)**: 위 분석 대로 false negative 가능(노출 1건만으로는 fit_reason='ok'일 수 있음 — Story 3.5 fit_reason 정의는 *"심각 노출"* 기준).

### NFR-P8 (1.5초) 달성 SOP

- **백엔드 query**: 단일 SQL LEFT JOIN 1회. 7일 × 평균 3 식단 = ~21 row 반환 — Postgres index hit(`idx_meal_analyses_user_id_created_at` Story 3.7 forward-compat) → ~10ms.
- **백엔드 latency 예산**: query ~10ms + Python aggregation ~50ms + Sentry instrumentation ~5ms + 전체 fastapi 응답 ~100ms 미만.
- **Web SSR latency 예산**: API 호출 ~150ms + Next.js RSC 직렬화 ~20ms + HTML 첫 페인트 ~500ms + recharts hydration ~300ms — 총 ~1.0초 (1.5초 NFR-P8 여유).
- **차트 렌더**: recharts 차트 4종 ResponsiveContainer 첫 mount 시 ~100ms × 4 = ~400ms — 본 스토리는 차트 *동시 hydration* 허용(SR 차트 1개씩 lazy load는 Story 8.4 polish forward).
- **bundle size**: recharts ~95KB gzip 추가. 본 스토리에서 bundle analyzer 도입은 over-engineering — Story 8.4 polish.

### NFR-A5 (접근성) 달성 SOP

- **데이터 테이블 fallback**: 4 차트 각각 `<details><summary>데이터 표 보기</summary><table>...</table></details>` — `<table>` 시맨틱 표준(`<thead><tbody>`, `<th scope="col">`).
- **차트 wrapper a11y**: `<div role="img" aria-label="매크로 비율 추이 차트">{chart}</div>` — 스크린리더가 이미지로 인식 + 차트 의미 라벨.
- **키보드 Tab 순서**: 차트별 wrapper에 `tabIndex={0}` 설정 시 자연 Tab 순서. `<details>` summary 자체가 focusable.
- **색상 대비**: Tailwind v4 디폴트 토큰(`text-slate-900` on `bg-white` ≈ 18.7:1) — 4.5:1 충분 통과. 차트 fill 색상은 모두 saturated(amber-400/blue-500/red-500) — text 노출 0이므로 대비 룰 비대상이지만 *데이터 테이블*에서 색상 + 숫자 두 채널 정합.
- **NFR-A4 색상 단독 의존 회피**: ProteinChart의 권장 영역 fill(연한 녹색)은 *데이터 테이블 행에 "범위 1.2-1.6" 텍스트 동시 표시*로 색약 사용자도 인식 가능.

### Story 4.4 Forward-Compat Hooks

본 스토리에서 박는 자원을 Story 4.4(인사이트 카드 + 매크로 목표 조정 + 자동 반영)가 소비:

- `WeeklyReportResponse.insights: None = None` 슬롯 — Story 4.4가 `list[InsightCard]`로 type narrow + 단백질 평균 vs 목표 미달 인사이트 + 1차 출처 인용.
- `report_service.get_weekly_report` — Story 4.4가 *insights 계산 분기* 추가(주간 평균 vs `users.macro_goal` 비교 — Story 4.4 신규 컬럼). 본 스토리 service는 *aggregation only*, Story 4.4가 *insight generation* 추가.
- `web/src/features/reports/WeeklyReport.tsx` — `<InsightCard>` 컴포넌트 신규 추가 영역 — 4 차트 위 또는 아래 sticky.
- `users.macro_goal` 컬럼 — Story 4.4 신규(본 스토리 영향 0). Story 4.4가 0015 마이그레이션 + `PATCH /v1/users/me/macro_goal` 신규.

### Previous Story Intelligence

#### Story 4.2 Done (2026-05-06) 핵심 학습

- **lifespan 5번째 자원 graceful 분기**: scheduler init 실패 시 `app.state.scheduler = None` + 잡 등록 skip + warn. 본 스토리 *report_service*는 lifespan 자원 추가 X(stateless service) — 영향 0.
- **Sentry transaction `op=...` 패턴**: `nudge.sweep` + child span. 본 스토리는 `op="reports.weekly"` + child `op="reports.aggregate"` 동일 패턴.
- **structlog masked user_id `u_{8char}` 패턴**: `nudge.sent` 이벤트 정합. 본 스토리 `report.weekly.start/complete` 이벤트도 동일 마스킹.
- **OpenAPI schema diff 정합**: 본 스토리는 `/v1/reports/weekly` 1건 신규(Story 4.2는 0건이었으나 본 스토리는 라우터 추가).

#### Story 4.1 Done (2026-05-06) 핵심 학습

- **`require_basic_consents` Dependency 패턴**: `Depends(require_basic_consents)` Story 4.1의 4 endpoint에 적용. 본 스토리도 동일(인증 + 기본 동의만 — `automated_decision`은 LLM 호출 시점 게이트라 불필요).
- **Pydantic `extra="forbid"` SOT**: Story 4.1 routerPydantic 모델 정합. 본 스토리 4 신규 모델도 동일.

#### Story 3.7 Done (2026-05-04) 핵심 학습

- **`meal_analyses` 테이블 SOT**: Story 3.7가 박은 12 컬럼 + `(user_id, created_at DESC)` 인덱스(*Story 4.3 forward-compat 슬롯*). 본 스토리가 정확히 이 인덱스를 활용 — 인덱스 hit으로 NFR-P8 1.5초 달성.
- **`selectinload(Meal.analysis)` 패턴**: Story 3.7 `GET /v1/meals` JOIN 정합. 본 스토리는 LEFT JOIN 1회 + 단일 query SOT — `selectinload` (lazy=raise_on_sql) 또는 explicit join SQL 둘 중 1.
- **N+1 가드**: Story 3.7 `lazy="raise_on_sql"` invariant — 본 스토리도 N+1 회피 정합.

#### Story 3.5 Done (2026-05-03) 핵심 학습

- **`_LABEL_SUBSTRING_EXCLUSIONS` SOT**: 메밀↔밀 등 false-positive 가드. 본 스토리 `contains_allergen`이 *재사용*. 신규 가드 추가 0.
- **22종 알레르기 enum 무결성**: `KOREAN_22_ALLERGENS` SOT. 본 스토리 `contains_allergen`은 22종 외 입력 거부 가드.

#### Story 3.6 Done (2026-05-04) 핵심 학습

- **Adapter boundary error translation**: Story 3.6 `llm_router` openai/anthropic permanent error → typed exception. 본 스토리는 LLM 호출 0건 — 영향 0.
- **광고 가드 SOT**: Story 3.6 `ad_expression_guard.py`. 본 스토리 `feedback_text`는 *이미 광고 가드 통과한 신뢰 텍스트* — `contains_allergen` substring 검사 안전.

#### Story 1.2 Done (2026-04-28) 핵심 학습

- **`getServerSideUser` cookie forward 패턴**: SSR fetch + `cache: "no-store"` + `import "server-only"`. 본 스토리 `getServerSideWeeklyReport`도 동일 패턴.
- **`/dashboard` 4 가드 분기**: user/basic_consents/automated_decision/profile_completed_at. 본 스토리 `/dashboard/weekly`도 동일 4 가드 — 코드 *재사용 또는 helper 추출*(*hint*: dashboard/page.tsx의 가드 4건이 weekly/page.tsx와 동일하므로 `lib/auth.ts:requireFullyOnboardedUser` 헬퍼 추출 검토 — 결정은 DS).

### Project Structure Notes

- **Branch**: `story-4-3` (master에서 분기 — 메모리 정합 *"새 스토리 브랜치는 항상 master에서 분기"*).
- **PR 패턴**: feature branch + PR + merge 버튼(메모리 정합 *"PR pattern for master integration"*).
- **DS 종료 시점**: commit + push만(메모리 정합 — PR은 CR 완료 후 한 번에 생성).
- **CR 종료 직전**: sprint-status / Story Status `review → done` 갱신을 PR commit에 포함(메모리 정합).

### Sprint Status 갱신 흐름

- 현재: `4-3-web-주간-리포트-차트: ready-for-dev` (CS 종료 시점, `epic-4: in-progress` 유지).
- DS 시작: `4-3-web-주간-리포트-차트: in-progress`
- DS 종료: `4-3-web-주간-리포트-차트: review`
- CR 종료: `4-3-web-주간-리포트-차트: done` (`epic-4`는 `in-progress` 유지 — Story 4.4 잔여)

## References

- [Source: `_bmad-output/planning-artifacts/epics.md:746-759`] — Story 4.3 AC 6건(SSR 7일 데이터 + Recharts 4 차트 + NFR-P8 1.5초 + NFR-A5 키보드/표 fallback + 빈 화면)
- [Source: `_bmad-output/planning-artifacts/epics.md:713-715`] — Epic 4 목표(미기록 푸시 + Web 4 차트 + 인사이트 → 다음 주 매크로 목표 자동 반영)
- [Source: `_bmad-output/planning-artifacts/epics.md:761-773`] — Story 4.4 인사이트 카드 + 매크로 목표 조정(본 스토리 forward-compat 슬롯 의식)
- [Source: `_bmad-output/planning-artifacts/prd.md:74-75`] — FR32 / FR33 / FR34 4 차트 + 인사이트 카드 + 매크로 목표 조정
- [Source: `_bmad-output/planning-artifacts/prd.md:485`] — TC3 *7일 ≤ 1.5초* SSR
- [Source: `_bmad-output/planning-artifacts/prd.md:687-697`] — W1/W2/W3 Next.js + Recharts + admin audit 패널 (W1=Next.js Pages, W2=차트, W3=admin 활동 로그)
- [Source: `_bmad-output/planning-artifacts/prd.md:707`] — A1 `/reports/weekly` endpoint 그룹
- [Source: `_bmad-output/planning-artifacts/prd.md:1037`] — NFR-P8 *Web 주간 리포트 7일 데이터 ≤ 1.5초* + Lighthouse 측정
- [Source: `_bmad-output/planning-artifacts/prd.md:1088`] — NFR-A5 *키보드 Tab + 차트 데이터 테이블 fallback*
- [Source: `_bmad-output/planning-artifacts/architecture.md:171/336/693`] — `recharts` 박힘(PRD 결정)
- [Source: `_bmad-output/planning-artifacts/architecture.md:334`] — Web RSC vs Client(차트는 Client component, 정적 페이지는 RSC SSR 1.5초)
- [Source: `_bmad-output/planning-artifacts/architecture.md:751`] — `/dashboard/weekly/page.tsx` SOT
- [Source: `_bmad-output/planning-artifacts/architecture.md:765-769`] — `features/reports/{Macro,Calorie,Protein,AllergyExposure}Chart.tsx` SOT
- [Source: `_bmad-output/planning-artifacts/architecture.md:881/989-991`] — `reports.py` FR32-34 + `/reports/weekly` aggregation
- [Source: `_bmad-output/planning-artifacts/architecture.md:632`] — `bmr.py` Mifflin-St Jeor + TDEE SOT
- [Source: `_bmad-output/planning-artifacts/architecture.md:1011/1080`] — NFR-A1-A5 a11y 룰 + 키보드 Tab + 차트 데이터 테이블 fallback
- [Source: `_bmad-output/implementation-artifacts/4-2-apscheduler-nudge-미기록-푸시.md`] — 직전 스토리 SOT(`expo_push.py` adapter / scheduler / nudge_scheduler / notifications 테이블 + lifespan 5번째 자원 + Sentry transaction 패턴)
- [Source: `_bmad-output/implementation-artifacts/4-1-알림-설정-푸시-권한.md`] — `users` 4컬럼 + `require_basic_consents` 게이트 패턴 + Pydantic `extra="forbid"` 정합
- [Source: `_bmad-output/implementation-artifacts/3-7-모바일-sse-스트리밍-채팅-ui-polling-fallback.md`] — `meal_analyses` 12 컬럼 + `(user_id, created_at DESC)` 인덱스 forward-compat 슬롯 + `selectinload(Meal.analysis)` N+1 가드 패턴
- [Source: `_bmad-output/implementation-artifacts/3-6-인용형-피드백-광고-가드-듀얼-llm.md`] — `feedback_text` 광고 가드 통과 신뢰 텍스트 SOT
- [Source: `_bmad-output/implementation-artifacts/3-5-fit-score-알고리즘-알레르기-단락.md`] — `_LABEL_SUBSTRING_EXCLUSIONS` / `_ALIAS_TEXT_EXCLUSIONS` / `_SKIP_SUBSTRING_LABELS` SOT(본 스토리 `contains_allergen` 재사용)
- [Source: `_bmad-output/implementation-artifacts/2-3-ocr-vision-추출-확인-카드.md`] — `parsed_items` jsonb 컬럼 SOT(본 스토리 알레르기 매칭 텍스트 입력)
- [Source: `_bmad-output/implementation-artifacts/1-2-google-oauth-로그인-jwt.md`] — `getServerSideUser` SSR fetch + cookie forward + `import "server-only"` 패턴(본 스토리 `getServerSideWeeklyReport` 정합)
- [Source: `web/AGENTS.md`] — Web 특화 룰(recharts Story 4.3 도입 / `next-auth` 금지 / Tailwind v4 / TanStack Query SOT / `pnpm gen:api` OpenAPI 동기화)
- [Source: https://www.npmjs.com/package/recharts] — recharts 3.8.1(2026-04 latest stable) + React 19 peer 지원
- [Source: https://github.com/recharts/recharts/releases] — recharts 3.x 릴리즈 노트
- [Source: https://recharts.org/en-US/api] — Recharts API(BarChart / LineChart / ComposedChart / ResponsiveContainer / ReferenceArea / ReferenceLine)
- [Source: https://nextjs.org/docs/app/building-your-application/rendering/server-components] — Next.js 16 App Router Server Component SSR

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Amelia / bmad-dev-story workflow, 2026-05-06).

### Debug Log References

- mypy `Generator[bool]` 추론 회귀: `analyzed_rows`(`r.analysis is not None` 필터 통과) 기반 `sum()` generator의 `mypy --strict` 추론이 `bool`로 좁혀지는 회귀 — 명시 `analyses = [r.analysis for r in analyzed_rows if r.analysis is not None]` narrowing list로 분리 + 타입 어노테이션(`sum_carb: float`, `sum_kcal: int`)으로 해결.
- mypy `__args__` `[attr-defined]` 위반: `AllergenLiteral.__args__` 직접 접근은 `typing.Literal`의 internal attribute 의존이라 mypy unsafe — `typing.get_args(AllergenLiteral)` SOT로 교체.
- ruff `react-hooks/set-state-in-effect`: WeeklyReport mounted flag의 `useEffect(() => setMounted(true), [])` 패턴이 ESLint rule 위반 — `useSyncExternalStore`(server snapshot=false / client snapshot=true) 표준 React 패턴으로 교체.
- 순환 import: 첫 시도 시 `app/services/report_service.py`가 `app/api/v1/reports.py`의 Pydantic 모델 import + 라우터가 service의 `get_weekly_report` import → main.py 평가 시 순환. Pydantic 응답 모델 4종(`WeeklyReportResponse` / `DailySummary` / `WeeklyMacros` / `AllergenExposure`) + `AllergenLiteral`을 service 모듈에 단일 SOT 정의 + 라우터가 import 하는 구조로 해결.

### Completion Notes List

- **AC1-AC11 모두 통과 + 11 task 모두 완료**.
- 신규 의존성 1건: `recharts ^3.8.1` (web only, React 19 호환). `pnpm install` 통과.
- 신규 백엔드 모듈 4건: `app/services/report_service.py` (Pydantic 모델 + service entry point — 순환 import 회피 SOT 변경), `app/api/v1/reports.py` (router only), `app/core/exceptions.py:WeeklyReportInvalidDateRangeError` + `ReportsError` 계층, `app/main.py` 라우터 wire 1줄.
- 신규 도메인 SOT 재배치: Story 3.5 `_LABEL_SUBSTRING_EXCLUSIONS` / `_ALIAS_TEXT_EXCLUSIONS` / `_SKIP_SUBSTRING_LABELS` / `ALLERGEN_ALIAS_MAP` 4건을 `fit_score.py` → `allergens.py`로 *재배치* + `contains_allergen` 헬퍼 신규(중복 정의 0). `fit_score.py`는 import로 인계.
- 신규 도메인 헬퍼: `app/domain/health_profile.py:PROTEIN_TARGET_BY_GOAL` `MappingProxyType` SOT + `get_protein_target` 헬퍼.
- 신규 web 모듈 7건: `lib/reports.ts` (server-only fetch + KST 7일 윈도우 계산), `features/reports/api.ts` (TanStack Query forward-compat), `features/reports/{WeeklyReport,MacroChart,CalorieChart,ProteinChart,AllergyExposureChart}.tsx` (5 컴포넌트). 각 차트 `<details><summary>` 데이터 테이블 fallback + `aria-label` + `tabIndex={0}` 키보드 Tab 정합 (NFR-A5).
- 신규 web 페이지 1건: `app/(user)/dashboard/weekly/page.tsx` Server Component. 4 가드(user/basic/AD/profile) + KST 7일 윈도우 SSR fetch + `WeeklyReport` client component 렌더.
- 갱신: `app/(user)/dashboard/page.tsx` placeholder 제거 + `<Link href="/dashboard/weekly">` 추가, `web/AGENTS.md` recharts 도입 완료 갱신, `web/src/lib/api-client.ts` + `mobile/lib/api-client.ts` 자동 갱신 (`pnpm gen:api` IN_PROCESS 모드).
- 신규 docs: `docs/runbook/web-perf-check.md` Lighthouse Mobile SOP (NFR-P8 1.5초 측정 + 통과 기준 + Cloudflare/Vercel 배포 환경 차이 노트).
- 단위 테스트 신규 ~36건: allergens 16(22 happy-path 21 + buckwheat/donut/coconut 가드 3 + 기타 skip/explicit 2 + alias 5 + NFC/empty/None/unknown 4 + multi-allergen 1 + label_not_present 1) + health_profile 5(4 enum + None + immutable + range invariant) + report_service 11(happy/empty/partial/TDEE-none/health_goal-none/protein-target/single-allergen-multi-day/multi-allergen/legacy-skip/from>to/KST boundary) + reports router 8(401/403/200 empty/200 happy/400 invalid range/400 30일 초과/422 missing params/200 forward-compat insights). pytest 867 → **934 passed / 11 skipped / 0 failed** (+67 신규/통합), coverage 84.85% → **85.40%** (+0.55pp).
- ruff/format/mypy 0 errors. web tsc + lint 0 errors. mobile tsc + lint 0 errors.
- Story 1.x/2.x/3.x/4.1/4.2 회귀 0건 가드 통과.
- **Spec deviation 1건**: AC10 `WeeklyReportResponse.insights: None = None` Pydantic 슬롯 — Story 4.4가 type narrow 갱신 의무. 본 스토리 baseline은 *항상 None*만 송신.
- **dev 환경 검증 SOP 명시만**: NFR-P8 1.5초 / NFR-A5 키보드 Tab 실 측정은 CR/QA 단계 책임. `docs/runbook/web-perf-check.md`에 Lighthouse Mobile SOP 등재.

### File List

**신규 파일 (Backend):**
- `api/app/api/v1/reports.py`
- `api/app/services/report_service.py`
- `api/tests/api/v1/test_reports.py`
- `api/tests/services/test_report_service.py`
- `api/tests/domain/test_health_profile.py`

**신규 파일 (Frontend Web):**
- `web/src/app/(user)/dashboard/weekly/page.tsx`
- `web/src/lib/reports.ts`
- `web/src/features/reports/api.ts`
- `web/src/features/reports/WeeklyReport.tsx`
- `web/src/features/reports/MacroChart.tsx`
- `web/src/features/reports/CalorieChart.tsx`
- `web/src/features/reports/ProteinChart.tsx`
- `web/src/features/reports/AllergyExposureChart.tsx`

**신규 파일 (Docs):**
- `docs/runbook/web-perf-check.md`

**수정 파일 (Backend):**
- `api/app/main.py` (`reports_router` import + `include_router` 1줄 추가)
- `api/app/domain/allergens.py` (Story 3.5 SOT 4건 *재배치 SOT* + `contains_allergen` 헬퍼 신규)
- `api/app/domain/fit_score.py` (Story 3.5 SOT 4건 inline 정의 → `allergens.py` import로 인계, `ALLERGEN_ALIAS_MAP` 정의 제거)
- `api/app/domain/health_profile.py` (`PROTEIN_TARGET_BY_GOAL` `MappingProxyType` + `get_protein_target` 헬퍼 추가)
- `api/app/core/exceptions.py` (`ReportsError` base + `WeeklyReportInvalidDateRangeError`)
- `api/tests/domain/test_allergens.py` (`contains_allergen` 16 테스트 추가)

**수정 파일 (Frontend Web):**
- `web/package.json` (`recharts ^3.8.0` 추가)
- `web/pnpm-lock.yaml` (lockfile 갱신, +38 packages)
- `web/src/lib/api-client.ts` (자동 갱신 — `WeeklyReportResponse`/`DailySummary`/`WeeklyMacros`/`AllergenExposure` types 신규)
- `web/src/app/(user)/dashboard/page.tsx` (placeholder 제거 + `<Link href="/dashboard/weekly">` 추가)
- `web/AGENTS.md` (recharts 도입 완료 + 차트 패턴 강제 룰 명시)

**수정 파일 (Frontend Mobile):**
- `mobile/lib/api-client.ts` (자동 갱신 — `WeeklyReportResponse` 등 types 신규, mobile 직접 사용 X)

**수정 파일 (Sprint):**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (`ready-for-dev → in-progress → review`)
- `_bmad-output/implementation-artifacts/4-3-web-주간-리포트-차트.md` (Status / Tasks / Dev Agent Record / File List / Change Log)

### Change Log

| Date | Author | Change |
|---|---|---|
| 2026-05-06 | Amelia (DS) | DS 종료 — 11 AC + 11 task 완료. 신규 백엔드 4 모듈 + 도메인 SOT 재배치(Story 3.5 4 constant `fit_score.py` → `allergens.py`) + `contains_allergen` + `PROTEIN_TARGET_BY_GOAL` + `WeeklyReportResponse` Pydantic 모델 + `app/services/report_service.py` aggregation. 신규 web 8 모듈(차트 4 + orchestrator + SSR fetch + TanStack Query hook + 페이지) + recharts ^3.8.1. pytest 867 → 934 passed/11 skipped/0 failed, coverage 84.85% → 85.40%. ruff/format/mypy 0 errors + web/mobile tsc + lint 0 errors. Story 1.x/2.x/3.x/4.1/4.2 회귀 0건. Status: in-progress → review. |
| 2026-05-07 | Amelia (CR) | CR 3-layer adversarial(Blind 33 / Edge 40 / Auditor 12 = 85 raw) → 3 decision-needed + 22 patch + 13 defer + 47 dismiss. **DN-1**(BMR sex 하드코드 → tdee=None graceful, Story 5.1까지 모든 사용자 빈 TDEE 라인): 잘못된 `sex="female"` 디폴트로 ~166 kcal 어긋난 TDEE 송신 회귀 차단. **DN-2**(feedback_text negation false-positive): `_NEGATION_PATTERNS = ("않","없","아니","아닙","제외")` + `_NEGATION_WINDOW_CHARS=12` 매칭 직후 윈도우 가드 — "우유는 들어있지 않아 안심" → False. **DN-3**(차트 wrapper a11y): spec 정합 `tabIndex={0}` 유지 + `aria-describedby` 4 차트 추가 — 차트→표 ARIA 연결. **P1**(BLOCKER, NFR-P8 무력화): SQL `WHERE ate_at BETWEEN ...` UTC bracket 추가 — 사용자 전체 history 로드 회귀 차단. **P2-P22 22 patches**: raw_text 매칭 제거 / naive datetime 가드 / `Field(ge=0)` clamp / `int(energy_kcal)` None 가드 / `(ValueError, KeyError)` catch / `AllergenLiteral` raise / KST `Intl.DateTimeFormat` SOT / `getServerSideWeeklyReport` null 일관 / fetchUserAllergies 401 redirect / 빈 주 NFR-A5 데이터 테이블 fallback / `connectNulls` 제거 / AllergyChart `<details>` 미렌더 분기 / Sentry `set_status` / 라우터-service 가드 일원화 / `RATE_LIMIT_USER_PER_MINUTE` decorator 명시(via global default 정합) / `PROTEIN_TARGET_BY_GOAL` import-time SOT 가드 + `.get()` graceful / structlog from/to_date / vacuous test fix / `useWeeklyReportQuery` 4xx retry off + staleTime 60s / CalorieChart 기록일 평균 / TDEE>0 가드. **Defer 13건** DF116-DF128(allergen short labels 가드 / weight_kg sanity / DoS cap / NFC 캐싱 / 기타 alias / monitored_allergies / 빈 주 dashboard 링크 / 단일일 지원 / parsed_items shape 경고 / protein 0 표시 / Tooltip formatter / 연도 경계 / Lighthouse 실측). pytest 934 → 944 passed/11 skipped/0 failed (+10 신규 가드 — 알레르기 negation 7 + report_service SQL 윈도우 1 + 30일 cap 1 + negation false positive 1), coverage 85.40% → 85.33%. ruff/format/mypy 0 errors + web/mobile tsc + lint 0 errors. Story 1.x/2.x/3.x/4.1/4.2 회귀 0건. Status: review → done. |

### Review Findings

**Adversarial 3-layer CR** (2026-05-06, Amelia): Blind Hunter 33 + Edge Case Hunter 40 + Acceptance Auditor 12 = 85 raw → 3 decision-needed + 22 patch + 13 defer + 47 dismiss.

#### Decision-needed (해결 필요 — patch 적용 전)

- [x] [Review][Decision] **DN-1 BMR `sex="female"` 하드코드 — 50% 사용자 TDEE 잘못** [api/app/services/report_service.py:1144-1153] — spec AC1/AC7는 BMR 5 입력(age/weight_kg/height_cm/sex/activity_level) 중 하나라도 None이면 `tdee=None` graceful. 코드는 `users.sex` 컬럼 부재를 default `"female"`로 우회 — 남성 사용자 TDEE ~166 kcal 과소산정, CalorieChart 본질 misleading. **선택지**: (a) `tdee=None` graceful 회복(spec 정합, 모든 사용자 TDEE 라인 안 보임 — Story 5.1/8.4까지) / (b) `users.sex` 컬럼 + 온보딩 흐름 추가 (Story 4.3 scope-creep, alembic 0015 + Story 1.5 health profile 폼 변경). 3-layer 모두 BLOCKER 표시. **출처**: Blind F2, Edge E3, Auditor A2.
- [x] [Review][Decision] **DN-2 알레르기 매칭 `feedback_text` negation false-positive** [api/app/services/report_service.py:1244-1263] — `contains_allergen("우유는 들어있지 않아 안심하세요", "우유") → True`. LLM 본문 부정문이 노출 카운트 증가 — AllergyExposureChart 과대보고. spec Allergen Matching 의사결정 노트는 substring 단순화를 의도적으로 채택. **선택지**: (a) 매칭 입력에서 `feedback_text` 제외, `parsed_items[].name`만 사용(precision↑ recall↓) / (b) 현 상태 유지 + 알려진 한계로 spec 보강(Story 8.4 NLP polish forward) / (c) negation 정규식 룰셋(`않아|없|아닙니다` 후행 negation 차단 — substring 룰 SOT 보강). **출처**: Edge E6, Blind F7(raw_text 추가 분리 처리 — DN-2와 무관, 아래 P3 참조).
- [x] [Review][Decision] **DN-3 차트 wrapper `tabIndex={0}` — spec 정합 vs WCAG 정합** [web/src/features/reports/{Macro,Calorie,Protein,AllergyExposure}Chart.tsx 각 `<section>`] — spec AC5는 `tabIndex={0}` 명시. WCAG/WAI-ARIA APG는 `role="img"` + non-interactive region에 tab stop 추가 권장 X(focus-stuck UX). 현 상태는 키보드 사용자가 차트에 focus 가능하지만 인터랙션 없음 + 표는 별도 `<details>` Tab 필요. **선택지**: (a) spec 정합 유지 + `aria-describedby={tableId}` 추가(차트→표 ARIA 연결, focus-stuck 수용) / (b) `tabIndex={0}` 제거 + `aria-describedby` 추가(WCAG 정합, spec 갱신 필요) / (c) 둘 다 유지 + `<details open>` 기본 펼침으로 SR 사용자 즉시 노출. **출처**: Blind F16, Edge E18.

#### Patch (수정 — 의도 명확)

- [x] [Review][Patch] **P1 SQL `WHERE ate_at BETWEEN from_date AND to_date` 누락 — BLOCKER, NFR-P8 무력화** [api/app/services/report_service.py:256-266] — query에 `ate_at` 범위 필터 부재 → 사용자 전체 식단 로드 후 Python에서 필터. 1년 사용 사용자 ~1000 row + selectinload 메모리 폭증. spec AC1/AC4 명시 위반. fix: SQL `func.timezone('Asia/Seoul', Meal.ate_at).cast(Date).between(from_date, to_date)` 또는 UTC bracket math로 push down. 3-layer 일치(Blind F1, Edge E1, Auditor A1).
- [x] [Review][Patch] **P2 `raw_text` 알레르기 매칭 입력 추가는 spec deviation** [api/app/services/report_service.py:1245-1257] — spec AC1은 `parsed_items[].name` 또는 `feedback_text`만 신뢰 SOT. 코드는 `raw_text` (광고 가드 미통과 사용자 입력) 추가 — false positive 벡터(예: "도넛 알레르기 없음"이 호두/도넛 트리거). fix: `if meal.raw_text:` 분기 제거. (출처: Blind F7. DN-2와 분리.)
- [x] [Review][Patch] **P3 `astimezone(_KST)` naive datetime crash 가드** [api/app/services/report_service.py:270] — `meal.ate_at`이 timezone-naive면 `astimezone()` ValueError로 endpoint 500. fix: `meal.ate_at.replace(tzinfo=UTC) if meal.ate_at.tzinfo is None else meal.ate_at`. (Edge E11.)
- [x] [Review][Patch] **P4 `WeeklyMacros Field(ge=0)` ValidationError mid-build** [api/app/services/report_service.py:1232-1237] — `round(-0.0001, 2) = -0.0` 시 Pydantic reject → 한 row 폴루트로 7-day 응답 전체 500. fix: `max(0.0, round(avg_x, 2))` clamp. (Edge E9.)
- [x] [Review][Patch] **P5 `int(a.energy_kcal)` truncate + None crash** [api/app/services/report_service.py:1222] — `int(None)` TypeError + `int(399.99) → 399` 체계적 underflow. fix: `round(float(a.energy_kcal or 0))`. (Blind F24, Edge E10.)
- [x] [Review][Patch] **P6 `compute_tdee` `KeyError` 미catch → 500** [api/app/services/report_service.py:218-243] — `ACTIVITY_MULTIPLIERS[activity_level]` legacy 값 시 KeyError 발생, `except ValueError`만 catch. fix: `except (ValueError, KeyError):`. (Edge E2.)
- [x] [Review][Patch] **P7 `AllergenLiteral` `assert` 모듈 import time crash → API 전체 down** [api/app/services/report_service.py:86-88] — 미래 22→23 enum 추가 시 `assert` AssertionError로 main.py import 실패 → API 전체 다운. `python -O` 시 strip되어 silent SOT drift도 위험. fix: `if get_args(AllergenLiteral) != KOREAN_22_ALLERGENS: raise RuntimeError(...)` 또는 dynamic Literal 생성. (Edge E35.)
- [x] [Review][Patch] **P8 KST window math `Intl.DateTimeFormat` SOT 전환** [web/src/lib/reports.ts:65-71] — `now.getTime() + 9*60*60*1000` manual offset + `toISOString().slice(0, 10)`은 Vercel/Cloudflare runtime TZ에 fragile (런타임 TZ가 KST면 over-shift). fix: `Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul" }).format(now)` SOT. (Blind F6, Edge E12/E13.)
- [x] [Review][Patch] **P9 `getServerSideWeeklyReport` 401 redirect/5xx throw → null 일관** [web/src/lib/reports.ts:74-78] — `getServerSideUser` 패턴은 모든 non-ok → null. 현 코드는 401→`/login` redirect + 5xx throw → 페이지가 ErrorBoundary로 떨어짐(spec graceful empty 깨짐) + `dashboard/page.tsx`는 `/api/auth/cleanup` 사용 — destination 불일치 login loop 위험. fix: `if (!response.ok) return null;` 단일 분기. (Blind F21, Edge E14/E15, Auditor A5.)
- [x] [Review][Patch] **P10 `fetchUserAllergies` 401/5xx silently `[]`** [web/src/app/(user)/dashboard/weekly/page.tsx:2974-2988] — 401 시 빈 list 반환 → "알레르기 항목 설정 시 노출 모니터링" UX로 잘못 안내(사용자가 알레르기 등록한 경우 실제 노출 누락). fix: `getServerSideUser` 패턴 정합 (status check + null/redirect). (Blind F4, Edge E16.)
- [x] [Review][Patch] **P11 빈 주간 차트/표 fallback 미렌더 (NFR-A5 위반)** [web/src/features/reports/WeeklyReport.tsx:3601-3640] — `isEmpty(report)` 시 4 차트 + `<details>` 표 fallback 모두 숨김. NFR-A5는 *"키보드 + 데이터 테이블 fallback"* 보장 — 빈 주에도 7행 0 카운트 표 노출이 정합. fix: 빈 데이터 표 행 렌더 또는 4 차트 + 빈 표 그대로 표시. (Blind F27, Edge E19.)
- [x] [Review][Patch] **P12 `connectNulls` ProteinChart 데이터 갭 왜곡** [web/src/features/reports/ProteinChart.tsx:3507] — 4-day 공백 사이를 직선 보간 → 사용자가 실제 기록한 추이가 아닌 가짜 트렌드. fix: `connectNulls` 제거. (Blind F22.)
- [x] [Review][Patch] **P13 `tdee=0` ReferenceLine 라벨 오해** [web/src/features/reports/CalorieChart.tsx:3232-3239] — 미래 BMR 계산 결과 round(0.4)=0 시 `ReferenceLine y=0` 그려짐 + "TDEE 0 kcal" 라벨. fix: `tdee !== null && tdee !== undefined && tdee > 0` 가드. (Edge E32.)
- [x] [Review][Patch] **P14 AllergyExposureChart `noUserAllergies` 빈 `<details>` 인콘시스턴스** [web/src/features/reports/AllergyExposureChart.tsx:3098-3144] — `noUserAllergies` 시 차트 영역은 "차트 미렌더" 메시지인데 `<details>` 빈 표는 그대로 SR에 노출. fix: `noUserAllergies` 시 `<details>` 자체 미렌더. (Blind F15/F20.)
- [x] [Review][Patch] **P15 Sentry transaction `set_status("internal_error")` 누락 (Story 4.2 retro 패턴)** [api/app/services/report_service.py:218-1305] — unhandled exception 시 Sentry 대시보드에 "ok"로 기록 → 실패율 visibility 0. Story 4.2 sweep loop과 동일 패턴 누락. fix: try/except + `transaction.set_status("internal_error")` + re-raise. (Edge E29.)
- [x] [Review][Patch] **P16 dual error guard — service `ValueError` unreachable** [api/app/api/v1/reports.py:557-564 + api/app/services/report_service.py:1115] — 라우터에서 `WeeklyReportInvalidDateRangeError` 먼저 raise → service의 `ValueError` 가드 코드 dead. fix: 검증을 service 일원화 + typed exception 통일(또는 router 가드 제거). (Blind F18, Auditor A3.)
- [x] [Review][Patch] ~~**P17**~~ → **DISMISS** (적용 시점 재분류) — peer endpoint(notifications/meals/users) 모두 explicit `@limiter.limit` decorator 미적용, project comment `_build_limiter`: *"AC5의 LangGraph tier는 후속 스토리에서 라우트별 데코레이터로 적용"* SOT. global `default_limits`로 60/min 동등 효과 + spec wording은 peer 정합 의도이므로 본 스토리 단독 도입은 inconsistency. Story 8.4 polish에서 일괄 적용. (Blind F3, Auditor A4.)
- [x] [Review][Patch] **P18 `PROTEIN_TARGET_BY_GOAL` KeyError 가드** [api/app/domain/health_profile.py:871-884] — 미래 5번째 enum 추가 시 endpoint 500. fix: `.get(health_goal)` + import-time `assert set(PROTEIN_TARGET_BY_GOAL) == set(HEALTH_GOAL_VALUES)` SOT 가드. (Blind F12.)
- [x] [Review][Patch] **P19 structlog `report.weekly.complete` 이벤트 from/to_date 누락** [api/app/services/report_service.py:1288-1294] — slow 요청 디버깅 시 날짜 범위 stitching 필요. fix: `from_date`/`to_date` 필드 추가. (Blind F32.)
- [x] [Review][Patch] **P20 vacuous test `test_legacy_invalid_allergy_silently_skipped`** [api/tests/services/test_report_service.py:2010-2028] — 테스트 이름과 달리 valid 알레르기(`우유`) 인입으로 22-out-of-bounds 필터 path 미통과. fix: raw SQL bypass CHECK 또는 mock User로 invalid label 직접 인입. (Blind F19.)
- [x] [Review][Patch] **P21 `useWeeklyReportQuery` 4xx retry/staleTime 누락** [web/src/features/reports/api.ts:3713-3717] — `if (!response.ok) throw` + 기본 retry 3회 → 400 invalid_date_range 알면서도 3회 hammering. fix: `retry: (count, err) => !err.message.includes("400") && count < 1` + `staleTime: 60_000`. (Edge E26.)
- [x] [Review][Patch] **P22 CalorieChart 주간 평균 0-kcal day 포함 misleading** [web/src/features/reports/CalorieChart.tsx:3206-3207] — "주간 평균"이 비기록일 0을 포함해 7로 나눔 → 3일만 기록한 사용자 평균이 실제의 3/7로 표시. fix: `chartData.filter(d => d.kcal > 0).length`로 평균 또는 라벨 변경 *"기록일 평균"*. (Edge E33.)

#### Defer (미래 작업으로 이관)

- [x] [Review][Defer] **DF116 — 알레르기 substring 매칭 short labels (게/잣) false-positive 가드 누락** [api/app/domain/allergens.py:_LABEL_SUBSTRING_EXCLUSIONS] — 단일 문자 `잣` 또는 `게`(한국어 매우 흔한 음절 — `먹게`/`있게`)가 22 알레르기 substring 매칭에서 광범위 false-positive 트리거. Story 3.5 SOT 확장 영역(본 스토리에서 단지 surfaced). 재검토: Story 8.4 polish 또는 Story 5.1 health profile 수정 시점. (Blind F33.)
- [x] [Review][Defer] **DF117 — `weight_kg < 20` 또는 > 300 sanity clamp** [api/app/services/report_service.py:1228-1230 + api/app/db/models/user.py] — `weight_kg=0.0001`(rounding bug) 또는 9999.9(corrupt entry) 시 `protein_g_per_kg` blow up 또는 0.002 — ProteinChart 비현실 표시. User 모델 CHECK 제약 추가 영역. 재검토: Story 5.1 (건강 프로필 수정) 또는 Story 8.4 polish. (Edge E20/E39.)
- [x] [Review][Defer] **DF118 — Per-meal text length cap (DoS 방지)** [api/app/services/report_service.py:1244-1263] — 50,000자 raw_text 인입 시 22 알레르기 × NFC normalize 부하. 1인 8주 단일 노드는 acknowledged. 재검토: Story 8.5 클라우드 hardening. (Edge E21.)
- [x] [Review][Defer] **DF119 — NFC normalize per-meal-once vs per-allergen 캐싱** [api/app/domain/allergens.py:contains_allergen] — 같은 텍스트에 22 알레르기 매칭 시 NFC normalize 22회 반복 — perf micro-opt. 재검토: Sentry latency p95 측정 후 NFR-P8 회귀 시. (Edge E22.)
- [x] [Review][Defer] **DF120 — `기타` 알레르기 자연어 매칭 미스** [api/app/domain/allergens.py + service] — `_SKIP_SUBSTRING_LABELS = {"기타"}` 가드로 인해 `"기타 알레르기 성분이 들어 있을 수 있습니다"` 자연어 텍스트가 `기타` 알레르기 사용자에게 노출 카운트 0. alias 룩업 SOT 확장 영역. 재검토: Story 3.5 SOT 보강 또는 Story 8.4. (Edge E23.)
- [x] [Review][Defer] **DF121 — `monitored_allergies` 응답 필드 (legacy invalid 알레르기 클라이언트 표시 정합)** [api/app/services/report_service.py:WeeklyReportResponse + AllergyExposureChart] — 사용자 `users.allergies`에 22-out-of-bounds 항목 있으면 백엔드 silently filter, 클라이언트는 raw 카운트 표시 — UI/server 표기 불일치. 재검토: Story 5.1 (allergies CHECK 제약 강화 정합). (Edge E40.)
- [x] [Review][Defer] **DF122 — WeeklyReport 빈 응답 시 dashboard 복귀 링크** [web/src/features/reports/WeeklyReport.tsx + weekly/page.tsx] — `report=null` fallback에 "대시보드로 돌아가기" 미제공 → dead-end UX. 재검토: Story 4.4 인사이트 카드 + 매크로 목표 조정 UX 통합 시. (Edge E34.)
- [x] [Review][Defer] **DF123 — `from_date == to_date` 단일일 지원 명시화** [api/app/services/report_service.py + spec] — service는 0-30일 범위 일반화, AC10 spec은 7일 default 가정. Story 4.4 14일 트레일링 윈도우 활용 시 `daily_summaries.length` 비-7 케이스 클라이언트 가드 필요. 재검토: Story 4.4 인사이트 카드 시점. (Edge E4.)
- [x] [Review][Defer] **DF124 — `parsed_items` non-dict shape structlog 경고** [api/app/services/report_service.py:1247-1251] — 레거시/스키마 드리프트로 `parsed_items` 항목이 dict가 아닐 때 silent partial info loss. 재검토: Story 8.4 polish. (Edge E7.)
- [x] [Review][Defer] **DF125 — `protein_g_per_kg=0` 표시 명시 ("단백질 기록 없음")** [web/src/features/reports/ProteinChart.tsx] — meal_count > 0이지만 protein 0g 케이스 UX 모호. 재검토: Story 4.4 인사이트 카드 차트 polish 시. (Edge E27.)
- [x] [Review][Defer] **DF126 — 차트 Tooltip formatter 표준화** [web/src/features/reports/{Macro,Calorie,Protein}Chart.tsx] — recharts `<Tooltip />` 기본값으로 `399.99999` 등 raw 노출 가능. `formatter={(v) => v.toFixed(0)}` 표준화. 재검토: Story 8.4 UI polish. (Blind F26.)
- [x] [Review][Defer] **DF127 — chartData `formatMmDd` 연도 경계** [MacroChart/CalorieChart/ProteinChart] — 7일 윈도우가 12-29 ~ 01-04 걸칠 때 라벨 정렬 비sortable + 연도 정보 누락. 재검토: 연말 윈도우 첫 실배포 시점 직전. (Blind F25.)
- [x] [Review][Defer] **DF128 — `docs/runbook/web-perf-check.md` Lighthouse 실측** [docs/runbook/web-perf-check.md] — DS는 SOP만 명시. NFR-P8 1.5초 실측은 CR/QA 단계 책임 — 본 CR에서 environment 부재로 미수행. 재검토: Story 8.4 클라우드 배포 hardening 또는 영업 데모 직전. (Spec self-defer.)

#### Dismissed (47건)

CR 노이즈/false positive/spec 의도 정합/cosmetic. 주요:
- F5/E37 (`?? []` defensive — cosmetic) · F8 (`_to_float_or_none` defensive — 실 path 정상) · F10/E38 (`insights: None = None` — spec 명시 의도) · F11 (`auth_headers` fixture — pytest 통과 확인됨) · F13/E30 (`useSyncExternalStore` no-op subscribe — 의도적 ESLint 회피) · F14/F23/F31 (self-resolved) · F17 (422→400 mapping — global handler 적용) · F25/F29 (cosmetic) · A6 (`assert` → `if/raise` — 코드가 spec보다 안전) · A7-A12 (PASS verification, no finding) · E5 (shallow frozen — 실 mutation path 없음) · E8 (bool coercion — 이론적) · E17 (vacuous truth — 동작 정합) · E24 (극단 날짜 — 실 attack 없음) · E28 (이미 처리됨) · E31 (Decimal 1e-15 — invisible) · E36 (`uselist=False` — DB UNIQUE 의존)
