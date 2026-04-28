"""`/v1/users/me` — 현재 로그인 사용자 조회 (Story 1.2 smoke)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import current_user
from app.db.models.user import User

router = APIRouter()


class UserMeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str | None
    picture_url: str | None
    role: str
    created_at: datetime
    last_login_at: datetime | None
    onboarded_at: datetime | None


@router.get("/me")
async def get_me(user: Annotated[User, Depends(current_user)]) -> UserMeResponse:
    return UserMeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        picture_url=user.picture_url,
        role=user.role,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        onboarded_at=user.onboarded_at,
    )
