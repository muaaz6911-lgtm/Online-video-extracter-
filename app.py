import os
import glob
import subprocess
import tempfile
import shutil

import yt_dlp

from flask import (
    Flask,
    request,
    jsonify,
    send_file,
    send_from_directory
)

from flask_cors import CORS


app = Flask(__name__)
CORS(app)


# =========================================================
# FFMPEG / FFPROBE
# =========================================================

FFMPEG_EXE = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
FFPROBE_EXE = shutil.which("ffprobe") or "/usr/bin/ffprobe"
FFMPEG_PATH = os.path.dirname(FFMPEG_EXE)

COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")
COOKIES_YOUTUBE_FILE = os.environ.get(
    "COOKIES_YOUTUBE_FILE",
    "cookies_youtube.txt"
)
COOKIES_INSTAGRAM_FILE = os.environ.get(
    "COOKIES_INSTAGRAM_FILE",
    "cookies_instagram.txt"
)


# =========================================================
# FRONTEND
# =========================================================

@app.route("/")
def home():
    return send_from_directory("public", "index.html")


@app.route("/<path:filename>")
def frontend_files(filename):
    return send_from_directory("public", filename)


# =========================================================
# HELPERS
# =========================================================

def find_file(folder, extensions):
    for ext in extensions:
        files = glob.glob(os.path.join(folder, f"*.{ext}"))
        if files:
            return files[0]
    return None


def pick_cookies_file(url):
    url_lower = url.lower()

    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        if os.path.exists(COOKIES_YOUTUBE_FILE):
            return COOKIES_YOUTUBE_FILE

    if "instagram.com" in url_lower:
        if os.path.exists(COOKIES_INSTAGRAM_FILE):
            return COOKIES_INSTAGRAM_FILE

    if os.path.exists(COOKIES_FILE):
        return COOKIES_FILE

    return None


def has_audio_stream(path):
    try:
        result = subprocess.run(
            [
                FFPROBE_EXE,
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=index",
                "-of", "csv=p=0",
                path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        return bool(result.stdout.strip())

    except Exception as e:
        print("ffprobe check failed:", e)
        return True


def fix_audio_compatibility(input_path):
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_fixed{ext}"

    result = subprocess.run(
        [
            FFMPEG_EXE,
            "-y",
            "-i", input_path,
            "-map", "0:v:0?",
            "-map", "0:a:0?",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            output_path
        ],
        capture_output=True,
        timeout=180
    )

    if result.returncode != 0 or not os.path.exists(output_path):
        print(
            "AUDIO FIX FAILED:",
            result.stderr.decode(errors="ignore")[-2000:]
        )
        return input_path

    return output_path


def build_ydl_options(
    url,
    temp_dir,
    audio_only,
    format_override=None
):
    output_template = os.path.join(
        temp_dir,
        "media.%(ext)s"
    )

    options = {
        "outtmpl": output_template,
        "noplaylist": True,
        "restrictfilenames": True,
        "quiet": False,
        "no_warnings": False,

        "ffmpeg_location": FFMPEG_PATH,

        "postprocessor_args": [
            "-loglevel",
            "warning"
        ],

        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 60,
        "extractor_retries": 5,
        "file_access_retries": 5,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        },

        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android",
                    "web",
                    "ios"
                ]
            }
        },

        "progress": True,

        "progress_template":
            "%(progress.total_size)s at %(progress._speed_str)s",

        "geo_bypass": True,
        "geo_bypass_country": "US",

        "check_fragments": True,
    }

    cookies_file = pick_cookies_file(url)

    if cookies_file:
        print(
            "Using cookies file:",
            cookies_file
        )
        options["cookiefile"] = cookies_file

    if audio_only:
        options.update({
            "format": "bestaudio/best",

            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192"
                }
            ]
        })

    else:
        options.update({
            "format":
                format_override or "bv*+ba/b",

            "merge_output_format": "mp4"
        })

    return options


def download_media(
    url,
    temp_dir,
    audio_only=False,
    format_override=None
):
    options = build_ydl_options(
        url,
        temp_dir,
        audio_only,
        format_override
    )

    print("FFmpeg:", FFMPEG_EXE)
    print("FFprobe:", FFPROBE_EXE)
    print("Downloading:", url)

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(
            url,
            download=True
        )


def cleanup_temp_dir(path):
    shutil.rmtree(
        path,
        ignore_errors=True
    )


# =========================================================
# STATUS API
# =========================================================

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "status": "online",
        "service": "Video Extractor API",
        "ffmpeg": FFMPEG_EXE,
        "ffprobe": FFPROBE_EXE
    })


# =========================================================
# VIDEO DOWNLOAD API
# =========================================================

@app.route("/api/download", methods=["POST"])
def download_video():

    temp_dir = None

    try:

        data = request.get_json(
            silent=True
        )

        # FIX:
        # Make sure frontend sends a JSON object
        # instead of a JSON string.
        if not isinstance(data, dict):
            return jsonify({
                "error":
                    "Invalid request format. "
                    "Expected JSON object."
            }), 400

        url = data.get(
            "url",
            ""
        ).strip()

        if not url:
            return jsonify({
                "error":
                    "Please enter a URL."
            }), 400

        temp_dir = tempfile.mkdtemp(
            prefix="video-"
        )

        # Download best video + audio
        download_media(
            url,
            temp_dir,
            audio_only=False
        )

        media_file = find_file(
            temp_dir,
            [
                "mp4",
                "webm",
                "mkv",
                "mov"
            ]
        )

        if not media_file:
            raise Exception(
                "Video file not found."
            )

        # =================================================
        # CHECK AUDIO
        # =================================================

        if not has_audio_stream(
            media_file
        ):

            print(
                "No audio stream detected, "
                "retrying with progressive format..."
            )

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )

            temp_dir = tempfile.mkdtemp(
                prefix="video-retry-"
            )

            try:

                download_media(
                    url,
                    temp_dir,
                    audio_only=False,
                    format_override=(
                        "best"
                        "[acodec!=none]"
                        "[vcodec!=none]"
                        "/best"
                    )
                )

                retry_file = find_file(
                    temp_dir,
                    [
                        "mp4",
                        "webm",
                        "mkv",
                        "mov"
                    ]
                )

                if retry_file:
                    media_file = retry_file

            except Exception as retry_error:

                print(
                    "Audio retry failed, "
                    "using original file:",
                    retry_error
                )

        # =================================================
        # FIX MP4 AUDIO COMPATIBILITY
        # =================================================

        if media_file.lower().endswith(
            ".mp4"
        ):

            media_file = fix_audio_compatibility(
                media_file
            )

        # =================================================
        # SEND FILE
        # =================================================

        response = send_file(
            media_file,
            as_attachment=True,
            download_name="video.mp4",
            mimetype="video/mp4"
        )

        response.call_on_close(
            lambda: cleanup_temp_dir(
                temp_dir
            )
        )

        return response

    except Exception as error:

        print(
            "DOWNLOAD ERROR:",
            str(error)
        )

        if temp_dir:
            cleanup_temp_dir(
                temp_dir
            )

        return jsonify({
            "error":
                str(error)
        }), 400


# =========================================================
# MP3 CONVERTER API
# =========================================================

@app.route(
    "/api/convert/mp3",
    methods=["POST"]
)
def convert_mp3():

    temp_dir = None

    try:

        data = request.get_json(
            silent=True
        )

        # FIX:
        # Make sure frontend sends a JSON object
        if not isinstance(data, dict):
            return jsonify({
                "error":
                    "Invalid request format. "
                    "Expected JSON object."
            }), 400

        url = data.get(
            "url",
            ""
        ).strip()

        if not url:
            return jsonify({
                "error":
                    "Please enter a URL."
            }), 400

        temp_dir = tempfile.mkdtemp(
            prefix="audio-"
        )

        download_media(
            url,
            temp_dir,
            audio_only=True
        )

        mp3_file = find_file(
            temp_dir,
            ["mp3"]
        )

        if not mp3_file:
            raise Exception(
                "MP3 file not found."
            )

        response = send_file(
            mp3_file,
            as_attachment=True,
            download_name="audio.mp3",
            mimetype="audio/mpeg"
        )

        response.call_on_close(
            lambda: cleanup_temp_dir(
                temp_dir
            )
        )

        return response

    except Exception as error:

        print(
            "MP3 ERROR:",
            str(error)
        )

        if temp_dir:
            cleanup_temp_dir(
                temp_dir
            )

        return jsonify({
            "error":
                str(error)
        }), 400


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
        )
