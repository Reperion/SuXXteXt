"""High-level archive jobs: single video, channel batch, history JSON.

Default pipeline: **captions first**, Whisper only when captions fail or
``--whisper-only``. Batch concurrency defaults match the proven gentle
throttle (4 workers / 2 Whisper models) from the Drberg 512 run.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import time
from datetime import datetime
from typing import Any, List, Optional, Tuple

from colorama import Fore, Style

from suxxtext.captions import fetch_captions
from suxxtext.paths import (
    ensure_channel_dirs,
    resolve_channel_folder,
    sanitize_filename,
    transcript_exists_for_id,
)
from suxxtext.whisper_runtime import ModelPool, transcribe_audio
from suxxtext.youtube import (
    download_audio,
    download_lowres_video,
    extract_video_info,
    get_channel_videos,
)

# Proven gentle defaults (YouTube 403/429 recovery — see docs/ops-channel-batch.md)
DEFAULT_WORKERS = 4
DEFAULT_MODEL_INSTANCES = 2
MIN_CAPTION_CHARS = 40


def normalize_channel_url(url: str) -> str:
    """Accept full URL, @handle, or bare handle → channel /videos URL."""
    u = (url or "").strip()
    if not u:
        return u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("@"):
        return f"https://www.youtube.com/{u}/videos"
    if "youtube.com" not in u.lower():
        return f"https://www.youtube.com/@{u.lstrip('@')}/videos"
    return u


def _paths_for_video(
    video_info: dict, mp3_dir: str, trans_dir: str
) -> Tuple[str, str, str, str, str]:
    video_id = video_info["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    title = video_info.get("title", f"video_{video_id}")
    view_count = video_info.get("view_count", 0)
    sanitized_title = sanitize_filename(title, 50)
    view_count_str = f"{view_count}views" if view_count is not None else "UnknownViews"
    base_filename = f"{sanitized_title}_{view_count_str}_{video_id}"
    mp3_path = os.path.join(mp3_dir, f"{base_filename}.m4a")
    txt_path = os.path.join(trans_dir, f"{base_filename}.txt")
    return video_id, video_url, title, mp3_path, txt_path


def try_captions_to_file(
    video_id: str,
    txt_path: str,
    languages: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """
    Fetch captions and write plain text archive file.
    Returns (ok, detail) where detail is language note or error.
    """
    result = fetch_captions(video_id, languages)
    if not result.get("success"):
        return False, result.get("error") or "captions unavailable"
    text = (result.get("full_text") or "").strip()
    if len(text) < MIN_CAPTION_CHARS:
        return False, f"captions too short ({len(text)} chars)"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")
    lang = result.get("language") or "unknown"
    return True, f"captions lang={lang} chars={len(text)}"


def process_video_task(
    video_info: dict,
    mp3_dir: str,
    trans_dir: str,
    logf: Any,
    model_pool: Optional[ModelPool],
    lock=None,
    prefer_captions: bool = True,
    whisper_fallback: bool = True,
):
    """
    One video for the archive.

    Prefer captions when enabled; Whisper download+ASR only if needed.
    Status: ``captions`` | ``whisper`` | ``error`` | ``skipped``.
    """
    _ = lock
    video_id, video_url, title, mp3_path, txt_path = _paths_for_video(
        video_info, mp3_dir, trans_dir
    )

    if prefer_captions:
        print(f"{Fore.WHITE}[{video_id}] Trying captions...{Style.RESET_ALL}")
        ok, detail = try_captions_to_file(video_id, txt_path)
        if ok:
            print(
                f"{Fore.GREEN}[{video_id}] Captions saved to {txt_path} ({detail}){Style.RESET_ALL}"
            )
            return "captions", f"Captions for {title} ({video_id}): {detail}"
        print(
            f"{Fore.YELLOW}[{video_id}] Captions miss: {detail}{Style.RESET_ALL}"
        )
        logf.write(f"Captions miss {video_id}: {detail}\n")
        if not whisper_fallback:
            msg = f"No captions and Whisper disabled for {title} ({video_id}): {detail}"
            print(f"{Fore.RED + Style.BRIGHT}[{video_id}] {msg}{Style.RESET_ALL}")
            logf.write(msg + "\n")
            return "error", msg

    if model_pool is None:
        msg = f"Whisper required but model pool not loaded for {title} ({video_id})"
        print(f"{Fore.RED + Style.BRIGHT}[{video_id}] {msg}{Style.RESET_ALL}")
        logf.write(msg + "\n")
        return "error", msg

    print(f"{Fore.WHITE}[{video_id}] Downloading audio...{Style.RESET_ALL}")
    ok, err = download_audio(video_url, mp3_path)
    if not ok:
        msg = f"Download error for {title} ({video_id}): {err}"
        print(f"{Fore.RED + Style.BRIGHT}[{video_id}] {msg}{Style.RESET_ALL}")
        logf.write(msg + "\n")
        if os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except OSError as remove_err:
                logf.write(f"  - Could not remove incomplete mp3 {mp3_path}: {remove_err}\n")
        return "error", msg

    print(f"{Fore.WHITE}[{video_id}] Transcribing audio (Whisper)...{Style.RESET_ALL}")
    try:
        with model_pool.get_model() as model:
            ok, err = transcribe_audio(mp3_path, model, txt_path, lock=None)
    except Exception as pool_err:
        ok = False
        err = f"Model execution failed: {pool_err}"

    if not ok:
        msg = f"Transcription error for {title} ({video_id}): {err}"
        print(f"{Fore.RED + Style.BRIGHT}[{video_id}] {msg}{Style.RESET_ALL}")
        logf.write(msg + "\n")
        return "error", msg

    print(f"{Fore.GREEN}[{video_id}] Whisper saved to {txt_path}{Style.RESET_ALL}")
    return "whisper", f"Whisper processed {title} ({video_id})"


def process_whisper_only_task(
    video_info: dict,
    mp3_dir: str,
    trans_dir: str,
    logf: Any,
    model_pool: ModelPool,
    lock=None,
):
    """Whisper path only (after captions already tried or --whisper-only)."""
    return process_video_task(
        video_info,
        mp3_dir,
        trans_dir,
        logf,
        model_pool,
        lock=lock,
        prefer_captions=False,
        whisper_fallback=True,
    )


def process_single_video(
    url: Optional[str] = None,
    model: Optional[str] = None,
    download_video: Optional[bool] = None,
    prefer_captions: bool = True,
    whisper_fallback: bool = True,
):
    """Process one video. None args → interactive prompts. Captions first by default."""
    if url is None:
        youtube_url = input(f"{Fore.CYAN}Enter YouTube video URL: {Style.RESET_ALL}").strip()
    else:
        youtube_url = url

    if model is None:
        model_name = (
            input(
                f"{Fore.CYAN}Enter Whisper model name (tiny, base, small, medium, large) [base]: {Style.RESET_ALL}"
            ).strip()
            or "base"
        )
    else:
        model_name = model

    print(f"{Fore.BLUE}Getting video info...{Style.RESET_ALL}")
    info = extract_video_info(youtube_url)
    title = info.get("title", "video")
    video_id = info.get("id", "unknown")
    channel_folder = resolve_channel_folder(info=info)
    base_channel_dir, mp3_dir, trans_dir = ensure_channel_dirs(channel_folder)
    print(f"{Fore.BLUE}Channel archive folder: {base_channel_dir}{Style.RESET_ALL}")

    sanitized_title = sanitize_filename(title, 50)
    mp3_path = os.path.join(mp3_dir, f"{sanitized_title}_{video_id}.m4a")
    date_str = datetime.now().strftime("%d-%b-%Y")
    txt_path = os.path.abspath(
        os.path.join(trans_dir, f"{date_str}-{sanitized_title}_{video_id}.txt")
    )
    print(f"{Fore.YELLOW}Saving transcript to: {txt_path}{Style.RESET_ALL}")

    existing = transcript_exists_for_id(trans_dir, video_id)
    if existing:
        print(
            f"{Fore.YELLOW}Transcription already exists for {video_id}: "
            f"{existing}. Skipping.{Style.RESET_ALL}"
        )
        return

    if download_video is None:
        choice = input(
            f"{Fore.CYAN}Download low-resolution video as well? (yes/no) [default: no]: {Style.RESET_ALL}"
        ).strip().lower()
        should_download_video = choice == "yes"
    else:
        should_download_video = bool(download_video)

    if should_download_video:
        video_dir = os.path.join(base_channel_dir, "video")
        os.makedirs(video_dir, exist_ok=True)
        video_path = os.path.join(video_dir, f"{date_str}-{sanitized_title}_{video_id}.mp4")
        print(f"{Fore.BLUE}Downloading low-resolution video to {video_path} ...{Style.RESET_ALL}")
        ok, err = download_lowres_video(youtube_url, video_path)
        if ok:
            print(f"{Fore.GREEN}Low-resolution video saved to {video_path}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED + Style.BRIGHT}Error downloading video: {err}{Style.RESET_ALL}")

    if prefer_captions:
        print(f"{Fore.BLUE}Trying captions first...{Style.RESET_ALL}")
        ok, detail = try_captions_to_file(video_id, txt_path)
        if ok:
            print(f"{Fore.GREEN}Captions saved ({detail}). Done.{Style.RESET_ALL}")
            return
        print(f"{Fore.YELLOW}Captions unavailable: {detail}{Style.RESET_ALL}")
        if not whisper_fallback:
            print(f"{Fore.RED + Style.BRIGHT}Whisper fallback disabled. Aborting.{Style.RESET_ALL}")
            return

    print(f"{Fore.BLUE}Downloading audio to {mp3_path} ...{Style.RESET_ALL}")
    ok, err = download_audio(youtube_url, mp3_path)
    if not ok:
        print(f"{Fore.RED + Style.BRIGHT}Error downloading audio: {err}{Style.RESET_ALL}")
        return

    print(f"{Fore.BLUE}Transcribing audio (Whisper)...{Style.RESET_ALL}")
    ok, err = transcribe_audio(mp3_path, model_name, txt_path)
    if not ok:
        print(f"{Fore.RED + Style.BRIGHT}Error transcribing audio: {err}{Style.RESET_ALL}")
        return
    print(f"{Fore.GREEN}Transcription saved to {txt_path}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")


def download_channel_history_json(url: Optional[str] = None):
    if url is None:
        print(
            f"{Fore.YELLOW}NOTE: The channel URL should be in this format: "
            f"https://www.youtube.com/@channelname/videos{Style.RESET_ALL}"
        )
        channel_url = input(f"{Fore.CYAN}Enter YouTube channel URL: {Style.RESET_ALL}").strip()
    else:
        channel_url = normalize_channel_url(url)

    print(f"{Fore.BLUE}Retrieving all video metadata for the channel...{Style.RESET_ALL}")
    try:
        _, channel_info = get_channel_videos(channel_url)
    except Exception as e:
        print(f"{Fore.RED + Style.BRIGHT}Error retrieving channel info: {e}{Style.RESET_ALL}")
        return

    channel_folder = resolve_channel_folder(info=channel_info, channel_url=channel_url)
    base_channel_dir, _, _ = ensure_channel_dirs(channel_folder)
    metadata_path = os.path.join(base_channel_dir, f"{channel_folder}-full-history.json")

    try:
        with open(metadata_path, "w", encoding="utf-8") as meta_f:
            json.dump(channel_info, meta_f, indent=4, ensure_ascii=False)
        print(f"{Fore.GREEN}Full channel metadata saved to {metadata_path}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not save metadata file: {e}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")


def process_channel_videos(
    url: Optional[str] = None,
    limit=None,
    workers: Optional[int] = None,
    model_instances: Optional[int] = None,
    model: Optional[str] = None,
    prefer_captions: bool = True,
    whisper_fallback: bool = True,
    caption_delay: float = 0.5,
):
    """
    Batch process latest N channel videos.

    Pipeline (default):
      1. Skip if transcript already exists for video_id
      2. Try YouTube captions (serial + small delay — kinder to rate limits)
      3. Whisper download+ASR for remaining (concurrent, gentle defaults)

    None interactive args → prompts. Defaults: 4 workers / 2 Whisper instances.
    """
    model_name = model or "base"

    if url is None:
        print(
            f"{Fore.YELLOW}NOTE: The channel URL should be in this format: "
            f"https://www.youtube.com/@channelname/videos{Style.RESET_ALL}"
        )
        channel_url = input(f"{Fore.CYAN}Enter YouTube channel URL: {Style.RESET_ALL}").strip()
    else:
        channel_url = normalize_channel_url(url)

    print(
        f"{Fore.BLUE}Retrieving all video metadata for the channel "
        f"(this might take a while for large channels)...{Style.RESET_ALL}"
    )
    try:
        videos, channel_info = get_channel_videos(channel_url)
    except Exception as e:
        print(f"{Fore.RED + Style.BRIGHT}Error retrieving channel info: {e}{Style.RESET_ALL}")
        return

    total_videos_found = len(videos)
    print(f"{Fore.WHITE}Found {total_videos_found} videos in the channel.{Style.RESET_ALL}")

    if limit is None:
        num_videos_str = input(
            f"{Fore.CYAN}How many of the latest videos do you want to ensure are processed "
            f"(enter 'all' or a number)? [default {min(10, total_videos_found)}]: {Style.RESET_ALL}"
        ).strip()
        if num_videos_str.lower() == "all":
            num_videos_target = total_videos_found
            print(f"{Fore.BLUE}Processing all {total_videos_found} videos.{Style.RESET_ALL}")
        else:
            try:
                num_videos_target = int(num_videos_str) if num_videos_str else min(10, total_videos_found)
            except ValueError:
                num_videos_target = min(10, total_videos_found)
            if num_videos_target > total_videos_found:
                num_videos_target = total_videos_found
            print(f"{Fore.BLUE}Processing {num_videos_target} videos.{Style.RESET_ALL}")
    else:
        if str(limit).lower() == "all":
            num_videos_target = total_videos_found
        else:
            num_videos_target = int(limit)
            if num_videos_target > total_videos_found:
                num_videos_target = total_videos_found
        print(f"{Fore.BLUE}Processing {num_videos_target} videos.{Style.RESET_ALL}")

    if workers is None:
        concurrency_str = input(
            f"{Fore.CYAN}Concurrent Whisper workers "
            f"[default {DEFAULT_WORKERS}, max 32]: {Style.RESET_ALL}"
        ).strip()
        try:
            max_workers = int(concurrency_str) if concurrency_str else DEFAULT_WORKERS
            if max_workers <= 0:
                max_workers = DEFAULT_WORKERS
            elif max_workers > 32:
                max_workers = 32
            print(f"{Fore.BLUE}Using {max_workers} concurrent workers.{Style.RESET_ALL}")
        except ValueError:
            max_workers = DEFAULT_WORKERS
            print(
                f"{Fore.YELLOW}Invalid number. Using default of {DEFAULT_WORKERS}.{Style.RESET_ALL}"
            )
    else:
        max_workers = min(max(1, int(workers)), 32)
        print(f"{Fore.BLUE}Using {max_workers} concurrent workers.{Style.RESET_ALL}")

    if model_instances is None:
        model_count_str = input(
            f"{Fore.CYAN}Whisper model instances "
            f"[default {DEFAULT_MODEL_INSTANCES}]: {Style.RESET_ALL}"
        ).strip()
        try:
            pool_size = (
                int(model_count_str) if model_count_str else DEFAULT_MODEL_INSTANCES
            )
        except ValueError:
            pool_size = DEFAULT_MODEL_INSTANCES
    else:
        pool_size = max(1, int(model_instances))

    print(f"{Fore.BLUE}Using up to {pool_size} Whisper model instance(s).{Style.RESET_ALL}")
    mode_note = []
    if prefer_captions:
        mode_note.append("captions-first")
    else:
        mode_note.append("whisper-only")
    if prefer_captions and whisper_fallback:
        mode_note.append("Whisper fallback on miss")
    elif prefer_captions and not whisper_fallback:
        mode_note.append("no Whisper fallback")
    print(f"{Fore.BLUE}Pipeline: {', '.join(mode_note)}{Style.RESET_ALL}")

    channel_folder = resolve_channel_folder(info=channel_info, channel_url=channel_url)
    base_channel_dir, mp3_dir, trans_dir = ensure_channel_dirs(channel_folder)
    print(f"{Fore.BLUE}Channel archive folder: {base_channel_dir}{Style.RESET_ALL}")

    metadata_path = os.path.join(base_channel_dir, f"{channel_folder}-full-history.json")
    try:
        with open(metadata_path, "w", encoding="utf-8") as meta_f:
            json.dump(channel_info, meta_f, indent=4, ensure_ascii=False)
        print(f"{Fore.GREEN}Full channel metadata saved to {metadata_path}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not save metadata file: {e}{Style.RESET_ALL}")

    log_path = os.path.join(base_channel_dir, "error_log.txt")

    if not videos:
        print(f"{Fore.YELLOW}No videos found for this channel URL.{Style.RESET_ALL}")
        return

    skipped_count = 0
    caption_count = 0
    whisper_count = 0
    error_count = 0
    checked_count = 0
    need_whisper: List[dict] = []
    # After N consecutive IP / request blocks from youtube-transcript-api, skip
    # further caption attempts for this run (Whisper path still works).
    caption_ip_block_streak = 0
    captions_disabled_this_run = False
    IP_BLOCK_STREAK_LIMIT = 3

    def _looks_like_ip_block(detail: str) -> bool:
        d = (detail or "").lower()
        return any(
            s in d
            for s in (
                "blocking requests from your ip",
                "ipblocked",
                "requestblocked",
                "too many requests",
                "cloud provider",
            )
        )

    print(
        f"\n{Fore.BLUE}Starting processing. Aiming to ensure the latest {num_videos_target} "
        f"videos are processed.{Style.RESET_ALL}"
    )

    try:
        existing_transcriptions = os.listdir(trans_dir)
    except OSError as e:
        print(
            f"{Fore.YELLOW}  - Warning: Could not list transcription directory {trans_dir}: {e}{Style.RESET_ALL}"
        )
        existing_transcriptions = []

    with open(log_path, "a", encoding="utf-8") as logf:
        logf.write(f"\n--- Processing run started at {datetime.now()} ---\n")
        logf.write(
            f"Targeting latest {num_videos_target} videos out of {total_videos_found} total.\n"
        )
        logf.write(
            f"prefer_captions={prefer_captions} whisper_fallback={whisper_fallback} "
            f"workers={max_workers} models={pool_size} caption_delay={caption_delay}\n"
        )

        # --- Phase 1: skip existing + captions (serial, rate-friendly) ---
        for idx, video in enumerate(videos):
            if checked_count >= num_videos_target:
                print(
                    f"{Fore.YELLOW}Reached target of {num_videos_target} videos checked. "
                    f"Stopping discovery.{Style.RESET_ALL}"
                )
                break

            video_id = video["id"]
            title = video.get("title", f"video_{video_id}")
            print(
                f"\n{Fore.WHITE}[{idx + 1}/{total_videos_found}] Checking video: "
                f"{title} ({video_id}){Style.RESET_ALL}"
            )

            found_existing = False
            for existing_file in existing_transcriptions:
                if video_id in existing_file and existing_file.endswith(".txt"):
                    print(
                        f"{Fore.YELLOW}  - Transcription file containing ID {video_id} already exists: "
                        f"{existing_file}. Skipping.{Style.RESET_ALL}"
                    )
                    found_existing = True
                    skipped_count += 1
                    break

            checked_count += 1
            if found_existing:
                continue

            if prefer_captions and not captions_disabled_this_run:
                _, _, _, _, txt_path = _paths_for_video(video, mp3_dir, trans_dir)
                print(f"{Fore.BLUE}  - Trying captions...{Style.RESET_ALL}")
                ok, detail = try_captions_to_file(video_id, txt_path)
                if ok:
                    print(f"{Fore.GREEN}  - Captions OK ({detail}){Style.RESET_ALL}")
                    caption_count += 1
                    caption_ip_block_streak = 0
                    existing_transcriptions.append(os.path.basename(txt_path))
                    if caption_delay > 0:
                        time.sleep(caption_delay)
                    continue
                print(f"{Fore.YELLOW}  - Captions miss: {detail}{Style.RESET_ALL}")
                logf.write(f"Captions miss {video_id}: {detail}\n")
                if _looks_like_ip_block(detail):
                    caption_ip_block_streak += 1
                    if caption_ip_block_streak >= IP_BLOCK_STREAK_LIMIT:
                        captions_disabled_this_run = True
                        msg = (
                            f"Caption API IP-blocked {caption_ip_block_streak}x in a row — "
                            f"skipping further caption attempts this run; Whisper fallback."
                        )
                        print(f"{Fore.MAGENTA}{msg}{Style.RESET_ALL}")
                        logf.write(msg + "\n")
                else:
                    caption_ip_block_streak = 0
                if caption_delay > 0 and not captions_disabled_this_run:
                    time.sleep(caption_delay)
                if not whisper_fallback:
                    error_count += 1
                    logf.write(f"No captions and Whisper disabled: {video_id}\n")
                    continue
                need_whisper.append(video)
            else:
                if prefer_captions and captions_disabled_this_run:
                    print(
                        f"{Fore.YELLOW}  - Captions skipped (API blocked this run) "
                        f"→ Whisper queue{Style.RESET_ALL}"
                    )
                need_whisper.append(video)

        # --- Phase 2: Whisper for remaining ---
        futures = []
        if need_whisper and whisper_fallback:
            print(
                f"\n{Fore.MAGENTA}Loading {pool_size} instance(s) of Whisper '{model_name}' "
                f"for {len(need_whisper)} video(s)...{Style.RESET_ALL}"
            )
            try:
                model_pool = ModelPool(model_name, pool_size)
            except Exception as e:
                print(f"{Fore.RED}Error initializing model pool: {e}{Style.RESET_ALL}")
                logf.write(f"Model pool init failed: {e}\n")
                error_count += len(need_whisper)
                need_whisper = []
                model_pool = None

            if model_pool is not None:
                print(
                    f"{Fore.BLUE}--- Submitting {len(need_whisper)} Whisper tasks "
                    f"(up to {max_workers} workers)... ---{Style.RESET_ALL}"
                )
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    for video in need_whisper:
                        futures.append(
                            executor.submit(
                                process_whisper_only_task,
                                video,
                                mp3_dir,
                                trans_dir,
                                logf,
                                model_pool,
                                None,
                            )
                        )
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            status, _message = future.result()
                            if status == "whisper":
                                whisper_count += 1
                            elif status == "captions":
                                caption_count += 1
                            elif status == "error":
                                error_count += 1
                        except Exception as exc:
                            error_count += 1
                            print(
                                f"{Fore.RED + Style.BRIGHT}A task generated an exception: "
                                f"{exc}{Style.RESET_ALL}"
                            )
                            logf.write(f"A task generated an exception: {exc}\n")
        elif need_whisper and not whisper_fallback:
            error_count += len(need_whisper)

    print(f"\n{Fore.GREEN + Style.BRIGHT}Batch processing summary:{Style.RESET_ALL}")
    print(
        f"{Fore.WHITE} - Videos checked (up to target): "
        f"{min(checked_count, num_videos_target)}/{num_videos_target}{Style.RESET_ALL}"
    )
    print(
        f"{Fore.WHITE} - New via captions: {caption_count}{Style.RESET_ALL}"
    )
    print(
        f"{Fore.WHITE} - New via Whisper: {whisper_count}{Style.RESET_ALL}"
    )
    print(
        f"{Fore.GREEN} - New videos successfully processed: "
        f"{caption_count + whisper_count}{Style.RESET_ALL}"
    )
    print(
        f"{Fore.YELLOW} - Videos skipped (already existed within target): {skipped_count}{Style.RESET_ALL}"
    )
    print(f"{Fore.RED + Style.BRIGHT} - Errors during processing: {error_count}{Style.RESET_ALL}")
    print(f"{Fore.WHITE} - Detailed errors (if any) are logged in {log_path}{Style.RESET_ALL}")
