#!/usr/bin/env python3
"""
YouTube Video Downloader CLI
An interactive CLI utility to download YouTube videos using yt-dlp.
Includes video stitching and YouTube upload capabilities.
"""

import yt_dlp
import sys
import os
import readline  # Enables arrow keys and history in input
from datetime import datetime
import pickle
import http.client
import httplib2
import random
import subprocess
import tempfile
import time


# ANSI Color Codes
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Regular colors
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    
    # Background colors
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_BLUE = '\033[44m'


OUTPUT_PATH = "/app/downloads"
WORK_PATH = OUTPUT_PATH  # Current working folder (can be a subdirectory)
CREDENTIALS_PATH = "/app/credentials"
CLIENT_SECRETS_FILE = "/app/client_secrets.json"
OAUTH_TOKEN_FILE = os.path.join(CREDENTIALS_PATH, "youtube_oauth.pickle")
GCS_TOKEN_FILE = os.path.join(CREDENTIALS_PATH, "gcs_oauth.pickle")
GCS_BUCKET_FILE = os.path.join(CREDENTIALS_PATH, "gcs_bucket.txt")
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.webm', '.avi', '.mov')
HOST_ROOT_MAPPINGS = []
EXTERNAL_PROJECT_PATH = ""
EXTERNAL_PROJECT_LABEL = ""
EXTERNAL_PROJECT_SOURCE = ""

# YouTube API settings
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
GCS_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
MAX_RETRIES = 10
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]


def normalize_optional_path(path: str) -> str:
    """Normalize a path string while preserving empty values."""
    path = (path or "").strip()
    return os.path.normpath(path) if path else ""


def load_host_root_mappings():
    """Load host-to-container root mappings from the environment."""
    mappings = []
    raw_mappings = os.environ.get("HOST_ROOT_MAPPINGS", "").strip()
    if not raw_mappings:
        return mappings

    for entry in raw_mappings.split(";"):
        if not entry or "=" not in entry:
            continue
        host_root, container_root = entry.split("=", 1)
        host_root = normalize_optional_path(host_root)
        container_root = normalize_optional_path(container_root)
        if host_root and container_root:
            mappings.append((host_root, container_root))

    return mappings


HOST_ROOT_MAPPINGS = load_host_root_mappings()
EXTERNAL_PROJECT_PATH = normalize_optional_path(os.environ.get("PROJECT_DIR", ""))
EXTERNAL_PROJECT_LABEL = os.environ.get("PROJECT_LABEL", "").strip()
EXTERNAL_PROJECT_SOURCE = normalize_optional_path(os.environ.get("PROJECT_SOURCE_PATH", ""))


def is_within_directory(path: str, directory: str) -> bool:
    """Return True when path is the same as or nested inside directory."""
    if not path or not directory:
        return False

    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(directory)]) == os.path.abspath(directory)
    except ValueError:
        return False


def translate_host_path_to_container(host_path: str) -> str:
    """Translate an absolute host path into the matching mounted container path."""
    normalized = normalize_optional_path(host_path)
    if not normalized or not os.path.isabs(normalized):
        return ""

    for host_root, container_root in HOST_ROOT_MAPPINGS:
        if normalized == host_root:
            return container_root
        if normalized.startswith(host_root + os.sep):
            return os.path.join(container_root, normalized[len(host_root) + 1:])

    return ""


def translate_container_path_to_host(container_path: str) -> str:
    """Translate a mounted container path back to its host path when possible."""
    normalized = normalize_optional_path(container_path)
    if not normalized:
        return ""

    for host_root, container_root in HOST_ROOT_MAPPINGS:
        if normalized == container_root:
            return host_root
        if normalized.startswith(container_root + os.sep):
            return os.path.join(host_root, normalized[len(container_root) + 1:])

    return ""


def set_external_project(host_path: str) -> bool:
    """Switch the working folder to a host-mounted external directory."""
    global WORK_PATH, EXTERNAL_PROJECT_PATH, EXTERNAL_PROJECT_LABEL, EXTERNAL_PROJECT_SOURCE
    c = Colors

    normalized_host_path = normalize_optional_path(host_path)
    if not normalized_host_path or not os.path.isabs(normalized_host_path):
        print(f"{c.RED}❌ Please provide an absolute host path.{c.RESET}")
        return False

    container_path = translate_host_path_to_container(normalized_host_path)
    if not container_path:
        roots = ", ".join(host_root for host_root, _ in HOST_ROOT_MAPPINGS) or "(none configured)"
        print(f"{c.RED}❌ Path is outside the shared host roots.{c.RESET}")
        print(f"{c.DIM}   Allowed roots: {roots}{c.RESET}")
        return False

    if not os.path.isdir(container_path):
        print(f"{c.RED}❌ Folder not found:{c.RESET} {normalized_host_path}")
        return False

    EXTERNAL_PROJECT_PATH = container_path
    EXTERNAL_PROJECT_SOURCE = normalized_host_path
    EXTERNAL_PROJECT_LABEL = os.path.basename(normalized_host_path) or normalized_host_path
    WORK_PATH = container_path

    print(f"{c.GREEN}✅ Working folder set to:{c.RESET} {c.WHITE}{WORK_PATH}{c.RESET}")
    print(f"{c.DIM}   Host path: {EXTERNAL_PROJECT_SOURCE}{c.RESET}")
    return True


def get_mounted_project_aliases():
    """Return names that should switch to the mounted host project."""
    aliases = {"external", "mounted", "host"}
    if EXTERNAL_PROJECT_LABEL:
        aliases.add(EXTERNAL_PROJECT_LABEL.lower())
    return aliases


def get_folder_label(path: str = None) -> str:
    """Return a human-readable label for the active folder."""
    current_path = path or WORK_PATH

    if current_path == OUTPUT_PATH:
        return "root"
    if EXTERNAL_PROJECT_PATH and is_within_directory(current_path, EXTERNAL_PROJECT_PATH):
        return EXTERNAL_PROJECT_LABEL or os.path.basename(EXTERNAL_PROJECT_PATH)
    return os.path.basename(current_path)


def set_project(name: str = None):
    """Set the working folder to a subdirectory of downloads."""
    global WORK_PATH
    c = Colors

    if name is None:
        # Reset to root downloads folder
        WORK_PATH = OUTPUT_PATH
        print(f"{c.GREEN}✅ Working folder set to:{c.RESET} {c.WHITE}{WORK_PATH}{c.RESET}")
        return True

    raw_name = name.strip()
    if not raw_name:
        print(f"{c.RED}❌ Invalid folder name.{c.RESET}")
        return False

    if EXTERNAL_PROJECT_PATH and raw_name.lower() in get_mounted_project_aliases():
        target = EXTERNAL_PROJECT_PATH
    elif os.path.isabs(raw_name):
        normalized = os.path.normpath(raw_name)
        translated = translate_host_path_to_container(normalized)
        if translated:
            return set_external_project(normalized)
        if EXTERNAL_PROJECT_PATH and is_within_directory(normalized, EXTERNAL_PROJECT_PATH):
            target = normalized
        else:
            print(f"{c.RED}❌ Only paths inside /app/downloads or the shared host roots are allowed.{c.RESET}")
            return False
    else:
        normalized = os.path.normpath(raw_name)
        if normalized in ('.', '..') or normalized.startswith(f"..{os.sep}"):
            print(f"{c.RED}❌ Invalid folder name.{c.RESET}")
            return False
        target = os.path.join(OUTPUT_PATH, normalized)

    os.makedirs(target, exist_ok=True)
    WORK_PATH = target
    print(f"{c.GREEN}✅ Working folder set to:{c.RESET} {c.WHITE}{WORK_PATH}{c.RESET}")
    host_path = translate_container_path_to_host(target)
    if host_path:
        EXTERNAL_PROJECT_PATH = target
        EXTERNAL_PROJECT_SOURCE = host_path
        EXTERNAL_PROJECT_LABEL = os.path.basename(host_path) or host_path
        print(f"{c.DIM}   Host path: {EXTERNAL_PROJECT_SOURCE}{c.RESET}")
    return True


def list_projects():
    """List subdirectories in the downloads folder."""
    c = Colors
    if not os.path.exists(OUTPUT_PATH):
        print(f"{c.YELLOW}📭 No downloads folder yet.{c.RESET}")
        return

    dirs = sorted(d for d in os.listdir(OUTPUT_PATH)
                  if os.path.isdir(os.path.join(OUTPUT_PATH, d)))

    print(f"\n{c.CYAN}{c.BOLD}📂 Projects{c.RESET} {c.DIM}(subfolders in {OUTPUT_PATH}){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")

    # Show root folder
    root_videos = len([f for f in os.listdir(OUTPUT_PATH)
                       if os.path.isfile(os.path.join(OUTPUT_PATH, f))
                       and f.lower().endswith(VIDEO_EXTENSIONS)])
    marker = f" {c.YELLOW}◀ active{c.RESET}" if WORK_PATH == OUTPUT_PATH else ""
    print(f"  {c.GREEN}[root]{c.RESET}  {c.WHITE}/ (downloads root){c.RESET} {c.DIM}({root_videos} videos){c.RESET}{marker}")

    for d in dirs:
        full = os.path.join(OUTPUT_PATH, d)
        vid_count = len([f for f in os.listdir(full)
                         if os.path.isfile(os.path.join(full, f))
                         and f.lower().endswith(VIDEO_EXTENSIONS)])
        marker = f" {c.YELLOW}◀ active{c.RESET}" if WORK_PATH == full else ""
        print(f"  {c.GREEN}[ {d} ]{c.RESET}  {c.DIM}({vid_count} videos){c.RESET}{marker}")

    if EXTERNAL_PROJECT_PATH and os.path.isdir(EXTERNAL_PROJECT_PATH):
        vid_count = len([f for f in os.listdir(EXTERNAL_PROJECT_PATH)
                         if os.path.isfile(os.path.join(EXTERNAL_PROJECT_PATH, f))
                         and f.lower().endswith(VIDEO_EXTENSIONS)])
        marker = f" {c.YELLOW}◀ active{c.RESET}" if is_within_directory(WORK_PATH, EXTERNAL_PROJECT_PATH) else ""
        label = EXTERNAL_PROJECT_LABEL or os.path.basename(EXTERNAL_PROJECT_PATH)
        print(f"  {c.BLUE}[external]{c.RESET} {c.WHITE}{label}{c.RESET} {c.DIM}({vid_count} videos){c.RESET}{marker}")
        if EXTERNAL_PROJECT_SOURCE:
            print(f"      {c.DIM}{EXTERNAL_PROJECT_SOURCE}{c.RESET}")

    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    if HOST_ROOT_MAPPINGS:
        print(f"\n{c.DIM}Switch with:{c.RESET} {c.CYAN}project <name>{c.RESET}  |  {c.CYAN}project external /path/to/folder{c.RESET}  |  {c.CYAN}project root{c.RESET}")
    else:
        print(f"\n{c.DIM}Switch with:{c.RESET} {c.CYAN}project <name>{c.RESET}  |  {c.CYAN}project root{c.RESET} to go back")


def download_video(url: str, quality: str = "best"):
    """Download a YouTube video."""
    c = Colors
    os.makedirs(WORK_PATH, exist_ok=True)
    
    ydl_opts = {
        'outtmpl': os.path.join(WORK_PATH, '%(title)s.%(ext)s'),
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if quality == 'best' else quality,
        'merge_output_format': 'mp4',
        'progress_hooks': [progress_hook],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"\n{c.CYAN}🔍 Fetching video info for:{c.RESET} {url}")
            info = ydl.extract_info(url, download=True)
            print(f"\n{c.GREEN}✅ Downloaded:{c.RESET} {c.WHITE}{info.get('title', 'Unknown')}{c.RESET}")
            print(f"{c.CYAN}📁 Saved to:{c.RESET} {WORK_PATH}")
            return True
    except Exception as e:
        print(f"\n{c.RED}❌ Error downloading video:{c.RESET} {e}")
        return False


def progress_hook(d):
    """Display download progress."""
    c = Colors
    if d['status'] == 'downloading':
        percent = d.get('_percent_str', 'N/A')
        speed = d.get('_speed_str', 'N/A')
        print(f"\r{c.CYAN}⬇️  Downloading:{c.RESET} {c.GREEN}{percent}{c.RESET} at {c.YELLOW}{speed}{c.RESET}   ", end='', flush=True)
    elif d['status'] == 'finished':
        print(f"\n{c.GREEN}✅ Download complete, processing...{c.RESET}")


def download_audio_only(url: str):
    """Download only the audio from a YouTube video as MP3."""
    c = Colors
    os.makedirs(WORK_PATH, exist_ok=True)
    
    ydl_opts = {
        'outtmpl': os.path.join(WORK_PATH, '%(title)s.%(ext)s'),
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'progress_hooks': [progress_hook],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"\n{c.CYAN}🔍 Fetching audio for:{c.RESET} {url}")
            info = ydl.extract_info(url, download=True)
            print(f"\n{c.GREEN}✅ Downloaded audio:{c.RESET} {c.WHITE}{info.get('title', 'Unknown')}{c.RESET}")
            print(f"{c.CYAN}📁 Saved to:{c.RESET} {WORK_PATH}")
            return True
    except Exception as e:
        print(f"\n{c.RED}❌ Error downloading audio:{c.RESET} {e}")
        return False


def get_video_info(url: str):
    """Get information about a video without downloading."""
    c = Colors
    ydl_opts = {'quiet': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print(f"\n{c.CYAN}╔{'═'*48}╗{c.RESET}")
            print(f"{c.CYAN}║{c.RESET}  {c.BOLD}ℹ️  Video Information{c.RESET}")
            print(f"{c.CYAN}╠{'═'*48}╣{c.RESET}")
            print(f"{c.CYAN}║{c.RESET}  {c.WHITE}Title:{c.RESET}    {info.get('title')}")
            print(f"{c.CYAN}║{c.RESET}  {c.WHITE}Duration:{c.RESET} {info.get('duration', 0) // 60}:{info.get('duration', 0) % 60:02d}")
            print(f"{c.CYAN}║{c.RESET}  {c.WHITE}Channel:{c.RESET}  {info.get('channel')}")
            print(f"{c.CYAN}║{c.RESET}  {c.WHITE}Views:{c.RESET}    {info.get('view_count', 'N/A'):,}")
            print(f"{c.CYAN}╚{'═'*48}╝{c.RESET}")
            return info
    except Exception as e:
        print(f"{c.RED}❌ Error fetching info:{c.RESET} {e}")
        return None


def get_video_files():
    """Get list of video files in current working folder."""
    if not os.path.exists(WORK_PATH):
        return []
    
    files = []
    for f in sorted(os.listdir(WORK_PATH)):
        if os.path.isfile(os.path.join(WORK_PATH, f)) and f.lower().endswith(VIDEO_EXTENSIONS):
            files.append(f)
    return files


def list_downloads():
    """List all downloaded files in current working folder."""
    c = Colors
    if not os.path.exists(WORK_PATH):
        print(f"{c.YELLOW}📭 No downloads yet.{c.RESET}")
        return
    
    files = [f for f in os.listdir(WORK_PATH) if os.path.isfile(os.path.join(WORK_PATH, f))]
    subdirs = [d for d in os.listdir(WORK_PATH) if os.path.isdir(os.path.join(WORK_PATH, d))]
    if not files and not subdirs:
        print(f"{c.YELLOW}📭 No files yet.{c.RESET}")
        return
    
    print(f"\n{c.CYAN}{c.BOLD}📁 Files{c.RESET} {c.DIM}({WORK_PATH}){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    # Show subdirectories first
    for d in sorted(subdirs):
        print(f"       📂 {c.CYAN}{d}/{c.RESET}")
    for idx, f in enumerate(sorted(files), 1):
        filepath = os.path.join(WORK_PATH, f)
        size = os.path.getsize(filepath)
        size_mb = size / (1024 * 1024)
        if f.lower().endswith(VIDEO_EXTENSIONS):
            print(f"  {c.GREEN}[{idx:2d}]{c.RESET} 🎬 {c.WHITE}{f}{c.RESET} {c.DIM}({size_mb:.1f} MB){c.RESET}")
        else:
            print(f"       🎵 {c.WHITE}{f}{c.RESET} {c.DIM}({size_mb:.1f} MB){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")


def write_ffmpeg_concat_file(filepaths):
    """Write a concat manifest for ffmpeg and return its path."""
    entries = []
    for filepath in filepaths:
        escaped_path = filepath.replace("\\", "\\\\").replace("'", "\\'")
        entries.append(f"file '{escaped_path}'\n")

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="ytd_concat_",
        delete=False,
        encoding="utf-8",
    )

    try:
        temp_file.writelines(entries)
    finally:
        temp_file.close()

    return temp_file.name


def stitch_videos(output_name: str = None):
    """Interactive video stitching."""
    c = Colors
    video_files = get_video_files()
    
    if not video_files:
        print(f"{c.RED}❌ No video files found in {WORK_PATH}{c.RESET}")
        return False
    
    # Display available videos
    print(f"\n{c.MAGENTA}{c.BOLD}🎬 Available videos for stitching:{c.RESET} {c.DIM}({WORK_PATH}){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    for idx, f in enumerate(video_files, 1):
        filepath = os.path.join(WORK_PATH, f)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  {c.GREEN}[{idx:2d}]{c.RESET} {c.WHITE}{f}{c.RESET} {c.DIM}({size_mb:.1f} MB){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    
    # Get user selection
    print(f"\n{c.CYAN}Enter video numbers to stitch (in order), separated by spaces or commas.{c.RESET}")
    print(f"{c.DIM}Example: 1 3 2  or  1,3,2{c.RESET}")
    
    try:
        selection = input("\nSelect videos: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    if not selection:
        print("No videos selected.")
        return False
    
    # Parse selection
    selection = selection.replace(',', ' ')
    try:
        indices = [int(x.strip()) for x in selection.split() if x.strip()]
    except ValueError:
        print(f"{c.RED}❌ Invalid input. Please enter numbers only.{c.RESET}")
        return False
    
    # Validate indices
    selected_files = []
    for idx in indices:
        if idx < 1 or idx > len(video_files):
            print(f"{c.RED}❌ Invalid selection: {idx}. Valid range is 1-{len(video_files)}{c.RESET}")
            return False
        selected_files.append(video_files[idx - 1])
    
    if len(selected_files) < 2:
        print(f"{c.RED}❌ Please select at least 2 videos to stitch.{c.RESET}")
        return False
    
    # Get output filename
    if not output_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"stitched_{timestamp}.mp4"
        try:
            output_name = input(f"Output filename [{default_name}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return False
        
        if not output_name:
            output_name = default_name
    
    if not output_name.endswith('.mp4'):
        output_name += '.mp4'
    
    output_path = os.path.join(WORK_PATH, output_name)
    
    # Confirm
    print(f"\n{c.CYAN}{c.BOLD}📋 Stitch order:{c.RESET}")
    for i, f in enumerate(selected_files, 1):
        print(f"   {c.GREEN}{i}.{c.RESET} {c.WHITE}{f}{c.RESET}")
    print(f"\n{c.CYAN}📁 Output:{c.RESET} {c.WHITE}{output_name}{c.RESET}")
    
    try:
        confirm = input("\nProceed? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    if confirm and confirm not in ('y', 'yes'):
        print("Cancelled.")
        return False
    
    # Perform stitching with ffmpeg so large files can be streamed instead of loaded into Python.
    source_paths = [os.path.join(WORK_PATH, filename) for filename in selected_files]
    concat_manifest = None

    try:
        print(f"\n{c.YELLOW}🔄 Preparing ffmpeg concat manifest...{c.RESET}")
        for i, filename in enumerate(selected_files, 1):
            print(f"   {c.DIM}Queueing [{i}/{len(selected_files)}]:{c.RESET} {filename}")

        concat_manifest = write_ffmpeg_concat_file(source_paths)
        ffmpeg_command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-stats",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_manifest,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            output_path,
        ]

        print(f"\n{c.YELLOW}🔄 Stitching videos with ffmpeg (this may take a while)...{c.RESET}")
        subprocess.run(
            ffmpeg_command,
            check=True,
        )

        output_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n{c.GREEN}✅ Successfully created:{c.RESET} {c.WHITE}{output_name}{c.RESET} {c.DIM}({output_size:.1f} MB){c.RESET}")
        return True

    except subprocess.CalledProcessError as e:
        print(f"\n{c.RED}❌ ffmpeg failed while stitching videos.{c.RESET}")
        print(f"{c.DIM}Exit code: {e.returncode}{c.RESET}")
        return False
    except Exception as e:
        print(f"\n{c.RED}❌ Error stitching videos:{c.RESET} {e}")
        return False
    finally:
        if concat_manifest and os.path.exists(concat_manifest):
            os.remove(concat_manifest)


def strip_audio_interactive():
    """Interactive command to strip audio from a video file."""
    from moviepy import VideoFileClip

    c = Colors
    video_files = get_video_files()

    if not video_files:
        print(f"{c.RED}\u274c No video files found in {WORK_PATH}{c.RESET}")
        return False

    # Display available videos
    print(f"\n{c.MAGENTA}{c.BOLD}🔇 Strip Audio{c.RESET} {c.DIM}({WORK_PATH}){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    for idx, f in enumerate(video_files, 1):
        filepath = os.path.join(WORK_PATH, f)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  {c.GREEN}[{idx:2d}]{c.RESET} {c.WHITE}{f}{c.RESET} {c.DIM}({size_mb:.1f} MB){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")

    try:
        selection = input("\nSelect video to strip audio from (number): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False

    if not selection:
        print("No video selected.")
        return False

    try:
        idx = int(selection)
        if idx < 1 or idx > len(video_files):
            print(f"{c.RED}\u274c Invalid selection. Choose 1-{len(video_files)}{c.RESET}")
            return False
    except ValueError:
        print(f"{c.RED}\u274c Please enter a number.{c.RESET}")
        return False

    selected_file = video_files[idx - 1]
    input_path = os.path.join(WORK_PATH, selected_file)
    name, ext = os.path.splitext(selected_file)
    default_output = f"{name}_noaudio{ext}"

    try:
        output_name = input(f"{c.CYAN}Output filename{c.RESET} [{default_output}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False

    if not output_name:
        output_name = default_output
    if not output_name.lower().endswith(VIDEO_EXTENSIONS):
        output_name += ext

    output_path = os.path.join(WORK_PATH, output_name)

    print(f"\n{c.CYAN}{c.BOLD}📋 Strip Audio:{c.RESET}")
    print(f"   {c.WHITE}Input:{c.RESET}  {selected_file}")
    print(f"   {c.WHITE}Output:{c.RESET} {output_name}")

    try:
        confirm = input("\nProceed? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False

    if confirm and confirm not in ('y', 'yes'):
        print("Cancelled.")
        return False

    print(f"\n{c.YELLOW}🔄 Stripping audio...{c.RESET}")
    try:
        clip = VideoFileClip(input_path)
        clip_no_audio = clip.without_audio()
        clip_no_audio.write_videofile(
            output_path,
            codec='libx264',
            logger='bar'
        )
        clip_no_audio.close()
        clip.close()

        output_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"\n{c.GREEN}✅ Created:{c.RESET} {c.WHITE}{output_name}{c.RESET} {c.DIM}({output_size:.1f} MB){c.RESET}")
        return True
    except Exception as e:
        print(f"\n{c.RED}❌ Error stripping audio:{c.RESET} {e}")
        return False


def generate_qr_code(url: str, title: str) -> str:
    """Generate a QR code image for a URL and save to downloads folder."""
    import qrcode
    import re
    
    try:
        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Clean title for filename
        safe_title = re.sub(r'[^\w\s-]', '', title).strip()[:50]
        safe_title = re.sub(r'[-\s]+', '_', safe_title)
        
        filename = f"{safe_title}_qr.png"
        filepath = os.path.join(WORK_PATH, filename)
        
        img.save(filepath)
        return filename
        
    except Exception as e:
        print(f"⚠️  Could not generate QR code: {e}")
        return None


def get_gcs_credentials():
    """Get authenticated credentials for Google Cloud Storage."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    
    credentials = None
    
    # Check if we have saved credentials
    if os.path.exists(GCS_TOKEN_FILE):
        with open(GCS_TOKEN_FILE, 'rb') as token:
            credentials = pickle.load(token)
    
    # If no valid credentials, get new ones
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except Exception:
                credentials = None
        
        if not credentials:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                print("❌ client_secrets.json not found!")
                return None
            
            # Manual OAuth flow
            import json
            from urllib.parse import urlencode, urlparse, parse_qs
            
            with open(CLIENT_SECRETS_FILE, 'r') as f:
                client_config = json.load(f)
            
            if 'installed' in client_config:
                client_info = client_config['installed']
            else:
                client_info = client_config['web']
            
            client_id = client_info['client_id']
            client_secret = client_info['client_secret']
            
            auth_params = {
                'client_id': client_id,
                'redirect_uri': 'http://localhost:8080/',
                'response_type': 'code',
                'scope': GCS_SCOPE,
                'access_type': 'offline',
                'prompt': 'consent'
            }
            auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
            
            print("\n🔐 Google Cloud Storage Authentication Required")
            print("=" * 60)
            print("1. Open this URL in your browser:")
            print(f"\n{auth_url}\n")
            print("2. Sign in and grant permissions")
            print("3. Copy the ENTIRE URL from your browser after redirect")
            print("=" * 60)
            
            redirect_url = input("\nPaste the redirect URL here: ").strip()
            
            try:
                parsed = urlparse(redirect_url)
                code = parse_qs(parsed.query).get('code', [None])[0]
                
                if not code:
                    print("❌ Could not find authorization code in URL")
                    return None
            except Exception as e:
                print(f"❌ Error parsing URL: {e}")
                return None
            
            import requests
            token_url = 'https://oauth2.googleapis.com/token'
            token_data = {
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': 'http://localhost:8080/'
            }
            
            try:
                response = requests.post(token_url, data=token_data)
                token_json = response.json()
                
                if 'error' in token_json:
                    print(f"❌ Token error: {token_json.get('error_description', token_json['error'])}")
                    return None
                
                credentials = Credentials(
                    token=token_json['access_token'],
                    refresh_token=token_json.get('refresh_token'),
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=[GCS_SCOPE]
                )
            except Exception as e:
                print(f"❌ Error getting token: {e}")
                return None
        
        # Save credentials
        os.makedirs(CREDENTIALS_PATH, exist_ok=True)
        with open(GCS_TOKEN_FILE, 'wb') as token:
            pickle.dump(credentials, token)
        print("✅ GCS authentication saved for future sessions.")
    
    return credentials


def get_or_set_bucket_name():
    """Get saved bucket name or prompt for one."""
    if os.path.exists(GCS_BUCKET_FILE):
        with open(GCS_BUCKET_FILE, 'r') as f:
            bucket_name = f.read().strip()
            if bucket_name:
                return bucket_name
    
    print("\n📦 Google Cloud Storage Bucket Setup")
    print("-" * 40)
    print("Enter your GCS bucket name.")
    print("(Create one at: https://console.cloud.google.com/storage/browser)")
    
    bucket_name = input("\nBucket name: ").strip()
    
    if bucket_name:
        os.makedirs(CREDENTIALS_PATH, exist_ok=True)
        with open(GCS_BUCKET_FILE, 'w') as f:
            f.write(bucket_name)
        print(f"✅ Bucket name saved: {bucket_name}")
    
    return bucket_name


def backup_to_gcs(filepath: str, bucket_name: str, credentials) -> bool:
    """Upload a file to Google Cloud Storage using REST API with resumable upload."""
    import requests
    from google.auth.transport.requests import Request
    
    try:
        # Refresh credentials if needed
        if credentials.expired:
            credentials.refresh(Request())
        
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        size_mb = file_size / (1024 * 1024)
        
        print(f"   Uploading {filename} ({size_mb:.1f} MB)...")
        
        # Determine content type
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            '.mp4': 'video/mp4',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.mp3': 'audio/mpeg',
            '.png': 'image/png',
        }
        content_type = content_types.get(ext, 'application/octet-stream')
        
        # For files under 5MB, use simple upload
        if file_size < 5 * 1024 * 1024:
            upload_url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket_name}/o?uploadType=media&name=ytd-backups/{filename}"
            
            headers = {
                'Authorization': f'Bearer {credentials.token}',
                'Content-Type': content_type
            }
            
            with open(filepath, 'rb') as f:
                response = requests.post(upload_url, headers=headers, data=f)
        else:
            # Use resumable upload for larger files
            # Step 1: Initiate resumable upload
            init_url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket_name}/o?uploadType=resumable&name=ytd-backups/{filename}"
            
            headers = {
                'Authorization': f'Bearer {credentials.token}',
                'Content-Type': 'application/json',
                'X-Upload-Content-Type': content_type,
                'X-Upload-Content-Length': str(file_size)
            }
            
            init_response = requests.post(init_url, headers=headers, json={'name': f'ytd-backups/{filename}'})
            
            if init_response.status_code != 200:
                error_msg = init_response.json().get('error', {}).get('message', init_response.text)
                print(f"   ❌ Failed to initiate upload: {error_msg}")
                return False
            
            upload_url = init_response.headers['Location']
            
            # Step 2: Upload file in chunks
            chunk_size = 10 * 1024 * 1024  # 10MB chunks
            
            with open(filepath, 'rb') as f:
                uploaded = 0
                while uploaded < file_size:
                    chunk = f.read(chunk_size)
                    chunk_end = uploaded + len(chunk) - 1
                    
                    headers = {
                        'Content-Length': str(len(chunk)),
                        'Content-Range': f'bytes {uploaded}-{chunk_end}/{file_size}'
                    }
                    
                    response = requests.put(upload_url, headers=headers, data=chunk)
                    
                    uploaded += len(chunk)
                    percent = int((uploaded / file_size) * 100)
                    print(f"\r   Uploading {filename}: {percent}%", end='', flush=True)
                    
                    # Check for completion or error
                    if response.status_code not in (200, 201, 308):
                        print()
                        error_msg = response.json().get('error', {}).get('message', response.text) if response.text else 'Unknown error'
                        print(f"   ❌ Failed: {error_msg}")
                        return False
            
            print()  # New line after progress
        
        if response.status_code in (200, 201):
            print(f"   ✅ Uploaded: gs://{bucket_name}/ytd-backups/{filename}")
            return True
        else:
            error_msg = response.json().get('error', {}).get('message', response.text) if response.text else 'Unknown error'
            print(f"   ❌ Failed: {error_msg}")
            return False
        
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def backup_interactive():
    """Interactive backup to Google Cloud Storage."""
    c = Colors
    video_files = get_video_files()
    
    if not video_files:
        print(f"{c.RED}❌ No video files found in {WORK_PATH}{c.RESET}")
        return False
    
    # Get credentials
    credentials = get_gcs_credentials()
    if not credentials:
        return False
    
    # Get bucket name
    bucket_name = get_or_set_bucket_name()
    if not bucket_name:
        print(f"{c.RED}❌ No bucket name provided.{c.RESET}")
        return False
    
    # Display available videos
    print(f"\n{c.BLUE}{c.BOLD}☁️  Cloud Backup{c.RESET} {c.DIM}({WORK_PATH}){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    for idx, f in enumerate(video_files, 1):
        filepath = os.path.join(WORK_PATH, f)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  {c.GREEN}[{idx:2d}]{c.RESET} {c.WHITE}{f}{c.RESET} {c.DIM}({size_mb:.1f} MB){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    
    # Get user selection
    print(f"\n{c.CYAN}Enter video numbers to backup, separated by spaces or commas.")
    print(f"Or type '{c.GREEN}all{c.CYAN}' to backup everything.{c.RESET}")
    
    try:
        selection = input(f"\n{c.CYAN}Select videos:{c.RESET} ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    if not selection:
        print(f"{c.YELLOW}No videos selected.{c.RESET}")
        return False
    
    # Parse selection
    if selection.lower() == 'all':
        selected_files = video_files
    else:
        selection = selection.replace(',', ' ')
        try:
            indices = [int(x.strip()) for x in selection.split() if x.strip()]
        except ValueError:
            print(f"{c.RED}❌ Invalid input. Please enter numbers only.{c.RESET}")
            return False
        
        selected_files = []
        for idx in indices:
            if idx < 1 or idx > len(video_files):
                print(f"{c.RED}❌ Invalid selection: {idx}. Valid range is 1-{len(video_files)}{c.RESET}")
                return False
            selected_files.append(video_files[idx - 1])
    
    # Confirm
    print(f"\n{c.CYAN}{c.BOLD}📋 Backup to:{c.RESET} {c.WHITE}gs://{bucket_name}/ytd-backups/{c.RESET}")
    print(f"   {c.WHITE}Files:{c.RESET} {len(selected_files)} video(s)")
    
    try:
        confirm = input(f"\n{c.CYAN}Proceed with backup?{c.RESET} [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    if confirm and confirm not in ('y', 'yes'):
        print("Cancelled.")
        return False
    
    # Perform backup
    print(f"\n{c.YELLOW}📤 Starting backup...{c.RESET}")
    success_count = 0
    
    for filename in selected_files:
        filepath = os.path.join(WORK_PATH, filename)
        if backup_to_gcs(filepath, bucket_name, credentials):
            success_count += 1
    
    print(f"\n{c.GREEN}✅ Backup complete:{c.RESET} {c.WHITE}{success_count}/{len(selected_files)}{c.RESET} files uploaded")
    return success_count == len(selected_files)


def get_authenticated_service():
    """Get authenticated YouTube API service."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    
    credentials = None
    
    # Check if we have saved credentials
    if os.path.exists(OAUTH_TOKEN_FILE):
        with open(OAUTH_TOKEN_FILE, 'rb') as token:
            credentials = pickle.load(token)
    
    # If no valid credentials, get new ones
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except Exception:
                credentials = None
        
        if not credentials:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                print("❌ client_secrets.json not found!")
                print("   Please follow the setup instructions in README.md")
                return None
            
            # Manual OAuth flow for container compatibility
            import json
            from google.oauth2.credentials import Credentials
            from urllib.parse import urlencode, urlparse, parse_qs
            
            with open(CLIENT_SECRETS_FILE, 'r') as f:
                client_config = json.load(f)
            
            # Get client info (handle both 'installed' and 'web' types)
            if 'installed' in client_config:
                client_info = client_config['installed']
            else:
                client_info = client_config['web']
            
            client_id = client_info['client_id']
            client_secret = client_info['client_secret']
            
            # Build authorization URL
            auth_params = {
                'client_id': client_id,
                'redirect_uri': 'http://localhost:8080/',
                'response_type': 'code',
                'scope': YOUTUBE_UPLOAD_SCOPE,
                'access_type': 'offline',
                'prompt': 'consent'
            }
            auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
            
            print("\n🔐 YouTube Authentication Required")
            print("=" * 60)
            print("1. Open this URL in your browser:")
            print(f"\n{auth_url}\n")
            print("2. Sign in and grant permissions")
            print("3. You'll be redirected to a page that may not load")
            print("4. Copy the ENTIRE URL from your browser's address bar")
            print("   (It will look like: http://localhost:8080/?code=...)")
            print("=" * 60)
            
            redirect_url = input("\nPaste the redirect URL here: ").strip()
            
            # Parse the code from the URL
            try:
                parsed = urlparse(redirect_url)
                code = parse_qs(parsed.query).get('code', [None])[0]
                
                if not code:
                    print("❌ Could not find authorization code in URL")
                    return None
            except Exception as e:
                print(f"❌ Error parsing URL: {e}")
                return None
            
            # Exchange code for tokens
            import requests
            token_url = 'https://oauth2.googleapis.com/token'
            token_data = {
                'client_id': client_id,
                'client_secret': client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': 'http://localhost:8080/'
            }
            
            try:
                response = requests.post(token_url, data=token_data)
                token_json = response.json()
                
                if 'error' in token_json:
                    print(f"❌ Token error: {token_json.get('error_description', token_json['error'])}")
                    return None
                
                credentials = Credentials(
                    token=token_json['access_token'],
                    refresh_token=token_json.get('refresh_token'),
                    token_uri='https://oauth2.googleapis.com/token',
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=[YOUTUBE_UPLOAD_SCOPE]
                )
            except Exception as e:
                print(f"❌ Error getting token: {e}")
                return None
        
        # Save credentials for future use
        os.makedirs(CREDENTIALS_PATH, exist_ok=True)
        with open(OAUTH_TOKEN_FILE, 'wb') as token:
            pickle.dump(credentials, token)
        print("✅ Authentication saved for future sessions.")
    
    return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)


def upload_video_to_youtube(filepath: str, title: str, description: str = "", 
                            privacy: str = "private", tags: list = None):
    """Upload a video to YouTube."""
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    
    youtube = get_authenticated_service()
    if not youtube:
        return False
    
    tags = tags or []
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '22'  # People & Blogs
        },
        'status': {
            'privacyStatus': privacy,
            'selfDeclaredMadeForKids': False
        }
    }
    
    # Create media upload object
    media = MediaFileUpload(
        filepath,
        mimetype='video/mp4',
        resumable=True,
        chunksize=1024*1024  # 1MB chunks
    )
    
    try:
        insert_request = youtube.videos().insert(
            part=','.join(body.keys()),
            body=body,
            media_body=media
        )
        
        print("\n📤 Uploading to YouTube...")
        response = resumable_upload(insert_request)
        
        if response:
            video_id = response.get('id')
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"\n✅ Upload successful!")
            print(f"   Video ID: {video_id}")
            print(f"   URL: {video_url}")
            
            # Generate QR code
            qr_filename = generate_qr_code(video_url, title)
            if qr_filename:
                print(f"   QR Code: {qr_filename}")
            
            if privacy == 'private':
                print(f"\n📢 To share with domain users:")
                print(f"   1. Go to YouTube Studio: https://studio.youtube.com")
                print(f"   2. Click on the video → Details → Visibility")
                print(f"   3. Click 'Share privately' and add email addresses")
            return True
        return False
        
    except HttpError as e:
        print(f"\n❌ Upload failed: {e}")
        return False


def resumable_upload(insert_request):
    """Execute resumable upload with retry logic."""
    from googleapiclient.errors import HttpError
    
    response = None
    error = None
    retry = 0
    
    while response is None:
        try:
            status, response = insert_request.next_chunk()
            if status:
                percent = int(status.progress() * 100)
                print(f"\r   Uploaded: {percent}%", end='', flush=True)
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = f"Retriable HTTP error {e.resp.status}: {e.content}"
            else:
                raise
        except (httplib2.HttpLib2Error, IOError, http.client.NotConnected,
                http.client.IncompleteRead, http.client.ImproperConnectionState,
                http.client.CannotSendRequest, http.client.CannotSendHeader,
                http.client.ResponseNotReady, http.client.BadStatusLine) as e:
            error = f"Retriable error: {e}"
        
        if error:
            retry += 1
            if retry > MAX_RETRIES:
                print(f"\n❌ Max retries exceeded. Last error: {error}")
                return None
            
            sleep_seconds = random.random() * (2 ** retry)
            print(f"\n   Retry {retry}/{MAX_RETRIES} in {sleep_seconds:.1f}s...")
            time.sleep(sleep_seconds)
            error = None
    
    return response


def upload_interactive():
    """Interactive video upload wizard."""
    c = Colors
    video_files = get_video_files()
    
    if not video_files:
        print(f"{c.RED}❌ No video files found in {WORK_PATH}{c.RESET}")
        return False
    
    # Check for client_secrets.json
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"{c.RED}❌ YouTube upload not configured!{c.RESET}")
        print(f"\n{c.YELLOW}To enable uploads, you need to:{c.RESET}")
        print(f"  {c.WHITE}1.{c.RESET} Go to Google Cloud Console (console.cloud.google.com)")
        print(f"  {c.WHITE}2.{c.RESET} Create a project and enable YouTube Data API v3")
        print(f"  {c.WHITE}3.{c.RESET} Create OAuth 2.0 credentials (Desktop app)")
        print(f"  {c.WHITE}4.{c.RESET} Download the JSON and save as 'client_secrets.json'")
        print(f"\n{c.DIM}See README.md for detailed instructions.{c.RESET}")
        return False
    
    # Display available videos
    print(f"\n{c.RED}{c.BOLD}📤 YouTube Upload Wizard{c.RESET} {c.DIM}({WORK_PATH}){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    for idx, f in enumerate(video_files, 1):
        filepath = os.path.join(WORK_PATH, f)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  {c.GREEN}[{idx:2d}]{c.RESET} {c.WHITE}{f}{c.RESET} {c.DIM}({size_mb:.1f} MB){c.RESET}")
    print(f"{c.DIM}{'─' * 60}{c.RESET}")
    
    # Get user selection
    try:
        selection = input("\nSelect video to upload (number): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    if not selection:
        print("No video selected.")
        return False
    
    try:
        idx = int(selection)
        if idx < 1 or idx > len(video_files):
            print(f"{c.RED}❌ Invalid selection. Choose 1-{len(video_files)}{c.RESET}")
            return False
    except ValueError:
        print(f"{c.RED}❌ Please enter a number.{c.RESET}")
        return False
    
    selected_file = video_files[idx - 1]
    filepath = os.path.join(WORK_PATH, selected_file)
    
    # Get video details
    default_title = os.path.splitext(selected_file)[0]
    sources = []
    
    try:
        print(f"\n{c.CYAN}Selected:{c.RESET} {c.WHITE}{selected_file}{c.RESET}")
        print(f"{c.DIM}{'─' * 40}{c.RESET}")
        
        title = input(f"{c.CYAN}Title{c.RESET} [{default_title}]: ").strip()
        if not title:
            title = default_title
        
        description = input(f"{c.CYAN}Description{c.RESET} (optional): ").strip()
        
        # Original sources for attribution
        print(f"\n{c.YELLOW}📎 Original Sources (for attribution):{c.RESET}")
        print(f"  {c.DIM}Enter source URLs or channel names, one per line.")
        print(f"  Press Enter twice when done (or once to skip).{c.RESET}")
        
        sources = []
        while True:
            source = input("  Source: ").strip()
            if not source:
                break
            sources.append(source)
        
        # Build full description with attribution
        if sources:
            attribution = "\n\n---\nOriginal content used with permission from:\n"
            for src in sources:
                attribution += f"• {src}\n"
            attribution += "\nAll rights belong to the original creators."
            description = description + attribution if description else attribution.strip()
        
        tags_input = input(f"{c.CYAN}Tags{c.RESET} (comma-separated, optional): ").strip()
        tags = [t.strip() for t in tags_input.split(',') if t.strip()] if tags_input else []
        
        print(f"\n{c.MAGENTA}🔒 Privacy options:{c.RESET}")
        print(f"  {c.GREEN}private{c.RESET}  - Only you can view")
        print(f"  {c.YELLOW}unlisted{c.RESET} - Anyone with the link can view")
        print(f"  {c.RED}public{c.RESET}   - Anyone can find and view")
        privacy = input(f"{c.CYAN}Privacy{c.RESET} [private]: ").strip().lower()
        if privacy not in ('public', 'unlisted', 'private'):
            privacy = 'private'
        
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    # Confirm
    print(f"\n{c.CYAN}{c.BOLD}📋 Upload Details:{c.RESET}")
    print(f"   {c.WHITE}File:{c.RESET} {selected_file}")
    print(f"   {c.WHITE}Title:{c.RESET} {title}")
    if sources:
        # Show original description without attribution for clarity
        orig_desc = description.split("\n\n---\n")[0] if "\n\n---\n" in description else description
        print(f"   {c.WHITE}Description:{c.RESET} {orig_desc or '(none)'}")
        print(f"   {c.WHITE}Sources:{c.RESET} {', '.join(sources)}")
    else:
        print(f"   {c.WHITE}Description:{c.RESET} {description or '(none)'}")
    print(f"   {c.WHITE}Tags:{c.RESET} {', '.join(tags) if tags else '(none)'}")
    print(f"   {c.WHITE}Privacy:{c.RESET} {privacy}")
    
    try:
        confirm = input("\nProceed with upload? [Y/n]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False
    
    if confirm and confirm not in ('y', 'yes'):
        print("Cancelled.")
        return False
    
    return upload_video_to_youtube(filepath, title, description, privacy, tags)


def qr_interactive():
    """Interactive QR code generation."""
    c = Colors
    try:
        print(f"\n{c.YELLOW}{c.BOLD}📱 QR Code Generator{c.RESET}")
        print(f"{c.DIM}{'─' * 40}{c.RESET}")
        
        url = input(f"{c.CYAN}Enter URL:{c.RESET} ").strip()
        if not url:
            print(f"{c.YELLOW}No URL provided.{c.RESET}")
            return False
        
        default_name = "qr_code"
        name = input(f"{c.CYAN}QR code name{c.RESET} [{default_name}]: ").strip()
        if not name:
            name = default_name
        
        filename = generate_qr_code(url, name)
        if filename:
            print(f"\n{c.GREEN}✅ QR code saved:{c.RESET} {c.WHITE}{filename}{c.RESET}")
            print(f"   {c.DIM}Location: {WORK_PATH}/{filename}{c.RESET}")
            return True
        return False
        
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return False


def print_help():
    """Print help message with colors and icons."""
    c = Colors
    print(f"""
{c.RED}╔{'═' * 48}╗{c.RESET}
{c.RED}║{c.RESET}  {c.BOLD}{c.WHITE}📺  YouTube Downloader CLI{c.RESET}                    {c.RED}║{c.RESET}
{c.RED}╚{'═' * 48}╝{c.RESET}

{c.CYAN}{c.BOLD}⬇️  Download Commands:{c.RESET}
  {c.GREEN}video{c.RESET} <URL>    📥 Download video (best quality MP4)
  {c.GREEN}audio{c.RESET} <URL>    🎵 Download audio only (MP3)
  {c.GREEN}info{c.RESET} <URL>     ℹ️  Get video information

{c.MAGENTA}{c.BOLD}📁 File Management:{c.RESET}
  {c.GREEN}list{c.RESET}           📋 List files in current folder
  {c.GREEN}project{c.RESET}        📂 List / switch project folders
  {c.GREEN}project{c.RESET} <name> 📂 Switch to (or create) a subfolder
    {c.GREEN}project external{c.RESET} 📂 Switch to the current host-mounted folder
    {c.GREEN}project external{c.RESET} <path> 📂 Open a host folder from /Users, /Volumes, or /private
  {c.GREEN}stitch{c.RESET}         🎬 Stitch multiple videos together
  {c.GREEN}strip-audio{c.RESET}    🔇 Strip audio from a video

{c.RED}{c.BOLD}📤 YouTube Upload:{c.RESET}
  {c.GREEN}upload{c.RESET}         🚀 Upload a video to YouTube
  {c.GREEN}auth{c.RESET}           🔑 Re-authenticate with YouTube/GCS

{c.BLUE}{c.BOLD}☁️  Cloud Backup:{c.RESET}
  {c.GREEN}backup{c.RESET}         💾 Backup videos to Google Cloud Storage

{c.YELLOW}{c.BOLD}🛠️  Utilities:{c.RESET}
  {c.GREEN}qr{c.RESET}             📱 Generate a QR code for any URL

{c.DIM}Other:{c.RESET}
  {c.GREEN}help{c.RESET}           ❓ Show this help message
  {c.GREEN}exit{c.RESET}           👋 Exit the CLI

{c.DIM}{'─' * 50}{c.RESET}
{c.BOLD}Examples:{c.RESET}
  {c.CYAN}video{c.RESET} https://www.youtube.com/watch?v=dQw4w9WgXcQ
  {c.CYAN}audio{c.RESET} https://youtu.be/dQw4w9WgXcQ
    {c.CYAN}project external /Volumes/MyDrive/Videos/my-compilation{c.RESET}
  {c.CYAN}project{c.RESET} my-compilation → {c.CYAN}stitch{c.RESET} → {c.CYAN}upload{c.RESET} → {c.CYAN}qr{c.RESET}
""")


def interactive_mode():
    """Run the interactive CLI mode."""
    c = Colors

    # Auto-select project folder from environment variable (set by run.sh)
    project_env = os.environ.get('PROJECT_DIR')
    if project_env:
        set_project(project_env)

    print(f"""
{c.RED}╔{'═' * 48}╗{c.RESET}
{c.RED}║{c.RESET}                                                {c.RED}║{c.RESET}
{c.RED}║{c.RESET}   {c.BOLD}{c.WHITE}📺  YouTube Downloader CLI  📺{c.RESET}               {c.RED}║{c.RESET}
{c.RED}║{c.RESET}                                                {c.RED}║{c.RESET}
{c.RED}║{c.RESET}   {c.DIM}Type '{c.GREEN}help{c.DIM}' for available commands{c.RESET}        {c.RED}║{c.RESET}
{c.RED}║{c.RESET}                                                {c.RED}║{c.RESET}
{c.RED}╚{'═' * 48}╝{c.RESET}
""")

    if EXTERNAL_PROJECT_SOURCE:
        print(f"{c.BLUE}Mounted host project:{c.RESET} {c.WHITE}{EXTERNAL_PROJECT_SOURCE}{c.RESET}")
        print(f"{c.DIM}Use 'project external' to return to it after switching folders.{c.RESET}")
    elif HOST_ROOT_MAPPINGS:
        print(f"{c.DIM}Use 'project external /path/to/folder' to open a host folder.{c.RESET}")
    
    while True:
        # Build prompt showing current project folder
        if WORK_PATH == OUTPUT_PATH:
            folder_label = ""
        else:
            folder_label = f" {c.CYAN}{get_folder_label()}{c.RESET}"
        prompt = f"{c.RED}ytd{c.RESET}{folder_label}{c.BOLD}{c.WHITE}>{c.RESET} "

        try:
            user_input = input(prompt).strip()
            
            if not user_input:
                continue
            
            parts = user_input.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            if command in ('exit', 'quit', 'q'):
                print(f"\n{c.YELLOW}👋 Goodbye!{c.RESET}\n")
                break
            elif command == 'help':
                print_help()
            elif command == 'list':
                list_downloads()
            elif command in ('project', 'proj', 'folder'):
                if not args:
                    list_projects()
                elif args.lower().startswith('external '):
                    set_external_project(args[9:].strip())
                elif args.lower() == 'external':
                    if EXTERNAL_PROJECT_SOURCE:
                        set_external_project(EXTERNAL_PROJECT_SOURCE)
                    else:
                        print(f"{c.YELLOW}Usage:{c.RESET} project external /path/to/folder")
                elif args.lower() in ('root', 'downloads'):
                    set_project(None)
                else:
                    set_project(args)
            elif command == 'stitch':
                stitch_videos(args if args else None)
            elif command in ('strip-audio', 'strip', 'noaudio', 'mute'):
                strip_audio_interactive()
            elif command == 'upload':
                upload_interactive()
            elif command == 'auth':
                # Force re-authentication
                print(f"\n{c.CYAN}{c.BOLD}🔑 Re-authenticate{c.RESET}")
                print(f"  {c.GREEN}1.{c.RESET} YouTube")
                print(f"  {c.GREEN}2.{c.RESET} Google Cloud Storage")
                print(f"  {c.GREEN}3.{c.RESET} Both")
                choice = input(f"\n{c.CYAN}Choice{c.RESET} [3]: ").strip() or "3"
                
                if choice in ('1', '3'):
                    if os.path.exists(OAUTH_TOKEN_FILE):
                        os.remove(OAUTH_TOKEN_FILE)
                        print(f"{c.GREEN}✅ Cleared YouTube credentials.{c.RESET}")
                    get_authenticated_service()
                    
                if choice in ('2', '3'):
                    if os.path.exists(GCS_TOKEN_FILE):
                        os.remove(GCS_TOKEN_FILE)
                        print(f"{c.GREEN}✅ Cleared GCS credentials.{c.RESET}")
                    if choice == '2':
                        get_gcs_credentials()
            elif command == 'qr':
                if args:
                    # If URL provided directly, prompt for name only
                    name = input(f"{c.CYAN}QR code name{c.RESET} [qr_code]: ").strip() or "qr_code"
                    filename = generate_qr_code(args, name)
                    if filename:
                        print(f"{c.GREEN}✅ QR code saved:{c.RESET} {c.WHITE}{filename}{c.RESET}")
                else:
                    qr_interactive()
            elif command == 'backup':
                backup_interactive()
            elif command == 'video':
                if not args:
                    print(f"{c.YELLOW}Usage:{c.RESET} video <URL>")
                else:
                    download_video(args)
            elif command == 'audio':
                if not args:
                    print(f"{c.YELLOW}Usage:{c.RESET} audio <URL>")
                else:
                    download_audio_only(args)
            elif command == 'info':
                if not args:
                    print(f"{c.YELLOW}Usage:{c.RESET} info <URL>")
                else:
                    get_video_info(args)
            else:
                # Assume it's a URL if it looks like one
                if user_input.startswith(('http://', 'https://', 'www.')):
                    download_video(user_input)
                else:
                    print(f"{c.RED}Unknown command:{c.RESET} {command}")
                    print(f"{c.DIM}Type 'help' for available commands{c.RESET}")
                    
        except KeyboardInterrupt:
            print(f"\n{c.DIM}Use 'exit' to quit{c.RESET}")
        except EOFError:
            print(f"\n{c.YELLOW}👋 Goodbye!{c.RESET}")
            break


def main():
    if len(sys.argv) < 2:
        # No arguments - enter interactive mode
        interactive_mode()
        return
    
    url = sys.argv[1]
    
    if url in ('--help', '-h', 'help'):
        print_help()
    elif "--info" in sys.argv:
        get_video_info(url)
    elif "--audio" in sys.argv:
        download_audio_only(url)
    else:
        download_video(url)


if __name__ == "__main__":
    main()
