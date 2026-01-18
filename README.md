# SuxxText: YouTube Video Transcriber & Channel Analyzer 🚀

![License](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Whisper](https://img.shields.io/badge/AI-OpenAI%20Whisper-green)
![yt-dlp](https://img.shields.io/badge/Tool-yt--dlp-red)
![Status](https://img.shields.io/badge/Status-Maintained-success)

> **"SuxxText"**: Converts video content into text you can actually use. 

![image](https://github.com/user-attachments/assets/f5067163-0f8e-470a-bba8-70164e58fe86)

## 🌟 Why SuxxText?

**SuxxText** is a robust **YouTube Transcriber** and **Channel Analyzer** designed for researchers, archivists, and data lovers. Stop manually transcribing videos or relying on flaky online converters.

*   🎙️ **Offline AI Transcription**: Powered by **OpenAI Whisper** for high-accuracy speech-to-text.
*   📊 **Channel Analytics**: Download full channel history and generate **beautiful HTML reports**.
*   ⚡ **Batch Processing**: Transcribe entire playlists or channels in parallel.
*   🔒 **Privacy Focused**: Everything runs locally on your machine. No API costs, no data leaks.

---

## 🚀 Quick Start

Get up and running in seconds.

### Prerequisities
*   Python 3.8+
*   `ffmpeg` (Required for audio processing: `sudo apt install ffmpeg`)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/LuCiDDre@MS/yt-transcriber.git
cd yt-transcriber

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the tool
python3 transcribe2.py
```

*Or use the included wrapper script:*
```bash
chmod +x run.sh
./run.sh
```

---

## ✨ Key Features

| Feature | Description |
| :--- | :--- |
| **Video to Text** | Convert any YouTube video to a `.txt` transcription file. |
| **MP3 Extraction** | Automatically save the audio track as a high-quality MP3. |
| **Channel Archiver** | Download metadata for *every* video on a channel into JSON. |
| **HTML Reports** | Analyze channel performance with interactive graphs and tables. |
| **Looping CLI** | A user-friendly, colored command-line interface that keeps running. |

---

## 🛠️ Technical Overview

### Architecture

SuxxText integrates powerful tools to deliver a seamless workflow:

```mermaid
graph LR
    A[SuxxText Script] --> B["yt-dlp CLI Tool"];
    A --> C["Whisper (OpenAI)"];
    A --> D[Colorama Library];
    A --> E["Concurrent.Futures Library"];
    A --> F["yt-dlp Python Library"];
    A --> G[yt_channel_analyzer.py Script];

    subgraph ExternalCommands
        B["yt-dlp CLI Tool"]
    end
    subgraph PythonEcosystem
        C["Whisper (OpenAI)"]
        D[Colorama Library]
        E["Concurrent.Futures Library"]
        F["yt-dlp Python Library"]
        G[yt_channel_analyzer.py Script]
    end

    style A stroke:#333,stroke-width:2px
    style B stroke:#333,stroke-width:2px
    style C stroke:#333,stroke-width:2px
    style D stroke:#333,stroke-width:2px
    style E stroke:#333,stroke-width:2px
    style F stroke:#333,stroke-width:2px
    style G stroke:#333,stroke-width:2px
```

### Core Workflows

1.  **Single Video**: Download Audio -> Transcribe with Whisper -> Save TXT
2.  **Batch Processing**: Fetch Channel List -> Filter Existing -> Parallel Transcribe
3.  **Analytics**: Parse History JSON -> Calculate Stats -> Generate HTML Report

---

## 📜 License & Credits

**Author:** [LuCiDDre@MS]
**License:** [CC BY-NC 4.0](LICENSE) - Free to use and adapt for non-commercial purposes. Attribution required.

This project stands on the shoulders of giants. Special thanks to:
*   [**yt-dlp**](https://github.com/yt-dlp/yt-dlp): The incredible tool powering the video downloads.
*   [**OpenAI Whisper**](https://github.com/openai/whisper): The state-of-the-art AI model used for accurate transcriptions.
*   [**Colorama**](https://github.com/tartley/colorama): For making the terminal output look great.
