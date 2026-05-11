"""Auth provider abstraction.

Each provider knows how to:
  1. Build the authorize redirect that sends the browser to the IdP.
  2. Process the callback and return a `UserInfo` for JIT user upsert.

The backend persists `(provider, subject)` from `UserInfo` as the stable user
identity, so swapping providers later only requires re-onboarding users.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from fastapi import Request, Response


@dataclass(frozen=True)
class UserInfo:
    """Identity returned by the provider after a successful login.

    Attributes:
        subject: Opaque, stable identifier of the user at the provider.
            GitHub: numeric `user.id` rendered as string.
            OIDC: the `sub` claim.
        email: Primary email of the user. Required by Netforge.
        display_name: Optional human-readable name.
    """

    subject: str
    email: str
    display_name: str | None = None


class AuthProvider(ABC):
    """Pluggable auth provider interface."""

    #: Short stable provider key persisted on `users.provider`.
    name: str

    @abstractmethod
    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        """Return a 302 redirect to the IdP authorize URL."""

    @abstractmethod
    async def authenticate(self, request: Request) -> UserInfo:
        """Process the IdP callback: exchange the code, return the user identity."""
