from dataclasses import dataclass
from time import time
from typing import Callable, Protocol
from uuid import uuid4

from repo_guardian.domain.tool_call import RiskTier


class CredentialError(RuntimeError):
    pass


class CredentialManagerPort(Protocol):
    def get_scoped_token(self, tier: RiskTier, tool_name: str, run_id: str) -> str: ...

    def revoke_token(self, token: str) -> None: ...


@dataclass(slots=True)
class _TokenGrant:
    tool_name: str
    run_id: str
    tier: RiskTier
    expires_at: float
    used: bool = False


class ScopedTokenFactory:
    def __init__(self, ttl_seconds: float = 30, clock: Callable[[], float] = time) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._grants: dict[str, _TokenGrant] = {}

    def get_scoped_token(self, tier: RiskTier, tool_name: str, run_id: str) -> str:
        expires_at = self._clock() + self._ttl_seconds
        token = f"{uuid4()}.{int(expires_at * 1000)}"
        self._grants[token] = _TokenGrant(tool_name, run_id, tier, expires_at)
        return token

    def validate_token(self, token: str, tool_name: str) -> None:
        grant = self._grants.get(token)
        if grant is None or grant.used:
            raise CredentialError("Token is invalid or has already been used")
        if self._clock() >= grant.expires_at:
            self._grants.pop(token, None)
            raise CredentialError("Token has expired")
        if grant.tool_name != tool_name:
            raise CredentialError("Token is not scoped to this tool")
        grant.used = True

    def revoke_token(self, token: str) -> None:
        self._grants.pop(token, None)
