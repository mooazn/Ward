"""
Rules-based DIR generator

Deterministic decision intelligence without LLMs.
"""

import re
from datetime import datetime
from typing import Dict, Any, List

from .schema import (
    DecisionIntelligenceReport,
    RequestFacts,
    RiskAssessment,
    RiskFactor,
    BlastRadius,
    ReversibilityAssessment,
    MissingInfo,
    RecommendedConstraints,
    Provenance,
    RiskLevel,
    Environment,
    Reversibility,
)


class RulesBasedGenerator:
    """
    Generates DIR using deterministic rules only.

    No LLMs. No probabilistic behavior. Pure pattern matching.
    """

    # Destructive command patterns
    DESTRUCTIVE_PATTERNS = [
        (r"\brm\s+(-rf?|--recursive)", "DESTRUCTIVE_RM", "high"),
        (r"\bDROP\s+(DATABASE|TABLE)", "SQL_DROP", "critical"),
        (r"\btruncate\b", "SQL_TRUNCATE", "high"),
        (r"\bdelete\s+from\b", "SQL_DELETE", "medium"),
        (r">\s*/dev/", "WRITE_TO_DEV", "high"),
        (r"\bmkfs\b", "FORMAT_FILESYSTEM", "critical"),
        (r"\bdd\b.*of=", "DD_WRITE", "high"),
    ]

    # Risky command patterns
    RISKY_PATTERNS = [
        (r"\bsudo\b", "ELEVATED_PRIVILEGES", "medium"),
        (r"\bcurl.*\|\s*bash", "PIPE_TO_BASH", "high"),
        (r"\bwget.*\|\s*bash", "PIPE_TO_BASH", "high"),
        (r"\bchmod\s+777", "OVERLY_PERMISSIVE", "medium"),
    ]

    # Resource tags patterns
    RESOURCE_PATTERNS = [
        (r"\b(mysql|postgres|mongo|redis)\b", "db"),
        (r"\b(\.sql|database|schema)\b", "db"),
        (r"\b(/dev/|/sys/|/proc/)", "system"),
        (r"\b(docker|kubernetes|k8s)\b", "container"),
        (r"\b(aws|gcp|azure)\b", "cloud"),
        (r"\b(secret|password|token|key)\b", "secrets"),
        (r"\b(network|iptables|firewall)\b", "network"),
    ]

    def generate(
        self, decision_id: str, agent_id: str, action: str, context: Dict[str, Any]
    ) -> DecisionIntelligenceReport:
        """
        Generate a DIR for a decision.

        Args:
            decision_id: Decision identifier
            agent_id: Agent making the request
            action: Requested action
            context: Request context (command, env, etc.)

        Returns:
            Complete DecisionIntelligenceReport
        """
        command = context.get("command", "")

        # Extract request facts
        request_facts = self._extract_facts(command, context)

        # Assess risk
        risk_assessment = self._assess_risk(command, context, request_facts)

        # Identify missing information
        missing_info = self._identify_missing_info(command, context, risk_assessment)

        # Recommend constraints
        recommended_constraints = self._recommend_constraints(
            command, context, risk_assessment
        )

        return DecisionIntelligenceReport(
            decision_id=decision_id,
            generated_at=datetime.now(),
            agent_id=agent_id,
            requested_action=action,
            request_facts=request_facts,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            recommended_constraints=recommended_constraints,
            provenance=Provenance(generator="rules", version="v2.0"),
        )

    def _extract_facts(
        self, command: str, context: Dict[str, Any]
    ) -> RequestFacts:
        """Extract factual properties from request"""

        # Detect environment
        env = Environment.UNKNOWN
        env_markers = {
            "prod": Environment.PROD,
            "production": Environment.PROD,
            "staging": Environment.STAGING,
            "stage": Environment.STAGING,
            "dev": Environment.DEV,
            "development": Environment.DEV,
        }

        command_lower = command.lower()
        for marker, env_type in env_markers.items():
            if marker in command_lower or marker in str(context.get("working_dir", "")).lower():
                env = env_type
                break

        # Detect surface
        surface = context.get("surface", "shell")

        # Check if destructive
        is_destructive = any(
            re.search(pattern, command, re.IGNORECASE)
            for pattern, _, _ in self.DESTRUCTIVE_PATTERNS
        )

        # Tag resources
        resource_tags = []
        for pattern, tag in self.RESOURCE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                if tag not in resource_tags:
                    resource_tags.append(tag)

        # Assess reversibility (simple heuristic)
        is_reversible = not is_destructive

        return RequestFacts(
            env=env,
            surface=surface,
            command_summary=self._summarize_command(command),
            resource_tags=resource_tags,
            is_destructive=is_destructive,
            is_reversible=is_reversible,
        )

    def _assess_risk(
        self, command: str, context: Dict[str, Any], facts: RequestFacts
    ) -> RiskAssessment:
        """Assess risk factors"""

        risk_factors = []

        # Check destructive patterns
        for pattern, code, severity in self.DESTRUCTIVE_PATTERNS:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                risk_factors.append(
                    RiskFactor(
                        code=code,
                        severity=severity,
                        evidence=[match.group(0)],
                        explanation=f"Destructive operation detected: {code}",
                    )
                )

        # Check risky patterns
        for pattern, code, severity in self.RISKY_PATTERNS:
            match = re.search(pattern, command, re.IGNORECASE)
            if match:
                risk_factors.append(
                    RiskFactor(
                        code=code,
                        severity=severity,
                        evidence=[match.group(0)],
                        explanation=f"Risky pattern detected: {code}",
                    )
                )

        # Production + destructive = critical
        if facts.env == Environment.PROD and facts.is_destructive:
            risk_factors.append(
                RiskFactor(
                    code="DESTRUCTIVE_IN_PROD",
                    severity="critical",
                    evidence=["production environment", "destructive operation"],
                    explanation="Destructive command targeting production",
                )
            )

        # Determine overall risk level
        if any(rf.severity == "critical" for rf in risk_factors):
            risk_level = RiskLevel.CRITICAL
        elif any(rf.severity == "high" for rf in risk_factors):
            risk_level = RiskLevel.HIGH
        elif any(rf.severity == "medium" for rf in risk_factors):
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        # Estimate blast radius
        blast_radius = self._estimate_blast_radius(command, facts, risk_factors)

        # Assess reversibility
        reversibility = self._assess_reversibility(command, facts, risk_factors)

        return RiskAssessment(
            risk_level=risk_level,
            risk_factors=risk_factors,
            blast_radius=blast_radius,
            reversibility=reversibility,
        )

    def _estimate_blast_radius(
        self, command: str, facts: RequestFacts, risk_factors: List[RiskFactor]
    ) -> BlastRadius:
        """Estimate impact scope"""

        # Database operations can affect entire service
        if "db" in facts.resource_tags:
            return BlastRadius(
                scope="service",
                estimate="Database operation may affect entire service",
                confidence="medium",
            )

        # Production + destructive = env-level
        if facts.env == Environment.PROD and facts.is_destructive:
            return BlastRadius(
                scope="env",
                estimate="Destructive prod operation may affect environment",
                confidence="high",
            )

        # System-level operations
        if "system" in facts.resource_tags:
            return BlastRadius(
                scope="env",
                estimate="System-level operation may affect host/cluster",
                confidence="medium",
            )

        # Default to single resource
        return BlastRadius(
            scope="single_resource",
            estimate="Impact likely limited to single resource",
            confidence="low",
        )

    def _assess_reversibility(
        self, command: str, facts: RequestFacts, risk_factors: List[RiskFactor]
    ) -> ReversibilityAssessment:
        """Assess whether action can be undone"""

        # Destructive operations are generally irreversible
        if facts.is_destructive:
            return ReversibilityAssessment(
                estimate=Reversibility.IRREVERSIBLE,
                notes="Destructive operation cannot be undone without backups",
            )

        # Read operations are reversible (idempotent)
        if re.search(r"\b(read|get|list|show|select)\b", command, re.IGNORECASE):
            return ReversibilityAssessment(
                estimate=Reversibility.REVERSIBLE,
                notes="Read operation is idempotent",
            )

        # Updates might be partially reversible
        if re.search(r"\b(update|modify|set)\b", command, re.IGNORECASE):
            return ReversibilityAssessment(
                estimate=Reversibility.PARTIALLY_REVERSIBLE,
                notes="Update may be reversible if previous state was recorded",
            )

        return ReversibilityAssessment(
            estimate=Reversibility.UNKNOWN, notes="Reversibility unclear"
        )

    def _identify_missing_info(
        self, command: str, context: Dict[str, Any], risk: RiskAssessment
    ) -> List[MissingInfo]:
        """Identify information needed for better decision"""

        missing = []

        # High/critical risk needs backup confirmation
        if risk.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            if risk.reversibility.estimate in (
                Reversibility.IRREVERSIBLE,
                Reversibility.UNKNOWN,
            ):
                missing.append(
                    MissingInfo(
                        field="backup_status",
                        question="Is there a verified backup taken within last 24 hours?",
                        blocking=True,
                    )
                )

        # Production operations need approval chain
        if "prod" in command.lower() or "production" in str(context).lower():
            missing.append(
                MissingInfo(
                    field="approval_chain",
                    question="Has this been reviewed by required approvers?",
                    blocking=False,
                )
            )

        return missing

    def _recommend_constraints(
        self, command: str, context: Dict[str, Any], risk: RiskAssessment
    ) -> RecommendedConstraints:
        """Recommend lease constraints if approved"""

        # High/critical risk: very tight constraints
        if risk.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return RecommendedConstraints(
                max_steps=1,
                ttl_seconds=300,  # 5 minutes
                allowed_actions=["shell_exec"],
                forbidden_patterns=["rm -rf", "DROP DATABASE", "truncate"],
            )

        # Medium risk: moderate constraints
        if risk.risk_level == RiskLevel.MEDIUM:
            return RecommendedConstraints(
                max_steps=5,
                ttl_seconds=600,  # 10 minutes
                allowed_actions=["shell_exec"],
                forbidden_patterns=["rm -rf"],
            )

        # Low risk: standard constraints
        return RecommendedConstraints(
            max_steps=10,
            ttl_seconds=1800,  # 30 minutes
            allowed_actions=["shell_exec"],
        )

    def _summarize_command(self, command: str) -> str:
        """Create a short summary of the command"""
        # Truncate long commands
        if len(command) > 100:
            return command[:97] + "..."
        return command
