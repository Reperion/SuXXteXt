"""YouTube caption fetch via youtube-transcript-api."""

from __future__ import annotations

from typing import List, Optional

from suxxtext.whisper_runtime import format_timestamp


def fetch_captions(video_id: str, languages: Optional[List[str]] = None) -> dict:
    """
    Fetch captions for a video id.
    Returns success dict or {"error": "..."}.
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
            language = (
                getattr(fetched, "language_code", None)
                or getattr(fetched, "language", None)
                or "unknown"
            )
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
