#!/usr/bin/env python3
"""
Ward + DeepSeek (Async) - Proper Approval Workflow

This implementation separates request/approval/execution into distinct phases,
allowing DeepSeek to work on other tasks while waiting for approvals.

Usage:
    Terminal 1: python deepseek_async.py agent  # Run agent
    Terminal 2: ward approve <id>               # Approve requests
    Terminal 1: (agent auto-resumes)
"""

import sys
import os
import json
import uuid
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ward.core import Policy, PolicyRule, PolicyOutcome, DecisionOutcome
from ward.agent import ShellAgent, AsyncAgent
from ward.storage import SQLiteAuditBackend

try:
    from openai import OpenAI
except ImportError:
    print("Error: openai package not installed")
    print("Install with: pip install openai")
    sys.exit(1)


class AsyncDeepSeekAgent(AsyncAgent):
    """
    DeepSeek agent with proper async approval handling.

    Architecture:
    1. Agent submits requests to Ward → Gets decision
    2. If NEEDS_HUMAN → Adds to pending queue, moves to next task
    3. Background checker polls for approvals
    4. When approved → Executes and continues
    """

    def __init__(
        self,
        agent_id: str,
        policy: Policy,
        db_path: str = "deepseek_async.db",
        poll_interval: int = 2,
    ):
        # Initialize AsyncAgent base class
        super().__init__(
            agent_id=agent_id,
            backend=SQLiteAuditBackend(db_path),
            poll_interval=poll_interval,
        )

        self.ward = ShellAgent(
            agent_id=agent_id,
            policy=policy,
            backend=self.backend,
            auto_request=False,
            generate_dir=True,
        )

        # Initialize LLM client (provider-agnostic)
        api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        base_url = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")

        if not api_key:
            print("⚠️  LLM_API_KEY not set")
            print("Set it: export LLM_API_KEY='your-key'")
            print("Optional: export LLM_BASE_URL='https://api.openai.com/v1'")
            print("\nRunning in demo mode...")
            self.client = None
        else:
            self.client = OpenAI(
                base_url=base_url,
                api_key=api_key,
            )
            if os.environ.get("WARD_VERBOSE"):
                print(f"Using LLM endpoint: {base_url}")

        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "execute_bash",
                    "description": "Execute a bash command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "environment": {
                                "type": "string",
                                "enum": ["dev", "staging", "prod"],
                            },
                        },
                        "required": ["command", "environment"],
                    },
                },
            }
        ]

        self.conversation_history = []

    def request_tool_execution(
        self, tool_name: str, tool_args: Dict[str, Any], tool_call_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Request to execute a tool through Ward.

        Returns immediately with status:
        - executed: Tool ran successfully
        - awaiting_approval: Queued for human approval
        - denied: Blocked by policy
        """
        # Build context
        context = self._build_context(tool_name, tool_args)
        action = f"{tool_name}({json.dumps(tool_args)})"

        print(f"\n🔍 Requesting: {tool_name}")
        print(f"   Context: {context}")

        # Request authority
        decision = self.ward.request_authority(action, context=context)

        # Handle outcome
        if decision.outcome == DecisionOutcome.APPROVED:
            print(f"   ✅ Auto-approved by policy: {decision.rule_name}")
            # Execute immediately
            lease_id = self._get_lease_id(decision)
            result = self._execute_tool(tool_name, tool_args, lease_id)
            return {"status": "executed", "result": result}

        elif decision.outcome == DecisionOutcome.NEEDS_HUMAN:
            # Get decision ID
            decisions = self.backend.get_decisions(
                agent_id=self.agent_id, outcome="needs_human", limit=1
            )
            decision_id = decisions[0]["id"] if decisions else None

            if decision_id:
                # Add to pending queue using base class method
                self.add_pending_approval(
                    decision_id=decision_id,
                    action_name=tool_name,
                    action_args=tool_args,
                    callback_data={"tool_call_id": tool_call_id},
                )

                print(f"   ⏸️  Awaiting approval: {decision.reason}")
                print(f"   📋 Decision ID: {decision_id[:12]}...")
                print(
                    f"   Approve with: ward approve --db deepseek_async.db {decision_id}"
                )

                return {
                    "status": "awaiting_approval",
                    "decision_id": decision_id,
                    "message": "Action queued for human approval",
                }

        else:  # DENIED
            print(f"   🚫 Denied: {decision.reason}")
            return {"status": "denied", "reason": decision.reason}

    def check_pending_approvals(self) -> List[Dict[str, Any]]:
        """
        Check if any pending approvals have been approved or denied.

        Returns list of executed results for approved items.
        For denied items, returns denial message.
        """
        # Use base class method with execution callback
        def execute_callback(action_name: str, action_args: Dict[str, Any], lease_id: str) -> str:
            """Execute the tool when approved"""
            print(f"\n✅ Approval detected...")
            print(f"   Executing: {action_name}")
            return self._execute_tool(action_name, action_args, lease_id)

        results = super().check_pending_approvals(execute_callback)

        # Print status for each result
        for result in results:
            decision_id = result["decision_id"]
            status = result["status"]

            if status == "denied":
                print(f"\n🚫 Denial detected for {decision_id[:12]}...")
                print(f"   Action: {result['action_name']}")
            elif status == "revoked":
                print(f"\n🚫 Revocation detected for {decision_id[:12]}...")
                print(f"   Action: {result['action_name']}")

        # Transform results to match expected format (add tool_call_id from callback_data)
        return [
            {
                "decision_id": r["decision_id"],
                "tool_name": r["action_name"],
                "tool_args": r["action_args"],
                "tool_call_id": r["callback_data"].get("tool_call_id"),
                "result": r["result"],
                "status": r["status"],
            }
            for r in results
        ]

    def _get_lease_id(self, decision) -> str:
        """Extract lease ID from decision"""
        # For auto-approved decisions, get from database
        decisions = self.backend.get_decisions(
            agent_id=self.agent_id, outcome="approved", limit=1
        )
        if decisions:
            return decisions[0].get("lease_id", str(uuid.uuid4()))
        return str(uuid.uuid4())

    def _build_context(
        self, tool_name: str, tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build risk context for Ward"""
        context = {}
        context["env"] = tool_args.get("environment", "dev")

        if tool_name == "execute_bash":
            command = tool_args.get("command", "")
            context["destructive"] = self._is_destructive_command(command)
            context["resource"] = "shell"
        else:
            context["destructive"] = False
            context["resource"] = "unknown"

        return context

    def _is_destructive_command(self, command: str) -> bool:
        """Detect if command is destructive"""
        destructive_patterns = [
            "rm ",
            "delete",
            "drop",
            "truncate",
            "kill",
        ]
        return any(pattern in command.lower() for pattern in destructive_patterns)

    def _execute_tool(
        self, tool_name: str, tool_args: Dict[str, Any], lease_id: str
    ) -> str:
        """Execute the tool with Ward lease"""
        try:
            if tool_name == "execute_bash":
                # ACTUALLY execute the command
                command = tool_args['command']
                print(f"   🚀 Executing: {command}")

                result_obj = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                output = result_obj.stdout
                error = result_obj.stderr

                if result_obj.returncode == 0:
                    result = f"Command executed successfully:\n{output}" if output else "Command executed successfully (no output)"
                else:
                    result = f"Command failed (exit code {result_obj.returncode}):\n{error}"
            else:
                result = f"[SIMULATED] Executed {tool_name}"

            # Record successful action
            self.backend.record_action(
                action_id=str(uuid.uuid4()),
                agent_id=self.agent_id,
                action=f"{tool_name}({json.dumps(tool_args)})",
                lease_id=lease_id,
                status="success",
                result={"output": result},
            )

            print(f"   ✓ Executed with lease {lease_id[:8]}...")
            return result

        except subprocess.TimeoutExpired:
            error_msg = "Command timed out (30s limit)"
            self.backend.record_action(
                action_id=str(uuid.uuid4()),
                agent_id=self.agent_id,
                action=f"{tool_name}({json.dumps(tool_args)})",
                lease_id=lease_id,
                status="failed",
                result={"error": error_msg},
            )
            return f"[ERROR] {error_msg}"
        except Exception as e:
            # Record failure
            self.backend.record_action(
                action_id=str(uuid.uuid4()),
                agent_id=self.agent_id,
                action=f"{tool_name}({json.dumps(tool_args)})",
                lease_id=lease_id,
                status="failed",
                result={"error": str(e)},
            )
            return f"[ERROR] {str(e)}"

    def run_agent_loop(self, max_iterations: int = 10):
        """
        Run agent loop with approval handling.

        Agent will:
        1. Request tool execution
        2. If needs approval, continue to other work
        3. Periodically check for approvals
        4. Resume when approved
        """
        print("\n" + "=" * 70)
        print("  DeepSeek Async Agent - Ward Protected")
        print("=" * 70)
        print(f"\nAgent ID: {self.agent_id}")
        print(f"Database: deepseek_async.db")
        print(f"Poll interval: {self.poll_interval}s")
        print("\n" + "=" * 70 + "\n")

        if not self.client:
            print("Running in DEMO mode (no OpenRouter API key)\n")
            self._demo_workflow()
        else:
            print("Running full DeepSeek conversation loop\n")
            self._deepseek_conversation()

    def _deepseek_conversation(self):
        """Run full DeepSeek conversation with async approval handling"""
        # Get user query
        print("Enter your request (or 'demo' for demo workflow):")
        user_query = input("> ").strip()

        if user_query.lower() == "demo":
            self._demo_workflow()
            return

        # Initialize conversation
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant that can execute bash commands. "
                "Always specify the environment (dev/staging/prod) when using execute_bash. "
                "For safe operations use dev, for testing use staging, for live use prod.",
            },
            {"role": "user", "content": user_query},
        ]

        print(f"\n{'='*70}")
        print("🤖 DeepSeek is thinking...")
        print(f"{'='*70}\n")

        iteration = 0
        max_iterations = 10

        while iteration < max_iterations:
            iteration += 1

            # Call LLM
            model = os.environ.get("LLM_MODEL", "deepseek/deepseek-chat")
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=self.tools,
                    tool_choice="auto",
                )
            except Exception as e:
                print(f"❌ DeepSeek API error: {e}")
                break

            assistant_message = response.choices[0].message

            # Check if DeepSeek wants to call tools
            if assistant_message.tool_calls:
                # Process each tool call
                # Convert to dict format for message history
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })

                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)

                    print(f"\n🔧 DeepSeek wants to call: {tool_name}")
                    print(f"   Args: {tool_args}")

                    # Request authority from Ward
                    result = self.request_tool_execution(tool_name, tool_args, tool_call.id)

                    # Handle result based on status
                    if result["status"] == "executed":
                        # Tool executed successfully
                        tool_result = result["result"]
                        print(f"   ✅ Executed successfully")

                    elif result["status"] == "awaiting_approval":
                        # Queued for approval - tell DeepSeek to wait
                        tool_result = (
                            "⏸️  This action requires human approval. "
                            f"Decision ID: {result['decision_id']}. "
                            "Waiting for approval..."
                        )
                        print(f"   ⏸️  Queued for approval")

                    else:  # denied
                        tool_result = f"❌ Action denied: {result.get('reason', 'Policy violation')}"
                        print(f"   ❌ Denied by policy")

                    # Add tool result to conversation
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )

                # Check for pending approvals before continuing
                if self.pending_approvals:
                    print(f"\n{'='*70}")
                    print(f"⏸️  Waiting for {len(self.pending_approvals)} approval(s)")
                    print(f"{'='*70}")

                    # Show pending decisions
                    print("\nPending decisions:")
                    for dec_id in self.pending_approvals.keys():
                        tool_info = self.pending_approvals[dec_id]
                        print(f"  - {tool_info['tool_name']}: {tool_info['tool_args']}")

                    # Quick approve/deny option
                    print("\nApprove all? (y=yes, n=no, w=wait for manual approval)")
                    choice = input("> ").strip().lower()

                    if choice == 'y':
                        # Approve all pending
                        print("\n✅ Approving all pending decisions...")
                        for dec_id in list(self.pending_approvals.keys()):
                            subprocess.run([
                                "python", "-m", "ward.cli.ward",
                                "--db", "deepseek_async.db",
                                "approve", dec_id,
                                "-m", "Approved via interactive prompt"
                            ], capture_output=True)
                        print("✓ All decisions approved\n")
                        # Let the polling loop handle execution

                    elif choice == 'n':
                        # Deny all pending
                        print("\n🚫 Denying all pending decisions...")
                        for dec_id in list(self.pending_approvals.keys()):
                            subprocess.run([
                                "python", "-m", "ward.cli.ward",
                                "--db", "deepseek_async.db",
                                "deny", dec_id,
                                "-m", "Denied via interactive prompt"
                            ], capture_output=True)
                        print("✓ All decisions denied\n")
                        # Let the polling loop handle the denials

                    else:
                        # Wait for manual approval
                        print("\n⏳ Waiting for manual approval in another terminal:")
                        for dec_id in self.pending_approvals.keys():
                            print(f"  ./ward --db deepseek_async.db approve {dec_id}")

                    print(f"\nPolling every {self.poll_interval}s for approvals...")
                    print("(Press Ctrl+C to stop)\n")

                    # Poll for approvals
                    try:
                        while self.pending_approvals:
                            time.sleep(self.poll_interval)
                            approved = self.check_pending_approvals()

                            if approved:
                                print(f"\n✅ {len(approved)} decision(s) processed!")

                                # Update the conversation with real results
                                # Find the tool messages by tool_call_id and update them
                                for approval in approved:
                                    tool_call_id = approval.get("tool_call_id")
                                    if not tool_call_id:
                                        continue

                                    # Format result based on status
                                    status = approval.get("status", "executed")
                                    if status == "executed":
                                        result_msg = f"✅ Approved and executed:\n{approval['result']}"
                                    elif status == "denied":
                                        result_msg = f"❌ Denied by human:\n{approval['result']}"
                                    elif status == "revoked":
                                        result_msg = f"🚫 Revoked by human:\n{approval['result']}"
                                    else:
                                        result_msg = approval['result']

                                    # Find the exact tool message with this tool_call_id
                                    for msg in messages:
                                        if (isinstance(msg, dict) and
                                            msg.get("role") == "tool" and
                                            msg.get("tool_call_id") == tool_call_id):
                                            # Update with actual result
                                            msg["content"] = result_msg
                                            break

                        print("\n✓ All decisions processed, continuing conversation...\n")

                    except KeyboardInterrupt:
                        print(f"\n⏸️  Paused. {len(self.pending_approvals)} approvals still pending.")
                        print("Run this script again to resume.")
                        break

            else:
                # DeepSeek is responding with text (no tool calls)
                response_text = assistant_message.content
                if response_text:
                    print(f"\n{'='*70}")
                    print("💬 DeepSeek:")
                    print(f"{'='*70}")
                    print(f"\n{response_text}\n")
                    print(f"{'='*70}\n")

                    # Add assistant's response to conversation
                    messages.append({
                        "role": "assistant",
                        "content": response_text
                    })

                    # Get user's follow-up input
                    print("Your response (or 'exit' to quit):")
                    user_input = input("> ").strip()

                    if user_input.lower() in ['exit', 'quit', 'q']:
                        print("\n👋 Conversation ended.\n")
                        break

                    # Add user's response to conversation
                    messages.append({
                        "role": "user",
                        "content": user_input
                    })

                    print(f"\n{'='*70}")
                    print("🤖 DeepSeek is thinking...")
                    print(f"{'='*70}\n")

                    # Continue the loop
                else:
                    # No response and no tool calls - conversation ended
                    break

        if iteration >= max_iterations:
            print(f"\n⚠️  Reached maximum iterations ({max_iterations})")

        print(f"{'='*70}\n")

    def _demo_workflow(self):
        """Demo workflow showing approval handling"""
        print("Demo: Requesting 3 tool executions...\n")

        # Request 1: Should auto-approve (safe dev command)
        print("─" * 70)
        result1 = self.request_tool_execution(
            "execute_bash", {"command": "ls /tmp", "environment": "dev"}
        )

        # Request 2: Needs approval (destructive)
        print("\n" + "─" * 70)
        result2 = self.request_tool_execution(
            "execute_bash",
            {"command": "rm -rf /tmp/cache", "environment": "staging"},
        )

        # Request 3: Needs approval (prod)
        print("\n" + "─" * 70)
        result3 = self.request_tool_execution(
            "execute_bash",
            {"command": "ls /var/log", "environment": "prod"},
        )

        print("\n" + "=" * 70)
        print("  Summary")
        print("=" * 70)
        print(f"\nPending approvals: {len(self.pending_approvals)}")

        if self.pending_approvals:
            print("\nWaiting for human approval...")
            print("In another terminal, run:")
            for dec_id in self.pending_approvals.keys():
                print(f"  ward approve --db deepseek_async.db {dec_id}")

            print(f"\nPolling for approvals every {self.poll_interval}s...")
            print("(Press Ctrl+C to stop)\n")

            # Poll for approvals
            try:
                while self.pending_approvals:
                    time.sleep(self.poll_interval)
                    results = self.check_pending_approvals()

                    if results:
                        print(
                            f"\n✅ {len(results)} approvals processed!"
                        )
                        for r in results:
                            print(f"   - {r['tool_name']}: {r['result'][:50]}...")

                print("\n✓ All approvals processed!")

            except KeyboardInterrupt:
                print(
                    f"\n\n⏸️  Stopped. Still waiting for {len(self.pending_approvals)} approvals"
                )

        print("\n" + "=" * 70 + "\n")


def create_async_policy() -> Policy:
    """Policy for async DeepSeek agent"""
    rules = [
        # Safe reads in dev - auto-approve
        PolicyRule(
            name="allow_dev_reads",
            action_pattern=".*",  # Match any action
            outcome=PolicyOutcome.ALLOW,
            reason="Safe dev commands allowed",
            scope_constraints={"env": "dev", "destructive": False},
            max_steps=10,
            max_duration_minutes=5,
        ),
        # Everything else needs human
        PolicyRule(
            name="review_other",
            action_pattern=".*",
            outcome=PolicyOutcome.NEEDS_HUMAN,
            reason="Action requires approval",
            scope_constraints={},
            max_steps=5,
            max_duration_minutes=30,
        ),
    ]

    return Policy(
        name="deepseek_async_policy",
        rules=rules,
        default_outcome=PolicyOutcome.NEEDS_HUMAN,
    )


def main():
    """Run async DeepSeek agent"""
    policy = create_async_policy()
    agent = AsyncDeepSeekAgent(
        agent_id="deepseek-async-1",
        policy=policy,
        db_path="deepseek_async.db",
        poll_interval=2,
    )

    agent.run_agent_loop()


if __name__ == "__main__":
    main()
