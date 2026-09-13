const express = require("express");
const path = require("path");
const dns = require("dns").promises;
const net = require("net");

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
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

  if (
    url.protocol !== "http:" &&
    url.protocol !== "https:"
  ) {
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

  const addresses = await dns.lookup(hostname, {
    all: true
  });

  if (
    !addresses.length ||
    addresses.some(item => isPrivateIP(item.address))
  ) {
    throw new Error("This URL is not allowed.");
  }

  return url;
}

function getFilename(urlString, contentType) {
  const url = new URL(urlString);

  let filename =
    path.basename(url.pathname);

  if (
    !filename ||
    filename === "/" ||
    !filename.includes(".")
  ) {
    if (
      contentType &&
      contentType.includes("webm")
    ) {
      filename = "video.webm";
    } else {
      filename = "video.mp4";
    }
  }

  return filename.replace(
    /[^a-zA-Z0-9._-]/g,
    "_"
  );
}

/* =====================
   DIRECT MEDIA DOWNLOAD
===================== */

app.post("/api/download", async (req, res) => {
  const { url } = req.body;

  if (!url) {
    return res.status(400).json({
      success: false,
      error: "Please paste a media URL."
    });
  }

  try {
    const safeURL = await validateURL(url);

    const controller = new AbortController();

    const timeout = setTimeout(() => {
      controller.abort();
    }, 30000);

    let response;

    try {
      response = await fetch(safeURL, {
        redirect: "follow",
        signal: controller.signal,
        headers: {
          "User-Agent": "Video-Extractor/1.0"
        }
      });
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      throw new Error(
        `Could not fetch file. Server returned ${response.status}.`
      );
    }

    if (!response.body) {
      throw new Error("The media file has no downloadable content.");
    }

    const contentType =
      response.headers.get("content-type") || "";

    const filename =
      getFilename(
        response.url || safeURL.toString(),
        contentType
      );

    res.setHeader(
      "Content-Type",
      contentType || "application/octet-stream"
    );

    res.setHeader(
      "Content-Disposition",
      `attachment; filename="${filename}"`
    );

    const contentLength =
      response.headers.get("content-length");

    if (contentLength) {
      res.setHeader(
        "Content-Length",
        contentLength
      );
    }

    const reader =
      response.body.getReader();

    res.on("close", () => {
      try {
        reader.cancel();
      } catch {}
    });

    while (true) {
      const { done, value } =
        await reader.read();

      if (done) break;

      if (!res.write(Buffer.from(value))) {
        await new Promise(resolve =>
          res.once("drain", resolve)
        );
      }
    }

    res.end();

  } catch (error) {
    console.error(error);

    if (!res.headersSent) {
      res.status(400).json({
        success: false,
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

    

        
    
