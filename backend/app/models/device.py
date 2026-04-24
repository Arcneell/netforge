"""Devices (équipements non-switch)."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.ip import Ip
    from app.models.port import Port


class DeviceType(str, Enum):
    server = "server"
    desktop = "desktop"
    laptop = "laptop"
    printer = "printer"
    phone = "phone"
    ap = "ap"
    camera = "camera"
    ups = "ups"
    other = "other"


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[DeviceType] = mapped_column(
        SAEnum(DeviceType, name="device_type", native_enum=True),
        nullable=False,
    )
    vendor: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    serial: Mapped[str | None] = mapped_column(String(100))
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL")
    )
    description: Mapped[str | None] = mapped_column(Text)

    ips: Mapped[list[Ip]] = relationship(back_populates="device")
    ports: Mapped[list[Port]] = relationship(
        back_populates="connected_device",
        foreign_keys="Port.connected_device_id",
    )
