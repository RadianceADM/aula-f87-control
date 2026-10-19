"""Built-in lighting effects, side-light modes and colour presets."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Effect:
    id: int
    name: str
    speed: bool
    color: bool


# Effect 18 plus the config "custom" flag shows the stored per-key map
# (confirmed on an F87 Pro; effect 21, used by newer F87 boards, goes dark).
PER_KEY = 18

# Firmware effect numbers. 6, 9 and 14 exist in the OEM table but
# misbehave on this board, so they are left out (as in other open tools).
EFFECTS = (
    Effect(0, "Off", False, False),
    Effect(1, "Static", False, True),
    Effect(2, "Breathing", True, True),
    Effect(3, "Rainbow wave", True, False),
    Effect(4, "Flash away", True, True),
    Effect(5, "Raindrops", True, True),
    Effect(7, "Ripples", True, True),
    Effect(8, "Twinkling stars", True, True),
    Effect(10, "Retro snake", True, True),
    Effect(11, "Neon stream", True, True),
    Effect(12, "Reactive (keypress)", True, True),
    Effect(13, "Sine wave", True, True),
    Effect(15, "Rotating windmill", True, False),
    Effect(16, "Colorful waterfall", True, False),
    Effect(17, "Blossoming", True, False),
    Effect(PER_KEY, "Custom per-key", False, False),
)

_BY_ID = {e.id: e for e in EFFECTS}


def effect_info(effect_id):
    return _BY_ID.get(effect_id) or Effect(effect_id, f"Effect {effect_id}", True, True)


# Lights on the sides of the case (config byte 18; Fn + Right Shift on the keyboard).
# The light bar above the arrow keys (byte 28, Fn + Left Shift) uses the same five
# modes, but the keyboard doesn't reliably apply changes to it from the computer.
SIDE_MODES = ("Off", "Rainbow wave", "Rainbow, all together", "Solid color", "Breathing")

PRESETS = (
    ("Red", (255, 0, 0)),
    ("Orange", (255, 96, 0)),
    ("Yellow", (255, 208, 0)),
    ("Green", (0, 255, 0)),
    ("Cyan", (0, 255, 255)),
    ("Blue", (0, 64, 255)),
    ("Purple", (140, 0, 255)),
    ("Pink", (255, 0, 160)),
    ("White", (255, 255, 255)),
)

# Music sync styles; the index is used by the GUIs and the CLI.
MUSIC_STYLES = ("EQ bars", "EQ bars (meter colors)", "EQ bars (rainbow)", "Beat pulse")

# What music sync can follow (key, label). Nothing selected = everything.
MUSIC_FOLLOW = (("bass", "Bass"), ("vocals", "Vocals"), ("beat", "Beat"))
FOLLOW_KEYS = tuple(key for key, _label in MUSIC_FOLLOW)

# "Turn the backlight off after" choices, in minutes (the keyboard stores 30 s steps).
SLEEP_MINUTES = (1, 2, 5, 10, 15, 30, 60)


def sleep_label(minutes):
    return f"{minutes:g} minute" + ("" if minutes == 1 else "s")


def nearest_sleep_index(minutes):
    return min(range(len(SLEEP_MINUTES)), key=lambda i: abs(SLEEP_MINUTES[i] - minutes))


def battery_text(battery, wired, last=None):
    """Human text for the battery row. battery: Battery or None; last: (percent, time)."""
    if battery is not None:
        return str(battery).capitalize()
    if wired:
        text = "Not reported over the cable (it charges from USB)"
        if last:
            import time
            percent, when = last
            stamp = time.strftime("%H:%M" if time.time() - when < 86400 else "%b %d %H:%M",
                                  time.localtime(when))
            text += f" · last 2.4G reading: {percent}% at {stamp}"
        return text
    return "Not reported"
