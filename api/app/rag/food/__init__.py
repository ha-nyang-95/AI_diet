"""Food RAG 모듈 — Story 3.1 (음식 영양 시드 + food_aliases 정규화 사전).

- ``seed.py`` — ``run_food_seed`` (식약처 OpenAPI 1차 + ZIP fallback 2단 + 멱등 INSERT).
- ``aliases_data.py`` — ``FOOD_ALIASES`` const dict 50+건 (한국식 음식명 변형 → 표준).
- ``aliases_seed.py`` — ``seed_food_aliases`` (멱등 INSERT + count ≥ 50 게이트).

Story 3.4 ``normalize.py``는 *검색 흐름*만 — 본 모듈에서 시드된 데이터를 lookup 입력.
"""
