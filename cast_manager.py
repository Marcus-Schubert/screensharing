import asyncio
import logging
import threading

import pychromecast
from pychromecast.models import CastInfo
import zeroconf

from exceptions import CastError

logger = logging.getLogger(__name__)

# Catch Zeroconf background thread exceptions on shutdown
_orig_excepthook = threading.excepthook

def _custom_excepthook(args):
    if args.exc_type is zeroconf.NotRunningException or "zeroconf" in str(args.thread.name).lower():
        return
    _orig_excepthook(args)

threading.excepthook = _custom_excepthook


class ChromecastManager:
    def __init__(self):
        self.zconf: zeroconf.Zeroconf | None = None
        self.browser = None
        self.active_cast: pychromecast.Chromecast | None = None
        self.found_devices: dict[str, pychromecast.Chromecast] = {}

    def _ensure_zeroconf(self):
        if not self.zconf:
            self.zconf = zeroconf.Zeroconf()

    async def discover_devices(self, known_hosts: list[str] | None = None, timeout: float = 3.5) -> list[dict]:
        """Searches for Chromecast devices (e.g. Nvidia Shield Pro) on the local network."""
        logger.info(f"Searching for Chromecast devices on network ({timeout}s)...")
        self._ensure_zeroconf()

        loop = asyncio.get_running_loop()

        def _sync_discover():
            try:
                return pychromecast.get_chromecasts(
                    known_hosts=known_hosts,
                    timeout=timeout,
                    zeroconf_instance=self.zconf
                )
            except Exception as e:
                raise CastError(f"Device discovery failed: {e}")

        try:
            casts, browser = await loop.run_in_executor(None, _sync_discover)
            self.browser = browser
        except Exception as e:
            logger.warning(f"Note during device discovery: {e}")
            casts = []
        
        devices = []
        for cast in casts:
            info: CastInfo = cast.cast_info
            name = info.friendly_name or "Unnamed Chromecast"
            self.found_devices[name] = cast
            devices.append({
                "name": name,
                "model": info.model_name,
                "host": info.host,
                "port": info.port,
                "uuid": str(info.uuid),
                "cast_object": cast
            })
        
        return devices

    def stop_discovery(self):
        """Stops the mDNS discovery gracefully."""
        if self.browser:
            try:
                self.browser.stop_discovery()
            except Exception:
                pass
            self.browser = None

    async def cast_stream(self, device_name_or_ip: str, stream_url: str, content_type: str = "video/webm") -> bool:
        """Starts screen sharing on the selected Chromecast device."""
        self._ensure_zeroconf()

        loop = asyncio.get_running_loop()

        def _sync_find_cast():
            target_cast = None
            clean_ip = device_name_or_ip.replace('.', '')
            if clean_ip.isdigit():
                logger.info(f"Connecting directly via IP: {device_name_or_ip}")
                casts, _ = pychromecast.get_chromecasts(
                    known_hosts=[device_name_or_ip],
                    timeout=3.0,
                    zeroconf_instance=self.zconf
                )
                if casts:
                    target_cast = casts[0]
            else:
                target_cast = self.found_devices.get(device_name_or_ip)
                if not target_cast:
                    for name, cast_obj in self.found_devices.items():
                        if device_name_or_ip.lower() in name.lower():
                            target_cast = cast_obj
                            break
            
            if not target_cast:
                raise CastError(f"Device '{device_name_or_ip}' not found.")
            
            target_cast.wait()
            return target_cast

        try:
            target_cast = await loop.run_in_executor(None, _sync_find_cast)
        except CastError as e:
            logger.error(str(e))
            return False

        # Stop any existing cast before starting a new one
        self.stop_cast()

        self.active_cast = target_cast
        logger.info(f"Connecting to '{target_cast.cast_info.friendly_name}' ({target_cast.cast_info.host})...")
        
        def _sync_play():
            mc = target_cast.media_controller
            logger.info(f"Sending stream (Type: {content_type}) to Shield Chromecast: {stream_url}")
            mc.play_media(stream_url, content_type=content_type, title="", stream_type="LIVE")
            mc.block_until_active(timeout=5)
            
        await loop.run_in_executor(None, _sync_play)
        
        logger.info(f"✅ Screen sharing successfully started on '{target_cast.cast_info.friendly_name}'!")
        return True

    def stop_cast(self):
        """Stops the screen cast on the Shield."""
        if self.active_cast:
            try:
                logger.info(f"Stopping cast on '{self.active_cast.cast_info.friendly_name}'...")
                self.active_cast.media_controller.stop()
                self.active_cast.quit_app()
            except Exception as e:
                logger.warning(f"Note during cast stop: {e}")
            finally:
                self.active_cast = None

    def close(self):
        """Closes all connection sockets and Zeroconf instances cleanly."""
        self.stop_cast()
        self.stop_discovery()
        if self.zconf:
            try:
                self.zconf.close()
            except Exception:
                pass
            self.zconf = None
