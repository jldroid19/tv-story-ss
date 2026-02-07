# 📺 YouTube Downloader CLI (ytd)

A Docker-based CLI utility to download YouTube videos, stitch them together, upload to your YouTube channel, and backup to Google Cloud Storage.

## ✨ Features

- 📥 **Download** videos and audio from YouTube
- 🎬 **Stitch** multiple videos into one
- 🚀 **Upload** videos directly to your YouTube account
- ☁️ **Backup** videos to Google Cloud Storage
- 📱 **QR Codes** - Generate QR codes for any URL

## 🚀 Quick Start

```bash
./run.sh
```

This builds and runs the container, dropping you into an interactive shell.

## 📋 Commands

| Command | Description |
|---------|-------------|
| `video <URL>` | 📥 Download video (best quality MP4) |
| `audio <URL>` | 🎵 Download audio only (MP3) |
| `info <URL>` | ℹ️ Get video information |
| `list` | 📋 List downloaded files |
| `stitch` | 🎬 Stitch multiple videos together |
| `upload` | 🚀 Upload a video to YouTube (with QR code generation) |
| `backup` | ☁️ Backup videos to Google Cloud Storage |
| `qr` | 📱 Generate a QR code for any URL |
| `auth` | 🔑 Re-authenticate with YouTube and/or GCS |
| `help` | ❓ Show all commands |
| `exit` | 👋 Exit the CLI |

## 🔐 YouTube Upload Setup

To enable uploading videos to YouTube, you need to set up Google API credentials:

### Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Name it (e.g., "YouTube Uploader") and click **Create**

### Step 2: Enable YouTube Data API

1. In your project, go to **APIs & Services** → **Library**
2. Search for "YouTube Data API v3"
3. Click on it and press **Enable**

### Step 3: Configure OAuth Consent Screen

1. Go to **APIs & Services** → **OAuth consent screen**
2. Select **External** and click **Create**
3. Fill in required fields:
   - App name: "YTD CLI"
   - User support email: your email
   - Developer contact: your email
4. Click **Save and Continue**
5. On "Scopes" page, click **Add or Remove Scopes**
   - Find and select `https://www.googleapis.com/auth/youtube.upload`
   - Click **Update** then **Save and Continue**
6. On "Test users" page, click **Add Users**
   - Add your Gmail address
   - Click **Save and Continue**

### Step 4: Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Application type: **Desktop app**
4. Name: "YTD CLI"
5. Click **Create**
6. Click **Download JSON**
7. Save the file as `client_secrets.json` in this project folder

### Step 5: First Authentication

1. Run `./run.sh`
2. Type `upload` and select a video
3. A URL will be shown - open it in your browser
4. Sign in with the Google account you added as a test user
5. Grant permissions
6. Authentication is saved for future sessions

## 📂 File Structure

```
.
├── run.sh                  # 🚀 Build and run script
├── Dockerfile              # 🐳 Container definition
├── requirements.txt        # 📦 Python dependencies
├── youtube_downloader.py   # 🐍 Main CLI application
├── client_secrets.json     # 🔐 Your OAuth credentials (not in git)
├── credentials/            # 💾 Saved auth tokens (not in git)
└── downloads/              # 🎥 Downloaded/stitched videos (not in git)
```

## ☁️ Google Cloud Storage Backup Setup

To enable backing up videos to Google Cloud Storage:

### Step 1: Enable Cloud Storage API

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project (same one used for YouTube)
3. Go to **APIs & Services** → **Library**
4. Search for "Cloud Storage" or "Google Cloud Storage JSON API"
5. Click **Enable**

### Step 2: Create a Storage Bucket

1. Go to **Cloud Storage** → **Buckets**
2. Click **Create Bucket**
3. Choose a unique name (e.g., `my-ytd-backups`)
4. Select a region close to you
5. Leave other settings as default and click **Create**

### Step 3: First Backup

1. Run `./run.sh` and type `backup`
2. You'll be prompted to authenticate (similar to YouTube)
3. Enter your bucket name when prompted
4. Select videos to backup

Files are stored in `gs://your-bucket/ytd-backups/`

## 🛠️ Feature Details

### 🎬 Video Stitching

The `stitch` command allows you to combine multiple downloaded videos into one:
1. Videos are displayed with numbers
2. Enter the numbers in the order you want them combined (e.g., `1 3 2`)
3. Choose an output filename
4. The tool preserves video and audio quality

### 🚀 YouTube Upload

When uploading with the `upload` command:
- **🎥 Title & Description** - Customize metadata
- **📎 Original Sources** - Add attribution for reused content (automatically formatted in description)
- **🏷️ Tags** - Add searchable keywords
- **🔒 Privacy** - Choose private/unlisted/public
- **📱 QR Code** - Automatically generated after successful upload and saved to downloads folder

### 📱 QR Code Generation

Use `qr` to create QR codes for any URL:
- Enter a URL and a name for the file
- QR code PNG is saved to the downloads folder
- Useful for sharing video links

## 📝 Notes

- 📁 Videos are saved to `./downloads/` on your host machine
- 🔐 The first time you upload/backup, you'll need to authenticate via browser
- 💾 After authentication, tokens are saved and reused
- 🔒 Your `client_secrets.json` is mounted read-only for security
- 🔑 If you get authentication errors, run `auth` to re-authenticate
- 📱 QR codes are automatically generated for uploaded videos

## 🔒 Privacy Settings

When uploading, you can choose:
- 🔒 **private** (default) - Only you can view
- 🔗 **unlisted** - Anyone with the link can view
- 🌍 **public** - Anyone can find and view

## 📦 Requirements

- 🐳 nerdctl or Docker (auto-detected)
- 📧 A Google account for YouTube uploads and Cloud Storage
