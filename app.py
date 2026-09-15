import os
import re
import glob
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import yt_dlp
import imageio_ffmpeg


app = Flask(__name__)
CORS(app)

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

DOWNLOAD_TIMEOUT = 300


# --------------------------------------------------
# BASIC URL VALIDATION
# --------------------------------------------------

def validate_url(url):
    if not isinstance(url, str):
        return False

    url = url.strip()

    if not url:
        return False

    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        if not parsed.netloc:
            return False

        return True

    except Exception:
        return False


# --------------------------------------------------
# FFmpeg helpers
# --------------------------------------------------

def run_ffmpeg(args, timeout=DOWNLOAD_TIMEOUT):
    command = [FFMPEG] + args

    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout
    )


def media_has_video_and_audio(path):
    """
    Uses FFmpeg's input inspection.
    Returns:
        (True, True)  -> video + audio
        (True, False) -> video only
        (False, True) -> audio only
        (False, False) -> invalid
    """

    try:
        result = run_ffmpeg(
            [
                "-hide_banner",
                "-i",
                path
            ],
            timeout=60
        )

        text = result.stderr or ""

        has_video = bool(re.search(r"\bVideo:", text))
        has_audio = bool(re.search(r"\bAudio:", text))

        return has_video, has_audio

    except Exception:
        return False, False


# --------------------------------------------------
# Find downloaded media
# --------------------------------------------------

def find_media_files(folder):
    candidates = []

    for root, dirs, files in os.walk(folder):

        for filename in files:

            full_path = os.path.join(root, filename)

            if not os.path.isfile(full_path):
                continue

            if filename.endswith((
                ".part",
                ".ytdl",
                ".tmp"
            )):
                continue

            try:
                size = os.path.getsize(full_path)

                if size > 1000:
                    candidates.append(full_path)

            except OSError:
                pass

    candidates.sort(
        key=lambda p: os.path.getsize(p),
        reverse=True
    )

    return candidates


# --------------------------------------------------
# Create compatible MP4
# --------------------------------------------------

def make_mp4(input_file, output_file):

    result = run_ffmpeg(
        [
            "-y",
            "-hide_banner",

            "-i",
            input_file,

            "-map",
            "0:v:0",

            "-map",
            "0:a:0",

            # Re-encode video to universally compatible H.264.
            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "23",

            "-pix_fmt",
            "yuv420p",

            # Audio
            "-c:a",
            "aac",

            "-b:a",
            "192k",

            # Better MP4 playback
            "-movflags",
            "+faststart",

            output_file
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg MP4 conversion failed."
        )

    if not os.path.exists(output_file):
        raise RuntimeError(
            "MP4 file was not created."
        )

    if os.path.getsize(output_file) < 1000:
        raise RuntimeError(
            "Generated MP4 is empty."
        )

    return output_file


# --------------------------------------------------
# Create MP3
# --------------------------------------------------

def make_mp3(input_file, output_file):

    result = run_ffmpeg(
        [
            "-y",
            "-hide_banner",

            "-i",
            input_file,

            "-vn",

            "-c:a",
            "libmp3lame",

            "-b:a",
            "192k",

            output_file
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg MP3 conversion failed."
        )

    if not os.path.exists(output_file):
        raise RuntimeError(
            "MP3 file was not created."
        )

    if os.path.getsize(output_file) < 1000:
        raise RuntimeError(
            "Generated MP3 is empty."
        )

    return output_file


# --------------------------------------------------
# yt-dlp options
# --------------------------------------------------

def base_ydl_options(folder):

    return {
        "outtmpl": os.path.join(
            folder,
            "%(id)s.%(ext)s"
        ),

        "noplaylist": True,

        # Prefer video+audio, otherwise single-file media.
        "format": "bv*+ba/b",

        "merge_output_format": "mp4",

        "ffmpeg_location": FFMPEG,

        "retries": 3,

        "fragment_retries": 3,

        "socket_timeout": 30,

        "quiet": True,

        "no_warnings": True,

        "restrictfilenames": True,

        # Normal browser-like request headers.
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9"
        }
    }


# --------------------------------------------------
# Error formatting
# --------------------------------------------------

def clean_error(error):

    text = str(error)

    if len(text) > 500:
        text = text[:500] + "..."

    return text


# --------------------------------------------------
# STATUS
# --------------------------------------------------

@app.get("/api/status")
def status():

    return jsonify({
        "online": True,
        "service": "Video Extractor",
        "ffmpeg": os.path.basename(FFMPEG)
    })


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.get("/")
def home():

    return send_file(
        os.path.join(
            os.path.dirname(__file__),
            "public",
            "index.html"
        )
    )


# --------------------------------------------------
# VIDEO DOWNLOAD
# --------------------------------------------------

@app.post("/api/download")
def download_video():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()

    if not validate_url(url):

        return jsonify({
            "error": "Please enter a valid http/https media URL."
        }), 400

    temp_dir = tempfile.mkdtemp(
        prefix="video-extractor-"
    )

    try:

        options = base_ydl_options(temp_dir)

        # Extract/download public or otherwise authorized media.
        with yt_dlp.YoutubeDL(options) as ydl:

            ydl.download([url])

        files = find_media_files(temp_dir)

        if not files:

            raise RuntimeError(
                "No media file was downloaded."
            )

        source_file = None

        # Find an actual video file.
        for candidate in files:

            has_video, has_audio = (
                media_has_video_and_audio(candidate)
            )

            if has_video:
                source_file = candidate
                break

        if not source_file:

            raise RuntimeError(
                "The source did not provide a usable video file."
            )

        has_video, has_audio = (
            media_has_video_and_audio(source_file)
        )

        if not has_audio:

            raise RuntimeError(
                "The downloaded media does not contain an audio stream."
            )

        final_file = os.path.join(
            temp_dir,
            "video.mp4"
        )

        make_mp4(
            source_file,
            final_file
        )

        # Final verification.
        final_video, final_audio = (
            media_has_video_and_audio(final_file)
        )

        if not final_video or not final_audio:

            raise RuntimeError(
                "Final MP4 validation failed."
            )

        response = send_file(
            final_file,
            mimetype="video/mp4",
            as_attachment=True,
            download_name="video.mp4"
        )

        # Remove temp directory after response is closed.
        @response.call_on_close
        def cleanup():

            try:
                shutil.rmtree(
                    temp_dir,
                    ignore_errors=True
                )
            except Exception:
                pass

        return response

    except yt_dlp.utils.DownloadError as e:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        return jsonify({
            "error": (
                "The media could not be extracted. "
                + clean_error(e)
            )
        }), 422

    except Exception as e:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        return jsonify({
            "error": clean_error(e)
        }), 500


# --------------------------------------------------
# MP3 CONVERSION
# --------------------------------------------------

@app.post("/api/convert/mp3")
def convert_mp3():

    data = request.get_json(silent=True) or {}

    url = data.get("url", "").strip()

    if not validate_url(url):

        return jsonify({
            "error": "Please enter a valid http/https media URL."
        }), 400

    temp_dir = tempfile.mkdtemp(
        prefix="video-extractor-mp3-"
    )

    try:

        options = base_ydl_options(temp_dir)

        # Audio is enough for MP3.
        options["format"] = "ba/b"

        with yt_dlp.YoutubeDL(options) as ydl:

            ydl.download([url])

        files = find_media_files(temp_dir)

        if not files:

            raise RuntimeError(
                "No audio file was downloaded."
            )

        source_file = None

        for candidate in files:

            has_video, has_audio = (
                media_has_video_and_audio(candidate)
            )

            if has_audio:

                source_file = candidate
                break

        if not source_file:

            raise RuntimeError(
                "The source did not provide a usable audio stream."
            )

        final_file = os.path.join(
            temp_dir,
            "audio.mp3"
        )

        make_mp3(
            source_file,
            final_file
        )

        response = send_file(
            final_file,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name="audio.mp3"
        )

        @response.call_on_close
        def cleanup():

            try:
                shutil.rmtree(
                    temp_dir,
                    ignore_errors=True
                )
            except Exception:
                pass

        return response

    except yt_dlp.utils.DownloadError as e:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        return jsonify({
            "error": (
                "The audio could not be extracted. "
                + clean_error(e)
            )
        }), 422

    except Exception as e:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        return jsonify({
            "error": clean_error(e)
        }), 500


# --------------------------------------------------
# LOCAL RUN
# --------------------------------------------------

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
