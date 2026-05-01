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
