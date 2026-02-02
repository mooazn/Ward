"""
Watchdog - Monitors leases and detects violations
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from collections import defaultdict

from .lease import Lease
from .revocation import Violation, ViolationType, RevocationReason


@dataclass
class WatchdogRule:
    """
    A rule that defines what the watchdog should check.

    Rules are deterministic checks against lease behavior.
    """

    name: str
    check: Callable[[Lease, Dict[str, Any]], Optional[Violation]]
    severity: str  # "low", "medium", "high", "critical"
    auto_revoke: bool = False
    description: str = ""


class Watchdog:
    """
    Monitors active leases and detects violations.

    The Watchdog is purely reactive - it checks constraints
    and reports violations. It does not make decisions.
    """

    def __init__(self):
        self.rules: List[WatchdogRule] = []
        self.violations: List[Violation] = []
        self.action_history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    def add_rule(self, rule: WatchdogRule) -> None:
        """Add a monitoring rule"""
        self.rules.append(rule)

    def check_lease(
        self, lease: Lease, context: Optional[Dict[str, Any]] = None
    ) -> List[Violation]:
        """
        Check a lease against all watchdog rules.

        Returns a list of detected violations.
        """
        context = context or {}
        violations = []

        for rule in self.rules:
            violation = rule.check(lease, context)
            if violation:
                violation.auto_revoke = rule.auto_revoke
                violations.append(violation)
                self.violations.append(violation)

        return violations

    def record_action(
        self, lease_id: str, action: str, result: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record an action for pattern analysis.

        This builds history that can be used for suspicious pattern detection.
        """
        self.action_history[lease_id].append(
            {
                "action": action,
                "timestamp": datetime.now(),
                "result": result or {},
            }
        )

    def get_violations_for_lease(self, lease_id: str) -> List[Violation]:
        """Get all violations for a specific lease"""
        return [v for v in self.violations if v.lease_id == lease_id]

    def get_violations_requiring_revocation(self) -> List[Violation]:
        """Get all violations marked for auto-revocation"""
        return [v for v in self.violations if v.auto_revoke]

    def clear_violations_for_lease(self, lease_id: str) -> None:
        """Clear violations for a revoked/expired lease"""
        self.violations = [v for v in self.violations if v.lease_id != lease_id]
        if lease_id in self.action_history:
            del self.action_history[lease_id]

    @staticmethod
    def create_default_rules() -> List[WatchdogRule]:
        """
        Create a set of sensible default watchdog rules.

        These are boring, deterministic checks.
        """

        def check_expired_usage(
            lease: Lease, context: Dict[str, Any]
        ) -> Optional[Violation]:
            """Check if an expired lease is being used"""
            if not lease.is_valid() and datetime.now() >= lease.expires_at:
                return Violation(
                    violation_id=f"violation-{datetime.now().timestamp()}",
                    violation_type=ViolationType.EXPIRED_LEASE_USAGE,
                    lease_id=lease.lease_id,
                    agent_id=lease.agent_id,
                    timestamp=datetime.now(),
                    description="Attempted to use expired lease",
                    severity="high",
                    context={"expires_at": lease.expires_at.isoformat()},
                )
            return None

        def check_scope_violation(
            lease: Lease, context: Dict[str, Any]
        ) -> Optional[Violation]:
            """Check if action violates lease scope"""
            action = context.get("action")
            if not action:
                return None

            if action not in lease.allowed_actions:
                return Violation(
                    violation_id=f"violation-{datetime.now().timestamp()}",
                    violation_type=ViolationType.ACTION_NOT_ALLOWED,
                    lease_id=lease.lease_id,
                    agent_id=lease.agent_id,
                    timestamp=datetime.now(),
                    description=f"Action '{action}' not in allowed actions",
                    severity="high",
                    context={
                        "attempted_action": action,
                        "allowed_actions": lease.allowed_actions,
                    },
                )
            return None

        def check_rate_limit(
            lease: Lease, context: Dict[str, Any]
        ) -> Optional[Violation]:
            """Check if lease is being used too rapidly"""
            if lease.max_steps and lease.steps_taken > lease.max_steps * 1.1:
                return Violation(
                    violation_id=f"violation-{datetime.now().timestamp()}",
                    violation_type=ViolationType.RATE_LIMIT_EXCEEDED,
                    lease_id=lease.lease_id,
                    agent_id=lease.agent_id,
                    timestamp=datetime.now(),
                    description=f"Exceeded step limit by >10%",
                    severity="medium",
                    context={
                        "max_steps": lease.max_steps,
                        "steps_taken": lease.steps_taken,
                    },
                )
            return None

        return [
            WatchdogRule(
                name="expired_lease_check",
                check=check_expired_usage,
                severity="high",
                auto_revoke=True,
                description="Detect usage of expired leases",
            ),
            WatchdogRule(
                name="scope_violation_check",
                check=check_scope_violation,
                severity="high",
                auto_revoke=True,
                description="Detect actions outside lease scope",
            ),
            WatchdogRule(
                name="rate_limit_check",
                check=check_rate_limit,
                severity="medium",
                auto_revoke=False,
                description="Detect excessive action rates",
            ),
        ]


def create_watchdog_with_defaults() -> Watchdog:
    """Create a Watchdog with default rules installed"""
    watchdog = Watchdog()
    for rule in Watchdog.create_default_rules():
        watchdog.add_rule(rule)
    return watchdog
