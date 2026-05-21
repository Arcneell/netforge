"""Subnets (IPv4 CIDR blocks)."""

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
    # Routing-table scope. NULL = global VRF. Two subnets in different VRFs
    # may share an overlapping CIDR — the GiST exclusion is partitioned by
    # `vrf_id` (see migration 0010).
    vrf_id: Mapped[int | None] = mapped_column(
        ForeignKey("vrfs.id", ondelete="RESTRICT"),
    )
    # Optional self-reference for hierarchical IPAM. A child subnet must
    # fit within its parent (enforced in the service layer); breaking the
    # parent link is allowed via SET NULL since orphans are still valid
    # standalone subnets.
    parent_subnet_id: Mapped[int | None] = mapped_column(
        ForeignKey("subnets.id", ondelete="SET NULL"),
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
    parent: Mapped[Subnet | None] = relationship(
        "Subnet",
        remote_side="Subnet.id",
        back_populates="children",
    )
    children: Mapped[list[Subnet]] = relationship(
        "Subnet",
        back_populates="parent",
        cascade="save-update",
    )
