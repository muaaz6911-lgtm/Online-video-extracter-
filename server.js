const express = require("express");
const multer = require("multer");
const { spawn } = require("child_process");
const ffmpegPath = require("ffmpeg-static");
const path = require("path");
const fs = require("fs");

const app = express();
const PORT = process.env.PORT || 3000;

const uploadDir = path.join(__dirname, "uploads");
const outputDir = path.join(__dirname, "outputs");

fs.mkdirSync(uploadDir, { recursive: true });
fs.mkdirSync(outputDir, { recursive: true });

app.use(express.static(path.join(__dirname, "public")));

const jobs = {};

const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, uploadDir);
  },

  filename: (req, file, cb) => {
    const unique =
      Date.now() + "-" +
      Math.round(Math.random() * 1e9);

    cb(
      null,
      unique + path.extname(file.originalname)
    );
  }
});

const upload = multer({
  storage,

  limits: {
    fileSize: 1024 * 1024 * 1024
  }
});


function timeToSeconds(time) {

  const parts = time.split(":");

  const hours = Number(parts[0]);
  const minutes = Number(parts[1]);
  const seconds = Number(parts[2]);

  return (
    hours * 3600 +
    minutes * 60 +
    seconds
  );

}


/* =========================
   CONVERT
========================= */

app.post(
  "/convert",
  upload.single("media"),
  (req, res) => {

    if (!req.file) {

      return res.status(400).json({
        success: false,
        error: "No file uploaded"
      });

    }


    const format = req.body.format;


    if (
      format !== "mp3" &&
      format !== "mp4"
    ) {

      return res.status(400).json({
        success: false,
        error: "Invalid format"
      });

    }


    const jobId =
      Date.now() + "-" +
      Math.random()
        .toString(36)
        .substring(2, 10);


    const outputName =
      jobId + "." + format;


    const outputPath =
      path.join(
        outputDir,
        outputName
      );


    jobs[jobId] = {

      progress: 0,

      status: "processing",

      download: null,

      error: null

    };


    let args;


    if (format === "mp3") {

      args = [

        "-i",
        req.file.path,

        "-vn",

        "-codec:a",
        "libmp3lame",

        "-q:a",
        "2",

        "-y",

        outputPath

      ];

    }

    else {

      args = [

        "-i",
        req.file.path,

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-c:a",
        "aac",

        "-y",

        outputPath

      ];

    }


    let duration = 0;


    const ffmpeg =
      spawn(
        ffmpegPath,
        args
      );


    ffmpeg.stderr.on(
      "data",
      (data) => {

        const text =
          data.toString();


        /* Get total duration */

        const durationMatch =
          text.match(
            /Duration: (\d{2}:\d{2}:\d{2}\.\d{2})/
          );


        if (durationMatch) {

          duration =
            timeToSeconds(
              durationMatch[1]
            );

        }


        /* Get current conversion time */

        const timeMatch =
          text.match(
            /time=(\d{2}:\d{2}:\d{2}\.\d{2})/
          );


        if (
          timeMatch &&
          duration > 0
        ) {

          const current =
            timeToSeconds(
              timeMatch[1]
            );


          let percent =
            Math.floor(
              (
                current /
                duration
              ) * 100
            );


          if (percent > 99) {
            percent = 99;
          }


          if (percent < 0) {
            percent = 0;
          }


          jobs[jobId].progress =
            percent;

        }

      }
    );


    ffmpeg.on(
      "error",
      (error) => {

        console.error(error);


        jobs[jobId].status =
          "error";


        jobs[jobId].error =
          "FFmpeg could not start.";


        if (
          fs.existsSync(
            req.file.path
          )
        ) {

          fs.unlinkSync(
            req.file.path
          );

        }

      }
    );


    ffmpeg.on(
      "close",
      (code) => {

        /* Delete uploaded file */

        if (
          fs.existsSync(
            req.file.path
          )
        ) {

          fs.unlink(
            req.file.path,
            () => {}
          );

        }


        if (code === 0) {

          jobs[jobId].progress =
            100;


          jobs[jobId].status =
            "complete";


          jobs[jobId].download =
            "/download/" +
            outputName;

        }

        else {

          jobs[jobId].status =
            "error";


          jobs[jobId].error =
            "Conversion failed.";

        }

      }
    );


    res.json({

      success: true,

      jobId

    });

  }
);


/* =========================
   PROGRESS
========================= */

app.get(
  "/progress/:jobId",
  (req, res) => {

    const job =
      jobs[
        req.params.jobId
      ];


    if (!job) {

      return res.status(404).json({

        error: "Job not found"

      });

    }


    res.json(job);

  }
);


/* =========================
   DOWNLOAD
========================= */

app.get(
  "/download/:file",
  (req, res) => {

    const safeFile =
      path.basename(
        req.params.file
      );


    const filePath =
      path.join(
        outputDir,
        safeFile
      );


    if (
      !fs.existsSync(filePath)
    ) {

      return res.status(404).send(
        "File not found"
      );

    }


    res.download(
      filePath
    );

  }
);


/* =========================
   START SERVER
========================= */

app.listen(
  PORT,
  () => {

    console.log(
      `Video Extractor running on port ${PORT}`
    );

  }
);
