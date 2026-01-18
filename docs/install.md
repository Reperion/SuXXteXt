# Installation Guide: SuxxText - YouTube Transcriber & Channel Analyzer

This guide details the full installation process for setting up the SuxxText project on a WSL2 (Ubuntu) environment with GPU acceleration.

---

## 1. Prerequisites

- **WSL2** with Ubuntu (or compatible Linux)
- **Python 3.8+** (recommended: Python 3.12)
- **NVIDIA GPU** with CUDA support (e.g., 3080Ti)
- **VS Code** (optional, for development)

---

## 2. Clone or Create Project Directory

```bash
cd ~/projects
mkdir yt-transcriber
cd yt-transcriber
```

---

## 3. Create and Activate Python Virtual Environment

```bash
python3 -m venv yt-transcriber-venv
source yt-transcriber-venv/bin/activate
```

---

## 4. Install Python Dependencies

Install `yt-dlp`, `openai-whisper`, and `colorama` (and their dependencies) inside the virtual environment:

```bash
pip install yt-dlp openai-whisper colorama
```

---

## 5. Install System Dependencies

**Install ffmpeg** (required for audio extraction and conversion):

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
```

---

## 6. Folder Structure

SuxxText organizes its output and documentation into a clear structure:

- `channels/` — Base directory for all channel-specific data.
    - `[ChannelName]/` — A directory for each processed YouTube channel (e.g., `channels/Eternal-Health/`).
        - `mp3/` — Stores downloaded audio files (e.g., `VideoTitle_ViewCount_ID.mp3`).
        - `transcriptions/` — Stores transcription output files (e.g., `VideoTitle_ViewCount_ID.txt`).
        - `video/` — (Optional, for single video option) Stores downloaded low-resolution video files (e.g., `DD-Mon-YYYY-VideoTitle.mp4`).
        - `[ChannelName]-full-history.json` — Full metadata dump of all videos from the channel.
        - `[ChannelName]_statistics.html` — Generated HTML statistics report for the channel.
        - `error_log.txt` — Logs any errors encountered during batch processing.
- `report-generator-css/` — Contains assets for the HTML statistics reports.
    - `css/` — Stylesheets for the reports (e.g., `style.css`).
    - `js/` — JavaScript for report interactivity (e.g., `script.js`).
- `docs/` — Contains project documentation.
    - `README.md` — Main project overview.
    - `install.md` — This installation guide.
    - `projectplan.md` — Project plan and progress.
    - `suxxtext.md` — (Legacy/Original project description)
- `transcribe2.py` — Main script for all operations.
- `yt_channel_analyzer.py` — Script used by `transcribe2.py` to generate statistics reports.

---

## 7. Usage

The easiest way to run the tool is using the `run.sh` wrapper script, which automatically activates the virtual environment.

### A. Professional / Automation (CLI Mode)
Run everything in a single command using flags.

```bash
# Transcribe a single video immediately
./run.sh --mode single --url "YOUTUBE_URL"

# Transcribe with options (e.g., small model, also download video)
./run.sh --mode single --url "YOUTUBE_URL" --model small --video

# Batch process the latest 5 videos from a channel
./run.sh --mode batch --url "CHANNEL_URL" --limit 5

# Download channel history JSON only
./run.sh --mode json --url "CHANNEL_URL"
```

### B. Interactive Mode
Run without arguments to use the menu system.

```bash
./run.sh
```

**Options overview:**
-   **1. Transcribe a single YouTube video:** Downloads audio and transcribes it. Optional low-res video download.
-   **2. Batch transcribe channel videos:** Downloads and transcribes the latest videos in parallel.
-   **3. Download Channel History:** Saves full metadata of all channel videos to a JSON file.
-   **4. Generate Statistics:** Creates a comprehensive HTML statistics report from a JSON history file.


---

## 8. GPU Acceleration

- The script and Whisper will use your NVIDIA GPU (CUDA) if available.
- You can monitor GPU usage with `nvidia-smi` in another terminal.
- Typical GPU memory usage for the base model is ~800MB during transcription.

---

## 9. Notes

- All dependencies are installed in the virtual environment to avoid system conflicts.
- If you encounter issues with missing packages, ensure your virtual environment is activated and ffmpeg is installed.
- For best performance, use the base model unless you need higher accuracy (larger models require more memory and time).

---

## 10. Uninstallation/Cleanup

To remove the virtual environment and all installed packages:

```bash
deactivate
rm -rf yt-transcriber-venv
```

---

**End of Installation Guide**
