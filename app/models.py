import uuid
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Table, Text, Column, UniqueConstraint
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
    background_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    inventory_categories: Mapped[list["InventoryCategory"]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        order_by="InventoryCategory.sort_order",
    )
    note_tabs: Mapped[list["CharacterNote"]] = relationship(
        back_populates="character",
        cascade="all, delete-orphan",
        order_by=lambda: (CharacterNote.sort_order, CharacterNote.id),
    )
    owner: Mapped["User | None"] = relationship(back_populates="characters")


class CharacterNote(Base):
    __tablename__ = "character_notes"
    __table_args__ = (
        UniqueConstraint("character_id", "title", name="uq_character_notes_character_title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    character: Mapped[Character] = relationship(back_populates="note_tabs")


class InventoryCategory(Base):
    __tablename__ = "inventory_categories"
    __table_args__ = (
        UniqueConstraint("character_id", "name", name="uq_inventory_categories_character_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    character: Mapped[Character] = relationship(back_populates="inventory_categories")
    contents: Mapped[list["InventoryContent"]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="InventoryContent.sort_order",
    )


class InventoryContent(Base):
    __tablename__ = "inventory_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("inventory_categories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    category: Mapped[InventoryCategory] = relationship(back_populates="contents")


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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="player", server_default="player")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    characters: Mapped[list[Character]] = relationship(back_populates="owner")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    replaced_by_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id"),
        nullable=True,
    )
    user: Mapped[User] = relationship(back_populates="refresh_tokens")
