"""yt-dlp helpers: resolve binary, download media, list channel videos."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUXXTEXT_VENV_PYTHON = PROJECT_ROOT / "suxxtext-venv" / "bin" / "python3"


def resolve_yt_dlp() -> List[str]:
    """Argv prefix to invoke yt-dlp (prefer project venv module)."""
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


def extract_video_id(url_or_id: str) -> str:
    url_or_id = (url_or_id or "").strip()
    patterns = [
        r"(?:v=|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return url_or_id


def download_audio(youtube_url: str, output_file: str) -> Tuple[bool, Optional[str]]:
    try:
        subprocess.run(
            [
                *resolve_yt_dlp(),
                "-f",
                "bestaudio[ext=m4a]/bestaudio",
                "-o",
                output_file,
                "--no-playlist",
                youtube_url,
            ],
            check=True,
        )
        return True, None
    except subprocess.CalledProcessError as e:
        return False, str(e)


def download_lowres_video(youtube_url: str, output_file: str) -> Tuple[bool, Optional[str]]:
    try:
        subprocess.run(
            [
                *resolve_yt_dlp(),
                "-f",
                "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[ext=mp4]",
                "--merge-output-format",
                "mp4",
                "-o",
                output_file,
                "--no-playlist",
                youtube_url,
            ],
            check=True,
        )
        return True, None
    except subprocess.CalledProcessError as e:
        return False, str(e)


def extract_video_info(youtube_url: str) -> Dict[str, Any]:
    import yt_dlp

    ytdlp_opts = {"skip_download": True, "quiet": True, "no_playlist": True}
    with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
        return ydl.extract_info(youtube_url, download=False)


def get_channel_videos(channel_url: str, max_videos: int = 10) -> Tuple[List[dict], dict]:
    """Return (video entries newest-first, full channel info). max_videos unused (full list)."""
    import yt_dlp

    _ = max_videos
    ytdlp_opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "force_generic_extractor": False,
    }
    with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        videos = info.get("entries") or []
        videos = [v for v in videos if v and str(v.get("ie_key", "")).startswith("Youtube")]
        videos = sorted(videos, key=lambda v: v.get("upload_date") or "", reverse=True)
        return videos, info


def normalize_channel_url(channel: str) -> str:
    if channel.startswith("http"):
        return channel
    if channel.startswith("@"):
        return f"https://www.youtube.com/{channel}/videos"
    if channel.startswith("UC") and len(channel) == 24:
        return f"https://www.youtube.com/channel/{channel}/videos"
    return f"https://www.youtube.com/@{channel}/videos"


def discover_channel_videos_flat(channel_url: str, limit: int = 10) -> List[dict]:
    """Lightweight latest-N discovery via yt-dlp --print (for TL;DW)."""
    url = normalize_channel_url(channel_url)
    cmd = [
        *resolve_yt_dlp(),
        "--flat-playlist",
        "--no-download",
        "--print",
        "%(title)s|||%(id)s|||%(duration)s|||%(view_count)s|||%(webpage_url)s",
        "--playlist-end",
        str(limit),
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            return []
        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|||")
            if len(parts) >= 5:
                videos.append(
                    {
                        "title": parts[0].strip(),
                        "id": parts[1].strip(),
                        "duration": parts[2].strip() if parts[2].strip() != "None" else "?",
                        "view_count": parts[3].strip() if parts[3].strip() != "None" else "?",
                        "url": parts[4].strip(),
                    }
                )
        return videos
    except Exception:
        return []
