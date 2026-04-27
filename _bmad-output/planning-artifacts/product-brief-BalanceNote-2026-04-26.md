---
title: "Product Brief — BalanceNote (한국 헬스테크 영양 분석 외주 영업 포트폴리오)"
product_name: BalanceNote
codebase_name: AI_diet  # 저장소 디렉토리·기존 BMad 산출물 명칭은 그대로 유지
author: hwan
date: 2026-04-26
brief_type: portfolio_reference_implementation
frame: 외주 영업용 포트폴리오 (학습용 X, 상용 SaaS X)
input_documents:
  - _bmad-output/brainstorming/brainstorming-session-2026-04-26-2038.md
  - _bmad-output/planning-artifacts/research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md
---

# Product Brief: BalanceNote — 한국 헬스테크 영양 분석 외주 영업 포트폴리오

## Executive Summary

**BalanceNote는 한국 헬스테크 외주 시장을 겨냥한 1인 8주 레퍼런스 구현물이다.** 식약처·대한비만학회·KDRIs(한국인 영양소 섭취기준) 등 한국 1차 공식 출처를 RAG로 인용하는 AI 영양 분석 시스템으로, 외주 발주자(병원/보험사/식품사/헬스케어 스타트업/제약사)에게 "AI 신뢰성 책임 추적이 가능한 LangGraph + RAG 솔루션을 8주 안에 납품할 수 있는 1인 개발자"라는 메시지를 시연 가능한 형태로 입증한다.

**왜 지금인가.** 한국 디지털헬스케어 시장은 2023년 6.5조 원(YoY +13.5%)으로 성장했고, 5개 외주 고객사 유형 모두에서 AI 영양·식단 관리 발주 사례가 누적되고 있다(루닛케어, 풀무원 NDP, KB오케어, 대상웰라이프 당프로 2.0, 현대그린푸드×디앤라이프 등). 동시에 글로벌 앱(Noom, MyFitnessPal, Cronometer)은 자체 큐레이션 DB라 병원·보험·식품사의 컴플라이언스를 통과하기 어렵다 — **한국 공식 출처를 직접 인용하는 솔루션의 빈자리**가 외주 진입점이다.

**무엇을 입증하는가.** ① LangGraph 6노드 + Self-RAG 재검색으로 AI 환각률을 낮추는 설계 능력, ② 한국 1차 출처 기반 책임 추적 가능한 영양 RAG 구축 능력, ③ 모바일(RN) + 웹(Next.js) + FastAPI + Docker 풀스택을 외주 산출물 수준의 운영 문서·디스클레이머·SOP까지 패키징할 수 있는 능력. 8주 후 산출물은 영업 시연 영상·README·SOP·Swagger·데모 시나리오 9포인트로 패키징된다.

## The Problem

**외주 발주자의 페인 (1차 타겟).** 한국 병원·보험사·식품사·헬스케어 스타트업은 AI 기반 영양·식단 솔루션을 발주하고 싶지만 — (1) 글로벌 앱은 자체 큐레이션 DB라 책임 추적이 어렵고, (2) 자체 LLM/RAG 인프라 구축은 비용·기간 부담이 크며, (3) 한국 식약처·KDRIs·진료지침에 정합한 인용 시스템을 갖춘 외주사가 드물다. "AI는 도입하고 싶은데 데이터 거버넌스·인허가·디스클레이머를 알아서 정리할 수 있는 외주사를 못 찾겠다"가 누적된 페인이다.

**1인 외주 개발자의 메타 페인.** 풀스택 1인 외주 개발자는 "왜 우리가 당신에게 맡겨야 하는가"라는 질문에 단순 GitHub 토이 코드가 아닌 **운영 가능한 도메인 솔루션**으로 답해야 한다. 학습용 토이 프로젝트와 영업 가능 포트폴리오는 산출물 단위가 다르다 — 후자는 디스클레이머·SOP·동의 패턴·데모 시나리오·운영 문서까지 포함된다.

**상태 유지의 비용.** 외주 영업 채널이 막힌 채로 시간이 흐르면 발주자는 (a) 글로벌 앱 도입 후 컴플라이언스 비용을 내부 흡수하거나, (b) 대형 외주사에 비용을 더 내고 위탁한다. 1인·소규모 외주 시장 자체가 수축한다.

## The Solution

BalanceNote는 **외주 시연 가능한 한국 헬스테크 AI 영양 분석 레퍼런스 시스템**이다. 사용자가 모바일 앱에서 식사를 텍스트 또는 사진으로 입력하면, 6단계 LangGraph 파이프라인이 (1) 음식 항목 추출 → (2) 식약처 영양 DB pgvector 검색 → (3) 검색 신뢰도 평가 후 부족 시 Self-RAG 재검색 → (4) 사용자 프로필 조회 → (5) 매크로/칼로리 적합도 점수 산출 → (6) 한국 가이드라인 인용을 포함한 스트리밍 피드백 생성을 수행한다. 결과는 모바일 채팅 UI에 실시간 표시되고, Next.js 웹에서는 사용자 주간 리포트와 관리자 대시보드가 함께 제공된다.

핵심은 **모든 권고에 출처가 따라붙는다**는 점이다. *"오늘 점심은 탄수화물 비중이 70%로 권장 범위(55-65%)를 약간 초과했어요. 저녁에 단백질을 25g 정도 추가하면 매크로 균형이 맞춰질 거에요. (출처: 2020 KDRIs)"* 형태의 인용형 피드백은 글로벌 앱이 제공하지 못하는 **책임 추적성**을 외주 고객사에 즉시 보여준다.

## What Makes This Different

1. **한국 1차 공식 출처 RAG.** 식약처 식품영양성분 DB(공공데이터 OpenAPI), 보건복지부 2020 KDRIs, 대한비만학회 진료지침 9판(2024 갱신), 대한당뇨병학회 매크로 권고를 가이드라인 RAG에 직접 시드한다. 모든 피드백 텍스트는 출처를 인용 가능 → **병원·보험사·식품사 컴플라이언스 통과의 핵심 카드**.
2. **Self-RAG 재검색 노드.** 단순 GPT 호출이 아니라 검색 신뢰도(`retrieval_confidence`)를 평가해 낮을 때 쿼리를 재작성하고 1회 재검색한다. 음식명 정규화 사전("짜장면" ≠ "자장면") + 임베딩 fallback으로 한국식 음식 매칭 정확도를 끌어올린다. 환각률 ↓ → 영업 답변 가능.
3. **한국 표준 통합 데이터 모델.** 식약처 알레르기 22종이 `users.allergies` 도메인으로, KDRIs AMDR/RDA가 `health_goal` enum별 매크로 룰로, 식약처 영양 성분 키가 `food_nutrition.nutrition` jsonb 표준으로 스키마에 박혀 있다. 외주 인수 시 한국 규제 정합성 작업이 0에 수렴.
4. **외주 인수인계 가능한 운영 산출물.** Docker Compose 1-cmd 실행, Sentry 에러 트래킹, Swagger API 문서, README/SOP, 디스클레이머 텍스트(한/영), 개인정보 동의 패턴, 의료기기 미분류 영업 답변 — 학습용 토이가 아닌 운영 외주 산출물 수준.

## Who This Serves

### 1차 타겟 — 외주 발주자 (Brief의 진짜 독자)

| 고객사 유형 | 적합성 | 핵심 가치 카드 | 대표 발주 사례 |
|---|---|---|---|
| **헬스케어 스타트업 CTO** | ★★★★★ | LangGraph 6노드 모듈 분리 + Docker 1-cmd → PoC 4주 내 검증 | DHP 액셀러레이터 포트폴리오 9곳 |
| **병원 의료정보팀** | ★★★★ | 가이드라인 RAG 인용 + 디스클레이머 표준 + 의료기기 미분류 입장 | 루닛케어 AI 식단, 디앤라이프×현대그린푸드 |
| **보험사 디지털전략팀** | ★★★★ | 푸시 nudge + 주간 리포트 → 가입자 인게이지먼트 KPI 도구 | KB오케어, 삼성생명 THE Health, 교보다솜케어 |
| **식품·식자재 기업 헬스케어 신사업** | ★★★★ | 음식 RAG에 자사 제품 시드 추가 → B2C 솔루션 즉시 확장 | 풀무원 NDP, 대상웰라이프 당프로 2.0, CJ제일제당 |
| **제약사 디지털전략팀** | ★★ | DTx 인허가 전 PoC + 약물별 식단 가이드 포지션 | 대웅제약 모비케어, 한독×웰트 |

### 2차 — 데모 시연용 엔드유저 페르소나

체중 감량 / 근육 증가 / 유지 / 당뇨 관리 4개 `health_goal` 페르소나. 데모 시나리오 9포인트는 외주 고객사 유형별로 강조 노드를 분기한다 — 병원: Self-RAG + 인용 / 보험사: 푸시 + 리포트 / 식품사: DB 확장 + 추천 / 스타트업: 모듈 구조 + Docker.

## Success Criteria

본 산출물은 영업 포트폴리오이므로 KPI는 사용자 활성화가 아닌 **영업 통과 가능성**으로 정의된다.

- **데모 통과:** 9포인트 시연 시나리오 전부가 라이브 환경에서 끊김 없이 동작 (특히 사진 OCR → Self-RAG → 인용 피드백 → 푸시 nudge 체인)
- **인수인계 가능성:** 외주 클라이언트 개발팀이 README + Docker Compose만으로 1일 내 로컬 환경 부팅 가능
- **영업 답변 5종 closing:** "기존 앱과 다른 점은?" / "의료기기 인허가 필요한가?" / "우리 회사 케이스에는 어떻게 적용?" / "8주에 정말 가능한가?" / "유지보수는?" — 전부 README/SOP/FAQ 1차 답변 가능
- **고객사별 페르소나 데모 영상 5종(병원/보험/식품/스타트업/제약 각 1개)** — 영업 첫 미팅 자료
- **컴플라이언스 안전판 명문화:** 의료기기 미분류 입장 + PIPA 2026.03.15 자동화 의사결정 동의 패턴 + 표준 디스클레이머(한/영) — 모두 SOP 문서로

## Scope

### IN — 13항목 (8주 1인 개발)

OAuth 로그인(Google) + 건강 프로필 입력 → 식단 텍스트/사진 입력 CRUD → OCR/Vision 음식 추출 → LangGraph 6노드 (Self-RAG 포함) → 두 종류 RAG (음식 영양 1,500-3,000건 + 가이드라인 50-100 chunks) → 스트리밍 채팅 UI(RN, react-native-sse) → 일별 기록 화면 → Expo 푸시 nudge → Next.js 사용자 주간 리포트(Recharts) + 관리자 화면(반응형) → Redis 캐시 → Docker Compose + Sentry + Pytest + Swagger + README/SOP.

### OUT — 명시적 제외 + 사유

- **결제/구독** — 외주 차별화 가치 낮음. README "PG 연동 확장 가이드"만
- **이메일 인증 풀세트/비밀번호 찾기** — OAuth 대체. 메일 서버 세팅 시간 낭비
- **Kafka/Celery/MSA** — 1인 포트폴리오 안티시그널(과설계). FastAPI BackgroundTasks로 충분
- **자체 LLM/Fine-tuning** — "API를 잘 쓰는 게 외주 본질". 영업적으로도 OK
- **FCM 직접 통합 푸시** — Expo Notifications로 경량 대체
- **풀 논문 RAG** — 정제 비용 1주+. 가이드라인 미니 RAG로 충분
- **DTx 인허가 트랙** — 웰니스 포지션 유지. 영업 답변에서 "확장 가능 PoC"로만 언급
- **분리된 UX 디자인 산출물(wireframe·디자인 시스템)** — 디스클레이머 텍스트·피드백 톤·9포인트 데모로 PRD/스토리에 흡수. 클라이언트가 별도 요구하면 그때 추가

## Compliance & Regulatory (본 산출물 안전판)

- **의료기기 미분류 (웰니스 트랙).** 식약처 가이드라인의 저위해도 일상 건강관리 명시 예시("식사 소비량 모니터·기록·과식 시 경고")에 정확히 일치 → 인허가 진입 회피. 단, 진단성 발언("당신은 당뇨가 의심됩니다") 금지.
- **PIPA 2026.03.15 시행 대응.** LangGraph 자동 분석은 "자동화된 의사결정"에 해당 가능 → 사용자 동의서에 처리 항목·범위 구체 공개. 건강정보(민감정보)는 별도 동의로 분리.
- **표준 디스클레이머.** 한국어/영문 각 1세트, 온보딩·약관·결과 화면 하단 상시 노출. `fit_score`는 "건강 목표 부합도 점수"로 명명 — 의학적 진단 어휘 회피.
- **피드백 텍스트 가드레일.** 식약처 표시·광고 금지 표현(진단/치료/예방/완화) 필터링을 `generate_feedback` 시스템 프롬프트에 주입. 위반 시 안전 대안 워딩으로 치환.

## Technical Approach (high-level)

- **고정 스택:** Next.js · React Native · FastAPI · LangGraph + RAG · PostgreSQL + pgvector · Redis · Docker Compose
- **LangGraph 6노드:** `parse_meal` → `retrieve_nutrition` → `evaluate_retrieval_quality`(Self-RAG 분기) → `fetch_user_profile` → `evaluate_fit`(Structured Output, fit_score 0-100) → `generate_feedback`(스트리밍, 인용형)
- **fit_score 알고리즘:** Macro 적합도(40) + 칼로리 적합도(25) + 알레르기 회피(20, 위반 시 0) + 영양소 균형 보너스(15). Mifflin-St Jeor BMR + TDEE 활동지수 + KDRIs AMDR + 식약처 22종 + 대비/대당학회 권고를 단일 알고리즘에 통합
- **호스팅:** Vercel(Web) + Railway(BE/DB/Redis) + Cloudflare R2(이미지) — AWS 마이그레이션 가이드는 README
- **LLM:** OpenAI GPT-4o-mini(메인) + Anthropic Claude(`evaluate_fit` 보조 — "두 모델 비교" 영업 무기) + OpenAI Vision(OCR)
- **데이터 출처:** 식약처 식품영양성분 DB OpenAPI(음식, 1차 시드) + 보건복지부 KDRIs PDF + 대한비만학회 진료지침 9판 + 대한당뇨병학회 매크로 권고(가이드라인 50-100 chunks)

## Top Risks

| # | 리스크 | 영향 | 대응 |
|---|---|---|---|
| 1 | 음식명 RAG 매칭 부정확("짜장면" ≠ "자장면") | 데모 망함 | 음식명 정규화 사전 1차 매칭 + 임베딩 fallback + Top-3 LLM 재선택 |
| 2 | RN 스트리밍 SSE 까다로움 | W4 일정 밀림 | W4 day1 spike. 안되면 polling fallback |
| 3 | Structured Output JSON 파싱 실패 | LangGraph 노드 멈춤 | Pydantic + retry 1회 + error edge fallback |
| 4 | 영양 DB 가공 시간 초과 | W1 일정 밀림 | W1 day1 spike. USDA FoodData Central 백업안 |
| 5 | 로컬↔클라우드 환경 차이 | W7 일정 밀림 | W1부터 Docker 개발, 로컬=컨테이너 |

## Vision

**6개월 (포트폴리오 공개 후):** 5개 고객사 유형 중 1-2개 유형에서 첫 외주 견적 → 발주 → 납품 사이클 1회 완주. 첫 사이클의 클라이언트 피드백을 다음 외주의 영업 카드로 재투입.

**1-2년:** BalanceNote 코어를 모듈화한 **"한국 헬스테크 RAG 외주 라인업"** 구축 — (a) 가이드라인 RAG 시드 키트, (b) LangGraph 6노드 템플릿, (c) Docker 1-cmd 외주 인수인계 패키지를 표준 산출물로. 외주 단가 협상력 = 도메인 정합성 + 운영 인수인계 완비 → 단순 시급제 1인 외주에서 도메인 외주사 포지션으로.

**확장 시나리오:** ① 식품사 자사 제품 카탈로그 통합 솔루션(B2B → B2C 다리), ② 보험사 인센티브 연동 행동변화 플랫폼, ③ 제약사 DTx 인허가 전 PoC 도구, ④ 병원 EMR 연동 환자 식단 가이드.

---

## 다음 단계

본 Brief는 다음 BMad 단계의 **Why/Who 앵커**다.

1. **`bmad-create-prd`** — 본 Brief의 Scope IN/OUT + Compliance + Technical Approach를 정식 PRD 기능 명세로
2. `bmad-create-architecture` — fit_score 알고리즘, 6노드 LangGraph, RAG 메타데이터를 솔루션 디자인으로
3. `bmad-create-epics-and-stories` — W1-W8 일정을 epic·story로 분해, 도메인 리서치 표준을 acceptance criteria로 인용
4. (생략 권장) `bmad-create-ux-design` — 본 Brief에서 명시적으로 제외. 클라이언트가 디자인 산출물을 추가 요구할 때만 호출
