"""Tkinter window for AULA F87 lighting.

This is the app on Windows and macOS (Tkinter ships with Python there), and
the fallback on Linux when GTK 4 isn't installed. It has the same three tabs
as the GTK app and uses the same device and music code.
"""

import colorsys
import queue
import sys
import threading
import tkinter as tk
import traceback
from tkinter import colorchooser, font as tkfont, ttk

from . import about, device
from .settings import Settings
from .effects import (EFFECTS, FOLLOW_KEYS, MUSIC_FOLLOW, MUSIC_STYLES, PER_KEY, PRESETS,
                      SIDE_MODES, SLEEP_MINUTES,
                      Effect, battery_text, effect_info, nearest_sleep_index, sleep_label)
from .layout import HEIGHT_U, KEY_X, KEYS, WIDTH_U

APPLY_DELAY_MS = 350
POLL_MS = 3000
BATTERY_EVERY_POLLS = 20  # about once a minute
CASE_COLOR = "#1a1a1c"
UNLIT_COLOR = "#36363b"


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb)


def _is_bright(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b > 140


class Worker:
    """Runs device I/O off the UI thread, one job at a time. Results are
    handed back to Tk's main loop, because Tk must only be used from there."""

    def __init__(self, root):
        self._root = root
        self._jobs = queue.Queue()
        self._results = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()
        self._pump()

    def submit(self, job, done=None, failed=None):
        self._jobs.put((job, done, failed))

    def call_soon(self, fn, *args):
        """Thread-safe: run fn(*args) on the UI thread."""
        self._results.put((fn, args))

    def _run(self):
        while True:
            job, done, failed = self._jobs.get()
            try:
                result = job()
            except Exception as exc:  # reported back to the UI
                if failed:
                    self.call_soon(failed, exc)
            else:
                if done:
                    self.call_soon(done, result)

    def _pump(self):
        while True:
            try:
                fn, args = self._results.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:
                traceback.print_exc()
        self._root.after(30, self._pump)


class KeyboardCanvas(tk.Canvas):
    """Draws the 87-key board. With ``paint`` set, click/drag paints keys and
    right-click clears them."""

    def __init__(self, parent, color_for, paint=None, height=230):
        super().__init__(parent, height=height, highlightthickness=0, bg=CASE_COLOR)
        self._color_for = color_for
        self._paint = paint
        self._items = {}
        self._hits = []
        self.bind("<Configure>", lambda _e: self.rebuild())
        if paint:
            self.configure(cursor="crosshair")
            right = ("2", "3") if sys.platform == "darwin" else ("3",)
            self.bind("<Button-1>", lambda e: self._paint_at(e, False))
            self.bind("<B1-Motion>", lambda e: self._paint_at(e, False))
            for button in right:
                self.bind(f"<Button-{button}>", lambda e: self._paint_at(e, True))
                self.bind(f"<B{button}-Motion>", lambda e: self._paint_at(e, True))

    def rebuild(self):
        self.delete("all")
        self._items, self._hits = {}, []
        width, height = self.winfo_width(), self.winfo_height()
        pad = 10
        unit = min((width - 2 * pad) / WIDTH_U, (height - 2 * pad) / HEIGHT_U)
        if unit <= 4:
            return
        ox = (width - unit * WIDTH_U) / 2
        oy = (height - unit * HEIGHT_U) / 2
        family = tkfont.nametofont("TkDefaultFont").actual("family")
        label_font = (family, -max(7, int(unit * 0.24)))
        gap = unit * 0.08
        for key in KEYS:
            x = ox + key.x * unit + gap / 2
            y = oy + key.y * unit + gap / 2
            w, h = key.w * unit - gap, unit - gap
            rect = self.create_rectangle(x, y, x + w, y + h, fill=UNLIT_COLOR, outline="")
            text = self.create_text(x + w / 2, y + h / 2, text=key.label, font=label_font)
            self._items[key.led] = (rect, text)
            self._hits.append((x, y, w, h, key.led))
        self.refresh()

    def refresh(self):
        for led, (rect, text) in self._items.items():
            rgb = self._color_for(led)
            lit = any(rgb)
            self.itemconfigure(rect, fill=_hex(rgb) if lit else UNLIT_COLOR)
            self.itemconfigure(text, fill="#191919" if lit and _is_bright(rgb) else "#f2f2f2")

    def _paint_at(self, event, erase):
        for x, y, w, h, led in self._hits:
            if x <= event.x <= x + w and y <= event.y <= y + h:
                self._paint(led, erase)
                return


class Swatch(tk.Label):
    """A small clickable color square (tk.Label honours bg on every platform)."""

    def __init__(self, parent, rgb, on_click, size=2):
        super().__init__(parent, bg=_hex(rgb), width=size, height=1, relief="ridge", bd=1,
                         cursor="hand2")
        self.bind("<Button-1>", lambda _e: on_click(tuple(rgb)))

    def set(self, rgb):
        self.configure(bg=_hex(rgb))


class LevelScale(ttk.Frame):
    """Horizontal slider that snaps to steps, with the value shown next to it."""

    def __init__(self, parent, lo, hi, step, on_change, fmt="{:.0f}"):
        super().__init__(parent)
        self._lo, self._hi, self._step, self._fmt = lo, hi, step, fmt
        self._on_change = on_change
        self._quiet = False
        self.var = tk.DoubleVar(value=lo)
        self.scale = ttk.Scale(self, from_=lo, to=hi, variable=self.var, length=260,
                               command=self._moved)
        self.scale.pack(side="left")
        self.label = ttk.Label(self, width=5)
        self.label.pack(side="left", padx=(8, 0))
        self._last = None
        self._show()

    def _snap(self, value):
        return round(round((value - self._lo) / self._step) * self._step + self._lo, 3)

    def _show(self):
        self.label.configure(text=self._fmt.format(self.get()))

    def _moved(self, _value):
        value = self._snap(self.var.get())
        self.var.set(value)
        self._show()
        if value != self._last:
            self._last = value
            if not self._quiet:
                self._on_change()

    def get(self):
        return self._snap(self.var.get())

    def set(self, value):
        self._quiet = True
        try:
            self.var.set(self._snap(value))
            self._last = self.get()
            self._show()
        finally:
            self._quiet = False

    def enable(self, on):
        self.scale.state(["!disabled"] if on else ["disabled"])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AULA F87 Control")
        self.settings = Settings()
        width, height = self.settings["window"]
        self.geometry(f"{max(width, 820)}x{max(height, 640)}")
        self.minsize(820, 640)
        style = ttk.Style(self)
        if sys.platform.startswith("linux") and "clam" in style.theme_names():
            style.theme_use("clam")

        self.worker = Worker(self)
        self.kb = None
        self.state = device.Lighting()
        self.keys = [(0, 0, 0)] * device.PLANE
        self.brush = tuple(self.settings["brush"])
        self.color = (255, 255, 255)
        self._effects = list(EFFECTS)
        self._loading = False
        self._connecting = False
        self._apply_after = None
        self._apply_queued = False
        self._damaged = False   # the keyboard's stored settings need Repair
        self.music = None
        self._music_starting = False
        self._music_colors = [(0, 0, 0)] * device.PLANE
        self._music_draw_pending = False
        self._polls = 0

        top = ttk.Frame(self, padding=(12, 8))
        top.pack(fill="x")
        self.status = ttk.Label(top, text="Looking for keyboard…")
        self.status.pack(side="left")
        self.reconnect_button = ttk.Button(top, text="Reconnect",
                                           command=lambda: self.connect_keyboard())
        self.reconnect_button.pack(side="right")
        ttk.Button(top, text="About", command=self._show_about).pack(side="right", padx=(0, 6))
        self._about = None
        self.banner = tk.Frame(self, bg="#7a4f00")
        self.banner_text = tk.Label(self.banner, bg="#7a4f00", fg="white", anchor="w", padx=12,
                                    pady=6, wraplength=820, justify="left")
        self.banner_text.pack(side="left", fill="x", expand=True)
        self.repair_button = ttk.Button(self.banner, text="Repair", command=self._repair)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tabs.add(self._lighting_tab(), text="  Lighting  ")
        self.tabs.add(self._per_key_tab(), text="  Per-key colors  ")
        self.tabs.add(self._music_tab(), text="  Music sync  ")
        self._tab_names = ["lighting", "per-key", "music"]
        self.tabs.select(self._tab_names.index(self.settings["tab"]))
        self.tabs.bind("<<NotebookTabChanged>>", lambda _e: self.settings.__setitem__(
            "tab", self._tab_names[self.tabs.index(self.tabs.select())]))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._sync_widgets()
        self.connect_keyboard()
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ tabs

    def _lighting_tab(self):
        tab = ttk.Frame(self.tabs, padding=12)
        self.preview = KeyboardCanvas(tab, self._preview_color)
        self.preview.pack(fill="x")

        form = ttk.Frame(tab, padding=(0, 12))
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        row = 0

        def label(text):
            ttk.Label(form, text=text).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)

        label("Lighting effect")
        self.effect_box = ttk.Combobox(form, state="readonly", width=28,
                                       values=[e.name for e in self._effects])
        self.effect_box.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        self.effect_box.grid(row=row, column=1, sticky="w")
        row += 1

        label("Color")
        color_row = ttk.Frame(form)
        color_row.grid(row=row, column=1, sticky="w")
        self.rainbow_var = tk.BooleanVar()
        self.rainbow_check = ttk.Checkbutton(color_row, text="Rainbow (all colors)",
                                             variable=self.rainbow_var, command=self._changed)
        self.rainbow_check.pack(side="left")
        self.color_swatch = Swatch(color_row, self.color, lambda _c: self._pick_color(), size=4)
        self.color_swatch.pack(side="left", padx=(16, 6))
        self.color_button = ttk.Button(color_row, text="Pick color…", command=self._pick_color)
        self.color_button.pack(side="left")
        row += 1

        label("Quick colors")
        presets = ttk.Frame(form)
        presets.grid(row=row, column=1, sticky="w")
        for _name, rgb in PRESETS:
            Swatch(presets, rgb, self._use_color).pack(side="left", padx=2)
        row += 1

        label("Brightness")
        self.brightness = LevelScale(form, 0, 4, 1, self._changed)
        self.brightness.grid(row=row, column=1, sticky="w")
        row += 1

        label("Speed")
        self.speed = LevelScale(form, 0, 4, 1, self._changed)
        self.speed.grid(row=row, column=1, sticky="w")
        row += 1

        label("Side lights")
        self.side_box = ttk.Combobox(form, state="readonly", width=28, values=list(SIDE_MODES))
        self.side_box.bind("<<ComboboxSelected>>", lambda _e: self._changed())
        self.side_box.grid(row=row, column=1, sticky="w")
        row += 1

        ttk.Label(form, foreground="#777777",
                  text="The light bar above the arrow keys is set on the keyboard: "
                       "press Fn + Left Shift to cycle its effects.").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 12))
        row += 1

        label("Battery")
        self.battery_label = ttk.Label(form, text="—")
        self.battery_label.grid(row=row, column=1, sticky="w")
        row += 1

        label("Backlight sleep")
        power = ttk.Frame(form)
        power.grid(row=row, column=1, sticky="w")
        self.keep_on_var = tk.BooleanVar()
        self.keep_on_check = ttk.Checkbutton(
            power, text="Keep backlight on (uses more battery on 2.4G)",
            variable=self.keep_on_var, command=self._sleep_changed)
        self.keep_on_check.pack(side="left")
        ttk.Label(power, text="   otherwise turn off after").pack(side="left")
        self.sleep_box = ttk.Combobox(power, state="readonly", width=12,
                                      values=[sleep_label(m) for m in SLEEP_MINUTES])
        self.sleep_box.current(nearest_sleep_index(5))
        self.sleep_box.bind("<<ComboboxSelected>>", lambda _e: self._sleep_changed())
        self.sleep_box.pack(side="left", padx=(6, 0))
        return tab

    def _per_key_tab(self):
        tab = ttk.Frame(self.tabs, padding=12)
        ttk.Label(tab, text="Click or drag over keys to paint them. Right-click clears a key. "
                            "Press Apply to send the colors to the keyboard.").pack(anchor="w")
        self.paint_view = KeyboardCanvas(tab, lambda led: self.keys[led], paint=self._paint_key,
                                         height=330)
        self.paint_view.pack(fill="both", expand=True, pady=12)

        tools = ttk.Frame(tab)
        tools.pack(fill="x")
        ttk.Label(tools, text="Brush").pack(side="left")
        self.brush_swatch = Swatch(tools, self.brush, lambda _c: self._pick_brush(), size=4)
        self.brush_swatch.pack(side="left", padx=6)
        ttk.Button(tools, text="Pick…", command=self._pick_brush).pack(side="left", padx=(0, 10))
        for _name, rgb in PRESETS:
            Swatch(tools, rgb, self._set_brush).pack(side="left", padx=2)
        ttk.Button(tools, text="Fill all", command=lambda: self._fill_keys(self.brush)).pack(
            side="left", padx=(12, 4))
        ttk.Button(tools, text="Clear all", command=lambda: self._fill_keys((0, 0, 0))).pack(
            side="left")
        self.apply_keys_button = ttk.Button(tools, text="Apply to keyboard",
                                            command=self._apply_keys)
        self.apply_keys_button.pack(side="right")
        return tab

    def _music_tab(self):
        tab = ttk.Frame(self.tabs, padding=12)
        self.music_view = KeyboardCanvas(tab, lambda led: self._music_colors[led])
        self.music_view.pack(fill="x")
        ttk.Label(tab, text="The keys move with whatever this computer is playing, from any app. "
                            "Your saved lighting comes back when you stop.").pack(
            anchor="w", pady=(12, 8))

        form = ttk.Frame(tab)
        form.pack(fill="x")
        self.music_button = ttk.Button(form, text="Start", width=12, command=self._toggle_music)
        self.music_button.grid(row=0, column=0, sticky="w", pady=6)
        self.music_state = ttk.Label(form, text="Stopped")
        self.music_state.grid(row=0, column=1, sticky="w", padx=12)

        ttk.Label(form, text="Style").grid(row=1, column=0, sticky="w", pady=6)
        self.music_style_box = ttk.Combobox(form, state="readonly", width=28,
                                            values=list(MUSIC_STYLES))
        self.music_style_box.current(self.settings["music_style"])
        self.music_style_box.bind("<<ComboboxSelected>>", lambda _e: self._music_settings())
        self.music_style_box.grid(row=1, column=1, sticky="w", padx=12)

        ttk.Label(form, text="Follow").grid(row=4, column=0, sticky="w", pady=6)
        follow_row = ttk.Frame(form)
        follow_row.grid(row=4, column=1, sticky="w", padx=12)
        self._follow_updating = False
        self.follow_vars = {}
        for key, label in (("all", "All"),) + MUSIC_FOLLOW:
            var = tk.BooleanVar()
            ttk.Checkbutton(follow_row, text=label, variable=var,
                            command=lambda k=key: self._follow_toggled(k)).pack(side="left", padx=(0, 12))
            self.follow_vars[key] = var
        self._show_follow(self.settings["music_follow"])
        ttk.Label(form, text="What the lights react to", foreground="#777777").grid(
            row=5, column=1, sticky="w", padx=12)

        ttk.Label(form, text="Sensitivity").grid(row=2, column=0, sticky="w", pady=6)
        self.sensitivity = LevelScale(form, 0.5, 2.0, 0.1, self._music_settings, fmt="{:.1f}")
        self.sensitivity.set(self.settings["music_sensitivity"])
        self.sensitivity.grid(row=2, column=1, sticky="w", padx=12)

        ttk.Label(form, text="Brightness").grid(row=3, column=0, sticky="w", pady=6)
        self.music_brightness = LevelScale(form, 0.1, 1.0, 0.05, self._music_settings,
                                           fmt="{:.0%}")
        self.music_brightness.set(self.settings["music_brightness"])
        self.music_brightness.grid(row=3, column=1, sticky="w", padx=12)
        return tab

    # ------------------------------------------------------------------ connection

    def connect_keyboard(self, quiet=False):
        if self._connecting or self.music or self._music_starting:
            return
        self._connecting = True
        old, self.kb = self.kb, None
        if not quiet:
            self.status.configure(text="Connecting…")

        def job():
            if old:
                old.close()
            kb = device.connect()
            try:
                return kb, kb.read_lighting(), kb.read_keys(), kb.read_battery()
            except Exception:
                kb.close()
                raise

        def done(result):
            self._connecting = False
            self.kb, state, keys, battery = result
            self.keys = keys
            self._show_state(state)
            self.banner.pack_forget()
            self._show_battery(battery)
            self._sync_widgets()
            self.paint_view.refresh()
            if self.settings["music_on"] and not self.music and not self._music_starting:
                self._start_music()  # it was on last time (or before the keyboard dropped out)

        def failed(exc):
            self._connecting = False
            self._disconnected(str(exc), isinstance(exc, device.DamagedSettings))

        self.worker.submit(job, done, failed)

    def _disconnected(self, message, damaged=False):
        if self.kb:
            self.worker.submit(self.kb.close)  # after jobs already queued for it
            self.kb = None
        self._damaged = damaged
        self.status.configure(text="Settings damaged" if damaged else "Not connected")
        self.battery_label.configure(text="—")
        self.banner_text.configure(text=message)
        if damaged:
            self.repair_button.pack(side="right", padx=8, pady=4)
        else:
            self.repair_button.pack_forget()
        self.banner.pack(fill="x", before=self.tabs)
        self._sync_widgets()

    def _repair(self):
        """Write the keyboard's last good settings back (see Keyboard.repair)."""
        if self._connecting:
            return
        self._connecting = True  # no reconnect attempts meanwhile
        self.banner.pack_forget()
        self.status.configure(text="Repairing…")

        def job():
            kb = device.connect()
            try:
                return kb.repair()
            finally:
                kb.close()

        def done(used):
            self._connecting = False
            self._damaged = False
            self.connect_keyboard()
            self._toast(f"Repaired: put back the keyboard's {used}")

        def failed(exc):
            self._connecting = False
            self._disconnected(f"Repair failed: {exc}", damaged=True)

        self.worker.submit(job, done, failed)

    def _poll(self):
        self._polls += 1
        if self.kb and not self.kb.alive:
            if self.music:
                self._stop_music()
            self._disconnected("The keyboard was unplugged.")
        elif not self.kb:
            self.connect_keyboard(quiet=True)
        elif (self._polls % BATTERY_EVERY_POLLS == 0 and not self.music
              and not self._music_starting):
            kb = self.kb
            self.worker.submit(kb.read_battery,
                               lambda battery: self.kb is kb and self._show_battery(battery))
        self.after(POLL_MS, self._poll)

    def _show_battery(self, battery):
        """Battery level over 2.4G; over the cable the keyboard runs on USB power."""
        if not self.kb:
            return
        text = battery_text(battery, self.kb.link.label == "USB cable", self.kb.last_battery())
        self.battery_label.configure(text=text)
        suffix = f"  ·  Battery {battery}" if battery is not None else ""
        self._status_text = self.kb.description + suffix
        self.status.configure(text=self._status_text)

    def _sleep_changed(self):
        if self._loading or not self._lighting_editable():
            self._sync_widgets()
            return
        keep_on = self.keep_on_var.get()
        index = max(0, self.sleep_box.current())
        minutes = 0 if keep_on else SLEEP_MINUTES[index]
        self.state.sleep = minutes
        self._sync_widgets()
        kb = self.kb
        message = ("Backlight stays on" if minutes == 0
                   else f"Backlight turns off after {sleep_label(minutes)} idle")
        self.worker.submit(lambda: kb.set_sleep(minutes), lambda _r: self._toast(message),
                           self._io_failed)

    def _show_about(self):
        """Version, links and the changelog."""
        if self._about is not None and self._about.winfo_exists():
            self._about.lift()
            return
        import webbrowser
        win = self._about = tk.Toplevel(self)
        win.title(f"About {about.NAME}")
        win.geometry("620x640")
        win.transient(self)
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        base = tkfont.nametofont("TkDefaultFont")
        title_font = base.copy()
        title_font.configure(size=base.cget("size") + 6, weight="bold")
        bold = base.copy()
        bold.configure(weight="bold")
        ttk.Label(body, text=about.NAME, font=title_font).pack(anchor="w")
        ttk.Label(body, text=f"Version {about.__version__}").pack(anchor="w", pady=(2, 8))
        ttk.Label(body, text=about.SUMMARY, wraplength=580, justify="left").pack(anchor="w")
        links = ttk.Frame(body)
        links.pack(anchor="w", pady=8)
        for text, url in (("Website", about.WEBSITE), ("Report an issue", about.ISSUES),
                          ("Full changelog", about.CHANGELOG_URL)):
            link = tk.Label(links, text=text, fg="#3b82f6", cursor="hand2", font=base)
            link.pack(side="left", padx=(0, 16))
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        ttk.Label(body, text=f"{about.LICENSE} · {about.COPYRIGHT}").pack(anchor="w")
        ttk.Label(body, text="Changelog", font=bold).pack(anchor="w", pady=(14, 4))
        frame = ttk.Frame(body)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, wrap="word", relief="flat", padx=10, pady=8, font=base,
                       height=10, highlightthickness=0)
        bar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("version", font=bold, spacing1=10, spacing3=4)
        text.tag_configure("item", lmargin1=8, lmargin2=24, spacing3=3)
        text.tag_configure("sub", lmargin1=28, lmargin2=44, spacing3=3)
        entries = about.releases()
        for version, date, items in entries:
            text.insert("end", f"Version {version}" + (f" · {date}" if date else "") + "\n", "version")
            for depth, item in items:
                text.insert("end", ("– " if depth else "• ") + about.plain(item) + "\n",
                            "sub" if depth else "item")
        if not entries:
            text.insert("end", f"See {about.CHANGELOG_URL}")
        text.configure(state="disabled")
        ttk.Button(body, text="Close", command=win.destroy).pack(anchor="e", pady=(10, 0))

    def _on_close(self):
        # Music sync stops with the window; the keyboard goes back to its own lighting.
        if self.wm_state() == "normal":  # (self.state is the lighting state here)
            self.settings["window"] = [self.winfo_width(), self.winfo_height()]
        if self.music:
            self.music.stop()
            self.music = None
        self.destroy()

    # ------------------------------------------------------------------ lighting

    def _effect_index(self, effect_id):
        for i, effect in enumerate(self._effects):
            if effect.id == effect_id:
                return i
        info = effect_info(effect_id)
        self._effects.append(Effect(effect_id, f"{info.name} (set on keyboard)", True, True))
        self.effect_box.configure(values=[e.name for e in self._effects])
        return len(self._effects) - 1

    def _show_state(self, state):
        self._loading = True
        try:
            self.state = state
            self.effect_box.current(self._effect_index(state.effect))
            self.rainbow_var.set(state.colorful)
            self.color = tuple(state.color)
            self.color_swatch.set(self.color)
            self.brightness.set(state.brightness)
            self.speed.set(state.speed)
            if state.side < len(SIDE_MODES):
                self.side_box.current(state.side)
            self.keep_on_var.set(state.sleep == 0)
            if state.sleep:
                self.sleep_box.current(nearest_sleep_index(state.sleep))
        finally:
            self._loading = False
        self._sync_widgets()

    def _read_widgets(self):
        index = self.effect_box.current()
        effect = self._effects[index].id if 0 <= index < len(self._effects) else self.state.effect
        side = self.side_box.current()
        return device.Lighting(
            effect=effect,
            brightness=int(self.brightness.get()),
            speed=int(self.speed.get()),
            colorful=self.rainbow_var.get(),
            color=self.color,
            side=side if side >= 0 else self.state.side,
            sleep=self.state.sleep,
        )

    def _sync_widgets(self):
        busy = self.music is not None or self._music_starting
        connected = self.kb is not None and not busy  # music sync owns the keyboard while on
        info = effect_info(self.state.effect)
        timed = 1 <= self.state.effect <= 18

        def enable(widget, on):
            widget.state(["!disabled"] if on else ["disabled"])

        enable(self.effect_box, connected)
        enable(self.side_box, connected)
        enable(self.rainbow_check, connected and info.color)
        enable(self.color_button, connected)
        self.brightness.enable(connected and timed)
        self.speed.enable(connected and timed and info.speed)
        enable(self.keep_on_check, connected)
        enable(self.sleep_box, connected and not self.keep_on_var.get())
        enable(self.apply_keys_button, connected)
        enable(self.reconnect_button, not busy)
        self.preview.refresh()

        running = self.music is not None
        self.music_button.configure(text="Stop" if running else "Start")
        enable(self.music_button, self.kb is not None and not self._music_starting)
        if running:
            self.music_state.configure(text=f"On · {self.kb.link.label}" if self.kb else "On")
        else:
            self.music_state.configure(text="Starting…" if self._music_starting else
                                       "Stopped" if self.kb else "Connect the keyboard first")

    def _lighting_editable(self):
        return self.kb is not None and self.music is None and not self._music_starting

    def _pick_color(self):
        if not self._lighting_editable():
            return
        _rgb, hex_color = colorchooser.askcolor(color=_hex(self.color), parent=self,
                                                title="Keyboard color")
        if hex_color:
            self._use_color(tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5)))

    def _use_color(self, rgb):
        """Picking a color means "make it this color": leave rainbow mode and,
        if the current effect can't take a color, switch to Static."""
        if not self._lighting_editable():
            return
        self.color = tuple(rgb)
        self.color_swatch.set(self.color)
        if not effect_info(self.state.effect).color:
            self.effect_box.current(self._effect_index(1))
        self.rainbow_var.set(False)
        self._changed()

    def _changed(self):
        if self._loading:
            return
        self.state = self._read_widgets()
        self._sync_widgets()
        if self.kb:
            if self._apply_after:
                self.after_cancel(self._apply_after)
            self._apply_after = self.after(APPLY_DELAY_MS, self._apply_lighting)

    def _apply_lighting(self):
        self._apply_after = None
        if not self.kb or self._apply_queued:
            return  # a queued job will send the newest state
        self._apply_queued = True
        kb = self.kb

        def job():  # worker thread
            self._apply_queued = False
            kb.apply_lighting(self.state)

        self.worker.submit(job, None, self._io_failed)

    def _io_failed(self, exc):
        if isinstance(exc, device.DamagedSettings):
            self._disconnected(str(exc), damaged=True)
            return
        if isinstance(exc, OSError) or (self.kb and not self.kb.alive):
            self._disconnected("Lost connection to the keyboard.")
        self._toast(f"Couldn't update the keyboard: {exc}")

    def _toast(self, message):
        """Show a short message in the status line, then restore it."""
        self.status.configure(text=message)
        self.after(6000, lambda: self.status.configure(
            text=getattr(self, "_status_text", "") if self.kb else "Not connected"))

    def _preview_color(self, led):
        state = self.state
        if state.effect == 0:
            return (0, 0, 0)
        if state.effect == PER_KEY:
            return self.keys[led]
        info = effect_info(state.effect)
        if 1 <= state.effect <= 18 and state.brightness == 0:
            return (0, 0, 0)
        level = 0.4 + 0.6 * state.brightness / 4
        if state.colorful or not info.color:
            hue = KEY_X.get(led, 0) / WIDTH_U
            rgb = tuple(c * 255 for c in colorsys.hsv_to_rgb(hue, 1, 1))
        else:
            rgb = state.color
        return tuple(int(c * level) for c in rgb)

    # ------------------------------------------------------------------ per-key

    def _pick_brush(self):
        _rgb, hex_color = colorchooser.askcolor(color=_hex(self.brush), parent=self,
                                                title="Brush color")
        if hex_color:
            self._set_brush(tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5)))

    def _set_brush(self, rgb):
        self.brush = tuple(rgb)
        self.brush_swatch.set(self.brush)
        self.settings["brush"] = self.brush

    def _paint_key(self, led, erase=False):
        color = (0, 0, 0) if erase else self.brush
        if self.keys[led] != color:
            self.keys = list(self.keys)
            self.keys[led] = color
            self.paint_view.refresh()

    def _fill_keys(self, color):
        self.keys = list(self.keys)
        for key in KEYS:
            self.keys[key.led] = color
        self.paint_view.refresh()

    def _apply_keys(self):
        if not self._lighting_editable():
            return
        kb, keys = self.kb, list(self.keys)
        self.apply_keys_button.state(["disabled"])

        def done(_result):
            self.state.effect = PER_KEY
            self._show_state(self.state)
            self._toast("Per-key colors applied")

        def failed(exc):
            self._sync_widgets()
            self._io_failed(exc)

        self.worker.submit(lambda: kb.apply_keys(keys), done, failed)

    # ------------------------------------------------------------------ music

    def _toggle_music(self):
        """Start/stop chosen by the user; remembered so it resumes next time."""
        if self.music:
            self.settings["music_on"] = False
            self._stop_music()
        else:
            self.settings["music_on"] = True
            self._start_music()

    def _show_follow(self, selected):
        self.follow_vars["all"].set(not selected)
        for key in FOLLOW_KEYS:
            self.follow_vars[key].set(key in selected)

    def _follow(self):
        return [key for key in FOLLOW_KEYS if self.follow_vars[key].get()]

    def _follow_toggled(self, key):
        """"All" and the specific choices exclude each other; with nothing
        picked, "All" ticks itself again."""
        if key == "all" and self.follow_vars["all"].get():
            self._show_follow([])
        else:
            self._show_follow(self._follow())
        self._music_settings()

    def _music_settings(self):
        self.settings["music_follow"] = self._follow()
        self.settings["music_style"] = max(0, self.music_style_box.current())
        self.settings["music_sensitivity"] = self.sensitivity.get()
        self.settings["music_brightness"] = self.music_brightness.get()
        if self.music:
            self.music.style = max(0, self.music_style_box.current())
            self.music.sensitivity = self.sensitivity.get()
            self.music.brightness = self.music_brightness.get()
            self.music.follow = tuple(self._follow())

    def _start_music(self):
        if not self.kb or self._music_starting:
            return
        self._music_starting = True
        self._sync_widgets()
        link = self.kb.link

        def on_frame(colors):  # music thread
            self._music_colors = colors
            if not self._music_draw_pending:
                self._music_draw_pending = True
                self.worker.call_soon(self._draw_music_frame)

        def on_error(exc):  # music thread
            self.worker.call_soon(self._music_failed, exc)

        def job():
            try:
                from .music import MusicSync  # needs numpy
            except ImportError as exc:
                raise RuntimeError(f"music sync needs numpy ({exc}): pip install numpy") from None
            return MusicSync(link, on_frame, on_error)

        def done(sync):
            self._music_starting = False
            if sync.running:  # it may already have failed and reported why
                self.music = sync
                self._music_settings()
            else:
                self.worker.submit(sync.stop)
            self._sync_widgets()

        def failed(exc):
            self._music_starting = False
            self.settings["music_on"] = False  # don't retry a start that can't work
            self._sync_widgets()
            self._toast(f"Couldn't start music sync: {exc}")

        # Queued on the worker so it starts after any pending keyboard writes.
        self.worker.submit(job, done, failed)

    def _draw_music_frame(self):
        self._music_draw_pending = False
        self.music_view.refresh()

    def _stop_music(self):
        sync, self.music = self.music, None
        self._sync_widgets()

        def done(_result):
            self._music_colors = [(0, 0, 0)] * device.PLANE
            self.music_view.refresh()

        if sync:
            self.worker.submit(sync.stop, done)

    def _music_failed(self, exc):
        self._stop_music()
        if isinstance(exc, OSError) or (self.kb and not self.kb.alive):
            self._disconnected("Lost connection to the keyboard.")
        self._toast(f"Music sync stopped: {exc}")


def _log_to_file_without_console():
    """Started without a console (pythonw / aula-f87-control-gui.exe), Python
    has no stdout/stderr; send them to a log file so errors aren't lost."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    import os
    from pathlib import Path
    base = Path(os.environ.get("APPDATA", Path.home())) / "aula-f87-control"
    try:
        base.mkdir(parents=True, exist_ok=True)
        log = open(base / "log.txt", "a", buffering=1, encoding="utf-8")
    except OSError:
        log = open(os.devnull, "w")
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def main():
    _log_to_file_without_console()
    if sys.platform == "win32":
        try:  # sharp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().mainloop()
    return 0
