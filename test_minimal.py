#!/usr/bin/env python3
"""Smoke checks for SuXXTeXt package imports and pure helpers (no network)."""

import sys


def main():
    errors = []
    try:
        import yt_dlp  # noqa: F401

        print("ok yt-dlp import")
    except Exception as e:
        errors.append(f"yt-dlp: {e}")

    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: F401

        print("ok youtube-transcript-api import")
    except Exception as e:
        errors.append(f"youtube-transcript-api: {e}")

    try:
        from faster_whisper import WhisperModel  # noqa: F401

        print("ok faster-whisper import")
    except Exception as e:
        errors.append(f"faster-whisper: {e}")

    try:
        from suxxtext.paths import channel_handle_from_url, resolve_channel_folder
        from suxxtext.whisper_runtime import get_whisper_runtime
        from suxxtext.youtube import extract_video_id, resolve_yt_dlp
        from suxxtext.cli import build_parser

        assert channel_handle_from_url("https://www.youtube.com/@Drberg/videos") == "Drberg"
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert resolve_yt_dlp()
        assert build_parser()
        dev, ct = get_whisper_runtime()
        print(f"ok suxxtext package (whisper runtime: {dev}/{ct})")
        print(f"ok resolve_channel_folder sample: {resolve_channel_folder(channel_url='https://www.youtube.com/@Drberg/videos')}")
    except Exception as e:
        errors.append(f"suxxtext: {e}")

    try:
        import transcribe2

        assert hasattr(transcribe2, "sanitize_filename")
        assert hasattr(transcribe2, "main")
        print("ok transcribe2 re-exports")
    except Exception as e:
        errors.append(f"transcribe2: {e}")

    if errors:
        print("FAILED:")
        for e in errors:
            print(" -", e)
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
