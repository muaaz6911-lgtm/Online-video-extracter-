import os
import glob
import subprocess
import tempfile

import yt_dlp
import static_ffmpeg

from flask import (
    Flask,
    request,
    jsonify,
    send_file,
    send_from_directory
)

from flask_cors import CORS


# =========================
# APP
# =========================

app = Flask(__name__)

CORS(app)


# =========================
# FFMPEG + COOKIES
# =========================

# static_ffmpeg downloads/caches BOTH ffmpeg and ffprobe binaries
# and returns their paths. imageio-ffmpeg only gave us ffmpeg,
# which is why "unable to obtain file audio codec with ffprobe"
# was happening during MP3 conversion.
FFMPEG_EXE, FFPROBE_EXE = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()

# yt-dlp accepts a directory containing both ffmpeg + ffprobe here.
FFMPEG_PATH = os.path.dirname(FFMPEG_EXE)

# Netscape-format cookies.txt exported from your browser.
# Upload this as a Render "Secret File" (do NOT commit to git).
COOKIES_FILE = os.environ.get("COOKIES_FILE", "cookies.txt")


# =========================
# FRONTEND
# =========================

@app.route("/")
def home():

    return send_from_directory(
        "public",
        "index.html"
    )


@app.route("/<path:filename>")
def frontend_files(filename):

    return send_from_directory(
        "public",
        filename
    )


# =========================
# FIND FILE
# =========================

def find_file(folder, extensions):

    for ext in extensions:

        files = glob.glob(
            os.path.join(
                folder,
                f"*.{ext}"
            )
        )

        if files:

            return files[0]

    return None


# =========================
# FIX AUDIO COMPATIBILITY
# =========================
# yt-dlp's merger copies streams as-is ("-c copy"). If the source
# audio codec (e.g. Opus, from a webm audio track) isn't natively
# supported by MP4 on the viewer's device/player, the video plays
# with NO SOUND even though an audio track technically exists.
# This re-encodes just the audio to AAC (universally compatible),
# keeping the video stream untouched (fast, no quality loss).

def fix_audio_compatibility(input_path):

    output_path = input_path.replace(
        ".mp4",
        "_fixed.mp4"
    )

    result = subprocess.run(
        [
            FFMPEG_EXE,
            "-y",
            "-i", input_path,
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
        # if the fix step fails for some reason, fall back to the
        # original file rather than breaking the whole download
        print(
            "AUDIO FIX FAILED:",
            result.stderr.decode(errors="ignore")[-400:]
        )
        return input_path

    return output_path


# =========================
# DOWNLOAD WITH YT-DLP
# =========================

def download_media(
    url,
    temp_dir,
    audio_only=False
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

        # FIX: tell yt-dlp where ffmpeg is, so it can actually
        # merge the separate video-only and audio-only streams
        # into one file with sound.
        "ffmpeg_location": FFMPEG_PATH

    }


    # Use cookies if a cookies.txt file has been uploaded
    # (fixes "Sign in to confirm you're not a bot" on YouTube).
    if os.path.exists(COOKIES_FILE):

        options["cookiefile"] = COOKIES_FILE


    # =====================
    # MP3 DOWNLOAD
    # =====================

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


    # =====================
    # VIDEO + AUDIO
    # =====================

    else:

        options.update({

            # FIX: "bv*+ba/b" is more reliable than restricting to
            # ext=mp4 — the old format string sometimes fell back
            # to a video-only stream on sites like Instagram.
            "format": "bv*+ba/b",

            "merge_output_format": "mp4"

        })


    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        ydl.extract_info(
            url,
            download=True
        )


# =========================
# API STATUS
# =========================

@app.route(
    "/api/status",
    methods=["GET"]
)

def status():

    return jsonify({

        "status": "online",

        "service": "Video Extractor API"

    })


# =========================
# VIDEO DOWNLOAD API
# =========================

@app.route(
    "/api/download",
    methods=["POST"]
)

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


        # Download video + audio

        download_media(

            url,

            temp_dir,

            audio_only=False

        )


        # Find downloaded video

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


        # Fix audio codec compatibility (this is what was
        # causing "video plays, but no sound")
        if media_file.endswith(".mp4"):

            media_file = fix_audio_compatibility(
                media_file
            )


        # Send video

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


# =========================
# MP3 CONVERSION API
# =========================

@app.route(
    "/api/convert/mp3",
    methods=["POST"]
)

def convert_mp3():

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


        # Find MP3 file

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


        # Send MP3

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


# =========================
# RUN APP
# =========================

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
    
