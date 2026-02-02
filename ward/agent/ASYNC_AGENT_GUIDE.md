# AsyncAgent Guide

The `AsyncAgent` base class provides a reusable pattern for agents that need to handle asynchronous human approvals.

## Problem It Solves

When your agent requests authority from Ward and gets `NEEDS_HUMAN`, the agent needs to:
1. Queue the action for later execution
2. Poll the database to check when it's approved/denied
3. Execute when approved
4. Handle denials and revocations

This pattern is common across many agents, so `AsyncAgent` provides it as reusable infrastructure.

## Usage

### Basic Example

```python
from ward.agent import AsyncAgent
from ward.storage import SQLiteAuditBackend

class MyAgent(AsyncAgent):
    def __init__(self, agent_id: str, db_path: str):
        super().__init__(
            agent_id=agent_id,
            backend=SQLiteAuditBackend(db_path),
            poll_interval=2  # Poll every 2 seconds
        )

    def my_action(self, action_args: dict, lease_id: str):
        """Execute your action with Ward lease"""
        # Your execution logic here
        result = do_something(action_args)
        return result

# Use the agent
agent = MyAgent("my-agent-1", "ward.db")

# When you get NEEDS_HUMAN from Ward
decision_id = "dec-123..."
agent.add_pending_approval(
    decision_id=decision_id,
    action_name="my_action",
    action_args={"param": "value"}
)

# Define execution callback
def execute_when_approved(action_name, action_args, lease_id):
    if action_name == "my_action":
        return agent.my_action(action_args, lease_id)

# Poll for approvals
while agent.has_pending_approvals():
    time.sleep(agent.poll_interval)
    results = agent.check_pending_approvals(execute_when_approved)

    for result in results:
        print(f"{result['status']}: {result['result']}")
```

### Advanced: Callback Data

You can pass callback data that will be returned with results:

```python
agent.add_pending_approval(
    decision_id=decision_id,
    action_name="execute_bash",
    action_args={"command": "ls -la"},
    callback_data={"tool_call_id": "abc123"}  # LLM-specific data
)

results = agent.check_pending_approvals(execute_callback)
for r in results:
    tool_call_id = r["callback_data"]["tool_call_id"]
    # Use this to match with LLM conversation
```

## API Reference

### Methods

#### `add_pending_approval(decision_id, action_name, action_args, callback_data=None)`
Add an action to the pending approvals queue.

**Args:**
- `decision_id`: ID of the Ward decision awaiting approval
- `action_name`: Name of your action to execute
- `action_args`: Arguments dict for your action
- `callback_data`: Optional dict to pass through to results

#### `check_pending_approvals(execute_callback) -> List[Dict]`
Check database for approval status changes and execute approved actions.

**Args:**
- `execute_callback`: Function `(action_name, action_args, lease_id) -> result`

**Returns:**
List of results with format:
```python
{
    "decision_id": "dec-123",
    "action_name": "my_action",
    "action_args": {...},
    "callback_data": {...},
    "result": "...",  # Your execution result or error message
    "status": "executed"  # or "denied", "revoked", "error"
}
```

#### `poll_until_resolved(execute_callback, timeout=None) -> List[Dict]`
Continuously poll until all pending approvals are resolved.

**Args:**
- `execute_callback`: Function to call when approved
- `timeout`: Optional timeout in seconds

**Returns:**
List of all results

#### `has_pending_approvals() -> bool`
Check if any approvals are pending.

#### `get_pending_count() -> int`
Get count of pending approvals.

## Backend Helpers

The `SQLiteAuditBackend` now includes helper methods for checking approval status:

### `check_decision_approved(decision_id) -> Optional[str]`
Returns lease_id if approved, None otherwise.

```python
lease_id = backend.check_decision_approved("dec-123")
if lease_id:
    print(f"Approved! Lease: {lease_id}")
```

### `is_decision_denied(decision_id) -> bool`
Returns True if explicitly denied.

```python
if backend.is_decision_denied("dec-123"):
    print("Human denied this action")
```

### `is_lease_revoked(lease_id) -> bool`
Returns True if lease was revoked.

```python
if backend.is_lease_revoked("lease-456"):
    print("Human revoked this lease")
```

## Full Example

See `ward/examples/deepseek_async.py` for a complete implementation using `AsyncAgent` with an LLM agent.

## Architecture

```
┌─────────────────┐
│  Your Agent     │
│  (extends       │
│  AsyncAgent)    │
└────────┬────────┘
         │
         │ add_pending_approval()
         ▼
┌─────────────────┐
│  Pending Queue  │
│  (in memory)    │
└────────┬────────┘
         │
         │ check_pending_approvals()
         ▼
┌─────────────────┐      ┌──────────────┐
│  SQLite Backend │◄────►│  Human CLI   │
│  (disk)         │      │  (ward)      │
└────────┬────────┘      └──────────────┘
         │
         │ Status: approved/denied/revoked
         ▼
┌─────────────────┐
│  Execute Action │
│  (with lease)   │
└─────────────────┘
```

## When to Use

Use `AsyncAgent` when:
- Your agent needs to handle `NEEDS_HUMAN` decisions
- You want to continue working while waiting for approval
- You need to poll for approval status changes

Don't use `AsyncAgent` when:
- All your actions auto-approve (use `ShellAgent` directly)
- You want blocking behavior (just wait for approval before continuing)
