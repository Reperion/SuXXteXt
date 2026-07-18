"""Persistent interactive sessions via tmux (survives agent shells / detach)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import Optional

from colorama import Fore, Style

from suxxtext.prompting import stdin_is_interactive

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SESSION = "suxxtext"
VENV_ACTIVATE = os.path.join(PROJECT_ROOT, "suxxtext-venv", "bin", "activate")


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def session_exists(name: str = DEFAULT_SESSION) -> bool:
    if not tmux_available():
        return False
    r = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
    )
    return r.returncode == 0


def start_persistent_session(session: str = DEFAULT_SESSION) -> int:
    """
    Start SuXXTeXt interactive CLI inside a detached tmux session.
    Returns 0 on success. Prints attach instructions.
    """
    if not tmux_available():
        print(
            f"{Fore.RED}tmux not found. Install tmux, or run in a real terminal:{Style.RESET_ALL}\n"
            f"  cd {PROJECT_ROOT} && source suxxtext-venv/bin/activate && python -m suxxtext"
        )
        return 1

    if session_exists(session):
        print(
            f"{Fore.YELLOW}SuXXTeXt session '{session}' is already running.{Style.RESET_ALL}\n"
            f"  Attach:  {Fore.CYAN}tmux attach -t {session}{Style.RESET_ALL}\n"
            f"  Kill:    {Fore.CYAN}tmux kill-session -t {session}{Style.RESET_ALL}"
        )
        return 0

    root_q = shlex.quote(PROJECT_ROOT)
    act_q = shlex.quote(VENV_ACTIVATE)
    inner = (
        f"cd {root_q} && "
        f"source {act_q} 2>/dev/null || true; "
        f"export SUXXTEXT_IN_TMUX=1; "
        f"export PYTHONUNBUFFERED=1; "
        f"exec python -m suxxtext --no-auto-tmux"
    )
    cmd = [
        "tmux",
        "new-session",
        "-d",
        "-s",
        session,
        "-c",
        PROJECT_ROOT,
        "bash",
        "-lc",
        inner,
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"{Fore.RED}Failed to start tmux session: {e}{Style.RESET_ALL}")
        return 1

    print(
        f"{Fore.GREEN}SuXXTeXt started in a persistent tmux session '{session}'.{Style.RESET_ALL}\n"
        f"  Attach now:  {Fore.CYAN}tmux attach -t {session}{Style.RESET_ALL}\n"
        f"  Detach later: Ctrl+b then d\n"
        f"  Kill session: {Fore.CYAN}tmux kill-session -t {session}{Style.RESET_ALL}"
    )
    return 0


def ensure_interactive_or_persist(auto_tmux: bool = True) -> Optional[int]:
    """
    If we already have a TTY (or are inside our tmux), return None (caller runs menu).
    If no TTY and auto_tmux, start persistent session and return exit code.
    """
    if os.environ.get("SUXXTEXT_IN_TMUX") == "1":
        return None
    if stdin_is_interactive():
        return None
    if not auto_tmux:
        print(
            f"{Fore.YELLOW}No interactive TTY. Use flags, or start a persistent session:{Style.RESET_ALL}\n"
            f"  python -m suxxtext --tmux\n"
            f"  tmux attach -t {DEFAULT_SESSION}\n"
            f"Or:\n"
            f"  python -m suxxtext --mode batch -u 'https://www.youtube.com/@channel/videos' --limit 3"
        )
        return 1
    print(
        f"{Fore.YELLOW}No interactive TTY detected — starting persistent tmux session…{Style.RESET_ALL}"
    )
    return start_persistent_session()
