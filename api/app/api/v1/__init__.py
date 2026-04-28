"""`/v1` 라우터 그룹 — 도메인별 1파일 1 APIRouter."""

from __future__ import annotations

# import 사이드이펙트로 라우터 모듈 로드 — main.py가 명시 import한다.
from app.api.v1 import auth, consents, legal, users  # noqa: F401
