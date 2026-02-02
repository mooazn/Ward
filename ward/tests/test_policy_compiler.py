"""
Tests for Policy Definition Layer (PDL) - YAML compilation
"""

import pytest
import tempfile
import os
from pathlib import Path

from ward.policy import PolicyCompiler, PolicyCompilationError
from ward.core import PolicyOutcome


class TestPolicyCompiler:
    """Tests for YAML policy compilation"""

    def test_compile_valid_policy(self):
        """Compiles valid YAML policy to Policy object"""
        yaml_content = """
version: 1
policy: test-policy

rules:
  - id: allow_safe_commands
    when:
      action: shell_exec
      destructive: false
    then:
      outcome: allow
      reason: Safe command permitted
      max_steps: 10
      max_duration_minutes: 5
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                policy = compiler.compile(f.name)

                assert policy.name == "test-policy"
                assert len(policy.rules) == 1

                rule = policy.rules[0]
                assert rule.name == "allow_safe_commands"
                assert rule.outcome == PolicyOutcome.ALLOW
                assert rule.scope_constraints == {"destructive": False}
                assert rule.max_steps == 10
                assert rule.max_duration_minutes == 5
            finally:
                os.unlink(f.name)

    def test_compile_multiple_rules(self):
        """Compiles policy with multiple rules"""
        yaml_content = """
version: 1
policy: multi-rule-policy

rules:
  - id: deny_prod_destructive
    when:
      action: shell_exec
      env: prod
      destructive: true
    then:
      outcome: deny
      reason: Destructive in prod not allowed

  - id: human_approval_staging
    when:
      action: shell_exec
      env: staging
      destructive: true
    then:
      outcome: needs_human
      reason: Staging destructive needs review
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                policy = compiler.compile(f.name)

                assert len(policy.rules) == 2
                assert policy.rules[0].outcome == PolicyOutcome.DENY
                assert policy.rules[1].outcome == PolicyOutcome.NEEDS_HUMAN
            finally:
                os.unlink(f.name)

    def test_reject_unknown_when_key(self):
        """Rejects YAML with unknown when key"""
        yaml_content = """
version: 1
policy: bad-policy

rules:
  - id: bad_rule
    when:
      action: shell_exec
      unknown_key: value
    then:
      outcome: allow
      reason: Test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                with pytest.raises(PolicyCompilationError) as exc_info:
                    compiler.compile(f.name)

                assert "Unknown when keys" in str(exc_info.value)
                assert "unknown_key" in str(exc_info.value)
            finally:
                os.unlink(f.name)

    def test_reject_unknown_then_key(self):
        """Rejects YAML with unknown then key"""
        yaml_content = """
version: 1
policy: bad-policy

rules:
  - id: bad_rule
    when:
      action: shell_exec
    then:
      outcome: allow
      reason: Test
      bad_key: value
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                with pytest.raises(PolicyCompilationError) as exc_info:
                    compiler.compile(f.name)

                assert "Unknown then keys" in str(exc_info.value)
            finally:
                os.unlink(f.name)

    def test_reject_invalid_outcome(self):
        """Rejects invalid outcome value"""
        yaml_content = """
version: 1
policy: bad-policy

rules:
  - id: bad_rule
    when:
      action: shell_exec
    then:
      outcome: maybe
      reason: Test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                with pytest.raises(PolicyCompilationError) as exc_info:
                    compiler.compile(f.name)

                assert "Invalid outcome" in str(exc_info.value)
            finally:
                os.unlink(f.name)

    def test_reject_wrong_version(self):
        """Rejects unsupported version"""
        yaml_content = """
version: 99
policy: future-policy

rules:
  - id: some_rule
    when:
      action: shell_exec
    then:
      outcome: allow
      reason: Test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                with pytest.raises(PolicyCompilationError) as exc_info:
                    compiler.compile(f.name)

                assert "Unsupported policy version" in str(exc_info.value)
            finally:
                os.unlink(f.name)

    def test_reject_missing_required_fields(self):
        """Rejects YAML with missing required fields"""
        yaml_content = """
version: 1
policy: bad-policy

rules:
  - id: missing_when
    then:
      outcome: allow
      reason: Test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                with pytest.raises(PolicyCompilationError) as exc_info:
                    compiler.compile(f.name)

                assert "missing required field: when" in str(exc_info.value).lower()
            finally:
                os.unlink(f.name)

    def test_custom_default_outcome(self):
        """Supports custom default outcome"""
        yaml_content = """
version: 1
policy: deny-by-default

default:
  outcome: deny
  reason: Unknown actions are denied

rules:
  - id: allow_read
    when:
      action: read
    then:
      outcome: allow
      reason: Reads are safe
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                policy = compiler.compile(f.name)

                assert policy.default_outcome == PolicyOutcome.DENY
                assert policy.default_reason == "Unknown actions are denied"
            finally:
                os.unlink(f.name)

    def test_explain_rule(self):
        """Generates human-readable rule explanation"""
        yaml_content = """
version: 1
policy: test-policy

rules:
  - id: test_rule
    when:
      action: shell_exec
      env: prod
      destructive: true
    then:
      outcome: needs_human
      reason: Destructive prod action requires approval
      max_steps: 1
      max_duration_minutes: 5
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                policy = compiler.compile(f.name)

                explanation = compiler.explain(policy, "test_rule")

                assert explanation is not None
                assert "test_rule" in explanation
                assert "needs_human" in explanation
                assert "env = prod" in explanation
                assert "destructive = True" in explanation
                assert "Max steps: 1" in explanation
            finally:
                os.unlink(f.name)

    def test_explain_nonexistent_rule(self):
        """Returns None for nonexistent rule"""
        yaml_content = """
version: 1
policy: test-policy

rules:
  - id: existing_rule
    when:
      action: shell_exec
    then:
      outcome: allow
      reason: Test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                policy = compiler.compile(f.name)

                explanation = compiler.explain(policy, "nonexistent")

                assert explanation is None
            finally:
                os.unlink(f.name)

    def test_scope_constraints_mapping(self):
        """Maps all when keys to scope constraints"""
        yaml_content = """
version: 1
policy: full-scope-policy

rules:
  - id: full_scope
    when:
      action: shell_exec
      env: staging
      destructive: true
      resource: db
      agent_id: agent-123
    then:
      outcome: needs_human
      reason: Complex constraints
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            try:
                compiler = PolicyCompiler()
                policy = compiler.compile(f.name)

                rule = policy.rules[0]
                assert rule.scope_constraints == {
                    "env": "staging",
                    "destructive": True,
                    "resource": "db",
                    "agent_id": "agent-123",
                }
            finally:
                os.unlink(f.name)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
