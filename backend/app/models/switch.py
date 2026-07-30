"""Switches."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.core import Room
    from app.models.port import Port


class Switch(Base, TimestampMixin):
    __tablename__ = "switches"
    __table_args__ = (CheckConstraint("port_count > 0", name="switches_port_count_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    serial: Mapped[str | None] = mapped_column(String(100))
    management_ip: Mapped[str | None] = mapped_column(INET)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        # Same rationale as devices.room_id: Postgres doesn't auto-index FK
        # columns and the topology view filters here on every render.
        index=True,
    )
    rack_position: Mapped[str | None] = mapped_column(String(20))
    port_count: Mapped[int] = mapped_column(nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String(50))
    snmp_community: Mapped[str | None] = mapped_column(String(100))
    asset_tag: Mapped[str | None] = mapped_column(String(50))
    warranty_expires_at: Mapped[date | None] = mapped_column(Date)
    eol_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)

    room: Mapped[Room | None] = relationship(back_populates="switches")
    ports: Mapped[list[Port]] = relationship(
        back_populates="switch",
        cascade="all, delete-orphan",
        # `ports.switch_id` is already ON DELETE CASCADE — let Postgres
        # handle the child deletes in one statement instead of the ORM
        # emitting one DELETE per port.
        passive_deletes=True,
    )
