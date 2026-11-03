"""Who is acting. Services take a Principal rather than anything HTTP-specific, so workers and
scripts can call them too."""

from __future__ import annotations

from dataclasses import dataclass

from khataiq.models.enums import UserRole


@dataclass(frozen=True)
class Principal:
    id: int
    org_id: int
    role: UserRole

    @property
    def is_owner(self) -> bool:
        return self.role == UserRole.OWNER
