"""bootstrap_seed.py — Docker ``seed`` 컨테이너 entrypoint.

Story 3.1 진입 — placeholder no-op 폐기. ``seed_food_db.main()``을 위임 호출 →
1차 식약처 OpenAPI + 2차 ZIP fallback + food_aliases 50+건 시드.

향후:
- Story 3.2 — ``seed_guidelines.py`` (한국인 영양섭취기준 가이드라인 RAG 시드 + chunking) 추가.

시드 실패는 비-zero exit으로 컨테이너에 신호 — *unknown failure 0*으로 끝나지
않도록(prod/staging 또는 strict 모드). dev/ci/test는 ``MFDS_OPENAPI_KEY`` 미설정
시 graceful 0건 진행 (D9 — 외주 인수 클라이언트 첫 부팅 영업 demo 보호).
"""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        # 동적 import — Python이 script 디렉토리(`/app/scripts/`)를 sys.path[0]에 추가하므로
        # sibling import 동작. Story 3.2+ seed 모듈 확장 시 동일 패턴.
        from seed_food_db import main as seed_food_db_main  # type: ignore[import-not-found]

        food_seed_exit = seed_food_db_main()
        if food_seed_exit != 0:
            return food_seed_exit

        # 향후 — seed_guidelines.main() 등 추가 시 동일 패턴.
        return 0
    except Exception:  # noqa: BLE001
        # 시드 실패는 운영자에게 명확하게 신호 — 컨테이너 exit 1 + stderr stack trace.
        print("[bootstrap_seed] FAILED:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
