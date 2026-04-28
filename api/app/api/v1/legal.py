"""`/v1/legal/{type}` — 법적 문서 풀텍스트 (Story 1.3, FR8).

**Public endpoint** — 인증 무관(`current_user` Depends 미사용). 클라이언트가 cookie를
동봉해도 본 라우터는 cookie를 읽지 않는다.

쿼리:
- `lang=ko|en` (default `ko`).

응답:
- 200 + ``LegalDocumentResponse`` (snake_case 양방향, Story 1.2 정합).
- 잘못된 `lang` 값: 422 (FastAPI Literal 자동 검증).
- 잘못된 `type` path: 404 (FastAPI Literal 자동 검증).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.domain.legal_documents import LEGAL_DOCUMENTS, LegalDocType, LegalLang

router = APIRouter()


class LegalDocumentResponse(BaseModel):
    type: LegalDocType
    lang: LegalLang
    version: str
    title: str
    body: str
    updated_at: datetime


@router.get("/{doc_type}")
async def get_legal_document(
    doc_type: Literal["disclaimer", "terms", "privacy"],
    lang: Literal["ko", "en"] = "ko",
) -> LegalDocumentResponse:
    """SOT 매핑(`LEGAL_DOCUMENTS`)에서 직접 조회 — DB 호출 없음."""
    document = LEGAL_DOCUMENTS[(doc_type, lang)]
    return LegalDocumentResponse(
        type=document.type,
        lang=document.lang,
        version=document.version,
        title=document.title,
        body=document.body,
        updated_at=document.updated_at,
    )
