#!/bin/bash
# run.sh - SuXXTeXt launcher (venv + CLI)
#   ./run.sh              interactive (auto-tmux if no TTY)
#   ./run.sh --tmux       force persistent tmux session
#   ./run.sh --mode ...   non-interactive modes
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/suxxtext-venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Please run: python3 -m venv suxxtext-venv && source suxxtext-venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR"
exec python -m suxxtext "$@"
