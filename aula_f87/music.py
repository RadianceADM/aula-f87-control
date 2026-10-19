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
FFT_SIZE = 2048            # main analysis window (~43 ms)
BASS_FFT_SIZE = 4096       # longer window: finer frequency steps for the bass range
BLOCK = 1024               # frames per capture read
BANDS = 18                 # roughly one band per key column
ROWS = sorted({k.y for k in KEYS})
LOW_HZ, HIGH_HZ = 40, 16000

BARS, METER, RAINBOW, PULSE = range(len(STYLES))

# What music sync follows. An empty selection means everything (the whole spectrum).
from .effects import FOLLOW_KEYS as FOLLOW_CHOICES  # noqa: E402


class MusicError(Exception):
    pass


class _Ring:
    """Keeps the most recent BASS_FFT_SIZE stereo samples (shape N x 2)."""

    def __init__(self):
        self._data = np.zeros((BASS_FFT_SIZE, 2), dtype=np.float32)
        self._lock = threading.Lock()

    def push(self, stereo):
        n = len(stereo)
        with self._lock:
            if n >= BASS_FFT_SIZE:
                self._data[:] = stereo[-BASS_FFT_SIZE:]
            else:
                self._data = np.roll(self._data, -n, axis=0)
                self._data[-n:] = stereo

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
            self._ring.push(stereo.astype(np.float32) / 32768.0)

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
                        data = np.asarray(data, dtype=np.float32)
                        if data.ndim == 1 or data.shape[1] == 1:
                            data = np.repeat(data.reshape(-1, 1), 2, axis=1)
                        self._ring.push(data[:, :2])
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


class _BandMeter:
    """Spectrum -> BANDS levels 0..1 for one frequency range.

    Each band has its own automatic gain, so every column moves with its part
    of the sound; levels rise instantly and fall smoothly."""

    SPAN_DB = 24.0          # dB window shown per band at sensitivity 1
    RANGE_DB = 40.0         # bands this far below the loudest are not boosted
    REF_FALL_DB_PER_S = 6.0
    FALL_PER_S = 2.2        # bars drop from full to empty in ~0.45 s
    FLOOR_DB = -100.0

    def __init__(self, fft_size, low_hz, high_hz, tilt=True):
        freqs = np.fft.rfftfreq(fft_size, 1.0 / RATE)
        edges = np.geomspace(low_hz, high_hz, BANDS + 1)
        self.slices = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            a = min(int(np.searchsorted(freqs, lo)), len(freqs) - 1)
            b = max(a + 1, int(np.searchsorted(freqs, hi)))
            self.slices.append((a, b))
        centers = np.sqrt(edges[:-1] * edges[1:])
        # per-bin density -> band power (music is roughly pink)
        self.tilt_db = 3.0 * np.log2(centers / 1000.0) if tilt else np.zeros(BANDS)
        self.band_ref = np.full(BANDS, self.FLOOR_DB + self.SPAN_DB)
        self.levels = np.zeros(BANDS)

    def band_db(self, spectrum):
        energy = np.array([np.sqrt(np.mean(spectrum[a:b] ** 2)) for a, b in self.slices])
        return 20 * np.log10(energy + 1e-12) + self.tilt_db

    def update(self, spectrum, dt, sensitivity):
        """spectrum: magnitudes, or None for silence."""
        if spectrum is None:
            target = np.zeros(BANDS)
        else:
            db = self.band_db(spectrum)
            span = self.SPAN_DB * sensitivity
            # Per-band reference: follows peaks up at once, sinks slowly, and is
            # held within RANGE_DB of the loudest band so near-silent bands
            # don't get amplified into noise.
            self.band_ref = np.maximum(db, self.band_ref - self.REF_FALL_DB_PER_S * dt)
            self.band_ref = np.maximum(
                self.band_ref, max(float(self.band_ref.max()) - self.RANGE_DB, self.FLOOR_DB + span))
            target = np.clip((db - (self.band_ref - span)) / span, 0.0, 1.0)
        self.levels = np.maximum(target, self.levels - self.FALL_PER_S * dt)
        return self.levels


# The beat lights the board from the middle outwards.
_BURST = 1.0 - 0.45 * np.abs(np.arange(BANDS) - (BANDS - 1) / 2) / ((BANDS - 1) / 2)


class Analyzer:
    """Audio -> ``levels`` (one 0..1 value per key column) and ``pulse`` (0..1).

    ``follow`` picks what drives them; the selected parts are combined:

    * empty (all): the whole spectrum, 40 Hz-16 kHz
    * "bass":   only 30-300 Hz, spread over all columns
    * "vocals": 150 Hz-5 kHz of what's in the centre of the stereo image,
      where singers are usually mixed; instruments spread to the sides drop out
    * "beat":   kick-drum hits; the board bursts from the middle on each beat
    """

    PULSE_FALL_PER_S = 3.0
    SILENCE_RMS = 10 ** (-70 / 20)  # quieter than -70 dBFS counts as silence
    CENTRE_SMOOTH_S = 0.25          # time constant of the stereo-centre estimate
    BEAT_BANDS = 4                  # lowest full-spectrum bands (40-150 Hz) used for the beat

    def __init__(self):
        self.window = np.hanning(FFT_SIZE).astype(np.float32)
        self.bass_window = np.hanning(BASS_FFT_SIZE).astype(np.float32)
        self.full = _BandMeter(FFT_SIZE, LOW_HZ, HIGH_HZ)
        self.bass = _BandMeter(BASS_FFT_SIZE, 30, 300, tilt=False)
        self.vocals = _BandMeter(FFT_SIZE, 150, 5000)
        self.prev_low_db = None
        self.flux_avg = 0.0
        self.beat = 0.0
        self.cross = None   # smoothed L*conj(R), |L|^2, |R|^2 per frequency bin
        self.levels = np.zeros(BANDS)
        self.pulse = 0.0

    @staticmethod
    def _stereo(samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim == 1:
            return samples, samples
        return samples[:, 0], samples[:, 1]

    def update(self, samples, dt, sensitivity=1.0, follow=()):
        """samples: stereo (N x 2) or mono; uses the last BASS_FFT_SIZE / FFT_SIZE of them.
        sensitivity > 1 widens the dB window, so bars sit higher."""
        left, right = self._stereo(samples)
        mid_all = (left + right) * 0.5
        mid = mid_all[-FFT_SIZE:]
        silent = float(np.sqrt(np.mean(mid ** 2))) < self.SILENCE_RMS
        follow = set(follow) & set(FOLLOW_CHOICES)
        norm = FFT_SIZE / 4

        # Whole spectrum: drives "all" and the beat detector.
        spectrum = None if silent else np.abs(np.fft.rfft(mid * self.window)) / norm
        full = self.full.update(spectrum, dt, sensitivity)

        # Beat: sudden rises in the low bands (spectral flux), compared with
        # their recent average. A steady bass line doesn't rise, a kick does.
        hit = 0.0
        if not silent:
            low_db = self.full.band_db(spectrum)[:self.BEAT_BANDS]
            if self.prev_low_db is not None:
                flux = float(np.maximum(low_db - self.prev_low_db, 0.0).sum())
                hit = float(np.clip((flux - 1.5 * self.flux_avg - 3.0) / 12.0, 0.0, 1.0))
                self.flux_avg += (flux - self.flux_avg) * min(1.0, dt / 1.0)
            self.prev_low_db = low_db
        else:
            self.prev_low_db = None
        self.beat = max(hit, self.beat - self.PULSE_FALL_PER_S * dt)

        if not follow:
            self.levels, self.pulse = full, self.beat
            return self.levels

        parts, drives = [], []
        if "bass" in follow:
            bass_spec = None
            if not silent:
                frame = mid_all[-BASS_FFT_SIZE:] if len(mid_all) >= BASS_FFT_SIZE else mid
                win = self.bass_window if len(frame) == BASS_FFT_SIZE else self.window
                bass_spec = np.abs(np.fft.rfft(frame * win)) / (len(frame) / 4)
            levels = self.bass.update(bass_spec, dt, sensitivity)
            parts.append(levels)
            drives.append(float(np.sort(levels)[-4:].mean()))
        if "vocals" in follow:
            vocal_spec = None
            if not silent:
                # Keep what sits in the centre: per frequency, L and R must be
                # correlated over time (coherence) and about equally loud.
                spec_l = np.fft.rfft(left[-FFT_SIZE:] * self.window)
                spec_r = np.fft.rfft(right[-FFT_SIZE:] * self.window)
                now = (spec_l * np.conj(spec_r), np.abs(spec_l) ** 2, np.abs(spec_r) ** 2)
                if self.cross is None:
                    self.cross = now
                else:
                    k = min(1.0, dt / self.CENTRE_SMOOTH_S)
                    self.cross = tuple(old + (new - old) * k for old, new in zip(self.cross, now))
                lr, ll, rr = self.cross
                coherence = np.abs(lr) ** 2 / (ll * rr + 1e-20)
                balance = 2 * np.sqrt(ll * rr) / (ll + rr + 1e-20)
                mask = np.clip(coherence * balance, 0.0, 1.0) ** 2
                vocal_spec = np.abs(np.fft.rfft(mid * self.window)) * mask / norm
            levels = self.vocals.update(vocal_spec, dt, sensitivity)
            parts.append(levels)
            drives.append(float(levels.mean()))
        if "beat" in follow:
            parts.append(self.beat * _BURST)
            drives.append(self.beat)
        self.levels = np.max(parts, axis=0)
        self.pulse = max(drives)
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
        self.follow = ()           # subset of FOLLOW_CHOICES; empty = everything
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
                analyzer.update(self._capture.samples(), now - last, self.sensitivity, self.follow)
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
