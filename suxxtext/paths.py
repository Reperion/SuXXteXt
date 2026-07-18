"""Channel archive paths, filename sanitization, skip detection."""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

CHANNELS_ROOT = "channels"


def sanitize_filename(name: str, max_length: int = 50) -> str:
    keepchars = (" ", ".", "_", "-")
    sanitized = "".join(c if c.isalnum() or c in keepchars else "_" for c in name)
    sanitized = sanitized.strip().replace(" ", "_")
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    return sanitized


def alnum_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def alnum_related(a: str, b: str) -> bool:
    """Same key, containment, or short is subsequence of long (len>=6)."""
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 6:
        return False
    it = iter(long_)
    return all(ch in it for ch in short)


def channel_handle_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    m = re.search(r"youtube\.com/@([^/?#]+)", url, re.I)
    if m:
        return m.group(1)
    cleaned = url.rstrip("/")
    for suffix in ("/videos", "/streams", "/shorts", "/featured", "/playlists", "/community"):
        if cleaned.lower().endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    m = re.search(r"youtube\.com/@([^/?#]+)", cleaned, re.I)
    if m:
        return m.group(1)
    part = cleaned.rstrip("/").split("/")[-1]
    if part.startswith("@"):
        return part[1:]
    if part.startswith("UC") and len(part) >= 22:
        return part
    if part and "youtube" not in part.lower() and part not in (
        "www.youtube.com",
        "channel",
        "c",
        "user",
    ):
        if not part.startswith("UC"):
            return part
    return None


def channel_handle_from_info(info: Optional[dict]) -> Optional[str]:
    if not info:
        return None
    for key in ("uploader_url", "channel_url", "webpage_url", "original_url"):
        handle = channel_handle_from_url(info.get(key) or "")
        if handle and not (handle.startswith("UC") and len(handle) >= 22):
            return handle
    for key in ("uploader_url", "channel_url"):
        handle = channel_handle_from_url(info.get(key) or "")
        if handle:
            return handle
    return None


def list_channel_dirs(channels_root: str = CHANNELS_ROOT) -> List[str]:
    if not os.path.isdir(channels_root):
        return []
    return [
        e
        for e in os.listdir(channels_root)
        if os.path.isdir(os.path.join(channels_root, e))
        and ".bak" not in e.lower()
        and not e.startswith("_")
    ]


def resolve_channel_folder(
    info: Optional[dict] = None,
    channel_url: Optional[str] = None,
    channels_root: str = CHANNELS_ROOT,
) -> str:
    """
    Canonical archive folder under channels/.

    Prefers @handle; reuses existing dirs via exact / case / alnum / related match.
    """
    handle = None
    if channel_url:
        handle = channel_handle_from_url(channel_url)
    if not handle and info:
        handle = channel_handle_from_info(info)

    display = None
    if info:
        display = info.get("channel") or info.get("uploader") or info.get("title")

    candidates: List[str] = []
    if handle:
        candidates.append(sanitize_filename(handle, 50))
    if display:
        d = sanitize_filename(display, 50)
        d = re.sub(r"_-_Videos$", "", d)
        d = re.sub(r"_Videos$", "", d)
        if d and d not in candidates:
            candidates.append(d)

    if not candidates:
        candidates = ["channel"]

    existing = list_channel_dirs(channels_root)

    for c in candidates:
        if c in existing:
            return c

    lower_map = {e.lower(): e for e in existing}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]

    existing_norm = {alnum_key(e): e for e in existing}
    for c in candidates:
        key = alnum_key(c)
        if key and key in existing_norm:
            return existing_norm[key]

    match_keys = list(candidates)
    if handle:
        match_keys.append(handle)
    best = None  # (len, name)
    for c in match_keys:
        ckey = alnum_key(c)
        if not ckey or len(ckey) < 5:
            continue
        for e in existing:
            ekey = alnum_key(e)
            if not ekey or len(ekey) < 5:
                continue
            if alnum_related(ckey, ekey):
                cand = (len(e), e)
                if best is None or cand < best:
                    best = cand
    if best:
        return best[1]

    return candidates[0]


def ensure_channel_dirs(
    channel_folder: str, channels_root: str = CHANNELS_ROOT
) -> Tuple[str, str, str]:
    base = os.path.join(channels_root, channel_folder)
    mp3_dir = os.path.join(base, "mp3")
    trans_dir = os.path.join(base, "transcriptions")
    os.makedirs(mp3_dir, exist_ok=True)
    os.makedirs(trans_dir, exist_ok=True)
    return base, mp3_dir, trans_dir


def transcript_exists_for_id(trans_dir: str, video_id: str) -> Optional[str]:
    """Return matching transcript filename if video_id already archived, else None."""
    if not video_id or not os.path.isdir(trans_dir):
        return None
    try:
        for name in os.listdir(trans_dir):
            if video_id in name and name.endswith(".txt"):
                return name
    except OSError:
        return None
    return None


def list_existing_transcript_ids(trans_dir: str) -> set:
    ids = set()
    if not os.path.isdir(trans_dir):
        return ids
    try:
        for name in os.listdir(trans_dir):
            if not name.endswith(".txt"):
                continue
            m = re.search(r"([A-Za-z0-9_-]{11})\.txt$", name)
            if m:
                ids.add(m.group(1))
            # also any embedded 11-char token
            for part in re.findall(r"[A-Za-z0-9_-]{11}", name):
                ids.add(part)
    except OSError:
        pass
    return ids
