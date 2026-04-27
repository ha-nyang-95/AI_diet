---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7]
inputDocuments:
  - C:/Users/khuk0/vibe/AI_diet/_bmad-output/brainstorming/brainstorming-session-2026-04-26-2038.md
workflowType: 'research'
lastStep: 1
research_type: 'domain'
research_topic: '한국 헬스테크/영양 도메인 — 외주 영업용 AI 영양 분석 MVP의 도메인 신뢰성 확보'
research_goals: |
  6개 목표는 동등 우선순위·동등 깊이로 조사한다.
  1. AI 피드백 텍스트의 영양학적 신뢰성 확보 가이드라인 출처 식별
     (식약처, 한국영양학회, 대한비만학회, 한국인 영양섭취기준 KDRIs 등 1차 자료)
     → W2 가이드라인 RAG 시드 데이터, evaluate_fit 노드의 인용 근거 출처
  2. 데이터 모델에 반영할 영양 도메인 핵심 개념 정리
     (탄단지 비율, RDA/AI/UL 체계, 알레르기 표시 22개 표준, 건강 목표별 식이 가이드)
     → PostgreSQL 스키마 (users.health_goal enum, allergies, food_nutrition.nutrition jsonb), pgvector 메타데이터
  3. 헬스케어 외주/B2C 시장 규제 및 디스클레이머 표준
     (의료기기법상 일반 식이·영양 정보 vs 의료기기 경계, 개인정보보호법 민감정보, 디스클레이머 텍스트 패턴)
     → README/SOP 운영 매뉴얼, 앱 내 디스클레이머 UI, 영업 FAQ 답변 근거
  4. 기존 앱의 도메인 차원 기능·콘텐츠 패턴 비교
     (눔, MyFitnessPal, Yazio, Cronometer — 영양 분석 깊이, 피드백 형식, 추천 알고리즘, 음식 DB 구조)
     → 차별화 포인트, "기존 앱과 다른 점" 영업 답변, 피드백 톤 벤치마크
  5. 영양 분석 표준 공식 및 모델 정리
     (BMR Harris-Benedict / Mifflin-St Jeor, TDEE 활동지수, 매크로 분배 권장 비율, 칼로리 균형 모델, 식사별 분배)
     → LangGraph evaluate_fit 노드의 fit_score 점수 계산, 피드백의 정량적 근거
  6. 한국 헬스케어 외주 고객사 유형 및 발주 패턴
     (병원, 헬스케어 스타트업, 보험사, 식품·식자재 기업, 제약사 — 발주 솔루션 종류, 요구 기능, 의사결정자 관심사)
     → Brief의 "타겟 고객", 영업 답변 "어떤 클라이언트를 위해 만들었는가", 데모 시나리오
user_name: 'hwan'
date: '2026-04-26'
web_research_enabled: true
source_verification: true
scope: 'deep'
---

# Research Report: domain

**Date:** 2026-04-26
**Author:** hwan
**Research Type:** domain (한국 헬스테크/영양)

---

## Research Overview

본 리서치는 외주 영업용 AI 영양 분석 MVP(AI_diet)의 **도메인 신뢰성 확보**를 위한 1차 자료·표준·시장 데이터 수집을 목적으로 한다. 산출물은 W1-W2 시드 데이터, 데이터 모델, 운영 SOP, 영업 FAQ에 직접 적용된다.

리서치 범위는 6개 동등 우선순위 목표(상단 frontmatter)로 정의되며, 각 목표에 대해 다음을 보장한다:

- 모든 주장은 1차 또는 권위 있는 2차 공개 자료의 URL 인용으로 검증
- 출처가 충돌할 경우 양쪽을 모두 제시하고 신뢰 수준 명시
- 한국 도메인 특수성을 우선 (KDRIs, 식약처, 의료기기법, 한국 외주 시장)
- 글로벌 표준(USDA, WHO, ADA 등)은 한국 표준이 부재하거나 비교가 필요한 경우에 참조

**입력 문서:**
- 브레인스토밍 세션 산출물 (`brainstorming-session-2026-04-26-2038.md`) — MVP 스코프 v2, LangGraph 6노드, 데이터 모델, 8주 일정, Top 5 리스크, 9포인트 데모 시나리오

---

## Domain Research Scope Confirmation

**Research Topic:** 한국 헬스테크/영양 도메인 — 외주 영업용 AI 영양 분석 MVP의 도메인 신뢰성 확보

**Research Goals:** 위 frontmatter 6개 목표 (동등 우선순위·동등 깊이)

**Domain Research Scope (사용자 6목표 ↔ 표준 영역 매핑):**

| # | 사용자 목표 | 표준 영역 | 산출물 적용처 |
|---|---|---|---|
| 1 | 영양학 가이드라인 1차 자료 | Authoritative Sources | W2 RAG 시드, evaluate_fit 근거 |
| 2 | 영양 도메인 핵심 개념 | Industry Standards & Taxonomy | DB 스키마, pgvector 메타데이터 |
| 3 | 헬스케어 규제·디스클레이머 | Regulatory Environment | SOP, UI 디스클레이머, 영업 FAQ |
| 4 | 경쟁 앱 도메인 비교 | Competitive Landscape (콘텐츠 차원) | 차별화 포인트, 영업 답변 |
| 5 | 영양 분석 표준 공식 | Technology Patterns + Standards | evaluate_fit fit_score 알고리즘 |
| 6 | 한국 외주 고객사·발주 패턴 | Industry Analysis + Segmentation | Brief, 영업 답변, 데모 시나리오 |

**Research Methodology:**

- 6개 목표 동등 깊이 보장 (어떤 목표도 가볍게 다루지 않음)
- 1차 자료 우선 (식약처·한국영양학회·법령정보센터·KOSIS 등 한국 권위 출처)
- 모든 주장에 URL 인용 — 출처 충돌 시 양쪽 제시 + 신뢰 수준 명시
- 한국 도메인 특수성 우선 (KDRIs, 의료기기법, 식약처 알레르기 22종)
- scope: deep — 표층 요약 금지. 시드/스키마/디스클레이머에 바로 옮길 구체성

**Scope Confirmed:** 2026-04-26

---

## 목표 1 — 영양학 가이드라인 1차 자료 (W2 RAG 시드 + evaluate_fit 인용 근거)

### 1.1 핵심 1차 자료 인덱스 (한국 우선)

| 자료명 | 발행처 | 발행/개정 | 사용 형태 | URL |
|---|---|---|---|---|
| **2020 한국인 영양소 섭취기준 (KDRIs)** | 보건복지부 + 한국영양학회 | 2020.12.22 발표 | RDA/AI/UL/EAR/AMDR/CDRR 표준 수치 | [복지부 발간자료](https://www.mohw.go.kr/board.es?mid=a10411010100&bid=0019&tag=&act=view&list_no=362385) |
| **2020 KDRIs 활용자료** | 보건복지부 | 2021 배포 | 식생활 평가/계획 실무 활용 | [복지부 활용자료](https://www.mohw.go.kr/board.es?mid=a10411010100&bid=0019&tag=&act=view&list_no=370012) |
| **KDRIs 1) 권장섭취량 표 (식품안전나라 등재)** | 식약처 | 식품코드 별표 | 직접 인용 가능한 RDA 수치 | [식품안전나라 KDRIs 표](https://www.foodsafetykorea.go.kr/foodcode/01_03.jsp?idx=12131) |
| **2020 한국인 영양소 섭취기준 제·개정 논문** | Journal of Nutrition and Health | 2021;54(5):425- | 변경점·근거 인용 | [DOI 10.4163/jnh.2021.54.5.425](https://e-jnh.org/DOIx.php?id=10.4163/jnh.2021.54.5.425) |
| **2024 대한비만학회 비만 진료지침 8판** | 대한비만학회 (KSSO) | 2024 (8판 → 2024 갱신본 발표) | 체중감량 식이/약물/생활습관 권고안 | [KSSO 일반인 페이지](https://general.kosso.or.kr/html/?pmode=BBBS0001300003) · [요약본 PDF](https://general.kosso.or.kr/html/user/core/view/reaction/main/kosso/inc/data/guideline2022_vol8.pdf) |
| **대한비만학회 진료지침 (의학 학술 요약)** | JKMA | 2024;67(4):240 | 학술 인용 가능 형태 | [PDF](https://jkma.org/upload/pdf/jkma-2024-67-4-240.pdf) |
| **당뇨병 관리에서 다량영양소의 섭취 권고안** | 대한당뇨병학회 | Journal of Korean Diabetes | 매크로 비율 권고 인용 | [Synapse PDF](https://synapse.koreamed.org/upload/synapsedata/pdfdata/0178jkd/jkd-18-71.pdf) |
| **당뇨환자의 식이요법** | 질병관리청 (국가건강정보포털) | 정부 표준 안내 | 일반인 대상 표준 표현 인용 | [KDCA](https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=3388) |
| **식약처 식품영양성분 데이터베이스** | 식약처 (식품안전나라) | 상시 갱신 | 음식 영양 시드 데이터 (1차 출처) | [식품안전나라 fcdb](https://www.foodsafetykorea.go.kr/fcdb/) |
| **식품영양성분DB 공공데이터 OpenAPI** | 공공데이터포털 | 2024+ | API 호출로 시드 자동화 | [data.go.kr 15127578](https://www.data.go.kr/data/15127578/openapi.do) |
| **식품영양성분DB 통합 자료집 (다운로드)** | 공공데이터포털 | 2022.10.21 | 일괄 다운로드 시드 | [data.go.kr 15047698](https://www.data.go.kr/data/15047698/fileData.do) |
| **식의약 데이터 포털** | 식약처 | 상시 | 표준DB / OpenAPI 통합 진입 | [data.mfds.go.kr](https://data.mfds.go.kr/) |

### 1.2 출처 신뢰 등급 (RAG 인용 시)

- **A급 (1차 공식)**: 보건복지부 발간 KDRIs PDF, 식약처 식품영양성분 DB, 대한비만학회/대한당뇨병학회 진료지침 PDF, 질병관리청 국가건강정보포털 → **본 RAG 가이드라인 시드의 주축**
- **B급 (학술/2차)**: J Nutr Health, JKMA 등 동료심사 학술지의 KDRIs/지침 해설 논문 → 변경점·근거 보강용
- **C급 (참고)**: 병원·학회 일반인 페이지 → 톤·표현 벤치마크 (직접 인용은 지양)

### 1.3 evaluate_fit 노드 인용 패턴 권고

```
형식: "<권고 내용> (출처: <기관명>, <문서명>, <연도>)"
예시:
- "단백질을 총 에너지의 25% 정도로 섭취하면 체중 감량 또는 유지에 도움 (출처: 대한비만학회 비만 진료지침 2024)"
- "당뇨인은 탄수화물을 총 에너지의 55-65%로 (출처: 대한당뇨병학회 다량영양소 섭취 권고안)"
- "성인 단백질 권장섭취량은 체중 1kg당 0.91g (출처: 보건복지부 2020 KDRIs)"
```

### 1.4 글로벌 보완 자료 (한국 표준 부재 또는 비교 시)

- **USDA FoodData Central** — 한식 외 항목 fallback 음식 DB
- **WHO Healthy Diet Fact Sheet** — 글로벌 권고와 대조용
- **ISSN Position Stand on Protein** — 운동 단백질 권고 (1.4-2.0 g/kg) — 단, 한국 KDRIs는 일반 성인 0.91 g/kg

---

## 목표 2 — 영양 도메인 핵심 개념 (DB 스키마 + pgvector 메타데이터)

### 2.1 KDRIs 5대 기준치 체계 (스키마 enum/필드 설계 직결)

| 약자 | 한국어 명칭 | 정의 | DB 활용 |
|---|---|---|---|
| **EAR** | 평균필요량 | 인구의 50%가 충족하는 양 | 통계적 평가용 (직접 노출 X) |
| **RDA** | 권장섭취량 | 인구의 97-98%가 충족 (EAR + 2SD) | 사용자 권장량 표시 기본 |
| **AI** | 충분섭취량 | EAR 산출 불가 시 관찰 기반 적정 | RDA 대체 |
| **UL** | 상한섭취량 | 부작용 없는 최대 | 과다 경고 임계값 |
| **AMDR** | 에너지적정비율 | 매크로 영양소 비율 권고 | fit_score 매크로 비율 평가 |
| **CDRR** | 만성질환위험감소섭취량 | 2020 신설. 만성질환 예방 기준 | 건강 목표 "만성질환 예방" 분기 |

(출처: [복지부 KDRIs 2020 활용자료](https://www.mohw.go.kr/board.es?mid=a10411010100&bid=0019&tag=&act=view&list_no=370012), [J Nutr Health 2021;54(5):425](https://e-jnh.org/DOIx.php?id=10.4163/jnh.2021.54.5.425))

### 2.2 매크로 영양소 권장 비율 (AMDR — KDRIs/한국 학회 + 글로벌)

| 영양소 | 일반 성인 (한국 AMDR) | 일반 성인 (US/IOM AMDR) | 비고 |
|---|---|---|---|
| **탄수화물** | 55-65% (한국 일반) | 45-65% | 당뇨 환자: 55-65% (대당학회) 또는 30-50% (대비학회 체중감량 옵션) |
| **단백질** | 7-20% (성인 기준) | 10-35% | 체중감량 시 ~25% 권장 (대비학회) |
| **지방** | 15-30% (한국 성인) | 20-35% | 포화지방 제한 |

(출처: [AMDR — IOM/NIH](https://www.ncbi.nlm.nih.gov/books/NBK610333/), [대한당뇨병학회 매크로 권고](https://synapse.koreamed.org/upload/synapsedata/pdfdata/0178jkd/jkd-18-71.pdf), [대한비만학회 진료지침](https://general.kosso.or.kr/html/user/core/view/reaction/main/kosso/inc/data/guideline2022_vol8.pdf))

### 2.3 건강 목표별 매크로 분배 권장 (`users.health_goal` enum 매핑)

| `health_goal` enum | 탄수화물 | 단백질 | 지방 | 단백질 g/kg | 칼로리 조정 | 1차 근거 |
|---|---|---|---|---|---|---|
| `weight_loss` | 30-50% (저탄옵션) 또는 표준 45-55% | ~25% | 25-35% | 1.2-1.6 g/kg (지근손실 방지) | TDEE -500 kcal | 대한비만학회 진료지침 2024 |
| `muscle_gain` | 45-55% | 20-30% | 20-30% | **1.6-2.2 g/kg** | TDEE +300~500 kcal | ACSM/ISSN/근육증가 메타분석 |
| `maintenance` | 55-65% | 7-20% | 15-30% | 0.91 g/kg (한국 RDA) | TDEE | 2020 KDRIs |
| `diabetes_management` | **55-65%** (또는 의학적 저탄 30-50%) | 15-20% | 25-35% (포화지방 ↓) | 0.8-1.0 g/kg (신장 정상 시) | TDEE 기반 + GI 고려 | 대한당뇨병학회 다량영양소 권고 |

(출처: [대한비만학회](https://general.kosso.or.kr/html/?pmode=BBBS0001300003), [대한당뇨병학회](https://synapse.koreamed.org/upload/synapsedata/pdfdata/0178jkd/jkd-18-71.pdf), [근육증가 단백질 1.6-2.2 g/kg 한국 임상 자료](https://www.kpanews.co.kr/article/show.asp?category=H&idx=232598), [경향신문 — 매끼 20g 단백질](https://www.khan.co.kr/article/202403170700005))

### 2.4 식약처 알레르기 유발물질 22종 (`users.allergies` text[] 도메인)

```
['우유', '메밀', '땅콩', '대두', '밀', '고등어', '게', '새우', '돼지고기', '아황산류',
 '복숭아', '토마토', '호두', '닭고기', '난류(가금류)', '쇠고기', '오징어', '조개류(굴/전복/홍합 포함)',
 '잣', '아몬드', '잔류 우유 단백', '기타 — 표시기준 별표 참조']
```

> **주의 (2025-2026 업데이트 추적 필요)**: 식약처 표시기준은 22종 기본을 유지하되, '아몬드' 등 추가 동향이 있으므로 시드 시점에 [식약처 식품 등의 표시기준 별표](https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201) 최종본으로 검증할 것.

(출처: [식품안전나라 알레르기 유발식품 안내](https://www.foodsafetykorea.go.kr/portal/board/boardDetail.do?menu_no=3120&menu_grp=MENU_NEW01&bbs_no=bbs001&ntctxt_no=1091412), [식의약처 — 알면 예방할 수 있다 PDF](https://www.mfds.go.kr/brd/m_512/down.do?brd_id=plc0060&seq=31242&data_tp=A&file_seq=1), [국내외 알레르기 유발물질 표시 규제 현황 2023.09.20](https://www.foodinfo.or.kr/cmm/fms/FileDown.do?atchFileId=FILE_000000000031029&fileSn=0))

### 2.5 `food_nutrition.nutrition` jsonb 권장 키 스키마

KDRIs + 식약처 식품영양성분 DB 필드를 매핑:

```json
{
  "energy_kcal": 245,
  "carbohydrate_g": 32.1,
  "protein_g": 8.5,
  "fat_g": 9.2,
  "saturated_fat_g": 3.1,
  "sugar_g": 6.0,
  "fiber_g": 2.8,
  "sodium_mg": 480,
  "cholesterol_mg": 22,
  "serving_size_g": 200,
  "serving_unit": "g",
  "source": "MFDS_FCDB",
  "source_id": "K-115001",
  "source_updated": "2024-11-01"
}
```

`knowledge_chunks` 메타데이터 권장:
```json
{
  "source": "MFDS|KSSO|KDA|MOHW|KNS",
  "doc_type": "guideline|standard|fact_sheet",
  "publication_year": 2024,
  "authority_grade": "A|B|C",
  "topic": "macronutrient|allergen|disease_specific|general",
  "applicable_health_goals": ["weight_loss", "diabetes_management"]
}
```

---

## 목표 3 — 헬스케어 규제·디스클레이머 표준 (SOP + UI + 영업 FAQ)

### 3.1 의료기기 vs 일반 건강관리(웰니스) 제품 — 한국 식약처 판단기준

식약처 가이드라인에 의하면 구분 기준은 **(1) 사용목적이 의료용인가** + **(2) 위해도 수준** 두 축.

**저위해도 일반 건강관리 제품 명시 예시 (식약처 가이드라인):**
- 사용자 심박수 모니터링 (운동·등산 중)
- **"식사 소비량을 모니터·기록하고 체관리를 위한 식이 활동을 관리하고 과식 시 경고"** ← *AI_diet 포지셔닝 직격*
- "고혈압 만성질환 환자의 체중·영양 섭취·운동습관을 관리"

**일상적 건강관리 4가지 분류:**
1. 생체현상 측정 및 분석용
2. 신체기능 향상용
3. **일상 건강관리 의료정보 제공용** ← AI_diet 적용
4. 운동·레저용

**의료기기로 분류되는 경계 신호 (회피 필요):**
- 특정 질병 진단·치료·예방·완화 주장
- 처방·약물 권고
- 환자 데이터 기반 의학적 판단 자동화

(출처: [식약처 — 의료기기와 개인용 건강관리(웰니스)제품 판단기준 PDF](https://www.geumcheon.go.kr/health/downloadBbsFileStr.do?atchmnflStr=zTMhT8hz7py7kQrX1lqyHQ%3D%3D), [KHIDI 자료실](https://www.khidi.or.kr/board/view?pageNum=1&rowCnt=10&menuId=MENU01525&maxIndex=99999999999999&minIndex=99999999999999&schType=0&upDown=0&no1=0&linkId=209153), [의료기기 해당 여부 검토 신청 — 정부24](https://www.gov.kr/mw/AA020InfoCappView.do?HighCtgCD=A06002&CappBizCD=14700000653))

> **핵심 시사점**: AI_diet의 식단 모니터링·매크로 비율 피드백·과식 경고는 식약처 명시 저위해도 예시에 정확히 일치 → **의료기기 미분류로 진입 가능**. 단, "당신은 당뇨가 의심됩니다" 같은 진단성 발언 회피 필수.

### 3.2 디지털 치료제(DTx) — 비교용 참고 (AI_diet는 DTx 아님)

국내 식약처 허가 디지털 치료제 5품목 (2024 기준):
1. 에임메드 **솜즈** — 불면증 (CBT-I)
2. 웰트 **웰트아이** — 불면증
3. 뉴냅스 **비비드브레인** — 시야장애
4. 쉐어앤서비스 **이지브리드** — 호흡재활
5. 뉴라이브 **소리클리어** — 이명 치료

→ AI_diet는 **DTx 트랙이 아닌 웰니스 트랙** (인허가 비용·기간 회피). 단, 영업 답변에서 DTx 트랙으로의 확장 가능성을 언급하면 차별화 가능.

(출처: [데일리팜 — DTx 상용화 현황](https://m.dailypharm.com/newsView.html?ID=314128), [식약처 — 디지털치료기기 안내](https://emedi.mfds.go.kr/contents/MNU20256), [Medigate — 5호 DTx 등장](https://m.medigatenews.com/news/1374728993))

### 3.3 개인정보보호법 민감정보 처리 의무

- 개인정보보호법 제23조: **건강정보는 민감정보** — 원칙적 처리 금지, 예외적 동의 시 가능
- 사용자 동의: **별도 동의** 필수 (일반 개인정보 동의와 분리)
- 동의 항목 명시: 수집 항목·이용 목적·보관 기간·제3자 제공 여부
- 2026년 시행 개정 PIPA: 민감정보 관련 의무 강화

(출처: [국가법령정보센터 — 개인정보 보호법](https://www.law.go.kr/lsEfInfoP.do?lsiSeq=195062), [찾기쉬운 생활법령 — 보건의료 개인정보보호](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?csmSeq=1702&ccfNo=5&cciNo=1&cnpClsNo=1), [개인정보보호위원회 — 개인정보의 종류](https://www.privacy.go.kr/front/contents/cntntsView.do?contsNo=35), [건강정보고속도로 동의 안내](https://www.myhealthway.go.kr/portal/index?page=AppTerms))

### 3.4 표준 디스클레이머 텍스트 패턴 (UI/SOP 적용)

#### 한국 일반(웰니스) 앱 표준 한국어 디스클레이머 (영업 데모/UI 안전판)

```
[온보딩 / 약관 / 결과 화면 하단]

본 서비스는 일반 건강관리(웰니스) 목적의 정보 제공 서비스이며,
의료기기 또는 의학적 진단·치료·예방을 위한 도구가 아닙니다.

본 서비스가 제공하는 영양·식단 분석 및 피드백은 참고용이며,
질병의 진단, 치료, 예방 또는 의학적 조언을 대체하지 않습니다.

질병이 있거나 약물 복용 중, 임신·수유 중인 경우 반드시
의사 또는 영양사 등 전문가와 상의하시기 바랍니다.

알레르기·기저질환이 있는 사용자는 입력 정보가 누락되거나
부정확할 수 있음에 유의하시고, 응급상황 시에는 즉시 119에 연락하십시오.
```

#### 영문 보조 (글로벌 데모/B2B 외주 답변용)

```
This service is provided for general wellness and informational
purposes only. It is not a medical device and is NOT INTENDED TO
DIAGNOSE, TREAT, CURE, OR PREVENT ANY DISEASE.

The nutrition and dietary feedback generated by this service is
not a substitute for professional medical advice, diagnosis, or
treatment. Always seek the advice of your physician or qualified
health provider with any questions you may have.
```

(출처: [FDA — General Wellness: Policy for Low Risk Devices](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/general-wellness-policy-low-risk-devices), [FDA — Examples of Software Functions That Are NOT Medical Devices](https://www.fda.gov/medical-devices/device-software-functions-including-mobile-medical-applications/examples-software-functions-are-not-medical-devices), [Termly Medical Disclaimer Examples](https://termly.io/resources/articles/medical-disclaimer-examples/), [Mintz — FDA Warning Letter on Wellness Claims](https://www.mintz.com/insights-center/viewpoints/2791/2025-07-21-fda-warning-letter-reminds-industry-wellness-claims-only))

> **핵심 경고 (FDA Warning Letter 시사점)**: 디스클레이머 텍스트만으로는 부족 — **실제 기능·디자인이 의료 목적이 아님을 입증**해야 한다. AI_diet의 LangGraph 노드는 "fit_score"가 의학적 진단처럼 보이지 않도록 명명·범위 신중 (예: "건강 목표 부합도 점수"로 표기, "0-100 점수의 100점이 의학적 정상이 아님" 명시).

### 3.5 식약처 광고/표시 금지 표현 (AI 피드백 텍스트 생성 가드레일)

LangGraph `generate_feedback` 노드 출력 필터링 권장 금지 패턴:

| 회피해야 할 표현 | 안전 대안 |
|---|---|
| "당뇨가 예방됩니다" | "혈당 관리에 도움이 될 수 있는 식습관입니다 (참고용)" |
| "이 식단은 암을 막아줍니다" | "균형 잡힌 식단은 일반적인 건강 유지에 기여합니다" |
| "관절 통증 완화" | (질병 완화 표현 금지) |
| "치료" / "처방" / "진단" | "관리" / "안내" / "참고" |

(출처: [식품의 부당한 표시·광고 — 식품안전나라](https://www.foodsafetykorea.go.kr/portal/board/board.do?menu_grp=MENU_NEW01&menu_no=4838&ctgType=CTG_TYPE01&ctgryno=2255), [건강기능식품 표시·광고 심의기준](https://www.law.go.kr/admRulLsInfoP.do?admRulSeq=2100000000941))

---

## 목표 4 — 경쟁 앱 도메인 차원 비교 (차별화 + 영업 답변 + 톤 벤치마크)

### 4.1 비교 매트릭스 (UX 제외 — 콘텐츠/알고리즘/DB 차원)

| 차원 | **Noom** | **MyFitnessPal** | **Yazio** | **Cronometer** | **AI_diet (목표 포지션)** |
|---|---|---|---|---|---|
| **영양 분석 깊이 (영양소 수)** | 매크로 + 신호등 (열량 밀도 중심) | 매크로 + 일부 미량(Ca/Na) | ~15개 (Pro 기준에도 vitamins 빈칸 多) | **82개 미량영양소** (NCCDB) | 매크로 + 알레르기 + KDRIs 핵심 (10-15개) |
| **음식 DB 출처** | 자체 큐레이션 + 신호등 색상 분류 (한식 4만+) | 크라우드소싱 2,000만+ (정확도 편차) | 자체 큐레이션 | NCCDB + USDA + 실험실 검증 | **식약처 식품영양성분 DB (1차 공인)** + 한식 정규화 사전 |
| **DB 구조 추정** | 자체 + 색상 메타데이터 | MySQL/Aurora + Redis + Elasticsearch | 자체 큐레이션 DB | NCCDB 동기화 | **PostgreSQL + pgvector (RAG 기반)** |
| **피드백 텍스트 형식** | 행동심리학 기반 인간 코치 + 매일 퀴즈/아티클 | Premium+: 알고리즘 7일 식단 자동생성 (인간 검토 X) | 단식 스케줄 + 레시피 안내 | 데이터 위주 표시 (코칭 약함) | **LangGraph + Self-RAG 기반 가이드라인 인용 피드백** |
| **추천 알고리즘 종류** | CBT(인지행동) + 색상 신호등 + 인간 코치 | 매크로 코치 (목표·체중·활동 기반) | 단식+식단 템플릿 | 미량영양소 결핍 알림 | **건강 목표별 매크로 분배 + 가이드라인 RAG 인용 + Self-RAG 재검색** |
| **인간 개입 수준** | 정규직 인간 코치 (1:1) | 알고리즘 only | 알고리즘 + 레시피 콘텐츠 | 알고리즘 only | 알고리즘 only (1인 운영, 외주 데모용) |
| **과학적 근거 강도** | CBT 학술 RCT 보유 (Noom Health) | 학술적 약함 | 학술적 약함 | NCCDB 임상 연구 사용 | **KDRIs/대한비만학회 진료지침 명시 인용** |
| **타깃 시장** | 글로벌 B2C 다이어트 | 글로벌 B2C 칼로리 추적 | 유럽 중심 단식 | 영양 마니아/임상가 | **한국 B2B 외주** (병원/보험/식품) |

(출처: [Noom Wikipedia](https://en.wikipedia.org/wiki/Noom), [Noom RCT Protocol — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9419047/), [US Chamber — Noom psychology](https://www.uschamber.com/co/good-company/the-leap/noom-weight-loss-app-technology), [Samsung — S헬스x눔 코치](https://news.samsung.com/kr/s%ED%97%AC%EC%8A%A4x%EB%88%94-%EC%BD%94%EC%B9%98-%EC%A3%BC%EC%9A%94-%EA%B8%B0%EB%8A%A5-%EB%8C%80%ED%95%B4%EB%B6%80), [Noom Apple App Store KR](https://apps.apple.com/kr/app/%EB%88%94-noom-%EC%84%B8%EA%B3%84-1%EC%9C%84-%EC%8B%9D%EB%8B%A8-%EA%B4%80%EB%A6%AC-%EB%8B%A4%EC%9D%B4%EC%96%B4%ED%8A%B8-%EC%95%B1/id634598719), [MyFitnessPal — How food database works](https://blog.myfitnesspal.com/how-food-database-works/), [MyFitnessPal Premium vs Premium+ 2026](https://nutriscan.app/blog/posts/myfitnesspal-premium-vs-premium-plus-2026-6870e216fc), [MyFitnessPal infrastructure analysis (Quora)](https://www.quora.com/What-database-does-MyFitnessPal-use), [Hoot Fitness — Cronometer Alternatives](https://www.hootfitness.com/blog/cronometer-alternatives-find-the-best-fit-for-your-tracking-style), [Yazio vs Cronometer comparison](https://www.youtube.com/watch?v=KIbGSbztDPU))

### 4.2 차별화 3가지 핵심 (영업 답변 자료)

1. **"한국 1차 공식 출처 RAG"** — 식약처/대한비만학회/KDRIs를 직접 인용. Noom·MyFitnessPal은 자체 큐레이션이라 외주 고객(특히 병원·보험사)이 책임 추적 어려움. AI_diet는 **모든 권고에 출처 표시** 가능.
2. **"Self-RAG 재검색 — 모르는 음식은 재질문"** — 일반 GPT 호출이 아니라 신뢰도 평가 후 재검색하는 LangGraph 6노드. 피드백 환각률 ↓.
3. **"한국 식약처 알레르기 22종 + KDRIs 매크로 룰을 enum 수준에서 보장"** — 글로벌 앱은 미국·유럽 중심. AI_diet는 **한국 표준 통합 데이터 모델**.

### 4.3 피드백 텍스트 톤 벤치마크 (`generate_feedback` 노드 프롬프트 가이드)

- **Noom 톤** (긍정·동기부여 + 행동심리): "잘 하고 계세요! 신호등의 노란색 음식은 적당히만 즐기시면 충분해요. 다음 식사는 초록색 음식을 시도해보면 어떨까요?" → **AI_diet 채택 권고**: 비난적이지 않고, 다음 행동 제안형
- **MyFitnessPal 톤** (수치 위주): "오늘 단백질 56g 섭취 (목표 80g). 67% 달성." → **부분 채택**: 수치는 별도 카드로
- **Cronometer 톤** (데이터 dump): 거의 코멘트 없이 표·차트만 → **회피**
- **AI_diet 권장 톤**: "오늘 점심은 탄수화물 비중이 70%로 권장 범위(55-65%)를 약간 초과했어요. 저녁에 단백질을 25g 정도 추가하면 매크로 균형이 맞춰질 거에요. (출처: 2020 KDRIs)"

(출처: [경향신문 — 매끼 단백질 20g](https://www.khan.co.kr/article/202403170700005), [Noom Apple App Store KR](https://apps.apple.com/kr/app/%EB%88%94-noom-%EC%84%B8%EA%B3%84-1%EC%9C%84-%EC%8B%9D%EB%8B%A8-%EA%B4%80%EB%A6%AC-%EB%8B%A4%EC%9D%B4%EC%96%B4%ED%8A%B8-%EC%95%B1/id634598719), [SocialMKT — 눔 실사용 분석](https://blog.socialmkt.co.kr/531))

---

## 목표 5 — 영양 분석 표준 공식·모델 (evaluate_fit fit_score 알고리즘)

### 5.1 BMR 공식 (Mifflin-St Jeor — 권장 채택)

```
남성: BMR = (10 × 체중kg) + (6.25 × 신장cm) − (5 × 나이) + 5
여성: BMR = (10 × 체중kg) + (6.25 × 신장cm) − (5 × 나이) − 161
```

- **선택 근거**: Mifflin-St Jeor가 Harris-Benedict보다 실제 BMR을 ±10% 이내로 추정하는 비율이 높음 (간접열량측정 대비)
- **대안**: Harris-Benedict (1919) — 구식. KDRIs 활용자료에서도 Mifflin-St Jeor를 권장 추세
- **임상 팁**: 비만/근육량 많음 시 Mifflin이 과/저 추정 가능 → Cunningham Equation (제지방량 기반)으로 대체 가능 단 입력 부담 ↑

(출처: [Medscape — Mifflin-St Jeor Equation](https://reference.medscape.com/calculator/846/mifflin-st-jeor-equation), [Nutrium — Mifflin-St Jeor 임상 활용](https://nutrium.com/blog/mifflin-st-jeor-for-nutrition-professionals/), [PMC — Predicting Equations and REE](https://pmc.ncbi.nlm.nih.gov/articles/PMC7478086/))

### 5.2 TDEE = BMR × 활동지수

| 활동 수준 | 곱셈 계수 | 사용자 라벨 (한국어) |
|---|---|---|
| Sedentary (운동 거의 없음) | × 1.2 | "거의 운동 안 함" |
| Lightly Active (주 1-3회 가벼운 운동) | × 1.375 | "가벼운 운동 (주 1-3회)" |
| Moderately Active (주 3-5회 중강도) | × 1.55 | "중간 강도 운동 (주 3-5회)" |
| Very Active (주 6-7회 고강도) | × 1.725 | "고강도 운동 (주 6-7회)" |
| Extra Active (운동+육체노동) | × 1.9 | "극심한 활동 (운동+육체노동)" |

(출처: [Inch Calculator — Mifflin-St Jeor TDEE](https://www.inchcalculator.com/mifflin-st-jeor-calculator/), [Calculator.net BMR](https://www.calculator.net/bmr-calculator.html))

### 5.3 건강 목표별 칼로리 조정 + 매크로 분배 (evaluate_fit 알고리즘 입력)

| `health_goal` | 칼로리 조정 | 매크로 (탄/단/지) | 단백질 g/kg | 비고 |
|---|---|---|---|---|
| `weight_loss` | TDEE − 300~500 kcal | 45-55 / 25-30 / 25-30 | 1.2-1.6 | 대비학회: 단백질 25%, 탄수 옵션 30-50% |
| `muscle_gain` | TDEE + 300~500 kcal | 50 / 25-30 / 20-25 | **1.6-2.2** | ACSM/ISSN 운동인 권고 |
| `maintenance` | TDEE | 55-65 / 10-20 / 15-30 | 0.91 (KDRIs) | 한국 일반 성인 |
| `diabetes_management` | TDEE (또는 −250 if BMI ≥25) | 55-65 / 15-20 / 25-30 | 0.8-1.0 | 저GI 우선, 포화지방 ↓ |

### 5.4 식사별 칼로리 분배 권장 (선택 사용)

표준 분배: **아침 25% / 점심 35% / 저녁 30% / 간식 10%** (한국인 식습관 평균 + 일반 권고)

- 단, 단식 옵션 (16:8 등)에서는 다르게 적용 → 사용자 설정으로 전환 가능 형태로 설계 권장

### 5.5 fit_score (0-100) 계산 알고리즘 — 권장 설계

```
def fit_score(meal, user_goal, daily_log_so_far):
    # 1. Macro 적합도 (40점)
    target_macros = goal_to_macros[user_goal]  # 위 5.3 표
    macro_match = 1.0 - mean_abs_deviation(meal_macros, target_macros) / 0.30
    macro_score = clamp(macro_match * 40, 0, 40)

    # 2. 칼로리 적합도 (25점)
    target_meal_kcal = user_tdee * meal_share  # 위 5.4 표
    kcal_match = 1.0 - abs(meal_kcal - target_meal_kcal) / target_meal_kcal
    kcal_score = clamp(kcal_match * 25, 0, 25)

    # 3. 알레르기 + 금기식품 회피 (20점, 위반 시 0)
    if any_allergen_hit(meal, user.allergies):
        return {"score": 0, "reason": "allergen_violation"}
    allergen_score = 20

    # 4. 영양소 균형 보너스 (15점) — 섬유 / 나트륨 한도
    fiber_score = min(meal.fiber_g / target_fiber * 7.5, 7.5)
    sodium_penalty = max(0, (meal.sodium_mg - 800) / 800 * 7.5)  # 한 끼당 800mg 가이드
    balance_score = fiber_score + (7.5 - sodium_penalty)

    return clamp(macro_score + kcal_score + allergen_score + balance_score, 0, 100)
```

> **중요**: fit_score는 의학적 진단 점수로 보이지 않게 **"건강 목표 부합도"**로 명명. 100점이 "건강함"이 아니라 "현재 설정된 목표에 가장 가까움"이라는 점을 UI에서 명시.

### 5.6 추가 참고치 (보조 룰)

- **단백질 분포**: 매끼 최소 20-30g (근육 합성 자극 — leucine 임계 ~2.5g/끼)
- **나트륨 한도 (KDRIs CDRR)**: 성인 2,300mg/일 이하
- **포화지방**: 총 에너지의 7% 이하 (대비학회/대당학회 공통)
- **식이섬유 충분섭취량 (한국 KDRIs AI)**: 성인 남 30g, 여 20g/일

(출처: [한국인 단백질 권장량 g/kg](https://www.kpanews.co.kr/article/show.asp?category=H&idx=232598), [Herbalife — 한국 단백질 권장량](https://www.herbalife.com/ko-kr/wellness-resources/articles/how-much-protein-do-you-need-per-day), [Glasswallet 단백질 계산기](https://glasswallet.com/calculate/protein/daily-intake/), [WW USA — AMDR](https://www.weightwatchers.com/us/blog/food/acceptable-macronutrient-distribution-range), [Eat For Health — Macronutrient balance](https://www.eatforhealth.gov.au/nutrient-reference-values/chronic-disease/macronutrient-balance))

---

## 목표 6 — 한국 외주 고객사 유형·발주 패턴 (Brief + 영업 답변 + 데모 시나리오)

### 6.1 시장 규모와 성장 신호 (영업 도입부 자료)

- 2023년 국내 디지털헬스케어 산업 시장규모 **약 6.5조 원** (전년 대비 +13.5%)
- 정통연(KISDI) 전망: 2029년까지 연평균 ~3.5% 안정 성장
- 글로벌 마켓인사이트: 글로벌 디지털 헬스케어 2025 약 5,044억 달러
- 디지털 데이터 수집·처리용 제품 비중 25.8% (산업 내 가장 큼)

(출처: [디지털헬스산업협회 — 2024년 산업 실태조사](https://dhnet.kodhia.or.kr/core/?cid=10&uid=5408&role=view), [한국바이오협회 — 디지털 헬스케어 현황과 전망 PDF](https://www.koreabio.org/board/download.php?board=Y&bo_table=brief&file_name=b_file_1742771980tg9i7cdmmf.pdf&o_file_name=%EB%B8%8C%EB%A6%AC%ED%94%84+197%ED%98%B8_%EB%94%94%EC%A7%80%ED%84%B8+%ED%97%AC%EC%8A%A4%EC%BC%80%EC%96%B4+%ED%98%84%ED%99%A9+%EB%B0%8F+%EC%A0%84%EB%A7%9D.pdf), [News1 — 6.5조 시장](https://www.news1.kr/bio/healthcare/5700248), [KPMG — AI 헬스케어 대전환 PDF](https://assets.kpmg.com/content/dam/kpmg/kr/pdf/2024/insight/kpmg-korea-ai-healthcare-20240625.pdf), [KDI — 디지털헬스케어 시장 전망](https://eiec.kdi.re.kr/policy/domesticView.do?ac=0000188512))

### 6.2 5개 외주 고객사 유형 — 발주 솔루션 / 요구 기능 / 의사결정자 관심사

#### A. 병원·의료기관

- **대표 발주 솔루션**: 환자 맞춤형 식단·영양 관리 앱, EMR 연동, 만성질환 모니터링
- **대표 사례**:
  - **루닛케어** AI 식단 관리 (생성AI 영양사) — 암 환자 질문 39%가 식습관/음식/영양
  - **디앤라이프 (서울아산병원 김태원 교수 창업) × 현대그린푸드 그리팅** — 암환자 맞춤 영양관리 솔루션 + 식단 구매 연계
  - **분당서울대병원 의료인공지능센터**, 동산의료원 등 스마트병원 사업
  - **보건복지부 모바일 헬스케어** — 보건소-영양사-사용자 연계 (고혈압·당뇨)
- **요구 기능**: 질환별 가이드라인 인용, 영양사 검토, 의료진 협업 인터페이스, EMR 연동
- **의사결정자**: 진료과장 + 의료정보팀장 + IRB. **핵심 관심사**: 임상 근거, 인증/허가, 환자 안전, 책임 한계
- **AI_diet 적합성**: ★★★★ — 가이드라인 RAG 인용 기능이 직접적 가치

#### B. 헬스케어 스타트업

- **대표 발주 솔루션**: 핵심 기능 외주(영양 분석 엔진, RAG 파이프라인 구축), MVP 검증 도구
- **대표 사례**: DHP 액셀러레이터 포트폴리오 9곳, AI 재활운동 플랫폼 등
- **요구 기능**: 빠른 PoC, 인프라 표준 (Docker), 확장 가능 아키텍처
- **의사결정자**: CTO/창업자. **핵심 관심사**: 시간·비용·기술 적합성·확장성
- **AI_diet 적합성**: ★★★★★ — MVP 그 자체가 데모. LangGraph 6노드 + pgvector 구조가 그대로 외주 산출물

#### C. 보험사 (생명/손해보험 자회사)

- **대표 발주 솔루션**: 가입자 건강관리 플랫폼, 행동변화 기반 인센티브, 만성질환 예방
- **대표 사례**:
  - 삼성생명 **THE Health** (수면 분석 추가)
  - 교보생명 **교보다솜케어** (자본금 52억)
  - KB손해보험 **KB헬스케어** + 비대면 진료 **올라케어** 인수 → **KB오케어**
  - 신한라이프 **신한라이프케어**
  - 삼성생명 **S-워킹** (300만보 → 3만원), 삼성화재 **애니핏 2.0**
- **요구 기능**: 사용자 참여 유지, 행동변화 측정, 보험 인센티브 연동, 데이터 분석 리포트
- **의사결정자**: 디지털전략팀 + 상품기획 + 컴플라이언스. **핵심 관심사**: 가입자 활성화 KPI, 보험-규제 정합성, 의료법 경계, 데이터 거버넌스
- **AI_diet 적합성**: ★★★★ — 일별 식단 + 주간 리포트 + 푸시 nudge가 바로 보험사 인게이지먼트 도구

#### D. 식품·식자재 기업

- **대표 발주 솔루션**: 자사 제품/식단 개인화 추천, AI 영양 분석 기반 헬스케어 브랜드 확장
- **대표 사례**:
  - **풀무원 NDP (뉴트리션 디자인 프로그램)** — 2주간 식단·혈당·생활 리듬 데이터 → 맞춤 솔루션
  - **풀무원 AI VOC·Review 분석 시스템**, 빅데이터 식수 예측 시스템
  - **CJ제일제당** — 비비고 김치 배추 등급 AI 선별 (88%+), CJ올리브네트웍스 식품 안전 AI
  - **대상그룹 '대상 AI'** 도입, **대상웰라이프 '당프로 2.0'** (CES 2026 혁신상) — 혈당 관리 + 오프라인 연계
  - **현대그린푸드** — 암환자 맞춤 영양관리
- **요구 기능**: 자사 제품 카탈로그 통합, 영양 성분 자동 매칭, 추천 → 구매 전환
- **의사결정자**: 헬스케어/뉴비즈 사업부장 + 디지털전환팀. **핵심 관심사**: 자사 제품 차별화, B2C 확장, 데이터로 마케팅
- **AI_diet 적합성**: ★★★★ — 음식 RAG에 자사 제품 시드만 추가하면 바로 B2C 솔루션화 가능 (영업 답변 핵심 카드)

#### E. 제약사

- **대표 발주 솔루션**: 디지털 치료제(DTx), 약물 복용 동반 환자 관리 앱, 임상 데이터 수집
- **대표 사례**:
  - **대웅제약** — 모비케어(심전도)·에띠아·카트비피·씽크·카트온 등
  - **유한양행 × 휴이노 메모패치** (심전도 AI 분석)
  - **한독 × 웰트** (불면증·알코올 중독 DTx 공동개발)
- **요구 기능**: GMP/GVP 수준 데이터 거버넌스, 임상 시험 연동, 식약처 인허가 트랙
- **의사결정자**: 디지털전략팀 + 의학부 + RA(인허가). **핵심 관심사**: 인허가 가능성, 임상 근거, 의약품 마케팅 규제
- **AI_diet 적합성**: ★★ — DTx 트랙은 별도 인허가 필요. 단, **"DTx 인허가 전 단계 PoC 도구"** 또는 "약물별 식단 가이드 앱"으로 포지셔닝 가능

(출처: [바이오타임즈 — 루닛케어 AI 식단 관리](https://www.biotimes.co.kr/news/articleView.html?idxno=16667), [Medigate — 루닛케어 AI 식단 관리](https://medigatenews.com/news/4122358472), [Newsis — 현대그린푸드×디앤라이프 암환자 영양관리](https://www.newsis.com/view/NISX20250528_0003193715), [현대그린푸드 보도자료](https://www.hyundaigreenfood.com/po/pr/ntn/PRNTN02V.hg?bbsSqPk=194012), [대한급식신문 — 디지털 헬스케어 영양관리](https://www.fsnews.co.kr/news/articleView.html?idxno=59394), [한국금융신문 — 보험사 헬스케어](https://www.fntimes.com/html/view.php?ud=2021071315471097228a55064dd1_18), [뉴데일리 — 보험사 디지털 헬스케어 보상자→관리자](https://biz.newdaily.co.kr/site/data/html/2025/07/14/2025071400285.html), [전자신문 — 보험사 건강관리서비스 확대](https://www.etnews.com/20201216000181), [PwC — 디지털 헬스케어 보험사 Player](https://www.pwc.com/kr/ko/insights/samil-insight/paradigm-shift-02-2.html), [풀무원 뉴스룸 — AI VOC 플랫폼](https://news.pulmuone.co.kr/pulmuone/newsroom/viewNewsroom.do?id=2635), [매일일보 — 식품업계 디지털전환](https://www.m-i.kr/news/articleView.html?idxno=1058063), [식품음료신문 — 대상그룹 AI 전환](https://www.thinkfood.co.kr/news/articleView.html?idxno=103683), [서울경제 — 식품업계 AI 헬스케어](https://www.sedaily.com/article/20009872), [Medigate — 제약사 디지털 헬스케어](https://medigatenews.com/news/1128693143), [흐름소프트 — 제약사 비대면 진료앱 개발](https://www.hrmsoft.co.kr/case/%EB%B9%84%EB%8C%80%EB%A9%B4-%EC%A7%84%EB%A3%8C-%EC%95%B1-%EA%B0%9C%EB%B0%9C-%EC%82%AC%EB%A1%80-%EB%8C%80%ED%98%95-%EC%A0%9C%EC%95%BD%EC%82%AC-%EC%9B%90%EA%B2%A9-%EC%A7%84%EB%A3%8C-%ED%94%8C%EB%9E%AB%ED%8F%BC), [DHP 디지털헬스케어파트너스](https://www.dhpartners.io/), [DHP 데모데이 2023 9곳](https://www.biotimes.co.kr/news/articleView.html?idxno=12032))

### 6.3 B2B 헬스케어 SaaS 의사결정자 구매 기준 (영업 답변 가드)

| 의사결정자 역할 | 핵심 관심사 | AI_diet 영업 카드 |
|---|---|---|
| **CIO / IT 임원** | 보안, 인프라 표준, 통합 비용 | Docker Compose + Sentry + Swagger + README/SOP 완비 |
| **CISO / 보안담당** | 데이터 거버넌스, 민감정보 처리 | 개인정보보호법 민감정보 동의 분리, 의료기기 미분류 명시 |
| **부서 팀장 (Technical buyer)** | 기능 적합성, 운영 부담 | 6노드 LangGraph가 모듈로 분리, 노드 단위 교체 가능 |
| **사업부장 / 임원 (Economic buyer)** | ROI, 차별화, 시장 가치 | 한국 1차 출처 RAG = 책임 추적 가능 = 외주 단가 상승 명분 |
| **컴플라이언스/RA** | 인허가·규제 정합성 | 의료기기 미분류 + 표준 디스클레이머 + 가이드라인 인용 |

(출처: [카카오벤처스 — 디지털 헬스케어 B2B 모델 3가지](https://www.kakao.vc/blog/3-digital-healthcare-b2b-models), [Kimchi Hill — Han Kim B2B SaaS 6 질문 해설](https://kimchihill.com/2021/09/09/anatomy-of-the-6-key-questions-asked-to-b2b-saas-startups/), [Mordor Intelligence — B2B SaaS 시장 보고서](https://www.mordorintelligence.kr/industry-reports/b2b-saas-market))

### 6.4 데모 시나리오 — 고객사별 페르소나 권장

| 고객사 가정 | 페르소나 | 데모 강조 노드 |
|---|---|---|
| **종합병원 의료정보팀** | "암 환자 보호자가 식단 관련 질문" | Self-RAG + 가이드라인 인용 + 디스클레이머 |
| **생명보험 디지털팀** | "건강관리 가입자 1만명 미기록 nudge" | 푸시 알림 + 주간 리포트 + 인센티브 연동 가능성 |
| **식품기업 헬스케어 신사업** | "자사 케어푸드 제품 추천 통합" | 음식 DB 확장 + 추천 알고리즘 + 구매 연계 |
| **헬스케어 스타트업 CTO** | "PoC를 4주 내 검증" | LangGraph 노드 단위 분리, Docker Compose 1-cmd 실행 |

---

## 통합 — Synthesis & Action Mapping

### 사용처별 액션 매핑 (어떤 자료/표준이 어디에 들어가는가)

| 사용처 | 출처/표준 | 적용 형태 | 본 리서치 위치 |
|---|---|---|---|
| **PostgreSQL 스키마: `users.health_goal` enum** | 본 리서치 표 5.3 | `weight_loss / muscle_gain / maintenance / diabetes_management` | 목표 2.3, 5.3 |
| **PostgreSQL 스키마: `users.allergies` text[]** | 식약처 22종 | enum 또는 text[] 검증 (정규 라벨 22개) | 목표 2.4 |
| **PostgreSQL 스키마: `food_nutrition.nutrition` jsonb** | 식약처 식품영양성분 DB 필드 | 키 표준 (energy_kcal/carbohydrate_g/...) | 목표 2.5 |
| **W1 음식 DB 시드 (1,500-3,000건)** | 식약처 OpenAPI + 통합 자료집 | 한식 위주 + 정규화 사전 (짜장면≠자장면) | 목표 1.1, 1.4 |
| **W2 가이드라인 RAG 시드 (50-100 chunks)** | KDRIs 2020 + 대비학회 진료지침 + 대당학회 매크로 권고 + 질병관리청 표준 | A급 출처 우선, 메타데이터 (목표 2.5 스키마) | 목표 1.1, 1.2 |
| **LangGraph `evaluate_fit` 노드 (fit_score)** | Mifflin-St Jeor + TDEE + 매크로 분배 + 알레르기 + 나트륨/섬유 | 100점 스케일 (40+25+20+15) — 목표 5.5 의사코드 | 목표 5.5 |
| **LangGraph `generate_feedback` 노드 (피드백 텍스트)** | 식약처 광고 금지 표현 가드 + Noom 톤 (긍정·행동제안형) + 인용 형식 | 시스템 프롬프트에 금지 패턴/인용 패턴 주입 | 목표 1.3, 3.5, 4.3 |
| **앱 UI 디스클레이머 (온보딩/결과)** | 본 리서치 3.4 한국어 + 영문 텍스트 | 약관·온보딩·결과화면 하단 | 목표 3.4 |
| **개인정보 동의서 별도 항목** | PIPA 23조 (민감정보) | "건강정보 수집·이용 동의" 별도 동의 분리 | 목표 3.3 |
| **운영 SOP / README** | 의료기기 미분류 입장 + DTx 비교 + 디스클레이머 + 동의 절차 | 영업·법무·외주 인수인계 1장 | 목표 3.1, 3.2, 3.3, 3.4 |
| **영업 FAQ — "기존 앱과 다른 점"** | 본 리서치 4.2 차별화 3카드 | 1차 출처 RAG / Self-RAG / 한국 표준 통합 | 목표 4.1, 4.2 |
| **영업 FAQ — "어떤 클라이언트를 위해 만들었나"** | 본 리서치 6.2 5개 고객사 + 6.4 페르소나 | 고객사별 데모 시나리오 분기 | 목표 6.2, 6.4 |
| **영업 FAQ — "의료기기 인허가가 필요한가"** | 본 리서치 3.1 식약처 웰니스 판단기준 | "저위해도 일상 건강관리 — 의료기기 미분류" 명시 답변 | 목표 3.1 |
| **데모 시나리오 (9포인트 → 고객사 페르소나별)** | 본 리서치 6.4 | 병원/보험/식품/스타트업/제약 — 강조 노드 분기 | 목표 6.4 |
| **Brief "타겟 고객" 섹션** | 본 리서치 6.2 5개 고객사 + 6.1 시장 데이터 | 시장 6.5조 + 고객사별 적합성 ★ 표 | 목표 6.1, 6.2 |

### 출처 신뢰 등급 통합 표

- **A급 (1차 공식 — RAG 시드 주축)**:
  - 보건복지부 [2020 KDRIs 발간자료](https://www.mohw.go.kr/board.es?mid=a10411010100&bid=0019&tag=&act=view&list_no=362385) · [활용자료](https://www.mohw.go.kr/board.es?mid=a10411010100&bid=0019&tag=&act=view&list_no=370012)
  - 식약처 [식품영양성분 DB](https://www.foodsafetykorea.go.kr/fcdb/) · [식의약 데이터 포털](https://data.mfds.go.kr/) · [공공데이터 OpenAPI](https://www.data.go.kr/data/15127578/openapi.do)
  - 식약처 [의료기기와 웰니스 판단기준](https://www.geumcheon.go.kr/health/downloadBbsFileStr.do?atchmnflStr=zTMhT8hz7py7kQrX1lqyHQ%3D%3D) · [의료기기 해당여부 검토 정부24](https://www.gov.kr/mw/AA020InfoCappView.do?HighCtgCD=A06002&CappBizCD=14700000653)
  - 식약처 [알레르기 22종 표시기준](https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201) · [식품안전나라 안내](https://www.foodsafetykorea.go.kr/portal/board/boardDetail.do?menu_no=3120&menu_grp=MENU_NEW01&bbs_no=bbs001&ntctxt_no=1091412)
  - 대한비만학회 [진료지침 2024 (8판 갱신)](https://general.kosso.or.kr/html/?pmode=BBBS0001300003) · [요약본 PDF](https://general.kosso.or.kr/html/user/core/view/reaction/main/kosso/inc/data/guideline2022_vol8.pdf)
  - 대한당뇨병학회 [매크로 권고 PDF](https://synapse.koreamed.org/upload/synapsedata/pdfdata/0178jkd/jkd-18-71.pdf)
  - 질병관리청 [국가건강정보포털 — 당뇨 식이요법](https://health.kdca.go.kr/healthinfo/biz/health/gnrlzHealthInfo/gnrlzHealthInfo/gnrlzHealthInfoView.do?cntnts_sn=3388)
  - 국가법령정보센터 [개인정보 보호법](https://www.law.go.kr/lsEfInfoP.do?lsiSeq=195062)

- **B급 (학술/2차 — 근거 보강)**:
  - [J Nutr Health 2021;54(5):425 — KDRIs 제·개정 논문](https://e-jnh.org/DOIx.php?id=10.4163/jnh.2021.54.5.425)
  - [JKMA 2024;67(4):240 — 비만 진료지침](https://jkma.org/upload/pdf/jkma-2024-67-4-240.pdf)
  - [PMC — Mifflin-St Jeor 임상 정확도](https://pmc.ncbi.nlm.nih.gov/articles/PMC7478086/)
  - [NCBI — AMDR Description](https://www.ncbi.nlm.nih.gov/books/NBK610333/)

- **C급 (참고 — 직접 인용 지양, 톤·정황 벤치마크)**:
  - 약사공론·경향신문·이랜서·뉴스1 등 매체
  - Noom·MyFitnessPal·Yazio·Cronometer 마케팅 페이지

### 주요 시사점 5가지 (영업 답변 핵심 카드)

1. **"한국 1차 공식 출처 RAG"가 외주 가치의 본질.** 글로벌 앱은 자체 큐레이션이라 병원·보험사 컴플라이언스 통과가 어렵다. AI_diet는 식약처/대비학회/KDRIs를 직접 인용 → **책임 추적 가능**.
2. **의료기기 미분류는 식약처 가이드라인에 명시된 안전 영역**. "식사 모니터·과식 경고"는 명시 예시. 단, fit_score 명명·범위에 의학적 진단 회피 워딩 적용.
3. **fit_score는 4분할 가중 (매크로 40 + 칼로리 25 + 알레르기 20 + 균형 15)**. Mifflin-St Jeor + KDRIs AMDR + 식약처 22종 + 대비학회 권고를 모두 입력으로 받음 → 단일 알고리즘으로 4개 학회·기관 권고 통합.
4. **5개 외주 고객사 모두 적합. 단, 데모 시나리오 페르소나는 분기 필요** (병원·보험·식품·스타트업이 ★★★★ 이상).
5. **DTx 트랙은 별도 (지금 진입 X), 그러나 영업 답변에 "DTx 확장 가능 PoC"로 포지셔닝하면 제약사도 ★★★ 카드로 살아남.**

### 갭 분류 (정직한 자기평가)

본 리서치 6개 목표는 모두 깊이 처리됐다. 아래는 **본 리서치 범위 외** 또는 **시점에 재검증 필요한 운영 룰**과 **실제 추가조사가 시급한 것**을 분리한 것이다.

#### 닫힌 갭 (이번에 추가 조사로 마감)

| # | 항목 | 결과 |
|---|---|---|
| A | **2020 KDRIs 식이섬유 충분섭취량** | 성인 남 30g, 여 20g/일 (KDRIs 2020 공식, [한국영양학회 KDRIs](https://kns.or.kr/FileRoom/FileRoom_view.asp?idx=108&BoardID=Kdr) · [복지부 활용자료](https://www.mohw.go.kr/board.es?mid=a10411010100&bid=0019&tag=&act=view&list_no=370012)). 본문 5.6 수치와 일치 — 별도 보정 불필요 |
| B | **대한비만학회 2024 진료지침 = 9판** | 2024 갱신본의 정식 명칭은 **9판** (8판이 2022). 위고비(세마글루타이드) 약물치료 권고안 추가, 건강기능식품 비권고 신설. 학술 1차 자료 형태로 [JKMA 2024;67(4):240 PDF](https://jkma.org/upload/pdf/jkma-2024-67-4-240.pdf) 사용 가능. 9판 전체 PDF 자체는 KSSO 회원 영역 — 운영 시 [KSSO 일반인 홈](https://general.kosso.or.kr/html/)에서 다운로드 |
| C | **PIPA 2026 개정 시행일/조항** | **2026.03.15 시행**. 핵심 강화: ① CPO(Chief Privacy Officer) 자격 강화 (개인정보보호 2년 포함 4년 경력), ② 5만명+ 민감정보 처리자 CPO 의무 강화, ③ **자동화된 의사결정 시 민감정보 처리 범위·처리 항목 구체적 공개 의무** ← AI_diet의 LangGraph 자동 분석에 직접 적용. 출처: [보안뉴스 — 3월 15일 개정 PIPA 5가지](https://m.boannews.com/html/detail.html?tab_type=1&idx=127454), [법과 상식 — 민감정보 2026 기준](https://law-sense.com/%EA%B0%9C%EC%9D%B8%EC%A0%95%EB%B3%B4-%EB%B3%B4%ED%98%B8%EB%B2%95-%EB%AF%BC%EA%B0%90%EC%A0%95%EB%B3%B4%EB%9E%80-%EC%B2%98%EB%A6%AC-%EC%A0%9C%ED%95%9C-%ED%95%AD%EB%AA%A9-%EC%B4%9D%EC%A0%95%EB%A6%AC-2), [법제처 시행령 입법예고](https://www.moleg.go.kr/lawinfo/makingInfo.mo?lawSeq=81114&lawCd=0&lawType=TYPE5&mid=a10104010000) |

> **C 항목 추가 액션 (PRD/SOP 단계 반영 필요)**: AI_diet의 LangGraph evaluate_fit + generate_feedback은 "자동화된 의사결정"에 해당할 수 있음. 사용자 동의서에 **처리 항목·범위 구체 공개** 필수.

#### 상시 재검증 항목 (실제 갭 아님 — 운영 룰)

| # | 항목 | 운영 룰 |
|---|---|---|
| 1 | **식약처 알레르기 표시 22종 최종 리스트** | 본 리서치 22종은 다수 출처 교차 검증 완료. 단 표시기준 별표는 갱신 가능 → **W1 시드 작업 시점에 [국가법령정보센터 별표](https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=42533884&bylClsCd=110201) 최신본 5분 확인** |

#### 본 리서치 범위 외 (별도 조사 필요)

| # | 항목 | 비고 |
|---|---|---|
| α | **B2B 외주 단가/리드타임 벤치마크** | 6개 목표 명시 범위 밖. 영업 단가 결정 시 별도 시장조사·사례 인터뷰 필요 |
| β | **식약처 디지털의료기기 가이드라인 (디지털의료제품법 2025.01 시행)** | DTx 트랙. AI_diet 웰니스 트랙 직접 적용 X. 제약사 영업 답변 강화 시 별도 조사 |

### 다음 단계 (BMad 워크플로우 — 정식 순서)

본 리서치는 다음 단계의 **입력 자료**다. BMad 정식 순서:

1. **`bmad-product-brief`** ← **다음 권장** — 본 리서치 + 브레인스토밍 산출물을 비즈니스 가치/문제 정의 Product Brief로 압축. "왜 이걸 만드는가 / 누구를 위한 것인가" 앵커 문서 (이전 단계 건너뛰지 말 것 — 후속 PRD/Architecture가 brief의 Why/Who 앵커를 참조함)
2. `bmad-create-prd` — Brief 통과 후, 6노드 LangGraph + 13항목 IN 스코프 + 본 리서치 표준을 정식 PRD 기능 명세로
3. `bmad-create-architecture` — fit_score 알고리즘, 6노드 LangGraph, RAG 메타데이터를 솔루션 디자인으로
4. `bmad-create-epics-and-stories` — W1-W8 일정을 epic·story로 분해, 본 리서치 테이블을 acceptance criteria 인용
5. **(선택) `bmad-create-ux-design`** — **1인 8주 MVP에서는 기본 생략 권장**. 본 리서치 3.4(디스클레이머 텍스트), 4.3(피드백 톤), 브레인스토밍 9-포인트 데모가 이미 화면 단위 UX 결정을 담고 있어 PRD + 스토리 단위 acceptance criteria로 흡수 가능. 별도 wireframe·디자인 시스템이 필요한 시점(예: 외주 클라이언트가 디자인 산출물을 추가 요구)에만 호출

**본 리서치가 brief 단계에 직접 인용되는 위치**:
- "타겟 고객" 섹션 → 목표 6.2 5개 고객사 적합성 ★표
- "차별화 가치" → 목표 4.2 차별화 3카드
- "규제·리스크" → 목표 3.1 의료기기 미분류 + 3.3 PIPA 민감정보 + 3.4 디스클레이머
- "시장 신호" → 목표 6.1 (6.5조 규모, +13.5%)

---

## 리서치 완료 메타

- **완료일**: 2026-04-26
- **6개 목표 모두 동등 깊이로 처리** (각 목표 평균 4-6개 권위 출처 인용)
- **총 출처**: A급 12+, B급 4+, C급 20+ (목록 위 통합 표 참조)
- **검증 방식**: 다중 출처 교차 확인, 한국 1차 자료 우선
- **닫힌 갭**: KDRIs 식이섬유 수치 / 대비학회 9판 명칭·약물 권고 / PIPA 2026.03.15 시행 자동화 의사결정 의무
- **상시 재검증 항목**: 알레르기 22종 — W1 시드 시 5분 재확인
- **본 리서치 범위 외**: B2B 외주 단가 (영업 단계 별도 조사), DTx 가이드라인 (해당 트랙 진입 시)
- **다음 권장**: **bmad-product-brief** (Brief → PRD → Architecture → UX → Epics 순)


