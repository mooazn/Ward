#!/usr/bin/env python3
"""
Generate realistic historical ground truth for Decision Saturation testing.

This script simulates realistic agent decision patterns to help reach the
200-decision threshold required for LLM readiness. It creates a variety of
scenarios across different risk levels and tracks human approval patterns.

Usage:
    python ward/examples/generate_ground_truth.py --count 200 --db ground_truth.db
"""

import sys
import random
import uuid
from pathlib import Path
from datetime import datetime, timedelta
import argparse

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ward.core import Policy, PolicyRule, PolicyOutcome
from ward.agent import ShellAgent
from ward.storage import SQLiteAuditBackend


# Realistic command scenarios by risk level
SAFE_COMMANDS = [
    ("ls -la", {"destructive": False, "resource": "filesystem"}),
    ("cat /etc/hosts", {"destructive": False, "resource": "filesystem"}),
    ("ps aux", {"destructive": False, "resource": "system"}),
    ("df -h", {"destructive": False, "resource": "system"}),
    ("grep error /var/log/app.log", {"destructive": False, "resource": "logs"}),
    ("curl https://api.example.com/status", {"destructive": False, "resource": "network"}),
    ("docker ps", {"destructive": False, "resource": "containers"}),
    ("git status", {"destructive": False, "resource": "vcs"}),
    ("npm test", {"destructive": False, "resource": "build"}),
    ("tail -f /var/log/app.log", {"destructive": False, "resource": "logs"}),
]

RISKY_COMMANDS = [
    ("rm -rf /tmp/cache/*", {"destructive": True, "env": "dev", "resource": "filesystem"}),
    ("docker restart web-service", {"destructive": True, "env": "staging", "resource": "containers"}),
    ("git push origin feature-branch", {"destructive": True, "env": "dev", "resource": "vcs"}),
    ("kubectl delete pod debug-pod", {"destructive": True, "env": "staging", "resource": "kubernetes"}),
    ("npm run migration:rollback", {"destructive": True, "env": "dev", "resource": "database"}),
    ("sudo systemctl restart nginx", {"destructive": True, "env": "staging", "resource": "services"}),
    ("terraform apply -auto-approve", {"destructive": True, "env": "dev", "resource": "infrastructure"}),
    ("ALTER TABLE users ADD COLUMN status VARCHAR", {"destructive": True, "env": "dev", "resource": "database"}),
]

CRITICAL_COMMANDS = [
    ("DROP DATABASE production", {"destructive": True, "env": "prod", "resource": "database"}),
    ("rm -rf /var/lib/postgresql/data", {"destructive": True, "env": "prod", "resource": "filesystem"}),
    ("kubectl delete namespace production", {"destructive": True, "env": "prod", "resource": "kubernetes"}),
    ("terraform destroy -auto-approve", {"destructive": True, "env": "prod", "resource": "infrastructure"}),
    ("sudo dd if=/dev/zero of=/dev/sda", {"destructive": True, "env": "prod", "resource": "system"}),
    ("aws s3 rb s3://production-backups --force", {"destructive": True, "env": "prod", "resource": "cloud"}),
]

# Missing info questions by resource type
MISSING_INFO_BY_RESOURCE = {
    "database": ["backup_status", "migration_tested", "rollback_plan"],
    "filesystem": ["backup_verified", "disk_space_checked"],
    "containers": ["health_check_status", "replica_count"],
    "kubernetes": ["deployment_yaml_reviewed", "rollback_available"],
    "infrastructure": ["terraform_plan_reviewed", "state_backup_confirmed"],
    "services": ["downstream_dependencies_checked", "monitoring_alerts_configured"],
    "cloud": ["iam_permissions_verified", "cost_impact_reviewed"],
}


def create_test_policy() -> Policy:
    """
    Create a realistic policy for testing that generates human approval decisions.

    For ground truth generation, we want most commands to require human review
    so we can build up approval history and saturation metrics.
    """
    rules = [
        # Prod destructive denied (no human needed)
        PolicyRule(
            name="deny_prod_destructive",
            action_pattern=".*",
            outcome=PolicyOutcome.DENY,
            reason="Production destructive actions not allowed",
            scope_constraints={"destructive": True, "env": "prod"},
        ),
        # Everything else needs human review (to generate approval data)
        PolicyRule(
            name="review_all_actions",
            action_pattern=".*",
            outcome=PolicyOutcome.NEEDS_HUMAN,
            reason="Action requires human approval",
            scope_constraints={},
            max_steps=5,
            max_duration_minutes=10,
        ),
    ]

    return Policy(
        name="ground_truth_policy",
        rules=rules,
        default_outcome=PolicyOutcome.NEEDS_HUMAN,
        default_reason="Unknown pattern requires review",
    )


def simulate_human_decision(command: str, context: dict, recommended_constraints: dict) -> dict:
    """
    Simulate realistic human decision-making.

    Humans mostly accept recommendations (80% saturation target) but sometimes override
    based on specific circumstances.
    """
    # Base acceptance rate: 85% accept recommendations
    accepts_constraints = random.random() < 0.85

    # Extract recommended values
    recommended_steps = recommended_constraints.get("max_steps", 1)
    recommended_duration = recommended_constraints.get("max_duration_minutes", 5)

    # Most humans accept recommendations
    if accepts_constraints:
        actual_steps = recommended_steps
        actual_duration = recommended_duration
    else:
        # Occasionally override with more permissive constraints
        actual_steps = recommended_steps + random.randint(1, 5)
        actual_duration = recommended_duration + random.randint(5, 15)

    # Generate missing info questions based on resource type
    resource = context.get("resource", "system")
    questions = MISSING_INFO_BY_RESOURCE.get(resource, ["status_checked"])

    # 90% of time humans resolve all questions
    if random.random() < 0.9:
        resolved = questions.copy()
    else:
        # Sometimes partial resolution
        resolved = random.sample(questions, k=max(1, len(questions) - 1))

    return {
        "actual_max_steps": actual_steps,
        "actual_duration_minutes": actual_duration,
        "missing_info_questions": questions,
        "missing_info_resolved": resolved,
    }


def generate_decisions(count: int, db_path: str):
    """Generate realistic ground truth decisions"""
    print(f"\n🔧 Generating {count} historical decisions...")
    print(f"📊 Database: {db_path}\n")

    backend = SQLiteAuditBackend(db_path)
    policy = create_test_policy()

    # Weight distributions (more safe commands, fewer critical)
    command_weights = [0.6, 0.3, 0.1]  # safe, risky, critical

    decisions_created = 0

    for i in range(count):
        # Select command based on weighted distribution
        command_type = random.choices(
            ["safe", "risky", "critical"],
            weights=command_weights
        )[0]

        if command_type == "safe":
            command, context = random.choice(SAFE_COMMANDS)
        elif command_type == "risky":
            command, context = random.choice(RISKY_COMMANDS)
        else:
            command, context = random.choice(CRITICAL_COMMANDS)

        # Create agent for this decision
        agent_id = f"agent-{random.randint(1, 10)}"
        agent = ShellAgent(
            agent_id=agent_id,
            policy=policy,
            backend=backend,
            auto_request=False,
            generate_dir=True,  # Enable DIR generation for approval tracking
        )

        # Request authority (this stores the decision and DIR in the database)
        _ = agent.request_authority(command, context=context)
        decisions_created += 1

        # Progress indicator
        if (i + 1) % 20 == 0:
            print(f"  ✓ Generated {i + 1}/{count} decisions...")

    # Now process all pending decisions that need human approval
    print(f"\n  🤖 Simulating human approvals...")
    pending = backend.get_decisions(outcome="needs_human", limit=count)
    approvals_recorded = 0

    for decision_data in pending:
        decision_id = decision_data["id"]
        command = decision_data["action"]
        context = decision_data["context"]

        # Get the DIR for this decision
        dir_data = backend.get_decision_intel(decision_id)

        if dir_data:
            # Extract recommended constraints from DIR
            recommended_steps = dir_data.get("recommended_max_steps", 1)
            recommended_duration = dir_data.get("recommended_duration_minutes", 5)

            recommended = {
                "max_steps": recommended_steps,
                "max_duration_minutes": recommended_duration,
            }

            # Simulate human decision
            human_decision = simulate_human_decision(command, context, recommended)

            # Record human approval
            backend.record_human_approval(
                approval_id=f"human-{uuid.uuid4()}",
                decision_id=decision_id,
                human_outcome="approved",
                recommended_max_steps=recommended["max_steps"],
                actual_max_steps=human_decision["actual_max_steps"],
                recommended_duration_minutes=recommended["max_duration_minutes"],
                actual_duration_minutes=human_decision["actual_duration_minutes"],
                missing_info_questions=human_decision["missing_info_questions"],
                missing_info_resolved=human_decision["missing_info_resolved"],
            )
            approvals_recorded += 1

    print(f"\n✅ Generation complete!")
    print(f"   Decisions created: {decisions_created}")
    print(f"   Human approvals recorded: {approvals_recorded}")

    # Calculate saturation
    print(f"\n📈 Calculating saturation metrics...\n")
    metrics = backend.calculate_decision_saturation()

    print("=" * 60)
    print("  DECISION SATURATION METRICS")
    print("=" * 60)
    print(f"Total Decisions:              {metrics['total_decisions']}")
    print(f"Constraints Acceptance Rate:  {metrics['constraints_acceptance_rate']:.1%}")
    print(f"Missing Info Resolution Rate: {metrics['missing_info_resolution_rate']:.1%}")
    print(f"Saturation Score:             {metrics['saturation_score']:.1%}")
    print(f"\nStatus: {metrics['status']}")
    print(f"Ready for LLM: {'✓ Yes' if metrics['ready_for_llm'] else '✗ No'}")

    if not metrics['ready_for_llm']:
        print(f"\nProgress: {metrics['total_decisions']}/{metrics['target_decisions']} decisions")
        print(f"          {metrics['saturation_score']:.1%}/{metrics['target_saturation']:.1%} saturation")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Generate realistic historical ground truth for Decision Saturation"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=200,
        help="Number of decisions to generate (default: 200)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="ground_truth.db",
        help="Database path (default: ground_truth.db)",
    )

    args = parser.parse_args()

    if args.count < 1:
        print("Error: count must be at least 1")
        sys.exit(1)

    generate_decisions(args.count, args.db)

    print(f"\n💡 Next steps:")
    print(f"   1. Review the database: {args.db}")
    print(f"   2. Check saturation: ward saturation --db {args.db}")
    print(f"   3. Use for testing: ward status --db {args.db}")
    print()


if __name__ == "__main__":
    main()
