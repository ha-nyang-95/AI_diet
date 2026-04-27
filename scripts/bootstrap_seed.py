"""bootstrap_seed.py — 초기 데이터 시드 entrypoint (placeholder).

향후:
- Story 3.1: seed_food_db.py — 식약처 OpenAPI에서 음식 영양 DB 시드
- Story 3.2: seed_guidelines.py — 한국인 영양섭취기준 가이드라인 RAG 시드

본 스토리(1.1)에서는 no-op으로 정상 종료. 향후 시드 호출 추가 시
실패는 non-zero exit로 전파해 컨테이너가 'unknown failure 0'으로 끝나지 않도록 한다.
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        # 향후: seed_food_db.run() / seed_guidelines.run()
        print("[bootstrap_seed] placeholder — Story 3.1/3.2에서 채워짐. no-op exit.")
        return 0
    except Exception:  # noqa: BLE001
        # 시드 실패는 운영자에게 명확하게 신호 — 컨테이너 exit 1 + stderr stack trace.
        print("[bootstrap_seed] FAILED:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
