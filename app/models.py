from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON, Integer, String
from .db import Base

class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug : Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    race: Mapped[str] = mapped_column(String(50))
    portrait_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)

    # JSON payloads to mirror your TS shape
    stats: Mapped[dict] = mapped_column(JSON, default=lambda: {"corps": 0, "mental": 0, "social": 0})
    skills_primary: Mapped[list[str]] = mapped_column(JSON, default=list)   # length rules enforced in Pydantic
    skills_secondary: Mapped[list[str]] = mapped_column(JSON, default=list)
    inventory: Mapped[list[str]] = mapped_column(JSON, default=list)