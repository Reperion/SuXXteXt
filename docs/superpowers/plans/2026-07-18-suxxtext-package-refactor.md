# SuXXTeXt Package Refactor Implementation Plan

> **For agentic workers:** Implement task-by-task. Interactive CLI must keep working (`python transcribe2.py` / `./run.sh` with menu + paste channel URL).

**Goal:** Factor SuXXTeXt into a shared `suxxtext` library with one CLI surface, zero duplicated helpers, and the same interactive human workflow.

**Architecture:** Core logic lives in `suxxtext/` (paths, YouTube I/O, Whisper runtime, captions, jobs). `transcribe2.py` and `python -m suxxtext` are thin entrypoints. `yt_tldw.py` / `fetch_captions_batch.py` call the library. Archives stay under `channels/<handle>/`.

**Tech Stack:** Python 3.8+, yt-dlp, faster-whisper, youtube-transcript-api, colorama, pytest (dev).

## Global Constraints

- Interactive menu (options 0–4) and CLI flags `--mode single|batch|json|stats` remain supported.
- Channel folders prefer `@handle`; reuse existing archives; never invent parallel trees for the same channel.
- Transcript filenames include 11-char video id for skip detection.
- Whisper: CUDA float16 when available, else CPU int8; batch default is **1 model instance** + concurrent downloads (safer GPU).
- No secrets in repo; `channels/` stays gitignored.
- Prefer rename to `.bak*` over `rm -rf`.

## Target layout

```
suxxtext/
  __init__.py
  __main__.py          # python -m suxxtext
  paths.py
  youtube.py
  whisper_runtime.py
  captions.py
  jobs.py
  cli.py
transcribe2.py         # thin: from suxxtext.cli import main
yt_tldw.py             # uses suxxtext.*
fetch_captions_batch.py
yt_channel_analyzer.py # import sanitize/resolve from suxxtext.paths
tests/
  test_paths.py
  test_captions_format.py
  test_smoke_imports.py
run.sh                 # python -m suxxtext "$@"
```

## Tasks

### Task 1: `suxxtext.paths` + unit tests
Channel handle extraction, resolve_channel_folder, sanitize_filename, ensure_channel_dirs, video_id_in_transcripts.

### Task 2: `suxxtext.youtube` + `suxxtext.whisper_runtime` + `suxxtext.captions`
yt-dlp resolution, download audio/video, list channel videos, extract info; ModelPool; caption fetch.

### Task 3: `suxxtext.jobs`
process_single_video, process_channel_videos, download_channel_history_json — behavior-compatible with prior CLI.

### Task 4: `suxxtext.cli` + thin wrappers
Interactive menu + argparse; `transcribe2.py` re-exports for backward compat (including `sanitize_filename` for analyzer).

### Task 5: Point TL;DW and caption batch at library; fix analyzer import.

### Task 6: Tests + live verification (single, batch skip, tldw, smoke).

### Task 7: Docs + commit.

## Success criteria

- `./run.sh` / `python transcribe2.py` opens menu.
- `python -m suxxtext --mode single -u URL` works.
- Batch skip-by-id works.
- `python yt_tldw.py --url ID` captions work.
- `pytest tests/ -q` passes (no network required for unit tests).
- Live smoke: single skip or short single + batch limit 2 re-run skip.
