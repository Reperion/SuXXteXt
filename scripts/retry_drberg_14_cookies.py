#!/usr/bin/env python3
"""Backward-compatible wrapper — prefer retry_missing_with_cookies.py."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ids = sys.argv[1] if len(sys.argv) > 1 else "/tmp/drberg-retry-14.txt"
script = Path(__file__).resolve().parent / "retry_missing_with_cookies.py"
sys.argv = [str(script), "Drberg", ids, "chrome"]
runpy.run_path(str(script), run_name="__main__")
