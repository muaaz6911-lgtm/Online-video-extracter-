FROM python:3.12-slim

# Install FFmpeg + FFprobe
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Working folder
WORKDIR /app

# Install Python requirements
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Render port
ENV PORT=10000

EXPOSE 10000

# Start Flask with Gunicorn
CMD gunicorn app:app --bind 0.0.0.0:$PORT
