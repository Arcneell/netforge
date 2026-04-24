"""Switches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
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
        ForeignKey("rooms.id", ondelete="RESTRICT")
    )
    rack_position: Mapped[str | None] = mapped_column(String(20))
    port_count: Mapped[int] = mapped_column(nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String(50))
    snmp_community: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)

    room: Mapped[Room | None] = relationship(back_populates="switches")
    ports: Mapped[list[Port]] = relationship(
        back_populates="switch",
        cascade="all, delete-orphan",
    )
