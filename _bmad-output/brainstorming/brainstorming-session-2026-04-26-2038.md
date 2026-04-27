---
stepsCompleted: [1, 2, 3, 4]
inputDocuments: []
session_topic: 'AI Health-Tech (영양 분석) MVP — 외주 영업용 포트폴리오'
session_goals: '고정 스택(Next.js · React Native · FastAPI · LangGraph+RAG · PostgreSQL+pgvector) 안에서, 3가지 핵심 루프(① 식단 입력 CRUD → ② LangGraph+RAG 분석 → ③ 웹/모바일 결과 표시)가 유기적으로 돌아가고, 외주 고객사에 시연 가능한 수준의 MVP 범위·기능·구현 방향 확정'
selected_approach: 'ai-recommended (역방향 모드로 변형 — facilitator가 초안 생성, user가 VC 시각으로 기각/수정/통과 판정)'
techniques_used: ['First Principles Thinking', 'SCAMPER Method', 'Reverse Brainstorming', 'Resource Constraints']
ideas_generated: ['MVP 스코프 v2 (13항목 IN)', 'LangGraph 6노드 (Self-RAG 포함)', '8주 일정', 'Top 5 리스크', '데모 시나리오 9포인트']
context_file: ''
---

# Brainstorming Session Results

**Facilitator:** hwan
**Date:** 2026-04-26

---

## Session Overview

**Topic:** AI Health-Tech (영양 분석) MVP — 외주 영업용 포트폴리오

**Goals:**
- 고정 스택(Next.js · React Native · FastAPI · LangGraph+RAG · PostgreSQL+pgvector) 안에서, 3가지 핵심 루프가 유기적으로 돌아가는 MVP 확정
  - ① 식단 입력 CRUD
  - ② LangGraph + RAG 분석
  - ③ 웹/모바일 결과 표시
- **외주 사업 영업용 포트폴리오** 수준의 완성도 (단순 학습용 아님)
- VC 거절 모드: 범위 초과 또는 영업 가치 없는 항목은 즉시 기각 + 단순 대안 제시

### Session Setup

- 모바일 스택 확정: **React Native**
- 추가 스택 정책: 기본 고정 스택 외 추가는 "서비스를 위한 기술" 원칙 충족 시만 허용
- 협업 모드: 표준 facilitator 모드(질문→답변)에서 **역방향 모드**(facilitator가 초안 → user가 VC 시각으로 판정)로 전환. 사유: 사용자가 풍부한 상위 컨텍스트를 미리 제공했고 추가 질문은 ceremony에 가까움.
- **결정적 lens 보정:** 1차 초안에서 "학습+시연" frame으로 OCR/지식RAG/푸시/OAuth/Redis/Sentry 등을 기각 → user 피드백으로 **"외주 영업 포트폴리오" frame**으로 재평가. 대부분의 기각이 뒤집힘.

---

## Technique Selection

**Approach:** AI-Recommended Techniques (역방향 모드)

**Recommended Techniques:**
- **First Principles Thinking** — MVP 본질 압축 ("외주 납품 가능 최소 단위가 무엇인가?")
- **SCAMPER Method** — 7개 렌즈로 3 루프 구조화된 발산 (특히 Substitute/Eliminate/Combine 활용)
- **Reverse Brainstorming + Resource Constraints** — VC 거절 모드 수렴, 실패 시나리오 도출

**AI Rationale:** 사용자의 명시적 거절 조건과 정합. Phase 2-3에서 자연스럽게 '욕심 제거'가 작동. 단, 실행 시 facilitator 질문이 ceremony가 되어 역방향 모드로 전환.

---

## 최종 산출물 — MVP 스코프 v2

### ✅ IN (13항목, 영업 포트폴리오 기준)

1. Google OAuth 로그인 + JWT
2. 건강 프로필 입력 (나이/체중/목표/알레르기)
3. 식단 **텍스트 + 사진** 입력 CRUD (모바일)
4. **OCR/Vision** 으로 사진 → 음식 항목 추출
5. LangGraph **6노드** 분석 파이프라인 (Self-RAG 재검색 포함)
6. **두 종류 RAG** — 음식 영양 DB (1,500-3,000건) + 영양 가이드라인 미니 지식베이스 (50-100건)
7. **스트리밍 채팅 UI** (RN, react-native-sse)
8. 일별 식단/피드백 기록 화면 (RN)
9. **푸시 알림** — "오늘 저녁 미기록" nudge (Expo + cron)
10. Next.js 사용자 주간 리포트 (Recharts)
11. Next.js 관리자 화면 (반응형)
12. Redis 캐시 (LLM 응답 + 식품 검색)
13. Docker Compose + 클라우드 배포 + Sentry + Pytest + Swagger + README/SOP

### ❌ OUT (기각 + 사유)

| 항목 | 기각 사유 |
|------|----------|
| 결제/구독 | 외주 고객 차별화 가치 ↓. README에 "PG 연동 확장 가이드"만 |
| 이메일 인증 풀세트/비밀번호 찾기 | OAuth로 대체. 메일 서버 세팅 시간 낭비 |
| Kafka/Celery | 1인 포트폴리오에 안티시그널 (과설계). FastAPI BackgroundTasks로 충분 |
| Microservices | 1인 1서비스에 MSA는 안티패턴 |
| 자체 LLM/Fine-tuning | "API 잘 쓰는 게 외주 본질". 영업적으로도 OK |
| 푸시 알림 풀세트 (FCM 직접 통합) | Expo Notifications로 경량 대체 |
| 풀 논문 RAG | 데이터 정제 비용 1주+ vs 가이드라인 미니 RAG로 충분 |

---

## LangGraph 노드 흐름 (v2)

```
[parse_meal] (텍스트 또는 OCR 결과)
    ↓
[retrieve_nutrition] (pgvector 음식 검색, top-3)
    ↓
[evaluate_retrieval_quality] ★Self-RAG 핵심★
    ├─ confidence 낮음 → [rewrite_query] → 재검색 (최대 1회)
    └─ 충분 → 다음
    ↓
[fetch_user_profile] (RDB)
    ↓
[evaluate_fit] (Structured Output: score + reason)
    ↓
[generate_feedback] (스트리밍, DB 저장)
```

### State 스키마

```python
class AnalysisState(TypedDict):
    user_id: int
    raw_text: str
    image_url: str | None
    parsed_items: list[dict]      # [{name, qty, unit}]
    nutrition_hits: list[dict]
    retrieval_confidence: float
    user_profile: dict
    fit_score: int                # 0-100
    fit_reason: str
    final_feedback: str
    needs_clarification: bool
```

---

## 데이터 모델

### RDB

```
users: id, email, oauth_provider, age, weight_kg, height_cm,
       health_goal (enum), allergies (text[]), created_at

meals: id, user_id, eaten_at, raw_text, image_url,
       parsed_items (jsonb), created_at

feedbacks: id, meal_id, fit_score, fit_reason, feedback_text, created_at
```

### pgvector

```
food_nutrition: id, food_name, food_name_normalized,
                nutrition (jsonb), embedding (vector(1536)), source

knowledge_chunks: id, source, title, content,
                  embedding (vector(1536))
```

### 시드 데이터

- **음식 영양:** 식약처 식품영양성분 DB 1,500-3,000건 (한식 위주). 백업안: USDA FoodData Central
- **가이드라인:** 한국영양학회/식약처 공개 가이드라인 50-100 chunks

---

## 8주 일정

| 주 | 작업 |
|----|------|
| **W1** | DB 스키마 + FastAPI CRUD + OAuth + 영양 DB 시드 + Redis 셋업 |
| **W2** | pgvector 검증 + 가이드라인 미니 지식베이스 시드 + LangGraph 6노드 + Self-RAG |
| **W3** | OCR/Vision 통합 + Structured Output 안정화 + Pytest 핵심 |
| **W4** | RN 화면 + 사진 업로드 + 스트리밍 채팅 + Expo 푸시 |
| **W5** | Next.js 사용자 리포트 + 관리자 + 반응형 + 차트 |
| **W6** | Sentry + 구조화 로깅 + Rate limit + Swagger 정리 |
| **W7** | Docker Compose + 클라우드 배포 + SOP/README 고도화 |
| **W8** | 데모 시나리오 영상 + 포트폴리오 페이지 + 영업 답변 FAQ 정리 |

---

## 인프라 & 외부 서비스 결정

| 항목 | 선택 | 사유 |
|------|------|------|
| Web 호스팅 | **Vercel** | Next.js 표준, 무료 |
| BE/DB 호스팅 | **Railway** | FastAPI + Postgres + pgvector + Redis 한 번에. AWS 마이그레이션 가이드는 README에 |
| 이미지 스토리지 | **Cloudflare R2** | S3 호환, 무료 티어 큼 |
| LLM 메인 | **OpenAI GPT-4o-mini** | 비용 효율 |
| LLM 보조 | **Anthropic Claude (evaluate_fit)** | 추론 품질. "두 모델 비교" 영업 무기 |
| OCR | **OpenAI Vision API** | 별도 OCR 모델 운영 회피 |
| 모바일 푸시 | **Expo Notifications** | RN 표준, FCM 직접 통합 회피 |
| 차트 | **Recharts** | Next.js 표준 |
| RN 스트림 | **react-native-sse 또는 fetch streaming** | SSE 표준 |
| 에러 트래킹 | **Sentry** | 무료 티어 충분 |
| 컨테이너 | **Docker Compose** | 배포 연습 + 이전 설치 시연 |

---

## Top 5 리스크 + 대응

| # | 리스크 | 영향 | 대응 |
|---|--------|------|------|
| 1 | 음식명 RAG 매칭 부정확 ("짜장면" ≠ "자장면") | 데모 망함 | 음식명 정규화 사전 1차 매칭 → 임베딩 fallback. Top-3 LLM 재선택 |
| 2 | RN 스트리밍 SSE 까다로움 | W4 일정 밀림 | W4 1일차 spike. 안되면 polling fallback |
| 3 | Structured Output JSON 파싱 실패 | LangGraph 노드 멈춤 | Pydantic + retry 1회 + error edge fallback |
| 4 | 영양 DB 가공 시간 초과 | W1 일정 밀림 | W1 day1 spike. USDA 백업안 미리 준비 |
| 5 | 로컬→클라우드 환경 차이 | W7 일정 밀림 | W1부터 Docker 개발. 로컬=컨테이너 |

---

## 데모 시나리오 (영업용 9포인트)

1. 📱 **Google 로그인** → "체중 감량" 목표 설정
2. 📱 점심: **사진 촬영** ("짜장면 + 군만두") → OCR로 항목 추출 ← *멀티모달*
3. 📱 채팅 UI 스트리밍 피드백 ← *RAG + Streaming*
4. 📱 음식 인식 실패 시 AI 추가 질문 ← *Self-RAG*
5. 📱 가이드라인 인용된 답변 ← *지식 RAG*
6. 🌐 웹 대시보드: 주간 차트 + 피드백 로그 ← *Next.js + 시각화*
7. 🌐 관리자 화면: 사용자 검색 (반응형) ← *Web 어드민*
8. 📱 저녁 8시 미기록 시 푸시 ← *Expo Notifications*
9. 📄 README/Swagger ← *운영 SOP + API 문서*

---

## 다음 단계

본 세션 산출물은 도메인 리서치(`_bmad-output/planning-artifacts/research/domain-한국-헬스테크-영양-도메인-신뢰성-research-2026-04-26.md`)와 함께 다음 BMad 단계의 입력 자료다.

**정식 순서:**
1. **`bmad-product-brief`** ← 다음 권장. 본 세션의 영업 프레임/스코프를 Brief의 Why/Who 앵커로 압축
2. `bmad-create-prd` — Brief 통과 후, 13항목 IN + 6노드 LangGraph + 도메인 리서치 표준을 기능 명세로
3. `bmad-create-architecture` — fit_score, RAG 메타데이터, 6노드 흐름을 솔루션 디자인으로
4. `bmad-create-epics-and-stories` — W1-W8 일정을 epic·story로 분해
5. (선택) `bmad-create-ux-design` — 디스클레이머/피드백 톤/리포트 레이아웃 wireframe이 필요할 때만. 1인 8주 MVP는 PRD + 스토리에 UI 결정을 흡수하면 생략 가능

---

## Session Reflection

- **무엇이 잘 되었는가:** 사용자의 풍부한 사전 컨텍스트를 활용한 역방향 모드 전환. 1차 기각 → user 피드백 → frame 재정의 → 2차 재평가의 빠른 사이클.
- **결정적 학습:** 같은 항목도 "학습 frame" vs "영업 frame"에서 정반대 판정. **purpose/audience frame을 먼저 못 박는 것이 모든 scoping의 첫 단계**.
- **메모리에 저장:** project (AI_diet는 영업 포트폴리오), feedback (frame 사전 확인), feedback (rich context 시 proposal-first 모드).
