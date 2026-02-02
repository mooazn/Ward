"""
Tests for Decision Intelligence (v2)
"""

import pytest
from datetime import datetime

from ward.intelligence import RulesBasedGenerator, RiskLevel, Environment


class TestRulesBasedGenerator:
    """Tests for rules-based DIR generation"""

    def test_detect_destructive_rm(self):
        """Detects rm -rf as high risk"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-1",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "rm -rf /tmp/data"},
        )

        assert dir_report.request_facts.is_destructive
        assert dir_report.risk_assessment.risk_level == RiskLevel.HIGH
        assert any(rf.code == "DESTRUCTIVE_RM" for rf in dir_report.risk_assessment.risk_factors)

    def test_detect_production_environment(self):
        """Detects production environment"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-2",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "rm -rf /prod/data"},
        )

        assert dir_report.request_facts.env == Environment.PROD

    def test_critical_risk_for_destructive_in_prod(self):
        """Destructive + production = critical risk"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-3",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "rm -rf /prod/database"},
        )

        assert dir_report.risk_assessment.risk_level == RiskLevel.CRITICAL
        assert any(
            rf.code == "DESTRUCTIVE_IN_PROD"
            for rf in dir_report.risk_assessment.risk_factors
        )

    def test_detect_database_operations(self):
        """Tags database resources"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-4",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "mysql -e 'DROP DATABASE test'"},
        )

        assert "db" in dir_report.request_facts.resource_tags

    def test_safe_command_low_risk(self):
        """Safe commands are low risk"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-5",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "ls -la"},
        )

        assert dir_report.risk_assessment.risk_level == RiskLevel.LOW
        assert not dir_report.request_facts.is_destructive

    def test_missing_info_for_high_risk(self):
        """High risk operations flag missing info"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-6",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "rm -rf /data"},
        )

        # Should ask about backup status
        backup_questions = [
            mi for mi in dir_report.missing_info if mi.field == "backup_status"
        ]
        assert len(backup_questions) > 0
        assert backup_questions[0].blocking

    def test_recommended_constraints_for_critical(self):
        """Critical risk gets tight constraints"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-7",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "DROP DATABASE production"},
        )

        constraints = dir_report.recommended_constraints
        assert constraints.max_steps == 1
        assert constraints.ttl_seconds == 300  # 5 minutes
        assert "DROP DATABASE" in constraints.forbidden_patterns

    def test_provenance_tracks_generator(self):
        """Provenance tracks how DIR was generated"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-8",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "echo test"},
        )

        assert dir_report.provenance.generator == "rules"
        assert dir_report.provenance.version == "v2.0"
        assert dir_report.provenance.model is None

    def test_serialization_to_dict(self):
        """DIR can be serialized to dict"""
        generator = RulesBasedGenerator()

        dir_report = generator.generate(
            decision_id="test-9",
            agent_id="agent-1",
            action="shell_exec",
            context={"command": "rm -rf /test"},
        )

        data = dir_report.to_dict()

        assert data["decision_id"] == "test-9"
        assert data["agent_id"] == "agent-1"
        assert "risk_assessment" in data
        assert "request_facts" in data
        assert data["provenance"]["generator"] == "rules"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
