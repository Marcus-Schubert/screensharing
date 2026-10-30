import logging
import threading
import time
from typing import Optional
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


class WaylandScreenCastPortal:
    def __init__(self):
        self.bus: Optional[Gio.DBusConnection] = None
        self.sender_name: str = ""
        self.session_handle: Optional[str] = None
        self.node_id: Optional[int] = None
        self.loop: Optional[GLib.MainLoop] = None
        self.error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def start_portal_session(self, timeout: float = 30.0) -> Optional[int]:
        """Startet die Portal-Sitzung. Der Benutzer bestätigt den KDE-Dialog.

        Gibt die aktive PipeWire Node ID zurück.
        """
        logger.info("🔐 Überfrage Bildschirmfreigabe über xdg-desktop-portal (Bitte im KDE-Dialog erlauben)...")
        
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.sender_name = self.bus.get_unique_name()[1:].replace('.', '_')
        except Exception as e:
            logger.error(f"DBus-Verbindung zum Portal fehlgeschlagen: {e}")
            return None

        self.loop = GLib.MainLoop()
        self.node_id = None
        self.error = None

        self._call_portal('CreateSession', None, 'create')

        # GLib Loop in einem separaten Thread laufen lassen, damit DBus Signals empfangen werden
        # während die Hauptanwendung weiterläuft
        ready_event = threading.Event()

        def run_loop():
            GLib.timeout_add(int(timeout * 1000), self._on_timeout)
            self.loop.run()
            ready_event.set()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

        # Warten bis Node ID empfangen wurde oder Abruch/Timeout
        ready_event.wait(timeout=timeout)

        if self.node_id is not None:
            logger.info(f"✅ Bildschirmfreigabe erteilt! PipeWire Screen Node ID: {self.node_id}")
            return self.node_id
        else:
            logger.error(f"❌ Bildschirmfreigabe nicht erteilt: {self.error or 'Timeout oder Abgebrochen'}")
            return None

    def _on_timeout(self):
        if self.loop and self.loop.is_running():
            self.error = "Timeout: Dialog zur Bildschirmfreigabe wurde nicht rechtzeitig bestätigt."
            self.loop.quit()
        return False

    def _call_portal(self, method: str, params_variant: Optional[str], step: str):
        token = f"req_{step}_{int(time.time()*1000)}"
        req_path = f"/org/freedesktop/portal/desktop/request/{self.sender_name}/{token}"

        self.bus.signal_subscribe(
            'org.freedesktop.portal.Desktop',
            'org.freedesktop.portal.Request',
            'Response',
            req_path,
            None,
            Gio.DBusSignalFlags.NONE,
            self._on_request_response,
            {'step': step}
        )

        opts = {'handle_token': GLib.Variant('s', token)}
        if step == 'create':
            opts['session_handle_token'] = GLib.Variant('s', f"sess_{int(time.time())}")
            var = GLib.Variant('(a{sv})', (opts,))
        elif step == 'select':
            opts['types'] = GLib.Variant('u', 1)  # 1 = Monitor (Gesamter Bildschirm)
            opts['multiple'] = GLib.Variant('b', False)
            var = GLib.Variant('(oa{sv})', (params_variant, opts))
        elif step == 'start':
            var = GLib.Variant('(osa{sv})', (params_variant, '', opts))
        else:
            return

        try:
            self.bus.call_sync(
                'org.freedesktop.portal.Desktop',
                '/org/freedesktop/portal/desktop',
                'org.freedesktop.portal.ScreenCast',
                method,
                var,
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None
            )
        except Exception as e:
            logger.error(f"Fehler beim DBus-Aufruf {method}: {e}")
            self.error = str(e)
            if self.loop and self.loop.is_running():
                self.loop.quit()

    def _on_request_response(self, conn, sender, path, iface, signal, params, user_data):
        code, results = params.unpack()
        step = user_data['step']

        if code != 0:
            logger.error(f"Freigabe-Dialog abgebrochen oder fehlgeschlagen in Schritt '{step}' (Code {code})")
            self.error = f"Freigabe abgelehnt (Code {code})"
            if self.loop and self.loop.is_running():
                self.loop.quit()
            return

        if step == 'create':
            self.session_handle = results.get('session_handle')
            if self.session_handle:
                self._call_portal('SelectSources', self.session_handle, 'select')
            else:
                self.error = "Kein Session Handle vom Portal erhalten"
                if self.loop and self.loop.is_running():
                    self.loop.quit()

        elif step == 'select':
            if self.session_handle:
                self._call_portal('Start', self.session_handle, 'start')

        elif step == 'start':
            streams = results.get('streams', [])
            if streams:
                self.node_id = streams[0][0]
            else:
                self.error = "Keine Video-Streams vom Portal zurückgeliefert"
            
            # NICHT loop.quit() aufrufen, damit die DBus Session während der Übertragung offen bleibt!

    def close(self):
        """Schließt die Portal-Sitzung sauber nach Beendigung des Streamings."""
        if self.loop and self.loop.is_running():
            self.loop.quit()
        self.session_handle = None
        self.node_id = None
