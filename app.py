import os
import re
import json
import uuid
import shutil
import subprocess
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_from_directory
)
from werkzeug.utils import secure_filename

# Project folders
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
WORK_DIR = BASE_DIR / "work"

for folder in (UPLOAD_DIR, OUTPUT_DIR, WORK_DIR):
    folder.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"
}

MAX_UPLOAD_MB = 2048

app = Flask(__name__)
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY"
) or uuid.uuid4().hex

app.config["MAX_CONTENT_LENGTH"] = (
    MAX_UPLOAD_MB * 1024 * 1024
)


def allowed_video(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def run_command(args):
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        errors="replace"
    )

    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout)[-3000:]
        )

    return result.stdout


def video_duration(path):
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            output = run_command([
                ffprobe,
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path)
            ])
            return max(0.0, float(output.strip()))
        except Exception:
            pass

    # PyAV fallback (in-process video demuxing)
    try:
        import av
        with av.open(str(path)) as container:
            if container.duration:
                # av container duration is in microseconds
                return max(0.0, float(container.duration) / 1000000.0)
    except Exception:
        pass

    raise RuntimeError(
        "Could not detect video duration. Please ensure FFmpeg/FFprobe is installed (e.g. 'winget install Gyan.FFmpeg')."
    )


def transcribe_video(path, model_size="base"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "Install the required libraries first (faster-whisper)."
        )

    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8"
    )

    segments, info = model.transcribe(
        str(path),
        vad_filter=True
    )

    transcript = []

    for segment in segments:
        text = (segment.text or "").strip()

        if text:
            transcript.append({
                "start": round(float(segment.start), 2),
                "end": round(float(segment.end), 2),
                "text": text
            })

    return transcript, getattr(info, "language", "unknown")


def score_text(text):
    text_lower = text.lower()
    score = 0

    keywords = [
        "wow", "what", "surprise", "unbelievable",
        "money", "million", "billion", "challenge", "secret",
        "crazy", "amazing", "insane", "never",
        "truth", "why", "how", "actually",
        "love", "hate", "win", "lose",
        "danger", "hack", "mistake", "warning",
        "shocking", "gamechanger", "critical",
        "lesson", "stop", "best", "worst", "proven", "tips", "viral"
    ]

    for word in keywords:
        if word in text_lower:
            score += 1

    if "!" in text:
        score += 2

    if "?" in text:
        score += 1

    word_count = len(text.split())
    if word_count >= 8:
        score += 1
    if word_count >= 16:
        score += 1

    return score


def make_title(text):
    words = re.findall(r"[A-Za-z0-9']+", text)

    if not words:
        return "Interesting Moment"

    title = " ".join(words[:7])

    return title[:58]


def build_moments(segments, duration, clip_length=35):
    moments = []

    for segment in segments:
        center = (
            segment["start"] + segment["end"]
        ) / 2

        start = max(0, center - clip_length * 0.35)
        end = min(duration, start + clip_length)

        text = " ".join(
            item["text"]
            for item in segments
            if item["start"] < end
            and item["end"] > start
        )

        score = score_text(text)

        if score > 0:
            moments.append({
                "start": round(start, 2),
                "end": round(end, 2),
                "score": score,
                "title": make_title(text),
                "text": text[:600]
            })

    moments.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    selected = []

    for moment in moments:
        if all(
            abs(moment["start"] - other["start"])
            > clip_length * 0.6
            for other in selected
        ):
            selected.append(moment)

        if len(selected) >= 8:
            break

    return sorted(
        selected,
        key=lambda item: item["start"]
    )


def srt_timestamp(seconds):
    milliseconds = int(round(seconds * 1000))

    hours = milliseconds // 3600000
    milliseconds %= 3600000

    minutes = milliseconds // 60000
    milliseconds %= 60000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:{minutes:02}:"
        f"{secs:02},{milliseconds:03}"
    )


def create_clip(
    source,
    start,
    end,
    segments,
    output_path
):
    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise RuntimeError(
            "FFmpeg not found. Install FFmpeg first."
        )

    if end <= start:
        raise RuntimeError("Invalid clip duration.")

    subtitle_path = WORK_DIR / (
        f"{uuid.uuid4().hex}.srt"
    )

    subtitle_rows = []

    index = 1

    for segment in segments:
        left = max(segment["start"], start)
        right = min(segment["end"], end)

        if right <= left:
            continue

        text = (
            segment["text"]
            .replace("-->", "→")
            .replace("\n", " ")
            .strip()
        )

        subtitle_rows.append(
            f"{index}\n"
            f"{srt_timestamp(left - start)} --> "
            f"{srt_timestamp(right - start)}\n"
            f"{text}\n"
        )

        index += 1

    subtitle_path.write_text(
        "\n".join(subtitle_rows),
        encoding="utf-8"
    )

    subtitle_filter_path = (
        str(subtitle_path.resolve())
        .replace("\\", "/")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )

    video_filter = (
        "scale=1080:1920:"
        "force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        f"subtitles='{subtitle_filter_path}':"
        "force_style='FontName=Arial,"
        "FontSize=18,Outline=2,Alignment=2,MarginV=80'"
    )

    try:
        run_command([
            ffmpeg,
            "-y",
            "-ss", str(start),
            "-i", str(source),
            "-t", str(end - start),
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path)
        ])

    finally:
        subtitle_path.unlink(missing_ok=True)


def download_youtube_video(url, output_dir, video_id):
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp library is required to process YouTube videos.")

    has_ffmpeg = bool(shutil.which("ffmpeg"))
    format_pref = (
        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        if has_ffmpeg else
        "best[ext=mp4]/best"
    )

    outtmpl_pattern = str(output_dir / f"{video_id}_%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl_pattern,
        "format": format_pref,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError("Failed to extract video information from YouTube URL.")

        # Locate the downloaded file in output_dir
        actual_path = None
        for file in output_dir.glob(f"{video_id}_*"):
            if file.is_file():
                actual_path = file
                break

        if not actual_path:
            filename_prepared = Path(ydl.prepare_filename(info))
            if filename_prepared.exists():
                actual_path = filename_prepared
            else:
                raise RuntimeError("Could not find downloaded YouTube video file.")

        title = info.get("title") or "YouTube Video"
        duration = float(info.get("duration") or 0.0)
        thumbnail = info.get("thumbnail") or ""

        if duration <= 0.0:
            try:
                duration = video_duration(actual_path)
            except Exception:
                duration = 60.0

        return actual_path.name, title, round(duration, 2), thumbnail


@app.route("/")
def index():
    video_id = request.args.get("video_id")
    state = None

    if video_id:
        state_path = WORK_DIR / f"{video_id}.json"

        if state_path.exists():
            state = json.loads(
                state_path.read_text(encoding="utf-8")
            )

    system_status = {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "whisper": True
    }

    return render_template(
        "index.html",
        state=state,
        video_id=video_id,
        system_status=system_status
    )


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(
        UPLOAD_DIR,
        filename
    )


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("video")

    if not file or not file.filename:
        flash("Choose a video first.", "error")
        return redirect(url_for("index"))

    filename = secure_filename(file.filename)

    if not allowed_video(filename):
        flash("Unsupported video format.", "error")
        return redirect(url_for("index"))

    video_id = uuid.uuid4().hex[:12]

    stored_name = f"{video_id}_{filename}"
    path = UPLOAD_DIR / stored_name

    file.save(path)

    try:
        duration = video_duration(path)

    except Exception as error:
        path.unlink(missing_ok=True)
        flash(str(error), "error")
        return redirect(url_for("index"))

    state = {
        "video_id": video_id,
        "filename": stored_name,
        "original_name": filename,
        "duration": round(duration, 2),
        "segments": [],
        "language": "not transcribed",
        "moments": [],
        "clips": []
    }

    (
        WORK_DIR / f"{video_id}.json"
    ).write_text(
        json.dumps(state, indent=2),
        encoding="utf-8"
    )

    flash("Video uploaded successfully!", "success")

    return redirect(
        url_for("index", video_id=video_id)
    )


@app.route("/youtube-process", methods=["POST"])
def youtube_process():
    url = request.form.get("youtube_url", "").strip()

    if not url:
        flash("Please enter a YouTube video URL.", "error")
        return redirect(url_for("index"))

    if not ("youtube.com" in url or "youtu.be" in url):
        flash("Please enter a valid YouTube or YouTube Shorts URL.", "error")
        return redirect(url_for("index"))

    video_id = uuid.uuid4().hex[:12]
    auto_transcribe = request.form.get("auto_transcribe") == "1"
    model_size = request.form.get("model_size", "base")
    if model_size not in {"tiny", "base", "small"}:
        model_size = "base"

    try:
        stored_name, title, duration, thumbnail = download_youtube_video(
            url,
            UPLOAD_DIR,
            video_id
        )
    except Exception as error:
        flash(f"YouTube processing error: {error}", "error")
        return redirect(url_for("index"))

    state = {
        "video_id": video_id,
        "filename": stored_name,
        "original_name": title,
        "duration": duration,
        "source_type": "youtube",
        "source_url": url,
        "thumbnail": thumbnail,
        "segments": [],
        "language": "not transcribed",
        "moments": [],
        "clips": []
    }

    if auto_transcribe:
        try:
            source = UPLOAD_DIR / stored_name
            segments, language = transcribe_video(source, model_size)
            state["segments"] = segments
            state["language"] = language
            state["moments"] = build_moments(segments, duration)
            flash(
                f"YouTube video '{title[:45]}' downloaded & transcribed with {len(state['moments'])} highlights!",
                "success"
            )
        except Exception as error:
            flash(
                f"YouTube video downloaded, but auto-transcription failed: {error}",
                "error"
            )
    else:
        flash(
            f"YouTube video '{title[:50]}' downloaded successfully!",
            "success"
        )

    (
        WORK_DIR / f"{video_id}.json"
    ).write_text(
        json.dumps(state, indent=2),
        encoding="utf-8"
    )

    return redirect(
        url_for("index", video_id=video_id)
    )


@app.route("/transcribe/<video_id>", methods=["POST"])
def transcribe(video_id):
    state_path = WORK_DIR / f"{video_id}.json"

    if not state_path.exists():
        flash("Project not found.", "error")
        return redirect(url_for("index"))

    state = json.loads(
        state_path.read_text(encoding="utf-8")
    )

    source = UPLOAD_DIR / state["filename"]

    model_size = request.form.get("model_size", "base")

    if model_size not in {"tiny", "base", "small"}:
        model_size = "base"

    try:
        segments, language = transcribe_video(
            source,
            model_size
        )

        state["segments"] = segments
        state["language"] = language

        state["moments"] = build_moments(
            segments,
            state["duration"]
        )

        state["clips"] = []

        state_path.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8"
        )

        flash("AI transcription completed!", "success")

    except Exception as error:
        flash(
            f"Transcription failed: {error}",
            "error"
        )

    return redirect(
        url_for("index", video_id=video_id)
    )


@app.route("/make-clips/<video_id>", methods=["POST"])
def make_clips(video_id):
    state_path = WORK_DIR / f"{video_id}.json"

    if not state_path.exists():
        flash("Project not found.", "error")
        return redirect(url_for("index"))

    state = json.loads(
        state_path.read_text(encoding="utf-8")
    )

    source = UPLOAD_DIR / state["filename"]

    starts = request.form.getlist("start[]")
    ends = request.form.getlist("end[]")
    titles = request.form.getlist("title[]")

    chosen = []

    for index, (start_text, end_text) in enumerate(
        zip(starts, ends)
    ):
        try:
            start = max(0, float(start_text))
            end = min(
                state["duration"],
                float(end_text)
            )

        except ValueError:
            continue

        if end > start and end - start >= 3:
            title = (
                titles[index]
                if index < len(titles)
                else f"Clip {index + 1}"
            )

            chosen.append((start, end, title))

    if not chosen:
        flash("Select a valid clip first.", "error")
        return redirect(
            url_for("index", video_id=video_id)
        )

    state["clips"] = []

    for number, (start, end, title) in enumerate(
        chosen[:8],
        start=1
    ):
        output_name = (
            f"{video_id}_clip_{number:02}.mp4"
        )

        output_path = OUTPUT_DIR / output_name

        try:
            create_clip(
                source,
                start,
                end,
                state["segments"],
                output_path
            )

            state["clips"].append({
                "filename": output_name,
                "title": title,
                "start": start,
                "end": end,
                "duration": round(end - start, 2)
            })

        except Exception as error:
            flash(str(error), "error")
            break

    state_path.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8"
    )

    if state["clips"]:
        flash("Your clips are ready!", "success")

    return redirect(
        url_for("index", video_id=video_id)
    )


@app.route("/outputs/<path:filename>")
def output_file(filename):
    return send_from_directory(
        OUTPUT_DIR,
        filename,
        as_attachment=True
    )


@app.errorhandler(413)
def too_large(error):
    flash("Video exceeds the upload limit.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    # Private on this laptop by default.
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )