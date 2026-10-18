"""Make the backlight follow whatever the computer is playing.

Audio is captured from the default output device ("what you hear"), so it
works with any player:

* Linux: PipeWire's ``pw-record`` (monitor of the default output), falling
  back to the ``soundcard`` package (PulseAudio) if pw-record is missing.
* Windows: WASAPI loopback through the ``soundcard`` package.
* macOS: ``soundcard`` can only record inputs, so a loopback device such as
  BlackHole must be the default input (untested).

Frames are sent as live, unsaved frames; the keyboard returns to its stored
lighting by itself shortly after they stop.
"""

import colorsys
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings

import numpy as np

from .device import PLANE
from .effects import MUSIC_STYLES as STYLES
from .layout import KEYS, WIDTH_U

RATE = 48000
FFT_SIZE = 2048
BLOCK = 1024               # frames per capture read
BANDS = 18                 # roughly one band per key column
ROWS = sorted({k.y for k in KEYS})
LOW_HZ, HIGH_HZ = 40, 16000

BARS, METER, RAINBOW, PULSE = range(len(STYLES))


class MusicError(Exception):
    pass


class _Ring:
    """Keeps the most recent FFT_SIZE mono samples."""

    def __init__(self):
        self._data = np.zeros(FFT_SIZE, dtype=np.float32)
        self._lock = threading.Lock()

    def push(self, mono):
        with self._lock:
            if len(mono) >= FFT_SIZE:
                self._data[:] = mono[-FFT_SIZE:]
            else:
                self._data = np.roll(self._data, -len(mono))
                self._data[-len(mono):] = mono

    def copy(self):
        with self._lock:
            return self._data.copy()


class PipeWireCapture:
    """Linux: records the default output's monitor with pw-record."""

    def __init__(self):
        self._ring = _Ring()
        self._proc = subprocess.Popen(
            ["pw-record",
             "-P", "{ stream.capture.sink=true node.name=aula-f87-music "
                   "node.description=\"AULA F87 music sync\" }",
             "--raw", "--rate", str(RATE), "--channels", "2", "--format", "s16",
             "--latency", "20ms", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        pending = b""
        while True:
            data = self._proc.stdout.read1(BLOCK * 4) if self._proc.stdout else b""
            if not data:
                return
            pending += data
            usable = len(pending) - len(pending) % 4
            if not usable:
                continue
            stereo = np.frombuffer(pending[:usable], dtype="<i2").reshape(-1, 2)
            pending = pending[usable:]
            self._ring.push(stereo.mean(axis=1, dtype=np.float32) / 32768.0)

    @property
    def alive(self):
        return self._proc.poll() is None

    def samples(self):
        return self._ring.copy()

    def close(self):
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()


class SoundcardCapture:
    """Windows (WASAPI loopback), macOS and PulseAudio via the soundcard package."""

    def __init__(self):
        try:
            import soundcard  # noqa: F401
        except ImportError:
            raise MusicError("Music sync needs the 'soundcard' package: pip install soundcard") from None
        except Exception as exc:  # e.g. no audio server
            raise MusicError(f"Couldn't open the audio system: {exc}") from None
        self._ring = _Ring()
        self._stop = threading.Event()
        self._error = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise MusicError(f"Couldn't capture the audio output: {self._error}")

    def _read(self):
        try:
            if sys.platform == "win32":
                # soundcard uses COM; every thread that touches it must join the MTA.
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
            import soundcard as sc
            if sys.platform == "darwin":
                mic = sc.default_microphone()  # route output into e.g. BlackHole
            else:
                mic = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # "data discontinuity" notices on Windows
                with mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as recorder:
                    self._ready.set()
                    while not self._stop.is_set():
                        data = recorder.record(numframes=BLOCK)
                        self._ring.push(np.asarray(data, dtype=np.float32).mean(axis=1))
        except Exception as exc:  # reported through `alive` / the constructor
            self._error = exc
        finally:
            self._ready.set()

    @property
    def alive(self):
        return self._thread.is_alive() and self._error is None

    @property
    def error(self):
        return self._error

    def samples(self):
        return self._ring.copy()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)


def open_capture():
    """Pick the audio backend for this system (override with AULA_F87_AUDIO)."""
    choice = os.environ.get("AULA_F87_AUDIO", "").lower()
    if choice == "soundcard":
        return SoundcardCapture()
    if choice in ("", "pipewire") and sys.platform.startswith("linux") and shutil.which("pw-record"):
        return PipeWireCapture()
    if choice == "pipewire":
        raise MusicError("pw-record was not found. Install it with: sudo apt install pipewire-bin")
    return SoundcardCapture()


class Analyzer:
    """FFT -> per-band levels 0..1. Each band has its own automatic gain, so
    every column dances to its part of the music; levels rise instantly and
    fall smoothly."""

    SPAN_DB = 24.0          # dB window shown per band at sensitivity 1
    RANGE_DB = 40.0         # bands this far below the loudest are not boosted
    REF_FALL_DB_PER_S = 6.0
    FALL_PER_S = 2.2        # bars drop from full to empty in ~0.45 s
    PULSE_FALL_PER_S = 3.0
    FLOOR_DB = -100.0
    SILENCE_RMS = 10 ** (-70 / 20)  # quieter than -70 dBFS counts as silence

    def __init__(self):
        self.window = np.hanning(FFT_SIZE).astype(np.float32)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / RATE)
        edges = np.geomspace(LOW_HZ, HIGH_HZ, BANDS + 1)
        self.slices = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            a = int(np.searchsorted(freqs, lo))
            b = max(a + 1, int(np.searchsorted(freqs, hi)))
            self.slices.append((a, b))
        centers = np.sqrt(edges[:-1] * edges[1:])
        self.tilt_db = 3.0 * np.log2(centers / 1000.0)  # per-bin density -> band power
        self.band_ref = np.full(BANDS, self.FLOOR_DB + self.SPAN_DB)
        self.bass_avg_db = None
        self.levels = np.zeros(BANDS)
        self.pulse = 0.0

    def update(self, samples, dt, sensitivity=1.0):
        """sensitivity > 1 widens the dB window, so bars sit higher."""
        if float(np.sqrt(np.mean(samples ** 2))) < self.SILENCE_RMS:
            target = np.zeros(BANDS)
            hit = 0.0
        else:
            spectrum = np.abs(np.fft.rfft(samples * self.window)) / (FFT_SIZE / 4)
            energy = np.array([np.sqrt(np.mean(spectrum[a:b] ** 2)) for a, b in self.slices])
            db = 20 * np.log10(energy + 1e-12) + self.tilt_db

            # Per-band reference: follows peaks up at once, sinks slowly, and is
            # held within RANGE_DB of the loudest band so near-silent bands
            # don't get amplified into noise.
            span = self.SPAN_DB * sensitivity
            self.band_ref = np.maximum(db, self.band_ref - self.REF_FALL_DB_PER_S * dt)
            self.band_ref = np.maximum(
                self.band_ref, max(float(self.band_ref.max()) - self.RANGE_DB, self.FLOOR_DB + span))
            target = np.clip((db - (self.band_ref - span)) / span, 0.0, 1.0)

            # Beat: bass jumping above its own recent (~1 s) average.
            bass_db = float(db[:3].max())
            if self.bass_avg_db is None:
                self.bass_avg_db = bass_db
            hit = float(np.clip((bass_db - self.bass_avg_db - 1.5) / 6.0, 0.0, 1.0))
            self.bass_avg_db += (bass_db - self.bass_avg_db) * min(1.0, dt)

        self.levels = np.maximum(target, self.levels - self.FALL_PER_S * dt)
        self.pulse = max(hit, self.pulse - self.PULSE_FALL_PER_S * dt)
        return self.levels


def _key_bands():
    out = []
    for key in KEYS:
        band = min(int((key.x + key.w / 2) / WIDTH_U * BANDS), BANDS - 1)
        height = len(ROWS) - 1 - ROWS.index(key.y)  # 0 = bottom row
        out.append((key.led, band, height))
    return out


KEY_BANDS = _key_bands()
RED, YELLOW, GREEN = (255, 0, 0), (255, 170, 0), (0, 255, 0)
METER_COLORS = (GREEN, GREEN, GREEN, YELLOW, YELLOW, RED)  # by height, bottom first


def _band_color(band):
    """Bass (left) red, mids yellow, treble (right) green."""
    third = BANDS // 3
    return RED if band < third else YELLOW if band < 2 * third else GREEN


def _scale(rgb, k):
    return tuple(int(c * k) for c in rgb)


def render(analyzer, style, brightness, few_colors, clock):
    """Turn analyzer state into 126 LED colors.

    few_colors: the 2.4G stream sends one group per distinct color, so keep
    the palette small there (no partial dimming, 6 rainbow hues).
    """
    colors = [(0, 0, 0)] * PLANE
    if style == PULSE:  # whole board, color slowly drifting
        hue = (clock * 0.03) % 1.0
        if few_colors:
            hue = round(hue * 12) / 12
        rgb = tuple(c * 255 for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
        level = 0.08 + 0.92 * analyzer.pulse  # faint glow between beats
        if few_colors:
            level = round(level * 8) / 8
        for led, _band, _h in KEY_BANDS:
            colors[led] = _scale(rgb, level * brightness)
        return colors

    rows = len(ROWS)
    for led, band, height in KEY_BANDS:
        lit = analyzer.levels[band] * rows - height
        if lit < 0.15:  # a barely-lit top key just looks like a dead key
            continue
        if style == RAINBOW:
            hue = band / BANDS * 0.8
            if few_colors:
                hue = round(hue * 6) / 6
            rgb = tuple(c * 255 for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
        elif style == METER:
            rgb = METER_COLORS[height]
        else:
            rgb = _band_color(band)
        k = brightness if few_colors else brightness * min(1.0, lit)
        colors[led] = _scale(rgb, k)
    return colors


class MusicSync:
    """Background loop: capture -> analyze -> render -> send live frames."""

    def __init__(self, link, on_frame=None, on_error=None):
        self.link = link
        self.on_frame = on_frame
        self.on_error = on_error
        self.style = 0
        self.sensitivity = 1.0
        self.brightness = 1.0
        self.frames = 0
        self._stop = threading.Event()
        self._capture = open_capture()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def running(self):
        return self._thread.is_alive() and not self._stop.is_set()

    def stop(self):
        self._stop.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=3)
        self._capture.close()

    def _run(self):
        analyzer = Analyzer()
        few_colors = self.link.LIVE_FEW_COLORS
        period = 1.0 / self.link.LIVE_FPS
        start = last = time.monotonic()
        try:
            while not self._stop.is_set():
                if not self._capture.alive:
                    detail = getattr(self._capture, "error", None)
                    raise MusicError("Audio capture stopped" + (f": {detail}" if detail else "."))
                now = time.monotonic()
                analyzer.update(self._capture.samples(), now - last, self.sensitivity)
                last = now
                colors = render(analyzer, self.style, self.brightness, few_colors, now - start)
                self.link.send_live(colors)
                self.frames += 1
                if self.on_frame:
                    self.on_frame(colors)
                self._stop.wait(max(0.0, period - (time.monotonic() - now)))
        except Exception as exc:  # reported to the caller
            self._capture.close()
            if self.on_error:
                self.on_error(exc)
            else:
                raise
