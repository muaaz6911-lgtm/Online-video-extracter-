import os
import glob
import shutil
import tempfile

import yt_dlp

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


# =========================
# FRONTEND
# =========================

@app.route("/")
def home():
    return send_from_directory("public", "index.html")


@app.route("/<path:filename>")
def frontend_files(filename):
    return send_from_directory("public", filename)


# =========================
# FIND FILE
# =========================

def find_file(folder, extensions):
    for ext in extensions:
        files = glob.glob(
            os.path.join(folder, f"*.{ext}")
        )

        if files:
            return files[0]

    return None


# =========================
# DOWNLOAD WITH YT-DLP
# =========================

def download_media(url, temp_dir, audio_only=False):

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
    }

    if audio_only:

        options.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        })

    else:

        options.update({
            "format": "best[ext=mp4]/best"
        })

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.extract_info(
            url,
            download=True
        )


# =========================
# STATUS
# =========================

@app.route("/api/status")
def status():

    return jsonify({
        "status": "online"
    })


# =========================
# VIDEO DOWNLOAD
# =========================

@app.route(
    "/api/download",
    methods=["POST"]
)
def download_video():

    temp_dir = None

    try:

        data = request.get_json()

        url = data.get(
            "url",
            ""
        ).strip()

        if not url:
            return jsonify({
                "error": "Please enter a URL."
            }), 400


        temp_dir = tempfile.mkdtemp()

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


        return send_file(
            media_file,
            as_attachment=True,
            download_name="video.mp4"
        )


    except Exception as error:

        print(
            "DOWNLOAD ERROR:",
            error
        )

        return jsonify({
            "error": str(error)
        }), 400


# =========================
# MP3 DOWNLOAD
# =========================

@app.route(
    "/api/convert/mp3",
    methods=["POST"]
)
def convert_mp3():

    try:

        data = request.get_json()

        url = data.get(
            "url",
            ""
        ).strip()

        if not url:
            return jsonify({
                "error": "Please enter a URL."
            }), 400


        temp_dir = tempfile.mkdtemp()

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


        return send_file(
            mp3_file,
            as_attachment=True,
            download_name="audio.mp3",
            mimetype="audio/mpeg"
        )


    except Exception as error:

        print(
            "MP3 ERROR:",
            error
        )

        return jsonify({
            "error": str(error)
        }), 400


# =========================
# RUN
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
