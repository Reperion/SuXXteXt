# Channel-scale batch ops (Whisper archive → Ollama PCS)

Playbook from the **Drberg 512** run (2026-07-18/19). Use for any large
channel archive under `channels/<Name>/`.

## Goals

1. **Step 1 — transcripts:** For N latest videos, **captions first** (fast, no GPU),
   then Whisper only on miss; skip by `video_id`.
2. **Step 2 — PCS cards:** Ollama (`gemma4:e4b` default) → fluff-free
   problem / cause / solution (+ related) under `summaries/`.

Do **not** run heavy Whisper batches while another GPU Whisper job owns the card.
PCS is lighter (Ollama) but still leave concurrent Whisper alone.

## Layout

```
channels/<Channel>/
  transcriptions/*.txt     # *_VIEWviews_VIDEOID.txt
  mp3/                     # audio cache
  summaries/<id>.json      # PCS cards
  summaries/index.jsonl
  logs/                    # batch + PCS + watch logs
```

Skip logic: any existing transcript whose filename ends with `_<video_id>.txt`.

## Step 1 — batch (captions first → Whisper)

CLI defaults (2026-07-19): **captions first**, Whisper fallback, **4 workers / 2 models**.

```bash
cd /home/lucid/projects/yt-transcriber
source suxxtext-venv/bin/activate
export PYTHONPATH=.

# Preferred — same as agents should use
python -m suxxtext --mode batch --channel "@HANDLE" --limit 512

# Explicit gentle Whisper throttle (defaults already 4 / 2)
python -m suxxtext --mode batch --channel "@HANDLE" --limit 512 \
  --workers 4 --model_instances 2 --model base

# Force Whisper only (skip caption attempt)
python -m suxxtext --mode batch --channel "@HANDLE" --limit 50 --whisper-only

# Captions only (no GPU)
python -m suxxtext --mode batch --channel "@HANDLE" --limit 50 --no-whisper-fallback
```

Captions run **serially** with `--caption-delay` (default 0.5s) to reduce API IP blocks.
Whisper only loads for videos that missed captions.

### Throttle guidance (RTX 3080 Ti-class, Whisper phase)

| Workers | Whisper models | When |
|--------:|---------------:|------|
| **4** | **2** | **CLI default — proven on Drberg residual** |
| 10 | 5 | Faster but 403/429 risk on audio downloads |
| 1–2 serial | 1–2 | Residual hard fails (see cookies) |

Expect many channels to fill mostly from captions (minutes not hours). Whisper phase
~40–50 new transcripts / 10 min when healthy on gentle settings.

### Rate-limit symptoms

- `HTTP Error 403`, `Download error`, `Sign in to confirm you’re not a bot`
- Burst of failures mid-batch after a fast start

**Response:** stop stacking retries at high concurrency; re-run same command with
**4 workers / 2 models** (skip-existing keeps good files). Still failing after
a full gentle pass → cookie retry (next section).

## Cookie retry for residual bot-blocks

`download_audio` does not pass browser cookies by default. A small set of videos
can remain 403 even at gentle throttle.

Optional env (core download path):

```bash
export SUXXTEXT_COOKIES_FROM_BROWSER=chrome   # needs Chrome profile on this host
```

Serial helper for a list of video IDs:

```bash
# one id per line
printf '%s\n' ID1 ID2 > /tmp/retry-ids.txt
python scripts/retry_missing_with_cookies.py Drberg /tmp/retry-ids.txt chrome
```

Uses yt-dlp `--cookies-from-browser chrome`, sleep between items, Whisper `base`,
and skip-if-transcript-exists. Chrome must be closed enough for cookie DB read
(or use a copy); on WSL this worked with system Google Chrome.

## Step 2 — PCS (Ollama)

**Only after** transcripts exist (or run in parallel only if GPU free and Ollama
healthy). **Verify Ollama before claiming done.**

```bash
# must answer
curl -s -m 3 http://127.0.0.1:11434/api/tags
# if down:
#   nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
#   ollama pull gemma4:e4b

python -m suxxtext.pcs --check
python -m suxxtext.pcs --channel Drberg   # no --force → skip existing cards
```

Cards: `channels/<Channel>/summaries/<video_id>.json` + `index.jsonl`.
Search: `python -m suxxtext.pcs --channel Drberg --search gout`

### Watch-chain pattern

```bash
# After starting batch, optional: wait for batch PID then PCS
# Critically: check ollama is up *before* PCS; do not treat “watch ALL_DONE”
# as PCS-complete if summaries count << transcript count.
```

False “done” we hit: watch loop fired PCS while Ollama was down → only ~19 cards.
Fix: ensure Ollama + re-run `pcs --channel …` (no `--force`).

## Progress / Telegram (optional)

- `scripts/drberg_tg_progress.sh` — HTML tables: counts, ETA, recent titles.
  Reads `channels/Drberg/logs/latest-batch.pidpath` for the active log.
  Secrets from `~/.hermes/.env` (never commit).
- Agent tick every ~10 min for TUI; TG every ~30 min while long jobs run.
- Cancel schedulers when `ALL_DONE` / PCS finished.

## Ops hygiene

- **Leave long jobs alone** unless Mike asks or they are clearly stuck.
- **Don’t second-run with `--force`** if cards already cover transcripts.
- **Don’t start a second 100+ Whisper batch** while one owns the GPU.
- Single-video TL;DW (`yt_tldw.py`) can use a separate `/tmp` output dir.
- Logs under `channels/<Name>/logs/` — keep; gitignores `channels/`.
- Prefer small, single-purpose commits in this repo.

## Drberg 512 results (reference)

| Stage | Outcome |
|-------|---------|
| Aggressive batch | Incomplete; 403/429 after reboot restart |
| Gentle 4w/2m | 298 new + 200 skip + 14 err → 498 txt |
| Cookie serial retry | 14/14 OK → **512/512** transcripts |
| PCS | `python -m suxxtext.pcs --channel Drberg` over Ollama |

---

*Last updated: 2026-07-19*
