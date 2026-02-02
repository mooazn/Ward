# Ward + DeepSeek Integration Setup

## Installation

### 1. Install Dependencies

```bash
# Install OpenAI client (OpenRouter is compatible)
pip install openai

# Or add to your requirements.txt:
echo "openai>=1.0.0" >> requirements.txt
pip install -r requirements.txt
```

### 2. Set Up Environment

```bash
# Option A: Shell environment variable (recommended)
export LLM_API_KEY="your-new-key-here"

# Option B: .env file (for development)
cp ward/examples/.env.example .env
# Edit .env and add your key
```

### 3. Test the Integration

```bash
# Run the demo
python ward/examples/deepseek_integration.py
```

Expected output:
```
======================================================================
  Ward + DeepSeek (OpenRouter) Integration Demo
======================================================================

✓ DeepSeek agent initialized with Ward protection
✓ Policy: 4 rules loaded
✓ Database: deepseek_integration.db

──────────────────────────────────────────────────────────────────────
Example: Ask DeepSeek to do something
──────────────────────────────────────────────────────────────────────

🤖 DeepSeek wants to call: execute_bash
   Arguments: {'command': 'ls /tmp', 'environment': 'dev'}
   ✅ Ward approved via policy: allow_dev_safe

🤖 DeepSeek: I've listed the files in /tmp directory...
```

---

## How It Works

### The Flow

```
User Message
    ↓
DeepSeek (via OpenRouter)
    ↓
Wants to call tool → Ward checks policy
    ↓
    ├─ APPROVED → Execute tool → Return result to DeepSeek
    ├─ NEEDS_HUMAN → Pause, notify human via CLI
    └─ DENIED → Tell DeepSeek it's blocked
```

### Policy Rules

The default policy:
- ✅ **Auto-approves:** Read operations, safe dev commands
- ⏸️ **Needs human:** Destructive commands, staging/prod changes
- 🚫 **Denied:** (You define these based on risk)

### Customizing the Policy

Edit `create_deepseek_policy()` in [deepseek_integration.py](deepseek_integration.py):

```python
def create_deepseek_policy() -> Policy:
    rules = [
        # Your custom rules here
        PolicyRule(
            name="allow_my_specific_action",
            action_pattern="read_file.*",  # Regex pattern
            outcome=PolicyOutcome.ALLOW,
            reason="This is safe because...",
            scope_constraints={
                "env": "dev",
                "destructive": False
            },
            max_steps=5,
            max_duration_minutes=10,
        ),
    ]
    return Policy(name="my_policy", rules=rules)
```

Add auto-approval rules for safe, repetitive actions:

```python
PolicyRule(
    name="allow_status_checks",
    action_pattern="execute_bash.*git status.*",
    outcome=PolicyOutcome.ALLOW,
    reason="Git status is always safe",
    scope_constraints={"destructive": False},
)
```

---

## Monitoring & Debugging

### Check Decision History

```bash
# All decisions
PYTHONPATH=. python ward/cli/ward.py --db deepseek_ward.db approvals

# Filter by outcome
# (Requires adding filter to CLI - see TODO)
```

### View Saturation Metrics

```bash
ward saturation --db deepseek_ward.db
```

### Export for Analysis

```bash
# SQLite is just a file - use standard tools
sqlite3 deepseek_ward.db "SELECT * FROM decisions ORDER BY timestamp DESC LIMIT 100" > recent_decisions.csv
```

### Debug Tool Calls

Add logging to `_execute_tool_with_ward()`:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

def _execute_tool_with_ward(...):
    logging.debug(f"Tool: {tool_name}, Args: {tool_args}, Context: {context}")
    # ... rest of method
```

---

### Optimization Tips

1. **Batch operations** when possible
2. **Cache READ operations** (safe to cache)
3. **Use streaming** for long responses
4. **Set max_tokens** to avoid runaway generation
