const express = require("express");
const path = require("path");
const dns = require("dns").promises;
const net = require("net");
const fs = require("fs");
const os = require("os");
const { pipeline } = require("stream/promises");
const { Readable } = require("stream");
const { spawn } = require("child_process");
const ffmpegPath = require("ffmpeg-static");

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json({ limit: "1mb" }));
app.use(express.static(path.join(__dirname, "public")));

function isPrivateIP(ip) {
  if (net.isIPv4(ip)) {
    return (
      ip.startsWith("10.") ||
      ip.startsWith("127.") ||
      ip.startsWith("192.168.") ||
      ip.startsWith("169.254.") ||
      /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip) ||
      ip === "0.0.0.0"
    );
  }

  if (net.isIPv6(ip)) {
    const value = ip.toLowerCase();

    return (
      value === "::1" ||
      value.startsWith("fc") ||
      value.startsWith("fd") ||
      value.startsWith("fe80")
    );
  }

  return true;
}

async function validateURL(urlString) {
  let url;

  try {
    url = new URL(urlString);
  } catch {
    throw new Error("Please enter a valid URL.");
  }

  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("Only HTTP and HTTPS URLs are allowed.");
  }

  const hostname = url.hostname.toLowerCase();

  if (
    hostname === "localhost" ||
    hostname.endsWith(".localhost")
  ) {
    throw new Error("This URL is not allowed.");
  }

  if (net.isIP(hostname)) {
    if (isPrivateIP(hostname)) {
      throw new Error("Private network URLs are not allowed.");
    }
    return url;
  }

  const addresses = await dns.lookup(hostname, { all: true });

  if (
    !addresses.length ||
    addresses.some(item => isPrivateIP(item.address))
  ) {
    throw new Error("This URL is not allowed.");
  }

  return url;
}

function safeFilename(name) {
  return name.replace(/[^a-zA-Z0-9._-]/g, "_");
}

function getFilename(urlString, contentType = "") {
  const url = new URL(urlString);
  let filename = path.basename(url.pathname);

  if (!filename || filename === "/" || !filename.includes(".")) {
    if (contentType.includes("webm")) filename = "video.webm";
    else if (contentType.includes("audio")) filename = "audio";
    else filename = "video.mp4";
  }

  return safeFilename(filename);
}

async function fetchMedia(urlString) {
  const safeURL = await validateURL(urlString);

  const controller = new AbortController();

  const timeout = setTimeout(
    () => controller.abort(),
    30000
  );

  try {
    const response = await fetch(safeURL, {
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "User-Agent": "Video-Extractor/2.0"
      }
    });

    if (!response.ok) {
      throw new Error(
        `Could not fetch file. Server returned ${response.status}.`
      );
    }

    if (!response.body) {
      throw new Error("The media file has no downloadable content.");
    }

    // Re-check final redirect destination
    await validateURL(response.url);

    return response;
  } finally {
    clearTimeout(timeout);
  }
}


/* =========================
   DIRECT MEDIA DOWNLOAD
========================= */

app.post("/api/download", async (req, res) => {
  const { url } = req.body;

  if (!url) {
    return res.status(400).json({
      error: "Please paste a media URL."
    });
  }

  try {
    const response = await fetchMedia(url);

    const contentType =
      response.headers.get("content-type") ||
      "application/octet-stream";

    const filename = getFilename(
      response.url || url,
      contentType
    );

    res.setHeader("Content-Type", contentType);

    res.setHeader(
      "Content-Disposition",
      `attachment; filename="${filename}"`
    );

    const contentLength =
      response.headers.get("content-length");

    if (contentLength) {
      res.setHeader("Content-Length", contentLength);
    }

    const readable =
      Readable.fromWeb(response.body);

    await pipeline(readable, res);

  } catch (error) {
    console.error("Download error:", error);

    if (!res.headersSent) {
      res.status(400).json({
        error:
          error.name === "AbortError"
            ? "Request timed out."
            : error.message
      });
    }
  }
});


/* =========================
   MP3 CONVERSION
========================= */

app.post("/api/convert/mp3", async (req, res) => {
  const { url } = req.body;

  if (!url) {
    return res.status(400).json({
      error: "Please paste a media URL."
    });
  }

  const tempDir = fs.mkdtempSync(
    path.join(os.tmpdir(), "video-extractor-")
  );

  const inputFile =
    path.join(tempDir, "input.media");

  const outputFile =
    path.join(tempDir, "audio.mp3");

  try {
    const response = await fetchMedia(url);

    const readable =
      Readable.fromWeb(response.body);

    const writable =
      fs.createWriteStream(inputFile);

    await pipeline(readable, writable);

    await new Promise((resolve, reject) => {

      const ffmpeg = spawn(ffmpegPath, [
        "-y",
        "-i", inputFile,
        "-vn",
        "-codec:a", "libmp3lame",
        "-b:a", "192k",
        outputFile
      ]);

      let errorOutput = "";

      ffmpeg.stderr.on("data", data => {
        errorOutput += data.toString();
      });

      ffmpeg.on("error", reject);

      ffmpeg.on("close", code => {
        if (code === 0) {
          resolve();
        } else {
          reject(
            new Error(
              "MP3 conversion failed. " +
              errorOutput.slice(-500)
            )
          );
        }
      });

    });

    res.download(
      outputFile,
      "audio.mp3",
      () => {
        fs.rm(
          tempDir,
          { recursive: true, force: true },
          () => {}
        );
      }
    );

  } catch (error) {

    console.error(
      "MP3 conversion error:",
      error
    );

    fs.rm(
      tempDir,
      { recursive: true, force: true },
      () => {}
    );

    if (!res.headersSent) {
      res.status(400).json({
        error:
          error.name === "AbortError"
            ? "Request timed out."
            : error.message
      });
    }
  }
});


app.listen(PORT, () => {
  console.log(
    `Video Extractor running on port ${PORT}`
  );
});
