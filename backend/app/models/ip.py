"""Individual IP addresses."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import INET, MACADDR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.subnet import Subnet


class IpStatus(str, Enum):
    reserved = "reserved"
    assigned = "assigned"
    dhcp = "dhcp"


class Ip(Base, TimestampMixin):
    __tablename__ = "ips"

    id: Mapped[int] = mapped_column(primary_key=True)
    subnet_id: Mapped[int] = mapped_column(
        ForeignKey("subnets.id", ondelete="CASCADE"),
        nullable=False,
    )
    address: Mapped[str] = mapped_column(INET, unique=True, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    mac: Mapped[str | None] = mapped_column(MACADDR)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    status: Mapped[IpStatus] = mapped_column(
        SAEnum(IpStatus, name="ip_status", native_enum=True),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)

    subnet: Mapped[Subnet] = relationship(back_populates="ips")
    device: Mapped[Device | None] = relationship(back_populates="ips")
