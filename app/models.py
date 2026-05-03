import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import JSON, ForeignKey, Integer, String, Table, Text, Column
from .db import Base

from sqlalchemy import text

character_teams = Table(
    "character_teams",
    Base.metadata,
    Column("character_id", ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("team_uuid", ForeignKey("teams.uuid", ondelete="CASCADE"), primary_key=True),
)


class Character(Base):
    __tablename__ = "characters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    race: Mapped[str] = mapped_column(String(50))
    portrait_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=lambda: {"corps": 0, "mental": 0, "social": 0})
    skills_primary: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills_secondary: Mapped[list[str]] = mapped_column(JSON, default=list)
    inventory: Mapped[list[str]] = mapped_column(JSON, default=list)
    gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_hp: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    bonus_health: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    teams: Mapped[list["Team"]] = relationship(
        secondary=character_teams,
        back_populates="characters",
    )


class Team(Base):
    __tablename__ = "teams"
    uuid: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(100), index=True)
    illustration_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    characters: Mapped[list[Character]] = relationship(
        secondary=character_teams,
        back_populates="teams",
    )
