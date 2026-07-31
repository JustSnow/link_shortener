"""SQLAlchemy ORM models — single source of truth for the schema."""


from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class LinkORM(Base):
    __tablename__ = "links"

    id = Column(String(6), primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
