#!/usr/bin/env python3
"""Build installer/sectorloom.ico from the site's logo.

The wordmark is unreadable at 16 px, so the icon uses the logo's own
trace-and-ticks motif inside the same gold frame.

Sizes up to 128 are written as uncompressed BMP and only 256 as PNG.
That is the layout Windows has always understood; a PNG-only .ico is
accepted by modern Windows but has a history of upsetting the resource
writers in packaging tools, and there is nothing to gain by risking it.

    python3 installer/make_icon.py ../lapwise/img/logo.webp
"""
import io
import os
import struct
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(HERE)), "lapwise", "img", "logo.webp")
OUT = os.path.join(HERE, "sectorloom.ico")
GOLD = (210, 164, 41, 255)
SIZES = [16, 24, 32, 48, 64, 128, 256]


def master():
    src = Image.open(LOGO).convert("RGBA")
    motif = src.crop((670, 22, 858, 114)).copy()
    # the crop clips the frame's corner; drop the gold so only the
    # trace and the red ticks come across
    px = motif.load()
    for x in range(motif.width):
        for y in range(motif.height):
            r, g, b, a = px[x, y]
            if a and r > 150 and 110 < g < 215 and b < 120 and r > b + 60:
                px[x, y] = (0, 0, 0, 0)
    motif = motif.crop(motif.getbbox())

    S = 256
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(icon).rounded_rectangle(
        [10, 10, S - 11, S - 11], radius=44,
        fill=(255, 255, 255, 255), outline=GOLD, width=11)
    inner = S - 2 * 21 - 22
    sc = min(inner / motif.width, inner / motif.height)
    m = motif.resize((round(motif.width * sc), round(motif.height * sc)), Image.LANCZOS)
    icon.alpha_composite(m, ((S - m.width) // 2, (S - m.height) // 2))
    return icon


def bmp_entry(im):
    """A 32-bit BMP as an .ico stores it: no file header, doubled
    height for the AND mask, rows bottom-up."""
    w, h = im.size
    px = im.load()
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)
    mask_stride = ((w + 31) // 32) * 4          # 1bpp, padded to 4 bytes
    and_mask = b"\x00" * (mask_stride * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + xor + and_mask


def main():
    icon = master()
    entries = []
    for s in SIZES:
        im = icon.resize((s, s), Image.LANCZOS)
        if s == 256:
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            entries.append((s, buf.getvalue()))
        else:
            entries.append((s, bmp_entry(im)))

    out = bytearray(struct.pack("<HHH", 0, 1, len(entries)))
    offset = 6 + 16 * len(entries)
    for s, blob in entries:
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32,
                           len(blob), offset)
        offset += len(blob)
    for _, blob in entries:
        out += blob
    open(OUT, "wb").write(bytes(out))
    print(f"{OUT}  {len(entries)} sizes  {len(out) // 1024} KB")


if __name__ == "__main__":
    main()
