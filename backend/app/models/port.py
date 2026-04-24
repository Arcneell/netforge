"""Ports de switch + table port_vlan pour trunks."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.device import Device
    from app.models.ip import Ip
    from app.models.switch import Switch
    from app.models.vlan import Vlan


class PortMode(str, Enum):
    access = "access"
    trunk = "trunk"
    hybrid = "hybrid"
    disabled = "disabled"


class PortAdminStatus(str, Enum):
    up = "up"
    down = "down"


class Port(Base):
    __tablename__ = "ports"
    __table_args__ = (
        UniqueConstraint("switch_id", "number", name="ports_switch_number_uniq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(
        ForeignKey("switches.id", ondelete="CASCADE"),
        nullable=False,
    )
    number: Mapped[int] = mapped_column(nullable=False)
    label: Mapped[str | None] = mapped_column(String(100))
    mode: Mapped[PortMode] = mapped_column(
        SAEnum(PortMode, name="port_mode", native_enum=True),
        nullable=False,
        default=PortMode.access,
    )
    native_vlan_id: Mapped[int | None] = mapped_column(
        ForeignKey("vlans.id", ondelete="SET NULL")
    )
    admin_status: Mapped[PortAdminStatus] = mapped_column(
        SAEnum(PortAdminStatus, name="port_admin_status", native_enum=True),
        nullable=False,
        default=PortAdminStatus.up,
    )
    connected_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    connected_ip_id: Mapped[int | None] = mapped_column(
        ForeignKey("ips.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    switch: Mapped[Switch] = relationship(back_populates="ports")
    native_vlan: Mapped[Vlan | None] = relationship(foreign_keys=[native_vlan_id])
    connected_device: Mapped[Device | None] = relationship(
        back_populates="ports",
        foreign_keys=[connected_device_id],
    )
    connected_ip: Mapped[Ip | None] = relationship(foreign_keys=[connected_ip_id])

    tagged_vlans: Mapped[list[PortVlan]] = relationship(
        back_populates="port",
        cascade="all, delete-orphan",
    )


class PortVlan(Base):
    """Table de liaison pour les VLANs tagués d'un port trunk."""

    __tablename__ = "port_vlan"

    port_id: Mapped[int] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"),
        primary_key=True,
    )
    vlan_id: Mapped[int] = mapped_column(
        ForeignKey("vlans.id", ondelete="CASCADE"),
        primary_key=True,
    )

    port: Mapped[Port] = relationship(back_populates="tagged_vlans")
    vlan: Mapped[Vlan] = relationship()
