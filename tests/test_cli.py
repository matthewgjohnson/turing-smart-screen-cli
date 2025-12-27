import turingscreencli.cli as cli


def _noop(*_args, **_kwargs):
    return None


class MockDevice:
    """Mock USB device with required attributes."""
    serial_number = "test123"
    bus = 1
    address = 1


def test_create_parser_includes_commands():
    parser = cli.create_parser()

    args = parser.parse_args(["sync"])
    assert args.command == "sync"

    args = parser.parse_args(["send-image", "--path", "img.png"])
    assert args.command == "send-image"
    assert args.path == "img.png"


def test_run_sync_success(monkeypatch):
    monkeypatch.setattr(cli, "configure_logging", _noop)

    captured = {}

    def fake_send_sync(dev):
        captured["dev"] = dev
        return b"ok"

    monkeypatch.setattr(cli.operations, "send_sync_command", fake_send_sync)

    rc = cli.run(["sync"], device_factory=lambda _: MockDevice())

    assert rc == 0
    assert "dev" in captured


def test_run_device_missing(monkeypatch):
    monkeypatch.setattr(cli, "configure_logging", _noop)

    def factory(_):
        raise ValueError("missing device")

    rc = cli.run(["sync"], device_factory=factory)
    assert rc == 1


def test_run_brightness_success(monkeypatch):
    monkeypatch.setattr(cli, "configure_logging", _noop)
    monkeypatch.setattr(cli.operations, "delay_sync", lambda dev: None)
    monkeypatch.setattr(cli.operations, "send_brightness_command", lambda dev, val: b"ok")

    rc = cli.run(["brightness", "--value", "50"], device_factory=lambda _: MockDevice())

    assert rc == 0


def test_run_send_image_failure(monkeypatch):
    monkeypatch.setattr(cli, "configure_logging", _noop)
    monkeypatch.setattr(cli.operations, "delay_sync", lambda dev: None)
    monkeypatch.setattr(cli.operations, "send_image", lambda dev, path: False)

    rc = cli.run(["send-image", "--path", "missing.png"], device_factory=lambda _: MockDevice())

    assert rc == 1
