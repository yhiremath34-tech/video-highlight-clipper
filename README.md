# 🎬 Video Highlight Clipper AI

> An automated AI studio that transforms long videos and YouTube URLs into viral 9:16 vertical clips (TikTok, Shorts, Reels) with speech-to-text transcription and burned-in subtitles.

---

## ✨ Features

- **🔴 YouTube URL Processing**: Paste any YouTube video or Shorts link (`yt-dlp`) for instant automated download and processing.
- **📁 Local Video Upload**: Support for MP4, MOV, MKV, WEBM, AVI, and M4V files up to 2 GB.
- **⚡ Faster-Whisper AI Transcription**: Fast, local CPU int8 quantized speech-to-text with Voice Activity Detection (VAD).
- **🔥 Automated Virality Detection**: Heuristic keyword scoring and temporal non-maximum suppression to detect high-impact moments.
- **📐 9:16 Vertical Smart Framing**: Re-frames horizontal videos to 1080x1920 with centered cropping and lower-third styled captions.
- **👁️ Interactive Preview & Editing**: In-browser video playback, interactive moment timeline, and instant timestamp seek.
- **🛡️ 100% Local & Private**: No cloud API keys or external subscriptions required.

---

## 🛠️ Requirements

- **Python**: 3.10 or 3.11
- **FFmpeg & FFprobe**: Required for video scaling, cropping, and subtitle burning.
  - Windows: `winget install Gyan.FFmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

---

## 🚀 Quickstart

### 1. Clone the repository
```bash
git clone https://github.com/yhiremath34-tech/video-highlight-clipper.git
cd video-highlight-clipper
```

### 2. Set up Virtual Environment & Install Dependencies

Using `uv` (Recommended - Ultra Fast):
```bash
uv venv --python 3.11
.\.venv\Scripts\activate
uv pip install -r requirements.txt
```

Or using standard `pip`:
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the Application
```bash
python app.py
```

Open your browser at **http://127.0.0.1:5000**.

---

## 🏗️ Project Architecture

```
video_highlight_clipper/
├── app.py              # Flask server, Faster-Whisper pipeline, yt-dlp & FFmpeg engine
├── requirements.txt    # Python package dependencies
├── templates/
│   └── index.html      # Responsive glassmorphic frontend UI
├── uploads/            # Temporary source video storage (.gitkeep)
├── outputs/            # Rendered 9:16 MP4 video clips (.gitkeep)
├── work/               # Subtitle SRTs and project JSON state (.gitkeep)
└── README.md           # Documentation
```

---

## 📄 License

MIT License. Open-source for personal and commercial usage.
