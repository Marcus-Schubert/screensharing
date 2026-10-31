#!/usr/bin/env python3
import argparse
import asyncio
import logging
import sys
from capture_server import StreamCaptureServer
from cast_manager import ChromecastManager
from wayland_screencast import WaylandScreenCastPortal

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ScreenShare")


def print_banner():
    banner = """
==========================================================
 🖥️  Asahi Linux Screen Sharing -> Nvidia Shield Pro (Chromecast)
==========================================================
"""
    print(banner)


async def main():
    print_banner()

    parser = argparse.ArgumentParser(description="Asahi Linux Screen Share to Chromecast / Nvidia Shield Pro")
    parser.add_argument("-d", "--device", type=str, help="Name of target Chromecast device (e.g. 'SHIELD')")
    parser.add_argument("--ip", type=str, help="Direct IP address of Nvidia Shield Pro (e.g. 192.168.178.73)")
    parser.add_argument("-p", "--port", type=int, default=8080, help="Port for the local HTTP streamer (default: 8080)")
    parser.add_argument("-m", "--mode", choices=["mp4", "webm"], default="mp4", help="Streaming mode: 'mp4' (Fragmented MP4, Ultra-Low Latency, default) or 'webm' (Progressive WebM)")
    parser.add_argument("--res", choices=["1080p", "720p", "native"], default="1080p", help="Target resolution (default: 1080p)")
    parser.add_argument("--bitrate", type=int, default=8, help="Bitrate in Mbps (default: 8 Mbps for crystal-clear image)")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second (default: 30 FPS)")
    parser.add_argument("-l", "--list", action="store_true", help="List discovered Chromecast devices and exit")
    args = parser.parse_args()

    cast_mgr = ChromecastManager()
    portal = WaylandScreenCastPortal()
    server = None

    try:
        # 1. Request Wayland screen share via KDE dialog
        node_id = portal.start_portal_session(timeout=30.0)
        if not node_id:
            logger.error("❌ Screen share aborted or failed.")
            sys.exit(1)

        known_hosts = [args.ip] if args.ip else None
        logger.info("Searching for available Chromecast devices on network...")
        devices = await cast_mgr.discover_devices(known_hosts=known_hosts, timeout=3.5)

        if args.list:
            if not devices:
                logger.error("❌ No Chromecast devices found on local network.")
            else:
                print("\n🔍 Found Chromecast devices:")
                for idx, dev in enumerate(devices, 1):
                    print(f"  [{idx}] {dev['name']} ({dev['model']}) @ {dev['host']}:{dev['port']}")
            sys.exit(0 if devices else 1)

        if not devices:
            if args.ip:
                logger.info(f"Using specified IP address directly: {args.ip}")
                target_identifier = args.ip
            else:
                logger.error("❌ No Chromecast devices found automatically via mDNS.")
                logger.info("Tip: You can specify your Shield Pro IP directly, e.g.:")
                logger.info("      python3 main.py --ip 192.168.178.73")
                sys.exit(1)
        else:
            if args.device:
                target_identifier = args.device
            elif args.ip:
                target_identifier = args.ip
            elif len(devices) == 1:
                target_identifier = devices[0]['name']
                logger.info(f"Automatically selected: {devices[0]['name']} ({devices[0]['host']})")
            else:
                print("\nPlease select the target device:")
                for idx, dev in enumerate(devices, 1):
                    print(f"  [{idx}] {dev['name']} ({dev['model']}) @ {dev['host']}")
                try:
                    choice = input("\nNummer eingeben [1]: ").strip()
                    idx_choice = int(choice) - 1 if choice else 0
                    target_identifier = devices[idx_choice]['name']
                except (ValueError, IndexError):
                    logger.error("Invalid selection.")
                    sys.exit(1)

        # 2. Start Stream Server with optimized resolution and bitrate
        server = StreamCaptureServer(
            node_id=node_id,
            port=args.port,
            resolution=args.res,
            bitrate_mbps=args.bitrate,
            fps=args.fps,
            mode=args.mode
        )
        await server.start()
        stream_url = server.get_stream_url()
        content_type = server.get_content_type()
        mode_label = "Fragmented MP4 (Ultra-Low Latency)" if args.mode == "mp4" else "WebM Progressive"
        logger.info(f"📺 Live stream ready ({mode_label}, {args.res} @ {args.bitrate} Mbps, {args.fps} FPS): {stream_url}")

        # 3. Send stream to Chromecast
        success = await cast_mgr.cast_stream(target_identifier, stream_url, content_type=content_type)

        if not success:
            logger.error("❌ Screen sharing could not be started.")
            sys.exit(1)

        print("\n" + "="*60)
        print(f" 🎉 SCREEN SHARING AKTIV auf '{target_identifier}'")
        print(f" ⚙️  Modus: {mode_label}")
        print(f" ⚙️  Einstellungen: {args.res} | {args.bitrate} Mbps | {args.fps} FPS")
        print(f" 🔗 Live Stream-URL: {stream_url}")
        print(f" 📄 Content-Type: {content_type}")
        print(" ⏹️  Drücke STRG+C zum Beenden")
        print("="*60 + "\n")

        while True:
            await asyncio.sleep(1)

    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("\nStopping screen sharing...")
        cast_mgr.close()
        portal.close()
        if server:
            await server.stop()
        print("Done. Goodbye! 👋")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
