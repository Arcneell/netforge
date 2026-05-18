"""SQLAlchemy models — imported here so Alembic picks them all up."""

from app.models.ai import (
    AIRunKind,
    AIRunLog,
    InfraInsight,
    InsightCategory,
    InsightSeverity,
    LinkSuggestion,
    LinkSuggestionStatus,
)
from app.models.base import Base
from app.models.core import Room, Site
from app.models.device import Device
from app.models.ip import Ip
from app.models.link import Link
from app.models.port import Port, PortVlan
from app.models.subnet import Subnet
from app.models.switch import Switch
from app.models.user import ApiToken, AuditLog, Session, User
from app.models.vlan import Vlan

__all__ = [
    "AIRunKind",
    "AIRunLog",
    "ApiToken",
    "AuditLog",
    "Base",
    "Device",
    "InfraInsight",
    "InsightCategory",
    "InsightSeverity",
    "Ip",
    "Link",
    "LinkSuggestion",
    "LinkSuggestionStatus",
    "Port",
    "PortVlan",
    "Room",
    "Session",
    "Site",
    "Subnet",
    "Switch",
    "User",
    "Vlan",
]
