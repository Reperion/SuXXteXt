#!/usr/bin/env python3
"""Retry missing channel videos with yt-dlp browser cookies + gentle serial throttle.

Use after a skip-existing batch still has residual HTTP 403 / bot-check failures.

Usage:
  python scripts/retry_missing_with_cookies.py CHANNEL ids.txt [browser]

  CHANNEL  archive name under channels/ (e.g. Drberg)
  ids.txt  one YouTube video id per line
  browser  yt-dlp --cookies-from-browser value (default: chrome)

Example:
  printf '%s\\n' abc123 def456 > /tmp/retry-ids.txt
  python scripts/retry_missing_with_cookies.py Drberg /tmp/retry-ids.txt chrome
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from suxxtext.paths import ensure_channel_dirs, sanitize_filename, transcript_exists_for_id
from suxxtext.whisper_runtime import ModelPool, transcribe_audio
from suxxtext.youtube import extract_video_info, resolve_yt_dlp


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    channel = sys.argv[1]
    ids_path = Path(sys.argv[2])
    browser = sys.argv[3] if len(sys.argv) > 3 else "chrome"

    if not ids_path.is_file():
        print(f"ids file not found: {ids_path}", file=sys.stderr)
        return 2

    ids = [x.strip() for x in ids_path.read_text().split() if x.strip()]
    _, mp3_dir, trans_dir = ensure_channel_dirs(channel)
    print(
        f"retrying {len(ids)} videos channel={channel} "
        f"cookies-from-browser={browser}",
        flush=True,
    )
    print(f"mp3={mp3_dir} trans={trans_dir}", flush=True)

    pool = ModelPool("base", 2)
    ok_n = err_n = skip_n = 0

    for i, vid in enumerate(ids, 1):
        url = f"https://www.youtube.com/watch?v={vid}"
        print(f"\n=== [{i}/{len(ids)}] {vid} ===", flush=True)
        existing = transcript_exists_for_id(trans_dir, vid)
        if existing:
            print(f"skip existing {existing}", flush=True)
            skip_n += 1
            continue

        try:
            info = extract_video_info(url)
        except Exception as e:
            print(f"extract_video_info failed: {e}; bare metadata", flush=True)
            info = {"id": vid, "title": f"video_{vid}", "view_count": None}

        title = info.get("title") or f"video_{vid}"
        view_count = info.get("view_count", 0)
        sanitized = sanitize_filename(title, 50)
        view_str = f"{view_count}views" if view_count is not None else "UnknownViews"
        base = f"{sanitized}_{view_str}_{vid}"
        mp3_path = os.path.join(mp3_dir, f"{base}.m4a")
        txt_path = os.path.join(trans_dir, f"{base}.txt")

        cmd = [
            *resolve_yt_dlp(),
            "--cookies-from-browser",
            browser,
            "-f",
            "bestaudio[ext=m4a]/bestaudio",
            "-o",
            mp3_path,
            "--no-playlist",
            "--sleep-requests",
            "1",
            "--sleep-interval",
            "2",
            "--max-sleep-interval",
            "5",
            url,
        ]
        print(f"download -> {mp3_path}", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            err_tail = (r.stderr or r.stdout or "")[-800:]
            print(f"DOWNLOAD FAIL {vid}: {err_tail}", flush=True)
            err_n += 1
            if os.path.exists(mp3_path):
                try:
                    os.remove(mp3_path)
                except OSError:
                    pass
            time.sleep(6)
            continue

        print(f"transcribe -> {txt_path}", flush=True)
        try:
            with pool.get_model() as model:
                ok, err = transcribe_audio(mp3_path, model, txt_path, lock=None)
        except Exception as e:
            ok, err = False, str(e)
        if ok:
            print(f"OK {vid}", flush=True)
            ok_n += 1
        else:
            print(f"TRANSCRIBE FAIL {vid}: {err}", flush=True)
            err_n += 1
        time.sleep(4)

    print(f"\n=== RETRY SUMMARY ok={ok_n} skip={skip_n} err={err_n} ===", flush=True)
    return 0 if err_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
