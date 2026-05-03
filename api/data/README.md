# `api/data/` — Story 3.1 시드 백업 + 운영 SOP

본 디렉터리는 Story 3.1 (음식 영양 RAG 시드 + pgvector HNSW)의 *2차 fallback*
정적 백업 파일과 운영 SOP를 보관한다.

## ZIP fallback 갱신 SOP

`mfds_food_nutrition_seed.csv` 는 식약처 식품영양성분 DB 통합 자료집의 변환본이다.
1차(공공데이터포털 15127578 OpenAPI) 장애·부족 시 시드 컨테이너가 본 파일을
읽어 `food_nutrition`을 보강한다.

1. `https://www.data.go.kr/data/15047698/fileData.do` (식약처 통합 자료집)에서
   ZIP/CSV 다운로드.
2. 컬럼을 식약처 표준 키로 변환:

   | CSV 컬럼          | 의미             | 단위/형식                    |
   |-------------------|------------------|------------------------------|
   | `name`            | 한국어 표준 음식명 | 텍스트                       |
   | `category`        | 식약처 품목분류  | 텍스트 (예: `면류`)          |
   | `energy_kcal`     | 에너지           | kcal                         |
   | `carbohydrate_g`  | 탄수화물         | g                            |
   | `protein_g`       | 단백질           | g                            |
   | `fat_g`           | 지방             | g                            |
   | `saturated_fat_g` | 포화지방산       | g                            |
   | `sugar_g`         | 당류             | g                            |
   | `fiber_g`         | 식이섬유         | g                            |
   | `sodium_mg`       | 나트륨           | mg                           |
   | `cholesterol_mg`  | 콜레스테롤       | mg                           |
   | `serving_size_g`  | 1회 제공량       | g (또는 mL)                  |
   | `serving_unit`    | 제공량 단위      | 텍스트 (`g`/`mL`/`인분`)     |
   | `source_id`       | 식품코드         | 식약처 코드 (예: `K-115001`) |

3. 변환된 CSV를 `api/data/mfds_food_nutrition_seed.csv`로 commit (UTF-8 + LF 개행).
4. 현재 repo는 *placeholder* (헤더만)을 commit한 상태 — 운영 사용 시 실제 데이터로 교체.
   분기 1회 갱신 권장.

## 외주 인수 클라이언트 — 자기 메뉴 별칭 추가 SOP (3 경로)

`food_aliases` 정규화 사전에 클라이언트가 자사 메뉴 별칭을 추가하는 3 경로:

### 경로 A — Python 코드 편집 (PR 게이트, 권장)

`api/app/rag/food/aliases_data.py` 의 `FOOD_ALIASES` dict에 entry 추가:

```python
FOOD_ALIASES: Final[dict[str, str]] = {
    # ... 기존 50+ 엔트리 ...
    "<자사 메뉴 별칭>": "<표준 음식명>",
}
```

→ PR + ruff/mypy/pytest 통과 → master 머지 → `docker compose restart seed`
또는 prod 배포 후 자동 시드(ON CONFLICT UPDATE 멱등). 코드 변경 추적 + 회귀
게이트 보호. **권장**.

### 경로 B — DB 직접 INSERT (런타임 즉시 반영)

```bash
psql -U app -d app -c \
  "INSERT INTO food_aliases (alias, canonical_name) \
   VALUES ('자사 메뉴 별칭', '표준 음식명') \
   ON CONFLICT (alias) DO UPDATE SET canonical_name = EXCLUDED.canonical_name;"
```

Story 3.4 `normalize.py`가 자동 lookup. 코드 배포 X + 즉시 영업 demo 반영 —
1회성 / 시연 직전 빠른 추가에 사용.

### 경로 C — admin UI (Story 7.x — OUT)

`POST /v1/admin/food-aliases` + audit log + role gate — 비개발자 운영자 + 변경
이력 추적이 필요한 시점. 본 스토리(3.1) baseline은 OUT.

### `canonical_name` ↔ `food_nutrition.name` 매칭

`canonical_name`이 `food_nutrition`에 미존재해도 시드 OK(forward FK 없음).
Story 3.4 `normalize.py`가 unmatched 시 임베딩 fallback → LLM 재선택 분기 자연 흡수.

## fit_score 알고리즘 baseline (Story 3.5)

`fit_score`(0-100)는 4 컴포넌트 합산 결정성 알고리즘이다. LLM 호출 X — 입력
동일 → 출력 동일(test 스냅샷 안정 + Story 3.6 회귀 측정 입력 안정화).

### 가중치

| 컴포넌트   | 만점 | 산출 근거                                         |
|------------|------|---------------------------------------------------|
| Macro      | 40   | meal 탄/단/지 비율과 KDRIs AMDR 권장 비율 편차    |
| 칼로리     | 25   | meal kcal과 ``(TDEE + adj)/3`` 편차(±15%/±30%)    |
| 알레르기   | 20   | 위반 0건 = 만점, 1건 이상 = 0점 + **즉시 단락**   |
| 균형       | 15   | 단백질 ≥ 10g(+5) / 식이섬유 ≥ 3g(+5) / 채소·과일(+5) |

알레르기 위반 1건 이상 → ``fit_score = 0`` 즉시 단락 + ``fit_reason="allergen_violation"``.
매크로/칼로리/균형 점수 산출 X (epic L652 + prd.md L442 정합).

### Mifflin-St Jeor BMR (kcal/day)

- 남성: ``BMR = 10*w + 6.25*h - 5*a + 5``
- 여성: ``BMR = 10*w + 6.25*h - 5*a - 161``

`UserProfileSnapshot.sex` 필드 부재(Story 1.5 baseline) — 본 baseline은 caller가
default ``sex="female"``를 적용한다(데모 페르소나 *지수* 정합 — prd.md L275).
prod 시나리오에 sex 분기가 필요한 외주 클라이언트는 Story 1.5 갱신 + caller 갱신
필요(Story 8.4 polish 슬롯).

### Activity 5단계 multiplier (Harris-Benedict)

| activity_level | multiplier | 의미                          |
|----------------|------------|-------------------------------|
| sedentary      | 1.2        | 거의 운동 안 함               |
| light          | 1.375      | 주 1-3회 가벼운 운동          |
| moderate       | 1.55       | 주 3-5회 중간 강도            |
| active         | 1.725      | 주 6-7회 강한 강도            |
| very_active    | 1.9        | 매일 강한 운동 + 신체노동     |

TDEE = ``BMR × multiplier``.

### KDRIs AMDR `health_goal` 매크로 룰 + 칼로리 adjustment

| health_goal          | carb | protein | fat  | adj(kcal/day) | 출처                           |
|----------------------|------|---------|------|---------------|--------------------------------|
| weight_loss          | 0.50 | 0.25    | 0.25 | -500          | 대한비만학회 9판 2024          |
| muscle_gain          | 0.45 | 0.30    | 0.25 | +300          | 단백질 1.6-2.0g/kg 권장 정합   |
| maintenance          | 0.55 | 0.20    | 0.25 | 0             | KDRIs 2020 AMDR 중간값         |
| diabetes_management  | 0.45 | 0.25    | 0.30 | 0             | 대한당뇨병학회 매크로 권고     |

target_meal_kcal = ``(TDEE + adj) / 3`` (3끼 분배 가정).

### `fit_label` band (NFR-A4 색약 대응)

| score 범위    | label                | UI 의미      |
|---------------|----------------------|--------------|
| 80-100        | `good`               | 양호         |
| 60-79         | `caution`            | 주의         |
| 0-59          | `needs_adjust`       | 조정 필요    |
| 위반 단락     | `allergen_violation` | 알레르기 위반|

UI는 색상+숫자+텍스트 라벨 동시 노출(NFR-A4) — 한국어 텍스트 라벨은 모바일/웹
i18n 자원 영역(백엔드는 enum SOT만).

## ALLERGEN_ALIAS_MAP 외주 인수 보강 SOP (Story 3.5)

`api/app/domain/fit_score.py:ALLERGEN_ALIAS_MAP`은 한국 외식·배달 메뉴 alias →
22종 표준 라벨 매핑 baseline(8-12건). 외주 인수 시 클라이언트가 자사 메뉴별
alias를 보강해 검출률을 끌어올리는 1차 SOP.

### baseline 매핑 (8-12건)

| alias    | 22종 표준 라벨   |
|----------|------------------|
| 계란     | 난류(가금류)     |
| 달걀     | 난류(가금류)     |
| 오믈렛   | 난류(가금류)     |
| 마요네즈 | 난류(가금류)     |
| 치즈     | 우유             |
| 요구르트 | 우유             |
| 버터     | 우유             |
| 쉬림프   | 새우             |
| 포크     | 돼지고기         |
| 비프     | 쇠고기           |
| 치킨     | 닭고기           |
| 넛       | 호두             |

### 보강 절차 (PR 게이트, 권장)

1. `api/app/domain/fit_score.py:ALLERGEN_ALIAS_MAP` dict에 entry 추가:

   ```python
   ALLERGEN_ALIAS_MAP: dict[str, str] = {
       # ... 기존 baseline ...
       "<자사 메뉴 alias>": "<22종 표준 라벨>",
   }
   ```

2. `api/tests/domain/test_fit_score_allergen_22.py:ALIAS_MAP_CASES`는 `ALLERGEN_ALIAS_MAP`
   전체를 매개변수화하므로 자동 회귀 가드. 22종 단락 가드도 동일.
3. PR + ruff/mypy/pytest 통과 → master 머지.

### NFC 정규화

macOS 클립보드의 NFD-encoded Hangul도 SOT의 NFC 라벨과 안전 매칭(`detect_allergen_violations`
는 NFC 정규화 후 substring 비교 — Story 1.5 패턴 정합).

### `"기타"` 알레르기 처리 — generic substring 회피

22종 마지막 항목 `"기타"`는 generic — `"기타치킨"` 같은 음식명은 false positive
위험. baseline은 substring 우선이라 `"기타알레르기성분"` 같이 명시적 alias로 등록한
경우만 매칭(false positive 회피). 클라이언트가 `"기타"` 알레르기를 등록한 사용자에게
서비스할 때는 자기 메뉴별 explicit alias로 보강 권장.

### 외주 인수 1차 데모 baseline

baseline 8-12건은 9포인트 데모 시나리오 음식(짜장면/우유라떼/땅콩버터/쉬림프카레/
달걀말이 등) 모두 검출 정합. 자사 메뉴 50+ 보강 시 외식·배달 검출률 ~90% 도달
경험치 기반.

## 의료기기 미분류 정합 (Story 3.5 + prd.md L409)

`fit_score`의 정식 명명은 *"건강 목표 부합도 점수"*. 의학적 진단 또는 의료기기
영역 외 — UI 푸터 문구는 다음 1줄로 통일한다:

> 건강 목표 부합도 점수 — 의학적 진단이 아닙니다.

C1 의료기기 미분류 SOP(Story 8.1) + Story 3.7 모바일 SSE UI 디스클레이머 푸터
(epic L690 정합) 모두 동일 SOT를 인용한다.
