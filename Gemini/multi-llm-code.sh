#!/bin/bash
# multi-llm-code.sh - Single master script for Gemini (planning) → Claude Code (execution) workflow
# Requirements: gemini CLI and claude CLI installed and authenticated

set -e  # Exit on any error

# Configurable paths (adjust if needed)
PLAN_FILE="PLAN.md"
GEMINI_PROMPT_FILE="tools/PROMPT_GEMINI_PLANNER.txt"
CLAUDE_PROMPT_FILE="tools/PROMPT_CLAUDE_EXECUTOR.txt"

# Colors for nice output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN} Multi-LLM Coding Workflow (Gemini → Claude)${NC}"
echo -e "${GREEN}=======================================${NC}"
echo

# Ensure prompt files exist
if [ ! -f "$GEMINI_PROMPT_FILE" ]; then
    echo -e "${RED}Error: Gemini planner prompt not found at $GEMINI_PROMPT_FILE${NC}"
    echo "Run the previous setup to create the prompt files first."
    exit 1
fi
if [ ! -f "$CLAUDE_PROMPT_FILE" ]; then
    echo -e "${RED}Error: Claude executor prompt not found at $CLAUDE_PROMPT_FILE${NC}"
    exit 1
fi

while true; do
    echo -e "${YELLOW}Current status:${NC}"
    if [ -f "$PLAN_FILE" ]; then
        echo "   • $PLAN_FILE exists (last modified: $(date -r "$PLAN_FILE" "+%H:%M:%S"))"
    else
        echo "   • $PLAN_FILE does not exist yet"
    fi
    echo
    echo "Choose phase:"
    echo "   1) Phase 1–3: Explore & Plan with Gemini"
    echo "   2) Phase 4: Execute Plan with Claude Code"
    echo "   3) View current PLAN.md"
    echo "   4) Delete PLAN.md (start fresh)"
    echo "   5) Quit"
    echo
    read -p "Enter choice (1-5): " choice
    echo

    case $choice in
        1)
            echo -e "${GREEN}Starting Gemini CLI — Exploration & Planning Mode${NC}"
            echo "Tip: Discuss freely. When ready, type:"
            echo "   COMMIT TO PLAN"
            echo "Then copy the structured plan and save it as $PLAN_FILE"
            echo "Press Enter to continue..."
            read
            gemini --system-prompt "$(cat "$GEMINI_PROMPT_FILE")"
            echo
            echo -e "${YELLOW}Gemini session ended. If you generated a plan, save it now as $PLAN_FILE${NC}"
            ;;

        2)
            if [ ! -f "$PLAN_FILE" ]; then
                echo -e "${RED}Error: $PLAN_FILE not found!${NC}"
                echo "You must first create a plan using option 1."
                echo
                continue
            fi

            echo -e "${GREEN}Handing off to Claude Code — Strict Execution Mode${NC}"
            echo "Plan loaded: $PLAN_FILE"
            echo "Claude will touch ONLY files listed in the plan."
            echo "Press Enter to begin execution..."
            read

            claude --system-prompt "$(cat "$CLAUDE_PROMPT_FILE")" <<EOF
You are now in deterministic execution mode.

Implement this plan EXACTLY as written.
- Touch ONLY the files listed in the "Files" section
- Do not redesign, add features, or optimize beyond instructions
- Stop and ask if anything is ambiguous

--- BEGIN PLAN ---

$(cat "$PLAN_FILE")

--- END PLAN ---

Begin implementation now.
EOF
            echo
            echo -e "${GREEN}Claude session ended.${NC}"
            ;;

        3)
            if [ -f "$PLAN_FILE" ]; then
                echo -e "${GREEN}=== Current $PLAN_FILE ===${NC}"
                cat "$PLAN_FILE"
                echo -e "${GREEN}=== End of Plan ===${NC}"
            else
                echo -e "${RED}No $PLAN_FILE found yet.${NC}"
            fi
            echo
            ;;

        4)
            read -p "Are you sure you want to delete $PLAN_FILE? (y/N): " confirm
            if [[ $confirm =~ ^[Yy]$ ]]; then
                rm -f "$PLAN_FILE"
                echo "$PLAN_FILE deleted."
            fi
            echo
            ;;

        5)
            echo "Goodbye!"
            exit 0
            ;;

        *)
            echo "Invalid choice. Please enter 1-5."
            echo
            ;;
    esac
done