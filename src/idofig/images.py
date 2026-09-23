"""The natural size of an image panel's file, read from its header — no imaging library.

An image panel (a hand drawing, a micrograph, a scheme from another program) is placed
as it is. To place it without distortion idofig needs its aspect ratio, and that is in
the first bytes of every format it accepts.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

IMAGE_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def natural_size(path: Path | str) -> tuple[float, float] | None:
    """Width and height in the file's own units (pixels, or SVG user units/points); None when unreadable."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".svg":
            return _svg(path.read_text(encoding="utf-8", errors="replace")[:4096])
        data = path.read_bytes()[:65536]
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return float(w), float(h)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return float(w), float(h)
    if data[:2] == b"\xff\xd8":
        return _jpeg(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data)
    return None


def _svg(head: str) -> tuple[float, float] | None:
    m = re.search(r"<svg\b([^>]*)>", head, re.S)
    if not m:
        return None
    attrs = m.group(1)
    vb = re.search(r'viewBox\s*=\s*"([^"]+)"', attrs)
    if vb:
        parts = [float(x) for x in re.split(r"[\s,]+", vb.group(1).strip()) if x]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return parts[2], parts[3]
    w = re.search(r'\bwidth\s*=\s*"([\d.]+)', attrs)
    h = re.search(r'\bheight\s*=\s*"([\d.]+)', attrs)
    if w and h and float(w.group(1)) > 0 and float(h.group(1)) > 0:
        return float(w.group(1)), float(h.group(1))
    return None


def _jpeg(data: bytes) -> tuple[float, float] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return float(w), float(h)
        i += 2 + length
    return None


def _webp(data: bytes) -> tuple[float, float] | None:
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        w, h = struct.unpack("<HH", data[26:30])
        return float(w & 0x3FFF), float(h & 0x3FFF)
    if chunk == b"VP8L" and len(data) >= 25:
        b = data[21:25]
        w = 1 + (((b[1] & 0x3F) << 8) | b[0])
        h = 1 + (((b[3] & 0x0F) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
        return float(w), float(h)
    if chunk == b"VP8X" and len(data) >= 30:
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return float(w), float(h)
    return None
