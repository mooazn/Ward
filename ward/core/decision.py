"""
Decision - The output of evaluating an action request
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum

from .lease import Lease


class DecisionOutcome(Enum):
    """Possible outcomes when an agent requests authority"""

    APPROVED = "approved"
    DENIED = "denied"
    NEEDS_HUMAN = "needs_human"


@dataclass
class Decision:
    """
    The result of evaluating whether an agent should be allowed
    to perform an action.

    This is what the authority system returns.
    """

    outcome: DecisionOutcome
    agent_id: str
    requested_action: str
    reason: str
    timestamp: datetime = field(default_factory=datetime.now)
    lease: Optional[Lease] = None
    constraints: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    policy_name: Optional[str] = None
    rule_name: Optional[str] = None

    def is_approved(self) -> bool:
        """Check if this decision grants authority"""
        return self.outcome == DecisionOutcome.APPROVED and self.lease is not None

    def is_denied(self) -> bool:
        """Check if this decision denies authority"""
        return self.outcome == DecisionOutcome.DENIED

    def needs_human_approval(self) -> bool:
        """Check if this decision requires human intervention"""
        return self.outcome == DecisionOutcome.NEEDS_HUMAN

    def to_dict(self) -> Dict[str, Any]:
        """Serialize decision for logging/transmission"""
        result = {
            "outcome": self.outcome.value,
            "agent_id": self.agent_id,
            "requested_action": self.requested_action,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "constraints": self.constraints,
            "context": self.context,
            "policy_name": self.policy_name,
            "rule_name": self.rule_name,
        }

        if self.lease:
            result["lease"] = self.lease.to_dict()

        return result

    @staticmethod
    def approve(
        agent_id: str,
        requested_action: str,
        lease: Lease,
        reason: str,
        constraints: Optional[Dict[str, Any]] = None,
        policy_name: Optional[str] = None,
        rule_name: Optional[str] = None,
    ) -> "Decision":
        """Create an approval decision with a lease"""
        return Decision(
            outcome=DecisionOutcome.APPROVED,
            agent_id=agent_id,
            requested_action=requested_action,
            reason=reason,
            lease=lease,
            constraints=constraints or {},
            policy_name=policy_name,
            rule_name=rule_name,
        )

    @staticmethod
    def deny(
        agent_id: str,
        requested_action: str,
        reason: str,
        policy_name: Optional[str] = None,
        rule_name: Optional[str] = None,
    ) -> "Decision":
        """Create a denial decision"""
        return Decision(
            outcome=DecisionOutcome.DENIED,
            agent_id=agent_id,
            requested_action=requested_action,
            reason=reason,
            policy_name=policy_name,
            rule_name=rule_name,
        )

    @staticmethod
    def needs_human(
        agent_id: str,
        requested_action: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        policy_name: Optional[str] = None,
        rule_name: Optional[str] = None,
    ) -> "Decision":
        """Create a decision that requires human approval"""
        return Decision(
            outcome=DecisionOutcome.NEEDS_HUMAN,
            agent_id=agent_id,
            requested_action=requested_action,
            reason=reason,
            context=context or {},
            policy_name=policy_name,
            rule_name=rule_name,
        )
