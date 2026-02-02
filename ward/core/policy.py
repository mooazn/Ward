"""
Policy - Rule-based decision engine for action approval
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import re


class PolicyOutcome(Enum):
    """Possible outcomes when evaluating an action against policy"""

    ALLOW = "allow"
    DENY = "deny"
    NEEDS_HUMAN = "needs_human"


@dataclass
class PolicyRule:
    """
    A single rule in a policy.

    Rules are evaluated in order. First match wins.
    """

    name: str
    action_pattern: str  # regex pattern to match actions
    outcome: PolicyOutcome
    reason: str
    scope_constraints: Dict[str, Any] = field(default_factory=dict)
    max_duration_minutes: Optional[int] = None
    max_steps: Optional[int] = None

    def matches(self, action: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """Check if this rule matches the given action and context"""
        # Check action pattern
        if not re.match(self.action_pattern, action):
            return False

        # Check scope constraints if provided
        if context and self.scope_constraints:
            for key, expected_value in self.scope_constraints.items():
                if context.get(key) != expected_value:
                    return False

        return True


@dataclass
class Policy:
    """
    A collection of rules that determine what actions are allowed.

    Policies are evaluated top-to-bottom. First matching rule wins.
    If no rule matches, the default is DENY.
    """

    name: str
    rules: List[PolicyRule]
    default_outcome: PolicyOutcome = PolicyOutcome.DENY
    default_reason: str = "No matching policy rule"

    def evaluate(
        self, action: str, context: Optional[Dict[str, Any]] = None
    ) -> tuple[PolicyOutcome, str, Optional[PolicyRule]]:
        """
        Evaluate an action against this policy.

        Returns: (outcome, reason, matching_rule)
        """
        for rule in self.rules:
            if rule.matches(action, context):
                return (rule.outcome, rule.reason, rule)

        return (self.default_outcome, self.default_reason, None)

    def get_constraints_for_action(
        self, action: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Get the constraints that apply to this action.

        Returns a dict with max_duration_minutes, max_steps, scope, etc.
        """
        outcome, reason, rule = self.evaluate(action, context)

        if rule is None:
            return {}

        constraints = {}
        if rule.max_duration_minutes is not None:
            constraints["max_duration_minutes"] = rule.max_duration_minutes
        if rule.max_steps is not None:
            constraints["max_steps"] = rule.max_steps
        if rule.scope_constraints:
            constraints["scope"] = rule.scope_constraints

        return constraints

    @staticmethod
    def create_default() -> "Policy":
        """Create a sensible default policy for common scenarios"""
        return Policy(
            name="default",
            rules=[
                # Production operations require human approval
                PolicyRule(
                    name="production_deploy",
                    action_pattern=r"deploy_prod.*",
                    outcome=PolicyOutcome.NEEDS_HUMAN,
                    reason="Production deployments require human approval",
                ),
                PolicyRule(
                    name="production_write",
                    action_pattern=r".*_prod.*",
                    outcome=PolicyOutcome.NEEDS_HUMAN,
                    reason="Production modifications require human approval",
                ),
                # Destructive operations are denied
                PolicyRule(
                    name="delete_production",
                    action_pattern=r"delete_prod.*",
                    outcome=PolicyOutcome.DENY,
                    reason="Direct production deletion is not allowed",
                ),
                # Staging operations are allowed with limits
                PolicyRule(
                    name="staging_deploy",
                    action_pattern=r"deploy_staging",
                    outcome=PolicyOutcome.ALLOW,
                    reason="Staging deployments are pre-approved",
                    scope_constraints={"environment": "staging"},
                    max_steps=50,
                    max_duration_minutes=30,
                ),
                # Read operations are generally allowed
                PolicyRule(
                    name="read_operations",
                    action_pattern=r"read_.*|get_.*|list_.*",
                    outcome=PolicyOutcome.ALLOW,
                    reason="Read operations are safe",
                    max_steps=100,
                ),
            ],
            default_outcome=PolicyOutcome.NEEDS_HUMAN,
            default_reason="Unknown action requires human review",
        )
