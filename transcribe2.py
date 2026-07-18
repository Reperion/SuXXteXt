#!/usr/bin/env python3
"""
Backward-compatible entrypoint for SuXXTeXt.

Prefer:  python -m suxxtext
Still works:  python transcribe2.py   |  ./run.sh
"""

from suxxtext.cli import main
from suxxtext.jobs import (
    download_channel_history_json,
    process_channel_videos,
    process_single_video,
)
from suxxtext.paths import (
    CHANNELS_ROOT,
    ensure_channel_dirs,
    resolve_channel_folder,
    sanitize_filename,
)
from suxxtext.whisper_runtime import (
    ModelPool,
    get_whisper_runtime,
    load_whisper_model,
    transcribe_audio,
)
from suxxtext.youtube import download_audio, get_channel_videos

# Re-exports used by yt_channel_analyzer and older scripts
__all__ = [
    "CHANNELS_ROOT",
    "ModelPool",
    "download_audio",
    "download_channel_history_json",
    "ensure_channel_dirs",
    "get_channel_videos",
    "get_whisper_runtime",
    "load_whisper_model",
    "main",
    "process_channel_videos",
    "process_single_video",
    "resolve_channel_folder",
    "sanitize_filename",
    "transcribe_audio",
]

if __name__ == "__main__":
    raise SystemExit(main())
