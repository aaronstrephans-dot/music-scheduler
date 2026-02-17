#!/bin/bash
set -euo pipefail

# Only run in Claude Code remote (web) sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

pip install -r "$CLAUDE_PROJECT_DIR/requirements.txt" --quiet --break-system-packages --ignore-installed
