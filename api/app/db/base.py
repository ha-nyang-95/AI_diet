"""SQLAlchemy 2.0 declarative Base — 모든 ORM 모델의 부모."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """프로젝트 공통 ORM Base. 도메인 모델은 본 클래스를 상속한다."""
