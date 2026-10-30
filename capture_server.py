import asyncio
import logging
import socket

from aiohttp import web

from command_builder import StreamCommandBuilder
from exceptions import CaptureError

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Erkennt die lokale LAN/WLAN-IP-Adresse des Asahi-Linux-Systems."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


class StreamCaptureServer:
    def __init__(
        self,
        node_id: int | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        resolution: str = "1080p",
        bitrate_mbps: int = 8,
        fps: int = 30
    ):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.resolution = resolution
        self.bitrate_mbps = bitrate_mbps
        self.fps = fps
        self.local_ip = get_local_ip()
        
        self.app = web.Application()
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/stream.webm', self.handle_stream)
        
        self.runner = None
        self.site = None
        self.proc = None

    def get_stream_url(self) -> str:
        return f"http://{self.local_ip}:{self.port}/stream.webm"

    async def handle_index(self, request: web.Request):
        html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Asahi Linux Screen Sharing (WebM)</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
        }}
        .card {{
            background: rgba(30, 41, 59, 0.8);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 32px;
            text-align: center;
            max-width: 800px;
            width: 90%;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
        }}
        h1 {{ margin-top: 0; color: #38bdf8; }}
        video {{
            width: 100%;
            border-radius: 8px;
            background: #000;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🖥️ Asahi Linux Screen Share (WebM)</h1>
        <p>Live WebM Stream für Nvidia Shield Pro / Chromecast</p>
        <p><strong>Stream URL:</strong> <code>{self.get_stream_url()}</code></p>
        <video controls autoplay muted src="/stream.webm"></video>
    </div>
</body>
</html>"""
        return web.Response(text=html, content_type='text/html')

    async def handle_stream(self, request: web.Request):
        logger.info(f"VP8/WebM Stream-Anfrage ({self.resolution}, {self.bitrate_mbps} Mbps, {self.fps} fps) empfangen von {request.remote}")
        
        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'video/webm',
                'Access-Control-Allow-Origin': '*'
            }
        )
        await response.prepare(request)

        try:
            while True:
                if not self.proc or not self.proc.stdout:
                    break
                chunk = await self.proc.stdout.read(65536)
                if not chunk:
                    break
                await response.write(chunk)
        except (ConnectionResetError, asyncio.CancelledError, BrokenPipeError, ConnectionError):
            logger.info("Client-Verbindung getrennt.")
        except Exception as e:
            logger.error(f"Error streaming data: {e}")
        
        return response

    async def start(self):
        # 1. Start GStreamer background process capturing screen and outputting WebM to stdout
        builder = StreamCommandBuilder(self.node_id, self.resolution, self.bitrate_mbps, self.fps)
        try:
            cmd = builder.build_progressive_command()
        except Exception as e:
            raise CaptureError(f"Failed to build progressive command: {e}")

        logger.info(f"Starte Screen Capture (WebM): {' '.join(cmd)}")

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        async def read_stderr():
            while True:
                if not self.proc or not self.proc.stderr:
                    break
                line = await self.proc.stderr.readline()
                if not line:
                    break
                msg = line.decode().strip()
                if msg:
                    logger.error(f"GStreamer WebM: {msg}")

        asyncio.create_task(read_stderr())

        # 2. Start HTTP Server
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"WebM Streaming-Server gestartet unter http://{self.local_ip}:{self.port}")

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await self.proc.wait()
            except Exception:
                pass
            self.proc = None

        if self.runner:
            await self.runner.cleanup()
            logger.info("WebM Streaming-Server gestoppt.")
