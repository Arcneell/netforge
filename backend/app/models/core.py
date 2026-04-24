"""Sites et salles (rooms)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.subnet import Subnet
    from app.models.switch import Switch


class Site(Base, TimestampMixin):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text)

    rooms: Mapped[list[Room]] = relationship(
        back_populates="site",
        cascade="all, delete-orphan",
    )
    subnets: Mapped[list[Subnet]] = relationship(back_populates="site")


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("site_id", "code", name="rooms_site_code_uniq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    site: Mapped[Site] = relationship(back_populates="rooms")
    switches: Mapped[list[Switch]] = relationship(back_populates="room")
