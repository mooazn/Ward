# Ward Changelog

All notable changes to Ward will be documented in this file.

---

## [2.5.0] - 2026-02-01

### Summary
Ward v2.5 introduces async agent support, improved CLI usability, and cleaner repository structure.

### Added
- **AsyncAgent Base Class** (`ward/agent/async_agent.py`)
  - Reusable base class for async approval handling
  - Eliminates 100+ lines of boilerplate per agent
  - Handles pending approvals, polling, and status checking automatically
  - See `ward/agent/ASYNC_AGENT_GUIDE.md` for usage guide

- **Backend Helper Methods** (SQLiteAuditBackend)
  - `check_decision_approved(decision_id)` - Returns lease_id if approved
  - `is_decision_denied(decision_id)` - Returns True if denied
  - `is_lease_revoked(lease_id)` - Returns True if revoked

- **Ward CLI Improvements**
  - Simplified approval: Type `y` instead of `APPROVE`
  - Batch operations: `ward approve --all` and `ward deny --all`
  - Support `-m` flag for batch rationale

- **Repository Structure**
  - `.gitignore` - Prevents database files and artifacts from being committed
  - `docs/design/` - Organized design documents
  - `ward/agent/ASYNC_AGENT_GUIDE.md` - User guide for AsyncAgent

### Changed
- **Package renamed** from `authority` to `ward`
- **deepseek_async.py** refactored to use AsyncAgent base class (110 fewer lines)
- Moved 8 design documents to `docs/design/` for better organization

### Removed
- Test databases (*.db files)
- Redundant demo files:
  - `basic_demo.py`
  - `v1_demo.py`
  - `persistence_demo.py`
  - `yaml_policy_demo.py`
  - ward wrapper script

### Migration Notes
**Package import change:**
```python
# Old (v2.0)
from ward.agent import ShellAgent

# New (v2.5)
from ward.agent import ShellAgent
```

**AsyncAgent usage:**
```python
from ward.agent import AsyncAgent
from ward.storage import SQLiteAuditBackend

class MyAgent(AsyncAgent):
    def __init__(self, agent_id, db_path):
        super().__init__(agent_id, SQLiteAuditBackend(db_path), poll_interval=2)
```

---

## [2.0.0] - 2025-01-31

### Summary
Ward v2.0 introduced YAML-based policies, Decision Intelligence Reports (DIRs), and decision saturation tracking for LLM readiness.

### Added
- **YAML Policy System**
  - `PolicyCompiler` - Compile YAML policies to Python objects
  - Human-readable policy files with validation
  - Example policies in `ward/examples/policies/`

- **Decision Intelligence Reports (DIRs)**
  - Automated risk assessment generation
  - Structured recommendations for constraints (max_steps, TTL)
  - Missing information tracking
  - Kill-switch controlled (`WARD_ENABLE_INTELLIGENCE` env var)

- **Decision Saturation Tracking (v2.5 feature prep)**
  - Tracks human approval patterns
  - Measures decision repeatability
  - Calculates saturation score for LLM readiness
  - `ward saturation` CLI command

- **LLM Advisory System**
  - Rules-based intelligence generator
  - One-way flow: LLM → Human (never Human → LLM)
  - Advisory-only mode (humans make final decisions)

- **Configuration Management**
  - `ward/config.py` - Centralized config with feature flags
  - `ward config` CLI command to view settings

- **Enhanced CLI**
  - `ward inspect <decision_id>` - Inspect decisions with DIRs
  - `ward policy-validate` - Validate YAML policies
  - `ward policy-compile` - View compiled policy rules
  - `ward policy-explain` - Explain specific policy rules

### Changed
- Policies can now be loaded from YAML files
- Decision Intelligence integrated into approval workflow
- Deterministic fallback when intelligence is disabled

### Documentation
- `DETERMINISTIC_FALLBACK.md` - How Ward works without LLMs
- `KILL_SWITCH.md` - Intelligence feature kill-switch design
- `LLM_ADVISOR_CONTRACT.md` - LLM integration contract
- `LLM_READINESS.md` - Decision saturation methodology
- `ONE_WAY_FLOW.md` - LLM → Human flow principle

---

## [1.0.0] - 2025-01-30

### Summary
Ward v1.0 established the core control plane with policies, leases, and human-in-the-loop approvals.

### Added
- **Core Control Plane**
  - `Policy` - Define rules for agent actions
  - `PolicyRule` - Individual rules with action patterns and constraints
  - `Lease` - Time-limited, step-limited execution permissions
  - `Decision` - Authority request outcomes (APPROVED, DENIED, NEEDS_HUMAN)
  - `RevocationRecord` - Track lease revocations

- **ShellAgent**
  - Agent wrapper enforcing Ward control
  - Automatic policy evaluation
  - Lease management and verification
  - Action recording and audit trails

- **SQLite Audit Backend**
  - Persistent storage for decisions, actions, revocations
  - Query interface for human review
  - Full audit trail of agent activity

- **Ward CLI**
  - `ward approvals` - List pending approvals
  - `ward approve <id>` - Approve with explicit confirmation
  - `ward deny <id>` - Deny a pending decision
  - `ward revoke <lease_id>` - Revoke active lease
  - `ward status` - System status overview
  - `ward leases` - View active leases

- **Core Principles**
  - Explicit authority required for all actions
  - Time-limited, step-limited leases
  - Human-in-the-loop for sensitive operations
  - Full auditability of agent actions
  - Instant revocation capability

### Documentation
- `README.md` - Project overview and quick start
- `INTEGRATION_GUIDE.md` - Integration patterns for agents
- `AUTHORITY_AUDIT.md` - Audit system design
- `RATIONALE_TRACKING.md` - Human rationale capture

---

## Version History

- **v2.5.0** (2026-02-01) - AsyncAgent, CLI improvements, package rename
- **v2.0.0** (2025-01-31) - YAML policies, DIRs, saturation tracking
- **v1.0.0** (2025-01-30) - Initial release with core control plane

---

## Links

- **GitHub**: https://github.com/mooazn/Ward
- **Issues**: https://github.com/mooazn/Ward/issues
- **Documentation**: See README.md and INTEGRATION_GUIDE.md
