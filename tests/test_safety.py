"""Checks that the keyboard's stored settings are never damaged by the app.

Runs without a keyboard: a fake link stands in for the USB / 2.4G transport.
python -m unittest discover -s tests
"""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from aula_f87 import device, music
from aula_f87.device import (DEFAULT_CONFIG, DamagedSettings, DeviceError, DeviceLock, Keyboard,
                             Lighting, _default_palette, config_ok, palette_ok)

# What the damage on a real F87 Pro looked like: palette bytes in the config,
# and the palette shifted by 21 bytes.
DAMAGED_CONFIG = bytes(_default_palette()[21:149])
SHIFTED_PALETTE = bytes(_default_palette()[21:]) + bytes(21)


class FakeLink:
    label = "USB cable"
    can_read_blocks = True
    LIVE_FPS = 30
    LIVE_FEW_COLORS = False

    class dev:
        alive = True

    def __init__(self, cfg=DEFAULT_CONFIG, pal=None):
        self.cfg = bytearray(cfg)
        self.pal = bytearray(pal or _default_palette())
        self.writes = []
        self.stale_reads = 0         # replies that aren't a config
        self.damage_next_write = False

    def close(self):
        pass

    def read_config(self):
        if self.stale_reads:
            self.stale_reads -= 1
            return bytearray(self.pal[:128])
        return bytearray(self.cfg)

    def read_palette(self):
        return bytearray(self.pal)

    def read_keys(self):
        return bytearray(device.KEYS_LEN)

    def read_battery(self):
        return None

    def send_live(self, colors):
        pass

    def _store(self, kind, cfg, pal=None):
        self.writes.append(kind)
        if self.damage_next_write:
            self.damage_next_write = False
            self.cfg[:], self.pal[:] = DAMAGED_CONFIG, SHIFTED_PALETTE
            return
        self.cfg[:] = cfg
        if pal is not None:
            self.pal[:] = pal

    def write_config(self, cfg):
        self._store("config", cfg)

    def write_lighting(self, cfg, pal):
        self._store("lighting", cfg, pal)

    def write_keys(self, cfg, keys):
        self._store("keys", cfg)


class SafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {name: self.tmp.name for name in
               ("XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "APPDATA", "LOCALAPPDATA")}
        for patcher in (mock.patch.dict(os.environ, env),
                        mock.patch.object(device.time, "sleep", lambda _s: None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def keyboard(self, link):
        return Keyboard(link, "F87 Pro", device.Cache())

    def test_validators(self):
        self.assertTrue(config_ok(DEFAULT_CONFIG))
        self.assertTrue(palette_ok(_default_palette()))
        self.assertFalse(config_ok(DAMAGED_CONFIG))
        self.assertFalse(palette_ok(SHIFTED_PALETTE))

    def test_writes_only_what_changed(self):
        link = FakeLink()
        kb = self.keyboard(link)
        state = kb.read_lighting()
        kb.apply_lighting(state)
        self.assertEqual(link.writes, [])
        state.brightness = 2
        kb.apply_lighting(state)
        self.assertEqual(link.writes, ["config"])
        state.effect, state.colorful, state.color = 1, False, (10, 20, 30)
        kb.apply_lighting(state)
        self.assertEqual(link.writes[-1], "lighting")
        self.assertEqual(tuple(link.pal[21:24]), (10, 20, 30))

    def test_stale_replies_are_read_again(self):
        link = FakeLink()
        link.stale_reads = 2
        self.assertEqual(self.keyboard(link).read_lighting().effect, DEFAULT_CONFIG[10])

    def test_damaging_write_is_undone(self):
        link = FakeLink()
        kb = self.keyboard(link)
        before = bytes(link.cfg), bytes(link.pal)
        link.damage_next_write = True
        with self.assertRaisesRegex(DeviceError, "put back"):
            kb.apply_lighting(Lighting(effect=2))
        self.assertEqual((bytes(link.cfg), bytes(link.pal)), before)

    def test_damaged_settings_are_never_written_back(self):
        good = FakeLink()
        self.keyboard(good).read_lighting()          # remembers the good settings
        link = FakeLink(DAMAGED_CONFIG, SHIFTED_PALETTE)
        kb = self.keyboard(link)
        with self.assertRaises(DamagedSettings):
            kb.read_lighting()
        with self.assertRaises(DamagedSettings):
            kb.apply_lighting(Lighting(effect=3))
        with self.assertRaises(DamagedSettings):
            kb.set_sleep(0)
        self.assertEqual(link.writes, [])
        self.assertEqual(kb.repair(), "last good settings")
        self.assertEqual(bytes(link.cfg), bytes(good.cfg))
        self.assertEqual(bytes(link.pal), bytes(good.pal))

    def test_repair_without_backup_uses_defaults(self):
        link = FakeLink(DAMAGED_CONFIG, SHIFTED_PALETTE)
        self.assertEqual(self.keyboard(link).repair(), "default settings")
        self.assertEqual(bytes(link.cfg), DEFAULT_CONFIG)
        self.assertTrue(palette_ok(link.pal))

    def test_invalid_settings_are_refused(self):
        link = FakeLink()
        bad = bytearray(DEFAULT_CONFIG)
        bad[1] = 0
        with self.assertRaisesRegex(DeviceError, "Not writing"):
            self.keyboard(link)._store(bad, DEFAULT_CONFIG)
        self.assertEqual(link.writes, [])

    def test_one_program_at_a_time(self):
        first = DeviceLock()
        self.assertTrue(first.acquire())
        second = DeviceLock()
        self.assertFalse(second.acquire(timeout=0.1))
        first.release()
        self.assertTrue(second.acquire(timeout=0.1))
        second.release()

    def test_no_settings_writes_during_music_sync(self):
        class Capture:
            alive = True

            def samples(self):
                return np.zeros((4096, 2), np.float32)

            def close(self):
                pass

        link = FakeLink()
        with mock.patch.object(music, "open_capture", Capture):
            sync = music.MusicSync(link)
            try:
                with self.assertRaisesRegex(DeviceError, "using the keyboard"):
                    self.keyboard(link).apply_lighting(Lighting(effect=3))
                with self.assertRaises(music.MusicError):
                    music.MusicSync(link)
            finally:
                sync.stop()
        self.assertEqual(link.writes, [])
        self.keyboard(link).apply_lighting(Lighting(effect=3))
        self.assertTrue(link.writes)


if __name__ == "__main__":
    unittest.main()
