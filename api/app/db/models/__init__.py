"""ORM 모델 — declarative 등록 사이드이펙트로 import.

신규 모델 추가 시 본 모듈에 import를 추가해 Alembic autogenerate가 인식하도록 한다.
"""

from __future__ import annotations

from app.db.models.audit_log import AuditLog
from app.db.models.consent import Consent
from app.db.models.food_alias import FoodAlias
from app.db.models.food_nutrition import FoodNutrition
from app.db.models.knowledge_chunk import KnowledgeChunk
from app.db.models.meal import Meal
from app.db.models.meal_analysis import MealAnalysis
from app.db.models.notification import Notification
from app.db.models.payment_log import PaymentLog
from app.db.models.refresh_token import RefreshToken
from app.db.models.subscription import Subscription
from app.db.models.user import User

__all__ = [
    "AuditLog",
    "Consent",
    "FoodAlias",
    "FoodNutrition",
    "KnowledgeChunk",
    "Meal",
    "MealAnalysis",
    "Notification",
    "PaymentLog",
    "RefreshToken",
    "Subscription",
    "User",
]
