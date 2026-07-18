"""Safe interactive prompts that never crash on EOF / non-TTY."""

from __future__ import annotations

import os
import sys
from typing import Optional

from colorama import Fore, Style


class InteractiveCancelled(Exception):
    """User cancelled or stdin closed."""


def stdin_is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def prompt(message: str, default: Optional[str] = None) -> str:
    """
    Read a line from the user.

    - On EOF / non-TTY: raises InteractiveCancelled (no traceback spam).
    - On Ctrl+C: raises InteractiveCancelled.
    - Empty input returns default if provided, else "".
    """
    if not stdin_is_interactive() and not os.environ.get("SUXXTEXT_ALLOW_EOF_PROMPT"):
        # Still try input if force-allowed (tests); otherwise fail clearly
        if not sys.stdin.isatty():
            raise InteractiveCancelled("No interactive terminal (stdin is not a TTY)")

    try:
        line = input(message)
    except EOFError as e:
        raise InteractiveCancelled("End of input") from e
    except KeyboardInterrupt as e:
        print()  # newline after ^C
        raise InteractiveCancelled("Interrupted") from e

    line = line.strip()
    if not line and default is not None:
        return default
    return line


def prompt_yes_no(message: str, default_no: bool = True) -> bool:
    raw = prompt(message, default="no" if default_no else "yes")
    return raw.lower() in ("y", "yes", "1", "true")
