"""
Revocation - Primitives for invalidating leases and tracking violations
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
import json


class RevocationReason(Enum):
    """Reasons why a lease might be revoked"""

    VIOLATED_SCOPE = "violated_scope"
    EXCEEDED_AUTHORITY = "exceeded_authority"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    HUMAN_OVERRIDE = "human_override"
    POLICY_CHANGED = "policy_changed"
    EMERGENCY_STOP = "emergency_stop"


class ViolationType(Enum):
    """Types of violations that can be detected"""

    SCOPE_VIOLATION = "scope_violation"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    SUSPICIOUS_SEQUENCE = "suspicious_sequence"
    EXPIRED_LEASE_USAGE = "expired_lease_usage"


@dataclass
class Violation:
    """
    A detected violation of lease constraints or policies.

    Violations are detected by the Watchdog and may trigger revocation.
    """

    violation_id: str
    violation_type: ViolationType
    lease_id: str
    agent_id: str
    timestamp: datetime
    description: str
    severity: str  # "low", "medium", "high", "critical"
    context: Dict[str, Any] = field(default_factory=dict)
    auto_revoke: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize violation for logging"""
        return {
            "violation_id": self.violation_id,
            "violation_type": self.violation_type.value,
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "severity": self.severity,
            "context": self.context,
            "auto_revoke": self.auto_revoke,
        }


@dataclass
class RevocationRecord:
    """
    An immutable record of a lease revocation.

    This is distinct from audit entries - it specifically tracks
    the lifecycle event of authority being withdrawn.
    """

    record_id: str
    lease_id: str
    agent_id: str
    reason: RevocationReason
    timestamp: datetime
    revoked_by: str  # "system", "human:{id}", "watchdog"
    description: str
    violations: List[str] = field(default_factory=list)  # violation_ids
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize revocation record"""
        return {
            "record_id": self.record_id,
            "lease_id": self.lease_id,
            "agent_id": self.agent_id,
            "reason": self.reason.value,
            "timestamp": self.timestamp.isoformat(),
            "revoked_by": self.revoked_by,
            "description": self.description,
            "violations": self.violations,
            "context": self.context,
        }

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(self.to_dict(), indent=2)


class RevocationLog:
    """
    Tracks all lease revocations.

    This provides a focused view of authority withdrawals,
    separate from the general audit log.
    """

    def __init__(self):
        self.records: List[RevocationRecord] = []

    def record_revocation(self, record: RevocationRecord) -> None:
        """Add a revocation record"""
        self.records.append(record)

    def get_revocations_for_agent(self, agent_id: str) -> List[RevocationRecord]:
        """Get all revocations for a specific agent"""
        return [r for r in self.records if r.agent_id == agent_id]

    def get_revocations_by_reason(
        self, reason: RevocationReason
    ) -> List[RevocationRecord]:
        """Get all revocations for a specific reason"""
        return [r for r in self.records if r.reason == reason]

    def get_recent(self, limit: int = 10) -> List[RevocationRecord]:
        """Get the most recent revocations"""
        return sorted(self.records, key=lambda r: r.timestamp, reverse=True)[:limit]

    def count_revocations(self) -> Dict[str, int]:
        """Get counts by reason"""
        counts = {}
        for record in self.records:
            reason = record.reason.value
            counts[reason] = counts.get(reason, 0) + 1
        return counts

    def to_json(self) -> str:
        """Export entire log as JSON"""
        return json.dumps([r.to_dict() for r in self.records], indent=2)
