#!/usr/bin/env bash
# Drberg 512-batch + PCS progress → Telegram (HTML tables + ETA).
# Secrets only from ~/.hermes/.env — never echo tokens.
set -euo pipefail

ROOT="/home/lucid/projects/yt-transcriber/channels/Drberg"
if [[ -z "${BATCH_LOG:-}" ]]; then
  if [[ -f "$ROOT/logs/latest-batch.pidpath" ]]; then
    _bp=$(tr -d " \n" <"$ROOT/logs/latest-batch.pidpath" || true)
    if [[ -n "$_bp" ]]; then
      if [[ "$_bp" != /* ]]; then _bp="/home/lucid/projects/yt-transcriber/$_bp"; fi
      BATCH_LOG="$_bp"
    fi
  fi
fi
BATCH_LOG="${BATCH_LOG:-$ROOT/logs/batch-512-latest.log}"
PID_FILE="$ROOT/logs/latest-batch.pid"
WATCH_PATH_FILE="$ROOT/logs/latest-watch.path"
ENV_FILE="${XO_TELEGRAM_ENV:-$HOME/.hermes/.env}"
TARGET="${DRBERG_TARGET:-512}"
RECENT_N="${DRBERG_RECENT_VIDEOS:-8}"
WINDOW_MIN="${DRBERG_RATE_WINDOW_MIN:-30}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a
eval "$(grep -E '^(TELEGRAM_BOT_TOKEN|TELEGRAM_ALLOWED_USERS|TELEGRAM_HOME_CHANNEL)=' "$ENV_FILE" | sed 's/\r$//')"
set +a
CHAT_ID="${TELEGRAM_CHAT_ID:-${TELEGRAM_HOME_CHANNEL:-${TELEGRAM_ALLOWED_USERS%%,*}}}"
CHAT_ID="${CHAT_ID// /}"
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "$CHAT_ID" ]]; then
  echo "error: missing TELEGRAM_BOT_TOKEN or chat id" >&2
  exit 1
fi

pid=""
alive=no
etime="-"
pcpu="-"
etime_sec=0
if [[ -f "$PID_FILE" ]]; then
  pid=$(tr -d ' \n' <"$PID_FILE" || true)
fi
if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
  alive=yes
  etime=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ' || echo "-")
  pcpu=$(ps -p "$pid" -o pcpu= 2>/dev/null | tr -d ' ' || echo "-")
  # etimes = seconds elapsed (GNU ps)
  etime_sec=$(ps -p "$pid" -o etimes= 2>/dev/null | tr -d ' ' || echo 0)
fi
etime_sec=${etime_sec:-0}

TDIR="$ROOT/transcriptions"
nt=$(find "$TDIR" -maxdepth 1 -type f -name '*.txt' 2>/dev/null | wc -l)
nm=$(find "$ROOT/mp3" -maxdepth 1 -type f 2>/dev/null | wc -l)
ns=$(find "$ROOT/summaries" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l)
pct=$(( TARGET > 0 ? nt * 100 / TARGET : 0 ))
recent=$(find "$TDIR" -maxdepth 1 -type f -name '*.txt' -mmin "-${WINDOW_MIN}" 2>/dev/null | wc -l)
gpu=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null | head -1 || echo "n/a")

finished=no
if [[ -f "$BATCH_LOG" ]] && grep -q 'Batch processing summary' "$BATCH_LOG" 2>/dev/null; then
  finished=yes
fi
watch_done=no
if [[ -f "$WATCH_PATH_FILE" ]]; then
  wlog=$(cat "$WATCH_PATH_FILE" 2>/dev/null || true)
  if [[ -n "${wlog:-}" && -f "$wlog" ]] && grep -q 'ALL_DONE' "$wlog" 2>/dev/null; then
    watch_done=yes
  fi
fi

err403=0
dlerr=0
if [[ -f "$BATCH_LOG" ]]; then
  err403=$(grep -c 'HTTP Error 403' "$BATCH_LOG" 2>/dev/null || true)
  dlerr=$(grep -c 'Download error' "$BATCH_LOG" 2>/dev/null || true)
fi
err403=${err403:-0}
dlerr=${dlerr:-0}

# Phase + ETA (python for clarity)
export NT="$nt" NS="$ns" TARGET_E="$TARGET" RECENT_E="$recent" WINDOW_E="$WINDOW_MIN"
export ETIME_SEC="$etime_sec" FINISHED="$finished" WATCH_DONE="$watch_done" ALIVE="$alive"
export TDIR_E="$TDIR" BATCH_LOG_E="$BATCH_LOG" RECENT_N_E="$RECENT_N"

eval "$(python3 <<'PY'
import os, re, html, time
from pathlib import Path

nt = int(os.environ["NT"])
ns = int(os.environ["NS"])
target = int(os.environ["TARGET_E"])
recent = int(os.environ["RECENT_E"])
window = max(1, int(os.environ["WINDOW_E"]))
etime_sec = int(os.environ.get("ETIME_SEC") or 0)
finished = os.environ.get("FINISHED") == "yes"
watch_done = os.environ.get("WATCH_DONE") == "yes"
alive = os.environ.get("ALIVE") == "yes"
tdir = Path(os.environ["TDIR_E"])
blog = Path(os.environ.get("BATCH_LOG_E") or "")
recent_n = int(os.environ.get("RECENT_N_E") or 8)

remaining_tx = max(0, target - nt)
remaining_pcs = max(0, nt - ns)

# rate: transcripts per minute from sliding window
rate_win = recent / float(window) if recent > 0 else 0.0
# rate from process lifetime (assume ~19 pre-existing at start; clamp)
pre = 19
new_this_run = max(0, nt - pre)
rate_life = (new_this_run / (etime_sec / 60.0)) if etime_sec > 60 and new_this_run > 0 else 0.0
# prefer window if we have signal, else lifetime
rate = rate_win if rate_win > 0.05 else rate_life
if rate_win > 0 and rate_life > 0:
    rate = 0.65 * rate_win + 0.35 * rate_life

def fmt_dur(mins: float) -> str:
    if mins < 0 or mins != mins:  # nan
        return "n/a"
    m = int(round(mins))
    if m < 1:
        return "<1m"
    if m < 60:
        return f"~{m}m"
    h, mm = divmod(m, 60)
    if h < 48:
        return f"~{h}h {mm:02d}m"
    d, h = divmod(h, 24)
    return f"~{d}d {h}h"

eta_tx = "n/a"
eta_done = "n/a"
eta_note = ""
if watch_done:
    eta_tx = "done"
    eta_done = "done"
    phase = "DONE (transcripts + PCS)"
elif finished:
    # PCS only left — ~4–6s per card on gemma4:e4b historically
    pcs_min = remaining_pcs * (5.0 / 60.0)
    eta_tx = "done"
    eta_done = fmt_dur(pcs_min)
    phase = "Transcripts done → PCS"
    eta_note = f"PCS left: {remaining_pcs}"
elif alive and rate > 0:
    mins_tx = remaining_tx / rate
    # after transcripts, PCS for all without cards
    pcs_after = max(remaining_pcs, remaining_tx)  # new ones need PCS
    # remaining_pcs already counts missing cards; plus ones still to transcribe
    need_pcs = remaining_pcs + remaining_tx
    mins_pcs = need_pcs * (5.0 / 60.0)
    eta_tx = fmt_dur(mins_tx)
    eta_done = fmt_dur(mins_tx + mins_pcs)
    phase = "Whisper batch running"
    eta_note = f"{rate:.2f} txt/min · rem {remaining_tx}"
elif alive:
    eta_tx = "warming up"
    eta_done = "…"
    phase = "Whisper batch running"
else:
    phase = "Batch not running (check log)"
    eta_tx = "n/a"
    eta_done = "n/a"

# recent video titles from newest transcript files
def clean_title(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^\d{1,2}-[A-Za-z]{3}-\d{4}-", "", name)
    name = re.sub(r"_\d+views?", "", name, flags=re.I)
    name = re.sub(r"_[A-Za-z0-9_-]{11}$", "", name)
    name = name.replace("_", " ").replace("...", "").strip()
    name = re.sub(r"\s+", " ", name)
    if len(name) > 42:
        name = name[:41] + "…"
    return name or path.stem[:40]

files = sorted(tdir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:recent_n]
rows = []
for i, p in enumerate(files, 1):
    age_m = max(0, int((time.time() - p.stat().st_mtime) / 60))
    age = f"{age_m}m" if age_m < 120 else f"{age_m // 60}h"
    rows.append((i, clean_title(p), age))

# currently transcribing ids from log tail (best-effort)
trans_now = []
if blog.is_file():
    try:
        # read last ~200KB only
        data = blog.read_bytes()[-200_000:].decode("utf-8", errors="replace")
        ids = re.findall(r"\[([A-Za-z0-9_-]{11})\] Transcribing audio", data)
        # unique preserve order last
        seen = set()
        for i in reversed(ids):
            if i not in seen:
                seen.add(i)
                trans_now.append(i)
            if len(trans_now) >= 4:
                break
        trans_now = list(reversed(trans_now))
    except OSError:
        pass

# build video table text (pre)
lines = ["#  Title                                      Age", "-- ---------------------------------------- ----"]
for i, title, age in rows:
    lines.append(f"{i:<2} {title:<40} {age:>4}")
vid_table = "\n".join(lines) if rows else "(no transcripts yet)"

# shell-export safe (use base64 for multiline)
import base64
def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()

print(f"PHASE={b64(phase)}")
print(f"ETA_TX={b64(eta_tx)}")
print(f"ETA_DONE={b64(eta_done)}")
print(f"ETA_NOTE={b64(eta_note)}")
print(f"VID_TABLE={b64(vid_table)}")
print(f"TRANS_NOW={b64(', '.join(trans_now) if trans_now else '—')}")
print(f"RATE={b64(f'{rate:.2f}' if rate else '0')}")
PY
)"

b64d() { python3 -c 'import sys,base64; print(base64.b64decode(sys.argv[1]).decode())' "$1"; }
phase=$(b64d "$PHASE")
eta_tx=$(b64d "$ETA_TX")
eta_done=$(b64d "$ETA_DONE")
eta_note=$(b64d "$ETA_NOTE")
vid_table=$(b64d "$VID_TABLE")
trans_now=$(b64d "$TRANS_NOW")
rate=$(b64d "$RATE")

title="${1:-Drberg batch progress}"
ts=$(date '+%Y-%m-%d %H:%M')

# HTML-escape dynamic free text for safety outside <pre>
# (pre content is plain ASCII from our cleaner)
MSG=$(cat <<EOF
📊 <b>${title}</b>
<code>${ts}</code> · latest ${TARGET} Whisper + PCS

<pre>
Metric          Value
--------------  --------------------
Phase           ${phase}
Status          ${alive}
Elapsed         ${etime}
CPU%            ${pcpu}
Transcripts     ${nt} / ${TARGET} (${pct}%)
Audio files     ${nm}
PCS summaries   ${ns}
+txt ~${WINDOW_MIN}m       ${recent}  (${rate}/min)
ETA transcripts ${eta_tx}
ETA all+PCS     ${eta_done}
Pace note       ${eta_note}
GPU util/VRAM   ${gpu}
HTTP 403s       ${err403}
DL errors       ${dlerr}
In-flight ASR   ${trans_now}
Batch summary   ${finished}
Watch ALL_DONE  ${watch_done}
</pre>

<b>Recent videos</b> (newest first)
<pre>
${vid_table}
</pre>
EOF
)

# Telegram 4096 limit — trim video table if needed
MSG_LEN=${#MSG}
if (( MSG_LEN > 4000 )); then
  MSG="${MSG:0:3990}…
</pre>"
fi

RESP=$(curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  -d "parse_mode=HTML" \
  -d "disable_web_page_preview=true" \
  --data-urlencode "text=${MSG}")

python3 -c '
import json, sys
d = json.load(sys.stdin)
if not d.get("ok"):
    print("send failed:", d.get("description"), file=sys.stderr)
    sys.exit(1)
print("ok message_id=%s" % d["result"].get("message_id"))
' <<<"$RESP"

if [[ "$watch_done" == yes ]]; then
  echo "ALL_DONE" >"$ROOT/logs/tg-progress-stop.flag"
fi
