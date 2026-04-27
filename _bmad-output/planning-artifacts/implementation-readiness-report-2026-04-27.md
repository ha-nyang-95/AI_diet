---
stepsCompleted: ['step-01-document-discovery', 'step-02-prd-analysis', 'step-03-epic-coverage-validation', 'step-04-ux-alignment', 'step-05-epic-quality-review', 'step-06-final-assessment']
workflowComplete: true
status: 'complete'
overallReadiness: 'READY'
completedAt: 2026-04-27
date: 2026-04-27
project_name: AI_diet
product_name: BalanceNote
assessor: 'Winston (System Architect) — bmad-check-implementation-readiness'
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/epics.md
supportingDocuments:
  - _bmad-output/planning-artifacts/product-brief-BalanceNote-2026-04-26.md
  - _bmad-output/planning-artifacts/research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md
ux_design: 'absorbed-into-prd-and-stories'
previousReport: 'implementation-readiness-report-2026-04-27-v1.md (stale — pre-17:18 docs)'
---

# Implementation Readiness Assessment Report

**Date:** 2026-04-27
**Project:** AI_diet (BalanceNote)
**Assessor:** Winston (System Architect)

## Document Inventory

### PRD
- `_bmad-output/planning-artifacts/prd.md` — 102,806 bytes, modified 2026-04-27 17:19

### Architecture
- `_bmad-output/planning-artifacts/architecture.md` — 70,596 bytes, modified 2026-04-27 17:18

### Epics & Stories
- `_bmad-output/planning-artifacts/epics.md` — 91,948 bytes, modified 2026-04-27 17:19

### UX Design
- 별도 문서 없음 — UX 결정은 PRD 및 Epic/Story에 흡수 (`absorbed-into-prd-and-stories`)

### Supporting Documents
- `_bmad-output/planning-artifacts/product-brief-BalanceNote-2026-04-26.md`
- `_bmad-output/planning-artifacts/research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md`

### Notes
- 이전 readiness 보고서(`implementation-readiness-report-2026-04-27-v1.md`)는 12:02 작성, PRD/Arch/Epics 17:18~17:19 재작성 이후 stale 처리되어 v1로 백업됨.
- 중복(Whole + Sharded) 없음. 필수 문서 누락 없음.

## PRD Analysis

### Functional Requirements

총 **49개 FR** — 9개 capability 영역. (PRD 본문 #934-1018, "Capability Contract")

#### 1. Identity & Account (5)
- **FR1.** Google OAuth 가입·로그인 + 모바일·웹 단일 계정 인증
- **FR2.** 건강 프로필 입력 (나이/체중/신장/활동 수준/`health_goal` 4종/22종 알레르기 다중)
- **FR3.** 건강 프로필 수정 + 변경 즉시 분석 반영
- **FR4.** 모바일·웹 어디서나 로그아웃
- **FR5.** 회원 탈퇴 (PIPA 외 보존 의무 외 즉시 파기)

#### 2. Privacy, Compliance & Disclosure (6)
- **FR6.** 첫 진입 시 디스클레이머(한/영) + 약관 동의 + 개인정보 동의(별도) 통과 필수
- **FR7.** PIPA 자동화 의사결정 동의 별도 + 미수신 시 분석 차단 + 안내
- **FR8.** 약관/처리방침/디스클레이머 한·영 재열람 가능
- **FR9.** 데이터 내보내기 (식단/피드백/프로필 JSON·CSV — PIPA 권리)
- **FR10.** 권한 거부 시 안내 화면 + 설정 deep link (빈 화면 금지)
- **FR11.** 분석 피드백 카드 푸터에 "건강 목표 부합도 점수 — 의학적 진단이 아닙니다" 노출

#### 3. Meal Logging (5)
- **FR12.** 식단 텍스트 또는 사진 입력 (모바일)
- **FR13.** 식단 조회·수정·삭제 (CRUD)
- **FR14.** 일별 식단 기록 시간순 표시 (식사 + 매크로 + 피드백 + fit_score)
- **FR15.** 사진 OCR 결과 확인·수정 후 분석 시작
- **FR16.** 오프라인 텍스트 식단 입력 큐잉 + 온라인 자동 sync

#### 4. AI Nutrition Analysis (Self-RAG + 인용형, 11)
- **FR17.** LangGraph 6노드 파이프라인 (parse_meal → retrieve → eval_quality → fetch_profile → eval_fit → feedback)
- **FR18.** Self-RAG 재검색 (retrieval_confidence 미달 시 쿼리 재작성 + 1회 재검색)
- **FR19.** 한국식 음식명 변형 통합 매칭 ("짜장면" / "자장면")
- **FR20.** 신뢰도 미달 시 사용자 재질문 ("이게 ◯◯이 맞나요?")
- **FR21.** fit_score 0-100 산출 (Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15)
- **FR22.** 알레르기 매칭 시 score=0 + 매크로/칼로리 점수 무시
- **FR23.** 한국 1차 출처 인용 피드백 생성 (KDRIs/대비/대당/식약처)
- **FR24.** 모든 권고에 (출처: 기관, 문서, 연도) 패턴 + 누락 시 재생성·치환
- **FR25.** 식약처 광고 금지 표현(진단·치료·예방·완화) 필터·치환
- **FR26.** 분석 결과 모바일 채팅 UI 스트리밍 수신
- **FR27.** 메인 LLM 실패 시 보조 LLM 자동 전환 (OpenAI → Claude)

#### 5. Engagement & Notifications (4)
- **FR28.** 온보딩 튜토리얼 (디스클레이머 → 약관 → 사용법 2-3 → 프로필)
- **FR29.** 미기록 nudge (설정 시간 + 30분 + 미입력 자동 푸시)
- **FR30.** 푸시 ON/OFF 토글 + 알림 시간 변경
- **FR31.** 푸시 탭 → 모바일 식단 입력 화면 직행

#### 6. Insights & Reporting (3)
- **FR32.** 웹 주간 리포트 4종 차트 (매크로 비율 / 칼로리 vs TDEE / 단백질 g/kg / 알레르기 노출)
- **FR33.** 주간 인사이트 카드 + 한국 1차 출처 인용 ("다음 주 권장 매크로 조정")
- **FR34.** 매크로/칼로리 목표 조정 + 알림 룰·모바일 권장 자동 반영

#### 7. Administration & Audit Trust (5)
- **FR35.** Admin role 분리 인증 (웹 관리자)
- **FR36.** 관리자 사용자 검색·식단 이력·피드백 로그·프로필 수정
- **FR37.** Admin 액션 audit log (시점·액터·액션·대상)
- **FR38.** 관리자 자기 활동 로그 self-audit
- **FR39.** 관리자 조회 시 민감정보 마스킹 + 명시적 "원문 보기" 액션

#### 8. Subscription & Payment (3)
- **FR40.** 정기결제 1플랜 sandbox 신청·해지
- **FR41.** 결제 영수증·이용내역 조회
- **FR42.** 결제 webhook 처리 + 구독 상태 갱신 + 이력 기록

#### 9. Operations & Handover (7)
- **FR43.** LLM 응답 + 음식 검색 결과 캐시 (Redis)
- **FR44.** 사용자별 + LangGraph 호출 별도 rate limit (비용·악용 방어)
- **FR45.** 분석/외부 API/DB 에러 자동 수집 + 민감정보 마스킹 (Sentry)
- **FR46.** 표준 OpenAPI 명세 (외주 인수인계)
- **FR47.** 1-cmd 컨테이너 부팅 (DB + 벡터 + 캐시 + API + 시드)
- **FR48.** 외주 클라이언트 개발자 README + Docker만으로 1일 내 환경 구축
- **FR49.** LangSmith 옵저버빌리티 + 한식 100건 회귀 평가 + 마스킹 hook (개발자·발주자 전용)

**Total FRs: 49**

> ※ PRD §Functional Requirements 도입부에는 "총 9개 capability 영역, 48개 FR"로 적혀 있으나, 실제 본문은 FR1~FR49로 49개 (Capability Contract 종결부 "이상 49개 FR"이 정정 확정). **PRD 본문 도입부 "48개" 표기는 오기로 추정 — 후속 보정 권고 (low severity).**

### Non-Functional Requirements

총 **68개 NFR** — 11개 영역.

#### Performance (10) — NFR-P1~P10
- P1: 종단 지연(사진 포함) p50≤4s/p95≤8s · P2: 텍스트 only p50≤2.5s/p95≤5s · P3: TTFT p50≤1.5s/p95≤3s
- P4: LangGraph 6노드 평균 ≤3s · P5: Self-RAG 재검색 +≤2s
- P6: pgvector 검색 캐시 miss p95≤200ms · P7: 캐시 hit p95≤30ms
- P8: 웹 주간 리포트 ≤1.5s · P9: 관리자 검색(1만 사용자) ≤1s · P10: 분석 외 API p95≤500ms

#### Security (10) — NFR-S1~S10
- TLS 1.2+/HSTS · JWT(access 30d/refresh 90d, Keychain·Keystore·httpOnly) · OAuth-only(비번 0)
- Rate limit(60/min, 1000/h, LangGraph 10/min) · 민감정보 마스킹(beforeSend hook 강제)
- Postgres 디스크 암호화(Railway) · Admin role 분리 secret·8h 만료 · IP 화이트리스트 옵션
- LLM 키 환경변수+secrets · 키 회전 SOP

#### Reliability & Availability (6) — NFR-R1~R6
- 99.9% (Railway) · LLM 듀얼 fallback · Pydantic retry 1회 + error edge · DB 다운 시 모바일 7일 캐시 RO · 일별 백업 7일 · Sentry 자동 알림

#### Observability & AI Quality (5) — NFR-O1~O5 ⭐ (영업 카드)
- O1 트레이싱 100% (LangGraph 6노드 + Self-RAG + LLM + RAG)
- O2 마스킹 hook (`app/core/observability.py`, PR CI 강제)
- O3 한식 100건 회귀 평가 (정확도 ≥90% 미달 시 머지 차단 권장)
- O4 영업 데모 9포인트 중 1포인트 = LangSmith 보드 링크
- O5 LangSmith US region 송신 + 처리방침 명시 + Self-hosted는 Growth

#### Scalability (4) — NFR-Sc1~Sc4
- 동시 100명/DAU 1000명 baseline · Vercel CDN · 10x 마이그레이션 가이드 README · LLM 비용 보호(캐시+rate limit+일별 임계 자동 차단)

#### Accessibility (6) — NFR-A1~A6
- 스크린리더(VoiceOver/TalkBack) · 색상 대비 WCAG AA · 폰트 스케일 200% · 색상 단독 정보 금지 · 키보드 내비 + 차트 데이터 테이블 fallback · 풀 WCAG 인증은 Growth

#### User Experience & Coaching Voice (6) — NFR-UX1~UX6
- UX1 Noom-style 코칭 톤(긍정·동기부여, 비난 금지)
- UX2 평가 + 행동 제안 두 부분 강제 (부재 시 후처리 재생성)
- UX3 수치는 별도 카드(접힘) — 채팅 본문은 자연어 코칭 우선
- UX4 의학 어휘 회피 (C5 가드 결합)
- UX5 한국 식사 패턴 컨텍스트 주입
- UX6 디스클레이머는 푸터 1줄, 본문 코칭 흐름 보존

#### Localization (4) — NFR-L1~L4
- 한국어 1차 · 영문 보조(디스클레이머/약관 풀텍스트) · KRW/YYYY-MM-DD/24h · 풀 다국어는 Growth

#### Maintainability & Testability (8) — NFR-M1~M8
- M1 Pytest ≥70% (T7 KPI) · M2 README 5섹션 · M3 SOP 4종
- M4 Swagger 자동 + 보강 · M5 .env.example · M6 Docker=로컬 환경 동질성
- M7 onboarding ≤8h · M8 데이터 모델 추상 분리

#### Compliance (Reference, 5) — NFR-C1~C5
- C1 의료기기 미분류 SOP · C2 PIPA 자동화 의사결정 별도 동의 + 차단 · C3 광고 금지 표현 가드(테스트 ≥10건) · C4 디스클레이머 4개 위치 노출 · C5 알레르기 22종 무결성 + fit_score 0점 트리거

#### Integration (Reference, 4) — NFR-I1~I4
- I1 식약처 OpenAPI fallback (ZIP/USDA) · I2 LLM 듀얼 fallback · I3 OCR 장애 graceful · I4 결제 sandbox 안정성은 Growth

**Total NFRs: 68**

### Additional Requirements

#### Compliance Domain (C1~C6, PRD §Compliance & Regulatory)
- C1 의료기기 미분류 (식약처 저위해도 명시 예시 일치)
- C2 PIPA 2026.03.15 자동화 의사결정 동의 + 민감정보 별도 동의 + 동의서 5섹션
- C3 표준 디스클레이머 한·영 (4개 노출 위치)
- C4 식약처 22종 알레르기 도메인 무결성
- C5 식약처 광고 금지 표현 가드 (회피→안전 매핑)
- C6 데이터 보존·파기 (탈퇴 즉시 + LLM 로그 30일)

#### Technical Constraints (TC1~TC4)
- TC1 보안(JWT 쿠키, HSTS, rate limit, 민감정보 마스킹, admin 분리)
- TC2 개인정보 (컬럼 암호화 Growth, Sentry beforeSend)
- TC3 성능 목표(상기 NFR-P 동일)
- TC4 가용성·내결함성 (LLM 듀얼 fallback, Pydantic retry, DB 503 안내)

#### Integration Requirements (I1~I4)
- I1 외부 RAG 시드 6개 (식약처 OpenAPI/ZIP, KDRIs PDF, 대비학회 PDF, 대당학회 PDF, 질병관리청 HTML)
- I2 LLM/OCR (OpenAI gpt-4o-mini, Anthropic Claude, OpenAI Vision)
- I3 Docker Compose, Swagger, README 5섹션, SOP 4종
- I4 Toss/Stripe sandbox 정기결제 1플랜

#### Risks (R1~R10)
- R1 음식명 매칭 정확도 (T3 KPI 회귀)
- R2 RN SSE 호환 (W4 day1 spike, polling fallback)
- R3 Structured Output JSON 파싱 실패 (Pydantic + retry + edge)
- R4 영양 DB 가공 시간 초과 (W1 spike, OpenAPI/ZIP/USDA fallback)
- R5 환경 차이 (W1부터 Docker, W7 dry-run)
- R6 LLM 비용 폭증 (Redis 캐시, gpt-4o-mini 메인, 일별 알림)
- R7 식약처 OpenAPI 장애 (ZIP/USDA fallback)
- R8 표시기준 22종 갱신 (분기 모니터링 SOP)
- R9 PIPA 시행령 갱신 (분기 모니터링)
- R10 진단성 발언 요구 (영업 답변 사전 차단)

#### Project-Type Specific (M1~M6, W1~W3, A1~A4)
- Mobile: RN+Expo managed, iOS 14+/Android 8.0+, 오프라인 큐잉(텍스트만), Expo Notifications, 권한 요청 흐름, 스토어 컴플라이언스
- Web: Next.js App Router, 반응형(360px-1440px+), Recharts, 관리자 self-audit 패널
- API Backend: FastAPI 엔드포인트 그룹(Auth/Profile/Meals/Analysis/Reports/Admin/Payment/Notification/Compliance), JWT+admin role, Redis rate limit/캐시, Swagger

### PRD Completeness Assessment

#### 강점
1. **Capability Contract 명시** — FR 외 기능은 정식 범위 외 (단일 출처 선언)
2. **이중 트래킹** — FR 49 + NFR 68 + Compliance C1~C6 + TC1~TC4 + R1~R10 + 타입별 (M/W/A) 모두 모듈화
3. **추적성 베이스라인** — 각 FR/NFR/AC가 KPI(B1~B5, T1~T10)와 명시 매핑
4. **컴플라이언스 4-layer 방어선** — 명명(fit_score) + 디스클레이머 4위치 + 광고 가드(C5) + PIPA 동의 차단(FR7) — FDA Warning Letter 시사점 반영
5. **외주 인수인계 가시성** — README 5섹션, SOP 4종, Docker 1-cmd, Swagger, LangSmith 보드 링크 모두 산출물로 박아둠

#### Minor Gaps / Watch
1. **PRD §FR 도입부 "48개 FR" 표기** — 실제 49개 (FR49 LangSmith 추가 후 도입부 카운트 미정정). 수정 권장 (cosmetic).
2. **FR16 오프라인 큐잉** — 사진 입력은 온라인 필수임을 명시했으나, "큐잉된 텍스트 입력의 sync 충돌"(예: 같은 시간대 입력 중복)에 대한 정책은 명시 부재. 에픽 단계에서 흡수되었는지 확인 필요.
3. **FR27 LLM 듀얼 fallback** — `evaluate_fit`은 Claude 보조이지만 `generate_feedback`도 NFR-R2에서 듀얼 fallback 적용. FR27이 두 노드 모두 커버하는지 에픽 단계에서 확인 필요.
4. **Vision/Roadmap 항목** — Growth 8항목 + Vision 4축은 명시되어 있으나, MVP→Growth 트리거 조건(언제 Phase 2로 넘어가는가)은 영업 사이클 1회 후로만 대략 명시. 우선순위 PR 권한 (P0 등) 부재 — 외주 영업 frame이라 의도적으로 보임.
5. **테스트 데이터셋 한식 100건의 출처/구성 비율** — T3, NFR-O3에서 100건이 핵심 KPI인데, "어떻게 100건을 큐레이션하는가"에 대한 spec은 PRD 외부(Story 단계)로 위임된 듯. 에픽/스토리에 흡수되었는지 검증 필요.

#### 결론
PRD는 **Capability Contract** 수준의 완성도. 9개 영역 × 49 FR + 11개 영역 × 68 NFR + 도메인별 부속(C/TC/R/M/W/A) 매트릭스 모두 명시. 1인 8주 영업 포트폴리오 frame 기준 *과잉 분해 없이* 외주 인수인계 가능 산출물 수준 도달.

## Epic Coverage Validation

### Epic 구조 (8개 Epic, 38개 Story)

| Epic | 제목 | Stories | 슬롯 |
|------|------|---------|------|
| 1 | 기반 인프라 + 인증 + 온보딩·동의 | 1.1~1.6 (6) | W1 |
| 2 | 식단 입력 + 일별 기록 + 권한 흐름 | 2.1~2.5 (5) | W4 |
| 3 | AI 영양 분석 (Self-RAG + 인용 피드백) | 3.1~3.8 (8) | W2-W3 |
| 4 | 알림(nudge) + Web 주간 리포트 | 4.1~4.4 (4) | W4-W5 |
| 5 | 계정 관리 + PIPA 권리 | 5.1~5.3 (3) | W5 |
| 6 | 결제/구독 sandbox | 6.1~6.3 (3) | W7 |
| 7 | 관리자 + Audit Trust | 7.1~7.4 (4) | W5 |
| 8 | 운영·인수인계 패키지 + 영업 자료 | 8.1~8.6 (6) | W6-W8 |

**Total: 38 stories across 8 epics**

### FR Coverage Matrix (49/49)

| FR | 요약 | Epic.Story | 상태 |
|----|------|-----------|------|
| FR1 | Google OAuth + JWT | 1.2 | ✓ Covered |
| FR2 | 건강 프로필 입력 (22종 알레르기) | 1.5 | ✓ Covered |
| FR3 | 프로필 수정 + 즉시 반영 | 5.1 | ✓ Covered |
| FR4 | 모바일·웹 로그아웃 | 1.2 | ✓ Covered |
| FR5 | 회원 탈퇴 + 즉시 파기 | 5.2 | ✓ Covered |
| FR6 | 디스클레이머 + 약관 + PIPA 민감정보 별도 | 1.3 | ✓ Covered |
| FR7 | 자동화 의사결정 동의 + 미수신 차단 | 1.4 | ✓ Covered |
| FR8 | 약관/처리방침/디스클레이머 재열람 | 1.3 | ✓ Covered |
| FR9 | 데이터 내보내기 JSON/CSV | 5.3 | ✓ Covered |
| FR10 | 권한 거부 시 안내 + deep link | 2.2 (+4.1 재사용) | ✓ Covered |
| FR11 | 결과 카드 푸터 디스클레이머 1줄 | 1.3 컴포넌트 → 3.7 적용 | ✓ Covered |
| FR12 | 식단 텍스트/사진 입력 | 2.1, 2.2 | ✓ Covered |
| FR13 | 식단 CRUD | 2.1 | ✓ Covered |
| FR14 | 일별 식단·매크로·fit_score 시간순 | 2.4 | ✓ Covered |
| FR15 | OCR 결과 확인·수정 후 분석 | 2.3 | ✓ Covered |
| FR16 | 오프라인 텍스트 큐잉 + 자동 sync | 2.5 | ✓ Covered |
| FR17 | LangGraph 6노드 파이프라인 | 3.3 | ✓ Covered |
| FR18 | Self-RAG 재검색 (1회 한도) | 3.4 | ✓ Covered |
| FR19 | 한국식 음식명 변형 통합 매칭 | 3.1 (food_aliases) + 3.4 | ✓ Covered |
| FR20 | 사용자 재질문 (모호 시) | 3.4 | ✓ Covered |
| FR21 | fit_score 0-100 통합 산출 | 3.5 | ✓ Covered |
| FR22 | 알레르기 위반 → score=0 단락 | 3.5 | ✓ Covered |
| FR23 | 한국 1차 출처 인용 피드백 | 3.6 (+ 3.2 RAG 시드) | ✓ Covered |
| FR24 | (출처) 패턴 강제 + 후처리 | 3.6 | ✓ Covered |
| FR25 | 광고 금지 표현 가드 | 3.6 | ✓ Covered |
| FR26 | 모바일 SSE 스트리밍 채팅 | 3.7 | ✓ Covered |
| FR27 | 메인 LLM 실패 시 보조 자동 전환 | 3.6 | ✓ Covered |
| FR28 | 온보딩 튜토리얼 순차 흐름 | 1.6 | ✓ Covered |
| FR29 | 미기록 nudge 자동 푸시 | 4.2 | ✓ Covered |
| FR30 | 알림 ON/OFF + 시간 변경 | 4.1 | ✓ Covered |
| FR31 | 푸시 탭 → 식단 입력 직행 | 4.2 | ✓ Covered |
| FR32 | Web 주간 리포트 4종 차트 | 4.3 | ✓ Covered |
| FR33 | 인사이트 카드 + 1차 출처 인용 | 4.4 | ✓ Covered |
| FR34 | 매크로 목표 조정 + 자동 반영 | 4.4 | ✓ Covered |
| FR35 | admin role 분리 인증 | 7.1 | ✓ Covered |
| FR36 | 관리자 검색·이력·프로필 수정 | 7.2 | ✓ Covered |
| FR37 | Audit log 자동 기록 | 7.3 | ✓ Covered |
| FR38 | 관리자 self-audit 화면 | 7.4 | ✓ Covered |
| FR39 | 민감정보 마스킹 + 원문 보기 | 7.4 | ✓ Covered |
| FR40 | 정기결제 sandbox 신청·해지 | 6.1 | ✓ Covered |
| FR41 | 영수증·이용내역 조회 | 6.2 | ✓ Covered |
| FR42 | 결제 webhook + 멱등 처리 | 6.3 | ✓ Covered |
| FR43 | LLM/음식 검색 캐시 | 1.1 (인프라) → 8.4 (정교화) | ✓ Covered (split) |
| FR44 | Rate limit (사용자별 + LangGraph 별도) | 1.1 (인프라) → 8.4 (정교화) | ✓ Covered (split) |
| FR45 | Sentry 자동 수집 + 마스킹 | 1.1 (SDK) → 8.4 (정교화) | ✓ Covered (split) |
| FR46 | OpenAPI 명세 (인수인계) | 1.1 (자동) → 8.4 (정리·예시) | ✓ Covered (split) |
| FR47 | Docker 1-cmd 컨테이너 부팅 | 1.1 → 8.5 (hardening) | ✓ Covered (split) |
| FR48 | README + Docker → 1일 내 환경 구축 | 8.3 | ✓ Covered |
| FR49 | LangSmith 옵저버빌리티 + 회귀 평가 | 3.8 (셋업) → 8.6 (영업 자료) | ✓ Covered (split) |

### NFR Coverage Sweep (보강 점검)

스토리 ACs에서 NFR이 어떻게 추적되는지 sweep — Step 5 품질 리뷰의 prelim 신호. **GAP 후보**(스토리 AC에서 명시 인용 없음)만 표시.

| NFR | 명시 인용 스토리 | 비고 |
|-----|---------------|------|
| NFR-P1 | 2.3, 3.7 | ✓ |
| NFR-P3 (TTFT) | 3.7 | ✓ |
| NFR-P4, P5 (LangGraph/Self-RAG) | 3.3 | ✓ |
| NFR-P6 (pgvector ≤200ms) | 3.1 | ✓ |
| NFR-P7 (cache ≤30ms) | 8.4 | ✓ |
| NFR-P8 (주간 리포트 ≤1.5s) | 4.3 | ✓ |
| NFR-P9 (관리자 ≤1s) | 7.2 | ✓ |
| **NFR-P10 (분석 외 API p95 ≤500ms)** | (스토리 AC 직접 인용 없음) | ⚠️ GAP — 일반 API 지연 게이트가 어느 스토리 AC에도 못박혀 있지 않음 |
| NFR-S1~S10 | 1.1·1.2·7.1·7.4·8.4·8.5 분산 | ✓ |
| NFR-R2~R6 | 2.4·3.3·3.6·8.4·8.5 | ✓ |
| NFR-O1~O5 | 3.8·8.6 | ✓ |
| NFR-Sc4 (LLM 비용 보호) | 8.4·8.5 (daily-cost-alert.yml) | ✓ |
| **NFR-A1 (모바일 스크린리더 a11y label)** | (직접 인용 없음 — 표준 RN props로 implicit 흡수 의도) | ⚠️ GAP — 스토리 AC에 a11y label 강제 못박힘 없음 |
| **NFR-A2 (색상 대비 4.5:1 / 3:1)** | (디자인 토큰 룰만 일반론) | ⚠️ GAP — 디자인 토큰 검증을 어느 스토리에서 점검할지 미명시 |
| NFR-A3 (폰트 200%) | 1.5, 2.4 | ✓ |
| NFR-A4 (색상 단독 금지) | 1.5, 2.4, 3.5 | ✓ |
| NFR-A5 (키보드/차트 fallback) | 4.3 | ✓ |
| NFR-UX1 Noom 톤 | 3.6 | ✓ |
| NFR-UX2 행동 제안 강제 | 3.6 | ✓ |
| NFR-UX3 수치 보조 카드 | 3.7 | ✓ |
| NFR-UX4 의학 어휘 회피 | 3.6 (광고 가드 흡수) | ✓ |
| **NFR-UX5 (한국 식사 패턴 시스템 프롬프트 컨텍스트 주입)** | (직접 인용 없음) | ⚠️ GAP — `generate_feedback` 시스템 프롬프트 사양에서 한국 식사 패턴 25/35/30 컨텍스트 주입을 어느 AC에도 못박지 않음 |
| NFR-UX6 디스클레이머 푸터 1줄 | 3.7 | ✓ |
| NFR-L1~L3 | 1.3, 5.3 (CSV BOM), 6.1 (KRW) | ✓ |
| NFR-M1~M8 | 1.1, 8.1, 8.3, 8.4 | ✓ |
| NFR-C1~C5 | 1.3, 1.4, 1.5, 3.1, 3.2, 3.5, 3.6, 3.7, 8.1 | ✓ |
| NFR-I1~I4 | 2.3, 3.1, 3.6, 6.1 | ✓ |

### Missing Coverage / Gaps

#### Critical Missing FRs
**없음.** 49/49 FR 모두 매핑 완료.

#### NFR Gap 후보 (Minor — Step 5 품질 리뷰에서 추가 검토 권고)
1. **NFR-P10** (분석 외 API p95 ≤500ms) — 어느 스토리 AC에도 명시 인용 없음. 일반 CRUD/조회 API 지연이 측정·게이트되지 않을 위험. **권고:** Story 8.4 (운영 polish) AC에 *"분석 외 API endpoint p95 ≤500ms — Sentry transaction tracing으로 회귀 검증"* 1줄 추가.
2. **NFR-A1** (모바일 스크린리더 호환 — accessibility label) — Story 1.5/2.4가 폰트 스케일·색상 단독 X는 명시했지만 a11y label은 RN 표준 props로 implicit 흡수만 됨. **권고:** Story 8.4 또는 Mobile QA 회귀에 *"모든 인터랙티브 요소 a11y label 검증 (VoiceOver/TalkBack 1회 체크)"* 추가, 또는 Mobile UI 화면 스토리(2.1, 2.4) 표준 빈/로딩/에러 화면 AC와 함께 통합.
3. **NFR-A2** (색상 대비 WCAG AA) — 디자인 토큰 룰만 일반론으로 PRD에 있고, 어느 스토리에서 토큰 검증을 어떻게 회귀하는지 명시 부재. **권고:** Story 1.1 (디자인 토큰 부트스트랩) 또는 Story 8.4 (표준 빈/로딩/에러 일괄)에 *"디자인 토큰 색상 대비 WCAG AA 통과 검증 1회"* AC 추가.
4. **NFR-UX5** (한국 식사 패턴 시스템 프롬프트 컨텍스트 주입) — Story 3.6의 시스템 프롬프트 사양에 *"매크로 룰 + 한국 식사 패턴 25/35/30 + 회식·외식"* 컨텍스트 주입 명시 부재. **권고:** Story 3.6 AC에 *"`generate_feedback` 시스템 프롬프트에 한국 식사 패턴 컨텍스트(아침-점심-저녁 25/35/30, 회식·외식 빈도) 주입 강제"* 1줄 추가.

#### FRs in Epics but NOT in PRD
**없음.** 모든 epic story가 PRD FR/NFR로 추적 가능.

### Coverage Statistics

- **Total PRD FRs:** 49
- **FRs covered in epics:** 49
- **FR Coverage percentage:** **100%** ✅
- **NFR coverage (sweep):** 64/68 명시적 인용 + 4 minor GAP 후보 (NFR-P10, NFR-A1, NFR-A2, NFR-UX5)
- **NFR Coverage percentage (sweep):** ≈94% 명시 / 100% 의도(+ 4건 보강 권고)

### 결론

**FR coverage 100% — 1인 8주 산출물 기준 합격.** Cross-cutting 인프라(FR43~FR47)는 Epic 1 셋업 → Epic 8 정교화 split 패턴으로 명확히 추적되며, FR48/FR49는 외주 인수인계와 영업 자료 패키징의 핵심 영업 카드를 epic 단위로 박았다. 4개 NFR 보강 권고는 step-05 품질 리뷰에서 재검토하되, 모두 *AC 한 줄 추가* 수준의 minor — implementation readiness를 막는 critical 이슈는 없음.

## UX Alignment Assessment

### UX Document Status

**Not Found (intentional)** — 사용자 명시 결정으로 별도 UX 산출물(wireframe·디자인 시스템·UX 사양서)은 OUT, PRD/Architecture/Story AC에 흡수.

근거:
- PRD frontmatter `out_with_valid_reasons` — *"분리된 UX 산출물 (별도 wireframe·디자인 시스템) — 사용자 명시 결정 (PRD/스토리에 흡수)"*
- Epics 도입부 — *"UX Design 별도 문서 없음 — PRD/스토리에 흡수(사용자 명시 결정)"*
- Memory: `feedback_skip_ux_design_default.md` — UX 결정은 PRD/스토리에 흡수가 기본, 별도 디자인 산출물 요구는 클라이언트 명시 시에만

이 결정은 *missing UX*가 아니라 *decision-by-absorption* — UX는 implied되어 있지만 별도 산출물을 만들지 않고 PRD/Architecture/Story AC가 그 책임을 분담한다.

### UX-PRD Absorption Verification (흡수 정합성 점검)

UX 결정이 어디서 어떻게 박혀 있는지 cross-check:

| UX 결정 영역 | 흡수 위치 | 정합 |
|------------|---------|------|
| **권한 거부 흐름** (카메라·사진첩·푸시) — 빈 화면 금지, 안내 + deep link | PRD M5 + FR10 / Story 2.2 (`PermissionDeniedView` 표준 컴포넌트) → Story 4.1 재사용 | ✅ |
| **표준 빈/로딩/에러 화면** | PRD `implicit_in_as_acceptance_criteria` / Story 2.1, 2.4, 8.4 (일괄 적용 W6) | ✅ |
| **온보딩 순차 흐름** (디스클레이머→약관→사용법 2-3→프로필) | PRD FR28 / Story 1.6 라우터 시퀀스 + Expo Router state 보존 | ✅ |
| **디스클레이머 4 위치 노출** | PRD C3 + FR11 / Story 1.3 (`DisclaimerFooter` 컴포넌트 + Web `/legal/*` + `/en/legal/*`) → Story 3.7 (분석 결과 푸터 1줄) | ✅ |
| **Coaching Tone (Noom-style)** | PRD NFR-UX1 / Story 3.6 시스템 프롬프트 + 행동 제안 후처리 강제 | ✅ |
| **수치는 보조 카드 (접힘)** | PRD NFR-UX3 / Story 3.7 매크로 g/kcal는 별도 데이터 카드 | ✅ |
| **SSE 스트리밍 채팅 UI** | PRD FR26 / Story 3.7 + Architecture (react-native-sse + sse-starlette + RFC 7807 + polling fallback) | ✅ |
| **Recharts 4종 차트** | PRD FR32 / Story 4.3 (Macro/Calorie/Protein/AllergyExposure) + Architecture Web | ✅ |
| **마스킹 UX (관리자)** | PRD FR39 / Story 7.4 (5분 비활동 후 마스킹 자동 복원, 원문 보기 audit) | ✅ |
| **fit_score 색상 + 숫자 + 텍스트 라벨 (색약 대응)** | PRD NFR-A4 / Story 1.5, 2.4, 3.5 | ✅ |
| **폰트 스케일 200% 대응** | PRD NFR-A3 / Story 1.5, 2.4 | ✅ |
| **앱 정보 화면 (버전·OSS 라이선스)** | PRD `implicit_in` / Story 8.4 (`(tabs)/settings/about.tsx` license-checker 자동 생성) | ✅ |
| **데이터 내보내기 UX (JSON/CSV BOM·LF·헤더)** | PRD FR9 / Story 5.3 (스트리밍 응답 + Content-Disposition + BOM) | ✅ |
| **회원 탈퇴 UX (30일 grace·재로그인 안내)** | PRD FR5 + C6 / Story 5.2 | ✅ |
| **결제 UX (KRW 정수·Toss/Stripe sandbox)** | PRD FR40 + NFR-L3 / Story 6.1 | ✅ |

### UX-Architecture Alignment

Architecture가 UX 결정을 *컴포넌트·패턴·인프라*로 응답하는지 점검:

| UX 요구 | Architecture 응답 |
|--------|-----------------|
| SSE 스트리밍 (RN + Next.js) | `sse-starlette EventSourceResponse` + react-native-sse + 이벤트 타입(`token`/`citation`/`done`/`error`) + polling fallback (W4 spike R2) |
| 모바일 권한 흐름 (5종) | Expo Notifications/Camera/ImagePicker + `mobile/lib/permissions.ts` hook + `PermissionDeniedView` 표준 컴포넌트 |
| 오프라인 큐잉 | AsyncStorage + Idempotency-Key 멱등 |
| Coaching Voice | `generate_feedback` 시스템 프롬프트 + 후처리 가드(인용 패턴 + 광고 표현 + 행동 제안) |
| 마스킹 일관성 | NFR-S5 룰 1지점(`app/core/observability.py`) → Sentry beforeSend + structlog processor + LangSmith mask_run hook 모두 동일 룰셋 |
| Audit log 자동 연쇄 | `Depends(audit_admin_action)` + `admin_user_jwt_required` 자동 연쇄 — 누락 차단 |
| 디스클레이머 텍스트 단일 출처 | `GET /v1/legal/{disclaimer,terms,privacy}` API + Web `/legal/*` · `/en/legal/*` 라우트 (텍스트 단일 출처) |
| Recharts 차트 SSR | Next.js RSC + TanStack Query — 7일 데이터 ≤ 1.5초 |
| AsyncPostgresSaver | LangGraph state 영속화 → Self-RAG 재질문 사용자 응답 대기 가능 (J2 정합) |

### Alignment Issues

**Critical:** 없음.

**Watch (Step 5에서 재검토):**
1. **NFR-UX5 (한국 식사 패턴 컨텍스트 주입)** — Story 3.6 AC에 명시 인용 없음. PRD에는 *"한국 식사 패턴 25/35/30 + 회식·외식 컨텍스트 주입"* 결정이 있으나 Architecture/Story가 이를 시스템 프롬프트 사양으로 박지 않음. UX-구현 alignment에서 한 줄 빠짐.
2. **WCAG AA 색상 대비 검증 절차** (NFR-A2) — UX 결정은 *디자인 토큰에 통과 색상만*이지만, 어느 스토리/Architecture 결정에서도 *토큰 검증을 어떻게 회귀하는가* 명시 부재. Mobile a11y label(NFR-A1)도 동일.

### Warnings

- **별도 UX 산출물 부재는 의도된 결정**이며 PRD §Project-Type Specific (M1~M6, W1~W3) + §Domain Requirements + §UX/Coaching Voice (NFR-UX1~UX6) + §Implicit IN(권한 흐름·표준 빈/로딩/에러·앱 정보) + Story AC가 모두 UX 사양을 분담한다. 외주 영업 frame이라 *클라이언트가 별도 wireframe·디자인 시스템을 명시 요구*하면 그 시점에 별도 산출물을 추가하는 것이 합리적 (Memory: `feedback_skip_ux_design_default.md`).
- 모바일 a11y label(NFR-A1) + 색상 대비(NFR-A2) + 한국 식사 패턴 컨텍스트(NFR-UX5)가 어느 Story AC에도 명시 인용 없음 — Step 5에서 추가 검토.

### 결론

**UX 흡수 정합성 = OK.** 별도 UX 문서 부재는 의도된 결정이며 PRD/Architecture/Story가 UX 사양을 명확히 분담함. 단 3개 보강 권고(NFR-A1, A2, UX5)는 Step 5에서 결정.

## Epic Quality Review

### Per-Epic Best Practices Compliance

| # | Epic | User Value | Independence | Story Sizing | AC Quality | FR 추적 |
|---|------|----------|------------|------------|------------|---------|
| 1 | 기반 인프라 + 인증 + 온보딩·동의 | ⚠️ Borderline (label에 "기반 인프라" — 단 Goal은 user value) | ✅ standalone | ⚠️ Story 1.1 큼 (의도된 묶음) | ✅ Given/When/Then 일관 | ✅ |
| 2 | 식단 입력 + 일별 기록 + 권한 흐름 | ✅ | ✅ Epic 1만 의존, 분석 없이 standalone | ✅ | ✅ 빈/에러 화면·retry·fallback 명시 | ✅ |
| 3 | AI 영양 분석 (Self-RAG + 인용) | ✅ (영업 차별화 핵심) | ✅ Epic 1+2 의존 | ✅ 자연스러운 점진 의존 (3.1→3.3→3.4→3.5→3.6→3.7→3.8) | ✅ T1~T5·T10 KPI 매핑 | ✅ |
| 4 | 알림 + Web 주간 리포트 | ✅ | ✅ Epic 1·2·3 의존 | ✅ | ✅ a11y·deep link·중복 차단 명시 | ✅ |
| 5 | 계정 관리 + PIPA 권리 | ✅ (탈퇴·내보내기·프로필) | ✅ Epic 1만 의존 | ✅ | ✅ cascade·grace·BOM 명시 | ✅ |
| 6 | 결제/구독 sandbox | ✅ | ✅ Epic 1만 의존 | ✅ | ✅ Idempotency-Key·RFC 7807·signature 검증 | ✅ |
| 7 | 관리자 + Audit Trust | ✅ (B2B trust 카드) | ✅ Epic 1 (admin role) 의존 | ✅ | ✅ 5분 비활동 마스킹·append-only | ✅ |
| 8 | 운영·인수인계 + 영업 자료 | ⚠️ Borderline (외주 발주자/인수 클라이언트 페르소나에 가치) | ✅ 모든 epic 정교화·split | ⚠️ Story 8.4 큼 (의도된 묶음) | ✅ T7 KPI + Runbook + Cron 매핑 | ✅ |

### 🔴 Critical Violations
**없음.**

- 기술적 milestone-only epic 없음 (모든 epic이 사용자 또는 외주 발주자/인수 클라이언트 가치 명시)
- 순환 의존 또는 backward forward reference 없음
- 모든 cross-cutting split(`Story 1.3 컴포넌트 → 3.7 적용`, `Story 2.2 컴포넌트 → 4.1 재사용`)이 명시 추적

### 🟠 Major Issues
**없음.**

다음은 *worth flagging but not blocking*:

1. **Story 1.1 부트스트랩 단일 스토리에 다량 묶음** — Docker + Postgres+pgvector + Redis + FastAPI/Web/Mobile init + Sentry + slowapi + CI 게이트 + `.env.example` + `.gitignore` + `AGENTS.md`. 일반 표준이라면 *3-4개 스토리로 분할 권고*. 단:
   - Architecture가 *"Day-1 1-cmd 부팅"*을 핵심 영업 카드(B3 KPI, FR47)로 명시 → 단일 머지 단위가 *외주 인수자 관점에서* 가치 있음
   - 1인 8주 frame에서 분할은 over-tracking; W1 spike(R5)로 보호
   - **결론:** 의도된 묶음, 분할 권고하지 않음. 단 **3 sub-checklist**(Docker 부팅 / 풀스택 init / CI 게이트)로 PR 단위만 명시 권고.

2. **Story 8.4 운영 polish 단일 스토리에 대량 묶음** — Sentry 정교화 + Swagger 정리 + Rate limit 정교화 + LLM 캐시 정교화 + 표준 빈/로딩/에러 화면 일괄 + 앱 정보 화면 + Pytest 커버리지 70%. 일반 표준이라면 분할.
   - 의도: W6 *"운영 polish 일괄 슬롯"* 으로 묶어 cross-cutting 마무리
   - **결론:** 의도된 묶음. 단 PR 단위 5분할 권고: (a) Sentry/Swagger 정리, (b) Rate limit/캐시 정교화, (c) 표준 빈/로딩/에러 일괄, (d) 앱 정보 화면, (e) Pytest 70% 도달.

3. **DB 테이블 생성 타이밍 — 다수가 Story 1.1 시점에 일괄 생성**
   - PRD W1 결정 + Architecture Alembic 단일 migration 패턴 → `subscriptions`(Epic 6 사용), `audit_logs`(Epic 7 사용), `payment_logs`(Epic 6 사용)도 모두 W1에 생성 가능
   - 표준은 *"each story creates tables it needs"*이지만 1인 8주 + 외주 인수자에게 *단일 schema dump* 가치 더 큼 (인수자가 마이그레이션 history 따라가기 쉬움)
   - **결론:** 의도된 단일 schema. 단 Alembic migration **파일 단위는 epic별 분리 권고** (`001_initial.py` + `002_payment.py` + `003_audit.py` 등) — 그래야 외주 인수자가 epic 단위 schema 이해 가능.

### 🟡 Minor Concerns

4. **NFR-P10 (분석 외 API p95 ≤500ms)** — 어느 스토리 AC에도 명시 인용 없음.
   - **권고:** Story 8.4 AC에 *"분석 외 API endpoint p95 ≤500ms — Sentry transaction tracing으로 회귀 검증"* 1줄 추가.

5. **NFR-A1 (모바일 a11y label)** — 직접 인용 없음. RN 표준 props로 implicit 흡수 의도.
   - **권고:** Story 2.1 또는 Story 8.4 AC에 *"모든 인터랙티브 요소에 accessibilityLabel 명시 + VoiceOver/TalkBack 1회 수동 검증"* 1줄 추가.

6. **NFR-A2 (색상 대비 WCAG AA)** — 디자인 토큰 룰만 일반론, 검증 절차 부재.
   - **권고:** Story 1.1 AC에 *"디자인 토큰 색상 대비 WCAG AA(본문 4.5:1, 큰 텍스트 3:1) 통과 검증"* 1줄 추가, 또는 Story 8.4 표준 빈/로딩/에러 일괄 AC와 통합.

7. **NFR-UX5 (한국 식사 패턴 컨텍스트 주입)** — Story 3.6 시스템 프롬프트 사양에 미명시.
   - **권고:** Story 3.6 AC에 *"`generate_feedback` 시스템 프롬프트에 한국 식사 패턴 컨텍스트(아침-점심-저녁 비중 25/35/30, 회식·외식 빈도) 주입 강제"* 1줄 추가.

8. **PRD 도입부 카운트 오기** — *"총 9개 capability 영역, 48개 FR"* 표기. 실제 49개 FR. PRD 본문 #934 한 줄 수정 권고.

9. **Architecture 도입부 카운트 오기** — *"Functional Requirements (48 FR / 9 capability 그룹)"* 표기. 동일 오기 수정 권고.

### Independence & Forward Dependency Audit

수동 inspection — **forward dependency 위반 없음**:

| 잠재 split 패턴 | 원본 → 적용 | 명시 추적 | 상태 |
|---------------|----------|---------|------|
| `DisclaimerFooter` 컴포넌트 | Story 1.3 → Story 3.7 | ✅ 명시 | OK |
| `PermissionDeniedView` 컴포넌트 | Story 2.2 → Story 4.1 | ✅ 명시 | OK |
| `useNotificationPermission` hook | Story 4.1 in 4.1 (Story 2.2 hook 패턴 재사용) | ✅ 명시 | OK |
| Redis 인프라 / cache 키 표준 | Story 1.1 (셋업) → Story 3.6, 8.4 (정교화) | ✅ FR 매트릭스 split 명시 | OK |
| Rate limit (slowapi) | Story 1.1 (셋업) → Story 8.4 (정교화) | ✅ | OK |
| Sentry SDK / before_send | Story 1.1 (셋업) → Story 8.4 (정교화) | ✅ | OK |
| Swagger | Story 1.1 (자동) → Story 8.4 (정리·예시) | ✅ | OK |
| Docker Compose | Story 1.1 (1-cmd) → Story 8.5 (hardening) | ✅ | OK |
| LangSmith mask hook | Story 3.8 (셋업) — Story 8.6 (영업 자료 보드 링크) | ✅ | OK |
| Audit AOP | Story 7.1 (admin JWT) → Story 7.3 (audit) → Story 7.4 (self-audit + 마스킹) | ✅ epic 내 자연 의존 | OK |

**Cross-Story dependency 모두 forward 아님 (선행 → 후행) 또는 split 명시.** 실행 가능 순서가 명확하다.

### Story-Level Dependency Graph (Topological Order)

W1: 1.1 → 1.2 → 1.5 → 1.3 → 1.4 → 1.6  (Epic 1)
W2: 3.1 → 3.2 → 3.3 → 3.4 → 3.5  (Epic 3 RAG/LangGraph 핵심)
W3: 3.6 → 3.7 → 3.8  (Epic 3 마무리)
W4: 2.1 → 2.2 → 2.3 → 2.4 → 2.5  (Epic 2 모바일)
W5: 4.1 → 4.2 → 4.3 → 4.4 / 5.1·5.2·5.3 / 7.1 → 7.2 → 7.3 → 7.4  (Epic 4·5·7 동시 — 의존 그룹 분리)
W6: 8.1 → 8.2 → 8.3 → 8.4  (Epic 8 polish + 영업 답변)
W7: 6.1 → 6.2 → 6.3 / 8.5  (Epic 6 결제 + 8.5 deploy hardening)
W8: 8.6  (데모 영상 + 영업 자료)

**위 흐름은 PRD §Phased Schedule W1-W8과 정합.** 의존 violation 없음.

### Greenfield Indicators

- ✅ Initial project setup story (Story 1.1) — 명시
- ✅ Development environment configuration (`.env.example` + Docker Compose) — Story 1.1
- ✅ CI/CD pipeline early (Story 1.1) — `ci.yml` PR 게이트 + main → Vercel/Railway 자동 배포
- ✅ Architecture가 starter template 명시 (`pnpm create next-app` + `npx create-expo-app` + `uv init` + `pgvector/pgvector:pg17`)

### Summary

- **Critical Violations:** 0
- **Major Issues:** 3 (모두 *의도된 묶음*으로 acceptable, sub-PR 분할만 권고)
- **Minor Concerns:** 6 (NFR AC 보강 4건 + PRD/Architecture 카운트 오기 2건)
- **Forward Dependency 위반:** 0
- **Greenfield 부트스트랩 표준:** Pass

## Summary and Recommendations

### Overall Readiness Status

# ✅ **READY**

8주 구현 진입 가능. PRD/Architecture/Epics가 *Capability Contract → 컴포넌트·패턴 결정 → Epic·Story·AC* 의 추적 체인을 완전히 닫았으며, FR coverage 100%, forward dependency 0건, 컴플라이언스 4축 가드(의료기기·PIPA·식약처 광고·디스클레이머) 모두 코드 위치까지 명시.

### Critical Issues Requiring Immediate Action

**없음.** Implementation을 막는 critical issue 0건.

### Findings Summary

| 카테고리 | Critical | Major | Minor | 설명 |
|---------|---------|-------|------|------|
| Document Discovery | 0 | 0 | 0 | PRD/Arch/Epics 모두 최신, UX는 의도된 흡수 |
| PRD Analysis | 0 | 0 | 1 | 도입부 카운트 오기 ("48 FR" → 49 FR) |
| Epic Coverage | 0 | 0 | 0 | FR 49/49 100% 커버 |
| NFR Coverage | 0 | 0 | 4 | NFR-P10·A1·A2·UX5 스토리 AC 인용 부재 (보강 권고) |
| UX Alignment | 0 | 0 | 0 | UX 흡수 정합성 OK |
| Epic Quality | 0 | 3 | 1 | 의도된 묶음(Story 1.1·8.4·DB 단일 schema), Architecture 카운트 오기 |
| **합계** | **0** | **3** | **6** | |

### Recommended Next Steps

#### 즉시 적용 (Implementation 진입 전 1-2시간 작업)

1. **PRD 도입부 카운트 오기 수정** (`prd.md:938`) — *"48개 FR"* → *"49개 FR"*. 1 line edit.
2. **Architecture 도입부 카운트 오기 수정** (`architecture.md:27`) — *"Functional Requirements (48 FR / 9 capability 그룹)"* → *"49 FR / 9 capability 그룹"*. 1 line edit.
3. **NFR AC 4건 보강** — 모두 1줄 추가, 총 30분 작업:
   - Story 8.4: NFR-P10 (분석 외 API p95 ≤500ms 회귀 검증)
   - Story 8.4 또는 Story 2.1: NFR-A1 (모든 인터랙티브 요소 accessibilityLabel + VoiceOver/TalkBack 1회 수동 검증)
   - Story 1.1 또는 Story 8.4: NFR-A2 (디자인 토큰 색상 대비 WCAG AA 통과 검증)
   - Story 3.6: NFR-UX5 (`generate_feedback` 시스템 프롬프트에 한국 식사 패턴 25/35/30 + 회식·외식 컨텍스트 주입 강제)

#### 권고만, 진입 차단 아님

4. **Story 1.1 sub-PR 분할 가이드** — 단일 스토리는 유지하되 PR 단위 3분할 권고를 README/AGENTS.md에 명시: (a) Docker Compose + Postgres+pgvector + Redis 부팅, (b) 풀스택 init(FastAPI/Next.js/Expo), (c) CI 게이트 + Sentry/slowapi 셋업.
5. **Story 8.4 sub-PR 분할 가이드** — 5분할 권고: (a) Sentry/Swagger 정리, (b) Rate limit/캐시 정교화, (c) 표준 빈/로딩/에러 일괄, (d) 앱 정보 화면, (e) Pytest 70% 도달.
6. **Alembic migration epic별 파일 분리 권고** — `001_initial.py`(users/consents/meals/food_*) + `002_payment.py`(subscriptions/payment_logs) + `003_audit.py`(audit_logs) 등 epic별 독립 파일. 단일 schema 유지 + 외주 인수자에게 *"epic 단위 schema 흐름"* 가시성 ↑.

#### Implementation 시작 후 검증

7. **W1 day1 spike**(R5/R7 mitigation) — Docker 1-cmd 부팅 ≤ 10분 + 식약처 OpenAPI 호출 + 백업 경로 검증.
8. **W2 spike**(R1) — 한식 100건 음식명 매칭 정확도 1차 검증 (T3 KPI baseline).
9. **W3 LangSmith 회귀 평가 baseline 확보**(NFR-O3) — 한식 100건 데이터셋 업로드 후 첫 평가 정확도 측정.
10. **W4 day1 spike**(R2) — RN react-native-sse 실제 디바이스(iOS/Android)에서 5분 세션 동작 + polling fallback 결정.
11. **W7 day1 dry-run**(R5) — Vercel + Railway + R2 prod 배포 1회.

### Strengths (영업 카드)

이 산출물의 *영업 통과 가능성*을 직접 강화하는 강점:

1. **Capability Contract 단일 출처** — FR 49 + NFR 68 + Compliance C1~C6 + Risk R1~R10 + Domain (식약처/KDRIs/22종) 모두 명시 매트릭스. PRD가 *"여기 명시되지 않은 기능은 정식 범위에 포함되지 않는다"* 선언 — 외주 발주자 영업 자리에서 *"왜 8주에 됨"* 답변 즉시 가능.
2. **컴플라이언스 4-layer 방어** — 명명(`fit_score`) + 디스클레이머 4 위치(`DisclaimerFooter` 컴포넌트 + Web `/legal/*` + 결과 푸터 + 설정) + 광고 가드(C5 정규식 + 안전 워딩 매핑) + PIPA 동의 차단(`require_automated_decision_consent` Dependency). FDA Warning Letter 시사점 반영.
3. **외주 인수인계 가시성** — Docker 1-cmd + README 5섹션 + SOP 4종 + FAQ 5종 + Runbook 3종 + Swagger + LangSmith 보드 공개 링크. B3 KPI(8시간 부팅) + Journey 7(클라이언트 신규 개발자) 라이브 검증 가능.
4. **Self-RAG + 듀얼-LLM + 인용형 피드백** — 학술 패턴(Asai 2023) + 한국 1차 출처(KDRIs/대비/대당/식약처) + 듀얼-LLM router(OpenAI 메인 + Claude 보조) — 글로벌 앱(Noom/MFP/Cronometer) 시장 빈자리 정확 응답.
5. **LLM 옵저버빌리티 영업 카드** — LangSmith 자동 트레이싱 + 한식 100건 회귀 평가 + 마스킹 hook + 공개 보드 링크. *"프로덕션 LLM 동작·품질·추세를 영업 보드로 입증"* (NFR-O4).

### Risks Watch (Implementation 중 모니터링)

PRD §Risk Mitigations와 정합 — 실행 중 추가 모니터링 필요:

- **R1 음식명 매칭 정확도** — W2 + W7 회귀 테스트 (T3 KPI ≥ 90%)
- **R2 RN SSE 호환** — W4 day1 spike + polling fallback 결정 (T5 KPI ≤ 1 끊김)
- **R6 LLM 비용 폭증** — Redis 캐시 + 일별 cron 알림 + Story 8.5 자동 차단
- **R8 식약처 22종 갱신** — 분기 1회 `verify_allergy_22.py` SOP 실행
- **R9 PIPA 시행령 갱신** — 분기 1회 입법예고 추적

### Final Note

이 평가는 **9개의 issue를 6개 카테고리에서 식별**했다. Critical 0건. Major 3건은 모두 *의도된 묶음*(Story 1.1·8.4 큼, DB 단일 schema)이며 1인 8주 + 외주 인수자 frame에서 acceptable. Minor 6건은 모두 *AC 한 줄 추가 또는 1 line edit* 수준으로 implementation 진입 전 30분 작업이면 모두 보강 가능.

**Recommendation: 즉시 적용 1-3번(카운트 오기 2건 + NFR AC 4건 보강) 완료 후 Story 1.1부터 W1 부트스트랩 시작.** Story 1.1 day1 spike(R5/R7) 통과를 W1 day2 진입 게이트로 사용하면 8주 일정 진입이 안전하다.

---

**Assessment Complete:** 2026-04-27
**Assessor:** Winston (System Architect) — `bmad-check-implementation-readiness`
**Report:** `_bmad-output/planning-artifacts/implementation-readiness-report-2026-04-27.md`

---

## Post-Assessment Updates Applied (2026-04-27)

평가 직후 사용자(hwan) 결정으로 6건 보강 즉시 적용 — Implementation 진입 차단 사유 0건으로 완전 정리.

| # | 권고 | 적용 위치 | 변경 내용 |
|---|------|---------|---------|
| 1 | PRD 도입부 카운트 오기 수정 | `prd.md` §Functional Requirements 도입부 | "총 9개 capability 영역, 48개 FR" → "49개 FR" |
| 2 | Architecture 도입부 카운트 오기 수정 | `architecture.md` §Project Context Analysis | "Functional Requirements (48 FR / 9 capability 그룹)" → "49 FR / 9 capability 그룹" |
| 3 | NFR-UX5 (한국 식사 패턴 컨텍스트 주입) | `epics.md` Story 3.6 AC | "`generate_feedback` 시스템 프롬프트에 한국 식사 패턴 컨텍스트(아침-점심-저녁 25/35/30, 회식·외식 빈도) 주입 강제" |
| 4 | NFR-P10 (분석 외 API 지연 게이트) | `epics.md` Story 8.4 AC | "분석 외 API endpoint p95 ≤500ms — Sentry transaction tracing 회귀 검증 + 위반 시 알림" |
| 5 | NFR-A2 (디자인 토큰 색상 대비 검증) | `epics.md` Story 8.4 AC | "디자인 토큰 색상 대비 WCAG AA(본문 4.5:1, 큰 텍스트 3:1) 통과 검증 + 1회 수동 spot check" |
| 6 | NFR-A1 (모바일 a11y baseline) | `epics.md` Story 8.4 AC | "모바일 모든 인터랙티브 요소에 `accessibilityLabel` prop 채움 + iOS VoiceOver / Android TalkBack 1회 수동 검증" |

**부수 작업:** `implementation-readiness-report-2026-04-27-v1.md`(stale) 삭제.

### 적용 후 상태

- ✅ FR Coverage: 49/49 = 100%
- ✅ NFR 명시 인용 보강: 64 → **68/68 = 100%** (Story AC 레벨)
- ✅ Critical 이슈: 0
- ✅ Major 이슈: 3 (의도된 묶음, 수용)
- ✅ Minor 이슈: 0 (모두 해소)
- ✅ Forward Dependency 위반: 0

**Implementation 진입 게이트 통과** — Story 1.1 W1 day1 부트스트랩 spike(R5/R7 mitigation: Docker 1-cmd ≤10분 부팅 + 식약처 OpenAPI 호출 + 백업 경로) 진입 가능.
