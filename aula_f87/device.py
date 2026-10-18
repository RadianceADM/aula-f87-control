"""Talk to the AULA F87 / F87 Pro over USB HID (no vendor software, no driver).

Raw HID access comes from ``hidio``: Linux hidraw, or hidapi on Windows/macOS.
Two transports carry the same three data blocks:

* USB cable (258a:010c): 520-byte HID feature reports, report ID 0x06.
  Header ``06 cmd 00 00 01 00 len_lo len_hi``; a read is ``cmd | 0x80``.
* 2.4G receiver (3554:fa09): 20-byte output reports, report ID 0x13,
  ``13 cmd sub seq len data[14] checksum``. The keyboard echoes every frame.

Data blocks:

* config  (128 bytes): current effect, per-effect brightness/speed/colour
  slot, side light.
* palette (512 bytes): seven RGB colour slots per effect, 21 bytes per effect.
* keys    (378 bytes): per-key colours as three 126-byte planes (R, G, B).
"""

import errno
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import hidio
from .effects import PER_KEY, effect_info

WIRED_ID = (0x258A, 0x010C)
DONGLE_ID = (0x3554, 0xFA09)

CFG_LEN = 128
PAL_LEN = 512
PLANE = 126
KEYS_LEN = 3 * PLANE

CFG_CUSTOM = 9       # 1 = show the per-key map (with effect PER_KEY)
CFG_EFFECT = 10
CFG_COLOR_MODE = 12  # 1 = use palette / rainbow, 3 = factory colours
CFG_SIDE = 18
CFG_SLEEP = 24       # idle time before the keyboard sleeps, in 30 s steps; 0 = never
COLORFUL = 7         # colour-slot value meaning "rainbow"

MODELS = {0x0B: "F87 Pro", 0x66: "F87 TK"}

_STD_COLORS = bytes.fromhex("ff0000" "00ff00" "0000ff" "ffff00" "ff00ff" "00ffff" "ffffff")


def param_offset(effect):
    """Config offset of an effect's [brightness, speed<<4 | colour slot] pair."""
    return 56 + 2 * effect


def slot_offset(effect, slot=0):
    return 21 * effect + 3 * slot


def _default_palette():
    pal = bytearray(PAL_LEN)
    for effect in range(1, 14):
        pal[slot_offset(effect):slot_offset(effect) + 21] = _STD_COLORS
    pal[506:508] = b"\x5a\xa5"
    return pal


class DeviceError(Exception):
    pass


# --------------------------------------------------------------------------- transports

_TRANSIENT = {errno.EPROTO, errno.EPIPE, errno.ETIMEDOUT, errno.EAGAIN}


class WiredLink:
    label = "USB cable"
    REPORT_SIZE = 520

    def __init__(self, dev):
        self.dev = dev

    def close(self):
        self.dev.close()

    def _set(self, data):
        buf = bytearray(self.REPORT_SIZE)
        buf[:len(data)] = data
        self.dev.set_feature(buf)
        time.sleep(0.01)

    def _get(self):
        return self.dev.get_feature(0x06, self.REPORT_SIZE)

    @staticmethod
    def _header(cmd, length):
        return bytes([0x06, cmd, 0, 0, 1, 0, length & 0xFF, length >> 8])

    @staticmethod
    def _retry(transfer, attempts=6):
        # The keyboard stalls requests (EPROTO/EPIPE) for a moment while it
        # stores a previous write in flash; retrying after a short pause works.
        for attempt in range(attempts):
            try:
                return transfer()
            except OSError as exc:
                if exc.errno not in _TRANSIENT or attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _request(self, data, attempts=6):
        def transfer():
            self._set(data)
            return self._get()
        return self._retry(transfer, attempts)

    def _read(self, cmd, length):
        resp = self._request(self._header(cmd | 0x80, length))
        if len(resp) < 8 + length or resp[1] != cmd | 0x80:
            raise DeviceError("The keyboard sent an unexpected reply over USB. Is another program "
                              "(or this app's music sync) using it right now?")
        return bytearray(resp[8:8 + length])

    def _write(self, cmd, body):
        self._retry(lambda: self._set(self._header(cmd, len(body)) + bytes(body)))

    def probe(self):
        # Few attempts: on Windows the wrong HID collections are tried too, and
        # they fail every time.
        resp = self._request(bytes([0x06, 0x82, 0x01, 0x00, 0x01, 0x00, 0x06]), attempts=2)
        if len(resp) < 14 or resp[1] != 0x82:
            raise DeviceError("The keyboard did not answer over USB. Is another program "
                              "(or this app's music sync) using it right now?")
        return MODELS.get(resp[13], "F87")

    can_read_blocks = True

    def read_config(self):
        return self._read(0x04, CFG_LEN)

    def read_palette(self):
        return self._read(0x0A, PAL_LEN)

    def read_keys(self):
        return self._read(0x06, KEYS_LEN)

    def write_lighting(self, cfg, pal):
        self._write(0x0A, pal)
        self._write(0x04, cfg)

    def write_keys(self, cfg, keys):
        self._write(0x06, keys)
        self._write(0x04, cfg)

    def write_config(self, cfg):
        self._write(0x04, cfg)

    def read_battery(self):
        return None  # the wired interface has no battery report; the cable charges it

    # Live frames (cmd 0x08) are shown but not stored; the keyboard goes back
    # to its saved lighting about a second after they stop.
    LIVE_FPS = 30
    LIVE_FEW_COLORS = False

    def send_live(self, colors):
        buf = bytearray(self.REPORT_SIZE)
        buf[0:8] = bytes([0x06, 0x08, 0, 0, 1, 0, 0x7A, 0x01])
        for led, (r, g, b) in enumerate(colors[:PLANE]):
            buf[8 + 3 * led:11 + 3 * led] = bytes((r, g, b))
        try:
            self.dev.set_feature(buf)
        except OSError as exc:
            if exc.errno not in _TRANSIENT:
                raise  # a stalled frame is simply dropped; the next one follows shortly


class DongleLink:
    label = "2.4G receiver"
    can_read_blocks = False  # only the config block has a known read command

    def __init__(self, dev):
        self.dev = dev

    def close(self):
        self.dev.close()

    @staticmethod
    def _frame(cmd, sub, seq, payload=b""):
        f = bytearray(20)
        f[0:4] = bytes([0x13, cmd, sub, seq])
        f[4:4 + len(payload)] = payload
        f[19] = sum(f[:19]) & 0xFF
        return bytes(f)

    def _frames(self, cmd, sub, body):
        return [self._frame(cmd, sub, seq, bytes([len(body[i:i + 14])]) + bytes(body[i:i + 14]))
                for seq, i in enumerate(range(0, len(body), 14))]

    def _recv(self, timeout):
        return self.dev.read(timeout)

    def _drain(self):
        while self._recv(0.0):
            pass

    def _send_all(self, frames):
        self._drain()
        echoed = 0
        for frame in frames:
            self.dev.write(frame)
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline:
                reply = self._recv(deadline - time.monotonic())
                if reply and reply[1:4] == frame[1:4]:
                    echoed += 1
                    break
        if not echoed:
            raise DeviceError("The keyboard stopped answering over 2.4G. Press a key to wake it up.")

    def read_config(self, attempts=3):
        parts = {}
        for _ in range(attempts):  # the radio occasionally drops a reply
            self._drain()
            self.dev.write(self._frame(0x44, 0x01, 0))
            parts = {}
            deadline = time.monotonic() + 1.0
            while len(parts) < 10 and time.monotonic() < deadline:
                reply = self._recv(deadline - time.monotonic())
                if reply and len(reply) >= 20 and reply[0:3] == b"\x13\x44\x0a" and reply[3] < 10:
                    parts[reply[3]] = reply
            if len(parts) == 10:
                break
        if len(parts) < 10:
            raise DeviceError(
                "The 2.4G receiver is plugged in but the keyboard is not answering. "
                "Switch the keyboard to 2.4G mode and press a key to wake it.")
        body = bytearray()
        for seq in range(10):
            body += parts[seq][5:5 + min(parts[seq][4], 14)]
        return body[:CFG_LEN]

    def probe(self):
        self.read_config(attempts=1)  # quick check; a sleeping keyboard never answers
        return "F87"

    # Live frames (cmd 0x88, the OEM "audio dance" stream) are shown but not
    # stored. Data is a run of colour groups: R G B count led1 led2 ...; LEDs
    # not listed are off. At most 14 fragments of 14 bytes per frame.
    LIVE_FPS = 20
    LIVE_FEW_COLORS = True  # every distinct color costs bytes in the stream
    FRAGMENT_GAP = 0.010  # tested: 2 ms spacing stutters over 2.4G, 10 ms is smooth

    def send_live(self, colors):
        groups = {}
        for led, rgb in enumerate(colors[:PLANE]):
            if any(rgb):
                groups.setdefault(tuple(rgb), []).append(led)
        data = bytearray()
        for (r, g, b), leds in sorted(groups.items(), key=lambda item: -len(item[1])):
            group = bytes([r, g, b, len(leds)]) + bytes(leds)
            if len(data) + len(group) <= 14 * 14:
                data += group
        if data:
            chunks = [data[i:i + 14] for i in range(0, len(data), 14)]
            frames = [self._frame(0x88, len(chunks), seq,
                                  bytes([0x10 + len(chunk)]) + chunk)
                      for seq, chunk in enumerate(chunks)]
        else:
            frames = [self._frame(0x88, 0x01, 0, b"\x23")]  # idle: all off
        for frame in frames:
            self.dev.write(frame)
            time.sleep(self.FRAGMENT_GAP)
        self._drain()  # discard the echoes

    def _save(self):
        # Commit to the keyboard's memory. It doesn't always echo this frame
        # (seen on an F87 Pro: no echo, yet the change was stored), so don't wait on it.
        self.dev.write(self._frame(0x0A, 0x01, 0, b"\x04\x07"))
        time.sleep(0.05)
        self._drain()

    def write_lighting(self, cfg, pal):
        self._send_all(self._frames(0x04, 0x0A, cfg) + self._frames(0x09, 0x25, pal))
        self._save()

    def write_config(self, cfg):
        self._send_all(self._frames(0x04, 0x0A, cfg))
        self._save()

    def read_battery(self, attempts=2):
        """Battery level over 2.4G: ``Battery(percent, charging)``, or None.

        Request ``13 4A 00…`` → reply ``13 4A 01 00 02 <level> <state> … sum``.
        State 0x01 = on battery, 0x10 = cable plugged in (the level then reads
        100 regardless, so it is reported as charging without a percentage)."""
        for _ in range(attempts):
            self._drain()
            self.dev.write(self._frame(0x4A, 0x00, 0))
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                reply = self._recv(deadline - time.monotonic())
                if (reply and len(reply) >= 20 and reply[0] == 0x13 and reply[1] & 0x7F == 0x4A
                        and sum(reply[:19]) & 0xFF == reply[19]):
                    level, state = reply[5], reply[6]
                    charging = state == 0x10
                    percent = level if 1 <= level <= 100 and not charging else None
                    return Battery(percent, charging)
            time.sleep(0.2)
        return None

    def write_keys(self, cfg, keys):
        trailer = b"\x00\x00\x5a\xa5\x00\x00"
        self._send_all(self._frames(0x04, 0x0A, cfg) + self._frames(0x02, 0x1C, bytes(keys) + trailer))
        self._save()


@dataclass
class Battery:
    percent: object   # 1-100, or None when unknown (e.g. while charging)
    charging: bool

    def __str__(self):
        if self.charging:
            return "charging"
        return f"{self.percent}%" if self.percent is not None else "unknown"


# --------------------------------------------------------------------------- cache

class Cache:
    """Remembers palette and per-key colours, which can't be read back over 2.4G."""

    def __init__(self):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home()))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self.path = base / "aula-f87-control" / "cache.json"
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, name, length):
        try:
            blob = bytearray.fromhex(self.data.get(name, ""))
        except ValueError:
            return None
        return blob if len(blob) == length else None

    def put(self, name, blob):
        self._save(name, bytes(blob).hex())

    def get_value(self, name):
        return self.data.get(name)

    def put_value(self, name, value):
        self._save(name, value)

    def _save(self, name, value):
        self.data[name] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))


# --------------------------------------------------------------------------- keyboard

@dataclass
class Lighting:
    effect: int = 1
    brightness: int = 4
    speed: int = 3
    colorful: bool = False
    color: tuple = (255, 255, 255)
    side: int = 1
    sleep: float = 5.0   # minutes of inactivity before the backlight sleeps; 0 = never


@dataclass
class Keyboard:
    link: object
    model: str
    cache: Cache = field(default_factory=Cache)

    @property
    def description(self):
        return f"{self.model} · {self.link.label}"

    @property
    def alive(self):
        return self.link.dev.alive

    def close(self):
        self.link.close()

    def _palette(self):
        if self.link.can_read_blocks:
            pal = self.link.read_palette()
            self.cache.put("palette", pal)
            return pal
        return self.cache.get("palette", PAL_LEN) or _default_palette()

    def read_lighting(self):
        cfg = self.link.read_config()
        pal = self._palette()
        state = Lighting(effect=cfg[CFG_EFFECT], side=cfg[CFG_SIDE], sleep=cfg[CFG_SLEEP] / 2)
        if 1 <= state.effect <= 18:
            p = param_offset(state.effect)
            state.brightness = min(cfg[p], 4)
            state.speed = min(cfg[p + 1] >> 4, 4)
            slot = cfg[p + 1] & 0x0F
            state.colorful = slot >= COLORFUL
            o = slot_offset(state.effect, 0 if state.colorful else slot)
            if any(pal[o:o + 3]):
                state.color = tuple(pal[o:o + 3])
        return state

    def apply_lighting(self, state):
        cfg = self.link.read_config()
        pal = self._palette()
        info = effect_info(state.effect)
        cfg[CFG_EFFECT] = state.effect
        cfg[CFG_CUSTOM] = 1 if state.effect == PER_KEY else 0
        cfg[CFG_COLOR_MODE] = 1
        cfg[CFG_SIDE] = state.side
        if 1 <= state.effect <= 18:
            p = param_offset(state.effect)
            cfg[p] = max(0, min(4, state.brightness))
            speed = max(0, min(4, state.speed)) if info.speed else cfg[p + 1] >> 4
            slot = cfg[p + 1] & 0x0F
            if info.color:
                slot = COLORFUL if state.colorful else 0
                if not state.colorful:
                    o = slot_offset(state.effect)
                    pal[o:o + 3] = bytes(state.color)
            cfg[p + 1] = (speed << 4) | slot
        self.link.write_lighting(cfg, pal)
        self.cache.put("palette", pal)

    def read_battery(self):
        """Battery over 2.4G as a Battery, or None (USB cable / no reply).

        The keyboard only reports its level over 2.4G, and only while the cable
        is unplugged, so the last real reading is remembered (see last_battery)."""
        battery = self.link.read_battery()
        if battery is not None and battery.percent is not None:
            self.cache.put_value("battery", {"percent": battery.percent, "time": time.time()})
        return battery

    def last_battery(self):
        """(percent, unix time) of the last 2.4G reading, or None."""
        value = self.cache.get_value("battery")
        try:
            return int(value["percent"]), float(value["time"])
        except (TypeError, KeyError, ValueError):
            return None

    def set_sleep(self, minutes):
        """Idle minutes before the keyboard turns its backlight off; 0 = never.
        Stored in the keyboard (one write), so it also applies without this app."""
        cfg = self.link.read_config()
        cfg[CFG_SLEEP] = max(0, min(255, round(minutes * 2)))
        self.link.write_config(cfg)

    def read_keys(self):
        if self.link.can_read_blocks:
            keys = self.link.read_keys()
            self.cache.put("keys", keys)
        else:
            keys = self.cache.get("keys", KEYS_LEN) or bytearray(KEYS_LEN)
        return [(keys[i], keys[PLANE + i], keys[2 * PLANE + i]) for i in range(PLANE)]

    def apply_keys(self, colors):
        keys = bytearray(KEYS_LEN)
        for i, (r, g, b) in enumerate(colors[:PLANE]):
            keys[i], keys[PLANE + i], keys[2 * PLANE + i] = r, g, b
        cfg = self.link.read_config()
        cfg[CFG_EFFECT] = PER_KEY
        cfg[CFG_CUSTOM] = 1
        cfg[CFG_COLOR_MODE] = 1
        self.link.write_keys(cfg, keys)
        self.cache.put("keys", keys)


def connect():
    """Open the keyboard over USB if possible, otherwise over the 2.4G receiver."""
    problems = []
    # (link, USB id, report ID it needs, vendor usage pages to try first)
    for link_cls, usb_id, report_id, pages in ((WiredLink, WIRED_ID, 0x06, [0xFF00]),
                                               (DongleLink, DONGLE_ID, 0x13, [0xFF02, 0xFF04])):
        try:
            found = hidio.candidates(usb_id, report_id, pages)
        except hidio.HidError as exc:
            raise DeviceError(str(exc)) from None
        for _label, open_device in found:
            link = None
            try:
                link = link_cls(open_device())
                return Keyboard(link, link.probe())
            except (OSError, DeviceError, hidio.HidError) as exc:
                problems.append(str(exc))
                if link:
                    link.close()
    if problems:
        # Prefer the most helpful message (permission / wake-up hints come last).
        raise DeviceError(problems[-1])
    raise DeviceError("No AULA F87 found. Plug in the USB cable or the 2.4G receiver.")
