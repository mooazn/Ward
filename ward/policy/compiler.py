"""
Policy Definition Layer (PDL) - YAML compilation to PolicyRule objects

Design principles:
- YAML is a serialization format, not a policy language
- Compile at startup, fail fast on invalid schema
- No runtime interpretation
- Explicit whitelist of allowed keys
- No conditionals, no expressions, no magic
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import yaml

from ward.core import Policy, PolicyRule, PolicyOutcome


class PolicyCompilationError(Exception):
    """Raised when YAML policy cannot be compiled"""

    pass


@dataclass
class PolicyYAML:
    """YAML policy schema (v1)"""

    version: int
    policy: str
    rules: List[Dict[str, Any]]


class PolicyCompiler:
    """
    Compiles YAML policies into PolicyRule objects.

    YAML is NOT interpreted at runtime. It is compiled into
    deterministic PolicyRule objects at startup. If compilation
    fails, Ward refuses to start.
    """

    # Explicit whitelist of allowed keys
    ALLOWED_WHEN_KEYS = {"action", "env", "destructive", "resource", "agent_id"}
    ALLOWED_THEN_KEYS = {"outcome", "reason", "max_steps", "max_duration_minutes"}
    ALLOWED_OUTCOMES = {"allow", "deny", "needs_human"}

    # Forbidden features (documented in README)
    FORBIDDEN_FEATURES = [
        "regex in YAML",
        "conditionals (if, and, or)",
        "string matching beyond exact match",
        "wildcards",
        "arithmetic",
        "LLM interpretation",
        "runtime evaluation",
    ]

    def compile(self, yaml_path: str) -> Policy:
        """
        Compile YAML to Policy object.

        Args:
            yaml_path: Path to YAML policy file

        Returns:
            Compiled Policy object

        Raises:
            PolicyCompilationError: If YAML is invalid
        """
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise PolicyCompilationError(f"Failed to load YAML: {e}")

        # Validate version
        if data.get("version") != 1:
            raise PolicyCompilationError(
                f"Unsupported policy version: {data.get('version')}. Expected: 1"
            )

        # Validate required fields
        if "policy" not in data:
            raise PolicyCompilationError("Missing required field: policy")
        if "rules" not in data or not isinstance(data["rules"], list):
            raise PolicyCompilationError("Missing or invalid field: rules")

        # Validate schema
        self._validate_schema(data)

        # Compile rules
        rules = []
        for i, rule_data in enumerate(data["rules"]):
            try:
                rule = self._compile_rule(rule_data)
                rules.append(rule)
            except Exception as e:
                raise PolicyCompilationError(
                    f"Failed to compile rule {i} (id: {rule_data.get('id', 'unknown')}): {e}"
                )

        # Get default outcome and reason if specified
        default_outcome = PolicyOutcome.NEEDS_HUMAN
        default_reason = "No matching policy rule"

        if "default" in data:
            default_data = data["default"]
            if "outcome" in default_data:
                outcome_str = default_data["outcome"]
                if outcome_str not in self.ALLOWED_OUTCOMES:
                    raise PolicyCompilationError(
                        f"Invalid default outcome: {outcome_str}"
                    )
                default_outcome = self._map_outcome(outcome_str)
            if "reason" in default_data:
                default_reason = default_data["reason"]

        return Policy(
            name=data["policy"],
            rules=rules,
            default_outcome=default_outcome,
            default_reason=default_reason,
        )

    def _validate_schema(self, data: Dict[str, Any]) -> None:
        """
        Validate YAML schema. Fail fast on unknown keys.

        This is the security boundary. Only whitelisted keys are allowed.
        """
        for i, rule in enumerate(data.get("rules", [])):
            rule_id = rule.get("id", f"rule-{i}")

            # Validate required fields
            if "id" not in rule:
                raise PolicyCompilationError(f"Rule {i} missing required field: id")
            if "when" not in rule:
                raise PolicyCompilationError(f"Rule {rule_id} missing required field: when")
            if "then" not in rule:
                raise PolicyCompilationError(f"Rule {rule_id} missing required field: then")

            # Check when clause
            when_keys = set(rule["when"].keys())
            unknown = when_keys - self.ALLOWED_WHEN_KEYS
            if unknown:
                raise PolicyCompilationError(
                    f"Rule {rule_id}: Unknown when keys: {unknown}. "
                    f"Allowed: {self.ALLOWED_WHEN_KEYS}"
                )

            # Check then clause
            then_keys = set(rule["then"].keys())
            unknown = then_keys - self.ALLOWED_THEN_KEYS
            if unknown:
                raise PolicyCompilationError(
                    f"Rule {rule_id}: Unknown then keys: {unknown}. "
                    f"Allowed: {self.ALLOWED_THEN_KEYS}"
                )

            # Validate outcome value
            outcome = rule["then"].get("outcome")
            if not outcome:
                raise PolicyCompilationError(
                    f"Rule {rule_id}: Missing required then field: outcome"
                )
            if outcome not in self.ALLOWED_OUTCOMES:
                raise PolicyCompilationError(
                    f"Rule {rule_id}: Invalid outcome: {outcome}. "
                    f"Allowed: {self.ALLOWED_OUTCOMES}"
                )

    def _compile_rule(self, rule_data: Dict[str, Any]) -> PolicyRule:
        """
        Compile single YAML rule to PolicyRule.

        This is where YAML becomes deterministic Python objects.
        """
        when = rule_data["when"]
        then = rule_data["then"]
        rule_id = rule_data["id"]

        # Build scope constraints from when clause
        scope_constraints = {}

        # Each when key maps directly to a scope constraint
        for key in ["env", "destructive", "resource", "agent_id"]:
            if key in when:
                scope_constraints[key] = when[key]

        # Map outcome string to enum
        outcome = self._map_outcome(then["outcome"])

        # Extract constraints
        max_steps = then.get("max_steps")
        max_duration_minutes = then.get("max_duration_minutes")

        # Action pattern (still uses regex for flexibility)
        action_pattern = when["action"]

        return PolicyRule(
            name=rule_id,
            action_pattern=action_pattern,
            outcome=outcome,
            reason=then.get("reason", "Policy rule matched"),
            scope_constraints=scope_constraints,
            max_steps=max_steps,
            max_duration_minutes=max_duration_minutes,
        )

    def _map_outcome(self, outcome_str: str) -> PolicyOutcome:
        """Map outcome string to PolicyOutcome enum"""
        outcome_map = {
            "allow": PolicyOutcome.ALLOW,
            "deny": PolicyOutcome.DENY,
            "needs_human": PolicyOutcome.NEEDS_HUMAN,
        }
        return outcome_map[outcome_str]

    def explain(self, policy: Policy, rule_id: str) -> Optional[str]:
        """
        Generate human-readable explanation of a compiled rule.

        Args:
            policy: Compiled policy
            rule_id: Rule ID to explain

        Returns:
            Human-readable explanation or None if not found
        """
        rule = next((r for r in policy.rules if r.name == rule_id), None)
        if not rule:
            return None

        lines = []
        lines.append(f"Rule: {rule.name}")
        lines.append(f"Outcome: {rule.outcome.value}")
        lines.append(f"Reason: {rule.reason}")
        lines.append("")
        lines.append("Matches when:")
        lines.append(f"  - Action matches: {rule.action_pattern}")

        if rule.scope_constraints:
            for key, value in rule.scope_constraints.items():
                lines.append(f"  - {key} = {value}")

        if rule.max_steps or rule.max_duration_minutes:
            lines.append("")
            lines.append("Constraints:")
            if rule.max_steps:
                lines.append(f"  - Max steps: {rule.max_steps}")
            if rule.max_duration_minutes:
                lines.append(f"  - Max duration: {rule.max_duration_minutes} minutes")

        return "\n".join(lines)
