# `data/guidelines/` — 한국 1차 출처 RAG 시드 자료

Story 3.2 — KDRIs/KSSO/KDA/MFDS/KDCA 5개 한국 1차 출처 가이드라인을 50-100 chunks로
시드하여 Story 3.6 `generate_feedback` 노드의 *(출처: 보건복지부 2020 KDRIs)* 패턴
인용 인프라를 박는다.

## 1. 자료 갱신 SOP — 분기 1회 (KDRIs 2025+ / KSSO 9판+ / KDA 2024+)

운영자 분기 1회(3월/6월/9월/12월) 자료 갱신 절차:

1. **원본 다운**: research 1.1 1차 자료 인덱스 URL에서 PDF/HTML 다운로드.
2. **수동 텍스트 추출**: 한글 PDF는 pypdf 한글 폰트 깨짐 위험으로 *수동 텍스트 추출 + 검수*
   필수(D1 명시). Word/Pages 등으로 PDF를 열어 본문 복사.
3. **frontmatter + body 갱신**: `data/guidelines/{source}-{slug}.md` 파일을
   frontmatter 메타데이터(아래 표) + body 가이드라인 본문으로 작성/갱신.
4. **시드 검증**: `cd api && uv run python /app/scripts/seed_guidelines.py`로 멱등 시드
   실행. `OPENAI_API_KEY` 설정 시 임베딩 NOT NULL 시드.
5. **PR + master 머지**: 게이트(ruff/mypy/pytest) 통과 → master 머지 → prod 자동 배포 시
   시드 컨테이너 자동 갱신.

## 2. 자료 인덱스 — 6 파일 + frontmatter 표준

| 파일 | source | source_id | authority_grade | topic | published_year |
|------|--------|-----------|-----------------|-------|----------------|
| kdris-2020-amdr.md | MOHW | KDRIS-2020-AMDR | A | macronutrient | 2020 |
| kdris-2020-protein.md | MOHW | KDRIS-2020-PROTEIN | A | macronutrient | 2020 |
| kosso-2024-weight-loss.md | KSSO | KSSO-2024-WEIGHT-LOSS | A | macronutrient | 2024 |
| kda-macronutrient.md | KDA | KDA-MACRO-2017 | A | disease_specific | 2017 |
| mfds-allergens-22.md | MFDS | MFDS-ALLERGEN-22 | A | allergen | 2024 |
| kdca-diabetes-diet.md | KDCA | KDCA-DIABETES-DIET | A | disease_specific | 2024 |

frontmatter 필드:
- `source` (Literal): `MFDS` / `MOHW` / `KSSO` / `KDA` / `KDCA`.
- `source_id` (str, min 3): 문서 식별자.
- `authority_grade` (Literal): `A` / `B` / `C` (research 1.2).
- `topic` (Literal): `macronutrient` / `allergen` / `disease_specific` / `general`.
- `applicable_health_goals` (list[Literal]): `weight_loss` / `muscle_gain` / `maintenance` /
  `diabetes_management`. *빈 배열은 전 사용자 적용*(예: 식약처 22종 알레르기).
- `published_year` (int, 1990-2100, optional): 발행연도.
- `doc_title` (str, min 5): 문서 표시명 — 인용 패턴 직접 주입.
- `allergens` (list[str], optional): `mfds-allergens-22.md` 전용 22 항목.

## 3. 외주 인수 클라이언트 — 자체 PDF 시드 추가 SOP (3 경로)

**경로 A — Markdown 변환 + frontmatter (권장)**:
1. 클라이언트 PDF/자료 → 운영자 수동 chunking + frontmatter 작성.
2. `data/guidelines/<client>-<slug>.md` 추가.
3. `seed_guidelines.py` 실행 → 멱등 시드 (PR 게이트 + ruff/mypy/pytest 보호).

**경로 B — `app/rag/chunking/pdf.py` 자동 chunking** (외주 인수 인터페이스 토대):
```python
from app.rag.chunking import chunk_pdf
chunks = chunk_pdf(pdf_bytes, max_chars=1000, overlap=100)
# 클라이언트 자체 자동 시드 파이프라인에서 호출.
```
*본 MVP 시드 경로는 호출 X* — 외주 인수 후 *자동 시드 파이프라인*으로 활성화 (D1).

**경로 C — psql 직접 INSERT (즉시 영업 demo)**:
```sql
INSERT INTO knowledge_chunks (
  source, source_id, chunk_index, chunk_text, embedding,
  authority_grade, topic, applicable_health_goals, published_year, doc_title
) VALUES (...)
ON CONFLICT (source, source_id, chunk_index) DO UPDATE ...;
```

## 4. 자료 신뢰 등급 가이드 (research 1.2)

- **A급**: 1차 공식 — KDRIs PDF / 학회 진료지침 / KDCA 포털 / 식약처 공식 표시기준.
- **B급**: 학술 논문 / 2차 가이드라인.
- **C급**: 참고 자료.

본 시드 baseline은 *모두 A급* — B/C는 future expansion.

## 5. `verify_allergy_22.py` 분기 SOP (R8 정합)

식약처 22종 갱신 시 `app/domain/allergens.py` lookup vs `mfds-allergens-22.md`
frontmatter `allergens` 1:1 매칭 검증:

```bash
cd api && uv run python /app/scripts/verify_allergy_22.py
```

성공 시 exit 0 + stdout `OK (22 items match)`. 차이 발견 시 exit 1 + stderr 차이
출력 + 운영자 갱신 PR SOP 안내.

식약처 공식 URL 3종은 본 스크립트가 stdout 출력 — 분기 1회 운영자 수동 다운 + 갱신 SOP.

## 인용 안내

본 가이드라인 시드는 RAG `generate_feedback` 노드의 *인용 출처 직접 주입* 인프라이며,
의료기기·치료기기로 분류되지 않는 일반 영양 분석 안내 앱의 1차 자료 제공 기능을 담당한다.
임상 적용 시 의료진 상담을 1차 경로로 한다.
