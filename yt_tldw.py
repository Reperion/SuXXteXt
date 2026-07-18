#!/usr/bin/env python3
"""
TL;DW Pipeline — captions-first YouTube extraction (+ optional Whisper).

Uses the shared suxxtext library (portable; no Hermes paths).

Usage:
    python3 yt_tldw.py --url "https://youtube.com/watch?v=VIDEO_ID"
    python3 yt_tldw.py --channel "@channelname" --limit 5
    python3 yt_tldw.py --url "URL" --fallback-whisper
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from suxxtext.captions import fetch_captions
from suxxtext.whisper_runtime import format_timestamp, load_whisper_model
from suxxtext.youtube import (
    discover_channel_videos_flat,
    download_audio,
    extract_video_id,
    normalize_channel_url,
    resolve_yt_dlp,
)


def transcribe_with_whisper(video_url: str, output_dir: Path, model: str = "base") -> dict:
    audio_path = output_dir / "audio.m4a"
    ok, err = download_audio(video_url, str(audio_path))
    if not ok:
        return {"error": f"Audio download failed: {err}"}
    if not audio_path.exists():
        return {"error": "Audio download produced no file"}

    try:
        fw = load_whisper_model(model, quiet=True)
        segments_iter, _info = fw.transcribe(str(audio_path), beam_size=5)
        segments = list(segments_iter)
        full_text = " ".join(seg.text.strip() for seg in segments if seg.text)
        timestamped = "\n".join(
            f"{format_timestamp(seg.start)} {seg.text.strip()}"
            for seg in segments
            if seg.text
        )
        audio_path.unlink(missing_ok=True)
        return {
            "success": True,
            "video_id": extract_video_id(video_url),
            "segment_count": len(segments),
            "full_text": full_text,
            "timestamped_text": timestamped,
            "method": "whisper",
            "model": model,
            "backend": "faster-whisper",
        }
    except Exception as e:
        audio_path.unlink(missing_ok=True)
        return {"error": f"Whisper transcription failed: {e}"}


def process_video(
    video_input: str,
    output_dir: Path,
    languages: Optional[List[str]] = None,
    fallback_whisper: bool = False,
    delay: float = 0,
    whisper_model: str = "base",
) -> dict:
    video_id = extract_video_id(video_input)
    video_url = (
        f"https://youtube.com/watch?v={video_id}"
        if not video_input.startswith("http")
        else video_input
    )

    if delay > 0:
        time.sleep(delay)

    video_dir = output_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "video_id": video_id,
        "url": video_url,
        "status": "processing",
        "output_dir": str(video_dir),
    }

    caption_result = fetch_captions(video_id, languages)

    if caption_result.get("success"):
        transcript_path = video_dir / "transcript.txt"
        timed_path = video_dir / "transcript_timed.txt"
        transcript_path.write_text(caption_result["full_text"], encoding="utf-8")
        timed_path.write_text(caption_result["timestamped_text"], encoding="utf-8")
        result.update(
            {
                "status": "success",
                "method": "captions",
                "segment_count": caption_result["segment_count"],
                "duration": caption_result["duration"],
                "transcript_path": str(transcript_path),
                "timed_path": str(timed_path),
                "char_count": len(caption_result["full_text"]),
                "language": caption_result["language"],
            }
        )
    elif fallback_whisper:
        print("  Captions unavailable, falling back to Whisper...", file=sys.stderr)
        whisper_result = transcribe_with_whisper(video_url, video_dir, model=whisper_model)
        if whisper_result.get("success"):
            transcript_path = video_dir / "transcript.txt"
            timed_path = video_dir / "transcript_timed.txt"
            transcript_path.write_text(whisper_result["full_text"], encoding="utf-8")
            timed_path.write_text(whisper_result["timestamped_text"], encoding="utf-8")
            result.update(
                {
                    "status": "success",
                    "method": "whisper",
                    "model": whisper_result.get("model", "?"),
                    "segment_count": whisper_result["segment_count"],
                    "transcript_path": str(transcript_path),
                    "timed_path": str(timed_path),
                    "char_count": len(whisper_result["full_text"]),
                }
            )
        else:
            result.update(
                {
                    "status": "failed",
                    "error": whisper_result.get("error", "Whisper fallback failed"),
                }
            )
    else:
        result.update(
            {
                "status": "no_captions",
                "error": caption_result.get("error", "Captions unavailable"),
            }
        )

    meta_path = video_dir / "metadata.json"
    meta_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="TL;DW — YouTube transcript extraction pipeline")
    parser.add_argument("--url", help="Single video URL or ID")
    parser.add_argument("--channel", help="Channel URL or @handle")
    parser.add_argument("--limit", type=int, default=5, help="Max videos from channel (default 5)")
    parser.add_argument("--output-dir", default=None, help="Output directory (default ./transcripts)")
    parser.add_argument("--language", help="Comma-separated language codes (e.g. en,tr)")
    parser.add_argument(
        "--delay", type=float, default=10.0, help="Seconds between channel requests (default 10)"
    )
    parser.add_argument(
        "--fallback-whisper",
        action="store_true",
        help="Use Whisper when captions unavailable",
    )
    parser.add_argument("--whisper-model", default="base", help="Whisper model (default base)")
    parser.add_argument("--dry-run", action="store_true", help="Discover only")
    args = parser.parse_args(argv)

    if not args.url and not args.channel:
        parser.error("Either --url or --channel is required")

    output_dir = Path(args.output_dir) if args.output_dir else Path.cwd() / "transcripts"
    output_dir.mkdir(parents=True, exist_ok=True)
    languages = [l.strip() for l in args.language.split(",")] if args.language else None

    results = []

    if args.channel:
        print(f"Discovering latest {args.limit} videos from {args.channel}...", file=sys.stderr)
        # normalize for messaging
        _ = normalize_channel_url(args.channel)
        videos = discover_channel_videos_flat(args.channel, args.limit)
        print(f"Found {len(videos)} videos.", file=sys.stderr)

        if args.dry_run:
            print(json.dumps(videos, indent=2, ensure_ascii=False))
            return 0

        for i, video in enumerate(videos):
            print(f"[{i + 1}/{len(videos)}] {video['title'][:60]}...", file=sys.stderr)
            result = process_video(
                video["url"],
                output_dir,
                languages=languages,
                fallback_whisper=args.fallback_whisper,
                delay=args.delay if i > 0 else 0,
                whisper_model=args.whisper_model,
            )
            result["title"] = video["title"]
            result["view_count"] = video.get("view_count", "?")
            results.append(result)
            if result["status"] == "success":
                print(
                    f"  ✓ {result['method']} — {result['char_count']} chars, "
                    f"{result.get('segment_count', '?')} segments",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  ✗ {result['status']}: {result.get('error', '')[:100]}",
                    file=sys.stderr,
                )

    elif args.url:
        if args.dry_run:
            print(f"Would process: {args.url}")
            return 0
        result = process_video(
            args.url,
            output_dir,
            languages=languages,
            fallback_whisper=args.fallback_whisper,
            whisper_model=args.whisper_model,
        )
        results.append(result)
        if result["status"] == "success":
            print(
                f"✓ {result['method']} — {result['char_count']} chars, "
                f"{result.get('segment_count', '?')} segments",
                file=sys.stderr,
            )
        else:
            print(f"✗ {result['status']}: {result.get('error', '')}", file=sys.stderr)

    summary = {
        "pipeline": "yt_tldw",
        "timestamp": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "total": len(results),
        "succeeded": sum(1 for r in results if r["status"] == "success"),
        "failed": sum(1 for r in results if r["status"] in ("failed", "no_captions")),
        "results": results,
        "yt_dlp": resolve_yt_dlp(),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
