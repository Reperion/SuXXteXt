#!/usr/bin/env python3
"""
fetch_captions_batch.py — Lightweight YouTube caption batch fetcher.

Fetches captions via youtube-transcript-api, falls back to yt-dlp+Whisper
if unavailable.  Uses Chrome cookies for authenticated access where possible.

Usage:
    python3 fetch_captions_batch.py --json channels/HubermanLabClips/HubermanLabClips-full-history.json --limit 10
    python3 fetch_captions_batch.py --json <file> --offset 0 --limit 50 --delay 5

New in v2:
  - Early abort: if 3 consecutive 429s, assume IP blocked and exit.
  - Cookie auth: uses Chrome cookies via yt-dlp for higher rate limits.
  - Smart fallback: tries whisper if captions unavailable.
  - Shorts detection: skips videos under 60s (rarely have captions).
  - Better backoff: exponential 5→60s, not flat 120s across 444 videos.
  - Instant skip on known-no-captions videos (transcript API returns block).
"""
import argparse, json, os, re, sys, time, subprocess

from suxxtext.paths import sanitize_filename
from suxxtext.youtube import resolve_yt_dlp

# ── Config ─────────────────────────────────────────────────────────────────
YT_DLP = resolve_yt_dlp()
# Optional: Chrome cookies raise rate limits. Disabled unless --cookies-from-browser is set.
COOKIE_OPTS = []
MAX_RETRIES = 3
CONSECUTIVE_429_LIMIT = 3  # abort after this many 429s in a row

# ── Helpers ─────────────────────────────────────────────────────────────────

def is_short(video_entry):
    """Heuristic: videos under 60s duration are likely Shorts."""
    dur = video_entry.get("length_seconds") or video_entry.get("duration") or 0
    return int(dur) < 60

def fetch_via_transcript_api(video_id):
    """Try youtube-transcript-api. Returns (text|None, was_blocked_bool)."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
    api = YouTubeTranscriptApi()
    for attempt in range(MAX_RETRIES):
        try:
            snippets = api.fetch(video_id)
            return (" ".join(seg.text for seg in snippets) if snippets else None, False)
        except (TranscriptsDisabled, NoTranscriptFound):
            return (None, False)  # no captions, not a block
        except Exception as e:
            err = str(e).lower()
            if any(x in err for x in ["blocked", "429", "too many", "requestblocked", "ipblocked"]):
                if attempt < MAX_RETRIES - 1:
                    wait = 2 ** (attempt + 1) * 5  # 10s, 20s, 40s
                    print(f"  ⚠  429 (attempt {attempt+1}) — waiting {wait}s...", file=sys.stderr)
                    time.sleep(wait)
                    continue
                return (None, True)  # exhausted retries, blocked
            return (None, False)  # other error
    return (None, False)

def has_captions_via_ytdlp(video_id):
    """Quick check using yt-dlp --list-subs with cookies. Returns bool."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r = subprocess.run(
            [*YT_DLP, *COOKIE_OPTS, "--skip-download", "--list-subs", url],
            capture_output=True, text=True, timeout=30,
        )
        out = (r.stdout + r.stderr).lower()
        if "has no subtitles" in out:
            return False
        if "downloading subtitles" in out or "subtitles:" in out or "available subtitles" in out:
            # Check if "en" is in the available languages
            return "en" in out or "english" in out
        return False
    except Exception:
        return False  # don't block on yt-dlp failures

def fetch_via_whisper_cpu(video_id, output_path, workdir="/tmp/yt_whisper"):
    """Download audio + transcribe via Whisper CPU (tiny model, slow but works)."""
    os.makedirs(workdir, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"

    # Download audio
    print(f"  🎧 Downloading audio...", file=sys.stderr)
    r = subprocess.run(
        [*YT_DLP, *COOKIE_OPTS, "-x", "--audio-format", "mp3",
         "-o", f"{workdir}/%(id)s.%(ext)s", url],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        print(f"  ⚠  Audio download failed: {r.stderr[-200:]}", file=sys.stderr)
        return None
    audio_file = f"{workdir}/{video_id}.mp3"
    if not os.path.exists(audio_file):
        return None

    # Transcribe with Whisper tiny (CPU, ~2-5x realtime)
    print(f"  🧠 Transcribing (tiny, CPU)...", file=sys.stderr)
    try:
        import whisper
        model = whisper.load_model("tiny")
        result = model.transcribe(audio_file)
        os.unlink(audio_file)  # cleanup
        return result["text"].strip()
    except Exception as e:
        print(f"  ⚠  Whisper failed: {e}", file=sys.stderr)
        return None

# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch captions for a batch of YouTube videos")
    parser.add_argument("--json", required=True, help="Path to channel JSON file with entries[]")
    parser.add_argument("--limit", type=int, default=10, help="Videos to process (default: 10)")
    parser.add_argument("--delay", type=float, default=10.0, help="Delay between requests (default: 10s)")
    parser.add_argument("--offset", type=int, default=0, help="Start index")
    parser.add_argument("--whisper", action="store_true", help="Fall back to Whisper CPU if no captions")
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
        help="Pass cookies from a browser to yt-dlp (e.g. chrome, firefox). Optional.",
    )
    args = parser.parse_args()

    global COOKIE_OPTS
    if args.cookies_from_browser:
        COOKIE_OPTS = ["--cookies-from-browser", args.cookies_from_browser]

    with open(args.json) as f:
        data = json.load(f)
    entries = data.get("entries", data if isinstance(data, list) else [])
    total = len(entries)

    base_dir = os.path.dirname(os.path.abspath(args.json))
    trans_dir = os.path.join(base_dir, "transcriptions")
    os.makedirs(trans_dir, exist_ok=True)

    # Existing IDs
    existing_ids = set()
    for fname in os.listdir(trans_dir):
        m = re.search(r'_([a-zA-Z0-9_-]{11})\.txt$', fname)
        if m:
            existing_ids.add(m.group(1))

    batch = entries[args.offset:args.offset + args.limit]
    processed = skipped = no_cap = blocked_abort = 0
    consecutive_429s = 0

    print(f"Batch: {len(batch)} videos (offset={args.offset}, delay={args.delay}s)")
    if COOKIE_OPTS:
        print(f"  yt-dlp cookies: {' '.join(COOKIE_OPTS)}\n")
    else:
        print("  Caption API only (no browser cookies). Use --cookies-from-browser chrome if rate-limited.\n")
    for idx, vid in enumerate(batch):
        vid_id = vid.get("id")
        title = vid.get("title", "?")
        views = vid.get("view_count", 0) or 0
        if not vid_id:
            continue
        if vid_id in existing_ids:
            skipped += 1
            continue

        # Check for Shorts
        if is_short(vid):
            print(f"  ⏭  {vid_id} — Shorts (under 60s), skipping")
            skipped += 1
            continue

        name = sanitize_filename(title, 50)
        fpath = os.path.join(trans_dir, f"{name}_{views}views_{vid_id}.txt")
        print(f"  [{idx+1}/{len(batch)}] {vid_id}: {title[:60]}", end="", file=sys.stderr)

        # ── Tier 1: youtube-transcript-api ──
        text, was_blocked = fetch_via_transcript_api(vid_id)
        if was_blocked:
            consecutive_429s += 1
            print(f"  ⚠  BLOCKED ({consecutive_429s}/{CONSECUTIVE_429_LIMIT})", file=sys.stderr)
            if consecutive_429s >= CONSECUTIVE_429_LIMIT:
                print(f"\n⛔ Aborting: {CONSECUTIVE_429_LIMIT} consecutive 429s — IP is blocked.", file=sys.stderr)
                print(f"   Try again in a few hours, or use a VPN/proxy.")
                blocked_abort = len(batch) - idx - 1
                break
            # Write placeholder and continue
            with open(fpath, "w") as f:
                f.write(f"[No captions — {vid_id}]\n")
            no_cap += 1
            continue
        else:
            consecutive_429s = 0  # reset on success

        if text:
            with open(fpath, "w") as f:
                f.write(text)
            processed += 1
            print(f"  ✓ captions ({len(text)} chars)", file=sys.stderr)
        else:
            # ── Tier 2: Whisper fallback (--whisper flag) ──
            if args.whisper:
                print(f"  🔄 no captions, trying Whisper...", file=sys.stderr)
                text = fetch_via_whisper_cpu(vid_id, fpath)
                if text:
                    with open(fpath, "w") as f:
                        f.write(text)
                    processed += 1
                    print(f"  ✓ whisper ({len(text)} chars)", file=sys.stderr)
                else:
                    with open(fpath, "w") as f:
                        f.write(f"[No captions — {vid_id}]\n")
                    no_cap += 1
                    print(f"  ⚡ no captions (API + Whisper failed)", file=sys.stderr)
            else:
                with open(fpath, "w") as f:
                    f.write(f"[No captions — {vid_id}]\n")
                no_cap += 1
                print(f"  ⚡ no captions", file=sys.stderr)

        time.sleep(args.delay)

    print(f"\n─── Batch complete ───")
    print(f"  Total: {len(batch)}")
    print(f"  New:   {processed}")
    print(f"  Skip:  {skipped}")
    print(f"  NoCap: {no_cap}")
    if blocked_abort:
        print(f"  Abort: {blocked_abort} unprocessed due to rate limiting")
    print(f"  Files in {trans_dir}: {len(os.listdir(trans_dir)) if os.path.exists(trans_dir) else 0}")

if __name__ == "__main__":
    main()
