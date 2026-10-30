import asyncio
import logging
import threading

import pychromecast
from pychromecast.models import CastInfo
import zeroconf

from exceptions import CastError

logger = logging.getLogger(__name__)

# Zeroconf-Hintergrundthread Ausnahmen beim Beenden abfangen
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
        """Sucht im lokalen Netzwerk nach Chromecast-Geräten (z.B. Nvidia Shield Pro)."""
        logger.info(f"Suche nach Chromecast-Geräten im Netzwerk ({timeout}s)...")
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
                raise CastError(f"Gerätesuche fehlgeschlagen: {e}")

        try:
            casts, browser = await loop.run_in_executor(None, _sync_discover)
            self.browser = browser
        except Exception as e:
            logger.warning(f"Hinweis bei der Gerätesuche: {e}")
            casts = []
        
        devices = []
        for cast in casts:
            info: CastInfo = cast.cast_info
            name = info.friendly_name or "Unbenannter Chromecast"
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
        """Stoppt die mDNS-Suche geordnet."""
        if self.browser:
            try:
                self.browser.stop_discovery()
            except Exception:
                pass
            self.browser = None

    async def cast_stream(self, device_name_or_ip: str, stream_url: str, content_type: str = "video/webm") -> bool:
        """Startet das Screen-Sharing auf dem ausgewählten Chromecast-Gerät."""
        self._ensure_zeroconf()

        loop = asyncio.get_running_loop()

        def _sync_find_cast():
            target_cast = None
            clean_ip = device_name_or_ip.replace('.', '')
            if clean_ip.isdigit():
                logger.info(f"Verbinde direkt über IP: {device_name_or_ip}")
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
                raise CastError(f"Gerät '{device_name_or_ip}' nicht gefunden.")
            
            target_cast.wait()
            return target_cast

        try:
            target_cast = await loop.run_in_executor(None, _sync_find_cast)
        except CastError as e:
            logger.error(str(e))
            return False

        self.active_cast = target_cast
        logger.info(f"Verbinde mit '{target_cast.cast_info.friendly_name}' ({target_cast.cast_info.host})...")
        
        def _sync_play():
            mc = target_cast.media_controller
            logger.info(f"Sende Stream (Type: {content_type}) an Shield Chromecast: {stream_url}")
            mc.play_media(stream_url, content_type=content_type, title="", stream_type="LIVE")
            mc.block_until_active(timeout=5)
            
        await loop.run_in_executor(None, _sync_play)
        
        logger.info(f"✅ Screen Sharing erfolgreich gestartet auf '{target_cast.cast_info.friendly_name}'!")
        return True

    def stop_cast(self):
        """Stoppt die Bildschirmübertragung auf der Shield."""
        if self.active_cast:
            try:
                logger.info(f"Stoppe Übertragung auf '{self.active_cast.cast_info.friendly_name}'...")
                self.active_cast.media_controller.stop()
                self.active_cast.quit_app()
            except Exception as e:
                logger.warning(f"Hinweis beim Stoppen des Castings: {e}")
            finally:
                self.active_cast = None

    def close(self):
        """Schließt alle Verbindungssockets und Zeroconf-Instanzen sauber."""
        self.stop_cast()
        self.stop_discovery()
        if self.zconf:
            try:
                self.zconf.close()
            except Exception:
                pass
            self.zconf = None
