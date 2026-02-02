"""
Lease - Represents granted authority to an agent
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from .revocation import RevocationReason


@dataclass
class Lease:
    """
    A Lease grants an agent explicit authority to perform actions
    within constraints and expiration.

    This is the fundamental unit of delegation in the authority system.
    """

    agent_id: str
    allowed_actions: List[str]
    expires_at: datetime
    lease_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    forbidden_actions: List[str] = field(default_factory=list)
    max_steps: Optional[int] = None
    scope: Dict[str, Any] = field(default_factory=dict)
    steps_taken: int = 0
    revoked: bool = False
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revocation_reason: Optional[str] = None  # Store as string to avoid circular import

    def __post_init__(self):
        """Validate the lease on creation"""
        if self.expires_at <= datetime.now():
            raise ValueError("Lease cannot expire in the past")

        if self.max_steps is not None and self.max_steps <= 0:
            raise ValueError("max_steps must be positive if specified")

        # Check for conflicts
        conflicts = set(self.allowed_actions) & set(self.forbidden_actions)
        if conflicts:
            raise ValueError(f"Actions cannot be both allowed and forbidden: {conflicts}")

    def is_valid(self) -> bool:
        """Check if lease is currently valid"""
        if self.revoked:
            return False

        if datetime.now() >= self.expires_at:
            return False

        if self.max_steps is not None and self.steps_taken >= self.max_steps:
            return False

        return True

    def can_perform(self, action: str) -> bool:
        """Check if this lease allows a specific action"""
        if not self.is_valid():
            return False

        # Explicit deny takes precedence
        if action in self.forbidden_actions:
            return False

        # Must be explicitly allowed
        return action in self.allowed_actions

    def record_step(self) -> None:
        """Record that the agent took one step under this lease"""
        if not self.is_valid():
            raise ValueError("Cannot record step on invalid lease")

        self.steps_taken += 1

    def revoke(
        self, reason: Optional[str] = None, revoked_by: Optional[str] = None
    ) -> None:
        """
        Immediately invalidate this lease.

        Args:
            reason: Why the lease was revoked (RevocationReason value)
            revoked_by: Who/what revoked it (e.g., "human:user123", "watchdog", "system")
        """
        self.revoked = True
        self.revoked_at = datetime.now()
        self.revocation_reason = reason
        self.revoked_by = revoked_by

    def to_dict(self) -> Dict[str, Any]:
        """Serialize lease for logging/transmission"""
        result = {
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "allowed_actions": self.allowed_actions,
            "forbidden_actions": self.forbidden_actions,
            "expires_at": self.expires_at.isoformat(),
            "max_steps": self.max_steps,
            "scope": self.scope,
            "steps_taken": self.steps_taken,
            "revoked": self.revoked,
            "is_valid": self.is_valid(),
        }

        if self.revoked:
            result["revoked_at"] = (
                self.revoked_at.isoformat() if self.revoked_at else None
            )
            result["revoked_by"] = self.revoked_by
            result["revocation_reason"] = self.revocation_reason

        return result
