# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool for controlling Turing Smart Screen 8.8" V1.1 USB displays (VID 0x1CBE, PID 0x0088). Unofficial implementation that runs on-demand without background daemons.

This repository is a fork with multi-device support, developed as part of Project Shiro to drive three displays showing system metrics for a high-performance AI workstation.

## Hardware Configuration

Three Turing 8.8" Smart Screens connect via USB using revision C protocol (LcdCommRevC). Hardware reports TURZX1.0 product string. Devices enumerate sorted by serial for stable index assignment.

| INDEX | Serial | Position | Orientation | DISPLAY_REVERSE |
|-------|--------|----------|-------------|------------------|
| 0 | 09289d37d4ce4501 | Vertical (right side) | Portrait | true |
| 1 | 0f23f65104b24704 | Horizontal (top left) | Landscape | false |
| 2 | 2c17089ce4b1c700 | Horizontal (top right) | Landscape | false |

Native resolution is 480x1920 (portrait). Orientation is controlled by theme DISPLAY_ORIENTATION (portrait/landscape) and config DISPLAY_REVERSE (180-degree flip).

## Shiro Remote Access

```bash
# SSH to Shiro
ssh 192.168.128.66

# Deploy updates on Shiro
ssh 192.168.128.66 "cd ~/turing-smart-screen-cli && git pull origin main && ~/.local/bin/uv tool install --reinstall ~/turing-smart-screen-cli"
```

## Development Commands

```bash
# Install with dev dependencies
uv sync --extra dev

# Run the CLI
uv run turing-screen <command>

# Verify syntax
uv run python -m py_compile src/turingscreencli/*.py

# Run tests
uv run pytest
uv run pytest tests/test_cli.py::test_run_sync_success  # single test
uv run pytest --cov=turingscreencli  # with coverage

# Linting/formatting
uv run ruff check src tests
uv run black src tests
uv run mypy src
```

## Architecture

The codebase follows a three-layer architecture:

- **cli.py**: Argument parsing with argparse subparsers, command dispatch via `_dispatch_command()`, device selection (index or serial)
- **operations.py**: High-level device operations (send_image, send_video, upload_file, etc.). Each operation builds command packets and handles the protocol logic
- **transport.py**: Low-level USB communication using pyusb. Handles device discovery, DES encryption of command packets, and read/write operations

### USB Protocol

Commands are sent as 512-byte DES-encrypted packets. The packet structure:
- Byte 0: command ID
- Bytes 2-3: magic bytes (0x1A, 0x6D)
- Bytes 4-7: timestamp
- Bytes 8+: command-specific payload
- Bytes 510-511: trailer (0xA1, 0x1A)

Key command IDs: 10=sync, 11=restart, 14=brightness, 102=send PNG, 121=send video chunk, 125=save settings

### Device Storage Paths

- Images: `/tmp/sdcard/mmcblk0p1/img/`
- Videos: `/tmp/sdcard/mmcblk0p1/video/`

### Image Handling

Images are sent as layered PNG chunks (max 512KB each). Large images are split into vertical layers sent from bottom to top. Device expects 480x1920 resolution.

### Video Handling

MP4 files are converted to raw H.264 Annex B format using FFmpeg before streaming. Video chunks are 202KB each.

**CRITICAL: Video Encoding Requirements**

Videos MUST be encoded with these exact settings or playback will fail/artifact:

```bash
ffmpeg -i input.mp4 -vf "vflip,hflip" -c:v libx264 -profile:v baseline -r 25 -bf 0 -an output.mp4
```

- **Profile**: Must be `baseline` (NOT high). High profile causes green artifacts/corruption.
- **Frame rate**: 25fps (`-r 25`)
- **B-frames**: Disabled (`-bf 0`)
- **Rotation**: Use `vflip,hflip` for 180° rotation. Do NOT use device rotation (command 125) for video - it only works for static images.
- **Audio**: Strip audio (`-an`) - device doesn't support it

The device rotation setting (`save --rotation 2`) does NOT affect video playback, only static image display.

### Multi-Display Setup

When using multiple displays simultaneously:

1. **Initialize sequentially** with delays between each display to avoid USB "Resource busy" errors
2. **Image displays**: Use layered sending for images >512KB - the `send_image` command handles this automatically
3. **Video displays**: Initialize video last after static displays are ready
4. Each display is a separate USB device - use `-d 0`, `-d 1`, `-d 2` to target specific displays

### Display Modes

Each screen operates in one of three mutually exclusive modes:

| Mode | Config Key | Description |
|------|------------|-------------|
| Stats | TEMPLATE | Template-driven metric display |
| Video | VIDEO | Looping video from SD card storage |
| Image | IMAGE | Static image display |

Video plays from device SD card, not USB streaming (USB 2.0 bandwidth insufficient for real-time HD).

### Multi-Display Configuration Schema

```yaml
multi-display:
  - DEVICE: 0                    # by index, serial, or serial prefix
    VIDEO: snow-loop.mp4         # video mode
    REVISION: C
    DISPLAY_REVERSE: true
    BRIGHTNESS: 50
  - DEVICE: 1
    TEMPLATE: shiro-system       # stats mode
    REVISION: C
    DISPLAY_REVERSE: false
    BRIGHTNESS: 50
  - DEVICE: 2
    IMAGE: snow-horiz-01.jpg     # image mode
    REVISION: C
    DISPLAY_REVERSE: false
    BRIGHTNESS: 50
```

### Display Content (Project Shiro)

| Display | Mode | Content |
|---------|------|---------|
| 0 | Video | Snowscape loop (portrait) |
| 1 | Stats | GPU0, GPU1, CPU, Bandwidth (shiro-system template) |
| 2 | Image | Snowscape placeholder (AI metrics future) |

## Testing Approach

Tests mock USB communication via `device_factory` parameter in `cli.run()`. The `monkeypatch` fixture replaces `operations.*` functions to avoid real device access.

## Repositories

| Repository | Purpose |
|------------|----------|
| [mathoudebine/turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) | Upstream Python library |
| [phstudy/turing-smart-screen-cli](https://github.com/phstudy/turing-smart-screen-cli) | CLI feature source |
| [matthewgjohnson/turing-smart-screen-cli](https://github.com/matthewgjohnson/turing-smart-screen-cli) | Fork with multi-device support |

## Related Documents

Located in parent directory (`../`):

| Document | Content |
|----------|----------|
| Project Shiro Foundation v1-02.md | Hardware spec, fan sensor mapping, storage architecture |
| Project Shiro Turing Screens v2-04.md | Display design system, metrics, implementation phases |
| Project_Shiro_System_Template_v1-14.html | Reference mockup for shiro-system template |

## Metric Sources (Project Shiro)

**GPU metrics** (zones 1-2): `nvidia-smi` queries for temp, fan, load, power, VRAM, pstate, throttle reasons

**CPU metrics** (zone 3):
- Temperature: `k10temp` hwmon (Tctl)
- Power: RAPL delta calculation (`/sys/class/powercap/intel-rapl:0/energy_uj`)
- Fans: `nct6798` hwmon - see Foundation doc section 2.3 for sensor-to-header mapping

**Bandwidth metrics** (zone 4):
- GPU PCIe: `nvidia-smi dmon` (MB/s converted to Gbps)
- SSD: `/proc/diskstats` sector deltas
- Network: `/proc/net/dev` byte deltas
- RAM/SSD used: `/proc/meminfo` and `df`
