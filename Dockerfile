FROM python:3.11-slim

# Install ffmpeg for audio extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the downloader script
COPY youtube_downloader.py .

# Create directories
RUN mkdir -p /app/downloads /app/credentials

# Create alias for the CLI command
RUN echo 'alias ytd="python /app/youtube_downloader.py"' >> /root/.bashrc

# Set the entrypoint to bash for interactive use
CMD ["/bin/bash"]
