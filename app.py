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
        files = glob.glob(
            os.path.join(folder, f"*.{ext}")
        )

        if files:
            return files[0]

    return None


def fix_audio_compatibility(input_path):
    """
    Re-encode audio to AAC while keeping the video stream unchanged.
    This helps make the MP4 more compatible with browsers/devices.
    """

    base, ext = os.path.splitext(input_path)

    output_path = f"{base}_fixed{ext}"

    result = subprocess.run(
        [
            FFMPEG_EXE,
            "-y",
            "-i",
            input_path,

            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",

            "-c:v",
            "copy",

            "-c:a",
            "aac",

            "-b:a",
            "192k",

            "-movflags",
            "+faststart",

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


def download_media(url, temp_dir, audio_only=False):
    """
    Download media using yt-dlp.
    FFmpeg and FFprobe are provided by the Docker image.
    """

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

        # IMPORTANT:
        # yt-dlp will find both ffmpeg and ffprobe here.
        "ffmpeg_location": FFMPEG_PATH,

        # Explicitly tell yt-dlp where ffprobe is.
        "postprocessor_args": [
            "-loglevel",
            "warning"
        ]
    }


    # =====================================================
    # OPTIONAL COOKIES
    # =====================================================

    if os.path.exists(COOKIES_FILE):
        print("Using cookies file:", COOKIES_FILE)

        options["cookiefile"] = COOKIES_FILE


    # =====================================================
    # AUDIO ONLY
    # =====================================================

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


    # =====================================================
    # VIDEO
    # =====================================================

    else:

        options.update({

            # Best available video + audio.
            # yt-dlp will merge them using FFmpeg.
            "format": "bv*+ba/b",

            "merge_output_format": "mp4"
        })


    print("FFmpeg:", FFMPEG_EXE)
    print("FFprobe:", FFPROBE_EXE)

    print("Downloading:", url)

    with yt_dlp.YoutubeDL(options) as ydl:

        ydl.extract_info(
            url,
            download=True
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

        if not data:

            return jsonify({
                "error": "No data received."
            }), 400


        url = data.get(
            "url",
            ""
        ).strip()


        if not url:

            return jsonify({
                "error": "Please enter a URL."
            }), 400


        # Create temporary folder
        temp_dir = tempfile.mkdtemp(
            prefix="video-"
        )


        # Download
        download_media(
            url,
            temp_dir,
            audio_only=False
        )


        # Find downloaded file
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
        # FIX MP4 AUDIO
        # =================================================

        if media_file.lower().endswith(".mp4"):

            fixed_file = fix_audio_compatibility(
                media_file
            )

            media_file = fixed_file


        # =================================================
        # SEND FILE
        # =================================================

        response = send_file(

            media_file,

            as_attachment=True,

            download_name="video.mp4",

            mimetype="video/mp4"
        )


        return response


    except Exception as error:

        print(
            "DOWNLOAD ERROR:",
            str(error)
        )

        return jsonify({
            "error": str(error)
        }), 400


# =========================================================
# MP3 CONVERTER API
# =========================================================

@app.route("/api/convert/mp3", methods=["POST"])
def convert_mp3():

    temp_dir = None

    try:

        data = request.get_json(
            silent=True
        )


        if not data:

            return jsonify({
                "error": "No data received."
            }), 400


        url = data.get(
            "url",
            ""
        ).strip()


        if not url:

            return jsonify({
                "error": "Please enter a URL."
            }), 400


        # Create temporary folder
        temp_dir = tempfile.mkdtemp(
            prefix="audio-"
        )


        # Download and convert
        download_media(
            url,
            temp_dir,
            audio_only=True
        )


        # Find MP3
        mp3_file = find_file(
            temp_dir,
            [
                "mp3"
            ]
        )


        if not mp3_file:

            raise Exception(
                "MP3 file not found."
            )


        # =================================================
        # SEND MP3
        # =================================================

        response = send_file(

            mp3_file,

            as_attachment=True,

            download_name="audio.mp3",

            mimetype="audio/mpeg"
        )


        return response


    except Exception as error:

        print(
            "MP3 ERROR:",
            str(error)
        )

        return jsonify({
            "error": str(error)
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
