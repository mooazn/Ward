"""
Shell Agent - Enforced shell command execution through Ward

The agent:
- Cannot execute commands without Ward approval
- Verifies lease before every command
- Records all actions to audit log
- Respects lease constraints (expiration, max_steps, revocation)
"""

import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import re

from ward.core import (
    Policy,
    PolicyRule,
    PolicyOutcome,
    Lease,
    Decision,
    DecisionOutcome,
)
from ward.storage import SQLiteAuditBackend
from ward.intelligence import RulesBasedGenerator
from ward.config import get_config


@dataclass
class ExecutionResult:
    """Result of attempting to execute a command"""

    allowed: bool
    exit_code: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    reason: str
    lease_id: Optional[str] = None


class ShellAgent:
    """
    Shell agent that enforces Ward control plane.

    All commands flow through Ward. No direct shell access.
    """

    def __init__(
        self,
        agent_id: str,
        policy: Policy,
        backend: SQLiteAuditBackend,
        auto_request: bool = False,
        generate_dir: bool = True,
    ):
        """
        Initialize shell agent.

        Args:
            agent_id: Unique agent identifier
            policy: Policy for evaluating commands
            backend: Persistent audit backend
            auto_request: If True, automatically request authority (for demo)
            generate_dir: If True, generate Decision Intelligence Reports (v2)
        """
        self.agent_id = agent_id
        self.policy = policy
        self.backend = backend
        self.auto_request = auto_request
        self.active_leases: Dict[str, Lease] = {}

        # Intelligence features (DIRs) respect global kill-switch
        config = get_config()
        self.generate_dir = generate_dir and config.intelligence_enabled

        if self.generate_dir:
            self.dir_generator = RulesBasedGenerator()
        else:
            self.dir_generator = None

    def _is_dangerous_command(self, command: str) -> bool:
        """Check if command is potentially dangerous"""
        dangerous_patterns = [
            r"\brm\s+(-rf?|--recursive)",  # rm -rf
            r"\bsudo\b",  # sudo
            r"\b(curl|wget)\b.*\|\s*bash",  # curl/wget | bash
            r">\s*/dev/",  # Write to /dev
            r"mkfs\b",  # Format filesystem
            r"dd\b.*of=",  # dd with output
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True

        return False

    def request_authority(
        self, command: str, context: Optional[Dict[str, Any]] = None
    ) -> Decision:
        """
        Request authority to execute a command.

        Returns a Decision (which may include a Lease if approved).
        """
        context = context or {}
        context["command"] = command
        context["dangerous"] = self._is_dangerous_command(command)

        # Evaluate against policy
        outcome, reason, rule = self.policy.evaluate("shell_exec", context)

        decision_id = f"dec-{uuid.uuid4()}"

        if outcome == PolicyOutcome.ALLOW:
            # Create lease
            constraints = self.policy.get_constraints_for_action("shell_exec", context)

            lease = Lease(
                agent_id=self.agent_id,
                allowed_actions=["shell_exec"],
                expires_at=datetime.now()
                + timedelta(minutes=constraints.get("max_duration_minutes", 5)),
                max_steps=constraints.get("max_steps", 1),
                scope=context,
            )

            # Store active lease
            self.active_leases[lease.lease_id] = lease

            decision = Decision.approve(
                agent_id=self.agent_id,
                requested_action="shell_exec",
                lease=lease,
                reason=reason,
                constraints=constraints,
                policy_name=self.policy.name,
                rule_name=rule.name if rule else None,
            )

            # Record decision
            self.backend.record_decision(
                decision_id=decision_id,
                agent_id=self.agent_id,
                action="shell_exec",
                outcome="approved",
                reason=reason,
                context=context,
                policy_name=self.policy.name,
                rule_name=rule.name if rule else None,
                lease_id=lease.lease_id,
            )

        elif outcome == PolicyOutcome.DENY:
            decision = Decision.deny(
                agent_id=self.agent_id,
                requested_action="shell_exec",
                reason=reason,
                policy_name=self.policy.name,
                rule_name=rule.name if rule else None,
            )

            self.backend.record_decision(
                decision_id=decision_id,
                agent_id=self.agent_id,
                action="shell_exec",
                outcome="denied",
                reason=reason,
                context=context,
                policy_name=self.policy.name,
                rule_name=rule.name if rule else None,
            )

        else:  # NEEDS_HUMAN
            decision = Decision.needs_human(
                agent_id=self.agent_id,
                requested_action="shell_exec",
                reason=reason,
                context=context,
                policy_name=self.policy.name,
                rule_name=rule.name if rule else None,
            )

            self.backend.record_decision(
                decision_id=decision_id,
                agent_id=self.agent_id,
                action="shell_exec",
                outcome="needs_human",
                reason=reason,
                known_unknowns=["human approval pending"],
                context=context,
                policy_name=self.policy.name,
                rule_name=rule.name if rule else None,
            )

            # Generate and store DIR (v2)
            if self.generate_dir and self.dir_generator:
                dir_report = self.dir_generator.generate(
                    decision_id=decision_id,
                    agent_id=self.agent_id,
                    action="shell_exec",
                    context=context,
                )
                self.backend.store_decision_intel(
                    decision_id=decision_id,
                    payload=dir_report.to_dict(),
                    generated_at=dir_report.generated_at.isoformat(),
                    generator=dir_report.provenance.generator,
                    model=dir_report.provenance.model,
                )

        return decision

    def execute(self, command: str, lease_id: Optional[str] = None) -> ExecutionResult:
        """
        Execute a shell command (if authorized).

        Args:
            command: Shell command to execute
            lease_id: Lease ID to use (if None and auto_request=True, will request)

        Returns:
            ExecutionResult with outcome
        """
        # If no lease provided and auto_request enabled, request authority
        if lease_id is None and self.auto_request:
            decision = self.request_authority(command)

            if not decision.is_approved():
                reason = f"{decision.outcome.value}: {decision.reason}"
                return ExecutionResult(
                    allowed=False,
                    exit_code=None,
                    stdout=None,
                    stderr=None,
                    reason=reason,
                )

            lease_id = decision.lease.lease_id

        # Verify lease
        if lease_id not in self.active_leases:
            return ExecutionResult(
                allowed=False,
                exit_code=None,
                stdout=None,
                stderr=None,
                reason="No active lease found",
            )

        lease = self.active_leases[lease_id]

        # Check lease validity
        if not lease.is_valid():
            reason = "Lease expired or exhausted"
            if lease.revoked:
                reason = "Lease revoked"

            # Record blocked action
            self.backend.record_action(
                action_id=f"act-{uuid.uuid4()}",
                agent_id=self.agent_id,
                action="shell_exec",
                status="blocked",
                lease_id=lease_id,
                result={"reason": reason},
                context={"command": command},
                tags=["blocked", "shell"],
            )

            return ExecutionResult(
                allowed=False,
                exit_code=None,
                stdout=None,
                stderr=None,
                reason=reason,
                lease_id=lease_id,
            )

        # Execute command
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Record step
            lease.record_step()

            # Record action
            self.backend.record_action(
                action_id=f"act-{uuid.uuid4()}",
                agent_id=self.agent_id,
                action="shell_exec",
                status="success" if result.returncode == 0 else "failed",
                lease_id=lease_id,
                result={
                    "exit_code": result.returncode,
                    "stdout_length": len(result.stdout),
                    "stderr_length": len(result.stderr),
                },
                context={"command": command, "steps_taken": lease.steps_taken},
                tags=["executed", "shell"],
            )

            return ExecutionResult(
                allowed=True,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                reason="Executed successfully",
                lease_id=lease_id,
            )

        except subprocess.TimeoutExpired:
            self.backend.record_action(
                action_id=f"act-{uuid.uuid4()}",
                agent_id=self.agent_id,
                action="shell_exec",
                status="timeout",
                lease_id=lease_id,
                result={"error": "Command timed out"},
                context={"command": command},
                tags=["timeout", "shell"],
            )

            return ExecutionResult(
                allowed=True,
                exit_code=-1,
                stdout=None,
                stderr="Command timed out",
                reason="Timeout",
                lease_id=lease_id,
            )

        except Exception as e:
            self.backend.record_action(
                action_id=f"act-{uuid.uuid4()}",
                agent_id=self.agent_id,
                action="shell_exec",
                status="error",
                lease_id=lease_id,
                result={"error": str(e)},
                context={"command": command},
                tags=["error", "shell"],
            )

            return ExecutionResult(
                allowed=True,
                exit_code=-1,
                stdout=None,
                stderr=str(e),
                reason="Execution error",
                lease_id=lease_id,
            )

    def run(self, command: str) -> ExecutionResult:
        """
        Convenience method: request authority and execute if approved.

        This is the main entry point for the agent.
        """
        return self.execute(command, lease_id=None)

    @staticmethod
    def create_shell_policy() -> Policy:
        """Create a policy suitable for shell command evaluation"""
        return Policy(
            name="shell_safety",
            rules=[
                # Destructive commands require human approval
                PolicyRule(
                    name="destructive_command",
                    action_pattern=r"shell_exec",
                    outcome=PolicyOutcome.NEEDS_HUMAN,
                    reason="Destructive command requires approval",
                    scope_constraints={"dangerous": True},
                ),
                # Safe commands are allowed
                PolicyRule(
                    name="safe_command",
                    action_pattern=r"shell_exec",
                    outcome=PolicyOutcome.ALLOW,
                    reason="Safe command permitted",
                    scope_constraints={"dangerous": False},
                    max_steps=10,
                    max_duration_minutes=5,
                ),
            ],
            default_outcome=PolicyOutcome.NEEDS_HUMAN,
            default_reason="Unknown command requires review",
        )
