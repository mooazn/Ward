"""
Async Agent - Base class for agents with asynchronous approval handling

Provides the common pattern of:
1. Requesting authority that may need human approval
2. Maintaining a queue of pending approvals
3. Polling for approval status changes
4. Executing once approved
"""

import time
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

from ward.storage import SQLiteAuditBackend


class PendingApproval:
    """Represents an action awaiting human approval"""

    def __init__(
        self,
        decision_id: str,
        action_name: str,
        action_args: Dict[str, Any],
        requested_at: float,
        callback_data: Optional[Dict[str, Any]] = None,
    ):
        self.decision_id = decision_id
        self.action_name = action_name
        self.action_args = action_args
        self.requested_at = requested_at
        self.callback_data = callback_data or {}


class AsyncAgent:
    """
    Base class for agents that handle asynchronous approvals.

    Usage:
        class MyAgent(AsyncAgent):
            def execute_action(self, action_name, action_args, lease_id):
                # Your execution logic here
                return result
    """

    def __init__(
        self,
        agent_id: str,
        backend: SQLiteAuditBackend,
        poll_interval: int = 2,
    ):
        self.agent_id = agent_id
        self.backend = backend
        self.poll_interval = poll_interval

        # Pending approvals queue: decision_id → PendingApproval
        self.pending_approvals: Dict[str, PendingApproval] = {}

    def add_pending_approval(
        self,
        decision_id: str,
        action_name: str,
        action_args: Dict[str, Any],
        callback_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add an action to the pending approvals queue.

        Args:
            decision_id: ID of the decision awaiting approval
            action_name: Name of the action to execute
            action_args: Arguments for the action
            callback_data: Optional data to pass to execution callback
        """
        self.pending_approvals[decision_id] = PendingApproval(
            decision_id=decision_id,
            action_name=action_name,
            action_args=action_args,
            requested_at=time.time(),
            callback_data=callback_data,
        )

    def check_pending_approvals(
        self, execute_callback: Callable[[str, Dict[str, Any], str], Any]
    ) -> List[Dict[str, Any]]:
        """
        Check if any pending approvals have been approved, denied, or revoked.

        Args:
            execute_callback: Function to call when action is approved.
                             Signature: (action_name, action_args, lease_id) -> result

        Returns:
            List of processed approvals with their results
        """
        if not self.pending_approvals:
            return []

        results = []

        for decision_id in list(self.pending_approvals.keys()):
            approval = self.pending_approvals[decision_id]

            # Check for denial first
            if self.backend.is_decision_denied(decision_id):
                self.pending_approvals.pop(decision_id)
                results.append(
                    {
                        "decision_id": decision_id,
                        "action_name": approval.action_name,
                        "action_args": approval.action_args,
                        "callback_data": approval.callback_data,
                        "result": "Action was denied by human operator",
                        "status": "denied",
                    }
                )
                continue

            # Check for approval
            lease_id = self.backend.check_decision_approved(decision_id)

            if lease_id:
                # Check if lease was revoked
                if self.backend.is_lease_revoked(lease_id):
                    self.pending_approvals.pop(decision_id)
                    results.append(
                        {
                            "decision_id": decision_id,
                            "action_name": approval.action_name,
                            "action_args": approval.action_args,
                            "callback_data": approval.callback_data,
                            "result": "Action was revoked by human operator",
                            "status": "revoked",
                        }
                    )
                    continue

                # Approved and not revoked - execute!
                self.pending_approvals.pop(decision_id)

                try:
                    result = execute_callback(
                        approval.action_name, approval.action_args, lease_id
                    )
                    results.append(
                        {
                            "decision_id": decision_id,
                            "action_name": approval.action_name,
                            "action_args": approval.action_args,
                            "callback_data": approval.callback_data,
                            "result": result,
                            "status": "executed",
                        }
                    )
                except Exception as e:
                    results.append(
                        {
                            "decision_id": decision_id,
                            "action_name": approval.action_name,
                            "action_args": approval.action_args,
                            "callback_data": approval.callback_data,
                            "result": f"Execution error: {str(e)}",
                            "status": "error",
                        }
                    )

        return results

    def poll_until_resolved(
        self,
        execute_callback: Callable[[str, Dict[str, Any], str], Any],
        timeout: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Poll for approvals until all pending items are resolved or timeout.

        Args:
            execute_callback: Function to call when action is approved
            timeout: Optional timeout in seconds

        Returns:
            List of all processed approvals
        """
        all_results = []
        start_time = time.time()

        while self.pending_approvals:
            # Check timeout
            if timeout and (time.time() - start_time) > timeout:
                break

            # Wait before polling
            time.sleep(self.poll_interval)

            # Check for status changes
            results = self.check_pending_approvals(execute_callback)
            all_results.extend(results)

        return all_results

    def has_pending_approvals(self) -> bool:
        """Check if there are any pending approvals"""
        return len(self.pending_approvals) > 0

    def get_pending_count(self) -> int:
        """Get count of pending approvals"""
        return len(self.pending_approvals)

    def get_pending_decisions(self) -> List[PendingApproval]:
        """Get list of all pending approvals"""
        return list(self.pending_approvals.values())
