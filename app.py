import os
import re
import glob
import shutil
import socket
import ipaddress
import tempfile
from urllib.parse import urlparse

import requests
import yt_dlp

from flask import (
    Flask,
    request,
    jsonify,
    send_file,
    send_from_directory
)

from flask_cors import CORS


# =========================================
# APP
# =========================================

app = Flask(__name__)

CORS(app)


# =========================================
# FRONTEND WEBSITE
# =========================================

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


# =========================================
# CONFIG
# =========================================

MAX_URL_LENGTH = 2000
REQUEST_TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)


# =========================================
# PRIVATE IP CHECK
# =========================================

def is_private_ip(ip):

    try:

        address = ipaddress.ip_address(ip)

        return (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        )

    except ValueError:

        return True


# =========================================
# VALIDATE URL
# =========================================

def validate_url(url):

    if not url:

        raise ValueError(
            "Please enter a URL."
        )


    if len(url) > MAX_URL_LENGTH:

        raise ValueError(
            "URL is too long."
        )


    parsed = urlparse(url)


    if parsed.scheme not in ("http", "https"):

        raise ValueError(
            "Only HTTP and HTTPS URLs are allowed."
        )


    hostname = parsed.hostname


    if not hostname:

        raise ValueError(
            "Invalid URL."
        )


    hostname = hostname.lower()


    # Block localhost

    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
    ):

        raise ValueError(
            "This URL is not allowed."
        )


    # =====================================
    # CHECK DIRECT IP
    # =====================================

    try:

        ipaddress.ip_address(hostname)


        if is_private_ip(hostname):

            raise ValueError(
                "Private network URLs are not allowed."
            )


        return url


    except ValueError as error:

        if "Private network" in str(error):

            raise error


    except Exception:

        pass


    # =====================================
    # DNS LOOKUP
    # =====================================

    try:

        addresses = socket.getaddrinfo(
            hostname,
            None
        )


        ips = set(
            item[4][0]
            for item in addresses
        )


        if not ips:

            raise ValueError(
                "Could not resolve this URL."
            )


        for ip in ips:

            if is_private_ip(ip):

                raise ValueError(
                    "This URL is not allowed."
                )


    except socket.gaierror:

        raise ValueError(
            "Could not resolve this URL."
        )


    return url


# =========================================
# GET URL FROM REQUEST
# =========================================

def get_request_url():

    data = request.get_json(
        silent=True
    )


    if not data:

        raise ValueError(
            "No data received."
        )


    url = data.get(
        "url",
        ""
    ).strip()


    return validate_url(url)


# =========================================
# SAFE FILENAME
# =========================================

def safe_filename(name):

    name = re.sub(
        r'[^a-zA-Z0-9._-]',
        "_",
        name
    )


    return name[:100]


# =========================================
# FIND FILE
# =========================================

def find_file(folder, extensions):

    for extension in extensions:

        pattern = os.path.join(
            folder,
            f"*.{extension}"
        )


        files = glob.glob(pattern)


        if files:

            return files[0]


    return None


# =========================================
# CHECK DIRECT MEDIA URL
# =========================================

def is_direct_media_url(url):

    path = urlparse(url).path.lower()


    extensions = (

        ".mp4",
        ".webm",
        ".mkv",
        ".mov",
        ".avi",

        ".mp3",
        ".m4a",
        ".wav",
        ".ogg",
        ".aac"

    )


    return path.endswith(
        extensions
    )


# =========================================
# DIRECT MEDIA DOWNLOAD
# =========================================

def download_direct_media(url, temp_dir):

    response = requests.get(

        url,

        stream=True,

        timeout=REQUEST_TIMEOUT,

        allow_redirects=True,

        headers={

            "User-Agent": USER_AGENT

        }

    )


    response.raise_for_status()


    # Validate redirect URL

    validate_url(
        response.url
    )


    content_type = (
        response.headers.get(
            "content-type",
            ""
        ).lower()
    )


    parsed = urlparse(
        response.url
    )


    filename = os.path.basename(
        parsed.path
    )


    if not filename:

        filename = "media"


    filename = safe_filename(
        filename
    )


    # Add extension if missing

    if "." not in filename:

        if "video" in content_type:

            filename += ".mp4"


        elif "audio" in content_type:

            filename += ".mp3"


        else:

            filename += ".media"


    file_path = os.path.join(
        temp_dir,
        filename
    )


    with open(
        file_path,
        "wb"
    ) as file:

        for chunk in response.iter_content(
            chunk_size=8192
        ):

            if chunk:

                file.write(
                    chunk
                )


    return file_path


# =========================================
# YT-DLP DOWNLOAD
# =========================================

def download_with_ytdlp(
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

        "quiet": False,

        "no_warnings": False,

        "restrictfilenames": True,

        "ffmpeg_location": "/usr/bin"

    }


    # =====================================
    # AUDIO / MP3
    # =====================================

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


    # =====================================
    # VIDEO WITH AUDIO
    # =====================================

    else:

        options.update({

            "format": (
                "bestvideo[ext=mp4]"
                "+bestaudio/"
                "best[ext=mp4]/best"
            ),

            "merge_output_format": "mp4"

        })


    with yt_dlp.YoutubeDL(
        options
    ) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )


    return info


# =========================================
# API STATUS
# =========================================

@app.route(
    "/api/status",
    methods=["GET"]
)

def status():

    return jsonify({

        "status": "online",

        "service":
        "Video Extractor API"

    })


# =========================================
# VIDEO DOWNLOAD API
# =========================================

@app.route(
    "/api/download",
    methods=["POST"]
)

def download_video():

    temp_dir = None


    try:

        url = get_request_url()


        temp_dir = tempfile.mkdtemp(
            prefix="video-extractor-"
        )


        media_file = None


        # =================================
        # DIRECT MEDIA
        # =================================

        if is_direct_media_url(url):

            try:

                media_file = download_direct_media(
                    url,
                    temp_dir
                )


            except Exception as error:

                print(
                    "Direct download failed:",
                    error
                )


        # =================================
        # YT-DLP DOWNLOAD
        # =================================

        if not media_file:

            download_with_ytdlp(
                url,
                temp_dir
            )


            media_file = find_file(

                temp_dir,

                [

                    "mp4",
                    "webm",
                    "mkv",
                    "mov",
                    "avi"

                ]

            )


        if not media_file:

            raise Exception(
                "Could not find downloaded media."
            )


        filename = os.path.basename(
            media_file
        )


        response = send_file(

            media_file,

            as_attachment=True,

            download_name=filename

        )


        @response.call_on_close
        def cleanup():

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )


        return response


    except Exception as error:

        print(
            "DOWNLOAD ERROR:",
            str(error)
        )


        if temp_dir:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )


        return jsonify({

            "error":
            "Unable to download this public media URL."

        }), 400


# =========================================
# MP3 CONVERSION API
# =========================================

@app.route(
    "/api/convert/mp3",
    methods=["POST"]
)

def convert_mp3():

    temp_dir = None


    try:

        url = get_request_url()


        temp_dir = tempfile.mkdtemp(
            prefix="video-extractor-"
        )


        # =================================
        # DOWNLOAD + CONVERT
        # =================================

        download_with_ytdlp(

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
                "MP3 conversion failed."
            )


        response = send_file(

            mp3_file,

            as_attachment=True,

            download_name="audio.mp3",

            mimetype="audio/mpeg"

        )


        @response.call_on_close
        def cleanup():

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
           
