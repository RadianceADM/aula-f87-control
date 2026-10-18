"""Raw HID access with two interchangeable backends.

* ``HidrawDevice``: Linux hidraw through ioctl. Built in, no extra packages.
* ``HidapiDevice``: the ``hidapi`` Python package, for Windows and macOS.
  You can also force it on Linux with ``AULA_F87_HID=hidapi``.

Both offer the same small interface used by ``device.py``:
``set_feature``, ``get_feature``, ``write``, ``read``, ``alive`` and ``close``.
Failed transfers raise ``OSError``.
"""

import errno
import os
import sys
import time
from pathlib import Path


class HidError(Exception):
    """Problem finding or opening a device (shown to the user as-is)."""


def backend_name():
    forced = os.environ.get("AULA_F87_HID", "").lower()
    if forced in ("hidraw", "hidapi"):
        return forced
    return "hidraw" if sys.platform.startswith("linux") else "hidapi"


# --------------------------------------------------------------------------- Linux hidraw

def _ioc_rw(nr, size):
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


class HidrawDevice:
    def __init__(self, path):
        import fcntl  # Linux only
        self._fcntl = fcntl
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise HidError(
                f"Permission denied on {path}. Install the udev rule (see README), "
                "then unplug and replug the keyboard.") from None

    @property
    def alive(self):
        return os.path.exists(self.path)

    def close(self):
        os.close(self.fd)

    def set_feature(self, data):
        self._fcntl.ioctl(self.fd, _ioc_rw(0x06, len(data)), bytes(data))  # HIDIOCSFEATURE

    def get_feature(self, report_id, size):
        buf = bytearray(size)
        buf[0] = report_id
        n = self._fcntl.ioctl(self.fd, _ioc_rw(0x07, size), buf, True)  # HIDIOCGFEATURE
        return bytes(buf[:n])

    def write(self, data):
        os.write(self.fd, bytes(data))

    def read(self, timeout):
        import select
        ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not ready:
            return None
        try:
            return os.read(self.fd, 64)
        except BlockingIOError:
            return None


def _hidraw_candidates(usb_id, report_marker):
    """Linux: hidraw nodes of this USB device whose report descriptor declares
    the report we need (e.g. ``85 06`` = report ID 6)."""
    root = Path("/sys/class/hidraw")
    if not root.is_dir():
        return []
    found = []
    for node in sorted(root.iterdir(), key=lambda p: p.name):
        try:
            uevent = (node / "device" / "uevent").read_text()
            descriptor = (node / "device" / "report_descriptor").read_bytes()
        except OSError:
            continue
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        try:
            _bus, vid, pid = (int(part, 16) for part in fields.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if (vid, pid) == usb_id and bytes([0x85, report_marker]) in descriptor:
            path = f"/dev/{node.name}"
            found.append((path, lambda p=path: HidrawDevice(p)))
    return found


# --------------------------------------------------------------------------- hidapi

def _hidapi_module():
    try:
        if backend_name() == "hidapi" and sys.platform.startswith("linux"):
            import hidraw as hid  # cython-hidapi's hidraw build: keeps the kernel driver attached
        else:
            import hid
        return hid
    except ImportError:
        raise HidError("The 'hidapi' package is missing. Install it with: pip install hidapi") from None


class HidapiDevice:
    def __init__(self, info):
        self._hid = _hidapi_module()
        self.info = info
        self.path = info["path"]
        self._dev = self._hid.device()
        try:
            self._dev.open_path(self.path)
        except (OSError, IOError) as exc:
            raise HidError(f"Couldn't open the keyboard ({exc}). Close AULA's own software "
                           "if it is running, then try again.") from None
        self._dev.set_nonblocking(True)

    @property
    def alive(self):
        try:
            return any(d["path"] == self.path for d in
                       self._hid.enumerate(self.info["vendor_id"], self.info["product_id"]))
        except Exception:
            return False

    def close(self):
        self._dev.close()

    @staticmethod
    def _fail(what, result=None):
        # hidapi gives no errno; EPIPE makes callers treat it like a stalled transfer.
        raise OSError(errno.EPIPE, f"{what} failed" + (f" ({result})" if result is not None else ""))

    def set_feature(self, data):
        try:
            result = self._dev.send_feature_report(bytes(data))
        except (OSError, IOError, ValueError) as exc:
            self._fail("send_feature_report", exc)
        if result is not None and result < 0:
            self._fail("send_feature_report", result)

    def get_feature(self, report_id, size):
        try:
            data = self._dev.get_feature_report(report_id, size)
        except (OSError, IOError, ValueError) as exc:
            self._fail("get_feature_report", exc)
        if not data:
            self._fail("get_feature_report")
        data = bytes(data)
        # Some platforms leave out the report ID byte; keep the layout identical to hidraw.
        if data[0] != report_id:
            data = bytes([report_id]) + data
        return data

    def write(self, data):
        try:
            result = self._dev.write(bytes(data))
        except (OSError, IOError, ValueError) as exc:
            self._fail("write", exc)
        if result is not None and result < 0:
            self._fail("write", result)

    def read(self, timeout):
        # hidapi treats timeout_ms=0 as "wait forever", so a zero timeout uses a
        # plain read on the non-blocking handle instead.
        ms = int(max(0.0, timeout) * 1000)
        try:
            data = self._dev.read(64, ms) if ms > 0 else self._dev.read(64)
        except (OSError, IOError, ValueError):
            return None
        return bytes(data) if data else None


def _hidapi_candidates(usb_id, usage_pages):
    """Vendor-defined collections of this device, preferred usage pages first."""
    hid = _hidapi_module()
    infos = [d for d in hid.enumerate(*usb_id) if 0xFF00 <= d["usage_page"] <= 0xFFFF]
    infos.sort(key=lambda d: usage_pages.index(d["usage_page"])
               if d["usage_page"] in usage_pages else len(usage_pages))
    seen, found = set(), []
    for info in infos:
        key = (info["path"], info["usage_page"])
        if key not in seen:
            seen.add(key)
            found.append((info["path"], lambda i=info: HidapiDevice(i)))
    return found


def candidates(usb_id, report_marker, usage_pages):
    """List of (label, opener) for every interface that may carry our reports.

    report_marker: report ID that must be declared (Linux hidraw backend).
    usage_pages:   vendor usage pages to try first (hidapi backend, where each
                   top-level collection is a separate device on Windows/macOS).
    """
    if backend_name() == "hidraw":
        return _hidraw_candidates(usb_id, report_marker)
    return _hidapi_candidates(usb_id, usage_pages)
