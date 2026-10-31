import logging
import threading
import time

from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


class WaylandScreenCastPortal:
    def __init__(self):
        self.bus: Gio.DBusConnection | None = None
        self.sender_name: str = ""
        self.session_handle: str | None = None
        self.node_id: int | None = None
        self.loop: GLib.MainLoop | None = None
        self.error: str | None = None
        self._thread: threading.Thread | None = None

    def start_portal_session(self, timeout: float = 30.0) -> int | None:
        """Starts the portal session. The user confirms the KDE dialog.

        Returns the active PipeWire Node ID."""
        logger.info("🔐 Requesting screen share via xdg-desktop-portal (Please allow in the KDE dialog)...")
        
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.sender_name = self.bus.get_unique_name()[1:].replace('.', '_')
        except Exception as e:
            logger.error(f"DBus connection to portal failed: {e}")
            return None

        self.loop = GLib.MainLoop()
        self.node_id = None
        self.error = None

        self._call_portal('CreateSession', None, 'create')

        # Run GLib Loop in a separate thread so DBus signals are received
        # while the main application continues
        ready_event = threading.Event()

        def run_loop():
            GLib.timeout_add(int(timeout * 1000), self._on_timeout)
            self.loop.run()
            ready_event.set()

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

        # Wait until Node ID received or abort/timeout
        ready_event.wait(timeout=timeout)

        if self.node_id is not None:
            logger.info(f"✅ Screen share granted! PipeWire Screen Node ID: {self.node_id}")
            return self.node_id
        else:
            logger.error(f"❌ Screen share not granted: {self.error or 'Timeout or aborted'}")
            return None

    def _on_timeout(self):
        if self.loop and self.loop.is_running():
            self.error = "Timeout: Screen share dialog was not confirmed in time."
            self.loop.quit()
        return False

    def _call_portal(self, method: str, params_variant: str | None, step: str):
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
            opts['types'] = GLib.Variant('u', 1)  # 1 = Monitor (Full screen)
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
            logger.error(f"Error during DBus call {method}: {e}")
            self.error = str(e)
            if self.loop and self.loop.is_running():
                self.loop.quit()

    def _on_request_response(self, conn, sender, path, iface, signal, params, user_data):
        code, results = params.unpack()
        step = user_data['step']

        if code != 0:
            logger.error(f"Share dialog aborted or failed at step '{step}' (Code {code})")
            self.error = f"Share rejected (Code {code})"
            if self.loop and self.loop.is_running():
                self.loop.quit()
            return

        if step == 'create':
            self.session_handle = results.get('session_handle')
            if self.session_handle:
                self._call_portal('SelectSources', self.session_handle, 'select')
            else:
                self.error = "No session handle received from portal"
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
                self.error = "No video streams returned from portal"
            
            # Do NOT call loop.quit() so the DBus session stays open during streaming!

    def close(self):
        """Closes the portal session cleanly after streaming ends."""
        if self.loop and self.loop.is_running():
            self.loop.quit()
        self.session_handle = None
        self.node_id = None
