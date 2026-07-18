"""SuXXTeXt CLI — interactive menu + non-interactive modes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

from colorama import Fore, Style, init as colorama_init

from suxxtext.jobs import (
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
{Fore.GREEN}SuXXTeXt extracts audio/video from YouTube videos and transcribes them to text using Whisper.
Process single videos or batch process any number of videos from a channel.
Files are organized into 'channels/[ChannelHandle]/mp3' and 'transcriptions'.
Download full channel history as json file.

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
        epilog="""
Examples:
  # Interactive mode (no arguments):
  python -m suxxtext
  python transcribe2.py
  ./run.sh

  # Transcribe a single video:
  python -m suxxtext --mode single --url "https://www.youtube.com/watch?v=VIDEO_ID"

  # Batch process latest 5 videos from a channel:
  python -m suxxtext --mode batch --url "https://www.youtube.com/@channelname/videos" --limit 5

  # Download channel history JSON only:
  python -m suxxtext --mode json --url "https://www.youtube.com/@channelname/videos"

  # Generate statistics:
  python -m suxxtext --mode stats
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
        default=4,
        help="Concurrent workers for batch mode (1-32). Default: 4",
    )
    parser.add_argument(
        "--model_instances",
        type=int,
        default=None,
        help="Whisper model instances to load. Default: 1 (safer for GPU VRAM)",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.mode:
        if args.mode == "single":
            if not args.url:
                print(
                    f"{Fore.RED + Style.BRIGHT}Error: --url is required for single mode{Style.RESET_ALL}"
                )
                return 1
            process_single_video(
                url=args.url, model=args.model, download_video=args.video
            )
        elif args.mode == "batch":
            if not args.url:
                print(
                    f"{Fore.RED + Style.BRIGHT}Error: --url is required for batch mode{Style.RESET_ALL}"
                )
                return 1
            # CLI default for model pool: 1 instance
            instances = args.model_instances if args.model_instances is not None else 1
            process_channel_videos(
                url=args.url,
                limit=args.limit,
                workers=args.workers,
                model_instances=instances,
                model=args.model,
            )
        elif args.mode == "json":
            if not args.url:
                print(
                    f"{Fore.RED + Style.BRIGHT}Error: --url is required for json mode{Style.RESET_ALL}"
                )
                return 1
            download_channel_history_json(url=args.url)
        elif args.mode == "stats":
            run_stats()
        return 0

    # Interactive loop — paste a channel link and go
    while True:
        print_header_and_clear()
        print_subtext()
        print(
            f"{Fore.WHITE + Style.BRIGHT}1. Transcribe a single YouTube video (and optionally download video){Style.RESET_ALL}"
        )
        print(
            f"{Fore.WHITE + Style.BRIGHT}2. Transcribe a batch of the latest videos from a YouTube channel{Style.RESET_ALL}"
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
