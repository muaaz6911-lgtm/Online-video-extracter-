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


COOKIES_FILE = os.environ.get(
    "COOKIES_FILE",
    "cookies.txt"
)

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


# =========================================================
# HELPERS
# =========================================================

def find_file(folder, extensions):
    """
    Find the first file matching one of the supplied extensions.
    """

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


def pick_cookies_file(url):
    """
    Use an existing cookies file when present.
    Does not create or extract cookies.
    """

    url_lower = url.lower()

    if (
        "youtube.com" in url_lower
        or "youtu.be" in url_lower
    ):
        if os.path.exists(
            COOKIES_YOUTUBE_FILE
        ):
            return COOKIES_YOUTUBE_FILE

    if "instagram.com" in url_lower:
        if os.path.exists(
            COOKIES_INSTAGRAM_FILE
        ):
            return COOKIES_INSTAGRAM_FILE

    if os.path.exists(
        COOKIES_FILE
    ):
        return COOKIES_FILE

    return None


def validate_url(url):
    """
    Basic URL validation.
    """

    if not url:
        return False

    url = url.strip()

    return (
        url.startswith("http://")
        or url.startswith("https://")
    )


def run_ffmpeg(command, timeout=300):
    """
    Run FFmpeg and raise a useful error when it fails.
    """

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout
    )

    if result.returncode != 0:
        error_text = (
            result.stderr
            or result.stdout
            or "FFmpeg failed."
        )

        raise RuntimeError(
            error_text[-3000:]
        )

    return result


def has_video_stream(path):
    """
    Check whether the file contains a video stream.
    """

    try:
        result = subprocess.run(
            [
                FFPROBE_EXE,
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        return bool(
            result.stdout.strip()
        )

    except Exception as error:
        print(
            "Video stream check failed:",
            error
        )

        return False


def has_audio_stream(path):
    """
    Check whether the file contains an audio stream.
    """

    try:
        result = subprocess.run(
            [
                FFPROBE_EXE,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        return bool(
            result.stdout.strip()
        )

    except Exception as error:
        print(
            "Audio stream check failed:",
            error
        )

        return False


# =========================================================
# YT-DLP OPTIONS
# =========================================================

def build_base_ydl_options(
    url,
    temp_dir
):
    """
    Common yt-dlp settings.
    """

    output_template = os.path.join(
        temp_dir,
        "%(title).80s.%(ext)s"
    )

    options = {
        "outtmpl": output_template,

        "noplaylist": True,

        "restrictfilenames": True,

        "quiet": False,

        "no_warnings": False,

        "ffmpeg_location": FFMPEG_PATH,

        "retries": 5,

        "fragment_retries": 5,

        "extractor_retries": 3,

        "file_access_retries": 3,

        "socket_timeout": 60,

        "check_fragments": True,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/120.0.0.0 "
                "Safari/537.36"
            ),
            "Accept-Language": (
                "en-US,en;q=0.9"
            )
        }
    }

    cookies_file = pick_cookies_file(
        url
    )

    if cookies_file:
        print(
            "Using cookies file:",
            cookies_file
        )

        options["cookiefile"] = (
            cookies_file
        )

    return options


# =========================================================
# DOWNLOAD VIDEO STREAM ONLY
# =========================================================

def download_video_stream(
    url,
    temp_dir
):
    """
    Download video-only stream.

    We intentionally request a video stream
    without audio because audio is downloaded
    separately and merged later.
    """

    options = build_base_ydl_options(
        url,
        temp_dir
    )

    options.update({
        "format": (
            "bestvideo/"
            "best[acodec=none]"
        ),

        "merge_output_format": "mp4"
    })

    print(
        "Downloading VIDEO stream..."
    )

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

        print(
            "Video extraction completed."
        )

        return info


# =========================================================
# DOWNLOAD AUDIO STREAM ONLY
# =========================================================

def download_audio_stream(
    url,
    temp_dir
):
    """
    Download audio-only stream.

    Audio remains separate until FFmpeg
    performs the final mux.
    """

    options = build_base_ydl_options(
        url,
        temp_dir
    )

    options.update({
        "format": (
            "bestaudio/"
            "best[acodec!=none]"
        )
    })

    print(
        "Downloading AUDIO stream..."
    )

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

        print(
            "Audio extraction completed."
        )

        return info


# =========================================================
# FIND DOWNLOADED VIDEO
# =========================================================

def find_video_file(
    folder
):
    """
    Find the downloaded video stream.
    """

    return find_file(
        folder,
        [
            "mp4",
            "webm",
            "mkv",
            "mov"
        ]
    )


# =========================================================
# FIND DOWNLOADED AUDIO
# =========================================================

def find_audio_file(
    folder
):
    """
    Find the downloaded audio stream.
    """

    return find_file(
        folder,
        [
            "m4a",
            "webm",
            "mp3",
            "opus",
            "aac",
            "ogg",
            "wav"
        ]
    )


# =========================================================
# MERGE VIDEO + AUDIO
# =========================================================

def merge_video_audio(
    video_file,
    audio_file,
    output_file
):
    """
    Combine separately downloaded video and
    audio streams into one MP4.

    Video is copied without re-encoding.

    Audio is encoded to AAC for broad MP4
    compatibility.
    """

    print(
        "Merging VIDEO + AUDIO..."
    )

    command = [
        FFMPEG_EXE,

        "-y",

        "-i",
        video_file,

        "-i",
        audio_file,

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        "-c:v",
        "copy",

        "-c:a",
        "aac",

        "-b:a",
        "192k",

        "-movflags",
        "+faststart",

        output_file
    ]

    run_ffmpeg(
        command,
        timeout=600
    )

    if not os.path.exists(
        output_file
    ):
        raise RuntimeError(
            "FFmpeg created no output file."
        )

    if os.path.getsize(
        output_file
    ) == 0:
        raise RuntimeError(
            "FFmpeg created an empty MP4."
        )

    print(
        "VIDEO + AUDIO merge completed."
    )

    return output_file


# =========================================================
# MP4 VALIDATION
# =========================================================

def validate_final_mp4(
    path
):
    """
    Make sure the final MP4 contains
    both video and audio.
    """

    if not os.path.exists(path):
        raise RuntimeError(
            "Final MP4 does not exist."
        )

    if os.path.getsize(path) == 0:
        raise RuntimeError(
            "Final MP4 is empty."
        )

    if not has_video_stream(path):
        raise RuntimeError(
            "Final MP4 contains no video stream."
        )

    if not has_audio_stream(path):
        raise RuntimeError(
            "Final MP4 contains no audio stream."
        )

    return True


# =========================================================
# DIRECT DOWNLOAD FALLBACK
# =========================================================

def download_combined_fallback(
    url,
    temp_dir
):
    """
    Fallback for sources that already expose
    a combined video+audio stream.

    This is used only if the separate-stream
    workflow cannot produce both streams.
    """

    options = build_base_ydl_options(
        url,
        temp_dir
    )

    options.update({
        "format": (
            "best"
            "[vcodec!=none]"
            "[acodec!=none]"
            "/best"
        ),

        "merge_output_format": "mp4"
    })

    print(
        "Trying combined media fallback..."
    )

    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        ydl.extract_info(
            url,
            download=True
        )

    combined_file = find_file(
        temp_dir,
        [
            "mp4",
            "webm",
            "mkv",
            "mov"
        ]
    )

    if not combined_file:
        raise RuntimeError(
            "Combined media file not found."
        )

    if not has_video_stream(
        combined_file
    ):
        raise RuntimeError(
            "Downloaded file has no video."
        )

    if not has_audio_stream(
        combined_file
    ):
        raise RuntimeError(
            "Downloaded file has no audio."
        )

    return combined_file


# =========================================================
# TEMP CLEANUP
# =========================================================

def cleanup_temp_dir(
    path
):
    if path:
        shutil.rmtree(
            path,
            ignore_errors=True
        )


# =========================================================
# STATUS API
# =========================================================

@app.route(
    "/api/status",
    methods=["GET"]
)
def status():

    return jsonify({
        "status": "online",
        "service": (
            "Video Extractor API"
        ),
        "ffmpeg": FFMPEG_EXE,
        "ffprobe": FFPROBE_EXE
    })


# =========================================================
# VIDEO DOWNLOAD API
# =========================================================

@app.route(
    "/api/download",
    methods=["POST"]
)
def download_video():

    temp_dir = None

    try:

        # -------------------------------------------------
        # REQUEST
        # -------------------------------------------------

        data = request.get_json(
            silent=True
        )

        if not isinstance(
            data,
            dict
        ):
            return jsonify({
                "error": (
                    "Invalid request format. "
                    "Expected JSON object."
                )
            }), 400

        url = data.get(
            "url",
            ""
        )

        if not isinstance(
            url,
            str
        ):
            return jsonify({
                "error": (
                    "URL must be a string."
                )
            }), 400

        url = url.strip()

        if not url:
            return jsonify({
                "error": (
                    "Please enter a URL."
                )
            }), 400

        if not validate_url(
            url
        ):
            return jsonify({
                "error": (
                    "Please enter a valid "
                    "HTTP or HTTPS URL."
                )
            }), 400

        # -------------------------------------------------
        # TEMP DIRECTORY
        # -------------------------------------------------

        temp_dir = tempfile.mkdtemp(
            prefix="video-extractor-"
        )

        print(
            "========================================"
        )

        print(
            "VIDEO REQUEST"
        )

        print(
            "URL:",
            url
        )

        print(
            "TEMP:",
            temp_dir
        )

        # -------------------------------------------------
        # STEP 1
        # VIDEO ONLY
        # -------------------------------------------------

        video_temp_dir = os.path.join(
            temp_dir,
            "video"
        )

        os.makedirs(
            video_temp_dir,
            exist_ok=True
        )

        try:

            download_video_stream(
                url,
                video_temp_dir
            )

            video_file = (
                find_video_file(
                    video_temp_dir
                )
            )

        except Exception as video_error:

            print(
                "Separate video download failed:",
                video_error
            )

            video_file = None

        # -------------------------------------------------
        # STEP 2
        # AUDIO ONLY
        # -------------------------------------------------

        audio_temp_dir = os.path.join(
            temp_dir,
            "audio"
        )

        os.makedirs(
            audio_temp_dir,
            exist_ok=True
        )

        try:

            download_audio_stream(
                url,
                audio_temp_dir
            )

            audio_file = (
                find_audio_file(
                    audio_temp_dir
                )
            )

        except Exception as audio_error:

            print(
                "Separate audio download failed:",
                audio_error
            )

            audio_file = None

        # -------------------------------------------------
        # STEP 3
        # VERIFY BOTH
        # -------------------------------------------------

        if (
            video_file
            and audio_file
            and os.path.exists(video_file)
            and os.path.exists(audio_file)
        ):

            print(
                "Separate VIDEO file:",
                video_file
            )

            print(
                "Separate AUDIO file:",
                audio_file
            )

            if not has_video_stream(
                video_file
            ):
                raise RuntimeError(
                    "Downloaded video stream "
                    "contains no video."
                )

            if not has_audio_stream(
                audio_file
            ):
                raise RuntimeError(
                    "Downloaded audio stream "
                    "contains no audio."
                )

            # -------------------------------------------------
            # STEP 4
            # FINAL MP4
            # -------------------------------------------------

            output_file = os.path.join(
                temp_dir,
                "video.mp4"
            )

            merge_video_audio(
                video_file,
                audio_file,
                output_file
            )

            # -------------------------------------------------
            # STEP 5
            # FINAL CHECK
            # -------------------------------------------------

            validate_final_mp4(
                output_file
            )

            print(
                "Final MP4:",
                output_file
            )

            response = send_file(
                output_file,
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

        # -------------------------------------------------
        # FALLBACK
        # -------------------------------------------------

        print(
            "Separate streams unavailable."
        )

        print(
            "Trying combined stream..."
        )

        fallback_dir = os.path.join(
            temp_dir,
            "fallback"
        )

        os.makedirs(
            fallback_dir,
            exist_ok=True
        )

        fallback_file = (
            download_combined_fallback(
                url,
                fallback_dir
            )
        )

        response = send_file(
            fallback_file,
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

    except yt_dlp.utils.DownloadError as error:

        print(
            "YT-DLP DOWNLOAD ERROR:",
            str(error)
        )

        if temp_dir:
            cleanup_temp_dir(
                temp_dir
            )

        return jsonify({
            "error": (
                "The media could not be downloaded. "
                "The source may be unavailable or "
                "may require access that this server "
                "does not have."
            )
        }), 400

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
            "error": str(error)
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

        # -------------------------------------------------
        # REQUEST
        # ------------------------------------------
