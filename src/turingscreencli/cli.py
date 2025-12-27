import argparse
import logging
import sys
from importlib.metadata import version, PackageNotFoundError

import usb.core

from . import operations, transport

try:
    __version__ = version("turingscreencli")
except PackageNotFoundError:
    __version__ = "0.0.0"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"
logger = logging.getLogger(__name__)


def configure_logging(verbosity: int) -> None:
    """Configure root logging based on requested verbosity."""
    root = logging.getLogger()
    level = _verbosity_to_level(verbosity)

    if root.handlers:
        root.setLevel(level)
        for handler in root.handlers:
            handler.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.captureWarnings(True)


def _verbosity_to_level(verbosity: int) -> int:
    if verbosity >= 2:
        return logging.DEBUG
    if verbosity == 1:
        return logging.INFO
    return logging.WARNING


def create_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Turing Smart Screen CLI Tool - Control your Turing Smart Screen device via USB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  turing-screen send-image --path sample.png\n"
            "  turing-screen send-video --path video.mp4 --loop\n"
            "  turing-screen brightness --value 80\n"
            "  turing-screen save --brightness 100 --rotation 0\n"
            "\n"
            "Video requirements:\n"
            "  Resolution: 480x1920 (portrait)\n"
            "  Codec: H.264 baseline profile, 25fps, no B-frames\n"
            "  Convert: ffmpeg -i in.mp4 -vf transpose=1 -c:v libx264 \\\n"
            "           -profile:v baseline -r 25 -bf 0 -an out.mp4"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-vv for debug logging).",
    )
    parser.add_argument(
        "-d",
        "--device",
        type=str,
        default=None,
        help="Device selector: index (0, 1, 2), full serial, or partial serial prefix.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    subparsers.required = True

    # List devices command (no device connection needed)
    subparsers.add_parser("list-devices", help="List all connected Turing Smart Screen devices")

    # Simple commands with no arguments
    subparsers.add_parser("sync", help="Send a sync command to the device")
    subparsers.add_parser("restart", help="Restart the device")
    subparsers.add_parser("refresh-storage", help="Show SD storage information")
    subparsers.add_parser("clear-image", help="Clear the current image")
    subparsers.add_parser("stop-play", help="Stop active playback")

    # Commands with arguments
    brightness_parser = subparsers.add_parser("brightness", help="Set screen brightness")
    brightness_parser.add_argument(
        "--value",
        type=int,
        required=True,
        choices=range(0, 103),
        metavar="[0-102]",
        help="Brightness value (0–102)",
    )

    save_parser = subparsers.add_parser(
        "save",
        help="Persist device settings (rotation requires restart to take effect)",
    )
    save_parser.add_argument(
        "--brightness",
        type=int,
        default=102,
        choices=range(0, 103),
        metavar="[0-102]",
        help="Brightness value (0-102, default: 102)",
    )
    save_parser.add_argument(
        "--startup",
        type=int,
        default=0,
        choices=[0, 1, 2],
        metavar="[0|1|2]",
        help="0 = default, 1 = play image, 2 = play video (default: 0)",
    )
    save_parser.add_argument(
        "--reserved",
        type=int,
        default=0,
        choices=[0],
        metavar="[0]",
        help="Reserved value (default: 0)",
    )
    save_parser.add_argument(
        "--rotation",
        type=int,
        default=0,
        choices=[0, 2],
        metavar="[0|2]",
        help="0 = 0°, 2 = 180° (default: 0). Requires restart to take effect.",
    )
    save_parser.add_argument(
        "--sleep",
        type=int,
        default=0,
        choices=range(0, 256),
        metavar="[0-255]",
        help="Sleep timeout (default: 0)",
    )
    save_parser.add_argument(
        "--offline",
        type=int,
        default=0,
        choices=[0, 1],
        metavar="[0|1]",
        help="0 = Disabled, 1 = Enabled (default: 0)",
    )

    list_parser = subparsers.add_parser("list-storage", help="List files stored on the device")
    list_parser.add_argument(
        "--type",
        type=str,
        choices=["image", "video"],
        required=True,
        help="Type of files to list: image or video",
    )

    image_parser = subparsers.add_parser("send-image", help="Display an image on the screen")
    image_parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to PNG image (ideally 480x1920)",
    )

    parser_video = subparsers.add_parser("send-video", help="Stream video to the screen")
    parser_video.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to MP4 video (480x1920, h264 baseline, 25fps)",
    )
    parser_video.add_argument(
        "--loop",
        action="store_true",
        help="Loop the video playback until interrupted",
    )

    # NOTE: The following commands are disabled due to reliability issues on tested hardware.
    # The underlying code is preserved in operations.py for future investigation.
    # - upload: USB timeouts during file write operations
    # - delete: Depends on working storage operations
    # - play-select: Files upload but playback doesn't start

    return parser


def _parse_device_selector(selector_str):
    """Parse device selector string into int index or string serial."""
    if selector_str is None:
        return None
    # Try to parse as integer index
    try:
        return int(selector_str)
    except ValueError:
        # Return as string for serial matching
        return selector_str


def _list_devices() -> bool:
    """List all connected Turing Smart Screen devices."""
    devices = transport.find_all_usb_devices()

    if not devices:
        print("No Turing Smart Screen devices found.")
        return True

    # Print header
    print(f"{'Index':<6} {'Serial':<18} {'Bus:Addr':<10} {'Product':<10} {'Firmware':<8}")
    print("-" * 60)

    for idx, dev in enumerate(devices):
        serial = transport.get_device_serial(dev)
        bus_addr = f"{dev.bus:03d}:{dev.address:03d}"
        try:
            product = dev.product or "Unknown"
        except (usb.core.USBError, ValueError):
            product = "Unknown"
        # bcdDevice is BCD-encoded version (e.g., 0x0100 = 1.00)
        try:
            bcd = dev.bcdDevice
            firmware = f"{(bcd >> 8) & 0xFF}.{bcd & 0xFF:02d}"
        except (usb.core.USBError, ValueError, AttributeError):
            firmware = "Unknown"
        print(f"{idx:<6} {serial:<18} {bus_addr:<10} {product:<10} {firmware:<8}")

    return True


def _get_device_info(dev) -> str:
    """Get a short description of the device for logging."""
    serial = transport.get_device_serial(dev)
    return f"device serial={serial} (bus={dev.bus:03d}, addr={dev.address:03d})"


def run(argv=None, *, device_factory=transport.find_usb_device) -> int:
    """Run the CLI with the provided arguments."""
    parser = create_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    # Handle list-devices separately (no device connection needed)
    if args.command == "list-devices":
        try:
            _list_devices()
            return 0
        except Exception as exc:
            logger.error("Error listing devices: %s", exc)
            return 1

    # Parse device selector
    device_selector = _parse_device_selector(args.device)

    try:
        dev = device_factory(device_selector)
    except ValueError as exc:
        logger.error("Error: %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 0
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        return 1

    # Log which device was selected (always show this for multi-device setups)
    device_info = _get_device_info(dev)
    logger.info("Using %s", device_info)

    try:
        success = _dispatch_command(dev, args)
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 0
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        return 1

    return 0 if success else 1


def _dispatch_command(dev, args) -> bool:
    command = args.command

    if command == "sync":
        return operations.send_sync_command(dev) is not None
    if command == "restart":
        operations.delay_sync(dev)
        return operations.send_restart_device_command(dev) is not None
    if command == "refresh-storage":
        operations.delay_sync(dev)
        operations.send_refresh_storage_command(dev)
        return True
    if command == "brightness":
        operations.delay_sync(dev)
        return operations.send_brightness_command(dev, args.value) is not None
    if command == "save":
        operations.delay_sync(dev)
        response = operations.send_save_settings_command(
            dev,
            brightness=args.brightness,
            startup=args.startup,
            reserved=args.reserved,
            rotation=args.rotation,
            sleep=args.sleep,
            offline=args.offline,
        )
        return response is not None
    if command == "list-storage":
        operations.delay_sync(dev)
        path = "/tmp/sdcard/mmcblk0p1/img/" if args.type == "image" else "/tmp/sdcard/mmcblk0p1/video/"
        operations.send_list_storage_command(dev, path)
        return True
    if command == "clear-image":
        operations.delay_sync(dev)
        return operations.clear_image(dev) is not None
    if command == "send-image":
        operations.delay_sync(dev)
        return operations.send_image(dev, args.path)
    if command == "send-video":
        operations.delay_sync(dev)
        return operations.send_video(dev, args.path, loop=args.loop)
    if command == "stop-play":
        operations.delay_sync(dev)
        return operations.stop_play(dev)

    raise ValueError(f"Unsupported command: {command}")


def main(argv=None):
    """CLI entry point."""
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
