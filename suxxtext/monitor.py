"""Near-real-time CLI dashboard for channel batch / PCS jobs.

Reads ``channels/<Name>/logs/latest-batch.*`` and archive counts.
No extra deps — colorama + ANSI clear + box drawing.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from colorama import Fore, Style

from suxxtext.paths import CHANNELS_ROOT, ensure_channel_dirs

_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")
_CHECK_RE = re.compile(r"\[(\d+)/(\d+)\] Checking video:")
_PACE_RE = re.compile(r"\[pace (\d+)/(\d+)\]")

# layout
W = 72  # inner content width (between box borders)


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


def _pid_etime(pid: Optional[int]) -> str:
    if not pid or not _pid_alive(pid):
        return "—"
    try:
        import subprocess

        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "etime="], text=True, timeout=1
        ).strip()
        return out or "—"
    except Exception:
        return "—"


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


def _gpu_info() -> Tuple[str, Optional[float], Optional[float]]:
    """Return (display, util_pct, mem_frac)."""
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
            return "n/a", None, None
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 3:
            util = float(parts[0])
            used = float(parts[1])
            total = float(parts[2]) or 1.0
            return f"{parts[0]}% · {parts[1]}/{parts[2]} MiB", util, used / total
        return out, None, None
    except Exception:
        return "n/a", None, None


def _bar(done: int, total: int, width: int = 32, color: str = Fore.GREEN) -> str:
    """Colored block progress bar."""
    if total <= 0:
        empty = "─" * width
        return f"{Fore.WHITE}[{empty}]{Style.RESET_ALL}   —"
    frac = min(1.0, max(0.0, done / float(total)))
    filled = int(round(frac * width))
    # partial last block
    bar = "█" * filled + "░" * (width - filled)
    pct = f"{100 * frac:5.1f}%"
    return (
        f"{Fore.WHITE}[{Style.RESET_ALL}{color}{bar}{Style.RESET_ALL}{Fore.WHITE}]"
        f"{Style.RESET_ALL} {Style.BRIGHT}{pct}{Style.RESET_ALL}"
    )


def _badge(text: str, kind: str = "ok") -> str:
    colors = {
        "ok": Fore.BLACK + "\033[42m",  # green bg
        "run": Fore.BLACK + "\033[46m",  # cyan bg
        "warn": Fore.BLACK + "\033[43m",
        "err": Fore.WHITE + "\033[41m",
        "idle": Fore.WHITE + "\033[100m",
        "pcs": Fore.BLACK + "\033[45m",
    }
    c = colors.get(kind, colors["idle"])
    return f"{c} {text} {Style.RESET_ALL}"


def _parse_log(text: str) -> dict:
    lines = text.splitlines()
    start_line = ""
    for ln in lines[:40]:
        if ln.startswith("START ") or "limit=" in ln.lower() or "Pipeline:" in ln:
            start_line = ln.strip()
            break
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

    downloading: List[str] = []
    transcribing: List[str] = []
    for ln in lines[-100:]:
        if "Downloading audio" in ln:
            m = _ID_RE.search(ln)
            if m:
                downloading.append(m.group(1))
        if "Transcribing audio" in ln:
            m = _ID_RE.search(ln)
            if m:
                transcribing.append(m.group(1))

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
            ln.strip()
            for ln in text[idx:].splitlines()[1:12]
            if ln.strip().startswith("-")
        ]

    # cleaner tail — drop partial download % lines
    tail_lines = []
    for ln in lines[-12:]:
        if "[download]" in ln and "%" in ln and "100%" not in ln:
            continue
        if "Downloading webpage" in ln or "player API JSON" in ln:
            continue
        if "client config" in ln or "tv client config" in ln:
            continue
        tail_lines.append(ln)
    tail_lines = tail_lines[-5:]

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
        "tail": "\n".join(tail_lines),
    }


def _mtime_age(path: Path) -> str:
    try:
        age = time.time() - path.stat().st_mtime
        if age < 120:
            return f"{int(age)}s"
        if age < 3600:
            return f"{int(age // 60)}m"
        return f"{age / 3600:.1f}h"
    except OSError:
        return "?"


def _recent_transcripts(trans_dir: Path, n: int = 7) -> List[Tuple[str, str, str]]:
    """(title, age, video_id)."""
    if not trans_dir.is_dir():
        return []
    try:
        files = sorted(
            trans_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:n]
    except OSError:
        return []
    rows = []
    for p in files:
        name = p.stem
        vid = ""
        m = re.search(r"_([A-Za-z0-9_-]{11})$", name)
        if m:
            vid = m.group(1)
        name = re.sub(r"_\d+views?", "", name, flags=re.I)
        name = re.sub(r"_[A-Za-z0-9_-]{11}$", "", name)
        name = name.replace("_", " ").strip()
        if len(name) > 38:
            name = name[:37] + "…"
        rows.append((name or p.name[:36], _mtime_age(p), vid))
    return rows


def _rate_from_files(trans_dir: Path, window_min: int = 15) -> float:
    """Approx transcripts/min from mtimes in last window."""
    if not trans_dir.is_dir():
        return 0.0
    cutoff = time.time() - window_min * 60
    n = 0
    try:
        for p in trans_dir.glob("*.txt"):
            try:
                if p.stat().st_mtime >= cutoff:
                    n += 1
            except OSError:
                pass
    except OSError:
        return 0.0
    return n / float(window_min) if window_min else 0.0


def _fmt_eta(minutes: float) -> str:
    if minutes != minutes or minutes < 0:  # nan
        return "—"
    m = int(round(minutes))
    if m < 1:
        return "<1m"
    if m < 60:
        return f"~{m}m"
    h, mm = divmod(m, 60)
    if h < 48:
        return f"~{h}h {mm:02d}m"
    d, h = divmod(h, 24)
    return f"~{d}d {h}h"


def _visible_len(s: str) -> int:
    """Length without ANSI escape sequences."""
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def _pad_vis(s: str, width: int) -> str:
    vis = _visible_len(s)
    if vis >= width:
        # crude truncate ANSI-aware: strip and cut plain
        plain = re.sub(r"\033\[[0-9;]*m", "", s)
        if len(plain) > width:
            return plain[: width - 1] + "…"
        return s
    return s + (" " * (width - vis))


def _box_top(title: str = "") -> str:
    if title:
        # ─ title ─
        t = f" {title} "
        inner = W - len(t)
        left = inner // 2
        right = inner - left
        mid = ("─" * left) + t + ("─" * right)
        return f"{Fore.GREEN}╭{mid}╮{Style.RESET_ALL}"
    return f"{Fore.GREEN}╭{'─' * W}╮{Style.RESET_ALL}"


def _box_sep(label: str = "") -> str:
    if not label:
        return f"{Fore.GREEN}├{'─' * W}┤{Style.RESET_ALL}"
    t = f" {label} "
    rest = W - len(t)
    if rest < 0:
        t = t[:W]
        rest = 0
    return f"{Fore.GREEN}├{Style.RESET_ALL}{Fore.CYAN}{t}{Style.RESET_ALL}{Fore.GREEN}{'─' * rest}┤{Style.RESET_ALL}"


def _box_row(content: str) -> str:
    body = _pad_vis(content, W)
    return f"{Fore.GREEN}│{Style.RESET_ALL}{body}{Fore.GREEN}│{Style.RESET_ALL}"


def _box_bot() -> str:
    return f"{Fore.GREEN}╰{'─' * W}╯{Style.RESET_ALL}"


def _kv(key: str, val: str, key_w: int = 12) -> str:
    return f" {Fore.WHITE}{key:<{key_w}}{Style.RESET_ALL} {val}"


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

    gpu_disp, gpu_util, gpu_mem = _gpu_info()
    rate = _rate_from_files(trans, 15)

    return {
        "channel": channel,
        "base": str(base),
        "batch_pid": batch_pid,
        "batch_alive": batch_alive,
        "batch_etime": _pid_etime(batch_pid),
        "watch_pid": watch_pid,
        "watch_alive": watch_alive,
        "blog": str(blog) if blog else None,
        "blog_name": blog.name if blog else None,
        "wlog": str(wlog) if wlog else None,
        "n_txt": n_txt,
        "n_mp3": n_mp3,
        "n_sum": n_sum,
        "gpu": gpu_disp,
        "gpu_util": gpu_util,
        "gpu_mem": gpu_mem,
        "parsed": parsed,
        "recent_files": _recent_transcripts(trans),
        "pcs_running": pcs_running,
        "watch_done": "ALL_DONE_PCS" in watch_text,
        "rate_per_min": rate,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "term_cols": shutil.get_terminal_size((80, 24)).columns,
    }


def render_snapshot(snap: dict) -> str:
    global W
    cols = snap.get("term_cols") or 80
    W = max(56, min(78, cols - 4))

    p = snap.get("parsed") or {}
    ch = snap["channel"]
    out: List[str] = []

    # ── header ──
    out.append(_box_top(" SuXXTeXt · LIVE "))
    title_line = (
        f" {Fore.GREEN + Style.BRIGHT}CHANNEL{Style.RESET_ALL} "
        f"{Fore.CYAN + Style.BRIGHT}{ch}{Style.RESET_ALL}"
        f"   {Fore.WHITE}{snap['ts']}{Style.RESET_ALL}"
    )
    out.append(_box_row(title_line))

    # status badges
    if snap["batch_alive"]:
        bstat = _badge("BATCH RUN", "run")
    elif p.get("batch_done"):
        bstat = _badge("BATCH DONE", "ok")
    else:
        bstat = _badge("BATCH IDLE", "idle")

    if snap.get("pcs_running"):
        pstat = _badge("PCS RUN", "pcs")
    elif snap.get("watch_done"):
        pstat = _badge("PCS DONE", "ok")
    elif snap.get("watch_alive"):
        pstat = _badge("WATCH", "run")
    else:
        pstat = _badge("PCS IDLE", "idle")

    err_n = (p.get("download_err") or 0) + (p.get("bot_sign") or 0) + (p.get("http_403") or 0)
    if err_n > 0:
        estat = _badge(f"ERR {err_n}", "err")
    else:
        estat = _badge("CLEAN", "ok")

    out.append(
        _box_row(
            f" {bstat}  {pstat}  {estat}   "
            f"{Fore.WHITE}elapsed{Style.RESET_ALL} {snap.get('batch_etime', '—')}"
        )
    )

    pid_bits = f"pid {snap['batch_pid'] or '—'}"
    if snap.get("watch_pid"):
        pid_bits += f"  ·  watch {snap['watch_pid']}"
    out.append(_box_row(f" {Fore.WHITE}{pid_bits}{Style.RESET_ALL}"))

    if p.get("start_line"):
        cfg = p["start_line"]
        if len(cfg) > W - 4:
            cfg = cfg[: W - 5] + "…"
        out.append(_box_row(f" {Fore.WHITE}cfg{Style.RESET_ALL}  {cfg}"))
    if snap.get("blog_name"):
        out.append(
            _box_row(
                f" {Fore.WHITE}log{Style.RESET_ALL}  "
                f"{Fore.CYAN}{snap['blog_name']}{Style.RESET_ALL}"
            )
        )

    # ── archive + progress ──
    out.append(_box_sep(" ARCHIVE "))
    out.append(
        _box_row(
            f"  {Fore.YELLOW}txt{Style.RESET_ALL} {Style.BRIGHT}{snap['n_txt']:<6}{Style.RESET_ALL}"
            f"  {Fore.YELLOW}mp3{Style.RESET_ALL} {Style.BRIGHT}{snap['n_mp3']:<6}{Style.RESET_ALL}"
            f"  {Fore.YELLOW}PCS{Style.RESET_ALL} {Style.BRIGHT}{snap['n_sum']:<6}{Style.RESET_ALL}"
            f"  {Fore.WHITE}ΔPCS{Style.RESET_ALL} "
            f"{max(0, snap['n_txt'] - snap['n_sum'])}"
        )
    )

    submitted = p.get("submitted")
    done_new = (p.get("whisper_ok") or 0) + (p.get("caption_ok") or 0)
    rate = snap.get("rate_per_min") or 0.0

    if submitted:
        remaining = max(0, submitted - done_new)
        eta = _fmt_eta(remaining / rate) if rate > 0.05 else "…"
        frac_color = Fore.GREEN if done_new / submitted > 0.5 else Fore.CYAN
        out.append(_box_row(f"  this run  {_bar(done_new, submitted, width=min(34, W - 28), color=frac_color)}"))
        out.append(
            _box_row(
                f"           {Fore.GREEN}{done_new}{Style.RESET_ALL}/{submitted} new"
                f"  ·  whisper {p.get('whisper_ok', 0)}"
                f"  ·  captions {p.get('caption_ok', 0)}"
                f"  ·  left {remaining}"
            )
        )
        out.append(
            _box_row(
                f"           pace {Fore.CYAN}{rate:.2f}{Style.RESET_ALL} txt/min (15m)"
                f"  ·  ETA {Fore.YELLOW}{eta}{Style.RESET_ALL}"
            )
        )
    if p.get("last_check"):
        a, b = p["last_check"]
        out.append(_box_row(f"  discovery {_bar(a, b, width=min(34, W - 28), color=Fore.BLUE)}"))
        out.append(_box_row(f"           checked {a}/{b}"))

    # ── health ──
    out.append(_box_sep(" HEALTH "))
    bot = p.get("bot_sign") or 0
    dl = p.get("download_err") or 0
    h403 = p.get("http_403") or 0
    skip = p.get("already") or 0

    def _num(n: int, bad: bool = False) -> str:
        if n == 0:
            return f"{Fore.GREEN}{n}{Style.RESET_ALL}"
        if bad:
            return f"{Fore.RED + Style.BRIGHT}{n}{Style.RESET_ALL}"
        return f"{Fore.YELLOW}{n}{Style.RESET_ALL}"

    out.append(
        _box_row(
            f"  skip~{_num(skip)}   dl-err {_num(dl, dl > 0)}   "
            f"bot {_num(bot, bot > 0)}   403 {_num(h403, h403 > 0)}"
            f"   (log window)"
        )
    )

    gu = snap.get("gpu_util")
    gm = snap.get("gpu_mem")
    gpu_bar = ""
    if gu is not None:
        gpu_bar = "  " + _bar(int(gu), 100, width=16, color=Fore.MAGENTA)
    out.append(_box_row(f"  GPU  {snap.get('gpu', 'n/a')}{gpu_bar}"))

    # ── in flight ──
    out.append(_box_sep(" IN FLIGHT "))
    dls = p.get("downloading") or []
    trs = p.get("transcribing") or []
    if dls:
        chips = "  ".join(f"{Fore.CYAN}⬇ {id_}{Style.RESET_ALL}" for id_ in dls)
        out.append(_box_row(f"  {chips}"))
    else:
        out.append(_box_row(f"  {Fore.WHITE}⬇ download{Style.RESET_ALL}   —"))
    if trs:
        chips = "  ".join(f"{Fore.MAGENTA}🎙 {id_}{Style.RESET_ALL}" for id_ in trs)
        out.append(_box_row(f"  {chips}"))
    else:
        out.append(_box_row(f"  {Fore.WHITE}🎙 whisper{Style.RESET_ALL}    —"))

    # ── recent ──
    out.append(_box_sep(" RECENT TRANSCRIPTS "))
    rec = snap.get("recent_files") or []
    if not rec:
        out.append(_box_row(f"  {Fore.WHITE}(none yet){Style.RESET_ALL}"))
    else:
        out.append(
            _box_row(
                f"  {Fore.WHITE}{'title':<38}  {'age':>5}  id{Style.RESET_ALL}"
            )
        )
        for i, (title, age, vid) in enumerate(rec):
            mark = f"{Fore.GREEN}●{Style.RESET_ALL}" if i == 0 else f"{Fore.WHITE}○{Style.RESET_ALL}"
            vid_s = f"{Fore.CYAN}{vid}{Style.RESET_ALL}" if vid else ""
            out.append(
                _box_row(
                    f"  {mark} {title:<38}  {Fore.YELLOW}{age:>5}{Style.RESET_ALL}  {vid_s}"
                )
            )

    if p.get("batch_done") and p.get("summary_lines"):
        out.append(_box_sep(" SUMMARY "))
        for sl in p["summary_lines"][:8]:
            s = sl if len(sl) <= W - 4 else sl[: W - 5] + "…"
            out.append(_box_row(f"  {s}"))

    # ── tail ──
    out.append(_box_sep(" LOG TAIL "))
    tail = (p.get("tail") or "").splitlines()
    if not tail:
        out.append(_box_row(f"  {Fore.WHITE}(quiet){Style.RESET_ALL}"))
    for ln in tail:
        s = ln.rstrip()
        if len(s) > W - 4:
            s = s[: W - 5] + "…"
        # color keywords
        if "Whisper saved" in s or "Captions saved" in s or "Captions OK" in s:
            s = f"{Fore.GREEN}{s}{Style.RESET_ALL}"
        elif "error" in s.lower() or "Sign in" in s or "ERROR" in s:
            s = f"{Fore.RED}{s}{Style.RESET_ALL}"
        elif "Transcribing" in s:
            s = f"{Fore.MAGENTA}{s}{Style.RESET_ALL}"
        elif "Downloading" in s or "download" in s:
            s = f"{Fore.CYAN}{s}{Style.RESET_ALL}"
        else:
            s = f"{Fore.WHITE}{s}{Style.RESET_ALL}"
        out.append(_box_row(f"  {s}"))

    out.append(_box_sep())
    out.append(
        _box_row(
            f" {Fore.YELLOW}Ctrl-C{Style.RESET_ALL} quit"
            f"  ·  auto-refresh"
            f"  ·  {Fore.WHITE}suxxtext --mode monitor{Style.RESET_ALL}"
        )
    )
    out.append(_box_bot())
    return "\n".join(out)


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
            os.system("cls" if os.name == "nt" else "clear")
            print(render_snapshot(snap))
            if once:
                return 0
            time.sleep(max(0.5, float(interval)))
    except KeyboardInterrupt:
        print(f"\n{Fore.GREEN}Monitor stopped.{Style.RESET_ALL}")
        return 0
