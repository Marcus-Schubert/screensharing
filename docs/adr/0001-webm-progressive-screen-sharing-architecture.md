# ADR 0001: WebM Progressive Screen Sharing Architecture for Asahi Linux to Nvidia Shield Pro (Chromecast)

## Status
Accepted

## Context
Streaming the Wayland desktop screen from an Asahi Linux machine (Apple Silicon ARM64) to an Nvidia Shield Pro (Android TV / Chromecast receiver) requires:
1. Secure capture of the Wayland display via `xdg-desktop-portal` and PipeWire.
2. Ultra-low latency real-time video encoding and streaming (~1-2 seconds delay).
3. Compatibility with Chromecast's media player receiver (`CC1AD845`), which supports progressive WebM streaming over HTTP.
4. Clean presentation without persistent time progress bars, loading spinners, or intrusive title overlays.

## Decision
We implemented the following architecture:

1. **Capture & PipeWire Integration (`wayland_screencast.py` & `command_builder.py`):**
   - Uses `xdg-desktop-portal` to obtain a secure PipeWire screen node ID via interactive user confirmation.
   - Pipes raw frames (`pipewiresrc`) into `videoconvert`, `videoscale`, and GStreamer's **`vp8enc`** encoder (optimized with `target-bitrate`, `cpu-used=12`, `threads=4`, `deadline=1`, `keyframe-max-dist=15`).
   - Multiplexes into WebM container using **`webmmux streamable=true`** piped to **`fdsink`**.

2. **Asynchronous HTTP Streaming (`capture_server.py`):**
   - Serves the raw WebM stream via an asynchronous **`aiohttp`** server endpoint (`/stream.webm`) with `Content-Type: video/webm` and `Access-Control-Allow-Origin: *`.
   - Streams chunks from GStreamer stdout directly to the client connection with minimal buffering for sub-2-second latency.

3. **Chromecast Integration (`cast_manager.py`):**
   - Discovers Chromecast devices via `pychromecast` and Zeroconf (mDNS) or direct IP connection (`--ip`).
   - Initiates playback with `content_type="video/webm"`, `stream_type="LIVE"`, and an empty title (`title=""`) to configure the Chromecast receiver for live broadcasting and suppress unwanted UI overlays and progress bars.

---

## Alternatives Considered

### 1. HLS (HTTP Live Streaming) via `hlssink`
- **Approach:** Using GStreamer's `hlssink` with MPEG-TS (`.ts`) segments and `.m3u8` playlists.
- **Result:** Introduced a painful 12-15 second latency due to segment buffering, and caused the Chromecast Default Media Receiver to constantly reset state and re-trigger the UI overlay every few seconds.

### 2. Raw Progressive HTTP Streaming without Chunked Protocol
- **Approach:** Piping raw sockets without proper stream response handling.
- **Result:** Caused `Cannot write to closing transport` timeouts and immediate connection drops on Android TV.
