"""VRFs (Virtual Routing and Forwarding instances).

A VRF is a routing-table isolation unit: two subnets in different VRFs
may have overlapping CIDRs without conflict. Practical examples:
  - A `tenant_a` and `tenant_b` VRF in a multi-tenant lab, both using
    10.0.0.0/16 internally.
  - A `prod` and `dev` VRF that mirror each other's IP plan for
    blue/green testing.

Subnets without a VRF live in the **global** scope and still benefit
from the no-overlap constraint among themselves. Internally we
represent the global scope as `vrf_id IS NULL`.
"""

from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Vrf(Base, TimestampMixin):
    __tablename__ = "vrfs"
    __table_args__ = (
        UniqueConstraint("name", name="vrfs_name_uniq"),
        UniqueConstraint("rd", name="vrfs_rd_uniq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Route distinguisher in the BGP/MPLS sense (e.g. "65000:42"). Optional —
    # operators who don't run BGP don't need it. Kept unique when set so an
    # accidental duplicate doesn't slip into a config export.
    rd: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
