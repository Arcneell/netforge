"""Liens physiques entre deux ports de switches."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.port import Port


class LinkType(str, Enum):
    copper = "copper"
    fiber = "fiber"
    dac = "dac"
    virtual = "virtual"


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        CheckConstraint("port_a_id <> port_b_id", name="links_distinct_ports"),
        CheckConstraint("port_a_id < port_b_id", name="links_canonical_order"),
        UniqueConstraint("port_a_id", "port_b_id", name="links_ports_uniq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    port_a_id: Mapped[int] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"),
        nullable=False,
    )
    port_b_id: Mapped[int] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"),
        nullable=False,
    )
    link_type: Mapped[LinkType] = mapped_column(
        SAEnum(LinkType, name="link_type", native_enum=True),
        nullable=False,
    )
    speed_mbps: Mapped[int | None] = mapped_column()
    description: Mapped[str | None] = mapped_column(Text)

    port_a: Mapped[Port] = relationship(foreign_keys=[port_a_id])
    port_b: Mapped[Port] = relationship(foreign_keys=[port_b_id])
