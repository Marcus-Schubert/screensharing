import asyncio
import logging
import os
import socket
from datetime import datetime, timezone

from aiohttp import web

from command_builder import StreamCommandBuilder
from exceptions import CaptureError

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Detects the local LAN/WLAN IP address of the Asahi Linux system."""
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
        fps: int = 30,
        mode: str = "mp4"
    ):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.resolution = resolution
        self.bitrate_mbps = bitrate_mbps
        self.fps = fps
        self.mode = mode
        self.local_ip = get_local_ip()
        
        self.app = web.Application()
        self.app.router.add_get('/', self.handle_index)
        self.app.router.add_get('/stream.mp4', self.handle_stream_mp4)
        self.app.router.add_get('/stream.webm', self.handle_stream_webm)
        
        # CORS Preflight OPTIONS routes
        self.app.router.add_options('/stream.mp4', self.handle_options)
        self.app.router.add_options('/stream.webm', self.handle_options)
        
        self.runner = None
        self.site = None
        self.proc = None
        self._stderr_task = None
        self._lock = asyncio.Lock()

    def get_stream_url(self) -> str:
        if self.mode == "mp4":
            return f"http://{self.local_ip}:{self.port}/stream.mp4"
        return f"http://{self.local_ip}:{self.port}/stream.webm"

    def get_content_type(self) -> str:
        if self.mode == "mp4":
            return "video/mp4"
        return "video/webm"

    async def handle_options(self, request: web.Request):
        return web.Response(
            status=204,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, OPTIONS',
                'Access-Control-Allow-Headers': '*',
            }
        )

    async def handle_index(self, request: web.Request):
        mode_label = "Fragmented MP4 (Ultra-Low Latency)" if self.mode == "mp4" else "WebM Progressive"
        html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Asahi Linux Screen Sharing ({self.mode.upper()})</title>
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
        p {{ line-height: 1.6; }}
        code {{ background: rgba(0, 0, 0, 0.4); padding: 4px 8px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🖥️ Asahi Linux Screen Share ({mode_label})</h1>
        <p>Live Streaming to Nvidia Shield Pro / Chromecast</p>
        <p><strong>Stream URL:</strong> <code>{self.get_stream_url()}</code></p>
        <p><strong>Content-Type:</strong> <code>{self.get_content_type()}</code></p>
        <p><strong>Settings:</strong> {self.resolution} | {self.bitrate_mbps} Mbps | {self.fps} FPS</p>
    </div>
</body>
</html>"""
        return web.Response(text=html, content_type='text/html')

    async def _start_capture(self):
        builder = StreamCommandBuilder(self.node_id, self.resolution, self.bitrate_mbps, self.fps)
        try:
            if self.mode == "mp4":
                cmd = builder.build_fragmented_mp4_command()
            else:
                cmd = builder.build_progressive_command()
        except Exception as e:
            raise CaptureError(f"Failed to build capture command: {e}")

        logger.info(f"Starting Screen Capture ({self.mode.upper()}): {' '.join(cmd)}")

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
                    logger.warning(f"GStreamer {self.mode.upper()}: {msg}")

        self._stderr_task = asyncio.create_task(read_stderr())

    async def _stop_capture(self):
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None

        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    async def handle_stream_mp4(self, request: web.Request):
        if self.mode != "mp4":
            raise web.HTTPBadRequest(text="Server is running in WebM mode. Please use /stream.webm.")

        logger.info(f"Fragmented MP4 stream request ({self.resolution}, {self.bitrate_mbps} Mbps, {self.fps} fps) received from {request.remote}")
        
        transport = request.transport
        if transport:
            sock = transport.get_extra_info('socket')
            if sock:
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass

        async with self._lock:
            await self._stop_capture()
            await self._start_capture()

        response = web.StreamResponse(
            status=200,
            reason='OK',
            headers={
                'Content-Type': 'video/mp4',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache, no-store, must-revalidate'
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
                await response.drain()
        except (ConnectionResetError, asyncio.CancelledError, BrokenPipeError, ConnectionError):
            logger.info("Client connection terminated.")
        except Exception as e:
            logger.error(f"Error streaming data: {e}")
        finally:
            async with self._lock:
                await self._stop_capture()
        
        return response

    async def handle_stream_webm(self, request: web.Request):
        if self.mode != "webm":
            raise web.HTTPBadRequest(text="Server is running in MP4 mode. Please use /stream.mp4.")

        logger.info(f"VP8/WebM Stream-Anfrage empfangen von {request.remote}")
        
        transport = request.transport
        if transport:
            sock = transport.get_extra_info('socket')
            if sock:
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except Exception:
                    pass

        async with self._lock:
            await self._stop_capture()
            await self._start_capture()

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
                await response.drain()
        except (ConnectionResetError, asyncio.CancelledError, BrokenPipeError, ConnectionError):
            logger.info("Client connection terminated.")
        except Exception as e:
            logger.error(f"Error streaming data: {e}")
        finally:
            async with self._lock:
                await self._stop_capture()
        
        return response

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"{self.mode.upper()} Streaming-Server bereit unter {self.get_stream_url()}")

    async def stop(self):
        async with self._lock:
            await self._stop_capture()

        if self.runner:
            await self.runner.cleanup()
            logger.info("Streaming-Server gestoppt.")
