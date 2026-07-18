"""Unit tests for video id extraction."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from suxxtext.youtube import extract_video_id, normalize_channel_url, resolve_yt_dlp


def test_extract_video_id():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_normalize_channel_url():
    assert normalize_channel_url("@Drberg").endswith("@Drberg/videos")
    assert "youtube.com" in normalize_channel_url("https://www.youtube.com/@x/videos")


def test_resolve_yt_dlp_nonempty():
    assert resolve_yt_dlp()
