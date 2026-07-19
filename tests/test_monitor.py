"""Monitor dashboard unit tests (no live batch required)."""

from __future__ import annotations

from pathlib import Path

from suxxtext.monitor import _bar, _parse_log, collect_snapshot, render_snapshot


def test_bar():
    s = _bar(25, 100, width=10)
    assert "25.0%" in s
    assert "#" in s


def test_parse_log_counts():
    text = """
START limit=1024 cookies=chrome workers=2
[1/5045] Checking video: Foo (abcdefghijk)
  - Transcription already exists
--- Submitting 512 Whisper tasks (up to 2 workers)... ---
[hutwzLgjU4U] Downloading audio...
[hutwzLgjU4U] Transcribing audio (Whisper)...
[hutwzLgjU4U] Whisper saved to channels/Drberg/transcriptions/x_hutwzLgjU4U.txt
[t91rTD0k0SA] Downloading audio...
Download error for Bad (badidBAD12): Sign in to confirm you're not a bot
"""
    p = _parse_log(text)
    assert p["submitted"] == 512
    assert p["whisper_ok"] == 1
    assert p["download_err"] == 1
    assert "hutwzLgjU4U" in p["recent_ok"]
    assert "t91rTD0k0SA" in p["downloading"]


def test_collect_and_render(tmp_path, monkeypatch):
    ch = tmp_path / "channels" / "TestCh"
    (ch / "logs").mkdir(parents=True)
    (ch / "transcriptions").mkdir()
    (ch / "mp3").mkdir()
    (ch / "summaries").mkdir()
    blog = ch / "logs" / "batch.log"
    blog.write_text(
        "START test\n--- Submitting 10 Whisper tasks (up to 2 workers)... ---\n"
        "[abcABCabcAB] Whisper saved to x_abcABCabcAB.txt\n",
        encoding="utf-8",
    )
    (ch / "logs" / "latest-batch.pidpath").write_text(str(blog), encoding="utf-8")
    (ch / "logs" / "latest-batch.pid").write_text("1\n", encoding="utf-8")
    (ch / "transcriptions" / "Hello_World_100views_abcABCabcAB.txt").write_text(
        "hi\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    snap = collect_snapshot("TestCh", channels_root="channels")
    assert snap["n_txt"] == 1
    assert snap["parsed"]["whisper_ok"] == 1
    out = render_snapshot(snap)
    assert "SuXXTeXt monitor" in out
    assert "TestCh" in out
