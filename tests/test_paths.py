"""Unit tests for suxxtext.paths (no network)."""

import os
import sys

# project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from suxxtext.paths import (
    alnum_related,
    channel_handle_from_url,
    resolve_channel_folder,
    sanitize_filename,
    transcript_exists_for_id,
)


def test_sanitize_filename():
    assert " " not in sanitize_filename("Hello World!")
    assert len(sanitize_filename("x" * 100, 50)) <= 53  # 50 + "..."


def test_channel_handle_from_url():
    assert channel_handle_from_url("https://www.youtube.com/@Drberg/videos") == "Drberg"
    assert channel_handle_from_url("https://www.youtube.com/@HubermanLabClips") == "HubermanLabClips"


def test_resolve_with_handle():
    folder = resolve_channel_folder(
        info={
            "channel": "Dr. Eric Berg DC",
            "uploader_url": "https://www.youtube.com/@Drberg",
        },
        channels_root=os.path.join(ROOT, "channels"),
    )
    assert folder == "Drberg"


def test_resolve_huberman():
    folder = resolve_channel_folder(
        info={
            "channel": "Huberman Lab Clips",
            "uploader_url": "https://www.youtube.com/@HubermanLabClips",
        },
        channels_root=os.path.join(ROOT, "channels"),
    )
    assert folder == "HubermanLabClips"


def test_alnum_related_drberg():
    assert alnum_related("drberg", "drericbergdc")


def test_transcript_exists(tmp_path):
    (tmp_path / "foo_AbCdEfGhIjK.txt").write_text("hi")
    assert transcript_exists_for_id(str(tmp_path), "AbCdEfGhIjK")
    assert transcript_exists_for_id(str(tmp_path), "nope1234567") is None
