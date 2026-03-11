# Ralph - Automated Task Runner

Ralph is a bash script that iterates through tasks defined in a JSON file, running Claude on each one sequentially. When a task is marked complete, Ralph kills the session and starts fresh on the next task.

## Quick Start

```bash
# Run with default prd.json
./ralph.sh

# Run with specific task file
./ralph.sh docs/code-review-tasks.json

# Limit iterations
./ralph.sh 5

# Both orders work
./ralph.sh 10 docs/code-review-tasks.json
./ralph.sh docs/code-review-tasks.json 10

# Enable verbose logging (writes to docs/<task>-ralph.log)
./ralph.sh -v docs/code-review-tasks.json
./ralph.sh --verbose docs/code-review-tasks.json 10
```

## How It Works

1. Ralph reads a task JSON file
2. Finds the first task with `passes: false`
3. Spawns Claude with a prompt containing the task details
4. Polls the JSON file every 2 seconds for `passes: true`
5. When detected, kills the session and moves to the next task
6. Repeats until all tasks complete or max iterations reached

```
  Ralph — Task Runner
  ──────────────────────────────────────
  Tasks:    code-review-tasks.json
  Max runs: 20

  [1/20] CR-001 Fix duplicate function
  ────────────────────────────────────────────────────────
    ⠹ Working... 1m 30s
    ✓ Task CR-001 complete
```

## Task JSON Format

### Minimal Example

```json
{
  "project": "My Project",
  "userStories": [
    {
      "id": "TASK-001",
      "phase": 1,
      "title": "Add user authentication",
      "description": "Implement JWT-based auth for the API",
      "acceptanceCriteria": [
        "POST /auth/login returns JWT token",
        "Protected routes require valid token",
        "Tests pass"
      ],
      "passes": false
    }
  ]
}
```

### Full Example with All Options

```json
{
  "project": "My Project",
  "description": "Optional project description",
  "commitPrefix": "feat",
  "workflow": {
    "1-Analyze": "Understand the requirements",
    "2-Plan": "Design the solution",
    "3-Implement": "Write the code",
    "4-Test": "Verify it works",
    "5-Document": "Update docs if needed"
  },
  "userStories": [
    {
      "id": "TASK-001",
      "phase": 1,
      "title": "Add feature X",
      "description": "Detailed description of what to do",
      "acceptanceCriteria": [
        "Criterion 1",
        "Criterion 2"
      ],
      "files": [
        "src/feature.py",
        "tests/test_feature.py"
      ],
      "reviewQuestions": [
        "Is there existing code that does this?",
        "Are there edge cases to consider?"
      ],
      "passes": false
    }
  ]
}
```

## Field Reference

### Project-Level Fields

| Field | Required | Description |
|-------|----------|-------------|
| `project` | Yes | Project name shown in prompt |
| `userStories` | Yes | Array of tasks |
| `description` | No | Project description |
| `commitPrefix` | No | Git commit prefix (default: `feat`) |
| `workflow` | No | Custom workflow steps shown to Claude |

### Task Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique task ID (e.g., `US-001`, `BUG-042`) |
| `title` | Yes | Short task title |
| `description` | Yes | What needs to be done |
| `acceptanceCriteria` | Yes | Array of criteria for completion |
| `passes` | Yes | Set to `false`, Claude sets to `true` when done |
| `phase` | No | Grouping/ordering (shown in output) |
| `files` | No | Array of relevant file paths |
| `reviewQuestions` | No | Hints/questions for Claude to consider (alias: `hints`) |
| `priority` | No | For documentation (not used by script) |

## Progress Tracking

Ralph creates a progress file named after the task file:
- `prd.json` → `prd-progress.txt`
- `code-review-tasks.json` → `code-review-tasks-progress.txt`

Claude is instructed to log summaries to this file before marking tasks complete.

**Note:** The progress file initialization (lines 69-82 in ralph.sh) contains some hardcoded project patterns. For other projects, you may want to customize this section or pre-create the progress file.

## Task Completion Flow

Claude must follow this order:

1. Do the work
2. Commit changes
3. **Write to progress file**
4. **Set `passes: true`** ← This triggers session end

Setting `passes: true` before writing to the progress file will cause the progress entry to be lost (Ralph kills the session on detection).

## Use Cases

### PRD Implementation
```json
{
  "project": "TableScan 2.0",
  "commitPrefix": "feat",
  "userStories": [
    {"id": "US-001", "title": "Add PageClassifier", ...},
    {"id": "US-002", "title": "Add multi-extractor", ...}
  ]
}
```

### Code Review Fixes
```json
{
  "project": "PR Review Fixes",
  "commitPrefix": "fix",
  "workflow": {
    "1-Review": "Check if issue is valid",
    "2-Decide": "FIX or SKIP with justification",
    "3-Implement": "Make changes if needed"
  },
  "userStories": [
    {
      "id": "CR-001",
      "title": "Remove dead code",
      "reviewQuestions": ["Is this actually dead code?"],
      ...
    }
  ]
}
```

### Bug Fixes
```json
{
  "project": "Bug Fixes",
  "commitPrefix": "fix",
  "userStories": [
    {
      "id": "BUG-101",
      "title": "Fix null pointer in parser",
      "files": ["src/parser.py"],
      ...
    }
  ]
}
```

## Configuration

### Command Line Options

| Option | Description |
|--------|-------------|
| `-v`, `--verbose` | Log Claude output to `docs/<task>-ralph.log` |

### Environment

Ralph uses these defaults:
- **Max wait per task**: 30 minutes
- **Poll interval**: 2 seconds
- **Grace period after completion**: 8 seconds
- **Default max iterations**: 20

### Requirements

- `bash`
- `jq` (JSON processor)
- `claude` CLI with `--dangerously-skip-permissions`
- `tput` (optional, for cursor hiding - usually pre-installed)

## Tips

1. **Start small**: Test with 1-2 tasks before running a full batch
2. **Check progress**: Monitor the progress file for task summaries
3. **Resume safely**: Ralph finds the first `passes: false` task, so you can stop and restart
4. **Reset tasks**: Set `passes: false` to re-run a task
5. **Parallel runs**: Don't run multiple Ralph instances on the same task file

## Troubleshooting

**Tasks not being documented in progress file?**
- Claude may be setting `passes: true` before writing to progress
- The JSON workflow should emphasize writing progress BEFORE marking complete

**Claude timing out?**
- Default is 30 min per task
- Complex tasks may need manual intervention
- Check if Claude is stuck on something

**Tasks completing but no commits?**
- Claude may have skipped the commit step
- Check the acceptance criteria includes explicit commit requirement

## Known Limitations

1. **Progress file initialization** has hardcoded project patterns (Django/Celery). Edit lines 74-79 in ralph.sh for other projects, or pre-create your progress file.

2. **Progress files go to docs/** directory. If your project structure differs, update line 59.

3. **No parallel task execution** - tasks run sequentially by design (context isolation).
