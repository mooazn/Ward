# Ward

**A control plane for long-running AI agents with explicit authority, time-limited leases, and full auditability.**

## The Problem

AI agents need boundaries. Ward enforces them with:
- **Explicit authority** - Agents must request permission before acting
- **Time-limited leases** - Authority expires automatically
- **Human oversight** - Critical actions require approval
- **Full audit trail** - Every decision is logged with context

## Quick Example

An LLM agent tries to delete a production file:

```
Enter your request:
> please remove the prod_data.txt file in the dir

💬 DeepSeek: To remove prod_data.txt, I need to know the directory
             and environment (dev/staging/prod) for safety...

Your response:
> it is in the current directory, in dev

🔧 DeepSeek wants to call: execute_bash
   Args: {'command': 'rm prod_data.txt', 'environment': 'dev'}

🔍 Requesting: execute_bash
   Context: {'env': 'dev', 'destructive': True, 'resource': 'shell'}
   ⏸️  Awaiting approval: Action requires approval
   📋 Decision ID: dec-505a8b24...

======================================================================
⏸️  Waiting for 1 approval(s)
======================================================================

Pending decisions:
  - execute_bash: {'command': 'rm prod_data.txt', 'environment': 'dev'}

Approve all? (y=yes, n=no, w=wait for manual approval)
> n

🚫 Denying all pending decisions...
✓ All decisions denied

💬 DeepSeek: Understood! The deletion of prod_data.txt in the dev
             environment has been denied. Let me know if there's
             anything else you'd like assistance with.
```

**Ward prevented the deletion** and gave the human full control.

## What Ward Does

Ward sits between your agent and execution:

```
┌─────────┐    request    ┌──────┐   if approved   ┌──────────┐
│  Agent  │─────────────→ │ Ward │─────────────────→│ Execute  │
│ (LLM)   │               │      │                  │ (Shell)  │
└─────────┘               └───┬──┘                  └──────────┘
                              │
                              ↓
                         [ Human CLI ]
                         ward approve/deny
```

**For safe actions:** Auto-approved (read-only, dev environment)
**For risky actions:** Human approval required (destructive, prod)

## Core Features

### 1. Async Agent Support (v2.5)
```python
from ward.agent import AsyncAgent
from ward.storage import SQLiteAuditBackend

class MyAgent(AsyncAgent):
    def __init__(self, agent_id, db_path):
        super().__init__(agent_id, SQLiteAuditBackend(db_path), poll_interval=2)

    # Your agent requests authority
    # Ward pauses execution if human approval needed
    # Agent resumes when approved
```

### 2. YAML Policies
```yaml
version: 1
policy: production-safety

rules:
  - id: safe_reads_in_dev
    when:
      action: shell_exec
      env: dev
      destructive: false
    then:
      outcome: allow
      max_steps: 10
      max_duration_minutes: 5

  - id: review_destructive
    when:
      destructive: true
    then:
      outcome: needs_human
      reason: Destructive action requires approval
```

### 3. Human CLI
```bash
# View pending decisions
ward approvals

# Approve single decision
ward approve dec-123 -m "Reviewed, safe to proceed"

# Approve all pending
ward approve --all -m "Batch approval"

# Deny
ward deny dec-123 -m "Too risky"

# Revoke active lease
ward revoke lease-456 -m "Security review needed"
```

### 4. Decision Intelligence
Ward provides structured context for human decisions:
- Risk assessment (critical/high/medium/low)
- Blast radius estimation
- Reversibility analysis
- Missing information detection
- Recommended constraints

```bash
ward inspect dec-123

# Output:
# Risk: CRITICAL
#   - DESTRUCTIVE_RM (high)
#   - DESTRUCTIVE_IN_PROD (critical)
#
# Blast radius: service (confidence: medium)
# Reversibility: irreversible
#
# Recommended constraints:
#   - ttl: 5m
#   - max_steps: 1
```

## Quick Start

```bash
# Install
pip install -e .

# Run tests
pytest ward/tests/

# Try the example
cd ward/examples
python deepseek_async.py

# Use the CLI
python -m ward.cli.ward approvals
python -m ward.cli.ward approve --all
```

## Integration

### Basic Integration
```python
from ward.agent import ShellAgent
from ward.core import Policy, PolicyRule, PolicyOutcome

# Define policy
policy = Policy(
    name="my-policy",
    rules=[
        PolicyRule(
            name="prod_requires_human",
            action_pattern=r".*",
            outcome=PolicyOutcome.NEEDS_HUMAN,
            reason="Production actions need approval",
            scope_constraints={"env": "prod"}
        )
    ]
)

# Wrap your agent
agent = ShellAgent(
    agent_id="my-agent-1",
    policy=policy,
    backend=SQLiteAuditBackend("ward.db")
)

# Request authority
decision = agent.request_authority("deploy", context={"env": "prod"})

if decision.is_approved():
    # Execute with lease
    result = agent.execute("deploy", lease_id=decision.lease.lease_id)
```

### Async Agent (v2.5)
For agents that need to continue working while waiting for approval:

```python
from ward.agent import AsyncAgent

class MyAsyncAgent(AsyncAgent):
    def execute_action(self, action_name, action_args, lease_id):
        # Your execution logic
        return result

# Add to pending queue when NEEDS_HUMAN
agent.add_pending_approval(
    decision_id=decision_id,
    action_name="deploy",
    action_args={"target": "prod"}
)

# Poll for approvals
results = agent.check_pending_approvals(execute_callback)
```

See `ward/agent/ASYNC_AGENT_GUIDE.md` for complete guide.

## Architecture

Ward is:
- **Model-agnostic** - Works with any LLM
- **Framework-agnostic** - Integrates with any agent system
- **Minimal** - No unnecessary dependencies
- **Auditable** - Full trail of decisions and actions
- **Production-ready** - SQLite backend, comprehensive tests

Ward is NOT:
- An agent framework
- An orchestration system
- A UI/dashboard
- A replacement for human judgment

## Design Principles

1. **Explicit authority** - No action without explicit lease
2. **Time-limited** - All authority expires
3. **Deny by default** - Unknown = needs approval
4. **Full auditability** - Every decision logged
5. **Human-in-the-loop** - Critical decisions require humans
6. **Instant revocation** - Stop agents immediately if needed

## Version History

- **v2.5.0** (2026-02-01) - AsyncAgent, CLI improvements, package rename
- **v2.0.0** (2025-01-31) - YAML policies, Decision Intelligence
- **v1.0.0** (2025-01-30) - Core control plane

See [CHANGELOG.md](CHANGELOG.md) for details.

## Examples

- **ward/examples/deepseek_async.py** - Full async LLM agent with Ward
- **ward/examples/v2_demo.py** - Core features demo
- **ward/examples/policies/** - YAML policy examples

## Documentation

- [CHANGELOG.md](CHANGELOG.md) - Version history
- [ward/agent/ASYNC_AGENT_GUIDE.md](ward/agent/ASYNC_AGENT_GUIDE.md) - AsyncAgent usage

## License

MIT
