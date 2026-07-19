"""Captions-first archive path unit tests (no network)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from suxxtext.jobs import (
    DEFAULT_MODEL_INSTANCES,
    DEFAULT_WORKERS,
    normalize_channel_url,
    try_captions_to_file,
    process_video_task,
)


def test_normalize_channel_url():
    assert normalize_channel_url("@Drberg") == "https://www.youtube.com/@Drberg/videos"
    assert normalize_channel_url("Drberg") == "https://www.youtube.com/@Drberg/videos"
    assert (
        normalize_channel_url("https://www.youtube.com/@Drberg/videos")
        == "https://www.youtube.com/@Drberg/videos"
    )


def test_defaults_gentle():
    assert DEFAULT_WORKERS == 4
    assert DEFAULT_MODEL_INSTANCES == 2


def test_try_captions_success(tmp_path):
    txt = tmp_path / "out.txt"
    fake = {
        "success": True,
        "full_text": "x" * 80,
        "language": "en",
        "segment_count": 1,
    }
    with patch("suxxtext.jobs.fetch_captions", return_value=fake):
        ok, detail = try_captions_to_file("abcdefghijk", str(txt))
    assert ok
    assert "en" in detail
    assert txt.read_text().strip() == "x" * 80


def test_try_captions_too_short(tmp_path):
    txt = tmp_path / "out.txt"
    with patch(
        "suxxtext.jobs.fetch_captions",
        return_value={"success": True, "full_text": "hi", "language": "en"},
    ):
        ok, detail = try_captions_to_file("abcdefghijk", str(txt))
    assert not ok
    assert "short" in detail
    assert not txt.exists()


def test_process_video_task_captions_skips_whisper(tmp_path):
    mp3_dir = tmp_path / "mp3"
    trans_dir = tmp_path / "trans"
    mp3_dir.mkdir()
    trans_dir.mkdir()
    log = MagicMock()
    video = {"id": "abcdefghijk", "title": "Test Video", "view_count": 100}
    fake = {
        "success": True,
        "full_text": "hello world " * 20,
        "language": "en",
    }
    with patch("suxxtext.jobs.fetch_captions", return_value=fake):
        with patch("suxxtext.jobs.download_audio") as dl:
            status, msg = process_video_task(
                video,
                str(mp3_dir),
                str(trans_dir),
                log,
                model_pool=None,
                prefer_captions=True,
                whisper_fallback=True,
            )
            dl.assert_not_called()
    assert status == "captions"
    files = list(trans_dir.glob("*.txt"))
    assert len(files) == 1
    assert "abcdefghijk" in files[0].name


def test_process_video_task_whisper_fallback(tmp_path):
    mp3_dir = tmp_path / "mp3"
    trans_dir = tmp_path / "trans"
    mp3_dir.mkdir()
    trans_dir.mkdir()
    log = MagicMock()
    video = {"id": "xyzXYZ12345", "title": "No Caps", "view_count": 1}
    pool = MagicMock()
    pool.get_model.return_value.__enter__ = MagicMock(return_value="model")
    pool.get_model.return_value.__exit__ = MagicMock(return_value=False)

    with patch("suxxtext.jobs.fetch_captions", return_value={"error": "none"}):
        with patch("suxxtext.jobs.download_audio", return_value=(True, None)) as dl:
            with patch("suxxtext.jobs.transcribe_audio", return_value=(True, None)) as tr:
                status, msg = process_video_task(
                    video,
                    str(mp3_dir),
                    str(trans_dir),
                    log,
                    model_pool=pool,
                    prefer_captions=True,
                    whisper_fallback=True,
                )
                dl.assert_called_once()
                tr.assert_called_once()
    assert status == "whisper"
