#!/usr/bin/env python3
"""
TL;DW Pipeline — unified YouTube content extraction + delivery pipeline.

Combines the light caption path (youtube-transcript-api) with structured
output for downstream summarization, formatting, and delivery.

Usage:
    # Single video
    python3 yt_tldw.py --url "https://youtube.com/watch?v=VIDEO_ID"
    python3 yt_tldw.py --url "VIDEO_ID" --output-dir ./transcripts

    # Latest N videos from a channel
    python3 yt_tldw.py --channel "@channelname" --limit 5
    python3 yt_tldw.py --channel "https://youtube.com/@channelname/videos" --limit 3

    # With Whisper fallback for videos without captions
    python3 yt_tldw.py --url "URL" --fallback-whisper

Output:
    transcripts/
      {sanitized_title}_{video_id}/
        transcript.txt          # Raw full text
        transcript_timed.txt    # Timestamped text
        metadata.json           # Video metadata + processing info
    
    On stdout: JSON array of results with video metadata and transcript paths.

Dependencies:
    youtube-transcript-api, yt-dlp (see requirements.txt)
    faster-whisper or openai-whisper (optional, for --fallback-whisper)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Path resolution ──────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR
SUXXTEXT_VENV_PYTHON = PROJECT_ROOT / "suxxtext-venv/bin/python3"


def resolve_yt_dlp() -> list:
    """Return argv prefix to run yt-dlp (venv module, PATH, or common install paths)."""
    if SUXXTEXT_VENV_PYTHON.exists():
        return [str(SUXXTEXT_VENV_PYTHON), "-m", "yt_dlp"]
    which = shutil.which("yt-dlp")
    if which:
        return [which]
    for candidate in (
        Path.home() / ".local/bin/yt-dlp",
        Path("/usr/local/bin/yt-dlp"),
        Path("/usr/bin/yt-dlp"),
    ):
        if candidate.exists():
            return [str(candidate)]
    return ["yt-dlp"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_video_id(url_or_id: str) -> str:
    """Extract 11-char video ID from any YouTube URL format."""
    url_or_id = url_or_id.strip()
    patterns = [
        r'(?:v=|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id


def sanitize_filename(name: str, max_length: int = 50) -> str:
    """Create a safe filename from a video title."""
    keepchars = (" ", ".", "_", "-")
    sanitized = "".join(c if c.isalnum() or c in keepchars else "_" for c in name)
    sanitized = sanitized.strip().replace(" ", "_")
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
    return sanitized


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Caption Fetcher ───────────────────────────────────────────────────────────

def fetch_captions(video_id: str, languages: Optional[list] = None) -> dict:
    """
    Fetch captions via youtube-transcript-api (portable; no external scripts).
    Returns success payload or {"error": "..."}.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return {
            "error": "youtube-transcript-api not installed. Run: pip install youtube-transcript-api"
        }

    try:
        api = YouTubeTranscriptApi()
        if languages:
            fetched = api.fetch(video_id, languages=languages)
        else:
            fetched = api.fetch(video_id)

        segments = [
            {"text": seg.text, "start": seg.start, "duration": seg.duration}
            for seg in fetched
        ]
        full_text = " ".join(s["text"].strip() for s in segments if s["text"].strip())
        timestamped_text = "\n".join(
            f"{format_timestamp(s['start'])} {s['text'].strip()}"
            for s in segments
            if s["text"].strip()
        )
        total_dur = 0.0
        if segments:
            last = segments[-1]
            total_dur = float(last["start"]) + float(last.get("duration") or 0)

        language = "unknown"
        try:
            language = getattr(fetched, "language_code", None) or getattr(fetched, "language", None) or "unknown"
        except Exception:
            pass

        return {
            "success": True,
            "video_id": video_id,
            "segment_count": len(segments),
            "duration": format_timestamp(total_dur),
            "full_text": full_text,
            "timestamped_text": timestamped_text,
            "language": language,
        }
    except Exception as e:
        err = str(e)
        low = err.lower()
        if "disabled" in low:
            return {"error": "Transcripts are disabled for this video."}
        if "no transcript" in low or "not found" in low:
            return {"error": "No transcript found for this video."}
        return {"error": err}


# ── Channel Discovery ─────────────────────────────────────────────────────────

def discover_channel_videos(channel_url: str, limit: int = 10) -> list:
    """
    Use yt-dlp to get the latest N videos from a channel.
    Returns list of {"title": ..., "id": ..., "url": ..., "duration": ..., "view_count": ...}
    """
    # Normalize channel URL
    if not channel_url.startswith("http"):
        if channel_url.startswith("@"):
            channel_url = f"https://youtube.com/{channel_url}/videos"
        elif channel_url.startswith("UC") and len(channel_url) == 24:
            channel_url = f"https://youtube.com/channel/{channel_url}/videos"
        else:
            channel_url = f"https://youtube.com/@{channel_url}/videos"
    
    cmd = [
        *resolve_yt_dlp(),
        "--flat-playlist",
        "--no-download",
        "--print", "%(title)s|||%(id)s|||%(duration)s|||%(view_count)s|||%(webpage_url)s",
        "--playlist-end", str(limit),
        channel_url,
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"yt-dlp error: {result.stderr[:500]}", file=sys.stderr)
            return []
        
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|||")
            if len(parts) >= 5:
                videos.append({
                    "title": parts[0].strip(),
                    "id": parts[1].strip(),
                    "duration": parts[2].strip() if parts[2].strip() != "None" else "?",
                    "view_count": parts[3].strip() if parts[3].strip() != "None" else "?",
                    "url": parts[4].strip(),
                })
        
        return videos
    except subprocess.TimeoutExpired:
        print("Channel discovery timed out", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Channel discovery error: {e}", file=sys.stderr)
        return []


# ── Whisper Fallback ──────────────────────────────────────────────────────────

def transcribe_with_whisper(video_url: str, output_dir: Path, model: str = "base") -> dict:
    """
    Fallback: download audio with yt-dlp, transcribe with faster-whisper
    (preferred) or openai-whisper.
    """
    audio_path = output_dir / "audio.m4a"

    dl_cmd = [
        *resolve_yt_dlp(),
        "-f", "bestaudio[ext=m4a]/bestaudio",
        "-o", str(audio_path),
        "--no-playlist",
        video_url,
    ]

    try:
        subprocess.run(dl_cmd, capture_output=True, text=True, timeout=180, check=True)
    except Exception as e:
        return {"error": f"Audio download failed: {e}"}

    if not audio_path.exists():
        return {"error": "Audio download produced no file"}

    try:
        # Prefer faster-whisper (same stack as transcribe2.py)
        try:
            from faster_whisper import WhisperModel
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute = "float16" if device == "cuda" else "int8"
            fw = WhisperModel(model, device=device, compute_type=compute)
            segments_iter, _info = fw.transcribe(str(audio_path), beam_size=5)
            segments = list(segments_iter)
            full_text = " ".join(seg.text.strip() for seg in segments if seg.text)
            timestamped = "\n".join(
                f"{format_timestamp(seg.start)} {seg.text.strip()}"
                for seg in segments
                if seg.text
            )
            backend = f"faster-whisper/{device}"
        except ImportError:
            import whisper

            model_instance = whisper.load_model(model)
            result = model_instance.transcribe(str(audio_path))
            segments = result.get("segments", [])
            full_text = " ".join(seg.get("text", "") for seg in segments)
            timestamped = "\n".join(
                f"{format_timestamp(seg['start'])} {seg['text'].strip()}"
                for seg in segments
            )
            backend = "openai-whisper"

        audio_path.unlink(missing_ok=True)

        return {
            "success": True,
            "video_id": extract_video_id(video_url),
            "segment_count": len(segments),
            "full_text": full_text,
            "timestamped_text": timestamped,
            "method": "whisper",
            "model": model,
            "backend": backend,
        }
    except Exception as e:
        audio_path.unlink(missing_ok=True)
        return {"error": f"Whisper transcription failed: {e}"}


# ── Core Pipeline ─────────────────────────────────────────────────────────────

def process_video(video_input: str, output_dir: Path, languages: list = None,
                  fallback_whisper: bool = False, delay: float = 0,
                  whisper_model: str = "base") -> dict:
    """
    Process a single video: fetch captions → save output → return metadata.
    
    Args:
        video_input: Video URL or ID
        output_dir: Base output directory
        languages: Language codes for caption fallback chain
        fallback_whisper: If True, fall back to Whisper when captions unavailable
        delay: Seconds to wait before fetching (rate limiting)
        whisper_model: Model name when using Whisper fallback
    
    Returns:
        dict with keys: video_id, title, url, status, transcript_path, error, ...
    """
    video_id = extract_video_id(video_input)
    video_url = f"https://youtube.com/watch?v={video_id}" if not video_input.startswith("http") else video_input
    
    if delay > 0:
        time.sleep(delay)
    
    # Create per-video output directory
    video_dir = output_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    
    result = {
        "video_id": video_id,
        "url": video_url,
        "status": "processing",
        "output_dir": str(video_dir),
    }
    
    # Try captions first
    caption_result = fetch_captions(video_id, languages)
    
    if caption_result.get("success"):
        # Save outputs
        transcript_path = video_dir / "transcript.txt"
        timed_path = video_dir / "transcript_timed.txt"
        
        transcript_path.write_text(caption_result["full_text"], encoding="utf-8")
        timed_path.write_text(caption_result["timestamped_text"], encoding="utf-8")
        
        result.update({
            "status": "success",
            "method": "captions",
            "segment_count": caption_result["segment_count"],
            "duration": caption_result["duration"],
            "transcript_path": str(transcript_path),
            "timed_path": str(timed_path),
            "char_count": len(caption_result["full_text"]),
            "language": caption_result["language"],
        })
    
    elif fallback_whisper:
        print(f"  Captions unavailable, falling back to Whisper...", file=sys.stderr)
        whisper_result = transcribe_with_whisper(
            video_url, video_dir, model=whisper_model
        )
        
        if whisper_result.get("success"):
            transcript_path = video_dir / "transcript.txt"
            timed_path = video_dir / "transcript_timed.txt"
            
            transcript_path.write_text(whisper_result["full_text"], encoding="utf-8")
            timed_path.write_text(whisper_result["timestamped_text"], encoding="utf-8")
            
            result.update({
                "status": "success",
                "method": "whisper",
                "model": whisper_result.get("model", "?"),
                "segment_count": whisper_result["segment_count"],
                "transcript_path": str(transcript_path),
                "timed_path": str(timed_path),
                "char_count": len(whisper_result["full_text"]),
            })
        else:
            result.update({
                "status": "failed",
                "error": whisper_result.get("error", "Whisper fallback failed"),
            })
    else:
        result.update({
            "status": "no_captions",
            "error": caption_result.get("error", "Captions unavailable"),
        })
    
    # Always save metadata
    meta_path = video_dir / "metadata.json"
    meta_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TL;DW — YouTube transcript extraction pipeline"
    )
    parser.add_argument("--url", help="Single video URL or ID to process")
    parser.add_argument("--channel", help="Channel URL or @handle for batch processing")
    parser.add_argument("--limit", type=int, default=5, help="Max videos to process from channel (default: 5)")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: ./transcripts)")
    parser.add_argument("--language", help="Comma-separated language codes for fallback (e.g. en,tr)")
    parser.add_argument("--delay", type=float, default=10.0, help="Seconds between requests for rate limiting (default: 10)")
    parser.add_argument("--fallback-whisper", action="store_true", help="Use Whisper fallback when captions unavailable")
    parser.add_argument("--whisper-model", default="base", help="Whisper model for fallback (default: base)")
    parser.add_argument("--dry-run", action="store_true", help="Discover only, don't fetch transcripts")
    
    args = parser.parse_args()
    
    if not args.url and not args.channel:
        parser.error("Either --url or --channel is required")
    
    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd() / "transcripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    languages = [l.strip() for l in args.language.split(",")] if args.language else None
    
    results = []
    
    if args.channel:
        print(f"Discovering latest {args.limit} videos from {args.channel}...", file=sys.stderr)
        videos = discover_channel_videos(args.channel, args.limit)
        print(f"Found {len(videos)} videos.", file=sys.stderr)
        
        if args.dry_run:
            print(json.dumps(videos, indent=2, ensure_ascii=False))
            return
        
        for i, video in enumerate(videos):
            print(f"[{i+1}/{len(videos)}] {video['title'][:60]}...", file=sys.stderr)
            result = process_video(
                video["url"],
                output_dir,
                languages=languages,
                fallback_whisper=args.fallback_whisper,
                delay=args.delay if i > 0 else 0,  # No delay on first, delay between rest
                whisper_model=args.whisper_model,
            )
            result["title"] = video["title"]
            result["view_count"] = video.get("view_count", "?")
            results.append(result)
            
            if result["status"] == "success":
                print(f"  ✓ {result['method']} — {result['char_count']} chars, {result.get('segment_count', '?')} segments", file=sys.stderr)
            else:
                print(f"  ✗ {result['status']}: {result.get('error', '')[:100]}", file=sys.stderr)
    
    elif args.url:
        if args.dry_run:
            print(f"Would process: {args.url}")
            return
        
        result = process_video(
            args.url,
            output_dir,
            languages=languages,
            fallback_whisper=args.fallback_whisper,
            whisper_model=args.whisper_model,
        )
        results.append(result)
        
        if result["status"] == "success":
            print(f"✓ {result['method']} — {result['char_count']} chars, {result.get('segment_count', '?')} segments", file=sys.stderr)
        else:
            print(f"✗ {result['status']}: {result.get('error', '')}", file=sys.stderr)
    
    # Output JSON summary to stdout
    summary = {
        "pipeline": "yt_tldw",
        "timestamp": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "total": len(results),
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] in ("failed", "no_captions")),
        "results": results,
    }
    
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
