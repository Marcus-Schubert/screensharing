import shutil

class StreamCommandBuilder:
    def __init__(self, node_id: int | None, resolution: str, bitrate_mbps: int, fps: int):
        self.node_id = node_id
        self.resolution = resolution
        self.bitrate_mbps = bitrate_mbps
        self.fps = fps
        self.bitrate_bps = bitrate_mbps * 1000000

    @property
    def resolution_width(self):
        return 1920 if self.resolution == "1080p" else 1280

    @property
    def resolution_height(self):
        return 1080 if self.resolution == "1080p" else 720

    def build_progressive_command(self) -> list[str]:
        pipewire_src = (
            ["pipewiresrc", f"path={self.node_id}", "do-timestamp=true", "keepalive-time=1000"]
            if self.node_id
            else ["pipewiresrc", "do-timestamp=true", "keepalive-time=1000"]
        )
        
        if shutil.which("gst-launch-1.0"):
            scale_elements = []
            if self.resolution in ("1080p", "720p"):
                scale_elements = [
                    "videoscale", "!", f"video/x-raw,width={self.resolution_width},height={self.resolution_height}", "!"
                ]

            return [
                "gst-launch-1.0", "-q", *pipewire_src, "!",
                "queue", "max-size-buffers=1", "leaky=downstream", "!",
                "videoconvert", "!", "videorate", "!", f"video/x-raw,framerate={self.fps}/1,format=I420", "!",
                *scale_elements,
                "vp8enc",
                f"target-bitrate={self.bitrate_bps}",
                "cpu-used=16",
                "threads=4",
                "deadline=1",
                "end-usage=cbr",
                "buffer-size=100",
                "buffer-initial-size=50",
                "buffer-optimal-size=50",
                "lag-in-frames=0",
                "keyframe-max-dist=15",
                "auto-alt-ref=false", "!",
                "webmmux",
                "streamable=true",
                "min-cluster-duration=100000000",
                "max-cluster-duration=200000000", "!",
                "fdsink"
            ]
        raise RuntimeError("gst-launch-1.0 not found")

    def build_fragmented_mp4_command(self) -> list[str]:
        pipewire_src = (
            ["pipewiresrc", f"path={self.node_id}", "do-timestamp=true", "keepalive-time=1000"]
            if self.node_id
            else ["pipewiresrc", "do-timestamp=true", "keepalive-time=1000"]
        )

        if shutil.which("gst-launch-1.0"):
            scale_elements = []
            if self.resolution in ("1080p", "720p"):
                scale_elements = [
                    "videoscale", "!", f"video/x-raw,width={self.resolution_width},height={self.resolution_height}", "!"
                ]

            return [
                "gst-launch-1.0", "-q", *pipewire_src, "!",
                "queue", "max-size-buffers=1", "leaky=downstream", "!",
                "videoconvert", "!", "videorate", "!", f"video/x-raw,framerate={self.fps}/1,format=I420", "!",
                *scale_elements,
                "openh264enc",
                "usage-type=screen",
                "complexity=low",
                "rate-control=bitrate",
                f"bitrate={self.bitrate_bps}",
                f"gop-size={self.fps}",
                "multi-thread=4", "!",
                "h264parse", "config-interval=-1", "!",
                "qtmux",
                "fragment-duration=1000",
                "faststart=true", "!",
                "fdsink"
            ]
        raise RuntimeError("gst-launch-1.0 not found")
