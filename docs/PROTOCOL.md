# AULA F87 / F87 Pro: USB HID protocol

This document describes everything the app sends to and reads from the keyboard. It was
compiled from the projects listed under [Credits](../README.md#credits) and checked on an
F87 Pro.

**Status:** ✅ = verified on F87 Pro hardware · ⚠️ = taken from other projects, not verified here.

## Devices

| Connection | USB ID | Product string | Reports used |
|---|---|---|---|
| Cable | `258a:010c` | BY Tech "Gaming Keyboard" | Feature report `0x06`, 520 bytes including the ID, on the vendor collection (usage page `0xFF00`) of interface 1 |
| 2.4G receiver | `3554:fa09` | "CX 2.4G Wireless Receiver" | Output and input report `0x13`, 20 bytes including the ID, on the collection with usage page `0xFF02`, usage `0x02` |

How to find the right device on each platform:

- **Linux (hidraw):** there is one `/dev/hidrawN` node per USB interface. Use the node whose
  report descriptor declares the report ID: `85 06` for the cable, `85 13` for the receiver.
- **Windows and macOS (hidapi):** each top-level collection is a separate device. Try every
  vendor collection (usage page `0xFF00`–`0xFFFF`) and keep the one that answers. The cable's
  report descriptor has three `0xFF00` collections, declaring reports `0x03`, `0x05` and
  `0x06`, and only the `0x06` one accepts these requests.

None of this needs a kernel driver or root. On Linux, a udev rule gives the logged-in user
access (see `udev/`).

## Cable: feature reports

Every request is one 520-byte feature report:

```
06  cmd  00 00  01 00  len_lo len_hi  data…
```

| Command | Read with | Block | Length | Status |
|---|---|---|---|---|
| `0x04` | `0x84` | config | 128 (`80 00`) | ✅ |
| `0x0A` | `0x8A` | palette | 512 (`00 02`) | ✅ |
| `0x06` | `0x86` | per-key map | 378 (`7A 01`) | ✅ |

**Reading a block.** Send the header with `cmd | 0x80` and the length, then do GET_FEATURE on
report `0x06`. The reply repeats the header, followed by the data.

**Writing a block.** Send the header with `cmd`, the length and the data. The keyboard stores it
immediately; there is no separate save command.

**Model query** ✅. Send `06 82 01 00 01 00 06`, then do GET_FEATURE. Byte 13 of the reply is the
model: `0x0B` is the F87 Pro, `0x66` is the F87 TK.

**Live frame** ✅ (cmd `0x08`). This shows colors without saving them:

```
06 08 00 00 01 00 7A 01  R0 G0 B0  R1 G1 B1 …   (122 LEDs, RGB interleaved, LED n at byte 8 + 3n)
```

The keyboard goes back to its saved lighting about one second after the last frame, so keep
sending frames, at least every 500 ms. About 30 frames per second works without stalls. This
is the same "direct mode" that OpenRGB uses.

**Timing quirks:**

- Right after a write, the keyboard briefly refuses the next transfers while it stores the data.
  Linux reports this as `EPROTO` or `EPIPE`. Retrying after 50–300 ms works.
- One keyboard reset (a USB disconnect and reconnect) happened during a config write while live
  frames were also being sent. Don't mix the two.

## 2.4G receiver: output reports

Every frame is 20 bytes. The keyboard echoes each frame it receives.

```
13  cmd  sub  seq  len  data[14]  sum        sum = (bytes 0–18) mod 256
```

A block is split into 14-byte chunks. `seq` counts the chunks from 0, and `len` is the number of
data bytes in the chunk.

| Action | Frames | Status |
|---|---|---|
| Read config | Send `13 44 01 00 …`. The reply is 10 frames `13 44 0A seq len data…`. | ✅ |
| Write config | 10 frames with cmd `04`, sub `0A` (128 bytes) | ✅ |
| Write palette | 37 frames with cmd `09`, sub `25` (512 bytes) | ✅ |
| Write per-key map | 27 frames with cmd `02`, sub `1C` (378 bytes), then a 6-byte trailer `00 00 5A A5 00 00` | ⚠️ |
| Save | cmd `0A`, sub `01`, data `04 07`. Send it after any write. The F87 Pro doesn't echo this frame. | ✅ |
| Battery | Send `13 4A 00 … 5D`. The reply is `13 4A 01 00 02 <level> <state> … sum`. Level is 1–100. State is `01` on battery or `10` with the cable plugged in; with the cable in, the level always reads 100. | ✅ |
| Live stream | cmd `88` (see below) | ✅ |

Notes:

- Only the config block has a known read command over 2.4G, so the app keeps its own copy of
  the palette and the per-key map.
- A sleeping keyboard doesn't answer anything. Replies are sometimes lost, so retry reads.
- Over 2.4G, the model query isn't available, so the app reports the keyboard as plain "F87".

**Live stream (cmd `0x88`, AULA's "audio dance")** ✅

```
13 88 <fragment count> <seq> <0x10 + N> <N data bytes> … sum
```

- The data is a run of color groups: `R G B count led1 led2 …`. LEDs that aren't listed are off.
- A frame can have at most 14 fragments of 14 bytes.
- The idle (all off) frame is `13 88 01 00 23 00 … BF`.
- Fragments must be at least about 10 ms apart. At 2 ms the animation stutters.
- Like the cable's live frames, these are never saved.

## Config block (128 bytes)

Offsets are within the block. On the cable, the offset in the report is the block offset plus 8.
Over 2.4G, the chunk is `seq = offset // 14` and the frame byte is `5 + offset % 14`.

| Offset | Meaning | Status |
|---|---|---|
| 3 | Unknown (one project calls it debounce). Leave it unchanged. | ⚠️ |
| 9 | Per-key flag: `1` together with effect 18 shows the per-key map | ✅ |
| 10 | Current effect number (see the table below) | ✅ |
| 12 | Color mode: `1` = palette or rainbow, `3` = factory colors. The app writes `1`. | ⚠️ |
| 18 | Side lights effect: 0 off, 1 rainbow wave, 2 rainbow all together, 3 solid, 4 breathing | ✅ |
| 19–21 | Side lights color, brightness and speed (probably) | ⚠️ |
| 24 | Sleep timer in 30-second steps (`2` = 1 minute). `0` = never sleep. | ✅ |
| 28 | Light bar above the arrow keys: same effect values as the side lights. Fn + Left Shift cycles it. | ✅ |
| 29 | Light bar color index (`0` red, `2` blue) | ✅ |
| 30–31 | Light bar brightness and speed (probably) | ⚠️ |
| 56 + 2n | Brightness of effect n, 0–4 | ✅ |
| 57 + 2n | Speed of effect n (`speed << 4`, speed 0–4) combined with the color slot (low nibble: 0–6 = palette slot, 7 = rainbow) | ✅ |
| 126–127 | `5A A5` end marker | ✅ |

**About the light bar.** The keyboard doesn't reliably apply host writes to offsets 28–29. They
took effect once and were ignored in later tries, while Fn + Left Shift always works. The bar
also ignores live frames: every LED position from 0 to 255 was tested, over both the cable and
2.4G. So it can't follow music.

## Effect numbers

| # | Name | Speed | Color |
|---|---|---|---|
| 0 | Off | | |
| 1 | Static | | ✓ |
| 2 | Breathing | ✓ | ✓ |
| 3 | Rainbow wave | ✓ | rainbow only |
| 4 | Flash away | ✓ | ✓ |
| 5 | Raindrops | ✓ | ✓ |
| 7 | Ripples | ✓ | ✓ |
| 8 | Twinkling stars | ✓ | ✓ |
| 10 | Retro snake | ✓ | ✓ |
| 11 | Neon stream | ✓ | ✓ |
| 12 | Reactive (lights the pressed key) | ✓ | ✓ |
| 13 | Sine wave | ✓ | ✓ |
| 15 | Rotating windmill | ✓ | rainbow only |
| 16 | Colorful waterfall | ✓ | rainbow only |
| 17 | Blossoming | ✓ | rainbow only |
| 18 | Custom per-key (needs config offset 9 = 1) | | |

Effects 6, 9 and 14 are in AULA's list but misbehave, so the app leaves them out. Newer F87
boards use effect 21 for per-key colors, but on the F87 Pro effect 21 turns the LEDs off.

## Palette block (512 bytes)

- Effect n has 7 RGB color slots, starting at byte `21 × n`.
- The factory colors are red, green, blue, yellow, magenta, cyan and white.
- The app puts a custom color in slot 0 and selects slot 0 in the effect's config byte.
- Bytes 506–507 hold the `5A A5` end marker.

## Per-key block (378 bytes)

The block holds three planes of 126 bytes, indexed by LED number: red at 0–125, green at
126–251, blue at 252–377.

## LED numbers (ANSI TKL)

LEDs are numbered in columns of six, top to bottom. Gaps in the layout skip numbers.

| Row | Keys (LED number) |
|---|---|
| F-row | Esc 0, F1 12, F2 18, F3 24, F4 30, F5 36, F6 42, F7 48, F8 54, F9 60, F10 66, F11 72, F12 78, PrtSc 84, ScrLk 90, Pause 96 |
| Number | \` 1, 1 7, 2 13, 3 19, 4 25, 5 31, 6 37, 7 43, 8 49, 9 55, 0 61, - 67, = 73, Backspace 79, Ins 85, Home 91, PgUp 97 |
| Top | Tab 2, Q 8, W 14, E 20, R 26, T 32, Y 38, U 44, I 50, O 56, P 62, [ 68, ] 74, \\ 80, Del 86, End 92, PgDn 98 |
| Home | Caps 3, A 9, S 15, D 21, F 27, G 33, H 39, J 45, K 51, L 57, ; 63, ' 69, Enter 81 |
| Shift | LShift 4, Z 10, X 16, C 22, V 28, B 34, N 40, M 46, , 52, . 58, / 64, RShift 82, Up 94 |
| Bottom | LCtrl 5, Win 11, LAlt 17, Space 35, RAlt 53, Fn 59, Menu 65, RCtrl 83, Left 89, Down 95, Right 101 |
