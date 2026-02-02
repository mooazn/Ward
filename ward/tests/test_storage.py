"""
Tests for persistent SQLite storage backend
"""

import pytest
import tempfile
import os
from datetime import datetime
from pathlib import Path

from ward.storage import SQLiteAuditBackend


class TestSQLiteBackend:
    """Tests for SQLite persistent storage"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        yield path
        # Cleanup
        if os.path.exists(path):
            os.remove(path)

    @pytest.fixture
    def backend(self, temp_db):
        """Create backend with temp database"""
        return SQLiteAuditBackend(temp_db)

    def test_init_creates_schema(self, temp_db):
        """Backend initialization creates all tables"""
        backend = SQLiteAuditBackend(temp_db)

        # Verify tables exist by querying them
        assert backend.count_decisions() == 0
        assert backend.count_actions() == 0
        assert backend.count_revocations() == 0

    def test_record_decision(self, backend):
        """Can record and retrieve a decision"""
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy_staging",
            outcome="approved",
            reason="Policy allows staging deploys",
            known_unknowns=["blast radius", "rollback plan"],
            context={"environment": "staging"},
            policy_name="default",
            rule_name="staging_deploy",
            lease_id="lease-123",
        )

        decisions = backend.get_decisions()
        assert len(decisions) == 1

        dec = decisions[0]
        assert dec["id"] == "dec-1"
        assert dec["agent_id"] == "agent-1"
        assert dec["action"] == "deploy_staging"
        assert dec["outcome"] == "approved"
        assert dec["known_unknowns"] == ["blast radius", "rollback plan"]
        assert dec["context"]["environment"] == "staging"

    def test_record_action(self, backend):
        """Can record and retrieve an action"""
        backend.record_action(
            action_id="act-1",
            agent_id="agent-1",
            action="deploy_staging",
            status="success",
            lease_id="lease-123",
            result={"version": "v1.2.3", "duration": 45},
            context={"server": "staging-1"},
            tags=["deploy", "success"],
        )

        actions = backend.get_actions()
        assert len(actions) == 1

        act = actions[0]
        assert act["id"] == "act-1"
        assert act["agent_id"] == "agent-1"
        assert act["status"] == "success"
        assert act["result"]["version"] == "v1.2.3"
        assert act["tags"] == ["deploy", "success"]

    def test_record_revocation(self, backend):
        """Can record and retrieve a revocation"""
        backend.record_revocation(
            revocation_id="rev-1",
            lease_id="lease-123",
            agent_id="agent-1",
            reason="violated_scope",
            revoked_by="watchdog",
            description="Attempted unauthorized action",
            violations=["viol-1", "viol-2"],
        )

        revocations = backend.get_revocations()
        assert len(revocations) == 1

        rev = revocations[0]
        assert rev["id"] == "rev-1"
        assert rev["lease_id"] == "lease-123"
        assert rev["reason"] == "violated_scope"
        assert rev["revoked_by"] == "watchdog"
        assert rev["violations"] == ["viol-1", "viol-2"]

    def test_query_decisions_by_agent(self, backend):
        """Can query decisions by agent_id"""
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="OK",
        )
        backend.record_decision(
            decision_id="dec-2",
            agent_id="agent-2",
            action="deploy",
            outcome="denied",
            reason="Not OK",
        )

        agent1_decisions = backend.get_decisions(agent_id="agent-1")
        assert len(agent1_decisions) == 1
        assert agent1_decisions[0]["agent_id"] == "agent-1"

    def test_query_decisions_by_outcome(self, backend):
        """Can query decisions by outcome"""
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="OK",
        )
        backend.record_decision(
            decision_id="dec-2",
            agent_id="agent-2",
            action="deploy",
            outcome="needs_human",
            reason="Requires approval",
        )

        pending = backend.get_decisions(outcome="needs_human")
        assert len(pending) == 1
        assert pending[0]["outcome"] == "needs_human"

    def test_query_actions_by_lease(self, backend):
        """Can query actions by lease_id"""
        backend.record_action(
            action_id="act-1",
            agent_id="agent-1",
            action="deploy",
            status="success",
            lease_id="lease-123",
        )
        backend.record_action(
            action_id="act-2",
            agent_id="agent-1",
            action="read",
            status="success",
            lease_id="lease-456",
        )

        lease_actions = backend.get_actions(lease_id="lease-123")
        assert len(lease_actions) == 1
        assert lease_actions[0]["lease_id"] == "lease-123"

    def test_get_pending_approvals(self, backend):
        """Can get decisions needing human approval"""
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy_prod",
            outcome="needs_human",
            reason="Production requires approval",
        )
        backend.record_decision(
            decision_id="dec-2",
            agent_id="agent-2",
            action="read_logs",
            outcome="approved",
            reason="Read is safe",
        )

        pending = backend.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0]["outcome"] == "needs_human"

    def test_persistence_across_connections(self, temp_db):
        """Data persists across backend instances"""
        # Write with first instance
        backend1 = SQLiteAuditBackend(temp_db)
        backend1.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="Test",
        )

        # Read with second instance
        backend2 = SQLiteAuditBackend(temp_db)
        decisions = backend2.get_decisions()

        assert len(decisions) == 1
        assert decisions[0]["id"] == "dec-1"

    def test_query_limit(self, backend):
        """Query limit works correctly"""
        # Create 10 decisions
        for i in range(10):
            backend.record_decision(
                decision_id=f"dec-{i}",
                agent_id="agent-1",
                action="test",
                outcome="approved",
                reason="Test",
            )

        # Query with limit
        decisions = backend.get_decisions(limit=5)
        assert len(decisions) == 5

    def test_count_methods(self, backend):
        """Count methods return correct totals"""
        # Add some records
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="Test",
        )
        backend.record_action(
            action_id="act-1",
            agent_id="agent-1",
            action="deploy",
            status="success",
        )
        backend.record_revocation(
            revocation_id="rev-1",
            lease_id="lease-1",
            agent_id="agent-1",
            reason="test",
            revoked_by="human",
            description="Test revocation",
        )

        assert backend.count_decisions() == 1
        assert backend.count_actions() == 1
        assert backend.count_revocations() == 1

    def test_timestamp_handling(self, backend):
        """Timestamps are stored and retrieved correctly"""
        now = datetime.now()

        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="Test",
            timestamp=now,
        )

        decisions = backend.get_decisions()
        # Timestamp is stored as ISO format string
        assert decisions[0]["timestamp"] == now.isoformat()

    def test_empty_lists_handled(self, backend):
        """Empty lists are handled correctly"""
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="Test",
            known_unknowns=[],  # Empty list
        )

        decisions = backend.get_decisions()
        assert decisions[0]["known_unknowns"] == []

    def test_none_optional_fields(self, backend):
        """None values for optional fields are handled"""
        backend.record_decision(
            decision_id="dec-1",
            agent_id="agent-1",
            action="deploy",
            outcome="approved",
            reason="Test",
            # All optional fields None
        )

        decisions = backend.get_decisions()
        assert decisions[0]["known_unknowns"] == []
        assert decisions[0]["context"] == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
