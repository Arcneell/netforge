"""VLANs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.subnet import Subnet


class Vlan(Base):
    __tablename__ = "vlans"
    __table_args__ = (
        CheckConstraint("vlan_id BETWEEN 1 AND 4094", name="vlans_id_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vlan_id: Mapped[int] = mapped_column(unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(7))  # #RRGGBB

    subnets: Mapped[list[Subnet]] = relationship(back_populates="vlan")
