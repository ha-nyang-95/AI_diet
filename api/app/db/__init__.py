"""DB 패키지 — Base + async session_maker + ORM 모델 export.

Alembic env.py가 `Base.metadata`를 참조하므로 모델 모듈은 본 패키지가 import 시점에
자동 등록되도록 `app.db.models` 패키지를 명시적으로 import한다(declarative 등록 사이드이펙트).
"""

from __future__ import annotations

from app.db import models  # noqa: F401  (모델 등록 사이드이펙트)
from app.db.base import Base

__all__ = ["Base"]
