# ADR 0001: Fragmented MP4 Screen Sharing Architecture for Sub-2-Second Latency

## Status
Accepted

## Context
Streaming the Wayland desktop screen from an Asahi Linux machine (Apple Silicon ARM64) to an Nvidia Shield Pro (Android TV / Chromecast receiver) requires ultra-low latency (~1-2 seconds) without requiring any app installations on the Nvidia Shield.

Initial implementations explored:
1. **Progressive WebM (`vp8enc` + `webmmux`):** Hit the "10-second progressive wall" because Google's Default Media Receiver (`CC1AD845`) enforces a hardcoded ~10s pre-roll buffer for progressive HTTP video files.
2. **MPEG-DASH (`dashsink` + MPEG-TS):** Failed on the Chromecast receiver because Chromium's Media Source Extensions (MSE) do not support raw MPEG-TS (`video/mp2t`) containers.

## Decision
We implemented **Fragmented MP4 (fMP4) over HTTP chunked streaming**:

1. **Capture & Encoding (`wayland_screencast.py` & `command_builder.py`):**
   - Captures screen via `xdg-desktop-portal` and PipeWire (`pipewiresrc do-timestamp=true`).
   - Encodes to H.264 using GStreamer's **`openh264enc`** (`usage-type=screen`, `complexity=low`, `rate-control=bitrate`, `gop-size=30`, `multi-thread=4`).
   - Inserts SPS/PPS headers at every IDR keyframe (`h264parse config-interval=-1`).
   - Muxes into Fragmented MP4 using **`qtmux fragment-duration=1000 faststart=true`** piped to **`fdsink`**.

2. **Asynchronous On-Demand HTTP Streaming (`capture_server.py`):**
   - Serves the Fragmented MP4 stream via `aiohttp` at `/stream.mp4` with `Content-Type: video/mp4` and `Access-Control-Allow-Origin: *`.
   - Enables `TCP_NODELAY` and immediately flushes chunks (`drain()`) with minimal buffering.

3. **Chromecast Integration (`cast_manager.py`):**
   - Casts the stream URL with `content_type="video/mp4"`, `stream_type="LIVE"`, and `title=""`.

## Consequences
- **Ultra-Low Latency:** Fragmented MP4 sends independent `moof`/`mdat` fragments that Chromium MSE decodes and renders immediately as they arrive, achieving **~1.5 seconds latency** with zero buffer delay.
- **Native Compatibility:** Chromium / Chromecast MSE natively supports H.264 inside Fragmented MP4 (`video/mp4`).
- **Zero Shield Apps:** Maintains the strict requirement of zero app installations on the Nvidia Shield Pro.
