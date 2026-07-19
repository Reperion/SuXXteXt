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
    SAFE_PACE_SECONDS,
    download_channel_history_json,
    process_channel_videos,
    process_single_video,
)
from suxxtext.monitor import list_channels_with_logs, run_monitor

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

  # Safe mode: 1 video / 3 min (~480/day), serial — good when sharing the PC
  python -m suxxtext --mode batch --channel "@Drberg" --limit 512 --safe
  # custom pace (seconds between Whisper starts):
  python -m suxxtext --mode batch --channel "@Drberg" --limit 100 --pace 120

  # Live dashboard (near real-time):
  python -m suxxtext --mode monitor
  python -m suxxtext --mode monitor --channel Drberg --interval 1.5
  suxxtext --mode monitor

  Defaults: --workers {DEFAULT_WORKERS} --model_instances {DEFAULT_MODEL_INSTANCES}
  Cookies: export SUXXTEXT_COOKIES_FROM_BROWSER=chrome  (or --cookies-from-browser chrome)
  See docs/ops-channel-batch.md
        """,
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["single", "batch", "json", "stats", "monitor"],
        help="Operation mode: single, batch, json, stats, monitor",
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
    parser.add_argument(
        "--safe",
        action="store_true",
        help=(
            f"Safe/paced batch: 1 Whisper video every {int(SAFE_PACE_SECONDS)}s "
            f"(~{int(86400 / SAFE_PACE_SECONDS)}/day), serial workers=1. "
            "Pair with --cookies-from-browser chrome."
        ),
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help=(
            "Min seconds between Whisper video starts (serial). "
            f"0=off. --safe sets this to {int(SAFE_PACE_SECONDS)}."
        ),
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        metavar="BROWSER",
        help=(
            "Pass browser cookies to yt-dlp (chrome, firefox, …). "
            "Sets SUXXTEXT_COOKIES_FROM_BROWSER for this process."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.5,
        help="Monitor refresh seconds (default 1.5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Monitor: print one dashboard frame and exit",
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

    if args.cookies_from_browser:
        os.environ["SUXXTEXT_COOKIES_FROM_BROWSER"] = args.cookies_from_browser.strip()

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
                pace_seconds=float(args.pace or 0.0),
                safe=bool(args.safe),
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
        elif args.mode == "monitor":
            ch = args.channel
            # --channel might be @Handle; strip for archive folder
            if ch and ch.startswith("@"):
                ch = ch[1:]
            return run_monitor(
                channel=ch,
                interval=args.interval,
                once=args.once,
            )
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
        print(
            f"{Fore.WHITE + Style.BRIGHT}5. Monitor batch / PCS dashboard "
            f"(near real-time){Style.RESET_ALL}"
        )
        print(f"{Fore.WHITE + Style.BRIGHT}0. Exit{Style.RESET_ALL}")
        choice = input(
            f"{Fore.CYAN}Choose an option (0–5): {Style.RESET_ALL}"
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
        elif choice == "5":
            chans = list_channels_with_logs()
            default = "Drberg" if "Drberg" in chans else (chans[0] if chans else "Drberg")
            prompt = (
                f"{Fore.CYAN}Channel folder to monitor "
                f"[{default}]: {Style.RESET_ALL}"
            )
            pick = input(prompt).strip() or default
            if pick.startswith("@"):
                pick = pick[1:]
            run_monitor(channel=pick, interval=1.5)
        elif choice == "0":
            print(f"{Fore.GREEN}Exiting. Goodbye!{Style.RESET_ALL}")
            break
        else:
            print(f"{Fore.RED + Style.BRIGHT}Invalid choice. Please try again.{Style.RESET_ALL}")
            time.sleep(2)
    return 0
