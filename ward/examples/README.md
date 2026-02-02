# Authority Examples

This directory contains example scripts and demonstrations of Ward's capabilities.

## Ground Truth Generation

### `generate_ground_truth.py`

Generates realistic historical ground truth data for testing Decision Saturation and preparing for LLM integration.

**Purpose:**
- Test the Decision Saturation tracking system
- Understand how to accumulate the 200 decisions needed for LLM readiness
- Simulate realistic command scenarios and human approval patterns

**Usage:**

```bash
# Generate 200 decisions (default)
python ward/examples/generate_ground_truth.py

# Generate custom count
python ward/examples/generate_ground_truth.py --count 250

# Use custom database
python ward/examples/generate_ground_truth.py --count 200 --db my_test.db
```

**What it does:**

1. **Generates diverse command scenarios:**
   - 60% safe commands (ls, cat, ps, df, etc.)
   - 30% risky commands (destructive in dev/staging)
   - 10% critical commands (destructive in prod - auto-denied)

2. **Simulates human decision patterns:**
   - 85% acceptance rate for recommended constraints
   - 90% resolution rate for missing information
   - Realistic override patterns when constraints are modified

3. **Creates saturation metrics:**
   - Tracks human approval consistency
   - Measures constraint acceptance rates
   - Monitors missing info resolution
   - Calculates overall saturation score

**Example output:**

```
🔧 Generating 225 historical decisions...
📊 Database: ground_truth.db

  ✓ Generated 20/225 decisions...
  ...
  ✓ Generated 225/225 decisions...

  🤖 Simulating human approvals...

✅ Generation complete!
   Decisions created: 225
   Human approvals recorded: 201

📈 Calculating saturation metrics...

============================================================
  DECISION SATURATION METRICS
============================================================
Total Decisions:              201
Constraints Acceptance Rate:  89.1%
Missing Info Resolution Rate: 100.0%
Saturation Score:             94.5%

Status: ready
Ready for LLM: ✓ Yes
============================================================
```

**Verifying results:**

```bash
# Check saturation metrics
PYTHONPATH=. python ward/cli/ward.py --db ground_truth.db saturation

# View system status
PYTHONPATH=. python ward/cli/ward.py --db ground_truth.db status

# Inspect specific approvals
PYTHONPATH=. python ward/cli/ward.py --db ground_truth.db approvals
```

## YAML Policy Demo

### `yaml_policy_demo.py`

Demonstrates loading and using YAML-defined policies with Ward.

```bash
python ward/examples/yaml_policy_demo.py
```

Shows:
- YAML policy compilation
- Policy rule evaluation
- Deterministic decision-making
- Integration with ShellAgent

## Policy Examples

### `policies/shell_safety.yaml`

Example YAML policy demonstrating:
- Environment-based rules (dev, staging, prod)
- Destructiveness checks
- Constraint specification
- Human approval requirements
