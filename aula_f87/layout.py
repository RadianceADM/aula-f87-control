"""Physical 87-key ANSI layout and the hardware LED index of every key.

LED indices come from the OEM driver's KB.ini; the board is wired in
columns of six LEDs (Esc=0, `=1, Tab=2, Caps=3, LShift=4, LCtrl=5, F1=12 ...).
Positions are in key units (1u = one alphanumeric key).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Key:
    label: str
    led: int
    x: float
    y: float
    w: float = 1.0


# Each row: (y, items). An item is (label, led[, width]) or a bare number for a gap.
_ROWS = [
    (0.0, [("Esc", 0), 1,
           ("F1", 12), ("F2", 18), ("F3", 24), ("F4", 30), 0.5,
           ("F5", 36), ("F6", 42), ("F7", 48), ("F8", 54), 0.5,
           ("F9", 60), ("F10", 66), ("F11", 72), ("F12", 78), 0.25,
           ("PrtSc", 84), ("ScrLk", 90), ("Pause", 96)]),
    (1.25, [("`", 1), ("1", 7), ("2", 13), ("3", 19), ("4", 25), ("5", 31),
            ("6", 37), ("7", 43), ("8", 49), ("9", 55), ("0", 61), ("-", 67),
            ("=", 73), ("Backspace", 79, 2), 0.25,
            ("Ins", 85), ("Home", 91), ("PgUp", 97)]),
    (2.25, [("Tab", 2, 1.5), ("Q", 8), ("W", 14), ("E", 20), ("R", 26),
            ("T", 32), ("Y", 38), ("U", 44), ("I", 50), ("O", 56), ("P", 62),
            ("[", 68), ("]", 74), ("\\", 80, 1.5), 0.25,
            ("Del", 86), ("End", 92), ("PgDn", 98)]),
    (3.25, [("Caps", 3, 1.75), ("A", 9), ("S", 15), ("D", 21), ("F", 27),
            ("G", 33), ("H", 39), ("J", 45), ("K", 51), ("L", 57), (";", 63),
            ("'", 69), ("Enter", 81, 2.25)]),
    (4.25, [("Shift", 4, 2.25), ("Z", 10), ("X", 16), ("C", 22), ("V", 28),
            ("B", 34), ("N", 40), ("M", 46), (",", 52), (".", 58), ("/", 64),
            ("Shift", 82, 2.75), 1.25, ("↑", 94)]),
    (5.25, [("Ctrl", 5, 1.25), ("Win", 11, 1.25), ("Alt", 17, 1.25),
            ("", 35, 6.25), ("Alt", 53, 1.25), ("Fn", 59, 1.25),
            ("Menu", 65, 1.25), ("Ctrl", 83, 1.25), 0.25,
            ("←", 89), ("↓", 95), ("→", 101)]),
]


def _build():
    keys = []
    for y, items in _ROWS:
        x = 0.0
        for item in items:
            if isinstance(item, (int, float)):
                x += item
                continue
            label, led, *width = item
            w = width[0] if width else 1.0
            keys.append(Key(label, led, x, y, w))
            x += w
    return tuple(keys)


KEYS = _build()
WIDTH_U = 18.25
HEIGHT_U = 6.25
KEY_X = {k.led: k.x + k.w / 2 for k in KEYS}
