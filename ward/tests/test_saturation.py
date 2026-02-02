"""
Tests for Decision Saturation tracking (v2.5)
"""

import pytest
import tempfile
import os

from ward.storage import SQLiteAuditBackend


class TestDecisionSaturation:
    """Tests for human approval tracking and saturation metrics"""

    def test_record_human_approval(self):
        """Records human approval with constraint tracking"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            # Record an approval
            backend.record_human_approval(
                approval_id="human-1",
                decision_id="dec-1",
                human_outcome="approved",
                recommended_max_steps=1,
                actual_max_steps=1,
                recommended_duration_minutes=5,
                actual_duration_minutes=5,
                missing_info_questions=["backup_status"],
                missing_info_resolved=["backup_verified"],
            )

            # Retrieve approvals
            approvals = backend.get_human_approvals()

            assert len(approvals) == 1
            assert approvals[0]["decision_id"] == "dec-1"
            assert approvals[0]["human_outcome"] == "approved"
            assert approvals[0]["constraints_modified"] is False
        finally:
            os.unlink(db_path)

    def test_track_constraint_modification(self):
        """Detects when human modifies recommended constraints"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            # Human overrides recommendation
            backend.record_human_approval(
                approval_id="human-1",
                decision_id="dec-1",
                human_outcome="approved",
                recommended_max_steps=1,
                actual_max_steps=5,  # Human overrode
                recommended_duration_minutes=5,
                actual_duration_minutes=10,  # Human overrode
            )

            approvals = backend.get_human_approvals()

            assert approvals[0]["constraints_modified"] is True
        finally:
            os.unlink(db_path)

    def test_calculate_saturation_insufficient_data(self):
        """Returns insufficient_data status with no decisions"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            metrics = backend.calculate_decision_saturation()

            assert metrics["total_decisions"] == 0
            assert metrics["saturation_score"] == 0.0
            assert metrics["status"] == "insufficient_data"
            assert metrics["ready_for_llm"] is False
        finally:
            os.unlink(db_path)

    def test_calculate_saturation_with_data(self):
        """Calculates saturation metrics correctly"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            # Record 10 approvals, 8 accepting recommendations
            for i in range(8):
                backend.record_human_approval(
                    approval_id=f"human-{i}",
                    decision_id=f"dec-{i}",
                    human_outcome="approved",
                    recommended_max_steps=1,
                    actual_max_steps=1,  # Accepted
                    recommended_duration_minutes=5,
                    actual_duration_minutes=5,  # Accepted
                    missing_info_questions=["status"],
                    missing_info_resolved=["answered"],
                )

            # 2 with overrides
            for i in range(8, 10):
                backend.record_human_approval(
                    approval_id=f"human-{i}",
                    decision_id=f"dec-{i}",
                    human_outcome="approved",
                    recommended_max_steps=1,
                    actual_max_steps=10,  # Overridden
                )

            metrics = backend.calculate_decision_saturation()

            assert metrics["total_decisions"] == 10
            assert metrics["constraints_acceptance_rate"] == 0.8  # 80%
            assert metrics["saturation_score"] > 0.0
            assert metrics["status"] == "collecting_data"  # Not enough decisions yet
            assert metrics["ready_for_llm"] is False  # Need 200 decisions
        finally:
            os.unlink(db_path)

    def test_saturation_ready_for_llm(self):
        """Correctly identifies LLM readiness"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            # Record 200 approvals with high saturation
            for i in range(200):
                backend.record_human_approval(
                    approval_id=f"human-{i}",
                    decision_id=f"dec-{i}",
                    human_outcome="approved",
                    recommended_max_steps=1,
                    actual_max_steps=1,
                    recommended_duration_minutes=5,
                    actual_duration_minutes=5,
                    missing_info_questions=["status"],
                    missing_info_resolved=["answered"],
                )

            metrics = backend.calculate_decision_saturation()

            assert metrics["total_decisions"] >= 200
            assert metrics["saturation_score"] >= 0.8
            assert metrics["ready_for_llm"] is True
        finally:
            os.unlink(db_path)

    def test_record_denial(self):
        """Records human denials"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            backend.record_human_approval(
                approval_id="human-1",
                decision_id="dec-1",
                human_outcome="denied",
                missing_info_questions=["critical_info"],
                missing_info_resolved=[],  # Not resolved
            )

            approvals = backend.get_human_approvals()

            assert len(approvals) == 1
            assert approvals[0]["human_outcome"] == "denied"
        finally:
            os.unlink(db_path)

    def test_missing_info_tracking(self):
        """Tracks missing information questions and resolution"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            backend = SQLiteAuditBackend(db_path)

            backend.record_human_approval(
                approval_id="human-1",
                decision_id="dec-1",
                human_outcome="approved",
                missing_info_questions=["backup_status", "deployment_window", "rollback_plan"],
                missing_info_resolved=["backup_status", "deployment_window"],  # 2 of 3 resolved
            )

            approvals = backend.get_human_approvals()

            assert len(approvals[0]["missing_info_questions"]) == 3
            assert len(approvals[0]["missing_info_resolved"]) == 2
        finally:
            os.unlink(db_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
