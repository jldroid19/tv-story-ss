#!/bin/bash

IMAGE_NAME="yt-downloader"
CONTAINER_NAME="yt-downloader-cli"

# Check for client_secrets.json
if [ ! -f "client_secrets.json" ]; then
    echo "⚠️  Warning: client_secrets.json not found."
    echo "   YouTube upload feature will not work without it."
    echo "   See README.md for setup instructions."
    echo ""
fi

echo "🔨 Building image..."
nerdctl build -t $IMAGE_NAME .

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
nerdctl run -it --rm \
    --name $CONTAINER_NAME \
    -v "$(pwd)/downloads:/app/downloads" \
    -v "$(pwd)/credentials:/app/credentials" \
    -v "$(pwd)/client_secrets.json:/app/client_secrets.json:ro" \
    -p 8080:8080 \
    $IMAGE_NAME
