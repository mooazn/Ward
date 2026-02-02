"""
Tests for core authority primitives
"""

import pytest
from datetime import datetime, timedelta

from ward.core import (
    Lease,
    Policy,
    PolicyRule,
    PolicyOutcome,
    Decision,
    DecisionOutcome,
    AuditEntry,
    AuditLog,
)


class TestLease:
    """Tests for Lease primitive"""

    def test_create_valid_lease(self):
        """Can create a valid lease"""
        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["deploy_staging"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        assert lease.agent_id == "agent-1"
        assert lease.is_valid()
        assert lease.can_perform("deploy_staging")

    def test_lease_expiration(self):
        """Lease becomes invalid after expiration"""
        # Should fail - can't create expired lease
        with pytest.raises(ValueError, match="cannot expire in the past"):
            Lease(
                agent_id="agent-1",
                allowed_actions=["read_logs"],
                expires_at=datetime.now() - timedelta(seconds=1),
            )

    def test_forbidden_actions_block(self):
        """Forbidden actions are denied even if allowed"""
        # Should fail - conflicting rules
        with pytest.raises(ValueError, match="cannot be both allowed and forbidden"):
            Lease(
                agent_id="agent-1",
                allowed_actions=["deploy_staging", "deploy_prod"],
                forbidden_actions=["deploy_prod"],
                expires_at=datetime.now() + timedelta(hours=1),
            )

    def test_step_limits(self):
        """Lease respects step limits"""
        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["read_logs"],
            expires_at=datetime.now() + timedelta(hours=1),
            max_steps=2,
        )

        assert lease.is_valid()

        lease.record_step()
        assert lease.steps_taken == 1
        assert lease.is_valid()

        lease.record_step()
        assert lease.steps_taken == 2
        assert not lease.is_valid()  # Exhausted

    def test_revocation(self):
        """Lease can be revoked immediately"""
        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["deploy_staging"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        assert lease.is_valid()

        lease.revoke()
        assert not lease.is_valid()
        assert not lease.can_perform("deploy_staging")


class TestPolicy:
    """Tests for Policy primitive"""

    def test_rule_matching(self):
        """Policy rules match actions correctly"""
        rule = PolicyRule(
            name="staging_deploy",
            action_pattern=r"deploy_staging",
            outcome=PolicyOutcome.ALLOW,
            reason="Staging is safe",
        )

        assert rule.matches("deploy_staging")
        assert not rule.matches("deploy_prod")

    def test_policy_evaluation(self):
        """Policy evaluates actions and returns outcomes"""
        policy = Policy(
            name="test",
            rules=[
                PolicyRule(
                    name="prod_deny",
                    action_pattern=r"deploy_prod",
                    outcome=PolicyOutcome.DENY,
                    reason="Production is locked",
                ),
                PolicyRule(
                    name="staging_allow",
                    action_pattern=r"deploy_staging",
                    outcome=PolicyOutcome.ALLOW,
                    reason="Staging is open",
                ),
            ],
        )

        outcome, reason, rule = policy.evaluate("deploy_prod")
        assert outcome == PolicyOutcome.DENY
        assert rule.name == "prod_deny"

        outcome, reason, rule = policy.evaluate("deploy_staging")
        assert outcome == PolicyOutcome.ALLOW
        assert rule.name == "staging_allow"

    def test_default_policy(self):
        """Default policy handles common scenarios"""
        policy = Policy.create_default()

        # Production requires human
        outcome, reason, _ = policy.evaluate("deploy_prod")
        assert outcome == PolicyOutcome.NEEDS_HUMAN

        # Staging is allowed
        outcome, reason, _ = policy.evaluate("deploy_staging", {"environment": "staging"})
        assert outcome == PolicyOutcome.ALLOW

        # Read is allowed
        outcome, reason, _ = policy.evaluate("read_logs")
        assert outcome == PolicyOutcome.ALLOW

    def test_scope_constraints(self):
        """Policy rules can match on context"""
        rule = PolicyRule(
            name="staging_only",
            action_pattern=r"deploy",
            outcome=PolicyOutcome.ALLOW,
            reason="Staging deploy",
            scope_constraints={"environment": "staging"},
        )

        # Matches with correct context
        assert rule.matches("deploy", {"environment": "staging"})

        # Doesn't match with wrong context
        assert not rule.matches("deploy", {"environment": "production"})


class TestDecision:
    """Tests for Decision primitive"""

    def test_approved_decision(self):
        """Can create an approved decision with lease"""
        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["deploy"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        decision = Decision.approve(
            agent_id="agent-1",
            requested_action="deploy",
            lease=lease,
            reason="Policy allows this",
        )

        assert decision.is_approved()
        assert not decision.is_denied()
        assert decision.lease is not None

    def test_denied_decision(self):
        """Can create a denied decision"""
        decision = Decision.deny(
            agent_id="agent-1",
            requested_action="deploy_prod",
            reason="Production is locked",
        )

        assert decision.is_denied()
        assert not decision.is_approved()
        assert decision.lease is None

    def test_needs_human_decision(self):
        """Can create a needs-human decision"""
        decision = Decision.needs_human(
            agent_id="agent-1",
            requested_action="delete_database",
            reason="This is too risky",
            context={"database": "production"},
        )

        assert decision.needs_human_approval()
        assert not decision.is_approved()
        assert not decision.is_denied()


class TestAudit:
    """Tests for AuditEntry and AuditLog"""

    def test_audit_from_decision(self):
        """Can create audit entry from decision"""
        decision = Decision.deny(
            agent_id="agent-1",
            requested_action="deploy_prod",
            reason="Locked",
        )

        entry = AuditEntry.from_decision(
            entry_id="audit-1",
            decision=decision,
            known_unknowns=["infra drift", "db migration state"],
        )

        assert entry.event_type == "decision"
        assert entry.agent_id == "agent-1"
        assert len(entry.known_unknowns) == 2

    def test_audit_from_action(self):
        """Can create audit entry from action"""
        entry = AuditEntry.from_action(
            entry_id="audit-2",
            agent_id="agent-1",
            action="deploy_staging",
            result={"status": "success", "version": "v1.2.3"},
            known_unknowns=["downstream impact"],
        )

        assert entry.event_type == "action"
        assert entry.action_taken == "deploy_staging"
        assert entry.action_result["status"] == "success"

    def test_audit_log(self):
        """AuditLog can store and query entries"""
        log = AuditLog()

        # Add some entries
        entry1 = AuditEntry.from_action(
            entry_id="1",
            agent_id="agent-1",
            action="deploy",
        )
        entry2 = AuditEntry.from_action(
            entry_id="2",
            agent_id="agent-2",
            action="read_logs",
            known_unknowns=["cache staleness"],
        )

        log.append(entry1)
        log.append(entry2)

        # Query by agent
        agent1_entries = log.get_entries_for_agent("agent-1")
        assert len(agent1_entries) == 1

        # Query by type
        action_entries = log.get_entries_by_type("action")
        assert len(action_entries) == 2

        # Query by unknown
        cache_entries = log.get_entries_with_unknown("cache staleness")
        assert len(cache_entries) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
