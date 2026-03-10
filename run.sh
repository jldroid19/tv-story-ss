#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE_NAME="yt-downloader"
CONTAINER_NAME="yt-downloader-cli"
PROJECT_SOURCE_DIR=""
PROJECT_NAME=""
PROJECT_CONTAINER_DIR=""
HOST_ROOT_MAPPINGS=()

RUN_ARGS=(
    -it
    --rm
    --name "$CONTAINER_NAME"
    -v "$SCRIPT_DIR/downloads:/app/downloads"
    -v "$SCRIPT_DIR/credentials:/app/credentials"
    -p 8080:8080
)

add_host_root() {
    local host_root="$1"
    local container_root="$2"

    if [ -d "$host_root" ]; then
        RUN_ARGS+=( -v "$host_root:$container_root" )
        HOST_ROOT_MAPPINGS+=( "$host_root=$container_root" )
    fi
}

translate_host_path() {
    local host_path="$1"
    local mapping

    for mapping in "${HOST_ROOT_MAPPINGS[@]}"; do
        local host_root="${mapping%%=*}"
        local container_root="${mapping#*=}"

        case "$host_path" in
            "$host_root")
                printf '%s\n' "$container_root"
                return 0
                ;;
            "$host_root"/*)
                printf '%s\n' "$container_root/${host_path#"$host_root"/}"
                return 0
                ;;
        esac
    done

    return 1
}

add_host_root "/Users" "/host/Users"
add_host_root "/Volumes" "/host/Volumes"
add_host_root "/private" "/host/private"

if [ ${#HOST_ROOT_MAPPINGS[@]} -gt 0 ]; then
    HOST_ROOT_MAPPINGS_ENV="$(printf '%s;' "${HOST_ROOT_MAPPINGS[@]}")"
    HOST_ROOT_MAPPINGS_ENV="${HOST_ROOT_MAPPINGS_ENV%;}"
    RUN_ARGS+=( -e "HOST_ROOT_MAPPINGS=$HOST_ROOT_MAPPINGS_ENV" )
fi

# Check if a project directory was passed as an argument
if [ -n "$1" ]; then
    # Resolve to absolute path
    PROJECT_SOURCE_DIR="$(cd "$1" 2>/dev/null && pwd)"
    if [ -z "$PROJECT_SOURCE_DIR" ] || [ ! -d "$PROJECT_SOURCE_DIR" ]; then
        echo "❌ Error: '$1' is not a valid directory."
        exit 1
    fi

    PROJECT_CONTAINER_DIR="$(translate_host_path "$PROJECT_SOURCE_DIR")"
    if [ -z "$PROJECT_CONTAINER_DIR" ]; then
        echo "❌ Error: '$PROJECT_SOURCE_DIR' is outside the shared host roots."
        echo "   Supported roots: /Users, /Volumes, /private"
        exit 1
    fi

    PROJECT_NAME="$(basename "$PROJECT_SOURCE_DIR")"
    RUN_ARGS+=(
        -e "PROJECT_DIR=$PROJECT_CONTAINER_DIR"
        -e "PROJECT_LABEL=$PROJECT_NAME"
        -e "PROJECT_SOURCE_PATH=$PROJECT_SOURCE_DIR"
    )

    echo "📂 Project folder: $PROJECT_SOURCE_DIR"
    echo "   → mounted at $PROJECT_CONTAINER_DIR"
    echo "   → shown in CLI as: $PROJECT_NAME"

    if [[ "$PROJECT_SOURCE_DIR" == /Volumes/* ]]; then
        echo "🔌 External volume detected."
        echo "   If the mount is denied, add the drive to Docker Desktop file sharing first."
    fi
    echo ""
fi

# Detect container runtime (check that it's actually responsive, not just installed)
RUNTIME=""
if command -v nerdctl &> /dev/null && nerdctl info &> /dev/null; then
    RUNTIME="nerdctl"
elif command -v docker &> /dev/null && docker info &> /dev/null; then
    RUNTIME="docker"
else
    echo "❌ Error: No working container runtime found."
    echo "   Please start Docker Desktop or Rancher Desktop."
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
else
    RUN_ARGS+=( -v "$SCRIPT_DIR/client_secrets.json:/app/client_secrets.json:ro" )
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
echo "  list         - List files in current folder"
echo "  project      - List / switch project folders"
echo "  project external /path/to/folder - Use a host folder from /Users, /Volumes, or /private"
echo "  stitch       - Stitch videos together"
echo "  upload       - Upload video to YouTube"
echo "  backup       - Backup videos to Google Cloud"
echo "  qr           - Generate QR code for any URL"
echo "  help         - Show all commands"
echo ""
echo "Usage: ./run.sh [/path/to/video/folder]"
echo "  Run without arguments, then use 'project external /path/to/folder' in the CLI."
echo "  You can still pass a folder here to auto-open it on startup."
echo "  Example: ./run.sh ~/Videos/my-compilation"
echo "  External drive example: ./run.sh /Volumes/MyDrive/Videos/my-compilation"
echo ""
echo "Downloads will be saved to /app/downloads"
echo "Type 'exit' to quit the container"
echo "================================================"
echo ""

# Run container interactively with volume mounts
$RUNTIME run "${RUN_ARGS[@]}" "$IMAGE_NAME"
