---
stepsCompleted: ['step-01-init', 'step-01b-continue', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete']
workflowComplete: true
completionDate: 2026-04-26
releaseMode: phased
inputDocuments:
  - _bmad-output/brainstorming/brainstorming-session-2026-04-26-2038.md
  - _bmad-output/planning-artifacts/product-brief-BalanceNote-2026-04-26.md
  - _bmad-output/planning-artifacts/research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md
workflowType: 'prd'
project_name: 'AI_diet'
product_name: 'BalanceNote'
project_type: 'greenfield'
classification:
  projectType: mobile_app
  projectTypeNote: '주축 mobile_app(RN) + 동반 web_app(Next.js) + api_backend(FastAPI). 단일 매핑 강제 — 멀티 컴포넌트 풀스택'
  domain: healthcare
  domainSubTrack: wellness  # 의료기기 미분류 — 식약처 가이드라인 저위해도 일상 건강관리 명시 예시 적용
  complexity: high
  projectContext: greenfield
scopeNotesPrelim:
  principle: 'UIUX 가시 영역은 서비스 완성도 기준 IN, 백엔드 비가시는 기본 기술로 OK. OUT 사유는 redundant 또는 1인 8주 anti-pattern만 유효 (포트폴리오 frame은 무효 사유)'
  in_total_count: 25
  in_core_13_from_brainstorming:
    - 1. Google OAuth 로그인 + JWT
    - 2. 건강 프로필 입력 (나이/체중/목표/알레르기)
    - 3. 식단 텍스트+사진 입력 CRUD (모바일 RN)
    - 4. OCR/Vision 사진→음식 항목 추출
    - 5. LangGraph 6노드 분석 파이프라인 (Self-RAG 포함)
    - 6. 두 종류 RAG (음식 영양 1,500-3,000 + 가이드라인 50-100 chunks)
    - 7. 스트리밍 채팅 UI (RN, react-native-sse)
    - 8. 일별 식단/피드백 기록 화면 (RN)
    - 9. 푸시 알림 — 미기록 nudge (Expo + cron)
    - 10. Next.js 사용자 주간 리포트 (Recharts)
    - 11. Next.js 관리자 화면 (반응형)
    - 12. Redis 캐시 (LLM 응답 + 식품 검색)
    - 13. Docker Compose + 클라우드 배포 + Sentry + Pytest + Swagger + README/SOP
  in_uiux_completeness_added:
    - 14. 로그아웃 — 로그인 있는 서비스 필수
    - 15. 회원 탈퇴/계정 삭제 — PIPA 권리 + 사용자 가시 필수
    - 16. 온보딩 약관·개인정보 동의 (별도 분리) — PIPA 민감정보 별도 동의 의무
    - 17. 디스클레이머 표시 강화 (온보딩 + 결과 화면 푸터, 한/영) — research 3.4 표준 텍스트 적용
    - 18. 설정 화면 (진입점 — 알림·약관·처리방침·디스클레이머·회원탈퇴 통합)
    - 19. 알림 설정 (푸시 ON/OFF)
    - 20. 프로필 수정 화면 — 건강 프로필 CRUD 확장
    - 21. 관리자 로그인/권한 분리 (admin role) — Web 관리자 보호
  in_payment_added:
    - 22. 결제/구독 sandbox (Toss Payments 또는 Stripe 정기결제 1플랜) — 결제 화면 + 영수증/이용내역 + 해지. W7 4-5일 배정
  in_completeness_added_post_audit:
    - 23. 데이터 내보내기 (PIPA 권리) — 식단/피드백/프로필 JSON 또는 CSV 다운로드 (모바일 + Web). PIPA 정보주체 권리 의무
    - 24. 온보딩 튜토리얼 (2-3 화면) — 약관 동의 → 사용법 안내 → 프로필 입력 흐름. 첫 사용 멈춤 방지
    - 25. 관리자 활동 로그 — admin role 조회/수정 액션 기록 (audit log). B2B 외주 신뢰 카드
  implicit_in_as_acceptance_criteria:
    - 모바일 권한 요청 UI 흐름 (푸시·카메라·사진첩) — IN #3 식단 CRUD + IN #9 푸시 알림 ACs로 명시
    - 표준 빈 상태 / 로딩 / 에러 화면 — 모든 화면(IN #1, 3, 7, 8, 10, 11 등) ACs로 명시
    - 앱 정보 화면 (버전·OSS 라이선스 고지) — IN #18 설정 화면 sub-entry로 흡수
  out_with_valid_reasons:
    - 이메일 인증 풀세트 (비번/아이디 찾기) — redundant (Google OAuth)
    - Kafka/Celery — redundant (FastAPI BackgroundTasks) + 1인 anti-pattern
    - MSA — 1인 anti-pattern
    - FCM 직접 통합 — redundant (Expo Notifications가 RN 표준이고 FCM 추상화)
    - 자체 LLM Fine-tuning — 데이터+학습+평가 8주 anti-pattern
    - 풀 논문 RAG — 정제+인용 평가 8주 anti-pattern
    - DTx 인허가 — 임상+심사 1년+ anti-pattern
    - 분리된 UX 산출물 (별도 wireframe·디자인 시스템) — 사용자 명시 결정 (PRD/스토리에 흡수)
    - 결제 풀세트 (사업자등록·PG계약·세금정산) — 1인 anti-pattern (sandbox만 IN)
---

# Product Requirements Document — BalanceNote (저장소: AI_diet)

**Author:** hwan
**Date:** 2026-04-26
**Frame:** 외주 영업용 포트폴리오 (학습용 X, 상용 SaaS X)

---

## Executive Summary

BalanceNote는 한국 헬스테크 외주 시장을 겨냥한 1인 8주 레퍼런스 구현물이다. 식약처 식품영양성분 DB·보건복지부 KDRIs 2020·대한비만학회 진료지침 9판(2024)·대한당뇨병학회 매크로 권고를 RAG로 직접 인용하는 AI 영양 분석 시스템으로, 외주 발주자(병원 의료정보팀·헬스케어 스타트업 CTO·보험사 디지털전략팀·식품기업 헬스케어 신사업·제약사 디지털전략팀)에게 *"AI 신뢰성 책임 추적이 가능한 LangGraph+RAG 솔루션을 8주 안에 납품할 수 있는 1인 개발자"* 라는 메시지를 시연 가능한 형태로 입증한다.

해결하려는 페인은 두 층위다. **외주 발주자 측**은 AI 영양·식단 솔루션을 발주하고 싶지만 글로벌 앱(Noom·MyFitnessPal·Cronometer)이 자체 큐레이션 DB라 한국 컴플라이언스(병원·보험사·식품사·식약처)를 통과하지 못하고, 자체 LLM/RAG 인프라 구축 비용 흡수가 부담스럽다. **1인 외주 개발자 측**은 *"왜 우리에게 맡겨야 하는가"* 라는 질문에 GitHub 토이 코드가 아닌 운영 가능 도메인 솔루션으로 답해야 한다. 두 페인의 교집합 = "한국 1차 출처를 직접 인용하는 8주 1인 도메인 외주" 포지션 = 외주 진입점.

대상 사용자는 두 층으로 분리된다. **1차 — 외주 발주자(Brief의 진짜 독자):** 병원 의료정보팀, 헬스케어 스타트업 CTO, 보험사 디지털전략팀, 식품·식자재 기업 헬스케어 신사업, 제약사 디지털전략팀 — 5개 유형 모두 적합도 ★★ ~ ★★★★★. **2차 — 데모 시연용 엔드유저 페르소나:** 체중 감량 / 근육 증가 / 유지 / 당뇨 관리 4개 `health_goal` 페르소나. 데모 시나리오 9포인트는 1차 외주 고객사 유형별로 강조 노드를 분기한다(병원: Self-RAG + 인용 / 보험사: 푸시 + 리포트 / 식품사: DB 확장 + 추천 / 스타트업: 모듈 구조 + Docker).

성공 정의는 사용자 활성화 KPI가 아닌 **영업 통과 가능성**이다: (1) 9포인트 데모 시나리오가 라이브 환경에서 끊김 없이 동작, (2) 외주 클라이언트 개발팀이 README + Docker Compose만으로 1일 내 로컬 부팅 가능, (3) 영업 답변 5종 closing(차별화/인허가/적용/8주 가능성/유지보수)을 README·SOP·FAQ로 1차 답변, (4) 고객사 유형별 페르소나 데모 영상 5종, (5) 컴플라이언스 안전판 명문화 — 의료기기 미분류(식약처 저위해도 명시 예시 정확 일치) + PIPA 2026.03.15 자동화 의사결정 동의 + 표준 디스클레이머(한/영).

### What Makes This Special

핵심 차별화는 네 가지다.

**1. 한국 1차 공식 출처 RAG.** 식약처 식품영양성분 DB(공공데이터 OpenAPI), 보건복지부 KDRIs 2020, 대한비만학회 진료지침 9판, 대한당뇨병학회 매크로 권고를 가이드라인 RAG에 직접 시드한다. 모든 피드백 텍스트가 출처를 인용 가능 — *"오늘 점심은 탄수화물 비중이 70%로 권장 범위(55-65%)를 초과했어요. (출처: 2020 KDRIs)"* 형식. 글로벌 앱이 제공하지 못하는 **책임 추적성**이 병원·보험사·식품사 컴플라이언스 통과의 핵심 카드다.

**2. Self-RAG 재검색 노드.** LangGraph 6노드(`parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality` → `fetch_user_profile` → `evaluate_fit` → `generate_feedback`) 안에서 검색 신뢰도(`retrieval_confidence`)를 평가해 낮을 때 쿼리를 재작성하고 1회 재검색한다. 음식명 정규화 사전("짜장면" ≠ "자장면") + 임베딩 fallback으로 한국식 음식 매칭 정확도를 끌어올린다. 환각률 ↓ → 영업 답변 가능.

**3. 한국 표준 통합 데이터 모델.** 식약처 알레르기 22종이 `users.allergies` 도메인으로, KDRIs AMDR + 대비/대당학회 권고가 `health_goal` enum별 매크로 룰(weight_loss / muscle_gain / maintenance / diabetes_management)로, 식약처 영양 성분 키가 `food_nutrition.nutrition` jsonb 표준으로 스키마에 박혀 있다. `fit_score` 알고리즘은 Mifflin-St Jeor BMR + TDEE 활동지수 + KDRIs AMDR + 식약처 22종 + 대비/대당학회 권고를 단일 알고리즘(Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 0-100점)에 통합한다. 외주 인수 시 한국 규제 정합성 작업이 0에 수렴한다.

**4. 외주 인수인계 가능한 운영 산출물.** Docker Compose 1-cmd 실행, Sentry 에러 트래킹, Swagger API 문서, README/SOP, 디스클레이머 텍스트(한/영), 개인정보 동의 패턴(PIPA 민감정보 별도 동의), PIPA 2026.03.15 자동화 의사결정 동의서, 의료기기 미분류 영업 답변 — 학습용 토이가 아닌 **운영 외주 산출물 수준**.

**핵심 인사이트(왜 지금인가).** 한국 디지털헬스케어 시장은 2023년 6.5조 원(YoY +13.5%, KISDI 2029년까지 연 +3.5%)이며 5개 외주 고객사 유형 모두에서 AI 영양·식단 발주 사례가 누적되고 있다(루닛케어 AI 식단, 풀무원 NDP, KB오케어, 대상웰라이프 당프로 2.0, 현대그린푸드×디앤라이프). 동시에 PIPA 2026.03.15 시행으로 자동화 의사결정 동의 의무가 강화되어 "처음부터 컴플라이언스 갖춘 외주사" 수요가 늘어나는 시점이다. 글로벌 앱의 컴플라이언스 빈자리 + 1인 개발자의 영업 자산 부재 = 진입 윈도우.

## Project Classification

- **Project Type:** `mobile_app` (주축 — RN 모바일이 핵심 사용자 UX: 식단 입력 → 스트리밍 채팅 피드백 → 일별 기록) + 동반 `web_app`(Next.js 사용자 주간 리포트 + 관리자) + `api_backend`(FastAPI + LangGraph 6노드). 멀티 컴포넌트 풀스택.
- **Domain:** `healthcare` — 웰니스 sub-track. 식약처 가이드라인 저위해도 일상 건강관리 명시 예시(*"식사 소비량 모니터·기록·체관리를 위한 식이 활동을 관리하고 과식 시 경고"*)에 정확히 일치 → 의료기기 미분류로 진입. 단 진단성 발언("당신은 당뇨가 의심됩니다") 회피 필수.
- **Complexity:** **high** — (1) 멀티 컴포넌트 풀스택(RN + Next.js + FastAPI + Postgres + pgvector + Redis + Docker), (2) LangGraph 6노드 + Self-RAG + Structured Output(Pydantic + retry), (3) 식약처/PIPA/의료기기 경계 컴플라이언스, (4) 한국 영양 도메인 깊은 통합.
- **Project Context:** **greenfield** — 기존 코드/문서 없음. 1인 8주 신규 개발.
- **Frame Note:** 본 PRD의 success criteria·우선순위·시간 배분은 *영업 통과 가능성* 으로 평가한다. 단 IN/OUT 결정은 redundant·anti-pattern 사유만 유효 — UIUX 가시 영역은 서비스 완성도 기준 IN bias.

---

## Success Criteria

### User Success

본 산출물의 사용자는 두 층으로 분리되며, 각 층의 success는 다른 모먼트에서 측정된다.

**1차 사용자 — 외주 발주자 (Brief의 진짜 독자)**

| 페르소나 | 'aha!' 모먼트 (success) | 측정 가능한 outcome |
|---------|----------------------|--------------------|
| **헬스케어 스타트업 CTO** | "Docker Compose 1-cmd로 PoC 환경이 즉시 부팅된다" | `docker compose up`만으로 로컬 부팅 ≤ 10분, README 따라 4주 내 자체 변형 PoC 완성 가능 |
| **병원 의료정보팀** | "AI 답변마다 출처(KDRIs/대비학회)가 인용되고, 디스클레이머가 자동 표시된다" | 시연 중 5건 질의에 모두 출처 인용 표시, 의료기기 미분류 영업 답변 SOP가 즉시 전달 가능 |
| **보험사 디지털전략팀** | "푸시 nudge → 미기록 → 주간 리포트의 인게이지먼트 흐름이 라이브로 보인다" | 9포인트 데모 중 푸시/리포트 노드(시나리오 #6, #8)가 끊김 없이 동작 |
| **식품기업 헬스케어 신사업** | "음식 RAG에 자사 제품 시드만 추가하면 추천이 즉시 동작" | DB 시드 추가 후 추천에 반영되는 시간 ≤ 1시간 (시연 가능) |
| **제약사 디지털전략팀** | "현재는 웰니스 트랙이지만 DTx 인허가 전 PoC 도구로 확장 경로가 명확" | "DTx 확장 가능 PoC" 영업 답변이 README/SOP에 명문화 |

**2차 사용자 — 데모 시연용 엔드유저 페르소나 (4종)**

`weight_loss / muscle_gain / maintenance / diabetes_management` 4개 `health_goal` 페르소나가 9포인트 데모 시나리오를 끊김 없이 경험. 'aha!' 모먼트:
- 사진 한 장 촬영 → 30초 내 음식 항목 추출 + 매크로 분석 + 한국 가이드라인 인용 피드백 도착
- 음식 인식 실패 시 *"이게 짜장면이 맞나요? 양은 1인분인가요?"* 형태로 AI가 재질문 (Self-RAG)
- 저녁 8시 미기록 시 푸시 nudge 도착 → 탭하면 식단 입력 화면으로 직행

### Business Success

본 산출물은 영업 포트폴리오이므로 비즈니스 KPI는 *사용자 활성화* 가 아닌 **영업 통과 가능성** 으로 정의한다.

| # | KPI | 목표 (8주 완료 시점) | 측정 방법 |
|---|----|---------------------|----------|
| B1 | **영업 답변 5종 closing** | 5종 모두 README/SOP/FAQ 1차 답변 가능 | 차별화 / 의료기기 인허가 / 우리 회사 적용 / 8주 가능성 / 유지보수 — 각 항목 ≥ 1페이지 답변 문서화 |
| B2 | **데모 통과** | 9포인트 시나리오 라이브 환경 100% 동작 | 시연 영상 5종(고객사 유형별 페르소나) 무편집 1회 촬영 가능 |
| B3 | **인수인계 가능성** | 외주 클라이언트 개발팀 1일 내 로컬 부팅 | README + Docker Compose만으로 부팅. 신규 개발자 onboarding 시간 ≤ 8시간 |
| B4 | **컴플라이언스 안전판 명문화** | 3종 문서 완비 | (1) 의료기기 미분류 입장 SOP, (2) PIPA 2026.03.15 자동화 의사결정 동의서 템플릿, (3) 표준 디스클레이머(한/영) |
| B5 | **포트폴리오 페이지·영업 자료** | 1식 완비 | 포트폴리오 랜딩 페이지 + 데모 영상 5종 + 영업 첫 미팅 자료(FAQ/SOP) |

**Vision-stage 비즈니스 KPI (참고, MVP 평가 대상 아님)**
- 6개월: 5개 고객사 유형 중 1-2개에서 첫 외주 견적→발주→납품 사이클 1회 완주
- 1-2년: "한국 헬스테크 RAG 외주 라인업" 표준 모듈화 (가이드라인 RAG 시드 키트 + LangGraph 6노드 템플릿 + Docker 인수인계 패키지)

### Technical Success

운영 외주 산출물 수준의 기술적 완성도. *코드만이 아닌 운영·컴플라이언스 산출물* 까지 포함한다.

| # | 항목 | 통과 기준 |
|---|------|----------|
| T1 | **6노드 LangGraph 안정성** | `parse_meal → retrieve_nutrition → evaluate_retrieval_quality → fetch_user_profile → evaluate_fit → generate_feedback` 전 노드 100회 연속 호출 시 실패율 ≤ 2% (Pydantic + retry 1회 포함) |
| T2 | **Self-RAG 재검색 동작** | `retrieval_confidence < threshold` 케이스에서 쿼리 재작성 → 재검색 → top-3 갱신이 정상 작동 (테스트 케이스 ≥ 5건) |
| T3 | **음식명 매칭 정확도** | 한식 100건 테스트셋 ("짜장면/자장면", "김치찌개/김치 찌개" 등 변형 포함)에서 정규화 사전 + 임베딩 fallback 결합 정확도 ≥ 90% |
| T4 | **인용 형식 100%** | `generate_feedback` 출력 모든 권고 텍스트에 `(출처: <기관명>, <문서명>, <연도>)` 패턴 포함. 100건 샘플 검증 |
| T5 | **스트리밍 채팅 안정성** | RN(react-native-sse) ↔ FastAPI 스트리밍 5분 세션 50회 연속 끊김 ≤ 1회 |
| T6 | **컨테이너 1-cmd 부팅** | `docker compose up`으로 Postgres+pgvector+Redis+FastAPI+seed 전체 부팅 ≤ 10분 (콜드 스타트) |
| T7 | **테스트 커버리지** | LangGraph 6노드 + 핵심 API + fit_score 알고리즘 — 핵심 경로 Pytest 커버리지 ≥ 70% |
| T8 | **에러 트래킹 운영** | Sentry에 핵심 노드 실패·API 예외·LLM 호출 실패가 자동 수집되고 알림 채널 연동 |
| T9 | **API 문서 완비** | Swagger/OpenAPI에 전 엔드포인트 + 요청/응답 스키마 + 에러 코드 명세 |
| T10 | **컴플라이언스 가드레일 동작** | `generate_feedback`이 식약처 광고 금지 표현(진단/치료/예방/완화) 패턴을 필터링하고 안전 대안 워딩으로 치환 (테스트 케이스 ≥ 10건) |

### Measurable Outcomes

8주 종료 시점 통과 체크리스트(이진 통과/실패):

- [ ] 9포인트 데모 시나리오 5종 영상 (각 ≤ 5분, 무편집 1회 촬영)
- [ ] README + Docker Compose로 신규 개발자 부팅 ≤ 8시간 (외부 검증 1회)
- [ ] 영업 답변 5종 closing 문서 (각 ≥ 1페이지)
- [ ] 컴플라이언스 3종 문서 (의료기기 미분류 SOP / PIPA 동의서 템플릿 / 디스클레이머 한·영)
- [ ] 가이드라인 RAG 시드 ≥ 50 chunks (KDRIs + 대비/대당학회 + 식약처 가이드라인 + 질병관리청 표준)
- [ ] 음식 영양 DB ≥ 1,500건 (식약처 OpenAPI 시드, 한식 우선)
- [ ] LangGraph 6노드 + Self-RAG 재검색 통합 테스트 통과
- [ ] fit_score 알고리즘 (Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15) 단위 테스트 통과
- [ ] Sentry + Swagger + Pytest 커버리지 ≥ 70% 운영 산출물 완비
- [ ] 포트폴리오 랜딩 페이지 + 영업 첫 미팅 자료 패키지

---

## Product Scope

### MVP — Minimum Viable Product (25 IN, 8주 1인 개발)

**핵심 13항목 (브레인스토밍 v2 확정)**

1. Google OAuth 로그인 + JWT
2. 건강 프로필 입력 (나이/체중/신장/목표/알레르기 22종)
3. 식단 텍스트 + 사진 입력 CRUD (RN 모바일)
4. OCR/Vision 사진 → 음식 항목 추출 (OpenAI Vision)
5. LangGraph 6노드 분석 파이프라인 (Self-RAG 재검색 포함)
6. 두 종류 RAG — 음식 영양 DB (1,500-3,000건, 식약처 OpenAPI 시드) + 영양 가이드라인 미니 지식베이스 (50-100 chunks)
7. 스트리밍 채팅 UI (RN, react-native-sse)
8. 일별 식단/피드백 기록 화면 (RN)
9. 푸시 알림 — 미기록 nudge (Expo Notifications + cron)
10. Next.js 사용자 주간 리포트 (Recharts)
11. Next.js 관리자 화면 (반응형)
12. Redis 캐시 (LLM 응답 + 식품 검색)
13. Docker Compose + 클라우드 배포(Vercel + Railway + Cloudflare R2) + Sentry + Pytest + Swagger + README/SOP

**UIUX 완성도 보강 8항목 (서비스 필수 IN)**

14. 로그아웃 (RN + Web 공통)
15. 회원 탈퇴 / 계정 삭제 (PIPA 권리 의무)
16. 온보딩 약관 동의 + 개인정보 동의(별도 분리, PIPA 민감정보)
17. 디스클레이머 표시 — 온보딩 + 결과 화면 푸터(한/영 텍스트, research 3.4 표준)
18. 설정 화면 — 진입점 (프로필 수정·알림 설정·약관·처리방침·디스클레이머 보기·회원 탈퇴 통합)
19. 알림 설정 — 푸시 ON/OFF 토글
20. 프로필 수정 화면 — 건강 프로필 CRUD 확장
21. 관리자 로그인 + admin role 권한 분리 — Web 관리자 보호

**결제/구독 1항목 (sandbox 레벨 IN)**

22. Toss Payments 또는 Stripe sandbox 정기결제 1플랜 — 결제 화면 + 영수증/이용내역 + 구독 해지 (W7 4-5일)

**서비스 완성도 보강 3항목 (감사 후 추가 IN)**

23. **데이터 내보내기 (PIPA 권리)** — 사용자 자기 식단/피드백/프로필을 JSON 또는 CSV로 다운로드 (모바일 + Web). PIPA 정보주체 권리 법정 의무.
24. **온보딩 튜토리얼** (2-3 화면) — 약관·개인정보 동의 → 사용법 간단 안내(사진 입력 / AI 피드백 / 디스클레이머) → 건강 프로필 입력. 첫 사용 멈춤 방지.
25. **관리자 활동 로그 (audit log)** — admin role의 사용자 조회·수정 액션을 시간/사용자/액션으로 기록. B2B 외주 신뢰 카드(누가 무엇을 봤는지 추적 가능).

**암묵 IN (기존 항목의 Acceptance Criteria로 흡수)**

- **모바일 권한 요청 UI 흐름** (푸시·카메라·사진첩 권한 요청 → 거부 시 안내 → 설정 가이드) → IN #3 식단 사진 CRUD + IN #9 푸시 알림의 AC에 명시 반영.
- **표준 빈 상태 / 로딩 / 에러 화면** ("기록 없음 — 첫 식단을 입력하세요" / 스켈레톤 / "오류 — 다시 시도") → 모든 화면(IN #1, 3, 7, 8, 10, 11 등)의 AC에 명시 반영.
- **앱 정보 화면** (앱 버전 / OSS 라이선스 고지 / 빌드 정보) → IN #18 설정 화면의 sub-entry로 흡수.

**MVP 명시 OUT (사유 정합)**

| 항목 | OUT 사유 |
|------|---------|
| 이메일 인증 풀세트(비번/아이디 찾기) | redundant — Google OAuth |
| Kafka/Celery | redundant — FastAPI BackgroundTasks + 1인 anti-pattern |
| MSA | 1인 anti-pattern |
| FCM 직접 통합 | redundant — Expo Notifications가 RN 표준이고 FCM 추상화 |
| 자체 LLM Fine-tuning | 데이터+학습+평가 8주 anti-pattern |
| 풀 논문 RAG | 정제+인용 평가 8주 anti-pattern |
| DTx 인허가 | 임상+심사 1년+ anti-pattern |
| 분리된 UX 산출물 (별도 wireframe·디자인 시스템) | 사용자 명시 결정 (PRD/스토리에 흡수) |
| 결제 풀세트 (사업자등록·PG계약·세금정산) | 1인 anti-pattern (sandbox만 IN) |

### Growth Features (Post-MVP, 외주 첫 사이클 후)

외주 클라이언트별 어댑터 작업으로 확장 — *MVP 코어를 그대로 유지하면서 모듈만 교체* 하는 패턴.

- **(식품기업)** 자사 제품 카탈로그 음식 RAG 통합 — `food_nutrition`에 자사 SKU 시드 추가, 추천 시 우선 노출. 구매 연계(B2B → B2C 다리)
- **(보험사)** 인센티브 연동 — 일별 기록·주간 리포트를 보험 인센티브 KPI로 변환 (예: "300만보 → 3만원" 모델의 식단 버전)
- **(병원)** EMR 연동 — 환자 데이터(BMI, 만성질환, 약물) 수신 → `health_goal`/`allergies` 자동 prefill, 의료진 검토 인터페이스
- **(스타트업)** PoC 변형 — LangGraph 노드 단위 교체(예: `evaluate_fit`을 클라이언트 알고리즘으로), 4주 PoC 변형 패키지
- **A/B 테스트 인프라** — `generate_feedback` 톤·인용 패턴 비교
- **알림 히스토리 + 알림 정책 세분화** — 시간대별·요일별·지표별 푸시 룰
- **데이터 다운로드/이전 권리** — PIPA 권리 풀 구현
- **다국어** — 영문 UI (글로벌 데모용)

### Vision (Future, 1-2년)

**"한국 헬스테크 RAG 외주 라인업"** 표준 모듈 구축 — 단일 1인 외주에서 *도메인 외주사* 포지션으로 전환.

1. **가이드라인 RAG 시드 키트** — 헬스케어 도메인별 가이드라인(영양/만성질환/소아/노인/임산부) 표준 시드 + 메타데이터 스키마 + 인용 품질 평가 도구
2. **LangGraph 노드 템플릿** — `parse_X → retrieve_Y → evaluate_quality → enrich_Z → evaluate_fit → generate_response` 패턴을 도메인별 인스턴스화 (영양·만성질환 관리·운동 처방 등)
3. **Docker 1-cmd 외주 인수인계 패키지** — 클라우드 마이그레이션 가이드(Railway → AWS/GCP/Azure) + 보안 점검 체크리스트 + SOP 템플릿
4. **확장 시나리오** — (a) 식품사 자사 제품 솔루션, (b) 보험사 인센티브 행동변화 플랫폼, (c) 제약사 DTx 인허가 전 PoC 도구, (d) 병원 EMR 연동 환자 식단 가이드

---

## User Journeys

본 산출물은 두 층 사용자(B2C 모바일 엔드유저 + B2B 외주 발주자)에 더해 운영·인수인계 페르소나까지 매핑한다. 영업 포트폴리오 frame 특성상 B2B 발주자 journey가 1차 가치 증명 경로다.

### Journey 1 — 모바일 엔드유저 Happy Path (체중 감량 페르소나)

**Persona:** 지수 (33, 직장인 여성, 체중 감량 목표 -5kg). 식약처 22종 알레르기 중 *복숭아* 표시. health_goal = `weight_loss`.

**Opening — 평일 점심 직후, 책상 앞.** 동료들과 짜장면집을 갔다 왔다. *"또 짜장면이네. 한식 다이어트 정말 어렵다. 이번 주 매크로 망한 것 같은데 정확히 얼마나 망한 거지?"*

**Rising Action.** 앱을 연다(이미 Google 로그인 + 건강 프로필 입력 완료, 온보딩 튜토리얼 통과). 모바일 식단 입력 화면 → 카메라 권한이 이미 허용된 상태(권한 요청 흐름 1회 완료) → 짜장면 + 군만두 사진 촬영. 화면에 스피너 → OCR/Vision 호출. 1.5초 후 *"짜장면 1인분, 군만두 4개 인식됨 — 맞으신가요?"* 확인 카드. 탭으로 확정.

**Climax.** 스트리밍 채팅 UI에 글자가 한 글자씩 흐른다. *"오늘 점심은 탄수화물 비중이 약 71%로 권장 범위(55-65%)를 초과했어요. 군만두의 포화지방도 한 끼 권고 한도에 가깝습니다. 저녁에 단백질을 25g 정도(닭가슴살 100g, 두부 1모 등) 추가하시면 매크로 균형이 맞춰집니다. (출처: 보건복지부 2020 KDRIs, 대한비만학회 진료지침 2024)"* 화면 하단에 fit_score 62점 + "건강 목표 부합도 점수입니다 — 의학적 진단이 아닙니다" 디스클레이머 푸터.

**Resolution.** *"오늘 저녁은 단백질 위주로 가야겠다."* 식단 자동 저장. 저녁 8시 미기록 시 푸시 nudge가 도착할 것이라는 점을 안다. 닫기. 새로운 일상.

**Capability mapping:** Google OAuth(IN #1) · 건강 프로필(IN #2) · 식단 사진 CRUD + 카메라 권한(IN #3, 암묵 IN) · OCR/Vision(IN #4) · LangGraph 6노드(IN #5) · 두 RAG(IN #6) · 스트리밍 채팅(IN #7) · 일별 기록(IN #8) · 디스클레이머(IN #17).

### Journey 2 — 모바일 엔드유저 Edge Case (Self-RAG 재질문)

**Persona:** 같은 지수, 다른 식사. 회사 근처 새 카페에서 *"포케볼 ABC 시그니처"* 라는 특이 메뉴 주문.

**Opening.** *"이건 뭐가 들어 있는지도 모르겠는데 분석이 될까?"*

**Rising Action.** 사진 업로드 → OCR 결과 *"포케볼"* 항목으로 인식, 그러나 `retrieve_nutrition` 결과 top-3 매칭 신뢰도(`retrieval_confidence`)가 0.42로 임계값(0.6) 이하. `evaluate_retrieval_quality` 노드가 *재검색 분기* 로 진입. `rewrite_query` 노드가 *"포케볼 → 연어 포케 / 참치 포케 / 베지 포케"* 로 쿼리 분기 재작성 → 재검색 → 여전히 모호.

**Climax.** AI가 채팅으로 재질문한다. *"이게 어떤 포케볼인가요? (1) 연어 (2) 참치 (3) 채소 위주 — 양은 한 그릇(약 400g)인가요?"* (Self-RAG의 `needs_clarification = True` 분기). 지수가 *"참치 한 그릇"* 으로 응답. 재질문 1회로 매칭 성공.

**Resolution.** *"오, AI가 잘 못 알면 그냥 추측 안 하고 물어보네. 신뢰가 가."* 인용형 피드백 도착(KDRIs + 대한비만학회 매크로 권고). 데모 시나리오 #4의 핵심 모먼트 — *환각률을 낮추는 Self-RAG의 영업 카드*.

**Capability mapping:** Self-RAG 재검색(IN #5의 핵심 노드) · 음식 정규화 사전(IN #6 보강 AC) · `needs_clarification` 분기 UX · 권한 요청 흐름(암묵 IN).

### Journey 3 — 미기록 알림 → 빠른 진입 (푸시 nudge 흐름)

**Persona:** 지수, 평일 저녁 8시. 회사 회식으로 식단 입력 못함.

**Opening.** *"오늘 저녁 또 술자리. 입력 까먹겠네."*

**Rising Action.** 저녁 8시 30분, BalanceNote 푸시 알림 도착(Expo Notifications + cron + 알림 설정 ON). *"오늘 저녁 미기록 — 1분 안에 빠른 입력으로 일주일 일관성 유지하세요."* 탭. 모바일 식단 입력 화면 직행(딥링크).

**Climax.** 텍스트로 빠르게 입력 — *"삼겹살 1인분, 소주 2잔, 김치찌개"*. 사진 없어도 LangGraph가 텍스트 → `parse_meal` 노드로 항목 추출 → 매크로 분석. 인용형 피드백 도착.

**Resolution.** 일주일 기록 누락 0건. 주간 리포트(Journey 4)에서 *"한 주 일관성 유지"* 그래프 가시화.

**Capability mapping:** Expo 푸시 + cron(IN #9) · 알림 설정 ON/OFF(IN #19) · 텍스트 입력 CRUD(IN #3) · 딥링크 라우팅(AC) · 권한 요청 흐름(암묵 IN).

### Journey 4 — Web 사용자 주간 리포트 (행동 변화 인사이트)

**Persona:** 지수, 일요일 아침. *"한 주 어땠지? 다음 주 뭐 바꿔야 하지?"*

**Opening.** Next.js 사용자 화면 접속(Web, 반응형). Google 로그인.

**Rising Action.** 주간 리포트 화면 진입 → Recharts 기반 차트 4종: (1) 일별 매크로 비율 스택(탄/단/지), (2) 일별 칼로리 vs TDEE, (3) 단백질 g/kg 일별 추이(weight_loss 목표 1.2-1.6 권장 라인 표시), (4) 알레르기 항목(복숭아) 노출 횟수.

**Climax.** *"단백질 평균 55g/일 — 목표 80g 미달. 다음 주 매끼 단백질 +20g 시도해보세요."* 인사이트 카드(KDRIs + 대비학회 인용). *"매크로 비율 70/15/15 → 권장 50/25/25에서 거리가 큽니다."*

**Resolution.** 지수가 다음 주 *"매끼 단백질 25g"* 미니 챌린지 셋팅. 모바일 알림 룰에 자동 반영.

**Capability mapping:** Next.js 사용자 리포트 + Recharts(IN #10) · 일별 기록 조회(IN #8) · 알림 설정 룰 변경(IN #19) · OAuth 공통(IN #1).

### Journey 5 — 외주 발주자 영업 데모 (B2B 1차 사용자)

**Persona:** 박 CTO, 헬스케어 스타트업(DHP 액셀러레이터 포트폴리오). 사내 PoC 검증 4주 내 결정 압박.

**Opening.** BalanceNote 1인 개발자 hwan과 영업 미팅. *"AI 영양 솔루션 외주를 발주하고 싶은데, 우리 도메인에 4주 PoC 가능한가? 컴플라이언스도 처리되어야 해."*

**Rising Action.** hwan이 데모 영상 9포인트(체중 감량 페르소나) 시연 — 사진 입력 → Self-RAG 재질문 → 인용형 피드백 → 푸시 nudge → 주간 리포트 → 관리자 화면 → README/Swagger. 박 CTO가 즉석에서 *"우리 노트북에서 직접 돌려볼 수 있나?"* 요청. hwan이 GitHub 링크 전달, 박 CTO가 노트북에서 `git clone` → `docker compose up`. 8분 내 로컬 부팅 완료(Postgres + pgvector + Redis + FastAPI + 음식 DB seed).

**Climax.** 박 CTO가 LangGraph 6노드 코드 직접 열어본다. *"evaluate_fit 노드만 우리 알고리즘으로 갈아끼우면 4주 PoC 변형 가능하겠다. retrieval_confidence + rewrite_query 분기는 그대로 가져가도 되겠어."* README의 영업 답변 5종 closing(차별화/인허가/적용/8주 가능성/유지보수)를 5분 안에 훑고 *의료기기 미분류 SOP* + *PIPA 2026.03.15 동의서 템플릿* 까지 확인.

**Resolution.** *"좋아요. 외주 견적 보내주세요. 우리 도메인으로 변형해서 6주 안에 PoC 끝낼 수 있겠어."* 첫 외주 사이클 진입(Vision-stage 6개월 KPI #1 달성).

**Capability mapping:** Docker Compose 1-cmd(IN #13) · README/SOP(IN #13) · 데모 시나리오 9포인트(B2 KPI) · 의료기기 미분류 SOP(B4 KPI) · PIPA 동의서(B4 KPI) · 영업 답변 FAQ(B1 KPI) · LangGraph 모듈성(T1 KPI).

### Journey 6 — Admin / Operations (B2B Trust 카드)

**Persona:** 김 매니저, 병원 의료정보팀(외주 발주 후 시범 운영 단계). 사용자 문의 응대 + 데이터 거버넌스 책임.

**Opening.** 환자 보호자가 콜센터로 문의 — *"앱 분석 결과가 이상한 것 같아요. 누가 확인해줄 수 있나요?"*

**Rising Action.** 김 매니저 Next.js 관리자 화면 로그인(admin role + 활동 로그 자동 기록 시작). 사용자 검색(반응형 화면) → 해당 환자 식단 이력 조회. **시스템이 김 매니저의 조회 액션을 audit log에 기록**(IN #25): *"2026-04-26 14:23:11 / admin_id=km01 / action=user_meal_history_view / target_user_id=u_8329"*.

**Climax.** 김 매니저가 식단 이력에서 *"포케볼"* 항목 분석을 발견. 피드백 텍스트 확인 → 인용 출처(KDRIs + 대한비만학회) 정확. Sentry 대시보드 별도 확인 → 해당 시점 OCR Vision API 호출 로그 정상. **분석 자체는 정확하지만 환자가 매크로 비율을 의학적 진단으로 오해**한 것으로 추정.

**Resolution.** 김 매니저가 환자 보호자에게 회신 — *"분석은 KDRIs 권장 비율 기준 참고용입니다. 디스클레이머에 명시되어 있고 의학적 진단이 아닙니다. 식이 상담은 영양사 외래로 안내드립니다."* 1인 외주 개발자(hwan)에게는 *"디스클레이머 텍스트를 결과 화면 상단에 더 잘 보이게 강화 요청"* 피드백 전달. 활동 로그 통해 누가/언제/무엇을 봤는지 사후 추적 가능 — B2B 외주 신뢰 카드 작동.

**Capability mapping:** 관리자 로그인 + admin role(IN #21) · Web 관리자 화면 사용자 검색(IN #11) · 활동 로그 audit(IN #25) · Sentry(IN #13) · 디스클레이머(IN #17) · 의료기기 미분류 SOP(B4 KPI).

### Journey 7 — 외주 인수인계 후 클라이언트 개발자 (Support/Troubleshooting)

**Persona:** 이 개발자, 박 CTO 회사의 신규 합류 백엔드 개발자. 인수받은 BalanceNote 코드 변형 작업 시작.

**Opening.** *"내일 PoC 변형 시작. 일단 로컬 부팅부터."*

**Rising Action.** GitHub repo clone → README 첫 페이지 따라가기 → `.env.example` → `docker compose up` → seed 자동 적용 → Swagger UI에서 API 직접 호출 테스트. 6시간 내 로컬 환경 완비. *"오, README가 정말 깔끔하네. 외주받은 코드라기엔 너무 정리되어 있어."*

**Climax.** 자사 음식 DB(자사 케어푸드 SKU) 시드 추가 → `food_nutrition` jsonb 표준 키(`energy_kcal`, `carbohydrate_g`, …) 따라 변환 스크립트 작성 → `python scripts/seed_custom_foods.py` 실행 → 1시간 내 추천 결과에 자사 SKU 노출 확인. *"DB 표준이 식약처 키 그대로라 변환 코스트가 거의 없네."*

**Resolution.** 첫 PoC 변형 1주차 완료 보고. *"인수인계 가능성"* B3 KPI 검증 완료(README + Docker만으로 8시간 내 부팅 + 1일 내 자체 데이터 통합).

**Capability mapping:** Docker Compose(IN #13) · README/SOP(IN #13) · Swagger(IN #13) · 한국 표준 통합 데이터 모델(차별화 카드 #3) · pgvector seed 스크립트(W1-W2 작업 산출물).

---

### Journey Requirements Summary

7개 journey가 드러내는 시스템 요구역량을 정리:

| Capability 영역 | 등장 Journey | 관련 IN 항목 |
|----------------|-------------|-------------|
| **인증·온보딩** | J1, J4 | #1, #2, #16, #17, #24 |
| **모바일 식단 입력 (텍스트+사진)** | J1, J2, J3 | #3, #4, 권한 요청 AC |
| **LangGraph + Self-RAG 분석** | J1, J2 | #5, #6 |
| **인용형 스트리밍 피드백** | J1, J2 | #5, #7 |
| **푸시 nudge** | J3 | #9, #19 |
| **주간 리포트 + 행동 인사이트** | J4 | #10 |
| **Web 관리자 + 사용자 검색** | J6 | #11, #21 |
| **Audit log (admin 활동 추적)** | J6 | #25 |
| **운영 인수인계 (Docker/README/Swagger/SOP)** | J5, J7 | #13 |
| **컴플라이언스 (디스클레이머·SOP·PIPA)** | J5, J6 | #17, B4 KPI |
| **데이터 거버넌스 + Sentry** | J6 | #13 |
| **데이터 모델 표준 (식약처/KDRIs)** | J7 | #6, 차별화 #3 |
| **데이터 내보내기 (PIPA 권리)** | (별도 journey 없음 — 사용자 권리 행사 시점) | #23 |
| **결제/구독 sandbox** | (별도 journey 없음 — 외주 클라이언트별 어댑터) | #22 |
| **회원 탈퇴 + 로그아웃** | (별도 journey 없음 — 사용자 권리 행사 시점) | #14, #15 |

**관찰:** J1-J4는 B2C 엔드유저 가치 증명, J5-J7은 B2B 외주 가치 증명. **영업 포트폴리오로서 J5(영업 데모) + J7(인수인계 검증) 이 차별화 KPI(B1, B2, B3)** 의 직접 측정 경로다. J6은 *Trust 카드* 로 작동(audit log → 신뢰 추적성).

---

## Domain-Specific Requirements

도메인 복잡도 high (healthcare 웰니스 sub-track). 한국 헬스케어 도메인 특수성 — 식약처·복지부·PIPA·KDRIs 통합. 도메인 리서치 산출물의 1차 자료를 직접 인용한다.

### Compliance & Regulatory

#### C1. 의료기기 미분류 (웰니스 트랙) 명확화

- **포지션:** 식약처 *"의료기기와 개인용 건강관리(웰니스)제품 판단기준"* 의 **저위해도 일상 건강관리** 명시 예시(*"식사 소비량을 모니터·기록하고 체관리를 위한 식이 활동을 관리하고 과식 시 경고"*)에 정확히 일치 → 의료기기 인허가 트랙 회피.
- **회피 의무 표현:** 진단성 발언("당신은 당뇨가 의심됩니다" / "이 식단은 ◯◯을 예방합니다"), 처방·약물 권고, 환자 데이터 기반 의학적 판단 자동화. → `generate_feedback` 노드 시스템 프롬프트에 금지 패턴 + 안전 대안 워딩 매핑(아래 C5).
- **`fit_score` 명명·범위:** *"건강 목표 부합도 점수"* 로 표기. 100점이 의학적 정상이 아님을 UI 푸터에 명시 — *"현재 설정된 건강 목표에 가장 가까움"*.
- **운영 산출물:** 의료기기 미분류 입장 SOP(README/SOP 1장) — 외주 클라이언트가 인허가 자문 받을 때 1차 답변 자료.

#### C2. PIPA 2026.03.15 시행 — 자동화 의사결정 동의 의무

- **법적 사실:** 2026년 3월 15일 시행 PIPA 개정 — *"자동화된 의사결정 시 민감정보 처리 범위·처리 항목 구체적 공개 의무"*.
- **BalanceNote 적용:** LangGraph `evaluate_fit` + `generate_feedback`은 자동화 의사결정에 해당 가능 → 사용자 동의서에 처리 항목·범위 구체 공개 필수.
- **민감정보 별도 동의:** 건강정보(체중·신장·건강 목표·알레르기·식사 기록)는 PIPA 23조 민감정보 → **일반 개인정보 동의와 분리한 별도 동의** 필수(IN #16).
- **동의서 템플릿:** 처리 항목, 이용 목적, 보관 기간, 제3자 제공(없음), LLM API 호출 시 외부 처리(OpenAI/Anthropic) 명시, 자동화 의사결정 동의 — 5개 섹션 템플릿. 운영 SOP 산출물.
- **CPO(개인정보 책임자) 표기:** 1인 개발자 명의로 `Privacy Policy` 풋터 + 설정 화면에 명시.

#### C3. 표준 디스클레이머 텍스트 (한·영) — 노출 위치 강화

- **한국어 원문(IN #17 기반):**
  > 본 서비스는 일반 건강관리(웰니스) 목적의 정보 제공 서비스이며, 의료기기 또는 의학적 진단·치료·예방을 위한 도구가 아닙니다. 영양·식단 분석 및 피드백은 참고용이며, 질병의 진단·치료·예방 또는 의학적 조언을 대체하지 않습니다. 질병이 있거나 약물 복용 중, 임신·수유 중인 경우 반드시 의사 또는 영양사 등 전문가와 상의하시기 바랍니다. 알레르기·기저질환이 있는 사용자는 입력 정보가 누락되거나 부정확할 수 있음에 유의하시고, 응급상황 시에는 즉시 119에 연락하십시오.
- **영문 원문(글로벌 데모/B2B 답변용):**
  > This service is provided for general wellness and informational purposes only. It is NOT a medical device and is NOT INTENDED TO DIAGNOSE, TREAT, CURE, OR PREVENT ANY DISEASE.
- **노출 위치:**
  - 온보딩 첫 진입 후 약관 동의 화면(IN #16)에 풀텍스트 표시
  - 모든 분석 피드백 카드 푸터에 *"건강 목표 부합도 점수입니다 — 의학적 진단이 아닙니다"* 1줄
  - 설정 화면(IN #18) 진입 → 디스클레이머 보기 sub-entry
  - Web 약관/처리방침 페이지에 한·영 풀텍스트
- **핵심 경고(FDA Warning Letter 시사점):** 디스클레이머 텍스트 단독으로는 부족 — *실제 기능·디자인이 의료 목적이 아님을 입증* 해야 함. 그래서 `fit_score` 명명, UI 푸터 노출 위치, 진단성 표현 가드(C5) 모두 동시 적용.

#### C4. 식약처 식품 표시 22종 알레르기 도메인 무결성

- `users.allergies text[]` 필드 도메인을 식약처 *"식품 등의 표시기준 별표"* 22종으로 제한(research 2.4):
  ```
  ['우유', '메밀', '땅콩', '대두', '밀', '고등어', '게', '새우', '돼지고기', '아황산류',
   '복숭아', '토마토', '호두', '닭고기', '난류(가금류)', '쇠고기', '오징어',
   '조개류(굴/전복/홍합 포함)', '잣', '아몬드', '잔류 우유 단백', '기타']
  ```
- **운영 룰:** W1 시드 시점에 [국가법령정보센터 별표 PDF](https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201) 최신본 5분 검증 후 코드 enum 갱신. 표시기준 갱신 시 OUT-of-band 추적.
- **fit_score 0점 트리거:** `evaluate_fit` 노드에서 알레르기 항목과 식사 매칭 발견 시 즉시 score=0, reason="allergen_violation" — 매크로/칼로리 점수 무시.

#### C5. 식약처 광고/표시 금지 표현 가드레일

- LangGraph `generate_feedback` 노드 시스템 프롬프트에 금지 패턴 + 안전 대안 매핑 주입(research 3.5):

| 회피 표현 | 안전 대안 |
|----------|----------|
| "당뇨가 예방됩니다" | "혈당 관리에 도움이 될 수 있는 식습관입니다 (참고용)" |
| "이 식단은 암을 막아줍니다" | "균형 잡힌 식단은 일반적인 건강 유지에 기여합니다" |
| "관절 통증 완화" | (질병 완화 표현 금지 — 발견 시 안전 워딩으로 치환) |
| "치료" / "처방" / "진단" | "관리" / "안내" / "참고" |

- **출력 가드 흐름:** 생성 텍스트 → 정규식 패턴 매칭 → 위반 발견 시 LLM 재생성 1회 또는 안전 워딩 자동 치환. T10 통과 기준에 매핑.

#### C6. 데이터 보존·파기 정책

- **사용자 데이터 보존:** 회원 탈퇴 시(IN #15) 즉시 삭제. 단 법정 보존 의무 항목(약관 동의 시점·결제 영수증)은 PIPA 외 관련법 보존 기간 준수 후 파기.
- **LLM 호출 로그:** Sentry/구조화 로그에는 사용자 식별자 마스킹(`u_xxxx` 형태). LLM API 호출 페이로드는 30일 보존 후 자동 파기.
- **백업 정책:** Postgres 일별 백업 7일 보존(Railway 표준).

### Technical Constraints

#### TC1. 보안

- **JWT 토큰:** httpOnly + Secure 쿠키. 만료 30일 + refresh 90일.
- **HTTPS only:** Vercel/Railway 표준 TLS. HSTS 헤더 적용.
- **API rate limit:** 사용자별 1분 60건, 1시간 1,000건. Redis 기반 슬라이딩 윈도우.
- **민감정보 마스킹:** 로그 출력 시 이메일·체중 등 민감정보 마스킹 처리.
- **Admin role 분리(IN #21):** 일반 사용자 JWT와 admin JWT 토큰 분리. admin 작업 시 audit log(IN #25) 자동 기록.

#### TC2. 개인정보 보호

- **암호화:** Postgres 컬럼 단위(체중·신장·알레르기) at-rest 암호화 — Railway 표준 디스크 암호화 + 추가 컬럼 암호화는 Growth 단계 검토.
- **민감정보 로그 금지:** 식단 raw_text·체중·알레르기는 로그·Sentry breadcrumbs 송신 금지. Sentry beforeSend hook으로 필터링.
- **PIPA 자동화 의사결정 동의 미수신 사용자:** `evaluate_fit`/`generate_feedback` 호출 차단 → 안내 화면 노출.

#### TC3. 성능 목표

- **모바일 식단 입력 → 피드백 도착 종단 지연:** p50 ≤ 4초, p95 ≤ 8초 (사진 OCR 포함).
- **스트리밍 첫 토큰 도착(TTFT):** ≤ 1.5초.
- **LangGraph 6노드 단일 호출 평균:** ≤ 3초 (Self-RAG 재검색 시 +2초).
- **음식 RAG 검색 응답:** ≤ 200ms (Redis 캐시 hit 시 ≤ 30ms).
- **Web 주간 리포트 로딩(데이터 7일치):** ≤ 1.5초.

#### TC4. 가용성·내결함성

- **목표 가용성:** Vercel + Railway 의존 — SLA는 Railway 기준 99.9%(공식). 별도 multi-AZ 구성 X(1인 anti-pattern).
- **외부 API 장애 fallback:** OpenAI 호출 실패 → Claude로 전환 시도(LLM 보조 라인). Claude 도 실패 시 *"AI 서비스 일시 장애, 잠시 후 다시 시도해주세요"* 안내 + Sentry 알림.
- **Structured Output 파싱 실패:** Pydantic 검증 실패 시 retry 1회 → 실패 시 error edge fallback("이번 식사는 분석에 시간이 더 걸립니다, 텍스트로 다시 입력해주세요").
- **DB 장애:** Railway Postgres 다운 시 readonly 캐시(Redis)에서 사용자 자기 기록 조회만 허용 + 입력은 큐잉 — Growth 단계 검토. MVP는 503 안내.

### Integration Requirements

#### I1. 외부 데이터 소스 (RAG 시드)

| 소스 | 형태 | 통합 방식 | 갱신 주기 |
|------|------|----------|----------|
| **식약처 식품영양성분 DB** | 공공데이터 OpenAPI | W1 시드 스크립트 — 1,500-3,000건 한식 우선 추출 | 분기 1회 수동 갱신 |
| **식약처 식품영양 통합 자료집** | 다운로드 ZIP (data.go.kr 15047698) | 백업 시드 (OpenAPI 장애 대비) | 식약처 발표 시 |
| **보건복지부 KDRIs 2020** | PDF (활용자료) | 수동 chunking 50-100 chunks → pgvector 시드 | 신규 KDRIs 발표 시 (2025+) |
| **대한비만학회 진료지침 9판** | PDF (KSSO 일반인 페이지) | 수동 chunking → pgvector 시드 | 학회 갱신 시 |
| **대한당뇨병학회 매크로 권고** | PDF (Synapse) | 수동 chunking → pgvector 시드 | 학회 갱신 시 |
| **질병관리청 국가건강정보포털** | HTML (당뇨 식이요법 등) | 텍스트 추출 → pgvector 시드 | 정부 갱신 시 |

#### I2. 외부 LLM·OCR API

- **OpenAI GPT-4o-mini** (메인 LLM) — `parse_meal`, `evaluate_retrieval_quality`, `rewrite_query`, `generate_feedback` 노드.
- **Anthropic Claude** (보조 LLM) — `evaluate_fit` 노드(추론 품질, "두 모델 비교" 영업 무기 + OpenAI 장애 시 fallback).
- **OpenAI Vision API** (OCR) — 사진 입력의 음식 항목 추출.
- **API 키 관리:** Railway 환경 변수 + 로컬 `.env` (gitignore). 클라이언트별 인수인계 시 README의 API key 가이드 따라 자체 발급.

#### I3. 외주 인수인계 인터페이스

- **Docker Compose 1-cmd:** Postgres+pgvector+Redis+FastAPI+seed 스크립트 일괄 부팅. README에 환경 변수 설명.
- **Swagger/OpenAPI:** 모든 API endpoint + 요청/응답 스키마 + 에러 코드. `/docs` 경로 노출.
- **README 5섹션 표준:** (1) Quick start (Docker Compose), (2) Architecture overview (LangGraph 6노드 다이어그램), (3) 데이터 모델 (식약처 표준 키), (4) 영업 답변 5종 closing FAQ, (5) AWS/GCP/Azure 마이그레이션 가이드 + 결제 PG 연동 확장 가이드.
- **SOP 문서:** 의료기기 미분류 입장 / PIPA 동의서 템플릿 / 디스클레이머 한·영 / 식약처 광고 금지 표현 가드 — 4종.

#### I4. 결제 sandbox (IN #22)

- **선택 PG:** Toss Payments(한국 우선) 또는 Stripe(글로벌 영업 대응). README에 둘 다 가이드.
- **통합 범위(MVP):** 정기결제 1플랜 sandbox · 결제 성공 webhook · 영수증 조회 API · 구독 해지 API.
- **OUT(통합 범위 외):** 사업자등록·PG 본 계약·세금정산·환불 자동화 — 인수받은 클라이언트가 자체 구축. README에 *"PG 본 계약·세금처리 가이드"* 만 1페이지.

### Risk Mitigations

| # | 리스크 | 영향 | 사전 대응 | 후속 모니터링 |
|---|--------|------|----------|-------------|
| R1 | 음식명 RAG 매칭 부정확("짜장면"≠"자장면", "김치찌개"≠"김치 찌개") | 데모 망함, 영업 신뢰 ↓ | 음식명 정규화 사전(NFKD + 공백/오타 표준화) 1차 매칭 → 임베딩 fallback → top-3 LLM 재선택 | T3 KPI(한식 100건 ≥ 90%) 회귀 테스트 W2 + W7 |
| R2 | RN 스트리밍 SSE 까다로움 (iOS Safari 호환) | W4 일정 밀림 | W4 day1 spike(react-native-sse 또는 fetch streaming) → polling fallback 준비 | T5 KPI(5분 50회 끊김 ≤ 1) 회귀 |
| R3 | Structured Output JSON 파싱 실패 (LLM hallucination) | LangGraph 노드 멈춤 | Pydantic 검증 + retry 1회 + error edge fallback. 노드별 isolation. | Sentry 자동 수집 + W3 단위 테스트 |
| R4 | 영양 DB 가공 시간 초과 | W1 일정 밀림 | W1 day1 spike, OpenAPI fallback → 통합 자료집 ZIP fallback → USDA FoodData Central 백업 | W2 종료 시 1,500건 ≥ 확보 검증 |
| R5 | 로컬↔클라우드 환경 차이 (W7 배포 시) | 배포 일정 밀림 | W1부터 Docker 개발(로컬=컨테이너) — 환경 동질성 보장 | W7 1일차 dry-run 배포 |
| R6 | LLM API 비용 폭증 (개발 중) | 예산 초과 | Redis 캐시 + GPT-4o-mini 메인(저비용) + Claude 보조만 호출 + 일일 사용량 모니터링 | Sentry + 일별 API 비용 알림 |
| R7 | 식약처 OpenAPI 장애 / quota 초과 | W1-W2 작업 중단 | 통합 자료집 ZIP 다운로드 백업 + USDA FoodData Central 영문 fallback | W1 day1 두 경로 모두 동작 검증 |
| R8 | 식약처 표시기준 22종 갱신 | 알레르기 도메인 무결성 깨짐 | W1 시드 시점 [국가법령 별표](https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201) 5분 재검증. enum 갱신 SOP 문서화 | 분기 1회 모니터링 (운영 SOP) |
| R9 | PIPA 시행령 추가 갱신 (2026.03.15 이후) | 동의서 템플릿 노후화 | research 2.5에서 인용한 [법제처 시행령 입법예고](https://www.moleg.go.kr/lawinfo/makingInfo.mo?lawSeq=81114&lawCd=0&lawType=TYPE5&mid=a10104010000) 추적 | 분기 1회 모니터링 |
| R10 | 외주 클라이언트가 진단성 발언 요구 | 컴플라이언스 위반 | C1·C5 명문화된 가드를 영업 답변에서 사전 차단(*"이 영역은 의료기기 인허가 트랙으로 분리됩니다"*) | SOP 영업 답변 5종 closing 중 #2 항목 |

---

## Innovation & Novel Patterns

본 산출물의 혁신은 *연구 수준의 신기술* 이 아니라 **"학술 RAG 기법(Self-RAG) + 한국 1차 출처 도메인 + 외주 인수인계 패키징"의 결합**에 있다. 정직하게 말해 LangGraph·OCR·pgvector·OAuth 등 개별 컴포넌트는 표준 기술이다. 혁신은 *결합 패턴* 과 *시장 빈자리에 대한 정밀한 응답* 에 있다.

### Detected Innovation Areas

#### IA1. Self-RAG의 한국 음식 도메인 적용 (학술 → 상용 적용 혁신)

- **학술 출처:** Asai et al., *"Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection"* (2023). 검색 결과의 *retrieval_confidence* 를 평가해 신뢰도 낮을 때 쿼리 재작성·재검색·재평가하는 패턴.
- **BalanceNote의 적용:** LangGraph 6노드 안에 `evaluate_retrieval_quality` 분기 + `rewrite_query` 분기 + 1회 재검색 한도. 한국식 음식명("짜장면" vs "자장면", "김치찌개" vs "김치 찌개") 매칭 부정확이 발견되면 자동 재시도.
- **왜 혁신인가:** 글로벌 영양 앱 중 Self-RAG를 명시적 노드로 구현한 상용 사례 부재(2026.04 시점 검색 기준). Noom·MyFitnessPal·Cronometer 모두 단순 검색 기반.
- **검증 방법:** T2 KPI(`retrieval_confidence < threshold` 케이스 ≥ 5건 재검색 정상 동작) + T3 KPI(한식 100건 매칭 ≥ 90%) 회귀 테스트. 매핑 사전 + 임베딩 + LLM 재선택 3단 fallback의 정확도 기여 분리 측정.
- **Fallback:** 재검색 1회로도 신뢰도 미달 시 사용자에게 명시적 *"이게 ◯◯이 맞나요?"* 재질문 (Journey 2). 환각보다 *모름을 인정하는* 패턴 — 영업 답변에서 *책임 추적성* 카드로 작동.

#### IA2. 인용형 LLM 피드백 + Citation-bound Generation (한국 1차 출처)

- **혁신 핵심:** `generate_feedback` 시스템 프롬프트가 *"권고 텍스트 옆에 (출처: 기관명, 문서명, 연도) 패턴을 반드시 포함"* 으로 강제. 출력 가드(C5)와 결합하여 인용 형식 ≥ 99%(T4 KPI).
- **무엇이 다른가:**
  - 글로벌 앱: 자체 큐레이션된 일반 권고 ("단백질을 더 드세요")
  - BalanceNote: 한국 1차 출처에 매핑된 권고 ("탄수화물 비중이 권장 범위 55-65%를 초과 — 출처: 보건복지부 2020 KDRIs")
- **시장 빈자리 정합:** 한국 병원·보험사·식품사·식약처 컴플라이언스 통과를 위해서는 *책임 추적 가능한 권고* 가 필수. 이게 IA2의 영업 가치(차별화 카드 #1).
- **검증 방법:** 100건 샘플의 모든 권고 텍스트에 출처 패턴 포함 검증(T4 KPI). 출처 부재 시 안전 워딩 자동 치환(C5).
- **Fallback:** LLM이 인용을 생략하는 경우 후처리 정규식 검증 → 재생성 1회 → 실패 시 *"권고 출처 검증 필요"* 안내 워딩.

#### IA3. 듀얼-LLM 아키텍처 (OpenAI + Claude) — 영업 무기로서의 결합

- **혁신적 결합:** OpenAI GPT-4o-mini를 메인 라인(parse_meal·rewrite·generate_feedback)에, Anthropic Claude를 보조 라인(`evaluate_fit` 추론)에 배치. 단일 LLM 의존을 회피하면서 *추론·생성 모델 분업* 실험.
- **왜 이게 혁신 모멘트인가:** 외주 영업에서 *"왜 OpenAI만 쓰지 않고 Claude도 쓰느냐"* 라는 자연 질문이 생긴다. 답: (a) 추론 품질 비교 검증, (b) 하나 장애 시 fallback, (c) 두 벤더 이해도를 외주 능력으로 입증. 단일 LLM 통합 솔루션과 차별화.
- **검증 방법:** `evaluate_fit` 노드의 응답 50건 비교 — Claude vs GPT-4o-mini의 fit_reason 텍스트 품질·일관성 정성 평가 + 응답 시간/비용 정량 비교. README의 *"두 LLM 비교 결과"* 1페이지 문서화 → 영업 답변 자료.
- **Fallback:** 한쪽 장애 시 다른 쪽으로 자동 전환(TC4).

#### IA4. 외주 인수인계 가능한 도메인 RAG 패키지 (시장 혁신)

- **혁신 카테고리:** 기술 혁신이 아닌 **시장·딜리버리 혁신**. 1인 외주 개발자의 산출물이 학습용 토이가 아닌 *Docker 1-cmd 부팅 + 한국 표준 통합 데이터 모델 + SOP 4종(의료기기 미분류·PIPA 동의·디스클레이머·식약처 광고 가드) + 영업 답변 5종 closing FAQ + 데모 영상 5종(고객사 페르소나별)* 으로 패키징됨.
- **왜 혁신인가(시장 관점):** 한국 헬스테크 외주 시장에서 *"도메인 정합성 + 운영 인수인계 + 컴플라이언스"* 를 1식으로 묶은 1인 외주 산출물 표준이 부재. BalanceNote가 그 표준의 첫 인스턴스를 제공.
- **검증 방법:** B3 KPI(외주 클라이언트 개발팀이 README + Docker로 1일 내 부팅) + Journey 7(클라이언트 신규 개발자 8시간 내 부팅 + 1시간 내 자체 데이터 통합) 라이브 검증.
- **Vision-stage 확장:** *"한국 헬스테크 RAG 외주 라인업"* 표준 모듈(가이드라인 RAG 시드 키트 + LangGraph 6노드 템플릿 + Docker 인수인계 패키지) — 1-2년 vision.

### Market Context & Competitive Landscape

도메인 리서치 4.1 비교 매트릭스 기반 분석.

| 비교 차원 | Noom | MyFitnessPal | Yazio | Cronometer | **BalanceNote (목표)** |
|----------|------|-------------|-------|-----------|---------------------|
| 음식 DB 출처 | 자체 큐레이션 + 신호등 | 크라우드소싱 (정확도 편차) | 자체 큐레이션 | NCCDB + USDA | **식약처 식품영양성분 DB (1차 공인)** |
| 검색 재시도 | 단순 검색 | 단순 검색 | 단순 검색 | 단순 검색 | **Self-RAG 재검색 노드** |
| 권고 인용 | 일반 권고 | 일반 권고 | 일반 권고 | 데이터 dump | **한국 1차 출처 인용 (KDRIs/대비학회/대당학회)** |
| 한국 컴플라이언스 | 약함 (글로벌 위주) | 약함 | 약함 | 약함 | **식약처/PIPA 정합 표준 통합 데이터 모델** |
| LLM 아키텍처 | (제한적) | (제한적) | (제한적) | (제한적) | **듀얼-LLM (OpenAI 메인 + Claude 보조)** |
| 외주 인수인계 | (B2C only) | (B2C only) | (B2C only) | (B2C only) | **Docker 1-cmd + SOP 4종 + 영업 답변 FAQ** |

**시장 빈자리 요약:** 글로벌 앱은 한국 1차 출처 책임 추적이 약하고(병원·보험사·식품사 컴플라이언스 ↓), 한국 자체 솔루션은 자체 LLM/RAG 인프라 구축 비용 부담이 크다. *BalanceNote = "한국 1차 출처 RAG + 글로벌 LLM API 효율 + 외주 인수인계"의 교집합* 이 시장 빈자리 정합 포지션.

### Validation Approach

| Innovation Area | 핵심 검증 KPI | 측정 방법 | 통과 기준 |
|----------------|-------------|---------|---------|
| IA1 Self-RAG | T2 (재검색 동작), T3 (한식 100건 매칭 정확도) | 통합 테스트 + 회귀 테스트 W2/W7 | 재검색 분기 ≥ 5건 동작 / 정확도 ≥ 90% |
| IA2 인용형 피드백 | T4 (인용 형식 100%) | 100건 샘플 정규식 + 안전 워딩 가드 | 인용 누락 < 1% |
| IA3 듀얼-LLM | (정성) 영업 자료 1페이지 + (정량) 응답 시간/비용 | 50건 비교 측정 + README 문서화 | 영업 미팅에서 자연 질문 답변 가능 |
| IA4 외주 인수인계 | B3 (1일 내 부팅) + Journey 7 라이브 검증 | 외부 개발자 1명 검증(가능 시) | 8시간 내 부팅 + 1일 내 자체 데이터 통합 |

### Risk Mitigation (Innovation-specific)

| Risk | 영향 | Mitigation |
|------|------|----------|
| Self-RAG 재검색이 무한 루프 / 비용 폭증 | 운영 비용 ↑, T1 안정성 ↓ | 재검색 한도 1회 강제 + Redis 캐시 + 일별 비용 알림(R6) |
| 인용 출처가 LLM 환각 (가짜 출처) | 컴플라이언스 ↓, 영업 신뢰 ↓ | 가이드라인 RAG retrieve 결과의 source 메타데이터를 시스템 프롬프트에 명시 주입(자유 인용 금지) + 후처리 검증 |
| 듀얼-LLM 응답 불일치 (`evaluate_fit` Claude vs GPT 결과 충돌) | UX 혼란 | 단일 LLM이 최종 결정, 다른 LLM은 비교용 — 충돌 시 메인 라인(GPT-4o-mini) 결과 사용 |
| Self-RAG가 자연어 사용자 메시지에 잘못 트리거 | 혼란 | `retrieval_confidence` 임계값 튜닝 (W2 spike) — 0.6 기본, 데이터 기반 조정 |
| "Self-RAG"라는 학술 용어가 영업 자리에서 과기술적 인상 | 영업 진입 장벽 | 영업 답변에서 *"AI가 잘 모르겠으면 다시 묻습니다"* 같은 자연어 표현으로 번역. README 첨부 |

---

## Project-Type Specific Requirements

본 산출물은 멀티 컴포넌트 풀스택이지만 *주축은 mobile_app(RN)*. 사용자 핵심 가치 흐름(식단 입력 → 스트리밍 피드백 → 일별 기록)이 모바일에서 일어나므로 mobile_app 요구사항을 1순위로 명세하고, 동반 컴포넌트(web_app + api_backend)를 보조 명세로 다룬다.

### Project-Type Overview

| 컴포넌트 | 역할 | 기술 스택 | 핵심 사용자 |
|---------|------|---------|-----------|
| **mobile_app (주축)** | 식단 입력 / 스트리밍 채팅 피드백 / 일별 기록 / 알림 / 설정 | React Native + Expo + react-native-sse | B2C 엔드유저 페르소나(4종) |
| **web_app (보조)** | 사용자 주간 리포트 + 관리자 화면 (반응형) | Next.js + Recharts | 사용자(주간 인사이트) + 관리자(B2B trust) |
| **api_backend (보조)** | LangGraph 6노드 + RAG + CRUD + 결제 + Audit | FastAPI + LangGraph + Postgres + pgvector + Redis | 양쪽 클라이언트 |

### Mobile App — Platform Requirements (주축)

#### M1. Native vs Cross-Platform

- **선택:** **React Native (Expo managed workflow)** — 1인 개발자가 iOS/Android 동시 커버.
- **이유:** (1) 1인 8주 일정에 native 듀얼 스택은 anti-pattern, (2) Expo Notifications가 RN 표준이라 IN #9 푸시 통합이 단순화, (3) 외주 클라이언트가 인수받을 때 RN 경험 개발자가 더 흔함.
- **Bare Workflow 회피:** Expo managed에서 충분 — eject 필요 시 Growth 단계에서.

#### M2. iOS / Android 최소 버전 + 디바이스

- **iOS 14+ / Android 8.0(API 26)+** — Expo SDK 51 기준 표준. 한국 사용자 99% 커버.
- **타겟 폼팩터:** 스마트폰 우선(태블릿 별도 최적화 X). 가로모드 OFF(영양 입력은 세로모드만).
- **Offline 미지원 시 정책:** 기본 온라인 의존(LangGraph + RAG는 서버 호출 필수). 단순 식단 텍스트 입력은 오프라인 큐잉 후 sync(M3 참조).

#### M3. Offline Mode (제한적)

- **MVP 범위:**
  - 오프라인 입력 큐잉: 텍스트 식단 입력은 로컬 큐(AsyncStorage)에 저장 → 온라인 복귀 시 자동 sync. 사진 입력은 온라인 필수(OCR 서버 호출).
  - 일별 기록 화면: 마지막 7일 데이터를 로컬 캐시(읽기 전용 표시).
  - LangGraph 분석 / 스트리밍 피드백 / 푸시: 온라인 필수.
- **Out of MVP:** 풀 오프라인 모드, 오프라인 분석(자체 모델), peer-to-peer sync — Growth.

#### M4. Push Notifications

- **공급자:** **Expo Notifications** (IN #9) — Expo Application Services(EAS) 기반.
- **전송 트리거:**
  - 미기록 nudge: 설정된 알림 시간(기본 저녁 8시) 후 30분 경과 + 당일 식단 미입력 시 자동 전송 (서버 cron).
  - (Growth) 주간 리포트 도착 알림 / 알레르기 위반 즉시 경고.
- **권한 흐름(IN #9 + 권한 요청 AC):** 첫 진입 시 권한 요청 → 거부 시 *"설정에서 알림 허용 시 미기록 nudge가 동작합니다"* 안내 + 설정 deep link. 알림 설정(IN #19)에서 사용자가 ON/OFF 토글 가능.
- **Out of MVP:** Rich notification(이미지·액션 버튼), iOS Critical Alert, 알림 카테고리 분기 — Growth.

#### M5. Device Permissions (UIUX 가시 권한 요청 흐름)

| 권한 | 용도 | 요청 시점 | 거부 시 처리 |
|------|------|----------|-----------|
| **카메라** | 식단 사진 촬영 (IN #3) | 첫 사진 입력 시도 시 | "갤러리 선택" fallback + 설정 가이드 안내 |
| **사진첩(미디어 라이브러리)** | 갤러리에서 식단 사진 선택 (IN #3) | 첫 갤러리 열기 시 | "카메라 촬영" fallback 또는 텍스트 입력 안내 |
| **알림 (Push)** | 미기록 nudge (IN #9) | 온보딩 종료 직후 또는 첫 미기록 후 | 알림 OFF 표시 + 설정 deep link 안내 |

- 모든 권한은 **거부 시 안내 화면 → 설정 deep link** 표준 흐름. 권한 거부 후 빈 화면 노출 금지(서비스 완성도).

#### M6. Store Compliance

- **Apple App Store:**
  - 헬스 데이터 수집 명시: HealthKit 직접 통합 안 함(MVP) — 자체 입력만. App Privacy 항목 정확 신고.
  - 디스클레이머 화면을 첫 진입 즉시 노출 → App Review의 *"의료적 주장이 없는 웰니스 앱"* 검증 통과.
  - In-App Purchase: 결제는 IAP 우회(외부 결제 화면 sandbox) — App Review 정책 준수 위해 *"앱 외부에서 구독 가능"* 화면만 노출하는 패턴 또는 IAP 통합(클라이언트별 결정). MVP는 외부 웹 결제만 우선.
- **Google Play:**
  - 민감 권한 정당화 명시(카메라·사진첩·알림).
  - 데이터 안전성(Data Safety) 양식: 건강 데이터 수집 + 자동화 의사결정 + 제3자 처리(LLM API) 명시.
  - 디스클레이머 정책 정합 — 의료기기 미분류 명확.
- **개발자 계정:** 1인 개발자 계정으로 신청 (Apple $99/년, Google $25 1회). 인수 시 클라이언트 계정 이전 SOP 문서화.

### Web App — Component Requirements (보조)

#### W1. SPA / 반응형

- **Next.js App Router** 기반. 사용자 주간 리포트(`/dashboard/weekly`) + 관리자(`/admin`) 두 영역.
- **반응형:** 모바일 폭(360px)부터 데스크톱(1440px+) 대응. 관리자 화면은 데스크톱 우선이지만 반응형 보장(영업 시연 환경 다양화).
- **인증:** 모바일과 동일 Google OAuth + JWT. 관리자는 별도 admin role 토큰(IN #21).

#### W2. 차트·시각화

- **Recharts** (IN #10) — 4종 차트(매크로 비율 스택 / 칼로리 vs TDEE / 단백질 g/kg / 알레르기 노출). SSR로 초기 로딩 ≤ 1.5초(TC3).

#### W3. 관리자 활동 로그 UI

- 관리자 모든 액션(사용자 검색·조회·수정)을 audit log(IN #25)에 기록. 관리자 화면 자체에 *"내 활동 로그"* 패널 표시 — 자기 감사 가능.

### API Backend — Component Requirements (보조)

#### A1. FastAPI 엔드포인트 그룹

- **Auth:** `/auth/google` (OAuth callback), `/auth/refresh`, `/auth/logout` (IN #14)
- **Profile:** `/users/me` (GET/PATCH — 프로필 조회/수정 IN #20), `/users/me` (DELETE — 회원 탈퇴 IN #15), `/users/me/export` (PIPA 데이터 내보내기 IN #23)
- **Meals:** `/meals` (POST/GET/PATCH/DELETE — 식단 CRUD IN #3), `/meals/{id}/image` (사진 업로드 → R2)
- **Analysis:** `/analysis/stream` (LangGraph 6노드 호출 + SSE 스트리밍 IN #5, #7)
- **Reports:** `/reports/weekly` (주간 리포트 데이터 IN #10)
- **Admin:** `/admin/users` (검색 IN #11), `/admin/audit-logs` (IN #25). 모두 admin role(IN #21) 필요.
- **Payment:** `/payments/subscribe`, `/payments/cancel`, `/payments/webhook` (IN #22)
- **Notification settings:** `/notifications/settings` (IN #19)
- **Compliance:** `/legal/disclaimer`, `/legal/privacy-policy`, `/legal/terms` (한·영 텍스트)

#### A2. 인증 모델

- **JWT access (만료 30일) + refresh (만료 90일)**. httpOnly Secure 쿠키 (Web) + Authorization Bearer 헤더 (모바일).
- **Admin role:** JWT claim에 `role: admin` 분리. 인덱스된 admin role 테이블로 권한 매핑.

#### A3. Rate Limit + 캐시

- **Rate limit:** 사용자별 분당 60 / 시간당 1,000 (Redis 슬라이딩 윈도우). LangGraph 호출은 비용 보호상 분당 10건.
- **Redis 캐시(IN #12):** LLM 동일 입력 응답 캐시(키: hash(meal_text + user_profile_hash)). 음식 검색 결과 캐시(키: 정규화된 음식명).

#### A4. Swagger / OpenAPI

- FastAPI 자동 생성 + 수동 보강(요청/응답 예시, 에러 코드 명세). `/docs` 노출 — 외주 인수인계 핵심 산출물(IN #13).

### Implementation Considerations

#### 빌드 / 배포

- **모바일:** Expo EAS Build → iOS TestFlight + Google Play Internal Testing → 데모 영상 시연용 ad-hoc 배포 + 외주 클라이언트 단계에서 정식 스토어 등록.
- **Web:** Vercel 자동 배포(GitHub 연동). PR 단위 preview URL.
- **Backend:** Railway 자동 배포(GitHub 연동). PR 단위 preview environment(가능 시).
- **Docker Compose:** 로컬 개발 + 외주 인수인계 표준 — `docker compose up`만으로 Postgres+pgvector+Redis+FastAPI+seed 일괄 부팅(W1부터 컨테이너=로컬 환경 동질성).

#### 환경 분리

- **dev (로컬):** Docker Compose. seed 데이터 사용. LLM API는 OpenAI/Anthropic 개발 키.
- **staging (Railway):** PR 검증용. seed 동일 + 실제 OpenAI/Anthropic 키.
- **prod (Railway + Vercel + R2):** 외주 인수인계 후 클라이언트가 자체 운영.

#### 데이터 모델 표준 (외주 인수인계 가치)

- 식약처 영양 성분 키 표준(`food_nutrition.nutrition` jsonb) 그대로 외부 노출.
- KDRIs AMDR + 대비/대당학회 매크로 룰을 `health_goal` enum별 상수 테이블로 분리 — 외주 클라이언트가 자기 도메인 룰로 갈아끼우기 쉽도록.
- 알레르기 22종 상수를 enum 또는 lookup table로 — 표시기준 갱신 시 enum만 갱신.

#### Skip된 영역 (의도적 OUT)

- `desktop_features` — 데스크톱 native 앱 OUT.
- `cli_commands` — CLI 인터페이스 OUT(개발 운영 스크립트는 별도, 사용자 노출 X).
- 풀 offline 모드 / 자체 LLM / Fine-tuning / 풀 논문 RAG / DTx 인허가 / MSA / Kafka — 기존 OUT 리스트 참조.

---

## Project Scoping & Phased Development

브레인스토밍 산출물의 **8주 W1-W8 phased delivery** 를 사용자 명시 phasing으로 채택. MVP는 단일 8주 사이클 안에서 25개 IN 항목 모두를 완료한다. Growth/Vision은 외주 첫 사이클 이후 별도 trajectory(이미 step-03 Product Scope에 정의).

### MVP Strategy & Philosophy

**MVP Approach:** **Demo-Ready Reference Implementation MVP** — 사용자 활성화가 아닌 *영업 통과 가능성* 을 검증하는 MVP. 9포인트 데모 시나리오 라이브 동작 + 외주 클라이언트 1일 내 부팅 + 컴플라이언스 안전판 명문화가 1차 유효성 검증.

**왜 이 MVP 전략인가:**
- **문제 검증형 MVP가 아닌 이유:** 사용자 페인은 이미 도메인 리서치 + brief에서 검증됨(시장 규모 6.5조, 5개 고객사 발주 사례 누적)
- **수익 검증형 MVP가 아닌 이유:** 본 산출물 자체는 수익원이 아닌 영업 자산
- **체험형 MVP인 이유:** 외주 발주자가 *데모 + 코드 + 문서* 3축으로 1인 개발자 능력을 즉시 평가 가능해야 함

**Resource Requirements:**
- **인력:** 1인 풀스택 개발자(hwan)
- **기간:** 8주 (W1-W8)
- **예산 (외부 비용):** Vercel 무료 + Railway $5-20/월 + Cloudflare R2 무료 티어 + OpenAI/Anthropic API ~$50-100 (개발 중) + Apple Developer $99/년 + Google Play $25 1회 + 도메인 + 데모 영상 제작
- **외부 의존:** OpenAI · Anthropic · Toss Payments(또는 Stripe) sandbox · 식약처 OpenAPI · 한국 영양 가이드라인 PDF 수동 chunking

### MVP Feature Set (Phase 1 — 단일 8주 사이클)

**Core User Journeys Supported (모든 7개 journey가 MVP 범위):**
- J1 모바일 happy path (사진 입력 → Self-RAG 분석 → 인용 피드백 → 일별 기록)
- J2 모바일 edge case (Self-RAG 재질문)
- J3 미기록 → 푸시 nudge → 빠른 진입
- J4 Web 주간 리포트 (행동 인사이트)
- J5 외주 발주자 영업 데모 (B2B 1차)
- J6 Admin / 관리자 audit log (B2B trust)
- J7 외주 인수인계 후 클라이언트 개발자 (Support)

**Must-Have Capabilities — IN 25 (전부 MVP):**

`Auth/Account/Privacy` (#1, #2, #14, #15, #16, #17, #18, #20, #23) · `핵심 가치 흐름` (#3, #4, #5, #6, #7, #8) · `알림` (#9, #19) · `웹/관리자` (#10, #11, #21, #25) · `인프라/운영` (#12, #13) · `결제` (#22) · `온보딩` (#24)

OUT 9항목은 step-03/02b의 `out_with_valid_reasons` 그대로(redundant 또는 anti-pattern 사유).

### Phased Schedule (W1-W8) — 25 IN 항목 슬롯 매핑

브레인스토밍 W1-W8 골격을 그대로 유지하되, UIUX 보강 8항목 + 결제 + 데이터 내보내기 + 온보딩 + audit를 적절한 주차에 분산.

#### W1 — Foundation (Backend Core + Infra Bootstrap)

**작업:**
- DB 스키마 설계·생성(Postgres) — `users`, `meals`, `feedbacks`, `subscriptions`, `payment_logs`, `audit_logs`, `food_nutrition`, `knowledge_chunks`. 식약처 표준 키 + KDRIs `health_goal` enum + 22종 알레르기 lookup
- FastAPI CRUD 골격 + Auth(`/auth/google` + JWT access/refresh + `/auth/logout`) + 회원 탈퇴 API(`DELETE /users/me`)
- Google OAuth callback + JWT 발급
- 음식 영양 DB 시드 1차(식약처 OpenAPI 또는 통합 자료집 ZIP) — 1,500-3,000건 한식 우선
- Redis 셋업(rate limit + 캐시 인프라)
- Docker Compose 일괄 부팅 (W1 day1부터 로컬=컨테이너)
- Sentry 통합 + 환경 변수 분리(.env.example)

**MVP IN 반영:** #1, #2 (백엔드), #14 logout API, #15 회원 탈퇴 API, #6 음식 RAG 시드, #12 Redis, #13 Docker/Sentry

**Spike 1일차 (R4·R5·R7 대응):** 식약처 OpenAPI 호출 + 백업안 검증 + Docker 1-cmd 부팅 검증.

#### W2 — RAG Core (LangGraph 6노드 + Self-RAG)

**작업:**
- pgvector extension 활성화 + 임베딩 인덱스
- 음식명 정규화 사전 1차 (NFKD + 공백/오타·이형 표준화 — "짜장면/자장면", "김치찌개/김치 찌개" 등) + 임베딩 fallback
- 가이드라인 미니 지식베이스 시드(KDRIs 2020 활용자료 + 대비학회 9판 + 대당학회 매크로 권고 + 질병관리청 표준) — 50-100 chunks. 메타데이터(`source`, `authority_grade`, `topic`, `applicable_health_goals`)
- LangGraph 6노드 구현: `parse_meal` · `retrieve_nutrition` · `evaluate_retrieval_quality` · `fetch_user_profile` · `evaluate_fit` · `generate_feedback`
- Self-RAG 분기: `evaluate_retrieval_quality` → `rewrite_query` → 재검색 (1회 한도)
- `evaluate_fit` 알고리즘: Macro 40 + 칼로리 25 + 알레르기 20 + 균형 15 = 100점

**MVP IN 반영:** #5, #6 (RAG core)

**Spike (R1 대응):** 음식명 매칭 100건 테스트셋 1회 검증.

#### W3 — Integration + Compliance Texts + Tests

**작업:**
- OCR/Vision 통합(OpenAI Vision API) — 사진 → `parsed_items` 추출
- Structured Output Pydantic + retry 1회 + error edge fallback (R3 대응)
- 식약처 광고 금지 표현 후처리 가드(C5) — 정규식 + 안전 워딩 치환 (T10 KPI 대응)
- 디스클레이머 한·영 텍스트 작성 (research 3.4 그대로) — DB 또는 정적 파일
- PIPA 동의서 템플릿 작성 (5개 섹션) — DB 또는 정적 파일
- Pytest 핵심 경로 작성 (LangGraph 6노드 + fit_score + 알레르기 가드 + 광고 표현 가드)
- LangSmith 외부 옵저버빌리티 통합 + 한식 100건 평가 데이터셋 업로드 (Epic 3 Story 3.8 / FR49 / NFR-O1~O5) — 마스킹 hook + LangGraph native 자동 트레이싱 + 평가 회귀

**MVP IN 반영:** #4 OCR, #5 안정화, #17 디스클레이머 텍스트(백엔드), #16 동의서 템플릿(백엔드), #13 Pytest, LangSmith 옵저버빌리티(FR49)

#### W4 — Mobile UX (1차)

**작업:**
- RN(Expo) 골격 + 라우팅 + 디자인 토큰
- 온보딩 흐름 — 디스클레이머 → 약관 동의 + 개인정보 동의(별도 분리) → 사용법 튜토리얼 2-3 화면 → 건강 프로필 입력 (#16, #17, #24, #2 모바일)
- 식단 입력 화면 — 텍스트 + 사진 (카메라/사진첩 권한 요청 흐름 + 거부 시 안내) (#3 모바일)
- 스트리밍 채팅 UI — react-native-sse, 인용 표시, fit_score 표시 + "건강 목표 부합도 점수" 디스클레이머 (#7)
- 일별 식단/피드백 기록 화면 (#8)
- Expo 푸시 + 권한 요청 흐름 + 미기록 nudge cron (#9)
- 알림 설정 ON/OFF 토글 (#19)
- 로그아웃 (#14 모바일)
- 표준 빈/로딩/에러 화면 1차 적용

**MVP IN 반영:** #3, #7, #8, #9, #14, #16, #17, #19, #24, 권한 요청 AC, 표준 빈/로딩/에러 AC

**Spike day1 (R2 대응):** RN SSE 스트리밍 검증, polling fallback 결정.

#### W5 — Web + Account/Admin Surface

**작업:**
- Next.js 사용자 주간 리포트(Recharts) — 4종 차트(매크로 비율, 칼로리 vs TDEE, 단백질 g/kg, 알레르기 노출) (#10)
- Next.js 관리자 화면(반응형) — 사용자 검색·조회·수정 (#11)
- 관리자 로그인 + admin role 권한 분리 — 일반 JWT와 admin JWT 분리 (#21)
- **관리자 활동 로그 (audit log)** — admin 모든 액션 기록 + 자기 활동 패널 (#25)
- 설정 화면 — 진입점 통합(프로필/알림/약관/처리방침/디스클레이머/회원 탈퇴/데이터 내보내기/앱 정보) (#18)
- 프로필 수정 화면 — 건강 프로필 CRUD 확장 (#20 모바일 + Web)
- 회원 탈퇴 화면 — 모바일 + Web (#15 화면)
- **데이터 내보내기(IN #23)** — `GET /users/me/export` JSON/CSV 다운로드 (모바일 + Web)
- 약관·처리방침·디스클레이머 보기 화면 (모바일 설정 + Web 푸터 링크)

**MVP IN 반영:** #10, #11, #15(화면), #18, #20, #21, #23, #25

#### W6 — Operational Polish + 표준 UX 일괄

**작업:**
- Sentry 룰 정교화 — LangGraph 노드 실패·LLM 호출 실패·DB 에러 자동 알림. 민감정보 마스킹 beforeSend hook
- 구조화 로깅 — JSON 로그 + 사용자 식별자 마스킹
- Rate limit 정교화 — 사용자별 분당 60 / 시간당 1,000 / LangGraph 분당 10 (Redis 슬라이딩 윈도우)
- Swagger/OpenAPI 정리 — 전 endpoint + 요청/응답 스키마 + 에러 코드 명세
- **앱 정보 화면(IN #18 sub-entry)** — 버전·빌드·OSS 라이선스 고지 (license-checker 자동 생성)
- **표준 빈/로딩/에러 화면 일괄 적용** — 전 화면(W4·W5에서 1차 적용한 패턴 통일·정합)
- 데이터 모델 표준화 검증 — 식약처 키·KDRIs 매크로 룰·22종 알레르기 enum 무결성

**MVP IN 반영:** #13 (Sentry/Swagger/Pytest 70% 보강), #18 sub-entries, 표준 UX AC 일괄

#### W7 — Deploy + Payment

**작업:**
- Docker Compose 강화 — multi-stage build, healthcheck, dependency wait
- 클라우드 배포 — Vercel(Web) + Railway(BE/Postgres/Redis) + Cloudflare R2(이미지). HTTPS·HSTS 적용
- SOP 4종 작성: (1) 의료기기 미분류 입장 SOP, (2) PIPA 2026.03.15 동의서 템플릿, (3) 디스클레이머 한·영, (4) 식약처 광고 가드
- README 고도화 — 5섹션 표준(Quick start / Architecture / 데이터 모델 / 영업 답변 5종 closing FAQ / AWS·GCP·Azure 마이그레이션 + PG 본 계약 가이드)
- **결제/구독 sandbox 통합(IN #22)** — Toss Payments 또는 Stripe sandbox 정기결제 1플랜 + 결제 화면(모바일+Web) + 영수증/이용내역 + 구독 해지. webhook 처리 + payment_logs 기록. 4-5일 배정.

**MVP IN 반영:** #13(클라우드 배포 + SOP), #22

**Spike day1 (R5 대응):** 클라우드 배포 dry-run.

#### W8 — Demo + Sales Material

**작업:**
- 데모 시나리오 9포인트 영상 5종(고객사 페르소나별 — 병원/보험/식품/스타트업/제약 각 1개) — 무편집 1회 촬영 가능 검증
- 포트폴리오 페이지 — 데모 영상 임베드 + 영업 첫 미팅 자료 다운로드 + 5종 SOP 링크
- 영업 답변 5종 closing FAQ 마무리 — 차별화 / 인허가 / 적용 / 8주 가능성 / 유지보수
- 영업 자료 패키지 — Brief 요약 1페이지 + 차별화 카드 4종 + 데모 영상 5종 + SOP 4종 + 영업 답변 FAQ
- 회귀 테스트 1회전 — T1-T10 KPI 통과 검증

**MVP IN 반영:** B1, B2, B5 KPI 측정 + 8주 통과 체크리스트 마무리

### Post-MVP (Step-03 Product Scope의 Growth/Vision 참조)

- **Phase 2 — Growth (외주 첫 사이클 이후):** 클라이언트별 어댑터 (식품기업 자사 SKU 통합, 보험사 인센티브 연동, 병원 EMR, 스타트업 PoC 변형), A/B 테스트, 알림 정책 세분화, 다국어, 데이터 다운로드 권리 풀 구현 등 — *MVP 코어 유지 + 모듈만 교체*
- **Phase 3 — Vision (1-2년):** "한국 헬스테크 RAG 외주 라인업" 표준 모듈화 (가이드라인 RAG 시드 키트 + LangGraph 6노드 템플릿 + Docker 인수인계 패키지) — 도메인 외주사 포지션 전환

### Risk Mitigation Strategy (8주 일정 보호)

**Technical Risks:**
- W1·W2·W4·W7 day1 spike으로 R1·R2·R4·R5 사전 차단 (각 1일 spike → 안되면 fallback 즉시 전환).
- LangGraph 노드 isolation + Pydantic + retry 1회 + error edge fallback (R3).
- 듀얼-LLM 자동 전환 (OpenAI 장애 시 Claude — TC4).

**Market Risks:**
- 도메인 리서치가 시장 빈자리 검증 완료(6.5조 + 5개 고객사 발주 누적). MVP는 영업 통과 가능성을 검증.
- 외주 영업 첫 미팅 시 고객사 반응이 약하면 차별화 카드 4종 중 강한 1-2개로 압축 (예: 한국 1차 출처 인용 + 외주 인수인계).

**Resource Risks (1인 8주의 의존성):**
- W4 모바일 작업 지연 시 → W4의 일부 화면(예: 알림 설정·앱 정보·OSS 라이선스 표시)을 W6으로 미루는 buffer.
- 결제 sandbox(W7)가 일정 압박 시 → Toss Payments 단일(Stripe 영문 가이드 README 미루기)로 압축.
- 데모 영상(W8)이 시간 부족 시 → 5종 페르소나 중 강한 2종(스타트업 CTO + 병원 의료정보팀) 우선 + 나머지 3종은 외주 첫 사이클 후 보강.
- 회귀 테스트 통과 우선 — 실패 KPI(T1-T10)는 W8 안에서 즉시 조치.

**Health-domain Risk (특수):**
- 의료기기 미분류 입장이 식약처 정책 변경으로 흔들리면 → SOP 즉시 갱신 + 영업 답변에 *"인허가 트랙 자문 별도"* 라인 추가 (R10).

---

## Functional Requirements

본 섹션은 **Capability Contract** 다. 여기 명시되지 않은 기능은 최종 산출물에 존재하지 않는다. UX·아키텍처·에픽 분해는 본 FR을 단일 출처로 사용한다.

총 9개 capability 영역, 49개 FR. 각 FR은 *무엇을(WHAT)* 명시하며 *어떻게(HOW)* 는 후속 단계 결정.

### 1. Identity & Account

- **FR1.** 엔드유저는 Google OAuth로 가입·로그인하고 동일 계정으로 모바일·웹 양쪽에 인증된 채 진입할 수 있다.
- **FR2.** 엔드유저는 자기 건강 프로필(나이, 체중, 신장, 활동 수준, `health_goal` 4종 중 1[`weight_loss`/`muscle_gain`/`maintenance`/`diabetes_management`], 식약처 22종 알레르기 중 다중 선택)을 입력할 수 있다.
- **FR3.** 엔드유저는 자기 건강 프로필을 언제든 수정할 수 있고 변경은 이후 모든 분석에 즉시 반영된다.
- **FR4.** 엔드유저는 모바일 또는 웹 어디서나 로그아웃할 수 있다.
- **FR5.** 엔드유저는 자기 계정을 삭제(회원 탈퇴)할 수 있다. 시스템은 PIPA 외 관련법 보존 의무 항목 외 모든 사용자 데이터를 즉시 파기한다.

### 2. Privacy, Compliance & Disclosure

- **FR6.** 엔드유저는 첫 진입 시 표준 디스클레이머(한·영)를 확인하고 약관 동의 + 개인정보 동의(PIPA 민감정보, 별도 분리)를 통과한 뒤에만 핵심 기능에 진입할 수 있다.
- **FR7.** 엔드유저는 PIPA 2026.03.15 자동화 의사결정 동의를 별도로 수행하며, 미수신 사용자에 대해 시스템은 자동 분석(`evaluate_fit`/`generate_feedback`) 호출을 차단하고 안내 화면을 노출한다.
- **FR8.** 엔드유저는 약관·개인정보 처리방침·디스클레이머 한·영 텍스트를 앱·웹 어디서나 다시 열람할 수 있다.
- **FR9.** 엔드유저는 자기 식단·피드백·프로필 데이터를 표준 형식(JSON 또는 CSV)으로 다운로드할 수 있다 (PIPA 정보주체 권리).
- **FR10.** 엔드유저는 알림·카메라·사진첩 권한을 거부한 경우에도 빈 화면이 아닌 상황별 안내 화면과 설정 deep link를 제공받는다.
- **FR11.** 시스템은 모든 분석 피드백 카드 푸터에 *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 디스클레이머를 노출한다.

### 3. Meal Logging

- **FR12.** 엔드유저는 모바일에서 식단을 *텍스트* 또는 *사진* 으로 입력할 수 있다.
- **FR13.** 엔드유저는 자기 식단 기록을 조회·수정·삭제할 수 있다.
- **FR14.** 엔드유저는 일별 식단 기록(식사 + 매크로 + 피드백 요약 + `fit_score`)을 한 화면에서 시간순으로 볼 수 있다.
- **FR15.** 엔드유저는 사진 업로드 시 OCR 결과로 추출된 음식 항목을 확인하고 수정한 후 분석을 시작할 수 있다.
- **FR16.** 엔드유저는 오프라인 상태에서 텍스트 식단을 입력하면 큐잉되어 온라인 복귀 시 자동 sync된다.

### 4. AI Nutrition Analysis (Self-RAG + 인용형 피드백)

- **FR17.** 시스템은 입력된 식사를 다단계 분석 파이프라인(음식 항목 추출 → 영양 검색 → 검색 신뢰도 평가 → 사용자 프로필 조회 → 적합도 평가 → 피드백 생성)으로 처리한다.
- **FR18.** 시스템은 음식 영양 검색 신뢰도가 임계값 미달 시 쿼리를 재작성하고 1회 재검색하는 자가-검증 패턴을 수행한다.
- **FR19.** 시스템은 한국식 음식명 변형(예: "짜장면" / "자장면")을 통합 매칭하여 동일 항목으로 인식한다.
- **FR20.** 시스템은 음식 인식 신뢰도가 재검색 후에도 낮으면 사용자에게 *"이게 ◯◯이 맞나요?"* 형태의 재질문을 보내 모호성을 해소한다.
- **FR21.** 시스템은 사용자 건강 목표·매크로 적합도·칼로리 적합도·알레르기·영양 균형을 통합하여 0-100 *건강 목표 부합도 점수* 를 산출한다.
- **FR22.** 시스템은 사용자 알레르기 항목과 식사 매칭 발견 시 점수 0과 *알레르기 위반* 사유를 반환하고 매크로/칼로리 점수를 무시한다.
- **FR23.** 시스템은 분석 결과를 한국 1차 출처(보건복지부 KDRIs / 대한비만학회 진료지침 / 대한당뇨병학회 매크로 권고 / 식약처 식품영양성분 DB) 인용을 포함한 자연어 피드백으로 생성한다.
- **FR24.** 시스템은 모든 권고 텍스트에 *(출처: 기관명, 문서명, 연도)* 패턴을 포함하며, 누락 시 후처리에서 재생성 또는 안전 워딩으로 치환한다.
- **FR25.** 시스템은 식약처 광고 금지 표현(진단·치료·예방·완화)을 가드레일로 필터링하고 안전 대안 워딩으로 치환한다.
- **FR26.** 엔드유저는 분석 결과를 모바일 채팅 UI에서 스트리밍 텍스트로 점진 수신한다.
- **FR27.** 시스템은 메인 LLM 호출 실패 시 보조 LLM(별도 벤더)으로 자동 전환하여 분석을 완료한다.

### 5. Engagement & Notifications

- **FR28.** 엔드유저는 첫 사용 시 *디스클레이머 → 약관 동의 → 사용법 안내(2-3 화면) → 건강 프로필 입력* 의 온보딩 튜토리얼을 순차 통과한다.
- **FR29.** 시스템은 사용자 설정 시간(기본 저녁 8시) 후 30분 경과 + 당일 식단 미입력 시 자동 푸시 nudge를 전송한다.
- **FR30.** 엔드유저는 푸시 알림을 ON/OFF로 토글하고, 알림 시간을 변경할 수 있다.
- **FR31.** 엔드유저가 푸시 알림을 탭하면 모바일 식단 입력 화면으로 직행한다.

### 6. Insights & Reporting

- **FR32.** 엔드유저는 웹에서 자기 주간 리포트(7일 매크로 비율 추이 / 칼로리 vs TDEE / 단백질 g/kg 일별 추이 / 알레르기 노출 횟수)를 차트로 조회한다.
- **FR33.** 엔드유저는 주간 리포트에서 *"다음 주 권장 매크로 조정"* 인사이트 카드를 한국 1차 출처 인용과 함께 본다.
- **FR34.** 엔드유저는 다음 주 매크로/칼로리 목표를 설정 화면에서 조정할 수 있고, 변경은 미기록 nudge 룰과 모바일 권장 표시에 자동 반영된다.

### 7. Administration & Audit Trust

- **FR35.** 관리자는 일반 사용자와 분리된 admin role 인증으로 웹 관리자 화면에 진입한다.
- **FR36.** 관리자는 사용자 검색·식단 이력 조회·피드백 로그 조회·프로필 수정을 수행할 수 있다.
- **FR37.** 시스템은 관리자의 모든 조회·수정 액션을 *시점·액터·액션·대상* 으로 audit log에 기록한다.
- **FR38.** 관리자는 자기 활동 로그를 관리자 화면에서 직접 조회할 수 있다 (self-audit).
- **FR39.** 시스템은 관리자가 사용자 데이터를 조회할 때 민감정보(이메일·체중·알레르기 상세)를 기본 마스킹 표시하고, 명시적 *원문 보기* 액션 시에만 해제한다.

### 8. Subscription & Payment

- **FR40.** 엔드유저는 정기결제 1플랜을 sandbox 결제 화면에서 신청·해지할 수 있다.
- **FR41.** 엔드유저는 자기 결제 영수증과 이용내역을 조회할 수 있다.
- **FR42.** 시스템은 결제 webhook을 받아 구독 상태를 갱신하고 결제 이벤트 이력을 기록한다.

### 9. Operations & Handover

- **FR43.** 시스템은 동일 입력 LLM 응답과 음식 검색 결과를 캐시 계층으로 응답 시간을 단축한다.
- **FR44.** 시스템은 사용자별 호출 횟수 제한과 LangGraph 호출 별도 제한을 적용하여 비용·악용을 방어한다.
- **FR45.** 시스템은 분석 노드 실패·외부 API 실패·DB 에러를 에러 트래킹에 자동 수집하며 민감정보를 마스킹한다.
- **FR46.** 시스템은 표준 OpenAPI 명세를 통해 모든 endpoint를 외주 인수인계 가능한 형태로 문서화한다.
- **FR47.** 시스템은 1-command 컨테이너 부팅으로 데이터베이스·벡터 검색·캐시·API·시드 데이터를 일괄 시작할 수 있다.
- **FR48.** 외주 클라이언트 개발자는 README + 컨테이너 부팅 명령만으로 1일 내 로컬 환경을 구축하고 자체 데이터 통합을 시도할 수 있다.
- **FR49.** 시스템은 LangGraph 노드 호출·LLM 호출·RAG 검색을 외부 옵저버빌리티 플랫폼(LangSmith)으로 자동 트레이싱하며, 한식 100건 평가 데이터셋 회귀 평가를 통해 AI 품질 추세를 추적할 수 있다. 트레이스 송신 전 민감정보(NFR-S5)를 마스킹한다. 보드는 개발자·외주 발주자 전용이며 일반 사용자에게 노출되지 않는다.

---

**Capability Contract 주의:** 이상 49개 FR에 명시되지 않은 기능은 본 PRD의 정식 범위에 포함되지 않는다. 추가 capability가 필요하면 PRD 개정을 통해 명시 추가해야 한다. UX·아키텍처·에픽·스토리는 본 FR 목록을 단일 출처로 사용한다.

---

## Non-Functional Requirements

본 NFR은 **이 산출물에 실제로 적용되는** 품질 속성만 포함한다. 영업 포트폴리오 frame이라 high-traffic·풀 WCAG 인증 같은 항목은 baseline 수준으로 정의하고 외주 인수 후 클라이언트별 강화로 분리한다.

### Performance

| ID | 측정 대상 | 목표 | 측정 방법 |
|----|----------|------|----------|
| **NFR-P1** | 모바일 식단 입력 → 피드백 도착 종단 지연 (사진 OCR 포함) | p50 ≤ 4초 / p95 ≤ 8초 | 부하 테스트 50건 + 실 사용 환경 측정 |
| **NFR-P2** | 모바일 식단 입력 → 피드백 도착 종단 지연 (텍스트 only) | p50 ≤ 2.5초 / p95 ≤ 5초 | 동일 |
| **NFR-P3** | 스트리밍 첫 토큰 도착(TTFT) | p50 ≤ 1.5초 / p95 ≤ 3초 | 50회 측정 |
| **NFR-P4** | LangGraph 6노드 단일 호출(Self-RAG 미발동) | 평균 ≤ 3초 | Sentry transaction tracing |
| **NFR-P5** | LangGraph + Self-RAG 1회 재검색 추가 지연 | + ≤ 2초 | 동일 |
| **NFR-P6** | 음식 RAG pgvector 검색 응답 (캐시 miss) | p95 ≤ 200ms | Postgres pg_stat_statements |
| **NFR-P7** | 음식 RAG 캐시 hit 응답 | p95 ≤ 30ms | Redis 응답 시간 |
| **NFR-P8** | Web 주간 리포트 7일 데이터 초기 로딩 | ≤ 1.5초 | Lighthouse + 실제 측정 |
| **NFR-P9** | Web 관리자 사용자 검색 (1만 건 사용자 가정) | ≤ 1초 | 부하 테스트 |
| **NFR-P10** | API endpoint p95 응답 시간 (분석 외) | ≤ 500ms | Sentry transaction tracing |

### Security

- **NFR-S1.** 모든 통신은 TLS 1.2+ 강제. HSTS 헤더 적용. HTTP 평문 요청은 308 redirect.
- **NFR-S2.** JWT access 토큰은 만료 30일, refresh 90일. 모바일은 Secure storage(iOS Keychain · Android Keystore), 웹은 httpOnly Secure 쿠키.
- **NFR-S3.** 사용자 비밀번호 자체 저장 없음(Google OAuth 단독). 따라서 비번 노출 표면 0.
- **NFR-S4.** 사용자 호출 횟수 제한: 분당 60건 / 시간당 1,000건. LangGraph 호출(LLM 비용 가중) 별도: 분당 10건. 초과 시 HTTP 429.
- **NFR-S5.** 민감정보(체중·신장·알레르기·식단 raw_text)는 로그·Sentry breadcrumbs·전송 페이로드 모두에서 마스킹. Sentry beforeSend hook으로 강제 적용.
- **NFR-S6.** Postgres at-rest 암호화는 Railway 표준 디스크 암호화 의존. 컬럼 단위 추가 암호화는 Growth(외주 클라이언트별 강화).
- **NFR-S7.** Admin role JWT는 일반 사용자 JWT와 분리된 secret + 짧은 만료(8시간). 모든 admin 액션은 audit log 자동 기록(FR37).
- **NFR-S8.** 관리자 화면 접근 IP 화이트리스트는 외주 클라이언트별 옵션(MVP는 강제 X).
- **NFR-S9.** 외부 LLM API 키(OpenAI, Anthropic)는 환경 변수 + Railway secrets로 관리. 코드·로그·git 히스토리에 노출 0.
- **NFR-S10.** 외주 인수인계 시 키 회전 SOP 명문화 — README의 *"API key 회전 절차"* 1페이지.

### Reliability & Availability

- **NFR-R1.** 목표 가용성: Railway SLA 기준 99.9% (월 다운타임 ≤ 43분). 단 멀티-AZ 구성은 1인 anti-pattern으로 제외.
- **NFR-R2.** 외부 LLM 장애 fallback: 메인 LLM(OpenAI) 실패 시 보조 LLM(Anthropic Claude)으로 자동 전환(`evaluate_fit` 노드 외 generation에도 적용). 양쪽 모두 실패 시 사용자에게 *"AI 서비스 일시 장애, 잠시 후 다시 시도해주세요"* 안내.
- **NFR-R3.** Structured Output 파싱 실패 시 Pydantic 검증 + retry 1회 + error edge fallback. 노드별 isolation으로 한 노드 실패가 전체 파이프라인을 멈추지 않음.
- **NFR-R4.** DB 다운 시: API 503 + 사용자에게 안내. 단순 조회용 일별 기록은 모바일 로컬 캐시(7일치)에서 읽기 전용 표시.
- **NFR-R5.** 백업: Postgres 일별 백업 7일 보존(Railway 표준).
- **NFR-R6.** Sentry로 LangGraph 노드 실패·외부 API 실패·DB 에러 자동 알림. 일별 비용 임계치(R6 mitigation) 알림.

### Observability & AI Quality

LLM 기반 시스템의 *프로덕션급 운영 능력*을 영업 카드로 입증. Sentry(에러 트래킹)와 역할이 다름 — Sentry는 *실패*를, LangSmith는 *동작 품질·추세*를 본다.

- **NFR-O1 (트레이싱 커버리지).** LangGraph 6노드 + Self-RAG 재검색 + LLM 호출(`generate_feedback`, `evaluate_fit`, `rewrite_query`) + RAG 검색(`retrieve_nutrition`, `knowledge_chunks` retrieve) 100% 자동 트레이스. 노드별 latency·token·cost·input/output 보존(마스킹 후).
- **NFR-O2 (민감정보 마스킹 — NFR-S5 결합).** LangSmith run 송신 전 체중·신장·알레르기·식단 raw_text를 마스킹. 마스킹 hook은 코드 1지점(`app/core/observability.py`)에서 강제. 마스킹 누락 시 PR CI 실패.
- **NFR-O3 (평가 데이터셋 회귀).** 한식 100건 테스트셋(짜장면/자장면 변형 포함, Story 3.4 KPI와 동일 셋)을 LangSmith Dataset에 업로드. 주요 프롬프트·노드 변경 PR 시 회귀 평가 1회 실행 — 정확도 ≥ 90% 미달 시 PR 머지 차단(권장, 강제는 아님).
- **NFR-O4 (영업 산출물 — 보드 링크).** Story 8.6 영업 데모 9포인트 중 1포인트로 LangSmith 보드 스크린샷 + 공개 링크 1세트 포함. *"LLM 동작을 추적·평가할 수 있다"* 역량 입증.
- **NFR-O5 (외부 의존 제3자 제공).** 트레이스 데이터는 LangSmith 클라우드(미국 region)로 송신 → 개인정보처리방침에 *제3자 제공·국외 이전* 항목 명시. NFR-O2 마스킹으로 PII 송신 0 보장 → PIPA 통지 의무 최소화. Self-hosted LangSmith는 외주 클라이언트별 옵션(MVP OUT).

### Scalability

- **NFR-Sc1.** MVP baseline: 동시 사용자 100명 / DAU 1,000명까지 *현재 단일 Railway 노드 + 단일 Postgres + Redis* 조합으로 처리.
- **NFR-Sc2.** Web 트래픽: Vercel CDN 기본 의존. 영업 데모 환경에서 burst 처리 가능.
- **NFR-Sc3.** 외주 인수 후 클라이언트 트래픽: 10배 성장 시 Railway scale-up + Postgres replica + Redis cluster 마이그레이션 가이드를 README에 명시. 본 산출물 단계에서는 "확장 가능 아키텍처" 입증만 요구.
- **NFR-Sc4.** LLM 비용 보호: Redis 캐시(LLM 응답 + 음식 검색)와 rate limit으로 비용 폭증 방어. 일별 API 비용 임계치 초과 시 알림 + 자동 차단(NFR-S4와 결합).

### Accessibility

영업 포트폴리오 baseline — 풀 WCAG AA 인증은 외주 클라이언트별 강화로 분리. 본 단계는 *기본 좋은 관행* 보장.

- **NFR-A1.** 모바일 — 스크린리더(VoiceOver / TalkBack) 호환: 모든 인터랙티브 요소에 accessibility label. RN 표준 a11y props 적용.
- **NFR-A2.** 색상 대비: 본문 텍스트 4.5:1 이상, 큰 텍스트 3:1 이상(WCAG AA 기준). 디자인 토큰에 통과 색상만 사용.
- **NFR-A3.** 폰트 스케일: 시스템 폰트 크기 변경(접근성 설정)에 반응. 최소 12pt 시작 + 200% 확대 시 레이아웃 깨지지 않음.
- **NFR-A4.** 색상 단독 정보 전달 금지: fit_score는 색상 + 숫자 + 텍스트 라벨 모두 표시(색약 대응).
- **NFR-A5.** Web — 키보드 내비게이션 가능(Tab 순서 자연). 차트는 데이터 테이블 fallback 제공(스크린리더 대응).
- **NFR-A6.** Out of MVP (Growth으로): 풀 WCAG AA 인증, 음성 안내, 시각 장애 사용자 전용 UX.

### User Experience & Coaching Voice

도메인 리서치 4.3의 톤 벤치마크는 *그저 "친절한 AI"* 가 아닌 명시적 voice 결정으로 PRD에 박혀야 한다 — 영업 차별화의 일부.

- **NFR-UX1 (Coaching Tone — Noom-style 채택):** `generate_feedback` 출력은 *긍정·동기부여 + 행동심리 코칭 톤*. 비난·낙담·도덕적 판단 표현 금지. 예시:
  - ✅ "탄수화물 비중이 권장 범위를 약간 초과했어요. 저녁에 단백질 25g 정도 추가하면 균형이 맞춰집니다 (출처: KDRIs 2020)."
  - ❌ "탄수화물을 너무 많이 드셨습니다." (비난)
  - ❌ "오늘 단백질 56g 섭취 (목표 80g). 67% 달성." (Cronometer 톤 — 수치 dump only, 코칭 없음)
- **NFR-UX2 (행동 제안형 마무리 강제):** 모든 피드백 텍스트는 *현재 평가* 와 *다음 행동 제안* 두 부분으로 구성. 시스템 프롬프트에 강제. 행동 제안 부재 시 후처리 재생성.
- **NFR-UX3 (수치는 보조 카드):** 단순 매크로 수치(g, kcal)는 채팅 본문이 아닌 별도 데이터 카드(접힘 가능). MyFitnessPal-스타일 *"56g/80g, 67% 달성"* 표시는 카드에서만 — 채팅 본문은 코칭 톤 자연어 우선.
- **NFR-UX4 (의학 어휘 회피 — C1·C5 결합):** "치료" / "처방" / "진단" / "예방" / "완화" 등 의학 어휘 금지. *"관리"* / *"안내"* / *"참고"* / *"도움이 될 수 있는"* 으로 치환(이미 C5 가드 + 식약처 광고 표현 필터로 강제).
- **NFR-UX5 (한국 문화 맥락 — 한식·식사 시간):** 시스템 프롬프트에 한국 식사 패턴(아침-점심-저녁 비중 25/35/30, 단식·간식 옵션, 회식·외식 빈도 등) 컨텍스트 주입. *"매끼 단백질 25g 권장"* 같은 한국 임상 자료 인용을 자연스럽게 포함.
- **NFR-UX6 (디스클레이머와 톤의 균형):** 매 응답마다 디스클레이머가 코칭 흐름을 깨지 않도록 — 본문은 자연어 코칭, 푸터는 *"건강 목표 부합도 점수 — 의학적 진단이 아닙니다"* 1줄. 길지 않게.

### Localization

- **NFR-L1.** 1차 언어: 한국어. 모든 UI 텍스트·디스클레이머·약관·피드백 한국어.
- **NFR-L2.** 영문 보조: 디스클레이머·약관 풀텍스트 영문판 1세트(글로벌 데모 / B2B 답변용). UI 영문화는 OUT(MVP).
- **NFR-L3.** 통화·날짜 포맷: 한국 표준(KRW · YYYY-MM-DD · 24시간).
- **NFR-L4.** Out of MVP: 풀 다국어(영문 UI / 일문 / 중문) — Growth 단계 외주 클라이언트 요구 시.

### Maintainability & Testability

영업 포트폴리오의 *"외주 인수인계 가능"* 핵심 가치 — 운영 산출물 표준.

- **NFR-M1.** 핵심 경로 Pytest 커버리지 ≥ 70% (T7 KPI). LangGraph 6노드 + fit_score 알고리즘 + 알레르기 가드 + 광고 표현 가드 + 핵심 API endpoints 포함.
- **NFR-M2.** README 5섹션 표준 — Quick start / Architecture / 데이터 모델 / 영업 답변 5종 closing FAQ / AWS·GCP·Azure 마이그레이션 + PG 연동 가이드.
- **NFR-M3.** SOP 4종 표준 — 의료기기 미분류 입장 / PIPA 동의서 템플릿 / 디스클레이머 한·영 / 식약처 광고 가드.
- **NFR-M4.** Swagger/OpenAPI 자동 생성 + 모든 endpoint 요청·응답 스키마 + 에러 코드 명세.
- **NFR-M5.** 환경 변수 표준화 — `.env.example`에 모든 필요 변수 + 설명 + 권장 값. `.env`는 gitignore.
- **NFR-M6.** Docker Compose 로컬 환경 = 컨테이너 환경(W1부터). 환경 차이로 인한 *"내 컴퓨터에선 됐는데"* 차단.
- **NFR-M7.** 외주 클라이언트 신규 개발자 onboarding 시간: README + Docker Compose만으로 ≤ 8시간 부팅 (B3 KPI).
- **NFR-M8.** 데이터 모델 표준성 — 식약처 영양 키 + KDRIs `health_goal` enum + 22종 알레르기 enum이 외주 인수 후 클라이언트 도메인 룰로 *갈아끼우기 쉬운* 추상 계층 분리.

### Compliance & Regulatory (Reference)

본 항목의 상세는 `## Domain-Specific Requirements`의 C1-C6에 명시. NFR 단계에서는 *측정 가능 통과 기준* 만 재정리.

- **NFR-C1.** 의료기기 미분류 통과: SOP 1장 완비 + 영업 답변 *"의료기기 인허가 필요한가?"* 1페이지 (B1·B4 KPI).
- **NFR-C2.** PIPA 2026.03.15 자동화 의사결정 동의: 별도 동의 UI(FR7) + 미동의 시 분석 차단(FR7) + 동의서 템플릿(SOP 1장) (B4 KPI).
- **NFR-C3.** 식약처 광고 금지 표현 가드: T10 KPI(테스트 케이스 ≥ 10건 통과).
- **NFR-C4.** 디스클레이머 한·영 노출: 온보딩 + 결과 카드 푸터 + 약관 페이지 + 설정 화면 — 4개 위치 모두 노출 검증.
- **NFR-C5.** 알레르기 22종 무결성: W1 시드 시점 식약처 표시기준 별표 검증 + enum 갱신 SOP. fit_score 0점 트리거 검증(T 단위 테스트).

### Integration (Reference)

본 항목의 상세는 `## Domain-Specific Requirements`의 I1-I4에 명시. 본 NFR 단계에서는 *통합 외부 시스템의 fallback 요구* 만 재정리.

- **NFR-I1.** 식약처 OpenAPI 장애 시 통합 자료집 ZIP fallback 또는 USDA FoodData Central 백업으로 RAG 시드 가능 (R7 mitigation).
- **NFR-I2.** OpenAI/Anthropic API 한쪽 장애 시 다른 한쪽으로 자동 전환 (NFR-R2).
- **NFR-I3.** OCR(OpenAI Vision) 장애 시 사용자에게 *"사진 인식 일시 장애 — 텍스트로 다시 입력해주세요"* 안내 (graceful degradation).
- **NFR-I4.** 결제 sandbox(Toss/Stripe) 장애는 영업 데모 외 영향 미미. 외주 인수 후 클라이언트 본 PG 통합 시점에 안정성 보강.
