#!/usr/bin/env python3
"""Smoke checks for SuXXTeXt imports and helpers (no network, no audio)."""
import sys


def main():
    errors = []

    try:
        import yt_dlp  # noqa: F401
        print(f"ok yt-dlp import")
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
        import transcribe2 as t
        assert t.channel_handle_from_url("https://www.youtube.com/@Drberg/videos") == "Drberg"
        dev, ct = t.get_whisper_runtime()
        print(f"ok transcribe2 helpers (whisper runtime: {dev}/{ct})")
    except Exception as e:
        errors.append(f"transcribe2: {e}")

    try:
        import yt_tldw as tldw
        assert tldw.extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert tldw.resolve_yt_dlp()
        print(f"ok yt_tldw helpers (yt-dlp: {tldw.resolve_yt_dlp()})")
    except Exception as e:
        errors.append(f"yt_tldw: {e}")

    if errors:
        print("FAILED:")
        for e in errors:
            print(" -", e)
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
