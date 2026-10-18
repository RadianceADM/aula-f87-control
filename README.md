# AULA F87 Control

[![CI](https://github.com/RadianceADM/aula-f87-control/actions/workflows/ci.yml/badge.svg)](https://github.com/RadianceADM/aula-f87-control/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/RadianceADM/aula-f87-control)](https://github.com/RadianceADM/aula-f87-control/releases/latest)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

Control the lighting of the **AULA F87 / F87 Pro** mechanical keyboard on **Linux and Windows**,
without AULA's own software.

![Lighting tab](docs/screenshots/lighting.png)

## Features

- **Lighting effects.** 14 built-in effects in any color or rainbow, with brightness and speed.
  Changes are sent to the keyboard as you click.
- **Per-key colors.** Paint individual keys on an on-screen keyboard.
- **Music sync.** The keys move with whatever your computer is playing, from any app. Styles:
  EQ bars, meter colors, rainbow, and beat pulse.
- **Battery level** (over 2.4G) and **sleep timer.** Keep the backlight always on, or choose
  when it turns off.
- **Side lights** effect.
- Works over the **USB cable** and the **2.4G receiver**.
- A **command line** for scripts and shortcuts.
- Needs no drivers and no admin rights once set up. Settings are stored in the keyboard
  itself, so they stay when you unplug it or use another computer.

## Supported keyboards

| Keyboard | USB cable | 2.4G receiver | Bluetooth |
|---|---|---|---|
| AULA F87 Pro | ✅ tested | ✅ tested | ❌ not supported |
| Other AULA boards with the same USB IDs (`258a:010c` cable, `3554:fa09` receiver), e.g. F87, F87 TK, F75, F99 | may work | may work | ❌ |

Tested on Ubuntu 26.04 with an F87 Pro, over both the cable and the 2.4G receiver. Per-key
colors were only tested over the cable.

The Windows version runs the same keyboard and audio code through `hidapi` and `soundcard`.
That code path was tested with the keyboard on Linux. CI checks on Windows that the installer
works and the window opens, but the app hasn't been used with a keyboard on a Windows PC yet,
so reports are welcome.

## Install

### Quick install

**Linux** (Ubuntu, Debian, Fedora, Arch). Paste into a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-linux.sh | bash
```

**Windows 10 / 11.** Paste into PowerShell (no admin needed):

```powershell
irm https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-windows.ps1 | iex
```

Both scripts install the [latest release](https://github.com/RadianceADM/aula-f87-control/releases/latest):

- **Linux:** the script asks for your password to install the required packages and the udev
  rule. It then adds **AULA F87 Control** to the app menu and the `aula-f87-control` command.
- **Windows:** the script installs Python with winget if it's missing, installs the app with
  pip, and adds **AULA F87 Control** to the Start menu.

Run the same command again to update. To uninstall:

```sh
curl -fsSL https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-linux.sh | bash -s -- --uninstall
```

```powershell
$env:AULA_UNINSTALL = 1; irm https://raw.githubusercontent.com/RadianceADM/aula-f87-control/main/scripts/install-windows.ps1 | iex
```

It's a good habit to read a script before you run it:
[install-linux.sh](scripts/install-linux.sh), [install-windows.ps1](scripts/install-windows.ps1).
To install by hand instead, follow the steps below.

### Ubuntu / Debian (manual)

```sh
sudo apt install git python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy pipewire-bin
git clone https://github.com/RadianceADM/aula-f87-control.git
cd aula-f87-control

# Let your user talk to the keyboard without root (one time)
sudo cp udev/70-aula-f87.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

./install.sh
```

Open **AULA F87 Control** from the app menu. If the keyboard isn't found, unplug and replug the
cable or receiver once, so the new permission applies.

`install.sh` adds a launcher and an app-menu entry that run the app from the cloned folder, so
keep the folder where it is. To update, run `git pull` in the folder. To uninstall, run
`./install.sh --remove`.

On other distributions, install the same packages under their own names, then follow the
steps above:

- **Fedora:** `python3-gobject gtk4 libadwaita python3-numpy pipewire-utils`
- **Arch:** `python-gobject gtk4 libadwaita python-numpy pipewire`

### Windows 10 / 11 (manual)

1. Install **Python 3.10 or newer** from [python.org](https://www.python.org/downloads/).
   In the installer, tick **"Add python.exe to PATH"**.
2. Open **Command Prompt** or **PowerShell** and run:

   ```
   pip install https://github.com/RadianceADM/aula-f87-control/archive/refs/heads/main.zip
   ```

3. To start the app, press **Win + R**, type `aula-f87-control-gui` and press Enter. You can also
   run `aula-f87-control` in a terminal.

   To pin the app to Start or the taskbar, find the program with `where aula-f87-control-gui`,
   then right-click it and choose **Pin to Start**.

No driver is needed. Close AULA's own software first if it is running. To update, run the
same `pip install` command with `--upgrade`. To uninstall, run `pip uninstall aula-f87-control`.

### macOS (untested)

Install it the same way as on Windows (`pip3 install …`), then run `aula-f87-control-gui`.
macOS may ask you to allow **Input Monitoring**. Music sync needs a loopback audio device,
such as BlackHole, set as the default input.

## Using the app

The Ubuntu app uses GTK and looks native on GNOME. Windows and macOS get a simpler window with
the same tabs and features. On Linux you can open that one too, with `aula-f87-control gui --tk`
(needs `python3-tk`).

### Lighting

- **Lighting effect.** Pick one of the built-in effects. *Custom per-key* shows your painted keys.
- **Color.** Pick any color, or click a quick color. Picking a color turns Rainbow off. If the
  current effect can't use a color, it switches to *Static*.
- **Rainbow.** Use all colors instead of a single one.
- **Brightness** and **Speed.** Range from 0 to 4. Speed only applies to animated effects.
- **Side lights.** Choose the effect of the lights on the sides of the case.
- **The light bar above the arrow keys** is controlled on the keyboard. Press **Fn + Left Shift**
  to cycle its effects (see [Troubleshooting](#troubleshooting)).

### Power

![Power settings](docs/screenshots/power.png)

- **Battery.** Shows the level when the keyboard is on the 2.4G receiver. On the cable it
  charges, and the keyboard doesn't report a level.
- **Keep backlight on.** The backlight never turns off when idle. This uses more battery on
  2.4G.
- **Turn backlight off after.** Sets how long the keyboard waits without a key press before
  the backlight sleeps. Press any key to wake it.

### Per-key colors

![Per-key colors](docs/screenshots/per-key.png)

Click or drag over keys to paint them with the brush color. Right-click a key to clear it.
**Fill all** and **Clear all** change every key at once. Press **Apply to keyboard** to save
the colors to the keyboard and switch it to the *Custom per-key* effect.

### Music sync

![Music sync](docs/screenshots/music.png)

Press **Start** and play something. The keyboard follows any app's sound: Spotify, YouTube,
games, and so on.

| Style | Looks like |
|---|---|
| EQ bars | One column per frequency band. Bass on the left is red, mids are yellow, treble on the right is green. |
| EQ bars (meter colors) | The same bars, colored green, then yellow, then red from bottom to top. |
| EQ bars (rainbow) | Each column has its own color. |
| Beat pulse | The whole keyboard flashes on the bass, with the color slowly changing. |

- **Sensitivity.** Higher makes the bars taller. The app also adjusts to the volume on its own.
- **Brightness.** How bright the music lights are.

Music sync sends temporary frames and saves nothing. Your normal lighting comes back about a
second after you press Stop. The other tabs are locked while it runs.

Over the cable the keyboard updates about 30 times per second. Over 2.4G it updates 12–20
times per second, because the radio can't take frames any faster.

## Command line

| Command | What it does |
|---|---|
| `aula-f87-control` | Open the window |
| `aula-f87-control status` | Show the effect, color, brightness, side lights, sleep and battery |
| `aula-f87-control set --effect static --color ff6000` | Solid orange |
| `aula-f87-control set --effect breathing --rainbow --speed 2 --brightness 3` | Rainbow breathing |
| `aula-f87-control set --side 1` | Side lights effect: 0 off, 1 rainbow wave, 2 rainbow together, 3 solid, 4 breathing |
| `aula-f87-control sleep never` | Keep the backlight always on |
| `aula-f87-control sleep 10` | Backlight turns off after 10 idle minutes |
| `aula-f87-control music --style bars` | Music sync until Ctrl+C. Styles: `bars`, `meter`, `rainbow`, `pulse`. Options: `--sensitivity 0.5–2`, `--brightness 0.1–1`, `--seconds N` |
| `aula-f87-control gui --tk` | Open the simpler Tkinter window, even on Linux |

You can give `--effect` as a number or as the start of a name: `off`, `static`, `breathing`,
`rainbow`, `flash`, `raindrops`, `ripples`, `twinkling`, `retro`, `neon`, `reactive`, `sine`,
`rotating`, `colorful`, `blossoming`, `custom`.

## Troubleshooting

**"Permission denied on /dev/hidrawN" (Linux).** Install the udev rule from
[Ubuntu / Debian](#ubuntu--debian-manual), then unplug and replug the keyboard or receiver.

**"The 2.4G receiver is plugged in but the keyboard is not answering."** The keyboard is
asleep, switched off, or in Bluetooth mode. Press a key, and check the mode switch on the
keyboard. To stop it from falling asleep, turn on **Keep backlight on**.

**"No AULA F87 found."** Check the cable or receiver. On Windows, close AULA's own software.
Only run one lighting app at a time.

**AULA's web driver (hub.aulacn.com) says it can't read the keyboard.** The web driver supports
newer boards, not the original F87 Pro. Use this app instead.

**The light bar above the arrow keys doesn't follow the app or the music.** The keyboard
controls that bar itself. Press **Fn + Left Shift** to cycle its effects: off, rainbow wave,
rainbow all together, solid, and breathing. It ignores the temporary frames that music sync
uses. The keyboard also doesn't reliably apply changes to it from the computer.

**Music sync is on but the keys stay dark.** Make sure something is playing on the default
audio output. On Linux the app needs `pw-record` (`sudo apt install pipewire-bin`). Raise
**Sensitivity** if the music is very quiet.

**Battery shows "On USB power".** That's expected on the cable. The keyboard only reports its
level over 2.4G, and over 2.4G it shows "Charging" while the cable is plugged in.

**Changes over 2.4G take a moment.** Each change takes about half a second over the radio.

**The keyboard restarted while I changed a setting.** Don't run two lighting apps at the same
time. This app locks the other tabs during music sync for this reason.

**I want AULA's factory settings back.** Hold **Fn + Esc** for 3 seconds, as described in AULA's manual.

**Windows: `AttributeError: module 'hid' has no attribute 'device'`.** A different package
called `hid` is installed. Run `pip uninstall hid`, then `pip install --force-reinstall hidapi`.

## Is it safe?

- The app sends the same kind of commands as AULA's Windows software. They were worked out by
  the projects listed in [Credits](#credits) and checked on a real F87 Pro.
- Saving a setting writes it once to the keyboard's memory. Music sync and previews use
  temporary frames that are never stored, so they don't wear that memory.
- The app never touches the keyboard's firmware.
- This project isn't affiliated with AULA. Use it at your own risk.

## How it works

The keyboard has a vendor-specific USB HID interface. Over the cable the app exchanges 520-byte
*feature reports* with it. Over the 2.4G receiver it sends 20-byte *output reports*, and the
keyboard echoes each one. Both carry the same settings blocks: a 128-byte config, a 512-byte
color palette and a 378-byte per-key color map.

- **Linux:** the app talks to `/dev/hidraw*` directly and records audio with PipeWire's
  `pw-record`.
- **Windows and macOS:** it uses [hidapi](https://pypi.org/project/hidapi/) and
  [soundcard](https://pypi.org/project/soundcard/).

[docs/PROTOCOL.md](docs/PROTOCOL.md) documents every byte the app uses.

## Contributing

Bug reports and test results are welcome, especially from **Windows** users and owners of
**other AULA models**. Please open an issue with:

- your keyboard model and connection (cable or 2.4G),
- your operating system,
- the output of `aula-f87-control status`.

To work on the code:

```sh
python3 -m aula_f87                 # run from the source folder
AULA_F87_HID=hidapi python3 -m aula_f87 status      # use the Windows/macOS HID path on Linux
AULA_F87_AUDIO=soundcard python3 -m aula_f87 music  # use the Windows/macOS audio path on Linux
```

| File | Purpose |
|---|---|
| `aula_f87/hidio.py` | Raw HID access: Linux hidraw, or hidapi |
| `aula_f87/device.py` | Keyboard protocol: settings, per-key colors, live frames, battery, sleep |
| `aula_f87/music.py` | Audio capture, spectrum analysis and music-sync rendering |
| `aula_f87/gui.py` | GTK 4 / libadwaita app (Linux) |
| `aula_f87/gui_tk.py` | Tkinter app (Windows, macOS, and the Linux fallback) |
| `aula_f87/effects.py`, `layout.py` | Effect list, presets, key positions and LED numbers |
| `aula_f87/__main__.py` | Command line and window selection |
| `scripts/` | Quick install scripts for Linux and Windows |

**Releases.** Bump `version` in `pyproject.toml`, add a section to `CHANGELOG.md`, then push a
tag that matches the version, such as `git tag v0.2.1 && git push origin v0.2.1`. GitHub
Actions builds the wheel and the source archive and publishes the release. CI tests installing
with pip on Linux and Windows, and runs both quick installers, on every push.

## Credits

This app builds on protocol research by:

- [marcoslor/Aula-F87-Controller](https://github.com/marcoslor/Aula-F87-Controller): 2.4G
  protocol and the audio stream
- [veysiemrah/aula-rgb-controller](https://github.com/veysiemrah/aula-rgb-controller): wired
  protocol and LED layout
- [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB): `SinowealthKeyboard10c` direct mode
- [ushineko/sanshoku #36](https://github.com/ushineko/sanshoku/issues/36) and
  [PyFlat/Device-Battery-Info #6](https://github.com/PyFlat/Device-Battery-Info/pull/6): the
  battery command

## License

[GPL-3.0-or-later](LICENSE).
