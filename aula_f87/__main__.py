"""Entry point: ``aula-f87-control [gui|status|set|sleep|music|repair] ...``.

Without a command it opens the window: the GTK 4 app on Linux, the Tkinter
app on Windows/macOS (or on Linux with ``gui --tk`` / when GTK is missing).
"""

import argparse
import sys
import threading
import time

from . import __version__, device
from .effects import EFFECTS, SIDE_MODES, battery_text, effect_info

STYLE_NAMES = ("bars", "meter", "rainbow", "pulse")  # same order as music.STYLES


def _effect_id(text):
    if text.isdigit():
        return int(text)
    for e in EFFECTS:
        if e.name.lower().startswith(text.lower()):
            return e.id
    raise argparse.ArgumentTypeError(f"unknown effect {text!r}")


def _color(text):
    text = text.lstrip("#")
    if len(text) != 6:
        raise argparse.ArgumentTypeError("use RRGGBB")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def gui_main(force_tk=False, background=False):
    """Open the window: GTK 4 on Linux when available, otherwise Tkinter.

    background: start with only the top-bar icon (GTK app on Linux)."""
    if sys.platform.startswith("linux") and not force_tk:
        try:
            from .gui import main as gtk_main
        except (ImportError, ValueError):  # PyGObject / GTK 4 / libadwaita missing
            pass
        else:
            return gtk_main(background=background)
    from .gui_tk import main as tk_main
    return tk_main()


def _sleep_text(minutes):
    return "never (backlight always on)" if minutes == 0 else f"after {minutes:g} min idle"


def _print_state(kb, state):
    info = effect_info(state.effect)
    color = "rainbow" if state.colorful else "#%02x%02x%02x" % state.color
    print(f"Keyboard:   {kb.description}")
    print(f"Effect:     {info.name} ({state.effect})")
    print(f"Color:      {color}")
    print(f"Brightness: {state.brightness}/4   Speed: {state.speed}/4")
    side = SIDE_MODES[state.side] if state.side < len(SIDE_MODES) else state.side
    print(f"Side lights: {side}")
    print(f"Sleep:      {_sleep_text(state.sleep)}")
    battery = kb.read_battery()
    print(f"Battery:    {battery_text(battery, kb.link.label == 'USB cable', kb.last_battery())}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="aula-f87-control")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--background", action="store_true",
                        help="start hidden with only the top-bar icon (used at login)")
    sub = parser.add_subparsers(dest="cmd")
    g = sub.add_parser("gui", help="open the window (default)")
    g.add_argument("--tk", action="store_true", help="use the Tkinter window even on Linux")
    sub.add_parser("status", help="show the current lighting")
    s = sub.add_parser("set", help="change the lighting")
    s.add_argument("--effect", type=_effect_id, help="name or number, e.g. static, breathing, 3")
    s.add_argument("--color", type=_color, help="RRGGBB")
    s.add_argument("--rainbow", action="store_true")
    s.add_argument("--brightness", type=int, choices=range(5))
    s.add_argument("--speed", type=int, choices=range(5))
    s.add_argument("--side", type=int, choices=range(len(SIDE_MODES)))
    z = sub.add_parser("sleep", help="when the backlight turns off: 'never' or idle minutes")
    z.add_argument("when", help="never, or minutes such as 1, 5, 10, 30")
    m = sub.add_parser("music", help="make the backlight follow what's playing (Ctrl+C stops)")
    m.add_argument("--style", choices=STYLE_NAMES, default="bars",
                   help="bars: bass red / mids yellow / treble green; meter: green-yellow-red by height")
    m.add_argument("--sensitivity", type=float, default=1.0, help="0.2-2, higher = taller bars")
    m.add_argument("--brightness", type=float, default=1.0, help="0.1-1")
    m.add_argument("--follow", default="all",
                   help="what to react to: all, or a comma list of bass, vocals, beat")
    m.add_argument("--seconds", type=float, help="stop automatically after this long")
    sub.add_parser("repair", help="put back the keyboard's last good settings "
                                  "(if it stopped typing or its lights flash)")
    args = parser.parse_args(argv)

    if args.cmd in (None, "gui"):
        return gui_main(force_tk=getattr(args, "tk", False), background=args.background)
    if args.cmd == "music":
        follow = [part.strip().lower() for part in args.follow.split(",") if part.strip()]
        unknown = [part for part in follow if part not in ("all", "bass", "vocals", "beat")]
        if unknown:
            print(f"Unknown --follow value: {', '.join(unknown)} (use all, bass, vocals, beat)",
                  file=sys.stderr)
            return 2
        args.follow = tuple(part for part in follow if part != "all")

    try:
        kb = device.connect()
    except device.DeviceError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.cmd == "music":
        return _music(kb, args)
    if args.cmd == "repair":
        try:
            used = kb.repair()
            print(f"Put back the keyboard's {used}.")
            _print_state(kb, kb.read_lighting())
        except (device.DeviceError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        finally:
            kb.close()
        return 0
    if args.cmd == "sleep":
        try:
            minutes = 0.0 if args.when.lower() in ("never", "off", "0") else float(args.when)
        except ValueError:
            print("Use 'never' or a number of minutes.", file=sys.stderr)
            kb.close()
            return 2
    try:
        state = kb.read_lighting()
        if args.cmd == "sleep":
            kb.set_sleep(minutes)
            state = kb.read_lighting()
        if args.cmd == "set":
            for name in ("effect", "color", "brightness", "speed", "side"):
                if getattr(args, name) is not None:
                    setattr(state, name, getattr(args, name))
            if args.color is not None or args.rainbow:
                state.colorful = args.rainbow
            kb.apply_lighting(state)
            state = kb.read_lighting()
        _print_state(kb, state)
    except device.DamagedSettings as exc:
        print(f"Error: {exc}\nRun: aula-f87-control repair", file=sys.stderr)
        return 1
    except (device.DeviceError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        kb.close()
    return 0


def _music(kb, args):
    from .music import MusicError, MusicSync

    failure = []
    done = threading.Event()

    def on_error(exc):
        failure.append(exc)
        done.set()

    try:
        sync = MusicSync(kb.link, on_error=on_error)
    except MusicError as exc:
        print(exc, file=sys.stderr)
        kb.close()
        return 1
    sync.style = STYLE_NAMES.index(args.style)
    sync.sensitivity = min(2.0, max(0.2, args.sensitivity))
    sync.brightness = min(1.0, max(0.1, args.brightness))
    sync.follow = args.follow
    print(f"Music sync on {kb.description}. Press Ctrl+C to stop.")
    start = time.monotonic()
    try:
        done.wait(args.seconds)
    except KeyboardInterrupt:
        pass
    sync.stop()
    kb.close()
    elapsed = time.monotonic() - start
    print(f"Stopped after {elapsed:.0f}s ({sync.frames / max(elapsed, 0.001):.1f} frames/s).")
    if failure:
        print(f"Error: {failure[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
