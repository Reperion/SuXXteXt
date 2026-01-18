#!/bin/bash
# run.sh - Wrapper script for SuXXTeXt YouTube Transcriber
# Automatically activates the virtual environment and runs the transcriber

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/yt-transcriber-venv"

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Error: Virtual environment not found at $VENV_DIR"
    echo "Please run: python3 -m venv yt-transcriber-venv && source yt-transcriber-venv/bin/activate && pip install yt-dlp openai-whisper colorama"
    exit 1
fi

# Activate virtual environment and run the script
source "$VENV_DIR/bin/activate"
python "$SCRIPT_DIR/transcribe2.py" "$@"
