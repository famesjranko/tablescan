#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop for TableScan 2.0
# Usage: ./ralph.sh [max_iterations]

set -e

# Parse arguments
MAX_ITERATIONS=20

if [[ "$1" =~ ^[0-9]+$ ]]; then
  MAX_ITERATIONS="$1"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRD_FILE="$SCRIPT_DIR/docs/prd.json"
PROGRESS_FILE="$SCRIPT_DIR/docs/progress.txt"
PRD_MD="$SCRIPT_DIR/docs/PRD-TableScan-2.0.md"

# Check required files exist
if [ ! -f "$PRD_FILE" ]; then
  echo "Error: prd.json not found at $PRD_FILE"
  exit 1
fi

# Initialize progress file if needed
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# TableScan 2.0 - Ralph Progress Log" > "$PROGRESS_FILE"
  echo "Started: $(date)" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "## Codebase Patterns" >> "$PROGRESS_FILE"
  echo "- Django 3.2 with DRF" >> "$PROGRESS_FILE"
  echo "- Extraction pipeline in api/scripts/" >> "$PROGRESS_FILE"
  echo "- Models in api/models.py (Report, Extracted)" >> "$PROGRESS_FILE"
  echo "- Async via Celery (api/tasks.py)" >> "$PROGRESS_FILE"
  echo "- Current extraction: YOLO -> Camelot" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
  echo "---" >> "$PROGRESS_FILE"
  echo "" >> "$PROGRESS_FILE"
fi

echo "Starting Ralph - Max iterations: $MAX_ITERATIONS"
echo "PRD: $PRD_FILE"
echo ""

for i in $(seq 1 $MAX_ITERATIONS); do
  echo ""
  echo "==============================================================="
  echo "  Ralph Iteration $i of $MAX_ITERATIONS"
  echo "==============================================================="

  # Find next incomplete story
  NEXT_STORY=$(jq -r '.userStories[] | select(.passes == false) | .id' "$PRD_FILE" | head -1)

  if [ -z "$NEXT_STORY" ]; then
    echo ""
    echo "========================================="
    echo "  Ralph completed all user stories!"
    echo "  Finished at iteration $i of $MAX_ITERATIONS"
    echo "========================================="
    exit 0
  fi

  STORY_TITLE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .title" "$PRD_FILE")
  STORY_PHASE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .phase" "$PRD_FILE")
  STORY_DESC=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .description" "$PRD_FILE")
  STORY_AC=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .acceptanceCriteria | join(\"\n- \")" "$PRD_FILE")

  echo ">>> Phase $STORY_PHASE: $NEXT_STORY - $STORY_TITLE"

  # Build the prompt for this specific story
  TASK_PROMPT="You are implementing a single user story for TableScan 2.0 - PDF table extraction modernization.

## Your Task: $NEXT_STORY - $STORY_TITLE
Phase: $STORY_PHASE

### Description
$STORY_DESC

### Acceptance Criteria
- $STORY_AC

## Context Files
- Read docs/prd.json for the full PRD structure
- Read docs/progress.txt for codebase patterns and context from previous work
- Read docs/PRD-TableScan-2.0.md for detailed specifications
- Read CLAUDE.md for project conventions

## Instructions
1. Implement ONLY story $NEXT_STORY (not any other stories)
2. Follow existing code patterns in the codebase
3. Test your implementation works
4. Commit with message: feat($NEXT_STORY): $STORY_TITLE
5. Update docs/prd.json to set passes: true for $NEXT_STORY
6. Append a brief summary of what you did to docs/progress.txt

## Quality Requirements
- Follow Django/DRF conventions
- No breaking changes to existing API
- Add type hints where appropriate
- Keep changes minimal and focused

IMPORTANT: When you complete the story and update prd.json with passes: true, the script will detect this and terminate your session. This is expected - a fresh agent will start on the next story.

DO NOT work on any other stories. Focus only on $NEXT_STORY."

  # Run claude in background
  echo "$TASK_PROMPT" | claude --dangerously-skip-permissions --print 2>&1 &
  CLAUDE_PID=$!

  echo ">>> Claude started (PID: $CLAUDE_PID). Watching for completion..."

  # Watch for completion: poll prd.json for passes: true
  MAX_WAIT=1800  # 30 min max per story
  POLL_INTERVAL=5
  WAITED=0

  while [ $WAITED -lt $MAX_WAIT ]; do
    sleep $POLL_INTERVAL
    WAITED=$((WAITED + POLL_INTERVAL))

    # Check if story is now complete
    IS_COMPLETE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .passes" "$PRD_FILE" 2>/dev/null || echo "false")

    if [ "$IS_COMPLETE" == "true" ]; then
      echo ""
      echo ">>> Story $NEXT_STORY marked complete in prd.json!"

      # Give agent a moment to finish up (commit, etc)
      sleep 3

      # Kill claude if still running
      if kill -0 $CLAUDE_PID 2>/dev/null; then
        echo ">>> Stopping claude (PID: $CLAUDE_PID)..."
        kill $CLAUDE_PID 2>/dev/null || true
        wait $CLAUDE_PID 2>/dev/null || true
      fi

      echo ">>> Starting fresh context for next story..."
      break
    fi

    # Check if claude died on its own
    if ! kill -0 $CLAUDE_PID 2>/dev/null; then
      echo ""
      echo ">>> Claude exited. Checking if story completed..."

      IS_COMPLETE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .passes" "$PRD_FILE" 2>/dev/null || echo "false")
      if [ "$IS_COMPLETE" == "true" ]; then
        echo ">>> Story $NEXT_STORY completed!"
      else
        echo ">>> Story $NEXT_STORY still incomplete. Will retry next iteration."
      fi
      break
    fi

    # Progress indicator
    if [ $((WAITED % 30)) -eq 0 ]; then
      echo "    ... still working ($WAITED seconds)"
    fi
  done

  # Timeout reached
  if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo ">>> Timeout ($MAX_WAIT seconds). Stopping claude..."
    kill $CLAUDE_PID 2>/dev/null || true
    wait $CLAUDE_PID 2>/dev/null || true
    echo ">>> Will retry $NEXT_STORY next iteration."
  fi

  sleep 1
done

echo ""
echo "Ralph reached max iterations ($MAX_ITERATIONS)."
echo "Check docs/prd.json and docs/progress.txt for status."

# Show summary
COMPLETED=$(jq '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
TOTAL=$(jq '.userStories | length' "$PRD_FILE")
echo "Progress: $COMPLETED / $TOTAL stories completed"

exit 1
