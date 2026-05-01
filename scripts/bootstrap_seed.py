"""bootstrap_seed.py — Docker ``seed`` 컨테이너 entrypoint.

Story 3.1 + Story 3.2 — food → guidelines 순차 위임.

흐름:
  1. ``seed_food_db.main()`` — 식약처 OpenAPI 1차 + ZIP fallback + food_aliases 시드.
  2. food 시드 성공 시 ``seed_guidelines.main()`` — KDRIs/KSSO/KDA/MFDS/KDCA 가이드라인
     50+ chunks 시드.

food 시드 실패 시 guidelines 시드 skip — 두 시드는 *독립 의존성*이지만 컨테이너
fail-fast 신호 통일 (Story 3.1 패턴 정합 — 첫 실패 시 즉시 비-zero exit).

dev/ci/test는 ``MFDS_OPENAPI_KEY`` 또는 ``OPENAI_API_KEY`` 미설정 시 graceful 0건/NULL
embedding 진행 (D9 — 외주 인수 클라이언트 첫 부팅 영업 demo 보호). prod/staging은
fail-fast.
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        # 동적 import — Python이 script 디렉토리(`/app/scripts/`)를 sys.path[0]에 추가하므로
        # sibling import 동작.
        from seed_food_db import main as seed_food_db_main  # type: ignore[import-not-found]
        from seed_guidelines import main as seed_guidelines_main  # type: ignore[import-not-found]

        food_seed_exit = seed_food_db_main()
        if food_seed_exit != 0:
            return food_seed_exit

        guidelines_seed_exit = seed_guidelines_main()
        if guidelines_seed_exit != 0:
            return guidelines_seed_exit

        return 0
    except Exception:  # noqa: BLE001
        # 시드 실패는 운영자에게 명확하게 신호 — 컨테이너 exit 1 + stderr stack trace.
        print("[bootstrap_seed] FAILED:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
