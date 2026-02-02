"""
SQLite persistent audit backend

Schema follows v1 spec exactly:
- decisions: Authority decisions with outcomes
- actions: Executed actions with lease tracking
- revocations: Lease revocations with reasons
"""

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path


class SQLiteAuditBackend:
    """
    Persistent audit log backed by SQLite.

    Stores decisions, actions, and revocations with no schema evolution.
    """

    def __init__(self, db_path: str = "ward.db"):
        """
        Initialize SQLite backend.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Decisions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,
                reason TEXT NOT NULL,
                known_unknowns TEXT,
                context TEXT,
                policy_name TEXT,
                rule_name TEXT,
                lease_id TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Actions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                lease_id TEXT,
                status TEXT NOT NULL,
                result TEXT,
                context TEXT,
                tags TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Revocations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS revocations (
                id TEXT PRIMARY KEY,
                lease_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                revoked_by TEXT NOT NULL,
                description TEXT,
                violations TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Decision Intelligence table (v2)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decision_intel (
                decision_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                generator TEXT NOT NULL,
                model TEXT,
                FOREIGN KEY (decision_id) REFERENCES decisions(id)
            )
        """)

        # Human Approvals table (v2.5 - Decision Saturation)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS human_approvals (
                id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                human_outcome TEXT NOT NULL,
                recommended_max_steps INTEGER,
                actual_max_steps INTEGER,
                recommended_duration_minutes INTEGER,
                actual_duration_minutes INTEGER,
                constraints_modified INTEGER NOT NULL,
                missing_info_questions TEXT,
                missing_info_resolved TEXT,
                rationale TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (decision_id) REFERENCES decisions(id)
            )
        """)

        # Add rationale column if it doesn't exist (for existing databases)
        try:
            cursor.execute("ALTER TABLE human_approvals ADD COLUMN rationale TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Indexes for common queries
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_agent ON decisions(agent_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_actions_agent ON actions(agent_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_actions_lease ON actions(lease_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_revocations_lease ON revocations(lease_id)"
        )

        conn.commit()
        conn.close()

    def _serialize_list(self, items: List[str]) -> str:
        """Serialize list to JSON string"""
        return json.dumps(items) if items else "[]"

    def _deserialize_list(self, data: str) -> List[str]:
        """Deserialize JSON string to list"""
        return json.loads(data) if data else []

    def record_decision(
        self,
        decision_id: str,
        agent_id: str,
        action: str,
        outcome: str,
        reason: str,
        known_unknowns: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        policy_name: Optional[str] = None,
        rule_name: Optional[str] = None,
        lease_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record an authority decision"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO decisions (
                id, agent_id, action, outcome, reason,
                known_unknowns, context, policy_name, rule_name,
                lease_id, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                decision_id,
                agent_id,
                action,
                outcome,
                reason,
                self._serialize_list(known_unknowns or []),
                json.dumps(context) if context else "{}",
                policy_name,
                rule_name,
                lease_id,
                (timestamp or datetime.now()).isoformat(),
            ),
        )

        conn.commit()
        conn.close()

    def record_action(
        self,
        action_id: str,
        agent_id: str,
        action: str,
        status: str,
        lease_id: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record an executed action"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO actions (
                id, agent_id, action, lease_id, status,
                result, context, tags, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                action_id,
                agent_id,
                action,
                lease_id,
                status,
                json.dumps(result) if result else "{}",
                json.dumps(context) if context else "{}",
                self._serialize_list(tags or []),
                (timestamp or datetime.now()).isoformat(),
            ),
        )

        conn.commit()
        conn.close()

    def record_revocation(
        self,
        revocation_id: str,
        lease_id: str,
        agent_id: str,
        reason: str,
        revoked_by: str,
        description: str,
        violations: Optional[List[str]] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Record a lease revocation"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO revocations (
                id, lease_id, agent_id, reason, revoked_by,
                description, violations, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                revocation_id,
                lease_id,
                agent_id,
                reason,
                revoked_by,
                description,
                self._serialize_list(violations or []),
                (timestamp or datetime.now()).isoformat(),
            ),
        )

        conn.commit()
        conn.close()

    def update_decision(
        self,
        decision_id: str,
        outcome: Optional[str] = None,
        lease_id: Optional[str] = None,
    ) -> None:
        """Update a decision's outcome and/or lease_id"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        updates = []
        params = []

        if outcome is not None:
            updates.append("outcome = ?")
            params.append(outcome)

        if lease_id is not None:
            updates.append("lease_id = ?")
            params.append(lease_id)

        if not updates:
            conn.close()
            return

        params.append(decision_id)
        query = f"UPDATE decisions SET {', '.join(updates)} WHERE id = ?"

        cursor.execute(query, params)
        conn.commit()
        conn.close()

    def get_decisions(
        self,
        agent_id: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query decisions"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM decisions WHERE 1=1"
        params = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "action": row["action"],
                "outcome": row["outcome"],
                "reason": row["reason"],
                "known_unknowns": self._deserialize_list(row["known_unknowns"]),
                "context": json.loads(row["context"]) if row["context"] else {},
                "policy_name": row["policy_name"],
                "rule_name": row["rule_name"],
                "lease_id": row["lease_id"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def get_actions(
        self,
        agent_id: Optional[str] = None,
        lease_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query actions"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM actions WHERE 1=1"
        params = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if lease_id:
            query += " AND lease_id = ?"
            params.append(lease_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "action": row["action"],
                "lease_id": row["lease_id"],
                "status": row["status"],
                "result": json.loads(row["result"]) if row["result"] else {},
                "context": json.loads(row["context"]) if row["context"] else {},
                "tags": self._deserialize_list(row["tags"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def get_revocations(
        self,
        agent_id: Optional[str] = None,
        lease_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query revocations"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM revocations WHERE 1=1"
        params = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if lease_id:
            query += " AND lease_id = ?"
            params.append(lease_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "lease_id": row["lease_id"],
                "agent_id": row["agent_id"],
                "reason": row["reason"],
                "revoked_by": row["revoked_by"],
                "description": row["description"],
                "violations": self._deserialize_list(row["violations"]),
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """
        Get decisions that need human approval.

        Only returns decisions that:
        - Have outcome = 'needs_human'
        - Have NOT been approved/denied yet (no entry in human_approvals)
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get pending decisions that haven't been processed yet
        cursor.execute(
            """
            SELECT d.*
            FROM decisions d
            LEFT JOIN human_approvals ha ON d.id = ha.decision_id
            WHERE d.outcome = 'needs_human'
              AND ha.id IS NULL
            ORDER BY d.timestamp DESC
        """
        )
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "action": row["action"],
                "outcome": row["outcome"],
                "reason": row["reason"],
                "known_unknowns": self._deserialize_list(row["known_unknowns"]),
                "context": json.loads(row["context"]) if row["context"] else {},
                "policy_name": row["policy_name"],
                "rule_name": row["rule_name"],
                "lease_id": row["lease_id"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def count_decisions(self) -> int:
        """Get total decision count"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM decisions")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def count_actions(self) -> int:
        """Get total action count"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM actions")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def count_revocations(self) -> int:
        """Get total revocation count"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM revocations")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def store_decision_intel(
        self,
        decision_id: str,
        payload: Dict[str, Any],
        generated_at: str,
        generator: str,
        model: Optional[str] = None,
    ) -> None:
        """Store a Decision Intelligence Report"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO decision_intel (
                decision_id, payload_json, generated_at, generator, model
            ) VALUES (?, ?, ?, ?, ?)
        """,
            (
                decision_id,
                json.dumps(payload),
                generated_at,
                generator,
                model,
            ),
        )

        conn.commit()
        conn.close()

    def get_decision_intel(self, decision_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve Decision Intelligence Report for a decision"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM decision_intel WHERE decision_id = ?", (decision_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            "decision_id": row["decision_id"],
            "payload": json.loads(row["payload_json"]),
            "generated_at": row["generated_at"],
            "generator": row["generator"],
            "model": row["model"],
        }

    def record_human_approval(
        self,
        approval_id: str,
        decision_id: str,
        human_outcome: str,
        recommended_max_steps: Optional[int] = None,
        actual_max_steps: Optional[int] = None,
        recommended_duration_minutes: Optional[int] = None,
        actual_duration_minutes: Optional[int] = None,
        missing_info_questions: Optional[List[str]] = None,
        missing_info_resolved: Optional[List[str]] = None,
        rationale: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """
        Record a human approval decision for saturation tracking.

        Args:
            approval_id: Unique approval identifier
            decision_id: Decision being approved/denied
            human_outcome: 'approved' or 'denied'
            recommended_max_steps: What DIR recommended
            actual_max_steps: What human chose
            recommended_duration_minutes: What DIR recommended
            actual_duration_minutes: What human chose
            missing_info_questions: Questions flagged by DIR
            missing_info_resolved: Questions answered by human
            rationale: Human's explanation for their decision
            timestamp: When approval happened
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Determine if constraints were modified
        constraints_modified = 0
        if recommended_max_steps is not None and actual_max_steps is not None:
            if recommended_max_steps != actual_max_steps:
                constraints_modified = 1
        if (
            recommended_duration_minutes is not None
            and actual_duration_minutes is not None
        ):
            if recommended_duration_minutes != actual_duration_minutes:
                constraints_modified = 1

        cursor.execute(
            """
            INSERT INTO human_approvals
            (id, decision_id, human_outcome, recommended_max_steps, actual_max_steps,
             recommended_duration_minutes, actual_duration_minutes, constraints_modified,
             missing_info_questions, missing_info_resolved, rationale, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                decision_id,
                human_outcome,
                recommended_max_steps,
                actual_max_steps,
                recommended_duration_minutes,
                actual_duration_minutes,
                constraints_modified,
                self._serialize_list(missing_info_questions or []),
                self._serialize_list(missing_info_resolved or []),
                rationale,
                (timestamp or datetime.now()).isoformat(),
            ),
        )

        conn.commit()
        conn.close()

    def get_human_approvals(
        self, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get all human approvals"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM human_approvals ORDER BY timestamp DESC"
        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "id": row["id"],
                "decision_id": row["decision_id"],
                "human_outcome": row["human_outcome"],
                "recommended_max_steps": row["recommended_max_steps"],
                "actual_max_steps": row["actual_max_steps"],
                "recommended_duration_minutes": row["recommended_duration_minutes"],
                "actual_duration_minutes": row["actual_duration_minutes"],
                "constraints_modified": bool(row["constraints_modified"]),
                "missing_info_questions": self._deserialize_list(
                    row["missing_info_questions"]
                ),
                "missing_info_resolved": self._deserialize_list(
                    row["missing_info_resolved"]
                ),
                "rationale": row.get("rationale"),  # Human's explanation
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]

    def calculate_decision_saturation(self) -> Dict[str, Any]:
        """
        Calculate decision saturation metrics.

        Returns metrics showing if humans are repeating themselves.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total human decisions
        cursor.execute("SELECT COUNT(*) FROM human_approvals")
        total_decisions = cursor.fetchone()[0]

        if total_decisions == 0:
            return {
                "total_decisions": 0,
                "saturation_score": 0.0,
                "constraints_acceptance_rate": 0.0,
                "missing_info_resolution_rate": 0.0,
                "status": "insufficient_data",
                "ready_for_llm": False,
                "target_decisions": 200,
                "target_saturation": 0.8,
            }

        # Constraint acceptance (did human use recommendations?)
        cursor.execute(
            "SELECT COUNT(*) FROM human_approvals WHERE constraints_modified = 0"
        )
        constraints_accepted = cursor.fetchone()[0]
        constraints_acceptance_rate = constraints_accepted / total_decisions

        # Missing info resolution (did human answer questions?)
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN missing_info_questions != '[]' THEN 1 END) as had_questions,
                COUNT(CASE WHEN missing_info_questions != '[]' AND missing_info_resolved != '[]' THEN 1 END) as resolved_questions
            FROM human_approvals
        """)
        had_questions, resolved_questions = cursor.fetchone()
        missing_info_resolution_rate = (
            resolved_questions / had_questions if had_questions > 0 else 1.0
        )

        # Decision repeatability (simplified: constraints accepted + info resolved)
        saturation_score = (constraints_acceptance_rate + missing_info_resolution_rate) / 2

        conn.close()

        # LLM readiness check: ≥80% saturation + ≥200 decisions
        ready_for_llm = saturation_score >= 0.8 and total_decisions >= 200

        return {
            "total_decisions": total_decisions,
            "saturation_score": saturation_score,
            "constraints_acceptance_rate": constraints_acceptance_rate,
            "missing_info_resolution_rate": missing_info_resolution_rate,
            "status": "ready" if ready_for_llm else "collecting_data",
            "ready_for_llm": ready_for_llm,
            "target_decisions": 200,
            "target_saturation": 0.8,
        }

    # Async Agent Helpers (v2.5)
    # These methods support async agents that poll for approval status changes

    def check_decision_approved(self, decision_id: str) -> Optional[str]:
        """
        Check if a decision has been approved.

        Returns:
            lease_id if approved, None if still pending or denied
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT lease_id, outcome FROM decisions
            WHERE id = ?
            """,
            (decision_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row and row["outcome"] == "approved" and row["lease_id"]:
            return row["lease_id"]
        return None

    def is_decision_denied(self, decision_id: str) -> bool:
        """
        Check if a decision has been explicitly denied.

        Returns:
            True if denied, False otherwise
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT outcome FROM decisions
            WHERE id = ?
            """,
            (decision_id,),
        )
        row = cursor.fetchone()
        conn.close()

        return row["outcome"] == "denied" if row else False

    def is_lease_revoked(self, lease_id: str) -> bool:
        """
        Check if a lease has been revoked.

        Returns:
            True if revoked, False otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM revocations
            WHERE lease_id = ?
            """,
            (lease_id,),
        )
        count = cursor.fetchone()[0]
        conn.close()

        return count > 0
