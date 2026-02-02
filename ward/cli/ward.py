#!/usr/bin/env python3
"""
Ward CLI - Human approval interface for AI agent control

Commands:
  ward approvals           List pending approvals
  ward leases              List active leases
  ward inspect <id>        Inspect a decision
  ward approve <id>        Approve a decision (with confirmation)
  ward deny <id>           Deny a decision
  ward revoke <lease_id>   Revoke an active lease
  ward status              Show system status overview
  ward saturation          Show decision saturation metrics

Design: Deliberate, not convenient.
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Optional
import uuid

from ward.storage import SQLiteAuditBackend
from ward.config import get_config
from ward.core import (
    Lease,
    Decision,
    DecisionOutcome,
    RevocationReason,
    RevocationRecord,
)
from ward.policy import PolicyCompiler, PolicyCompilationError


class WardCLI:
    """Ward command-line interface"""

    def __init__(self, db_path: str = "ward.db"):
        self.backend = SQLiteAuditBackend(db_path)
        self.db_path = db_path

    def cmd_approvals(self, args):
        """List pending approvals"""
        pending = self.backend.get_pending_approvals()

        if not pending:
            print("No pending approvals.")
            return

        print(f"Pending approvals ({len(pending)}):\n")

        for dec in pending:
            # Try to get DIR for risk level (if intelligence enabled)
            config = get_config()
            risk_level = ""
            if config.intelligence_enabled:
                dir_data = self.backend.get_decision_intel(dec["id"])
                if dir_data:
                    payload = dir_data["payload"]
                    risk = payload.get("risk_assessment", {}).get("risk_level", "")
                    if risk:
                        risk_level = f"  Risk: {risk.upper()}"

            print(f"ID: {dec['id']}{risk_level}")
            print(f"Agent: {dec['agent_id']}")
            print(f"Action: {dec['action']}")

            # Show command if it's a shell execution
            if dec.get("context") and "command" in dec["context"]:
                print(f"Command: {dec['context']['command']}")

            print(f"Requested at: {dec['timestamp']}")

            if dec.get("known_unknowns"):
                print("\nKnown unknowns:")
                for unknown in dec["known_unknowns"]:
                    print(f"- {unknown}")

            print()

    def cmd_inspect(self, args):
        """Inspect a specific decision"""
        decision_id = args.decision_id

        # Query decision
        decisions = self.backend.get_decisions()
        decision = next((d for d in decisions if d["id"] == decision_id), None)

        if not decision:
            print(f"Error: Decision {decision_id} not found")
            return 1

        print(f"Decision ID: {decision['id']}")
        print(f"Outcome: {decision['outcome']}")
        print(f"Reason: {decision['reason']}")

        # Try to get DIR
        # Show DIR if intelligence is enabled
        config = get_config()
        if config.intelligence_enabled:
            dir_data = self.backend.get_decision_intel(decision_id)
            if dir_data:
                self._print_dir(dir_data["payload"])
            else:
                # Fallback to basic info
                print(f"\nAgent: {decision['agent_id']}")
                print(f"Requested action: {decision['action']}")

                if decision.get("context"):
                    print(f"\nContext:")
                    for key, value in decision["context"].items():
                        print(f"  {key}: {value}")

                if decision.get("policy_name"):
                    print(f"\nPolicy triggered:")
                    print(f"- {decision['policy_name']}")
                    if decision.get("rule_name"):
                        print(f"  Rule: {decision['rule_name']}")

    def _print_dir(self, payload: dict):
        """Print DIR in readable format"""
        print()

        # Risk assessment
        risk = payload.get("risk_assessment", {})
        if risk:
            risk_level = risk.get("risk_level", "unknown").upper()
            print(f"Risk: {risk_level}")

            # Risk factors
            risk_factors = risk.get("risk_factors", [])
            if risk_factors:
                for rf in risk_factors:
                    print(f"  - {rf['code']} ({rf['severity']})")
                    print(f"    {rf['explanation']}")

            # Blast radius
            blast = risk.get("blast_radius", {})
            if blast:
                print(f"\nBlast radius: {blast['scope']} (confidence: {blast['confidence']})")
                print(f"  {blast['estimate']}")

            # Reversibility
            rev = risk.get("reversibility", {})
            if rev:
                print(f"\nReversibility: {rev['estimate']}")
                if rev.get('notes'):
                    print(f"  {rev['notes']}")

        # Missing info
        missing = payload.get("missing_info", [])
        if missing:
            print(f"\nMissing info:")
            for mi in missing:
                blocking = " (blocking)" if mi.get("blocking") else ""
                print(f"  - {mi['field']}{blocking}: {mi['question']}")

        # Recommended constraints
        constraints = payload.get("recommended_constraints")
        if constraints:
            print(f"\nRecommended constraints if approved:")
            print(f"  - ttl: {constraints['ttl_seconds']}s ({constraints['ttl_seconds']//60}m)")
            print(f"  - max_steps: {constraints['max_steps']}")
            if constraints.get("forbidden_patterns"):
                print(f"  - forbid patterns: {', '.join(constraints['forbidden_patterns'])}")

        print()

    def cmd_approve(self, args):
        """Approve a decision with explicit confirmation"""
        # Handle --all flag
        if args.all:
            return self._approve_all(args)

        # Single decision approval
        decision_id = args.decision_id

        if not decision_id:
            print("Error: decision_id is required unless using --all")
            return 1

        # Query decision
        decisions = self.backend.get_pending_approvals()
        decision = next((d for d in decisions if d["id"] == decision_id), None)

        if not decision:
            print(f"Error: Pending decision {decision_id} not found")
            return 1

        # Show what will be approved
        print("You are approving an action.\n")

        print(f"Agent: {decision['agent_id']}")
        print(f"Action: {decision['action']}")

        if decision.get("context"):
            if "command" in decision["context"]:
                print(f"\nCommand:")
                print(f"  {decision['context']['command']}")

        # Check for Decision Intelligence recommendations (if intelligence enabled)
        config = get_config()
        recommended_steps = 1
        recommended_duration = 5
        missing_info_questions = []

        if config.intelligence_enabled:
            dir_data = self.backend.get_decision_intel(decision_id)
        else:
            dir_data = None

        if dir_data:
            payload = dir_data["payload"]
            constraints = payload.get("recommended_constraints")

            if constraints:
                recommended_steps = constraints.get("max_steps", 1)
                recommended_duration = constraints.get("ttl_seconds", 300) // 60

                print("\nRecommended constraints (based on risk assessment):")
                print(f"  - Max steps: {recommended_steps}")
                print(f"  - Duration: {recommended_duration} minutes")

                if constraints.get("forbidden_patterns"):
                    print(f"  - Forbid patterns: {', '.join(constraints['forbidden_patterns'])}")

                print("\n(Override with --max-steps and --duration flags if needed)")

            # Extract missing info questions for saturation tracking
            missing_info = payload.get("missing_info", [])
            missing_info_questions = [mi.get("field", "") for mi in missing_info]

        # Calculate lease parameters (use recommended or override)
        max_steps = args.max_steps or recommended_steps
        duration_minutes = args.duration or recommended_duration

        print(f"\nThis will issue a lease with:")
        print(f"  - Max steps: {max_steps}")
        print(f"  - Expiration: {duration_minutes} minutes")

        # Confirmation prompt
        print(f"\nApprove? (y/n):")
        confirmation = input("> ").strip().lower()

        if confirmation not in ['y', 'yes']:
            print("\n✗ Approval cancelled")
            return 1

        # Issue lease
        lease_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(minutes=duration_minutes)

        # Update the decision with the lease
        self.backend.update_decision(
            decision_id=decision_id,
            outcome="approved",
            lease_id=lease_id,
        )

        # Record approval action
        self.backend.record_action(
            action_id=f"approval-{uuid.uuid4()}",
            agent_id="human:cli",
            action="approve_decision",
            status="approved",
            result={
                "decision_id": decision_id,
                "lease_id": lease_id,
                "max_steps": max_steps,
                "expires_at": expires_at.isoformat(),
            },
            context={"decision": decision},
            tags=["approval", "human"],
        )

        # Record human approval for saturation tracking (v2.5)
        self.backend.record_human_approval(
            approval_id=f"human-{uuid.uuid4()}",
            decision_id=decision_id,
            human_outcome="approved",
            recommended_max_steps=recommended_steps,
            actual_max_steps=max_steps,
            recommended_duration_minutes=recommended_duration,
            actual_duration_minutes=duration_minutes,
            missing_info_questions=missing_info_questions,
            missing_info_resolved=[],  # TODO: collect from human in future
            rationale=args.comment,  # Human's explanation for approval
        )

        print(f"\n✓ Approved")
        print(f"Lease issued: {lease_id[:8]}...")
        print(f"Expires at: {expires_at.strftime('%H:%M:%S')}")

        if args.comment:
            print(f"Rationale: {args.comment}")

    def _approve_all(self, args):
        """Approve all pending decisions"""
        pending = self.backend.get_pending_approvals()

        if not pending:
            print("No pending approvals.")
            return 0

        # Show all pending decisions
        print(f"You are about to approve {len(pending)} pending decision(s):\n")
        for i, dec in enumerate(pending, 1):
            print(f"{i}. {dec['action']}")
            if dec.get("context") and "command" in dec["context"]:
                print(f"   Command: {dec['context']['command']}")
            print()

        # Get config for recommended constraints
        config = get_config()
        max_steps = args.max_steps or 1
        duration_minutes = args.duration or 5

        print(f"Each lease will have:")
        print(f"  - Max steps: {max_steps}")
        print(f"  - Expiration: {duration_minutes} minutes")

        # Confirmation
        print(f"\nApprove all {len(pending)} decisions? (y/n):")
        confirmation = input("> ").strip().lower()

        if confirmation not in ['y', 'yes']:
            print("\n✗ Batch approval cancelled")
            return 1

        # Approve each decision
        print(f"\n✅ Approving {len(pending)} decisions...")
        approved_count = 0

        for decision in pending:
            decision_id = decision["id"]
            lease_id = str(uuid.uuid4())
            expires_at = datetime.now() + timedelta(minutes=duration_minutes)

            # Update decision with lease
            self.backend.update_decision(
                decision_id=decision_id,
                outcome="approved",
                lease_id=lease_id,
            )

            # Record approval action
            self.backend.record_action(
                action_id=f"approval-{uuid.uuid4()}",
                agent_id="human:cli",
                action="approve_decision",
                status="approved",
                result={
                    "decision_id": decision_id,
                    "lease_id": lease_id,
                    "max_steps": max_steps,
                    "expires_at": expires_at.isoformat(),
                },
                context={"decision": decision},
                tags=["approval", "human", "batch"],
            )

            # Record human approval for saturation tracking
            self.backend.record_human_approval(
                approval_id=f"human-{uuid.uuid4()}",
                decision_id=decision_id,
                human_outcome="approved",
                recommended_max_steps=1,
                actual_max_steps=max_steps,
                recommended_duration_minutes=5,
                actual_duration_minutes=duration_minutes,
                missing_info_questions=[],
                missing_info_resolved=[],
                rationale=args.comment or "Batch approval",
            )

            approved_count += 1
            print(f"  ✓ Approved {decision['action'][:50]}... (lease: {lease_id[:8]}...)")

        print(f"\n✓ Successfully approved {approved_count} decision(s)")
        if args.comment:
            print(f"Rationale: {args.comment}")

        return 0

    def cmd_deny(self, args):
        """Deny a decision"""
        # Handle --all flag
        if args.all:
            return self._deny_all(args)

        # Single decision denial
        decision_id = args.decision_id

        if not decision_id:
            print("Error: decision_id is required unless using --all")
            return 1

        comment = args.comment or "Denied by human operator"

        # Query decision
        decisions = self.backend.get_pending_approvals()
        decision = next((d for d in decisions if d["id"] == decision_id), None)

        if not decision:
            print(f"Error: Pending decision {decision_id} not found")
            return 1

        # Get DIR data for saturation tracking
        dir_data = self.backend.get_decision_intel(decision_id)
        missing_info_questions = []
        if dir_data:
            payload = dir_data["payload"]
            missing_info = payload.get("missing_info", [])
            missing_info_questions = [mi.get("field", "") for mi in missing_info]

        # Update the decision to mark it as denied
        self.backend.update_decision(
            decision_id=decision_id,
            outcome="denied",
        )

        # Record denial
        self.backend.record_action(
            action_id=f"denial-{uuid.uuid4()}",
            agent_id="human:cli",
            action="deny_decision",
            status="denied",
            result={"decision_id": decision_id, "reason": comment},
            context={"decision": decision},
            tags=["denial", "human"],
        )

        # Record human denial for saturation tracking (v2.5)
        self.backend.record_human_approval(
            approval_id=f"human-{uuid.uuid4()}",
            decision_id=decision_id,
            human_outcome="denied",
            missing_info_questions=missing_info_questions,
            missing_info_resolved=[],
            rationale=args.comment,  # Human's explanation for denial
        )

        print(f"✗ Denied")
        print(f"Decision {decision_id} closed")

        if args.comment:
            print(f"Rationale: {args.comment}")

    def _deny_all(self, args):
        """Deny all pending decisions"""
        pending = self.backend.get_pending_approvals()

        if not pending:
            print("No pending approvals.")
            return 0

        # Show all pending decisions
        print(f"You are about to deny {len(pending)} pending decision(s):\n")
        for i, dec in enumerate(pending, 1):
            print(f"{i}. {dec['action']}")
            if dec.get("context") and "command" in dec["context"]:
                print(f"   Command: {dec['context']['command']}")
            print()

        # Confirmation
        print(f"\nDeny all {len(pending)} decisions? (y/n):")
        confirmation = input("> ").strip().lower()

        if confirmation not in ['y', 'yes']:
            print("\n✗ Batch denial cancelled")
            return 1

        # Deny each decision
        print(f"\n🚫 Denying {len(pending)} decisions...")
        denied_count = 0
        comment = args.comment or "Batch denial by human operator"

        for decision in pending:
            decision_id = decision["id"]

            # Get DIR data for saturation tracking
            dir_data = self.backend.get_decision_intel(decision_id)
            missing_info_questions = []
            if dir_data:
                payload = dir_data["payload"]
                missing_info = payload.get("missing_info", [])
                missing_info_questions = [mi.get("field", "") for mi in missing_info]

            # Update decision to denied
            self.backend.update_decision(
                decision_id=decision_id,
                outcome="denied",
            )

            # Record denial
            self.backend.record_action(
                action_id=f"denial-{uuid.uuid4()}",
                agent_id="human:cli",
                action="deny_decision",
                status="denied",
                result={"decision_id": decision_id, "reason": comment},
                context={"decision": decision},
                tags=["denial", "human", "batch"],
            )

            # Record human denial for saturation tracking
            self.backend.record_human_approval(
                approval_id=f"human-{uuid.uuid4()}",
                decision_id=decision_id,
                human_outcome="denied",
                missing_info_questions=missing_info_questions,
                missing_info_resolved=[],
                rationale=comment,
            )

            denied_count += 1
            print(f"  ✓ Denied {decision['action'][:50]}...")

        print(f"\n✓ Successfully denied {denied_count} decision(s)")
        if args.comment:
            print(f"Rationale: {args.comment}")

        return 0

    def cmd_revoke(self, args):
        """Revoke an active lease"""
        lease_id = args.lease_id
        comment = args.comment or "Revoked by human operator"

        # Record revocation
        self.backend.record_revocation(
            revocation_id=f"rev-{uuid.uuid4()}",
            lease_id=lease_id,
            agent_id="unknown",  # Would need to look up from lease
            reason="human_override",
            revoked_by="human:cli",
            description=comment,
        )

        print(f"✓ Lease revoked")
        print(f"Agent execution halted")

        if args.comment:
            print(f"Rationale: {args.comment}")

    def cmd_policy_validate(self, args):
        """Validate YAML policy without compiling"""
        policy_file = args.policy_file

        try:
            compiler = PolicyCompiler()
            policy = compiler.compile(policy_file)
            print(f"✓ Valid policy: {policy.name}")
            print(f"  Rules: {len(policy.rules)}")
            print(f"  Default: {policy.default_outcome.value}")
        except PolicyCompilationError as e:
            print(f"✗ Invalid policy: {e}")
            return 1
        except FileNotFoundError:
            print(f"✗ File not found: {policy_file}")
            return 1

    def cmd_policy_compile(self, args):
        """Show compiled policy rules"""
        policy_file = args.policy_file

        try:
            compiler = PolicyCompiler()
            policy = compiler.compile(policy_file)

            print(f"Policy: {policy.name}\n")
            print(f"Default outcome: {policy.default_outcome.value}")
            print(f"Default reason: {policy.default_reason}\n")
            print(f"Rules ({len(policy.rules)}):\n")

            for i, rule in enumerate(policy.rules, 1):
                print(f"{i}. {rule.name}")
                print(f"   Action: {rule.action_pattern}")
                if rule.scope_constraints:
                    print(f"   Scope: {rule.scope_constraints}")
                print(f"   Outcome: {rule.outcome.value}")
                print(f"   Reason: {rule.reason}")
                if rule.max_steps:
                    print(f"   Max steps: {rule.max_steps}")
                if rule.max_duration_minutes:
                    print(f"   Max duration: {rule.max_duration_minutes} minutes")
                print()

        except PolicyCompilationError as e:
            print(f"✗ Compilation failed: {e}")
            return 1
        except FileNotFoundError:
            print(f"✗ File not found: {policy_file}")
            return 1

    def cmd_policy_explain(self, args):
        """Explain a specific policy rule"""
        policy_file = args.policy_file
        rule_id = args.rule_id

        try:
            compiler = PolicyCompiler()
            policy = compiler.compile(policy_file)

            explanation = compiler.explain(policy, rule_id)
            if explanation:
                print(explanation)
            else:
                print(f"✗ Rule not found: {rule_id}")
                print(f"\nAvailable rules:")
                for rule in policy.rules:
                    print(f"  - {rule.name}")
                return 1

        except PolicyCompilationError as e:
            print(f"✗ Compilation failed: {e}")
            return 1
        except FileNotFoundError:
            print(f"✗ File not found: {policy_file}")
            return 1

    def cmd_status(self, args):
        """Show Ward system status overview"""
        from datetime import datetime, timedelta

        # Get pending approvals
        pending = self.backend.get_pending_approvals()

        # Get recent revocations (last 24h)
        all_revocations = self.backend.get_revocations()
        now = datetime.now()
        recent_revocations = [
            r
            for r in all_revocations
            if (now - datetime.fromisoformat(r["timestamp"])) < timedelta(hours=24)
        ]

        # Get total decisions
        all_decisions = self.backend.get_decisions()

        # Count active leases (approved decisions with leases)
        active_leases = sum(1 for d in all_decisions if d.get("lease_id") and d["outcome"] == "approved")

        print("\nWard Status")
        print("=" * 60)
        print(f"Active leases: {active_leases}")
        print(f"Pending approvals: {len(pending)}")
        print(f"Revocations (last 24h): {len(recent_revocations)}")
        print(f"Total decisions: {len(all_decisions)}")
        print("=" * 60 + "\n")

    def cmd_saturation(self, args):
        """Show decision saturation metrics for LLM readiness"""
        metrics = self.backend.calculate_decision_saturation()

        print("\nDecision Saturation Metrics")
        print("=" * 60)
        print(f"Total human decisions: {metrics['total_decisions']} / {metrics['target_decisions']}")
        print(f"Saturation score: {metrics['saturation_score']:.1%} (target: {metrics['target_saturation']:.0%})")
        print()
        print("Breakdown:")
        print(f"  Constraints acceptance: {metrics['constraints_acceptance_rate']:.1%}")
        print(f"  Missing info resolution: {metrics['missing_info_resolution_rate']:.1%}")
        print()

        if metrics["ready_for_llm"]:
            print("✓ READY FOR LLM")
            print("  Humans are repeating themselves consistently.")
            print("  Proceed to next LLM readiness check.")
        else:
            print("✗ NOT READY FOR LLM")
            if metrics["total_decisions"] < metrics["target_decisions"]:
                needed = metrics["target_decisions"] - metrics["total_decisions"]
                print(f"  Need {needed} more decisions for statistical significance.")
            if metrics["saturation_score"] < metrics["target_saturation"]:
                print(f"  Saturation too low - humans are not repeating themselves.")
                print(f"  This means decisions are still unpredictable.")

        print("\nStatus:", metrics["status"])
        print("=" * 60 + "\n")

    def cmd_leases(self, args) -> int:
        """Show active leases"""
        print("\nActive Leases")
        print("=" * 80)

        # Get approved decisions with lease_ids
        decisions = self.backend.get_decisions(outcome="approved", limit=1000)

        if not decisions:
            print("No active leases found.\n")
            return 0

        # Get revocations to filter out revoked leases
        conn = sqlite3.connect(self.backend.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT lease_id FROM revocations")
        revoked_lease_ids = {row["lease_id"] for row in cursor.fetchall()}

        # Get approval actions to find lease details (max_steps, expires_at)
        cursor.execute("""
            SELECT result FROM actions
            WHERE action = 'approve_decision'
            AND status = 'approved'
        """)
        approval_actions = cursor.fetchall()
        conn.close()

        # Build lease_id -> details map
        lease_details = {}
        for action in approval_actions:
            result = json.loads(action["result"])
            lease_id = result.get("lease_id")
            if lease_id:
                lease_details[lease_id] = {
                    "max_steps": result.get("max_steps", 1),
                    "expires_at": result.get("expires_at", "unknown"),
                    "decision_id": result.get("decision_id", "unknown"),
                }

        # Filter and display active leases
        active_count = 0
        now = datetime.now()

        for decision in decisions:
            lease_id = decision["lease_id"]

            # Skip if revoked
            if lease_id in revoked_lease_ids:
                continue

            # Get lease details
            details = lease_details.get(lease_id, {})
            expires_at_str = details.get("expires_at", "unknown")

            # Check if expired
            if expires_at_str != "unknown":
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    if now > expires_at:
                        continue  # Skip expired leases
                except ValueError:
                    pass  # If we can't parse, show it anyway

            # This lease is active
            active_count += 1

            print(f"\nLease ID: {lease_id}")
            print(f"Agent: {decision['agent_id']}")
            print(f"Action: {decision['action']}")
            print(f"Decision ID: {decision['id']}")
            print(f"Max steps: {details.get('max_steps', 'unknown')}")
            print(f"Expires at: {expires_at_str}")

            if expires_at_str != "unknown":
                try:
                    expires_at = datetime.fromisoformat(expires_at_str)
                    time_left = expires_at - now
                    minutes_left = int(time_left.total_seconds() / 60)
                    print(f"Time remaining: {minutes_left} minutes")
                except ValueError:
                    pass

        print("\n" + "=" * 80)
        print(f"Total active leases: {active_count}\n")
        return 0

    def cmd_config(self, args) -> int:
        """Show Ward configuration and feature flags"""
        config = get_config()

        print("\nWard Configuration")
        print("=" * 80)

        # Intelligence Kill-Switch Status
        status = "ENABLED ✓" if config.intelligence_enabled else "DISABLED (safe mode)"
        status_color = "🟢" if config.intelligence_enabled else "🔴"

        print(f"\n{status_color} Intelligence Features: {status}")

        if config.intelligence_enabled:
            print("\n  Active features:")
            print("  - Decision Intelligence Reports (DIRs)")
            print("  - Risk assessment generation")
            print("  - Advisory features")
            print("\n  ⚠️  LLM integration is ENABLED")
            print("  To disable: export WARD_ENABLE_INTELLIGENCE=0")
        else:
            print("\n  Ward is running in deterministic mode:")
            print("  ✓ Policies work")
            print("  ✓ Human approvals work")
            print("  ✓ Leases work")
            print("  ✓ Audit works")
            print("  ✗ DIRs disabled")
            print("  ✗ Risk assessment disabled")
            print("\n  To enable: export WARD_ENABLE_INTELLIGENCE=1")

        print("\n" + "=" * 80)
        print("\nEnvironment Variables:")
        print(f"  WARD_ENABLE_INTELLIGENCE = {config.intelligence_enabled}")
        print(f"  WARD_VERBOSE = {config.verbose}")
        print("\n" + "=" * 80 + "\n")

        return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="ward",
        description="Ward - Human approval interface for AI agent control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--db",
        default="ward.db",
        help="Path to Ward database (default: ward.db)",
    )

    parser.add_argument(
        "--no-intelligence",
        action="store_true",
        help="Disable intelligence features (DIRs, LLM). Proves deterministic fallback works.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # ward approvals
    subparsers.add_parser("approvals", help="List pending approvals")

    # ward inspect <decision_id>
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a decision")
    inspect_parser.add_argument("decision_id", help="Decision ID to inspect")

    # ward approve <decision_id>
    approve_parser = subparsers.add_parser(
        "approve", help="Approve a decision (requires confirmation)"
    )
    approve_parser.add_argument("decision_id", nargs="?", help="Decision ID to approve (not needed with --all)")
    approve_parser.add_argument(
        "--all",
        action="store_true",
        help="Approve all pending decisions",
    )
    approve_parser.add_argument(
        "--max-steps",
        type=int,
        help="Maximum steps for lease (default: 1)",
    )
    approve_parser.add_argument(
        "--duration",
        type=int,
        help="Lease duration in minutes (default: 5)",
    )
    approve_parser.add_argument(
        "-m",
        "--comment",
        help="Explain why you approved this decision",
    )

    # ward deny <decision_id>
    deny_parser = subparsers.add_parser("deny", help="Deny a decision")
    deny_parser.add_argument("decision_id", nargs="?", help="Decision ID to deny (not needed with --all)")
    deny_parser.add_argument(
        "--all",
        action="store_true",
        help="Deny all pending decisions",
    )
    deny_parser.add_argument(
        "-m",
        "--comment",
        help="Explain why you denied this decision",
    )

    # ward revoke <lease_id>
    revoke_parser = subparsers.add_parser("revoke", help="Revoke an active lease")
    revoke_parser.add_argument("lease_id", help="Lease ID to revoke")
    revoke_parser.add_argument(
        "-m",
        "--comment",
        help="Explain why you revoked this lease",
    )

    # ward policy-validate <policy_file>
    policy_validate_parser = subparsers.add_parser(
        "policy-validate", help="Validate YAML policy"
    )
    policy_validate_parser.add_argument("policy_file", help="Path to YAML policy file")

    # ward policy-compile <policy_file>
    policy_compile_parser = subparsers.add_parser(
        "policy-compile", help="Show compiled policy rules"
    )
    policy_compile_parser.add_argument("policy_file", help="Path to YAML policy file")

    # ward policy-explain <policy_file> <rule_id>
    policy_explain_parser = subparsers.add_parser(
        "policy-explain", help="Explain a specific policy rule"
    )
    policy_explain_parser.add_argument("policy_file", help="Path to YAML policy file")
    policy_explain_parser.add_argument("rule_id", help="Rule ID to explain")

    # ward status
    subparsers.add_parser("status", help="Show Ward system status overview")

    # ward saturation
    subparsers.add_parser("saturation", help="Show decision saturation metrics (LLM readiness)")

    # ward leases
    subparsers.add_parser("leases", help="List active leases")

    # ward config
    subparsers.add_parser("config", help="Show configuration and feature flags")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Handle --no-intelligence flag (deterministic fallback)
    if args.no_intelligence:
        config = get_config()
        config.disable_intelligence()
        print("⚠️  Intelligence features DISABLED (deterministic mode)")
        print("   DIRs will not be displayed\n")

    # Create CLI instance
    cli = WardCLI(db_path=args.db)

    # Dispatch command
    if args.command == "approvals":
        return cli.cmd_approvals(args) or 0
    elif args.command == "inspect":
        return cli.cmd_inspect(args) or 0
    elif args.command == "approve":
        return cli.cmd_approve(args) or 0
    elif args.command == "deny":
        return cli.cmd_deny(args) or 0
    elif args.command == "revoke":
        return cli.cmd_revoke(args) or 0
    elif args.command == "policy-validate":
        return cli.cmd_policy_validate(args) or 0
    elif args.command == "policy-compile":
        return cli.cmd_policy_compile(args) or 0
    elif args.command == "policy-explain":
        return cli.cmd_policy_explain(args) or 0
    elif args.command == "status":
        return cli.cmd_status(args) or 0
    elif args.command == "saturation":
        return cli.cmd_saturation(args) or 0
    elif args.command == "leases":
        return cli.cmd_leases(args) or 0
    elif args.command == "config":
        return cli.cmd_config(args) or 0
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
