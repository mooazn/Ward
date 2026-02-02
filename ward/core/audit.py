"""
Audit - Immutable records of authority decisions and actions
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
import json

from .decision import Decision


@dataclass
class AuditEntry:
    """
    An immutable record of an authority decision or action.

    This is half the value of the system - making agent behavior
    debuggable and trustworthy.
    """

    entry_id: str
    timestamp: datetime
    event_type: str  # "decision", "action", "lease_revoked", etc.
    agent_id: str
    decision: Optional[Decision] = None
    action_taken: Optional[str] = None
    action_result: Optional[Dict[str, Any]] = None
    known_unknowns: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize audit entry for storage/transmission"""
        result = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "known_unknowns": self.known_unknowns,
            "context": self.context,
            "tags": self.tags,
        }

        if self.decision:
            result["decision"] = self.decision.to_dict()

        if self.action_taken:
            result["action_taken"] = self.action_taken

        if self.action_result:
            result["action_result"] = self.action_result

        return result

    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(self.to_dict(), indent=2)

    @staticmethod
    def from_decision(
        entry_id: str,
        decision: Decision,
        known_unknowns: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> "AuditEntry":
        """Create an audit entry from a decision"""
        return AuditEntry(
            entry_id=entry_id,
            timestamp=datetime.now(),
            event_type="decision",
            agent_id=decision.agent_id,
            decision=decision,
            known_unknowns=known_unknowns or [],
            context=context or {},
            tags=tags or [],
        )

    @staticmethod
    def from_action(
        entry_id: str,
        agent_id: str,
        action: str,
        result: Optional[Dict[str, Any]] = None,
        known_unknowns: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> "AuditEntry":
        """Create an audit entry from an action"""
        return AuditEntry(
            entry_id=entry_id,
            timestamp=datetime.now(),
            event_type="action",
            agent_id=agent_id,
            action_taken=action,
            action_result=result,
            known_unknowns=known_unknowns or [],
            context=context or {},
            tags=tags or [],
        )


class AuditLog:
    """
    Simple in-memory audit log.

    In production, this would write to persistent storage.
    """

    def __init__(self):
        self.entries: List[AuditEntry] = []

    def append(self, entry: AuditEntry) -> None:
        """Add an entry to the audit log"""
        self.entries.append(entry)

    def get_entries_for_agent(self, agent_id: str) -> List[AuditEntry]:
        """Get all entries for a specific agent"""
        return [e for e in self.entries if e.agent_id == agent_id]

    def get_entries_by_type(self, event_type: str) -> List[AuditEntry]:
        """Get all entries of a specific type"""
        return [e for e in self.entries if e.event_type == event_type]

    def get_entries_with_unknown(self, unknown: str) -> List[AuditEntry]:
        """Find entries that flagged a specific unknown"""
        return [e for e in self.entries if unknown in e.known_unknowns]

    def get_recent(self, limit: int = 10) -> List[AuditEntry]:
        """Get the most recent entries"""
        return sorted(self.entries, key=lambda e: e.timestamp, reverse=True)[:limit]

    def to_json(self) -> str:
        """Export entire log as JSON"""
        return json.dumps([e.to_dict() for e in self.entries], indent=2)

    def export_to_file(self, filepath: str) -> None:
        """Export log to a JSON file"""
        with open(filepath, "w") as f:
            f.write(self.to_json())
