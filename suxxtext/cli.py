"""SuXXTeXt CLI — interactive menu + non-interactive modes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Optional

from colorama import Fore, Style, init as colorama_init

from suxxtext.jobs import (
    DEFAULT_MODEL_INSTANCES,
    DEFAULT_WORKERS,
    download_channel_history_json,
    process_channel_videos,
    process_single_video,
)

colorama_init(autoreset=True)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def print_header_and_clear():
    os.system("cls" if os.name == "nt" else "clear")
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
    print(
        f"""
{Fore.GREEN}SuXXTeXt extracts YouTube text: captions first (fast), Whisper fallback (GPU).
Batch uses gentle defaults ({DEFAULT_WORKERS} workers / {DEFAULT_MODEL_INSTANCES} Whisper models).
Files land in channels/[ChannelHandle]/{{mp3,transcriptions,summaries}}.

Choose an option to proceed:
{Style.RESET_ALL}"""
    )


def run_stats():
    print(f"{Fore.BLUE}Switched to Statistics Module{Style.RESET_ALL}")
    analyzer = os.path.join(PROJECT_ROOT, "yt_channel_analyzer.py")
    try:
        subprocess.run([sys.executable, analyzer], check=True, cwd=PROJECT_ROOT)
    except subprocess.CalledProcessError as e:
        print(f"{Fore.RED + Style.BRIGHT}Error generating statistics: {e}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Statistics generation finished.{Style.RESET_ALL}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SuXXTeXt - YouTube Transcriber & Channel Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Interactive mode (no arguments):
  python -m suxxtext

  # Single video (captions first, Whisper on miss):
  python -m suxxtext --mode single --url "https://www.youtube.com/watch?v=VIDEO_ID"

  # Batch latest N — captions first, then Whisper; gentle throttle:
  python -m suxxtext --mode batch --url "https://www.youtube.com/@channelname/videos" --limit 50
  python -m suxxtext --mode batch --channel "@Drberg" --limit 512

  # Force Whisper only (skip caption attempt):
  python -m suxxtext --mode batch --channel "@Drberg" --limit 10 --whisper-only

  # Captions only (no download/Whisper):
  python -m suxxtext --mode batch --channel "@Drberg" --limit 50 --no-whisper-fallback

  Defaults: --workers {DEFAULT_WORKERS} --model_instances {DEFAULT_MODEL_INSTANCES}
  See docs/ops-channel-batch.md
        """,
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["single", "batch", "json", "stats"],
        help="Operation mode: single, batch, json, stats",
    )
    parser.add_argument("-u", "--url", help="YouTube video or channel URL")
    parser.add_argument(
        "--channel",
        help="Channel @handle or URL (batch/json alias for --url)",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper model name (tiny, base, small, medium, large). Default: base",
    )
    parser.add_argument(
        "--video",
        action="store_true",
        help="Also download low-resolution video (single mode only)",
    )
    parser.add_argument(
        "--limit",
        help='Number of videos to process (or "all") for batch mode. Default: 10',
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent Whisper workers for batch (1-32). Default: {DEFAULT_WORKERS}",
    )
    parser.add_argument(
        "--model_instances",
        type=int,
        default=DEFAULT_MODEL_INSTANCES,
        help=(
            f"Whisper model instances to load for batch. "
            f"Default: {DEFAULT_MODEL_INSTANCES} (gentle GPU throttle)"
        ),
    )
    parser.add_argument(
        "--whisper-only",
        action="store_true",
        help="Skip captions; always download audio + Whisper",
    )
    parser.add_argument(
        "--no-whisper-fallback",
        action="store_true",
        help="Do not use Whisper when captions are missing (captions-only)",
    )
    parser.add_argument(
        "--caption-delay",
        type=float,
        default=0.5,
        help="Seconds between caption requests in batch (default 0.5)",
    )
    return parser


def _resolve_url(args) -> Optional[str]:
    return args.url or args.channel


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    prefer_captions = not args.whisper_only
    whisper_fallback = not args.no_whisper_fallback
    if args.whisper_only and args.no_whisper_fallback:
        print(
            f"{Fore.RED + Style.BRIGHT}Error: --whisper-only and "
            f"--no-whisper-fallback conflict{Style.RESET_ALL}"
        )
        return 1

    if args.mode:
        target = _resolve_url(args)
        if args.mode == "single":
            if not target:
                print(
                    f"{Fore.RED + Style.BRIGHT}Error: --url is required for single mode{Style.RESET_ALL}"
                )
                return 1
            process_single_video(
                url=target,
                model=args.model,
                download_video=args.video,
                prefer_captions=prefer_captions,
                whisper_fallback=whisper_fallback,
            )
        elif args.mode == "batch":
            if not target:
                print(
                    f"{Fore.RED + Style.BRIGHT}Error: --url or --channel is required "
                    f"for batch mode{Style.RESET_ALL}"
                )
                return 1
            process_channel_videos(
                url=target,
                limit=args.limit,
                workers=args.workers,
                model_instances=args.model_instances,
                model=args.model,
                prefer_captions=prefer_captions,
                whisper_fallback=whisper_fallback,
                caption_delay=args.caption_delay,
            )
        elif args.mode == "json":
            if not target:
                print(
                    f"{Fore.RED + Style.BRIGHT}Error: --url or --channel is required "
                    f"for json mode{Style.RESET_ALL}"
                )
                return 1
            download_channel_history_json(url=target)
        elif args.mode == "stats":
            run_stats()
        return 0

    # Interactive loop — paste a channel link and go
    while True:
        print_header_and_clear()
        print_subtext()
        print(
            f"{Fore.WHITE + Style.BRIGHT}1. Single video "
            f"(captions first → Whisper fallback){Style.RESET_ALL}"
        )
        print(
            f"{Fore.WHITE + Style.BRIGHT}2. Batch latest channel videos "
            f"(captions first → Whisper; {DEFAULT_WORKERS}w/{DEFAULT_MODEL_INSTANCES}m){Style.RESET_ALL}"
        )
        print(
            f"{Fore.WHITE + Style.BRIGHT}3. Download Channel Video History (JSON only){Style.RESET_ALL}"
        )
        print(
            f"{Fore.WHITE + Style.BRIGHT}4. Generate Statistics (from existing JSON history){Style.RESET_ALL}"
        )
        print(f"{Fore.WHITE + Style.BRIGHT}0. Exit{Style.RESET_ALL}")
        choice = input(
            f"{Fore.CYAN}Choose an option (0, 1, 2, 3, or 4): {Style.RESET_ALL}"
        ).strip()

        if choice == "1":
            process_single_video()
        elif choice == "2":
            process_channel_videos()
        elif choice == "3":
            download_channel_history_json()
        elif choice == "4":
            run_stats()
            time.sleep(5)
        elif choice == "0":
            print(f"{Fore.GREEN}Exiting. Goodbye!{Style.RESET_ALL}")
            break
        else:
            print(f"{Fore.RED + Style.BRIGHT}Invalid choice. Please try again.{Style.RESET_ALL}")
            time.sleep(2)
    return 0
