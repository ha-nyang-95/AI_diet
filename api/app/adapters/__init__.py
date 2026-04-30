"""외부 시스템 어댑터 패키지 — Google OAuth, R2, OpenAI Vision, MFDS, 결제 등.

원칙: 외부 통신 책임을 라우터·서비스에서 분리. 테스트 시 monkeypatch / respx로 stub.
"""

from app.adapters.openai_adapter import (
    ParsedMeal,
    ParsedMealItem,
    parse_meal_image,
)
from app.adapters.r2 import PresignedUpload, create_presigned_upload

__all__ = [
    "ParsedMeal",
    "ParsedMealItem",
    "PresignedUpload",
    "create_presigned_upload",
    "parse_meal_image",
]
