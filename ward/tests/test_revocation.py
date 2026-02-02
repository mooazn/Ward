"""
Tests for revocation and watchdog functionality
"""

import pytest
from datetime import datetime, timedelta

from ward.core import (
    Lease,
    RevocationReason,
    RevocationRecord,
    RevocationLog,
    Violation,
    ViolationType,
    Watchdog,
    WatchdogRule,
    create_watchdog_with_defaults,
)


class TestRevocation:
    """Tests for revocation primitives"""

    def test_lease_revocation(self):
        """Can revoke a lease with reason"""
        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["deploy"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        assert lease.is_valid()
        assert not lease.revoked

        lease.revoke(
            reason=RevocationReason.HUMAN_OVERRIDE.value, revoked_by="admin:user123"
        )

        assert lease.revoked
        assert not lease.is_valid()
        assert lease.revocation_reason == RevocationReason.HUMAN_OVERRIDE.value
        assert lease.revoked_by == "admin:user123"
        assert lease.revoked_at is not None

    def test_revocation_record(self):
        """Can create revocation records"""
        record = RevocationRecord(
            record_id="rev-1",
            lease_id="lease-123",
            agent_id="agent-1",
            reason=RevocationReason.VIOLATED_SCOPE,
            timestamp=datetime.now(),
            revoked_by="watchdog",
            description="Agent exceeded allowed scope",
            violations=["violation-1", "violation-2"],
        )

        assert record.reason == RevocationReason.VIOLATED_SCOPE
        assert len(record.violations) == 2

        # Can serialize
        data = record.to_dict()
        assert data["reason"] == "violated_scope"
        assert data["revoked_by"] == "watchdog"

    def test_revocation_log(self):
        """RevocationLog tracks revocations"""
        log = RevocationLog()

        record1 = RevocationRecord(
            record_id="rev-1",
            lease_id="lease-1",
            agent_id="agent-1",
            reason=RevocationReason.HUMAN_OVERRIDE,
            timestamp=datetime.now(),
            revoked_by="human",
            description="Manual revocation",
        )

        record2 = RevocationRecord(
            record_id="rev-2",
            lease_id="lease-2",
            agent_id="agent-1",
            reason=RevocationReason.VIOLATED_SCOPE,
            timestamp=datetime.now(),
            revoked_by="watchdog",
            description="Scope violation",
        )

        log.record_revocation(record1)
        log.record_revocation(record2)

        # Query by agent
        agent1_revocations = log.get_revocations_for_agent("agent-1")
        assert len(agent1_revocations) == 2

        # Query by reason
        human_revocations = log.get_revocations_by_reason(
            RevocationReason.HUMAN_OVERRIDE
        )
        assert len(human_revocations) == 1

        # Count by reason
        counts = log.count_revocations()
        assert counts["human_override"] == 1
        assert counts["violated_scope"] == 1


class TestViolation:
    """Tests for Violation primitive"""

    def test_create_violation(self):
        """Can create a violation"""
        violation = Violation(
            violation_id="viol-1",
            violation_type=ViolationType.SCOPE_VIOLATION,
            lease_id="lease-123",
            agent_id="agent-1",
            timestamp=datetime.now(),
            description="Action not allowed",
            severity="high",
            context={"attempted_action": "delete_prod"},
        )

        assert violation.violation_type == ViolationType.SCOPE_VIOLATION
        assert violation.severity == "high"
        assert not violation.auto_revoke

    def test_violation_serialization(self):
        """Violations can be serialized"""
        violation = Violation(
            violation_id="viol-1",
            violation_type=ViolationType.EXPIRED_LEASE_USAGE,
            lease_id="lease-123",
            agent_id="agent-1",
            timestamp=datetime.now(),
            description="Used expired lease",
            severity="critical",
            auto_revoke=True,
        )

        data = violation.to_dict()
        assert data["violation_type"] == "expired_lease_usage"
        assert data["severity"] == "critical"
        assert data["auto_revoke"] is True


class TestWatchdog:
    """Tests for Watchdog"""

    def test_create_watchdog(self):
        """Can create a watchdog"""
        watchdog = Watchdog()
        assert len(watchdog.rules) == 0
        assert len(watchdog.violations) == 0

    def test_create_with_defaults(self):
        """Can create watchdog with default rules"""
        watchdog = create_watchdog_with_defaults()
        assert len(watchdog.rules) > 0

    def test_add_rule(self):
        """Can add custom rules to watchdog"""
        watchdog = Watchdog()

        def custom_check(lease, context):
            if lease.steps_taken > 10:
                return Violation(
                    violation_id="test",
                    violation_type=ViolationType.RATE_LIMIT_EXCEEDED,
                    lease_id=lease.lease_id,
                    agent_id=lease.agent_id,
                    timestamp=datetime.now(),
                    description="Too many steps",
                    severity="medium",
                )
            return None

        rule = WatchdogRule(
            name="custom",
            check=custom_check,
            severity="medium",
            description="Custom check",
        )

        watchdog.add_rule(rule)
        assert len(watchdog.rules) == 1

    def test_check_lease_no_violations(self):
        """Checking valid lease returns no violations"""
        watchdog = create_watchdog_with_defaults()

        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["read_logs"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        violations = watchdog.check_lease(lease)
        assert len(violations) == 0

    def test_detect_scope_violation(self):
        """Watchdog detects scope violations"""
        watchdog = create_watchdog_with_defaults()

        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["read_logs"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        # Try an action not in allowed list
        violations = watchdog.check_lease(lease, context={"action": "delete_database"})

        assert len(violations) > 0
        assert violations[0].violation_type == ViolationType.ACTION_NOT_ALLOWED
        assert violations[0].auto_revoke is True

    def test_detect_expired_usage(self):
        """Watchdog detects expired lease usage"""
        watchdog = create_watchdog_with_defaults()

        # Create an expired lease (by setting expires_at in past after creation)
        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["read_logs"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        # Manually set expiration to past (simulating time passing)
        lease.expires_at = datetime.now() - timedelta(seconds=1)

        violations = watchdog.check_lease(lease)

        # Should detect expired usage
        expired_violations = [
            v
            for v in violations
            if v.violation_type == ViolationType.EXPIRED_LEASE_USAGE
        ]
        assert len(expired_violations) > 0
        assert expired_violations[0].auto_revoke is True

    def test_action_history(self):
        """Watchdog records action history"""
        watchdog = Watchdog()

        watchdog.record_action("lease-1", "deploy", {"status": "success"})
        watchdog.record_action("lease-1", "read_logs", {"status": "success"})

        assert len(watchdog.action_history["lease-1"]) == 2
        assert watchdog.action_history["lease-1"][0]["action"] == "deploy"

    def test_clear_violations(self):
        """Can clear violations for a lease"""
        watchdog = create_watchdog_with_defaults()

        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["read_logs"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        # Generate violation
        violations = watchdog.check_lease(lease, context={"action": "delete_database"})
        assert len(violations) > 0
        assert len(watchdog.violations) > 0

        # Clear violations
        watchdog.clear_violations_for_lease(lease.lease_id)
        remaining = watchdog.get_violations_for_lease(lease.lease_id)
        assert len(remaining) == 0

    def test_get_violations_requiring_revocation(self):
        """Can filter violations that require revocation"""
        watchdog = create_watchdog_with_defaults()

        lease = Lease(
            agent_id="agent-1",
            allowed_actions=["read_logs"],
            expires_at=datetime.now() + timedelta(hours=1),
        )

        # Generate violation that requires auto-revoke
        violations = watchdog.check_lease(lease, context={"action": "delete_database"})

        auto_revoke = watchdog.get_violations_requiring_revocation()
        assert len(auto_revoke) > 0
        assert all(v.auto_revoke for v in auto_revoke)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
