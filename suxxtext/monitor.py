"""Near-real-time CLI dashboard for channel batch / PCS jobs.

Reads ``channels/<Name>/logs/latest-batch.*`` and archive counts.
No extra deps — colorama + ANSI clear.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from colorama import Fore, Style

from suxxtext.paths import CHANNELS_ROOT, ensure_channel_dirs

_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
_CHECK_RE = re.compile(r"\[(\d+)/(\d+)\] Checking video:")
_PACE_RE = re.compile(r"\[pace (\d+)/(\d+)\]")


def _count_glob(directory: Path, pattern: str) -> int:
    if not directory.is_dir():
        return 0
    try:
        return sum(1 for _ in directory.glob(pattern))
    except OSError:
        return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_int_file(path: Path) -> Optional[int]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return int(raw.split()[0])
    except (OSError, ValueError):
        return None


def _read_path_file(path: Path) -> Optional[Path]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        return p
    except OSError:
        return None


def _tail_text(path: Path, max_bytes: int = 120_000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _gpu_line() -> str:
    try:
        import subprocess

        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2,
        ).strip()
        if not out:
            return "n/a"
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 3:
            return f"{parts[0]}% util · {parts[1]}/{parts[2]} MiB"
        return out
    except Exception:
        return "n/a"


def _bar(done: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    frac = min(1.0, max(0.0, done / float(total)))
    filled = int(round(frac * width))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {100 * frac:5.1f}%"


def _parse_log(text: str) -> dict:
    lines = text.splitlines()
    start_line = ""
    for ln in lines[:30]:
        if ln.startswith("START ") or "limit=" in ln or "Pipeline:" in ln:
            start_line = ln.strip()
            break
    # last [n/total] check
    last_check = None
    for ln in reversed(lines):
        m = _CHECK_RE.search(ln)
        if m:
            last_check = (int(m.group(1)), int(m.group(2)))
            break
        m2 = _PACE_RE.search(ln)
        if m2:
            last_check = (int(m2.group(1)), int(m2.group(2)))
            break

    whisper_ok = len(re.findall(r"Whisper saved to ", text))
    caption_ok = len(re.findall(r"Captions (?:OK|saved)", text))
    download_err = len(re.findall(r"Download error", text))
    bot_sign = len(re.findall(r"Sign in to confirm", text))
    http_403 = len(re.findall(r"HTTP Error 403", text, re.I))
    already = len(re.findall(r"already exists", text))
    submitted = None
    m = re.search(r"Submitting (\d+) Whisper tasks", text)
    if m:
        submitted = int(m.group(1))
    m = re.search(r"Paced Whisper: (\d+) video", text)
    if m:
        submitted = int(m.group(1))
    batch_done = "ALL_DONE_BATCH" in text or "Batch processing summary:" in text
    pcs_done = "ALL_DONE_PCS" in text

    # in-flight ids from recent lines
    downloading: List[str] = []
    transcribing: List[str] = []
    for ln in lines[-80:]:
        if "Downloading audio" in ln:
            m = _ID_RE.search(ln)
            if m:
                downloading.append(m.group(1))
        if "Transcribing audio" in ln:
            m = _ID_RE.search(ln)
            if m:
                transcribing.append(m.group(1))
    # unique preserve order last
    def uniq_last(seq: List[str], n: int = 4) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in reversed(seq):
            if x not in seen:
                seen.add(x)
                out.append(x)
            if len(out) >= n:
                break
        return list(reversed(out))

    recent_ok: List[str] = []
    for ln in lines:
        if "Whisper saved to " in ln or "Captions saved" in ln:
            m = _ID_RE.search(ln)
            if m:
                recent_ok.append(m.group(1))
    recent_ok = uniq_last(recent_ok, 6)

    summary_lines = []
    if "Batch processing summary:" in text:
        idx = text.rfind("Batch processing summary:")
        summary_lines = [
            ln.strip() for ln in text[idx:].splitlines()[1:12] if ln.strip().startswith("-")
        ]

    return {
        "start_line": start_line,
        "last_check": last_check,
        "whisper_ok": whisper_ok,
        "caption_ok": caption_ok,
        "download_err": download_err,
        "bot_sign": bot_sign,
        "http_403": http_403,
        "already": already,
        "submitted": submitted,
        "batch_done": batch_done,
        "pcs_done": pcs_done,
        "downloading": uniq_last(downloading),
        "transcribing": uniq_last(transcribing),
        "recent_ok": recent_ok,
        "summary_lines": summary_lines,
        "tail": "\n".join(lines[-6:]) if lines else "",
    }


def _mtime_age(path: Path) -> str:
    try:
        age = time.time() - path.stat().st_mtime
        if age < 120:
            return f"{int(age)}s ago"
        if age < 3600:
            return f"{int(age // 60)}m ago"
        return f"{age / 3600:.1f}h ago"
    except OSError:
        return "?"


def _recent_transcripts(trans_dir: Path, n: int = 6) -> List[Tuple[str, str]]:
    if not trans_dir.is_dir():
        return []
    try:
        files = sorted(trans_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[
            :n
        ]
    except OSError:
        return []
    rows = []
    for p in files:
        name = p.stem
        name = re.sub(r"_\d+views?", "", name, flags=re.I)
        name = re.sub(r"_[A-Za-z0-9_-]{11}$", "", name)
        name = name.replace("_", " ").strip()
        if len(name) > 42:
            name = name[:41] + "…"
        rows.append((name or p.name[:40], _mtime_age(p)))
    return rows


def collect_snapshot(channel: str, channels_root: str = CHANNELS_ROOT) -> dict:
    base = Path(channels_root) / channel
    logs = base / "logs"
    trans = base / "transcriptions"
    mp3 = base / "mp3"
    summaries = base / "summaries"

    batch_pid = _read_int_file(logs / "latest-batch.pid")
    watch_pid = _read_int_file(logs / "latest-watch.pid")
    pcs_pid = _read_int_file(logs / "latest-pcs.pid")
    blog = _read_path_file(logs / "latest-batch.pidpath")
    wlog = _read_path_file(logs / "latest-watch.path")

    # PCS process may only be under watch bash — detect by name via /proc light
    batch_alive = _pid_alive(batch_pid) if batch_pid else False
    watch_alive = _pid_alive(watch_pid) if watch_pid else False

    log_text = _tail_text(blog) if blog and blog.is_file() else ""
    parsed = _parse_log(log_text) if log_text else {}

    n_txt = _count_glob(trans, "*.txt")
    n_mp3 = _count_glob(mp3, "*")
    n_sum = _count_glob(summaries, "*.json")

    watch_text = _tail_text(wlog, 40_000) if wlog and wlog.is_file() else ""
    pcs_running = "Starting PCS" in watch_text and "ALL_DONE_PCS" not in watch_text
    if pcs_pid and _pid_alive(pcs_pid):
        pcs_running = True

    return {
        "channel": channel,
        "base": str(base),
        "batch_pid": batch_pid,
        "batch_alive": batch_alive,
        "watch_pid": watch_pid,
        "watch_alive": watch_alive,
        "blog": str(blog) if blog else None,
        "wlog": str(wlog) if wlog else None,
        "n_txt": n_txt,
        "n_mp3": n_mp3,
        "n_sum": n_sum,
        "gpu": _gpu_line(),
        "parsed": parsed,
        "recent_files": _recent_transcripts(trans),
        "pcs_running": pcs_running,
        "watch_done": "ALL_DONE_PCS" in watch_text,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def render_snapshot(snap: dict) -> str:
    p = snap.get("parsed") or {}
    ch = snap["channel"]
    lines: List[str] = []
    lines.append(
        f"{Fore.GREEN + Style.BRIGHT}SuXXTeXt monitor{Style.RESET_ALL}  "
        f"{Fore.WHITE}{snap['ts']}{Style.RESET_ALL}  channel={Fore.CYAN}{ch}{Style.RESET_ALL}"
    )
    lines.append("")

    alive = snap["batch_alive"]
    status = f"{Fore.GREEN}RUNNING{Style.RESET_ALL}" if alive else f"{Fore.YELLOW}idle/stopped{Style.RESET_ALL}"
    lines.append(
        f"  Batch PID  {snap['batch_pid'] or '—':>8}  {status}"
    )
    if snap.get("watch_pid"):
        w = (
            f"{Fore.GREEN}alive{Style.RESET_ALL}"
            if snap["watch_alive"]
            else f"{Fore.WHITE}done/stopped{Style.RESET_ALL}"
        )
        lines.append(f"  Watch PID  {snap['watch_pid']:>8}  {w}")
    if snap.get("pcs_running"):
        lines.append(f"  PCS        {Fore.MAGENTA}running{Style.RESET_ALL}")
    elif snap.get("watch_done"):
        lines.append(f"  PCS        {Fore.GREEN}ALL_DONE{Style.RESET_ALL}")

    if p.get("start_line"):
        lines.append(f"  Config     {p['start_line'][:90]}")
    if snap.get("blog"):
        lines.append(f"  Log        {snap['blog']}")

    lines.append("")
    lines.append(f"{Fore.WHITE + Style.BRIGHT}  Archive{Style.RESET_ALL}")
    lines.append(
        f"  transcripts  {snap['n_txt']:<6}  mp3 {snap['n_mp3']:<6}  "
        f"PCS cards {snap['n_sum']}"
    )
    # progress vs submitted
    submitted = p.get("submitted")
    done_new = (p.get("whisper_ok") or 0) + (p.get("caption_ok") or 0)
    if submitted:
        lines.append(f"  this run    {_bar(done_new, submitted)}")
        lines.append(
            f"             new ok {done_new}/{submitted}  "
            f"(whisper {p.get('whisper_ok', 0)} · captions {p.get('caption_ok', 0)})"
        )
    if p.get("last_check"):
        a, b = p["last_check"]
        lines.append(f"  discovery   checked {a}/{b}")

    lines.append("")
    lines.append(f"{Fore.WHITE + Style.BRIGHT}  Errors / skips (log window){Style.RESET_ALL}")
    lines.append(
        f"  skip existing ~{p.get('already', 0):<5}  "
        f"dl errors {p.get('download_err', 0):<5}  "
        f"bot-check {p.get('bot_sign', 0):<5}  403s {p.get('http_403', 0)}"
    )

    lines.append("")
    lines.append(f"{Fore.WHITE + Style.BRIGHT}  In flight{Style.RESET_ALL}")
    dl = ", ".join(p.get("downloading") or []) or "—"
    tr = ", ".join(p.get("transcribing") or []) or "—"
    lines.append(f"  downloading   {Fore.CYAN}{dl}{Style.RESET_ALL}")
    lines.append(f"  transcribing  {Fore.MAGENTA}{tr}{Style.RESET_ALL}")

    lines.append("")
    lines.append(f"{Fore.WHITE + Style.BRIGHT}  Recent transcript files{Style.RESET_ALL}")
    for title, age in snap.get("recent_files") or []:
        lines.append(f"  · {title:<44} {age}")
    if not snap.get("recent_files"):
        lines.append("  · (none yet)")

    lines.append("")
    lines.append(f"  GPU  {snap.get('gpu', 'n/a')}")

    if p.get("batch_done"):
        lines.append("")
        lines.append(f"{Fore.GREEN}  Batch log reports finished{Style.RESET_ALL}")
        for sl in p.get("summary_lines") or []:
            lines.append(f"  {sl}")

    lines.append("")
    lines.append(f"{Fore.WHITE}  log tail{Style.RESET_ALL}")
    for ln in (p.get("tail") or "").splitlines()[-4:]:
        # strip download % spam somewhat
        if "[download]" in ln and "%" in ln and "100%" not in ln:
            continue
        s = ln if len(ln) < 100 else ln[:97] + "…"
        lines.append(f"  {Fore.WHITE}{s}{Style.RESET_ALL}")

    lines.append("")
    lines.append(
        f"{Fore.YELLOW}  q + Enter quit · refresh auto · Ctrl-C quit{Style.RESET_ALL}"
    )
    return "\n".join(lines)


def list_channels_with_logs(channels_root: str = CHANNELS_ROOT) -> List[str]:
    root = Path(channels_root)
    if not root.is_dir():
        return []
    names = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "logs").is_dir():
            names.append(p.name)
    return names


def run_monitor(
    channel: Optional[str] = None,
    interval: float = 1.5,
    once: bool = False,
    channels_root: str = CHANNELS_ROOT,
) -> int:
    """Interactive or one-shot dashboard. Returns process exit code."""
    if not channel:
        # Prefer channel that has latest-batch.pid alive, else Drberg, else first
        candidates = list_channels_with_logs(channels_root)
        chosen = None
        for name in candidates:
            pid = _read_int_file(Path(channels_root) / name / "logs" / "latest-batch.pid")
            if pid and _pid_alive(pid):
                chosen = name
                break
        if not chosen:
            for pref in ("Drberg", "drberg"):
                if pref in candidates:
                    chosen = pref
                    break
        channel = chosen or (candidates[0] if candidates else "Drberg")

    ensure_channel_dirs(channel, channels_root=channels_root)

    try:
        while True:
            snap = collect_snapshot(channel, channels_root=channels_root)
            # clear
            os.system("cls" if os.name == "nt" else "clear")
            print(render_snapshot(snap))
            if once:
                return 0
            # non-blocking-ish quit: short sleeps and check stdin if possible
            time.sleep(max(0.5, float(interval)))
    except KeyboardInterrupt:
        print(f"\n{Fore.GREEN}Monitor stopped.{Style.RESET_ALL}")
        return 0
