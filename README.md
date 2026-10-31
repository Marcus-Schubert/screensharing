# Linux Screen Sharing

Stream your Linux desktop to Nvidia Shield / Chromecast devices over your local network.

> ⚠️ **Early Alpha** — This project is under active development. Expect rough edges and breaking changes.

## How It Works

```
┌──────────────┐     PipeWire      ┌──────────────┐    Fragmented MP4     ┌──────────────────┐
│   Wayland    │ ──────────────▶  │  GStreamer    │ ──────────────▶       │  Nvidia Shield / │
│   Desktop    │   screen capture  │ H.264 Encoder│   (HTTP Chunked fMP4) │  Chromecast      │
└──────────────┘                   └──────────────┘                       └──────────────────┘
```

1. Requests screen capture permission via `xdg-desktop-portal` (KDE dialog)
2. Captures frames through PipeWire and encodes to H.264 (`openh264enc`) using GStreamer
3. Packages into Fragmented MP4 (`qtmux fragment-duration=1000`) for true low-latency chunked streaming
4. Sends the stream URL to your Chromecast/Shield via `pychromecast` with ultra-low latency (~1.5s)

## Tested Configuration

| Component       | Version / Details                          |
|-----------------|--------------------------------------------|
| OS              | Asahi Linux (Apple Silicon / ARM64)        |
| Desktop         | KDE Plasma 6 (Wayland)                     |
| Target Device   | Nvidia Shield Pro (Android TV / Chromecast)|
| Python          | 3.14                                       |
| GStreamer       | 1.28.x                                     |

Other Linux distributions with Wayland, PipeWire, and GStreamer may work but are not tested or guaranteed.

## Prerequisites

### System Packages

You need these installed on your system (package names may vary by distro):

- **GStreamer 1.x** and plugins:
  - `gstreamer` (core)
  - `gst-plugins-base` (videoconvert, videoscale, qtmux)
  - `gst-plugins-good` (vp8enc, webmmux, pipewiresrc)
  - `openh264` / `gstreamer1-plugin-openh264` (openh264enc)
- **PipeWire** (running as your audio/video server)
- **xdg-desktop-portal** + KDE portal backend (`xdg-desktop-portal-kde`)
- **Python 3.10+**

On Arch-based systems (including Asahi Linux):
```bash
sudo pacman -S gstreamer gst-plugins-base gst-plugins-good openh264 pipewire xdg-desktop-portal xdg-desktop-portal-kde python
```

On Fedora-based systems (including Asahi Linux Fedora Remix):
```bash
sudo dnf install gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good gstreamer1-plugin-openh264 openh264 pipewire xdg-desktop-portal xdg-desktop-portal-kde python3
```

On Debian/Ubuntu-based systems:
```bash
sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pipewire pipewire xdg-desktop-portal python3
```

### Python Dependencies

```bash
pip install pychromecast zeroconf aiohttp PyGObject
```

## Usage

### Basic — Cast to Shield by IP (Fragmented MP4, Ultra-Low Latency)

```bash
python3 main.py --ip <SHIELD_IP>
```

### List Available Chromecast Devices

```bash
python3 main.py --list
```

### Cast to a Named Device

```bash
python3 main.py --device "SHIELD"
```

### Custom Quality Settings

```bash
python3 main.py --ip <SHIELD_IP> --res 720p --bitrate 4 --fps 24
```

### All Options

| Flag           | Default  | Description                                    |
|----------------|----------|------------------------------------------------|
| `--ip`         | —        | Direct IP address of the target device         |
| `-d, --device` | —        | Name of the target Chromecast device           |
| `-p, --port`   | `8080`   | Local HTTP server port                         |
| `-m, --mode`   | `mp4`    | Streaming mode (`mp4` for Fragmented MP4 ultra-low latency, or `webm` for progressive WebM fallback) |
| `--res`        | `1080p`  | Target resolution (`1080p`, `720p`)            |
| `--bitrate`    | `8`      | Video bitrate in Mbps                          |
| `--fps`        | `30`     | Frames per second                              |
| `-l, --list`   | —        | List discovered Chromecast devices and exit    |

## Project Structure

```
├── main.py                  # Entry point and CLI argument handling
├── capture_server.py        # aiohttp server streaming Fragmented MP4 / WebM over HTTP
├── cast_manager.py          # Chromecast discovery and media casting
├── command_builder.py       # GStreamer pipeline command construction
├── wayland_screencast.py    # xdg-desktop-portal / PipeWire integration
├── exceptions.py            # Custom exception hierarchy
├── pyproject.toml           # Project metadata and dependencies
```
