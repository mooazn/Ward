#!/usr/bin/env python3
"""
Ward v2 Demo - Decision Intelligence

Demonstrates:
1. Agent attempts dangerous command
2. DIR generated with risk assessment
3. Human reviews structured decision context via CLI
4. Recommended constraints shown
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ward.agent import ShellAgent
from ward.storage import SQLiteAuditBackend


def print_section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def demo():
    print("\nWard v2 Demo - Decision Intelligence")
    print("━" * 60)
    print("Rules-based risk assessment (no LLMs)\n")

    # Setup
    backend = SQLiteAuditBackend("ward_v2_demo.db")
    policy = ShellAgent.create_shell_policy()
    agent = ShellAgent(
        agent_id="shell-agent-1",
        policy=policy,
        backend=backend,
        auto_request=True,
        generate_dir=True,  # Enable v2 DIR generation
    )

    # ═══════════════════════════════════════════════════════
    # Scenario 1: Critical risk - destructive in prod
    # ═══════════════════════════════════════════════════════
    print_section("Scenario 1: Critical Risk Command")

    print("Agent attempts: rm -rf /prod/database")
    result = agent.run("rm -rf /prod/database")

    print(f"Result: {'Allowed' if result.allowed else 'Blocked'}")
    print(f"Reason: {result.reason}")

    if not result.allowed:
        print("\nDIR generated - view with:")
        print("  ward --db ward_v2_demo.db approvals")
        print("  ward --db ward_v2_demo.db inspect <decision_id>")

    # ═══════════════════════════════════════════════════════
    # Scenario 2: High risk - SQL drop
    # ═══════════════════════════════════════════════════════
    print_section("Scenario 2: High Risk Command")

    print("Agent attempts: mysql -e 'DROP DATABASE test'")
    result = agent.run("mysql -e 'DROP DATABASE test'")

    print(f"Result: {'Allowed' if result.allowed else 'Blocked'}")
    print(f"Reason: {result.reason}")

    # ═══════════════════════════════════════════════════════
    # Scenario 3: Safe command
    # ═══════════════════════════════════════════════════════
    print_section("Scenario 3: Safe Command")

    print("Agent attempts: ls -la /tmp")
    result = agent.run("ls -la /tmp")

    print(f"Result: {'Allowed' if result.allowed else 'Blocked'}")
    print(f"Reason: {result.reason}")

    # ═══════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════
    print_section("Summary")

    pending = backend.get_pending_approvals()
    print(f"Pending approvals: {len(pending)}")

    if pending:
        print("\nTo review with Decision Intelligence:")
        print(f"  1. ward --db ward_v2_demo.db approvals")
        print(f"  2. ward --db ward_v2_demo.db inspect <id>")
        print(f"  3. ward --db ward_v2_demo.db approve <id>")

        print("\nYou'll see:")
        print("  - Risk level (CRITICAL/HIGH/MEDIUM/LOW)")
        print("  - Specific risk factors detected")
        print("  - Blast radius estimate")
        print("  - Reversibility assessment")
        print("  - Missing info to gather")
        print("  - Recommended lease constraints")

    print("\nDatabase: ward_v2_demo.db")
    print("━" * 60 + "\n")


if __name__ == "__main__":
    demo()
