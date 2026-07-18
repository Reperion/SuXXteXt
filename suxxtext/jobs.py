"""High-level archive jobs: single video, channel batch, history JSON."""

from __future__ import annotations

import concurrent.futures
import json
import os
from datetime import datetime
from typing import Any, Optional

from colorama import Fore, Style

from suxxtext.paths import (
    ensure_channel_dirs,
    resolve_channel_folder,
    sanitize_filename,
    transcript_exists_for_id,
)
from suxxtext.prompting import prompt
from suxxtext.whisper_runtime import ModelPool, transcribe_audio
from suxxtext.youtube import (
    download_audio,
    download_lowres_video,
    extract_video_info,
    get_channel_videos,
)


def process_video_task(
    video_info: dict,
    mp3_dir: str,
    trans_dir: str,
    logf: Any,
    model_pool: ModelPool,
    lock=None,
):
    """Download + transcribe one video (batch worker)."""
    _ = lock
    video_id = video_info["id"]
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    title = video_info.get("title", f"video_{video_id}")
    view_count = video_info.get("view_count", 0)

    sanitized_title = sanitize_filename(title, 50)
    view_count_str = f"{view_count}views" if view_count is not None else "UnknownViews"
    base_filename = f"{sanitized_title}_{view_count_str}_{video_id}"
    mp3_path = os.path.join(mp3_dir, f"{base_filename}.m4a")
    txt_path = os.path.join(trans_dir, f"{base_filename}.txt")

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

    print(f"{Fore.WHITE}[{video_id}] Transcribing audio...{Style.RESET_ALL}")
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

    print(f"{Fore.GREEN}[{video_id}] Transcription saved to {txt_path}{Style.RESET_ALL}")
    return "success", f"Successfully processed {title} ({video_id})"


def process_single_video(
    url: Optional[str] = None,
    model: Optional[str] = None,
    download_video: Optional[bool] = None,
):
    """Process one video. None args → interactive prompts."""
    if url is None:
        youtube_url = prompt(f"{Fore.CYAN}Enter YouTube video URL: {Style.RESET_ALL}")
    else:
        youtube_url = url

    if model is None:
        model_name = prompt(
            f"{Fore.CYAN}Enter Whisper model name (tiny, base, small, medium, large) [base]: {Style.RESET_ALL}",
            default="base",
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
        choice = prompt(
            f"{Fore.CYAN}Download low-resolution video as well? (yes/no) [default: no]: {Style.RESET_ALL}",
            default="no",
        ).lower()
        should_download_video = choice in ("y", "yes")
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

    print(f"{Fore.BLUE}Downloading audio to {mp3_path} ...{Style.RESET_ALL}")
    ok, err = download_audio(youtube_url, mp3_path)
    if not ok:
        print(f"{Fore.RED + Style.BRIGHT}Error downloading audio: {err}{Style.RESET_ALL}")
        return

    print(f"{Fore.BLUE}Transcribing audio...{Style.RESET_ALL}")
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
        channel_url = prompt(f"{Fore.CYAN}Enter YouTube channel URL: {Style.RESET_ALL}")
    else:
        channel_url = url

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
):
    """Batch process latest N channel videos. None args → interactive prompts."""
    model_name = model or "base"

    if url is None:
        print(
            f"{Fore.YELLOW}NOTE: The channel URL should be in this format: "
            f"https://www.youtube.com/@channelname/videos{Style.RESET_ALL}"
        )
        channel_url = prompt(f"{Fore.CYAN}Enter YouTube channel URL: {Style.RESET_ALL}")
    else:
        channel_url = url

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
        default_n = min(10, total_videos_found)
        num_videos_str = prompt(
            f"{Fore.CYAN}How many of the latest videos do you want to ensure are processed "
            f"(enter 'all' or a number)? [default {default_n}]: {Style.RESET_ALL}",
            default=str(default_n),
        )
        if num_videos_str.lower() == "all":
            num_videos_target = total_videos_found
            print(f"{Fore.BLUE}Processing all {total_videos_found} videos.{Style.RESET_ALL}")
        else:
            try:
                num_videos_target = int(num_videos_str)
                if num_videos_target > total_videos_found:
                    print(
                        f"{Fore.YELLOW}Requested number ({num_videos_target}) is more than found "
                        f"({total_videos_found}). Processing all {total_videos_found} videos.{Style.RESET_ALL}"
                    )
                    num_videos_target = total_videos_found
                elif num_videos_target <= 0:
                    print(
                        f"{Fore.RED + Style.BRIGHT}Number of videos must be positive. Exiting.{Style.RESET_ALL}"
                    )
                    return
            except ValueError:
                print(
                    f"{Fore.YELLOW}Invalid input. Using default of {min(10, total_videos_found)}.{Style.RESET_ALL}"
                )
                num_videos_target = min(10, total_videos_found)
    else:
        if str(limit).lower() == "all":
            num_videos_target = total_videos_found
        else:
            num_videos_target = int(limit)
            if num_videos_target > total_videos_found:
                num_videos_target = total_videos_found
        print(f"{Fore.BLUE}Processing {num_videos_target} videos.{Style.RESET_ALL}")

    if workers is None:
        concurrency_str = prompt(
            f"{Fore.CYAN}Enter the number of videos to process concurrently [default 4, max 32]: {Style.RESET_ALL}",
            default="4",
        )
        try:
            max_workers = int(concurrency_str)
            if max_workers <= 0:
                max_workers = 4
            elif max_workers > 32:
                max_workers = 32
            print(f"{Fore.BLUE}Using {max_workers} concurrent workers.{Style.RESET_ALL}")
        except ValueError:
            max_workers = 4
            print(f"{Fore.YELLOW}Invalid number. Using default of 4.{Style.RESET_ALL}")
    else:
        max_workers = min(max(1, int(workers)), 32)
        print(f"{Fore.BLUE}Using {max_workers} concurrent workers.{Style.RESET_ALL}")

    # Safer GPU default: 1 model unless user overrides (downloads still concurrent)
    if model_instances is None:
        model_count_str = prompt(
            f"{Fore.CYAN}Enter number of model instances to load [default 1]: {Style.RESET_ALL}",
            default="1",
        )
        try:
            pool_size = int(model_count_str)
        except ValueError:
            pool_size = 1
    else:
        pool_size = max(1, int(model_instances))

    print(f"{Fore.BLUE}Using {pool_size} parallel model instances.{Style.RESET_ALL}")

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

    processed_count = 0
    skipped_count = 0
    error_count = 0
    futures = []
    checked_count = 0

    print(
        f"\n{Fore.BLUE}Starting processing. Aiming to ensure the latest {num_videos_target} "
        f"videos are processed using up to {max_workers} workers.{Style.RESET_ALL}"
    )

    print(
        f"{Fore.MAGENTA}Loading {pool_size} instances of Whisper model '{model_name}'...{Style.RESET_ALL}"
    )
    try:
        model_pool = ModelPool(model_name, pool_size)
    except Exception as e:
        print(f"{Fore.RED}Error initializing model pool: {e}{Style.RESET_ALL}")
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        with open(log_path, "a", encoding="utf-8") as logf:
            logf.write(f"\n--- Processing run started at {datetime.now()} ---\n")
            logf.write(
                f"Targeting latest {num_videos_target} videos out of {total_videos_found} total.\n"
            )
            logf.write(f"Using up to {max_workers} concurrent workers, {pool_size} models.\n")

            try:
                existing_transcriptions = os.listdir(trans_dir)
            except OSError as e:
                print(
                    f"{Fore.YELLOW}  - Warning: Could not list transcription directory {trans_dir}: {e}{Style.RESET_ALL}"
                )
                logf.write(f"Warning: Could not list transcription directory {trans_dir}: {e}\n")
                existing_transcriptions = []

            for idx, video in enumerate(videos):
                if checked_count >= num_videos_target:
                    print(
                        f"{Fore.YELLOW}Reached target of {num_videos_target} videos checked. "
                        f"No more tasks will be submitted.{Style.RESET_ALL}"
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

                print(f"{Fore.BLUE}  - Submitting task for video {video_id}...{Style.RESET_ALL}")
                future = executor.submit(
                    process_video_task, video, mp3_dir, trans_dir, logf, model_pool, None
                )
                futures.append(future)

            print(
                f"\n{Fore.BLUE}--- Submitted {len(futures)} tasks for processing. "
                f"Waiting for completion... ---{Style.RESET_ALL}"
            )

            for future in concurrent.futures.as_completed(futures):
                try:
                    status, _message = future.result()
                    if status == "success":
                        processed_count += 1
                    elif status == "error":
                        error_count += 1
                except Exception as exc:
                    error_count += 1
                    print(
                        f"{Fore.RED + Style.BRIGHT}A task generated an exception: {exc}{Style.RESET_ALL}"
                    )
                    logf.write(f"A task generated an exception: {exc}\n")

    print(f"\n{Fore.GREEN + Style.BRIGHT}Batch processing summary:{Style.RESET_ALL}")
    print(
        f"{Fore.WHITE} - Videos checked (up to target): "
        f"{min(checked_count, num_videos_target)}/{num_videos_target}{Style.RESET_ALL}"
    )
    print(
        f"{Fore.WHITE} - Tasks submitted (new videos within target): {len(futures)}{Style.RESET_ALL}"
    )
    print(f"{Fore.GREEN} - New videos successfully processed: {processed_count}{Style.RESET_ALL}")
    print(
        f"{Fore.YELLOW} - Videos skipped (already existed within target): {skipped_count}{Style.RESET_ALL}"
    )
    print(f"{Fore.RED + Style.BRIGHT} - Errors during processing: {error_count}{Style.RESET_ALL}")
    print(f"{Fore.WHITE} - Detailed errors (if any) are logged in {log_path}{Style.RESET_ALL}")
