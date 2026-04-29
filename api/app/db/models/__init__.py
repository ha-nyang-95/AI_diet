"""ORM 모델 — declarative 등록 사이드이펙트로 import.

신규 모델 추가 시 본 모듈에 import를 추가해 Alembic autogenerate가 인식하도록 한다.
"""

from __future__ import annotations

from app.db.models.consent import Consent
from app.db.models.meal import Meal
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User

__all__ = ["Consent", "Meal", "RefreshToken", "User"]
