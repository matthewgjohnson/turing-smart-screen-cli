"""Low-level USB transport helpers for the Turing Smart Screen."""

from __future__ import annotations

import logging
import platform
import struct
import time
from functools import partial

import usb.core
import usb.util
from Crypto.Cipher import DES

logger = logging.getLogger(__name__)

VENDOR_ID = 0x1CBE
PRODUCT_ID = 0x0088
_DES_KEY = b"slv3tuzx"


def _endpoint_matches_direction(endpoint, *, direction):
    return usb.util.endpoint_direction(endpoint.bEndpointAddress) == direction


def build_command_packet_header(command_id: int) -> bytearray:
    """Build a command packet header for the provided command id."""
    packet = bytearray(500)
    packet[0] = command_id
    packet[2] = 0x1A
    packet[3] = 0x6D
    timestamp = int((time.time() - time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))) * 1000)
    packet[4:8] = struct.pack("<I", timestamp)
    return packet


def encrypt_with_des(key: bytes, data: bytes) -> bytes:
    cipher = DES.new(key, DES.MODE_CBC, key)
    padded_len = (len(data) + 7) // 8 * 8
    padded_data = data.ljust(padded_len, b"\x00")
    return cipher.encrypt(padded_data)


def encrypt_command_packet(data: bytearray) -> bytearray:
    encrypted = encrypt_with_des(_DES_KEY, data)
    final_packet = bytearray(512)
    final_packet[: len(encrypted)] = encrypted
    final_packet[510] = 161
    final_packet[511] = 26
    return final_packet


def _configure_device(dev):
    """Configure a USB device for communication."""
    try:
        dev.set_configuration()
    except usb.core.USBError as exc:
        logger.warning("set_configuration() failed: %s", exc)

    if platform.system() == "Linux":
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
        except usb.core.USBError as exc:
            logger.warning("detach_kernel_driver failed: %s", exc)

    return dev


def get_device_serial(dev) -> str:
    """Get the serial number for a device, or fallback to bus:address."""
    try:
        serial = dev.serial_number
        if serial:
            return serial
    except (usb.core.USBError, ValueError):
        pass
    return f"bus{dev.bus:03d}:{dev.address:03d}"


def find_all_usb_devices():
    """Find all connected Turing Smart Screen devices, sorted by serial number."""
    devices = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID, find_all=True)
    if devices is None:
        return []
    device_list = list(devices)
    # Sort by serial number for stable ordering
    device_list.sort(key=get_device_serial)
    return device_list


def find_usb_device(device_selector=None):
    """Find a USB device, optionally by index or serial number.

    Args:
        device_selector: None for first device, int for index, str for serial match

    Returns:
        Configured USB device

    Raises:
        ValueError: If no device found or selector doesn't match
    """
    devices = find_all_usb_devices()

    if not devices:
        raise ValueError("No Turing Smart Screen devices found")

    if device_selector is None:
        # Default to first device
        return _configure_device(devices[0])

    if isinstance(device_selector, int):
        # Select by index
        if device_selector < 0 or device_selector >= len(devices):
            raise ValueError(
                f"Device index {device_selector} out of range (0-{len(devices) - 1})"
            )
        return _configure_device(devices[device_selector])

    # Select by serial number (full or partial match)
    serial_str = str(device_selector)
    matches = []
    for dev in devices:
        dev_serial = get_device_serial(dev)
        if dev_serial == serial_str:
            # Exact match
            return _configure_device(dev)
        if dev_serial.startswith(serial_str):
            matches.append(dev)

    if len(matches) == 1:
        return _configure_device(matches[0])
    if len(matches) > 1:
        serials = [get_device_serial(d) for d in matches]
        raise ValueError(
            f"Ambiguous serial prefix '{serial_str}' matches: {', '.join(serials)}"
        )

    raise ValueError(f"No device found matching '{serial_str}'")


def read_flush(ep_in, max_attempts: int = 5) -> None:
    for _ in range(max_attempts):
        try:
            ep_in.read(512, timeout=100)
        except usb.core.USBError as exc:
            if exc.errno == 110 or exc.args[0] == "Operation timed out":
                break
            break


def write_to_device(dev, data, timeout: int = 2000):
    cfg = dev.get_active_configuration()
    intf = usb.util.find_descriptor(cfg, bInterfaceNumber=0)
    if intf is None:
        raise RuntimeError("USB interface 0 not found")

    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=partial(
            _endpoint_matches_direction,
            direction=usb.util.ENDPOINT_OUT,
        ),
    )
    ep_in = usb.util.find_descriptor(
        intf,
        custom_match=partial(
            _endpoint_matches_direction,
            direction=usb.util.ENDPOINT_IN,
        ),
    )
    if ep_out is None or ep_in is None:
        raise RuntimeError("Unable to locate USB endpoints")

    try:
        ep_out.write(data, timeout)
    except usb.core.USBError as exc:
        logger.error("USB write error: %s", exc)
        return None

    try:
        response = ep_in.read(512, timeout)
        read_flush(ep_in)
        return bytes(response)
    except usb.core.USBError as exc:
        logger.error("USB read error: %s", exc)
        return None
