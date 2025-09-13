from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON, Integer, String, Text
from .db import Base

from sqlalchemy import Integer, String, JSON, text
# ...
class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    race: Mapped[str] = mapped_column(String(50))
    portrait_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=lambda: {"corps": 0, "mental": 0, "social": 0})
    skills_primary: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills_secondary: Mapped[list[str]] = mapped_column(JSON, default=list)
    inventory: Mapped[list[str]] = mapped_column(JSON, default=list)
    gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)