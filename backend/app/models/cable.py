"""Physical cables — metadata bag for the cable that realises a link.

Modelled as a separate table (not extra columns on `links`) for two reasons:
  - Cables outlive links. When you swap a switch and re-patch, the same
    physical cable now realises a different `Link` row; the metadata
    (label, length, vendor) should follow the cable, not the link.
  - Cables can exist before they're plugged anywhere (inventory).

The relationship is one-to-one with `Link` via `cables.link_id`. A NULL
link_id means "in stock, not patched". A link without a cable row is fine
too — older deployments simply have no cable inventory.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Cable(Base, TimestampMixin):
    __tablename__ = "cables"
    __table_args__ = (
        # One cable per link, at most. NULL link_id is allowed for stock —
        # PostgreSQL treats NULLs as distinct in UNIQUE indexes by default,
        # so multiple unpatched cables coexist without trouble.
        UniqueConstraint("link_id", name="cables_link_uniq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Human label printed on the cable (e.g. "PA-CR12-A03"). Optional but
    # nearly always set in practice.
    label: Mapped[str | None] = mapped_column(String(120))
    link_id: Mapped[int | None] = mapped_column(
        ForeignKey("links.id", ondelete="SET NULL"),
    )
    length_m: Mapped[int | None] = mapped_column(Integer)
    color: Mapped[str | None] = mapped_column(String(40))
    vendor: Mapped[str | None] = mapped_column(String(100))
    part_number: Mapped[str | None] = mapped_column(String(100))
    serial: Mapped[str | None] = mapped_column(String(120))
    installed_on: Mapped[date | None] = mapped_column(Date)
    last_tested_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
