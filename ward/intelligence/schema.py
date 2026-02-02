"""
Decision Intelligence Report (DIR) schema

Structured context attached to decisions for human review.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum


class RiskLevel(Enum):
    """Risk severity levels"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Environment(Enum):
    """Deployment environments"""

    PROD = "prod"
    STAGING = "staging"
    DEV = "dev"
    UNKNOWN = "unknown"


class Reversibility(Enum):
    """Whether an action can be undone"""

    REVERSIBLE = "reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


@dataclass
class RequestFacts:
    """Factual properties of the request"""

    env: Environment
    surface: str  # "shell", "ci", "custom", "unknown"
    command_summary: str
    resource_tags: List[str] = field(default_factory=list)
    is_destructive: bool = False
    is_reversible: bool = True


@dataclass
class RiskFactor:
    """A single risk factor"""

    code: str
    severity: str  # "low", "medium", "high", "critical"
    evidence: List[str]
    explanation: str


@dataclass
class BlastRadius:
    """Estimated impact scope"""

    scope: str  # "single_resource", "service", "env", "unknown"
    estimate: str
    confidence: str  # "low", "medium", "high"


@dataclass
class ReversibilityAssessment:
    """Whether the action can be undone"""

    estimate: Reversibility
    notes: str


@dataclass
class RiskAssessment:
    """Overall risk evaluation"""

    risk_level: RiskLevel
    risk_factors: List[RiskFactor]
    blast_radius: BlastRadius
    reversibility: ReversibilityAssessment


@dataclass
class MissingInfo:
    """Information needed to make better decision"""

    field: str
    question: str
    blocking: bool


@dataclass
class RecommendedConstraints:
    """Suggested lease parameters if approved"""

    max_steps: int
    ttl_seconds: int
    allowed_actions: List[str]
    allowed_scopes: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)


@dataclass
class Recommendation:
    """Generator's suggested outcome (advisory only)"""

    suggested_outcome: str  # "deny", "needs_human", "approve_with_constraints"
    confidence: str  # "low", "medium", "high"
    rationale: str


@dataclass
class ComparableDecision:
    """Similar prior decision"""

    prior_decision_id: str
    prior_outcome: str
    similarity: float
    notes: str


@dataclass
class Provenance:
    """How this DIR was generated"""

    generator: str  # "rules", "advisor_model", "hybrid"
    model: Optional[str] = None
    version: str = "v2.0"


@dataclass
class DecisionIntelligenceReport:
    """
    Complete decision intelligence report.

    Provides structured context for human approval decisions.
    """

    decision_id: str
    generated_at: datetime
    agent_id: str
    requested_action: str
    request_facts: RequestFacts
    risk_assessment: RiskAssessment
    missing_info: List[MissingInfo]
    provenance: Provenance
    recommended_constraints: Optional[RecommendedConstraints] = None
    recommendation: Optional[Recommendation] = None
    comparables: List[ComparableDecision] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary"""
        return {
            "decision_id": self.decision_id,
            "generated_at": self.generated_at.isoformat(),
            "agent_id": self.agent_id,
            "requested_action": self.requested_action,
            "request_facts": {
                "env": self.request_facts.env.value,
                "surface": self.request_facts.surface,
                "command_summary": self.request_facts.command_summary,
                "resource_tags": self.request_facts.resource_tags,
                "is_destructive": self.request_facts.is_destructive,
                "is_reversible": self.request_facts.is_reversible,
            },
            "risk_assessment": {
                "risk_level": self.risk_assessment.risk_level.value,
                "risk_factors": [
                    {
                        "code": rf.code,
                        "severity": rf.severity,
                        "evidence": rf.evidence,
                        "explanation": rf.explanation,
                    }
                    for rf in self.risk_assessment.risk_factors
                ],
                "blast_radius": {
                    "scope": self.risk_assessment.blast_radius.scope,
                    "estimate": self.risk_assessment.blast_radius.estimate,
                    "confidence": self.risk_assessment.blast_radius.confidence,
                },
                "reversibility": {
                    "estimate": self.risk_assessment.reversibility.estimate.value,
                    "notes": self.risk_assessment.reversibility.notes,
                },
            },
            "missing_info": [
                {"field": mi.field, "question": mi.question, "blocking": mi.blocking}
                for mi in self.missing_info
            ],
            "recommended_constraints": (
                {
                    "max_steps": self.recommended_constraints.max_steps,
                    "ttl_seconds": self.recommended_constraints.ttl_seconds,
                    "allowed_actions": self.recommended_constraints.allowed_actions,
                    "allowed_scopes": self.recommended_constraints.allowed_scopes,
                    "forbidden_patterns": self.recommended_constraints.forbidden_patterns,
                }
                if self.recommended_constraints
                else None
            ),
            "recommendation": (
                {
                    "suggested_outcome": self.recommendation.suggested_outcome,
                    "confidence": self.recommendation.confidence,
                    "rationale": self.recommendation.rationale,
                }
                if self.recommendation
                else None
            ),
            "comparables": [
                {
                    "prior_decision_id": c.prior_decision_id,
                    "prior_outcome": c.prior_outcome,
                    "similarity": c.similarity,
                    "notes": c.notes,
                }
                for c in self.comparables
            ],
            "provenance": {
                "generator": self.provenance.generator,
                "model": self.provenance.model,
                "version": self.provenance.version,
            },
        }
