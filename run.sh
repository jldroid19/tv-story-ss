#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="yt-downloader"
CONTAINER_NAME="yt-downloader-cli"

# Detect container runtime (prefer nerdctl, fallback to docker)
RUNTIME=""
if command -v nerdctl &> /dev/null; then
    RUNTIME="nerdctl"
elif command -v docker &> /dev/null; then
    RUNTIME="docker"
else
    echo "❌ Error: Neither nerdctl nor docker found."
    echo "   Please install one of them to use this tool."
    exit 1
fi

echo "🐳 Found container runtime: $RUNTIME"
read -p "   Press Enter to continue or Ctrl+C to cancel..."
echo ""

# Check for client_secrets.json
if [ ! -f "$SCRIPT_DIR/client_secrets.json" ]; then
    echo "⚠️  Warning: client_secrets.json not found."
    echo "   YouTube upload feature will not work without it."
    echo "   See README.md for setup instructions."
    echo ""
fi

echo "🔨 Building image..."
$RUNTIME build -t $IMAGE_NAME "$SCRIPT_DIR"

if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi

echo ""
echo "✅ Build complete!"
echo ""
echo "🚀 Starting container with interactive shell..."
echo "================================================"
echo ""
echo "Available commands:"
echo "  ytd                  - Enter interactive mode"
echo "  ytd <URL>           - Download video"
echo "  ytd <URL> --audio   - Download audio only (MP3)"
echo "  ytd <URL> --info    - Get video info"
echo ""
echo "Inside interactive mode:"
echo "  video <URL>  - Download video"
echo "  audio <URL>  - Download audio"
echo "  list         - List downloaded files"
echo "  stitch       - Stitch videos together"
echo "  upload       - Upload video to YouTube"
echo "  backup       - Backup videos to Google Cloud"
echo "  qr           - Generate QR code for any URL"
echo "  help         - Show all commands"
echo ""
echo "Downloads will be saved to /app/downloads"
echo "Type 'exit' to quit the container"
echo "================================================"
echo ""

# Run container interactively with volume mounts
$RUNTIME run -it --rm \
    --name $CONTAINER_NAME \
    -v "$SCRIPT_DIR/downloads:/app/downloads" \
    -v "$SCRIPT_DIR/credentials:/app/credentials" \
    -v "$SCRIPT_DIR/client_secrets.json:/app/client_secrets.json:ro" \
    -p 8080:8080 \
    $IMAGE_NAME
