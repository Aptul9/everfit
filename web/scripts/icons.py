"""Render the app icon (the kcal ring on the app background) to PNG, standard library only.

    python web/scripts/icons.py        web icons and the Android launcher, maskable and splash images
"""

import math
import struct
import zlib
from pathlib import Path

BG = (10, 12, 15)
A = (212, 250, 124)
B = (123, 227, 176)
TRACK = (26, 31, 38)
ARC = 0.72
ROOT = Path(__file__).resolve().parents[2]


def mix(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2, strict=True))


def render(size: int, outer: float = 0.34, inner: float = 0.24) -> bytes:
    ss = 3
    cx = cy = size / 2
    r_out, r_in = size * outer, size * inner
    mid, cap = (r_in + r_out) / 2, (r_out - r_in) / 2
    ends = [(math.sin(a) * mid, -math.cos(a) * mid, c) for a, c in ((0.0, A), (ARC * 2 * math.pi, B))]
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            acc = [0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss - cx
                    py = y + (sy + 0.5) / ss - cy
                    d = math.hypot(px, py)
                    col = BG
                    if r_in <= d <= r_out:
                        frac = ((math.atan2(px, -py) + 2 * math.pi) % (2 * math.pi)) / (2 * math.pi)
                        col = mix(A, B, frac / ARC) if frac <= ARC else TRACK
                    for ex, ey, c in ends:
                        if math.hypot(px - ex, py - ey) <= cap:
                            col = c
                    for i in range(3):
                        acc[i] += col[i]
            row += bytes(round(v / ss / ss) for v in acc)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


if __name__ == "__main__":
    for s in (192, 512):
        write(ROOT / "web" / "public" / f"icon-{s}.png", render(s))
    res = ROOT / "android" / "app" / "src" / "main" / "res"
    for density, k in (("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)):
        write(res / f"mipmap-{density}" / "ic_launcher.png", render(round(48 * k)))
        # adaptive icon layer: the ring stays inside the 66% safe zone of the 108 dp canvas
        write(res / f"mipmap-{density}" / "ic_maskable.png", render(round(108 * k), 0.25, 0.177))
        write(res / f"drawable-{density}" / "splash.png", render(round(300 * k), 0.3, 0.21))
