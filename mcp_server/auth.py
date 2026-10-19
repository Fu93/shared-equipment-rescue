"""Authentication: Bearer token -> account. Identity NEVER comes from args."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import constants as C


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    role: str


_PRINCIPALS: dict[str, Principal] = {
    C.TOKEN_MANAGER: Principal("user-manager", "Facility Manager", "manager"),
    C.TOKEN_CHEN: Principal("user-chen", "Chen", "researcher"),
    C.TOKEN_WANG: Principal("user-wang", "Wang", "researcher"),
    C.TOKEN_LI: Principal("user-li", "Li", "researcher"),
}


def principal_from_headers(get_header) -> Optional[Principal]:
    """get_header(name) -> Optional[str]; case-insensitive lookup is caller's job."""
    auth = get_header("authorization")
    if not auth:
        return None
    parts = auth.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return _PRINCIPALS.get(parts[1].strip())


def has_permission(principal: Principal, equipment_id: str, perms: dict[str, set]) -> bool:
    return principal.user_id in perms.get(equipment_id, set())
