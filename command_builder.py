import shutil
from typing import List, Optional

class StreamCommandBuilder:
    def __init__(self, node_id: Optional[int], resolution: str, bitrate_mbps: int, fps: int):
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

    def build_progressive_command(self) -> List[str]:
        pipewire_src = ["pipewiresrc", f"path={self.node_id}"] if self.node_id else ["pipewiresrc"]
        
        if shutil.which("gst-launch-1.0"):
            return [
                "gst-launch-1.0", "-q", *pipewire_src, "!", 
                "videoconvert", "!", "video/x-raw,format=I420", "!",
                "videoscale", "!", f"video/x-raw,width={self.resolution_width},height={self.resolution_height}", "!",
                "vp8enc", f"target-bitrate={self.bitrate_bps}", "cpu-used=12", "threads=4", "deadline=1", "keyframe-max-dist=15", "!",
                "webmmux", "streamable=true", "!",
                "fdsink"
            ]
        raise RuntimeError("gst-launch-1.0 not found")

    def build_hls_command(self, output_dir: str) -> List[str]:
        pipewire_src = ["pipewiresrc", f"path={self.node_id}"] if self.node_id else ["pipewiresrc"]
        
        if shutil.which("gst-launch-1.0"):
            return [
                "gst-launch-1.0", "-v", *pipewire_src, "!", 
                "videoconvert", "!", "video/x-raw,format=I420", "!",
                "videoscale", "!", f"video/x-raw,width={self.resolution_width},height={self.resolution_height}", "!",
                "openh264enc", f"bitrate={self.bitrate_bps}", "gop-size=15", "!",
                "video/x-h264,stream-format=byte-stream", "!",
                "mpegtsmux", "!",
                "hlssink",
                f"location={output_dir}/segment_%05d.ts",
                f"playlist-location={output_dir}/playlist.m3u8",
                "target-duration=2",
                "max-files=5"
            ]
        raise RuntimeError("gst-launch-1.0 not found")
