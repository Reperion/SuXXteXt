import subprocess
from faster_whisper import WhisperModel
import os
import re
from datetime import datetime
import concurrent.futures # Added for parallel processing
import time # Added for potential delays
import colorama
from colorama import Fore, Style
import json # Moved to global scope
import argparse # Added for CLI argument support
import threading # Added for transcription lock
import queue # Added for ModelPool
import contextlib # Added for ModelPool context manager

colorama.init(autoreset=True)

CHANNELS_ROOT = "channels"


def print_header_and_clear():
    os.system('cls' if os.name == 'nt' else 'clear') # Clear the terminal
    ascii_art = """
███████╗██╗   ██╗██╗  ██╗██╗  ██╗████████╗███████╗██╗  ██╗████████╗
██╔════╝██║   ██║╚██╗██╔╝╚██╗██╔╝╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝
███████╗██║   ██║ ╚███╔╝  ╚███╔╝    ██║   █████╗   ╚███╔╝    ██║   
╚════██║██║   ██║ ██╔██╗  ██╔██╗    ██║   ██╔══╝   ██╔██╗    ██║   
███████║╚██████╔╝██╔╝ ██╗██╔╝ ██╗   ██║   ███████╗██╔╝ ██╗   ██║   
╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   ╚═╝   
  ### Extract Text From Any Video Source including YouTube ###
"""
    print(f"{Fore.GREEN + Style.BRIGHT}{ascii_art}{Style.RESET_ALL}")

def print_subtext():
    subtext = f"""
{Fore.GREEN}SuXXTeXt extracts audio/video from YouTube videos and transcribes them to text using Whisper.
Process single videos or batch process any number videos from a channel.
Files are organized into 'channels/[ChannelHandle]/mp3' and './transcriptions'.
Download full channel history as json file.

Choose an option to proceed:
{Style.RESET_ALL}"""
    print(subtext)


def get_whisper_runtime():
    """Prefer CUDA + float16 when available; fall back to CPU int8."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def load_whisper_model(model_name):
    device, compute_type = get_whisper_runtime()
    print(f"{Fore.MAGENTA}Loading Whisper '{model_name}' on {device} ({compute_type})...{Style.RESET_ALL}")
    return WhisperModel(model_name, device=device, compute_type=compute_type)


class ModelPool:
    def __init__(self, model_name, pool_size):
        self.pool = queue.Queue()
        self.pool_size = pool_size
        self.device, self.compute_type = get_whisper_runtime()
        print(
            f"{Fore.MAGENTA}Initializing Model Pool: {pool_size} x '{model_name}' "
            f"on {self.device} ({self.compute_type})...{Style.RESET_ALL}"
        )
        for i in range(pool_size):
            try:
                model = WhisperModel(
                    model_name, device=self.device, compute_type=self.compute_type
                )
                self.pool.put(model)
                print(f"{Fore.MAGENTA}  - Loaded model instance {i+1}/{pool_size}{Style.RESET_ALL}")
            except Exception as e:
                # CUDA OOM / missing kernels: fall back to CPU for remaining loads
                if self.device != "cpu":
                    print(
                        f"{Fore.YELLOW}GPU load failed ({e}); falling back to CPU int8 "
                        f"for remaining instances...{Style.RESET_ALL}"
                    )
                    self.device, self.compute_type = "cpu", "int8"
                    try:
                        model = WhisperModel(
                            model_name, device=self.device, compute_type=self.compute_type
                        )
                        self.pool.put(model)
                        print(f"{Fore.MAGENTA}  - Loaded model instance {i+1}/{pool_size} on CPU{Style.RESET_ALL}")
                        continue
                    except Exception as e2:
                        print(f"{Fore.RED}Error loading model instance {i+1}: {e2}{Style.RESET_ALL}")
                        raise e2
                print(f"{Fore.RED}Error loading model instance {i+1}: {e}{Style.RESET_ALL}")
                raise e

    @contextlib.contextmanager
    def get_model(self):
        model = self.pool.get()
        try:
            yield model
        finally:
            self.pool.put(model)


def sanitize_filename(name, max_length=50):
    # Remove/replace problematic characters and truncate
    keepchars = (" ", ".", "_", "-")
    sanitized = "".join(c if c.isalnum() or c in keepchars else "_" for c in name)
    sanitized = sanitized.strip().replace(" ", "_")
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    return sanitized


def _alnum_key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _alnum_related(a, b):
    """True if alnum keys are the same, one contains the other, or short is a subsequence of long.

    Subsequence helps title folders (DrEricBergDC) match handle folders (Drberg).
    """
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 6:
        return False
    it = iter(long)
    return all(ch in it for ch in short)


def channel_handle_from_url(url):
    """Extract @handle (or last path segment) from a YouTube channel/video page URL."""
    if not url:
        return None
    url = url.strip()
    m = re.search(r"youtube\.com/@([^/?#]+)", url, re.I)
    if m:
        return m.group(1)
    # strip common tabs
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
    # channel/UCxxxx — use id only as last resort (not a nice folder name)
    if part.startswith("UC") and len(part) >= 22:
        return part
    if part and "youtube" not in part.lower() and part not in ("www.youtube.com", "channel", "c", "user"):
        # /c/Name or bare handle path
        if not part.startswith("UC"):
            return part
    return None


def channel_handle_from_info(info):
    """Prefer @handle from metadata URLs over display title."""
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


def resolve_channel_folder(info=None, channel_url=None, channels_root=CHANNELS_ROOT):
    """
    Canonical channel archive folder under channels/.

    Prefers @handle (matches batch mode + existing archives). Reuses an existing
    directory on case-insensitive or alnum-normalized match so single-video runs
    do not spawn parallel trees (e.g. Dr._Eric_Berg_DC vs Drberg).
    """
    handle = None
    if channel_url:
        handle = channel_handle_from_url(channel_url)
    if not handle and info:
        handle = channel_handle_from_info(info)

    display = None
    if info:
        display = info.get("channel") or info.get("uploader") or info.get("title")

    candidates = []
    if handle:
        candidates.append(sanitize_filename(handle, 50))
    if display:
        d = sanitize_filename(display, 50)
        # strip trailing " - Videos" etc. from channel listing titles
        d = re.sub(r"_-_Videos$", "", d)
        d = re.sub(r"_Videos$", "", d)
        if d and d not in candidates:
            candidates.append(d)

    if not candidates:
        candidates = ["channel"]

    existing = []
    if os.path.isdir(channels_root):
        existing = [
            e for e in os.listdir(channels_root)
            if os.path.isdir(os.path.join(channels_root, e))
            and ".bak" not in e.lower()
            and not e.startswith("_")
        ]

    # 1) Exact match for any candidate
    for c in candidates:
        if c in existing:
            return c

    # 2) Case-insensitive
    lower_map = {e.lower(): e for e in existing}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]

    # 3) Alnum-normalized (HubermanLabClips == Huberman_Lab_Clips)
    existing_norm = {_alnum_key(e): e for e in existing}
    for c in candidates:
        key = _alnum_key(c)
        if key and key in existing_norm:
            return existing_norm[key]

    # 4) Substring match on alnum keys (Drberg ⊂ DrEricBergDC, etc.)
    # Prefer the *shortest* existing match so we land on handle folders, not long titles.
    match_keys = list(candidates)
    if handle:
        match_keys.append(handle)
    best = None  # (len(existing_name), existing_name)
    for c in match_keys:
        ckey = _alnum_key(c)
        if not ckey or len(ckey) < 5:
            continue
        for e in existing:
            ekey = _alnum_key(e)
            if not ekey or len(ekey) < 5:
                continue
            if _alnum_related(ckey, ekey):
                cand = (len(e), e)
                if best is None or cand < best:
                    best = cand
    if best:
        return best[1]

    # 5) Prefer handle as new folder name (stable with batch/json modes)
    return candidates[0]


def ensure_channel_dirs(channel_folder, channels_root=CHANNELS_ROOT):
    base = os.path.join(channels_root, channel_folder)
    mp3_dir = os.path.join(base, "mp3")
    trans_dir = os.path.join(base, "transcriptions")
    os.makedirs(mp3_dir, exist_ok=True)
    os.makedirs(trans_dir, exist_ok=True)
    return base, mp3_dir, trans_dir


def download_audio(youtube_url, output_file):
    # Download audio from YouTube using yt-dlp
    try:
        subprocess.run([
            "yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", output_file, youtube_url
        ], check=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, str(e)


def transcribe_audio(audio_file, model_name_or_obj, output_file, lock=None):
    try:
        if isinstance(model_name_or_obj, str):
            model = load_whisper_model(model_name_or_obj)
        else:
            model = model_name_or_obj
        segments, _ = model.transcribe(audio_file, beam_size=5)
        full_text = " ".join([segment.text for segment in segments])
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(full_text)
        return True, None
    except Exception as e:
        return False, str(e)

def get_channel_videos(channel_url, max_videos=10):
    # Use yt-dlp to get metadata for the channel and retrieve the most recent videos
    import yt_dlp
    # Corrected indentation for ytdlp_opts dictionary
    ytdlp_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'force_generic_extractor': False,
    }
    with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        # info['entries'] is a list of video dicts
        videos = info.get('entries', [])
        # Filter out non-video entries (sometimes channels have playlists, etc.)
        videos = [v for v in videos if v.get('ie_key', '').startswith('Youtube')]
        # Sort by upload date descending if available
        videos = sorted(videos, key=lambda v: v.get('upload_date', ''), reverse=True)
        # Return all videos, sorted by upload date (newest first)
        return videos, info

def process_single_video(url=None, model=None, download_video=None):
    """Process a single video. If arguments are None, prompt the user interactively."""
    # Get URL from argument or prompt
    if url is None:
        youtube_url = input(f"{Fore.CYAN}Enter YouTube video URL: {Style.RESET_ALL}").strip()
    else:
        youtube_url = url
    
    # Get model from argument or prompt
    if model is None:
        model_name = input(f"{Fore.CYAN}Enter Whisper model name (tiny, base, small, medium, large) [base]: {Style.RESET_ALL}").strip() or "base"
    else:
        model_name = model
    
    # Get video info
    print(f"{Fore.BLUE}Getting video info...{Style.RESET_ALL}")
    import yt_dlp
    ytdlp_opts = {'skip_download': True, 'quiet': True}
    with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        title = info.get('title', 'video')
        video_id = info.get('id', 'unknown')
        channel_folder = resolve_channel_folder(info=info)
    base_channel_dir, mp3_dir, trans_dir = ensure_channel_dirs(channel_folder)
    print(f"{Fore.BLUE}Channel archive folder: {base_channel_dir}{Style.RESET_ALL}")

    # Filenames include video_id so batch skip logic (id in .txt name) works for singles too
    sanitized_title = sanitize_filename(title, 50)
    mp3_filename = f"{sanitized_title}_{video_id}.m4a"
    mp3_path = os.path.join(mp3_dir, mp3_filename)
    now = datetime.now()
    date_str = now.strftime("%d-%b-%Y")
    txt_filename = f"{date_str}-{sanitized_title}_{video_id}.txt"
    txt_path = os.path.abspath(os.path.join(trans_dir, txt_filename))
    print(f"{Fore.YELLOW}Saving transcript to: {txt_path}{Style.RESET_ALL}")

    # Skip if this video id was already transcribed in this channel tree
    try:
        for existing_file in os.listdir(trans_dir):
            if video_id in existing_file and existing_file.endswith(".txt"):
                print(
                    f"{Fore.YELLOW}Transcription already exists for {video_id}: "
                    f"{existing_file}. Skipping.{Style.RESET_ALL}"
                )
                return
    except OSError:
        pass
    
    # --- Optional Low-Resolution Video Download ---
    if download_video is None:
        download_video_choice = input(f"{Fore.CYAN}Download low-resolution video as well? (yes/no) [default: no]: {Style.RESET_ALL}").strip().lower()
        should_download_video = download_video_choice == 'yes'
    else:
        should_download_video = download_video
    
    if should_download_video:
        video_dir = os.path.join(base_channel_dir, "video")
        os.makedirs(video_dir, exist_ok=True)
        
        video_filename = f"{date_str}-{sanitized_title}_{video_id}.mp4"
        video_path = os.path.join(video_dir, video_filename)

        print(f"{Fore.BLUE}Downloading low-resolution video to {video_path} ...{Style.RESET_ALL}")
        try:
            subprocess.run([
                "yt-dlp",
                "-f", "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[ext=mp4]",
                "--merge-output-format", "mp4",
                "-o", video_path,
                youtube_url
            ], check=True)
            print(f"{Fore.GREEN}Low-resolution video saved to {video_path}{Style.RESET_ALL}")
        except subprocess.CalledProcessError as e:
            print(f"{Fore.RED + Style.BRIGHT}Error downloading video: {e}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED + Style.BRIGHT}An unexpected error occurred during video download: {e}{Style.RESET_ALL}")

    # Download audio
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

def download_channel_history_json(url=None):
    """Download channel history JSON. If url is None, prompt the user interactively."""
    if url is None:
        print(f"{Fore.YELLOW}NOTE: The channel URL should be in this format: https://www.youtube.com/@channelname/videos{Style.RESET_ALL}")
        channel_url = input(f"{Fore.CYAN}Enter YouTube channel URL: {Style.RESET_ALL}").strip()
    else:
        channel_url = url

    print(f"{Fore.BLUE}Retrieving all video metadata for the channel...{Style.RESET_ALL}")
    try:
        _, channel_info = get_channel_videos(channel_url) # We only need channel_info
    except Exception as e:
        print(f"{Fore.RED + Style.BRIGHT}Error retrieving channel info: {e}{Style.RESET_ALL}")
        return

    channel_folder = resolve_channel_folder(info=channel_info, channel_url=channel_url)
    base_channel_dir, _, _ = ensure_channel_dirs(channel_folder)

    metadata_filename = f"{channel_folder}-full-history.json"
    metadata_path = os.path.join(base_channel_dir, metadata_filename)

    try:
        with open(metadata_path, "w", encoding="utf-8") as meta_f:
            json.dump(channel_info, meta_f, indent=4, ensure_ascii=False)
        print(f"{Fore.GREEN}Full channel metadata saved to {metadata_path}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not save metadata file: {e}{Style.RESET_ALL}")
    
    print(f"{Fore.GREEN}Done.{Style.RESET_ALL}")

# --- Helper function for processing a single video in parallel ---
def process_video_task(video_info, mp3_dir, trans_dir, logf, model_pool, lock=None):
    """Downloads and transcribes a single video. Returns status and message."""
    video_id = video_info['id']
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    title = video_info.get('title', f"video_{video_id}")
    view_count = video_info.get('view_count', 0)

    # --- File Naming ---
    sanitized_title = sanitize_filename(title, 50)
    view_count_str = f"{view_count}views" if view_count is not None else "UnknownViews"
    base_filename = f"{sanitized_title}_{view_count_str}_{video_id}"
    mp3_filename = f"{base_filename}.m4a"
    txt_filename = f"{base_filename}.txt"
    mp3_path = os.path.join(mp3_dir, mp3_filename)
    txt_path = os.path.join(trans_dir, txt_filename)

    # --- Download Audio ---
    print(f"{Fore.WHITE}[{video_id}] Downloading audio...{Style.RESET_ALL}")
    ok, err = download_audio(video_url, mp3_path)
    if not ok:
        msg = f"Download error for {title} ({video_id}): {err}"
        print(f"{Fore.RED + Style.BRIGHT}[{video_id}] {msg}{Style.RESET_ALL}")
        logf.write(msg + "\n")
        # Clean up incomplete mp3
        if os.path.exists(mp3_path):
            try: os.remove(mp3_path)
            except OSError as remove_err: logf.write(f"  - Could not remove incomplete mp3 {mp3_path}: {remove_err}\n")
        return "error", msg

    # --- Transcribe Audio ---
    print(f"{Fore.WHITE}[{video_id}] Transcribing audio...{Style.RESET_ALL}")
    
    try:
        # Acquire a model from the pool
        with model_pool.get_model() as model:
            # No lock needed here as each model in the pool is independent and owned by this thread currently
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
    # Optional: Remove mp3 after success
    # try: os.remove(mp3_path)
    # except OSError as e: logf.write(f"Warning: Could not remove mp3 file {mp3_path}: {e}\n")

    return "success", f"Successfully processed {title} ({video_id})"

def process_channel_videos(url=None, limit=None, workers=None, model_instances=None, model=None):
    """Process channel videos. If arguments are None, prompt the user interactively."""
    model_name = model or "base"

    # Get URL from argument or prompt
    if url is None:
        print(f"{Fore.YELLOW}NOTE: The channel URL should be in this format: https://www.youtube.com/@channelname/videos{Style.RESET_ALL}")
        channel_url = input(f"{Fore.CYAN}Enter YouTube channel URL: {Style.RESET_ALL}").strip()
    else:
        channel_url = url

    print(f"{Fore.BLUE}Retrieving all video metadata for the channel (this might take a while for large channels)...{Style.RESET_ALL}")
    try:
        # Fetch ALL videos, ignore max_videos parameter here
        videos, channel_info = get_channel_videos(channel_url)
    except Exception as e:
        print(f"{Fore.RED + Style.BRIGHT}Error retrieving channel info: {e}{Style.RESET_ALL}")
        return

    total_videos_found = len(videos)
    print(f"{Fore.WHITE}Found {total_videos_found} videos in the channel.{Style.RESET_ALL}")

    # Get limit from argument or prompt
    if limit is None:
        num_videos_str = input(f"{Fore.CYAN}How many of the latest videos do you want to ensure are processed (enter 'all' or a number)? [default {min(10, total_videos_found)}]: {Style.RESET_ALL}").strip()

        if num_videos_str.lower() == 'all':
            num_videos_target = total_videos_found
            print(f"{Fore.BLUE}Processing all {total_videos_found} videos.{Style.RESET_ALL}")
        else:
            try:
                # Use default if input is empty, otherwise convert to int
                num_videos_target = int(num_videos_str) if num_videos_str else min(10, total_videos_found)
                if num_videos_target > total_videos_found:
                    print(f"{Fore.YELLOW}Requested number ({num_videos_target}) is more than found ({total_videos_found}). Processing all {total_videos_found} videos.{Style.RESET_ALL}")
                    num_videos_target = total_videos_found
                elif num_videos_target <= 0:
                     print(f"{Fore.RED + Style.BRIGHT}Number of videos must be positive. Exiting.{Style.RESET_ALL}")
                     return
            except ValueError:
                # Handle cases where input is not 'all' and not a valid number
                print(f"{Fore.YELLOW}Invalid input. Please enter 'all' or a positive number. Using default of {min(10, total_videos_found)}.{Style.RESET_ALL}")
                num_videos_target = min(10, total_videos_found)
    else:
        # Handle CLI limit argument
        if str(limit).lower() == 'all':
            num_videos_target = total_videos_found
        else:
            num_videos_target = int(limit)
            if num_videos_target > total_videos_found:
                num_videos_target = total_videos_found
        print(f"{Fore.BLUE}Processing {num_videos_target} videos.{Style.RESET_ALL}")

    # Get workers from argument or prompt
    if workers is None:
        concurrency_str = input(f"{Fore.CYAN}Enter the number of videos to process concurrently [default 8, max 32]: {Style.RESET_ALL}").strip()
        try:
            max_workers = int(concurrency_str) if concurrency_str else 8
            if max_workers <= 0:
                print(f"{Fore.YELLOW}Concurrency level must be positive. Using default of 8.{Style.RESET_ALL}")
                max_workers = 8
            elif max_workers > 32:
                print(f"{Fore.YELLOW}Concurrency level capped at 32 for stability. Using 32.{Style.RESET_ALL}")
                max_workers = 32
            else:
                 print(f"{Fore.BLUE}Using {max_workers} concurrent workers.{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.YELLOW}Invalid number for concurrency. Using default of 8.{Style.RESET_ALL}")
            max_workers = 8
    else:
        max_workers = min(max(1, int(workers)), 32)
        print(f"{Fore.BLUE}Using {max_workers} concurrent workers.{Style.RESET_ALL}")

    # Determine model pool size
    if model_instances is None:
        # Default to matching worker count if not specified via CLI, or ask user? 
        # For simplicity in interactive mode, let's default to max_workers or ask.
        # Let's ask to depend on GPU strength, but defaulting to worker count is a safe bet for high-end GPUs.
        model_count_str = input(f"{Fore.CYAN}Enter number of model instances to load [default {max_workers}]: {Style.RESET_ALL}").strip()
        try:
             pool_size = int(model_count_str) if model_count_str else max_workers
        except ValueError:
             pool_size = max_workers
    else:
        pool_size = int(model_instances)
    
    print(f"{Fore.BLUE}Using {pool_size} parallel model instances.{Style.RESET_ALL}")

    channel_folder = resolve_channel_folder(info=channel_info, channel_url=channel_url)
    base_channel_dir, mp3_dir, trans_dir = ensure_channel_dirs(channel_folder)
    print(f"{Fore.BLUE}Channel archive folder: {base_channel_dir}{Style.RESET_ALL}")

    # Save full metadata
    metadata_filename = f"{channel_folder}-full-history.json"
    metadata_path = os.path.join(base_channel_dir, metadata_filename)
    try:
        with open(metadata_path, "w", encoding="utf-8") as meta_f:
            json.dump(channel_info, meta_f, indent=4, ensure_ascii=False)
        print(f"{Fore.GREEN}Full channel metadata saved to {metadata_path}{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not save metadata file: {e}{Style.RESET_ALL}")

    log_path = os.path.join(base_channel_dir, "error_log.txt")

    if not videos:
        print(f"{Fore.YELLOW}No videos found for this channel URL.{Style.RESET_ALL}")
        # Log is handled below if needed
        return

    processed_count = 0
    skipped_count = 0
    error_count = 0

    print(f"\n{Fore.BLUE}Starting processing. Aiming to ensure the latest {num_videos_target} videos are processed using up to {max_workers} workers.{Style.RESET_ALL}")

    # --- Load Model Pool ---
    print(f"{Fore.MAGENTA}Loading {pool_size} instances of Whisper model '{model_name}'...{Style.RESET_ALL}")
    try:
        model_pool = ModelPool(model_name, pool_size)
    except Exception as e:
        print(f"{Fore.RED}Error initializing model pool: {e}{Style.RESET_ALL}")
        return

    # No longer need a global GPU lock
    gpu_lock = None

    # --- Use ThreadPoolExecutor for parallel processing ---
    # Using ThreadPoolExecutor as downloading is I/O bound, transcription might be CPU/GPU bound
    # but GIL might limit true CPU parallelism in threads for transcription part.
    # ProcessPoolExecutor could be an alternative if transcription is CPU-heavy and GIL becomes a bottleneck.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        videos_to_process_list = [] # Keep track of videos submitted

        with open(log_path, "a", encoding="utf-8") as logf: # Append to log file
            logf.write(f"\n--- Processing run started at {datetime.now()} ---\n")
            logf.write(f"Targeting latest {num_videos_target} videos out of {total_videos_found} total.\n")
            logf.write(f"Using up to {max_workers} concurrent workers.\n")

            # --- First pass: Check duplicates and submit tasks ---
            checked_count = 0
            
            # Cache the file list ONCE before the loop to avoid O(N^2) performance hit
            try:
                existing_transcriptions = os.listdir(trans_dir)
            except OSError as e:
                print(f"{Fore.YELLOW}  - Warning: Could not list transcription directory {trans_dir}: {e}{Style.RESET_ALL}")
                logf.write(f"Warning: Could not list transcription directory {trans_dir}: {e}\n")
                existing_transcriptions = []

            for idx, video in enumerate(videos):
                if checked_count >= num_videos_target:
                    print(f"{Fore.YELLOW}Reached target of {num_videos_target} videos checked. No more tasks will be submitted.{Style.RESET_ALL}")
                    break

                video_id = video['id']
                title = video.get('title', f"video_{video_id}")
                print(f"\n{Fore.WHITE}[{idx+1}/{total_videos_found}] Checking video: {title} ({video_id}){Style.RESET_ALL}")

                # --- Duplicate Check ---
                found_existing = False
                for existing_file in existing_transcriptions:
                    if video_id in existing_file and existing_file.endswith(".txt"):
                        print(f"{Fore.YELLOW}  - Transcription file containing ID {video_id} already exists: {existing_file}. Skipping.{Style.RESET_ALL}")
                        found_existing = True
                        skipped_count += 1
                        break

                checked_count += 1 # Increment checked count regardless of skip

                if found_existing:
                    continue # Skip to the next video

                # --- Submit task to executor ---
                print(f"{Fore.BLUE}  - Submitting task for video {video_id}...{Style.RESET_ALL}")
                # Pass necessary info to the task function
                future = executor.submit(process_video_task, video, mp3_dir, trans_dir, logf, model_pool, gpu_lock)
                futures.append(future)
                videos_to_process_list.append(video_id) # Track submitted video

                # Optional: Add a small delay between submissions to be less aggressive
                # time.sleep(0.1)

            print(f"\n{Fore.BLUE}--- Submitted {len(futures)} tasks for processing. Waiting for completion... ---{Style.RESET_ALL}")

            # --- Process completed futures ---
            for future in concurrent.futures.as_completed(futures):
                try:
                    status, message = future.result()
                    if status == "success":
                        processed_count += 1
                    elif status == "error":
                        error_count += 1
                    # Message already printed/logged within the task functionyes
                except Exception as exc:
                    # Handle exceptions raised within the task itself
                    error_count += 1
                    # Attempt to find which video failed from the list (less reliable)
                    # This part is tricky as the future doesn't directly hold the video_id
                    print(f'{Fore.RED + Style.BRIGHT}A task generated an exception: {exc}{Style.RESET_ALL}')
                    logf.write(f"A task generated an exception: {exc}\n")


    print(f"\n{Fore.GREEN + Style.BRIGHT}Batch processing summary:{Style.RESET_ALL}")
    # Note: checked_count includes skipped videos up to the target number
    print(f"{Fore.WHITE} - Videos checked (up to target): {min(checked_count, num_videos_target)}/{num_videos_target}{Style.RESET_ALL}")
    print(f"{Fore.WHITE} - Tasks submitted (new videos within target): {len(futures)}{Style.RESET_ALL}")
    print(f"{Fore.GREEN} - New videos successfully processed: {processed_count}{Style.RESET_ALL}")
    # skipped_count is calculated during the initial check phase
    print(f"{Fore.YELLOW} - Videos skipped (already existed within target): {skipped_count}{Style.RESET_ALL}")
    print(f"{Fore.RED + Style.BRIGHT} - Errors during processing: {error_count}{Style.RESET_ALL}")
    print(f"{Fore.WHITE} - Detailed errors (if any) are logged in {log_path}{Style.RESET_ALL}")

def main():
    # --- CLI Argument Parsing ---
    parser = argparse.ArgumentParser(
        description="SuXXTeXt - YouTube Transcriber & Channel Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (no arguments):
  python transcribe2.py

  # Transcribe a single video:
  python transcribe2.py --mode single --url "https://www.youtube.com/watch?v=VIDEO_ID"

  # Transcribe with specific model and download video:
  python transcribe2.py --mode single --url "URL" --model small --video

  # Batch process latest 5 videos from a channel:
  python transcribe2.py --mode batch --url "https://www.youtube.com/@channelname/videos" --limit 5

  # Download channel history JSON only:
  python transcribe2.py --mode json --url "https://www.youtube.com/@channelname/videos"

  # Generate statistics:
  python transcribe2.py --mode stats
        """
    )
    parser.add_argument('-m', '--mode', 
                        choices=['single', 'batch', 'json', 'stats'],
                        help='Operation mode: single (transcribe one video), batch (process channel), json (download history), stats (generate statistics)')
    parser.add_argument('-u', '--url', 
                        help='YouTube video or channel URL')
    parser.add_argument('--model', 
                        default='base',
                        help='Whisper model name (tiny, base, small, medium, large). Default: base')
    parser.add_argument('--video', 
                        action='store_true',
                        help='Also download low-resolution video (only for single mode)')
    parser.add_argument('--limit', 
                        help='Number of videos to process (or "all") for batch mode. Default: 10')
    parser.add_argument('--workers', 
                        type=int, 
                        default=8,
                        help='Number of concurrent workers for batch mode (1-32). Default: 8')
    parser.add_argument('--model_instances',
                        type=int,
                        help='Number of model instances to load. Defaults to matching worker count.')

    args = parser.parse_args()

    # --- Route based on CLI arguments ---
    if args.mode:
        # CLI mode - run the specified operation and exit
        if args.mode == 'single':
            if not args.url:
                print(f"{Fore.RED + Style.BRIGHT}Error: --url is required for single mode{Style.RESET_ALL}")
                return
            process_single_video(url=args.url, model=args.model, download_video=args.video)
        elif args.mode == 'batch':
            if not args.url:
                print(f"{Fore.RED + Style.BRIGHT}Error: --url is required for batch mode{Style.RESET_ALL}")
                return
            process_channel_videos(
                url=args.url,
                limit=args.limit,
                workers=args.workers,
                model_instances=args.model_instances,
                model=args.model,
            )
        elif args.mode == 'json':
            if not args.url:
                print(f"{Fore.RED + Style.BRIGHT}Error: --url is required for json mode{Style.RESET_ALL}")
                return
            download_channel_history_json(url=args.url)
        elif args.mode == 'stats':
            print(f"{Fore.BLUE}Switched to Statistics Module{Style.RESET_ALL}")
            try:
                subprocess.run(["python3", "yt_channel_analyzer.py"], check=True)
            except subprocess.CalledProcessError as e:
                print(f"{Fore.RED + Style.BRIGHT}Error generating statistics: {e}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}Statistics generation finished.{Style.RESET_ALL}")
        return  # Exit after CLI operation

    # --- Interactive mode (no arguments provided) ---
    while True:
        print_header_and_clear()
        print_subtext() # This now includes the "Choose an option" part

        print(f"{Fore.WHITE + Style.BRIGHT}1. Transcribe a single YouTube video (and optionally download video){Style.RESET_ALL}")
        print(f"{Fore.WHITE + Style.BRIGHT}2. Transcribe a batch of the latest videos from a YouTube channel{Style.RESET_ALL}")
        print(f"{Fore.WHITE + Style.BRIGHT}3. Download Channel Video History (JSON only){Style.RESET_ALL}")
        print(f"{Fore.WHITE + Style.BRIGHT}4. Generate Statistics (from existing JSON history){Style.RESET_ALL}")
        print(f"{Fore.WHITE + Style.BRIGHT}0. Exit{Style.RESET_ALL}") # Added exit option
        choice = input(f"{Fore.CYAN}Choose an option (0, 1, 2, 3, or 4): {Style.RESET_ALL}").strip()

        if choice == "1":
            process_single_video()
        elif choice == "2":
            process_channel_videos()
        elif choice == "3":
            download_channel_history_json()
        elif choice == "4":
            print(f"{Fore.BLUE}Switched to Statistics Module{Style.RESET_ALL}")
            try:
                subprocess.run(["python3", "yt_channel_analyzer.py"], check=True)
            except subprocess.CalledProcessError as e:
                print(f"{Fore.RED + Style.BRIGHT}Error generating statistics: {e}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}Statistics generation finished.{Style.RESET_ALL}")
            time.sleep(5) # Pause for 5 seconds
        elif choice == "0": # Handle exit option
            print(f"{Fore.GREEN}Exiting. Goodbye!{Style.RESET_ALL}")
            break
        else:
            print(f"{Fore.RED + Style.BRIGHT}Invalid choice. Please try again.{Style.RESET_ALL}")
            time.sleep(2) # Short pause for invalid choice message

if __name__ == "__main__":
    main()
