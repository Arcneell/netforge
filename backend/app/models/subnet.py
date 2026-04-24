"""Subnets (sous-réseaux IPv4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import CIDR, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.core import Site
    from app.models.ip import Ip
    from app.models.vlan import Vlan


class Subnet(Base, TimestampMixin):
    __tablename__ = "subnets"

    id: Mapped[int] = mapped_column(primary_key=True)
    cidr: Mapped[str] = mapped_column(CIDR, nullable=False)
    gateway: Mapped[str | None] = mapped_column(INET)
    vlan_id: Mapped[int | None] = mapped_column(
        ForeignKey("vlans.id", ondelete="SET NULL")
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)
    dhcp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dhcp_range_start: Mapped[str | None] = mapped_column(INET)
    dhcp_range_end: Mapped[str | None] = mapped_column(INET)

    vlan: Mapped[Vlan | None] = relationship(back_populates="subnets")
    site: Mapped[Site] = relationship(back_populates="subnets")
    ips: Mapped[list[Ip]] = relationship(
        back_populates="subnet",
        cascade="all, delete-orphan",
    )
