#!/bin/bash
# Ralph Wiggum - Long-running AI agent loop for TableScan 2.0
# Usage: ./ralph.sh [options] [max_iterations] [task_file]
#
# Options:
#   -v, --verbose    Log Claude output to docs/<task>-ralph.log
#
# Examples:
#   ./ralph.sh                              # Run prd.json with 20 iterations
#   ./ralph.sh 10                           # Run prd.json with 10 iterations
#   ./ralph.sh 20 docs/code-review-tasks.json  # Run code review tasks
#   ./ralph.sh -v docs/code-review-tasks.json  # Run with logging enabled

set -e

# Hide cursor during execution, restore on exit
tput civis 2>/dev/null || true
trap 'tput cnorm 2>/dev/null || true' EXIT

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
ORANGE='\033[38;5;208m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Parse arguments
MAX_ITERATIONS=20
TASK_FILE=""
VERBOSE=false

for arg in "$@"; do
  if [[ "$arg" == "--verbose" || "$arg" == "-v" ]]; then
    VERBOSE=true
  elif [[ "$arg" =~ ^[0-9]+$ ]]; then
    MAX_ITERATIONS="$arg"
  elif [[ "$arg" != -* ]]; then
    TASK_FILE="$arg"
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default to prd.json if no task file specified
if [[ -z "$TASK_FILE" ]]; then
  PRD_FILE="$SCRIPT_DIR/docs/prd.json"
elif [[ "$TASK_FILE" = /* ]]; then
  # Absolute path
  PRD_FILE="$TASK_FILE"
else
  # Relative path
  PRD_FILE="$SCRIPT_DIR/$TASK_FILE"
fi

# Derive progress file from task file name
TASK_BASENAME=$(basename "$PRD_FILE" .json)
PROGRESS_FILE="$SCRIPT_DIR/docs/${TASK_BASENAME}-progress.txt"
LOG_FILE="$SCRIPT_DIR/docs/${TASK_BASENAME}-ralph.log"
PRD_MD="$SCRIPT_DIR/docs/PRD-TableScan-2.0.md"

# Clear log file if verbose
if [ "$VERBOSE" = true ]; then
  echo "# Ralph Log - $TASK_BASENAME" > "$LOG_FILE"
  echo "Started: $(date)" >> "$LOG_FILE"
  echo "" >> "$LOG_FILE"
fi

# Check required files exist
if [ ! -f "$PRD_FILE" ]; then
  echo -e "${RED}Error:${NC} Task file not found: $PRD_FILE"
  exit 1
fi

# Initialize progress file if needed
if [ ! -f "$PROGRESS_FILE" ]; then
  echo "# Ralph Progress Log - $TASK_BASENAME" > "$PROGRESS_FILE"
  echo "Task File: $PRD_FILE" >> "$PROGRESS_FILE"
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

echo ""
echo -e "  ${CYAN}${BOLD}Ralph${NC} ${DIM}— Task Runner${NC}"
echo -e "  ${DIM}──────────────────────────────────────${NC}"
echo -e "  ${DIM}Tasks:${NC}    ${WHITE}$(basename "$PRD_FILE")${NC}"
echo -e "  ${DIM}Max runs:${NC} ${WHITE}$MAX_ITERATIONS${NC}"
if [ "$VERBOSE" = true ]; then
  echo -e "  ${DIM}Log:${NC}      ${WHITE}$(basename "$LOG_FILE")${NC}"
fi
echo ""

for i in $(seq 1 $MAX_ITERATIONS); do
  # Find next incomplete story
  NEXT_STORY=$(jq -r '.userStories[] | select(.passes == false) | .id' "$PRD_FILE" | head -1)

  if [ -z "$NEXT_STORY" ]; then
    echo ""
    echo -e "  ${GREEN}✓ All tasks complete!${NC}"
    echo ""
    exit 0
  fi

  STORY_TITLE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .title" "$PRD_FILE")
  STORY_PHASE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .phase" "$PRD_FILE")
  STORY_DESC=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .description" "$PRD_FILE")
  STORY_AC=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .acceptanceCriteria | join(\"\n- \")" "$PRD_FILE")

  echo ""
  echo -e "  ${DIM}[$i/$MAX_ITERATIONS]${NC} ${CYAN}${BOLD}$NEXT_STORY${NC} ${WHITE}$STORY_TITLE${NC}"
  echo -e "  ${DIM}────────────────────────────────────────────────────────${NC}"

  # Get optional task-specific fields
  STORY_FILES=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .files // [] | join(\", \")" "$PRD_FILE")
  STORY_HINTS=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .reviewQuestions // .hints // [] | join(\"\n- \")" "$PRD_FILE")

  # Get project-level config from JSON (allows customization per task file)
  PROJECT_NAME=$(jq -r '.project // "Project"' "$PRD_FILE")
  COMMIT_PREFIX=$(jq -r '.commitPrefix // "feat"' "$PRD_FILE")

  # Check for custom workflow/instructions in JSON
  CUSTOM_WORKFLOW=$(jq -r '.workflow | to_entries | map("- " + .key + ": " + .value) | join("\n")' "$PRD_FILE" 2>/dev/null || echo "")
  CUSTOM_INSTRUCTIONS=$(jq -r '.instructions // empty' "$PRD_FILE")

  # Build the prompt
  TASK_PROMPT="You are working on a task for $PROJECT_NAME.

## Task: $NEXT_STORY - $STORY_TITLE
Phase: $STORY_PHASE

### Description
$STORY_DESC"

  # Add files if specified
  if [ -n "$STORY_FILES" ]; then
    TASK_PROMPT="$TASK_PROMPT

### Relevant Files
$STORY_FILES"
  fi

  # Add hints/review questions if present
  if [ -n "$STORY_HINTS" ]; then
    TASK_PROMPT="$TASK_PROMPT

### Consider
- $STORY_HINTS"
  fi

  TASK_PROMPT="$TASK_PROMPT

### Acceptance Criteria
- $STORY_AC

## Context
- Task file: $PRD_FILE
- Progress log: $PROGRESS_FILE
- Read CLAUDE.md for project conventions"

  # Add custom workflow if defined in JSON, otherwise use default
  if [ -n "$CUSTOM_WORKFLOW" ] && [ "$CUSTOM_WORKFLOW" != "null" ]; then
    TASK_PROMPT="$TASK_PROMPT

## Workflow
$CUSTOM_WORKFLOW"
  fi

  TASK_PROMPT="$TASK_PROMPT

## Required Steps
1. Implement ONLY task $NEXT_STORY
2. Follow existing code patterns
3. Test your changes work
4. Commit: $COMMIT_PREFIX($NEXT_STORY): $STORY_TITLE
5. Log summary to $PROGRESS_FILE
6. LAST: Set passes: true in $PRD_FILE (triggers session end)

IMPORTANT: Setting passes:true ends this session. Complete all steps BEFORE updating passes.

Focus only on $NEXT_STORY."

  # Run claude in background
  if [ "$VERBOSE" = true ]; then
    echo -e "\n--- $NEXT_STORY: $STORY_TITLE ---\n" >> "$LOG_FILE"
    echo "$TASK_PROMPT" | claude --dangerously-skip-permissions --print >> "$LOG_FILE" 2>&1 &
  else
    echo "$TASK_PROMPT" | claude --dangerously-skip-permissions --print > /dev/null 2>&1 &
  fi
  CLAUDE_PID=$!

  # Braille spinner characters
  SPINNER=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  SPIN_IDX=0

  # Format seconds as human readable
  format_time() {
    local secs=$1
    if [ $secs -lt 60 ]; then
      echo "${secs}s"
    else
      local mins=$((secs / 60))
      local remaining=$((secs % 60))
      echo "${mins}m ${remaining}s"
    fi
  }

  printf "    ${DIM}${SPINNER[0]} Working...${NC}\\r"

  # Watch for completion
  MAX_WAIT=1800  # 30 min max per story
  SPIN_INTERVAL=0.15  # Fast spinner
  CHECK_INTERVAL=2    # Check completion every 2s
  WAITED=0
  SPIN_COUNT=0
  CHECKS_PER_INTERVAL=$((CHECK_INTERVAL * 1000 / 150))  # ~13 spins per check

  while [ $WAITED -lt $MAX_WAIT ]; do
    sleep $SPIN_INTERVAL
    SPIN_COUNT=$((SPIN_COUNT + 1))

    # Update spinner every iteration (fast)
    SPIN_IDX=$(( (SPIN_IDX + 1) % ${#SPINNER[@]} ))
    printf "    ${ORANGE}${SPINNER[$SPIN_IDX]}${NC} ${DIM}Working...${NC} ${CYAN}$(format_time $WAITED)${NC}   \\r"

    # Only check completion every CHECK_INTERVAL seconds
    if [ $((SPIN_COUNT % CHECKS_PER_INTERVAL)) -ne 0 ]; then
      continue
    fi

    WAITED=$((WAITED + CHECK_INTERVAL))

    # Check if story is now complete
    IS_COMPLETE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .passes" "$PRD_FILE" 2>/dev/null || echo "false")

    if [ "$IS_COMPLETE" == "true" ]; then
      printf "\\033[2K\\r"  # Clear spinner line
      echo -e "    ${GREEN}✓${NC} ${BOLD}Task $NEXT_STORY complete${NC}"

      # Give agent time to finish up (progress file write, commit, etc)
      sleep 8

      # Kill claude if still running
      if kill -0 $CLAUDE_PID 2>/dev/null; then
        echo -e "    ${DIM}Stopping session...${NC}"
        kill $CLAUDE_PID 2>/dev/null || true
        wait $CLAUDE_PID 2>/dev/null || true
      fi

      echo ""
      break
    fi

    # Check if claude died on its own
    if ! kill -0 $CLAUDE_PID 2>/dev/null; then
      printf "\\033[2K\\r"  # Clear spinner line
      echo -e "    ${YELLOW}⚠${NC}  Claude exited. Checking..."

      IS_COMPLETE=$(jq -r ".userStories[] | select(.id == \"$NEXT_STORY\") | .passes" "$PRD_FILE" 2>/dev/null || echo "false")
      if [ "$IS_COMPLETE" == "true" ]; then
        echo -e "    ${GREEN}✓${NC} Task $NEXT_STORY completed"
      else
        echo -e "    ${RED}✗${NC} Task $NEXT_STORY incomplete. ${DIM}Retrying next iteration.${NC}"
      fi
      break
    fi
  done

  # Timeout reached
  if [ $WAITED -ge $MAX_WAIT ]; then
    printf "\\033[2K\\r"  # Clear spinner line
    echo -e "    ${RED}⏱${NC}  Timeout ($(format_time $MAX_WAIT)). Stopping..."
    kill $CLAUDE_PID 2>/dev/null || true
    wait $CLAUDE_PID 2>/dev/null || true
    echo -e "    ${DIM}Will retry $NEXT_STORY next iteration.${NC}"
  fi

  sleep 1
done

# Show summary
COMPLETED=$(jq '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
TOTAL=$(jq '.userStories | length' "$PRD_FILE")
REMAINING=$((TOTAL - COMPLETED))

echo ""
echo -e "  ${DIM}────────────────────────────────────────────────────────${NC}"
echo -e "  ${YELLOW}Summary:${NC} ${GREEN}$COMPLETED${NC}/${WHITE}$TOTAL${NC} complete ${DIM}($REMAINING remaining)${NC}"
echo -e "  ${DIM}Max iterations reached${NC}"
echo ""

exit 1
