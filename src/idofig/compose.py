"""figure.json + panel SVGs → figure.svg. Standard library only; milliseconds per figure.

Panels are placed, never scaled: every panel was drawn at its printed size, so a 7 pt
label in a panel is a 7 pt label in the figure. One user unit is one point.

Output structure (stable ids, so a canvas can address everything)::

    <svg data-idofig-figure="fig-2" viewBox="0 0 W H" width="…mm" height="…mm">
      <rect id="figure.background"/>
      <g id="dose" data-idofig-panel="dose" transform="translate(x y)">  … ids "dose::<part>" …</g>
      <text id="dose.letter" data-idofig-role="letter">a</text>
      <g id="annotations"> <g id="sig-1" data-idofig-annotation="bracket"> … </g> </g>
    </svg>
"""

from __future__ import annotations

import base64
import json
import math
import re
import time
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from . import journals as J
from . import spec as S
from .fsutil import write_atomic
from .mplsetup import SVG_FONT_STACK
from .project import Project
from .units import PT_PER_MM, fmt

_DECL = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.S)
_DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>\s*", re.S)
_ROOT_OPEN = re.compile(r"<svg\b([^>]*)>", re.S)
_ID = re.compile(r'\bid="([^"]+)"')
_VIEWBOX = re.compile(r'viewBox="([^"]+)"')
_WH = re.compile(r'\b(width|height)="([0-9.]+)(pt|px|mm|in)?"')
_UNIT_TO_PT = {None: 0.75, "px": 0.75, "pt": 1.0, "mm": PT_PER_MM, "in": 72.0}
_AT = {"center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0), "left": (0.0, 0.5), "right": (1.0, 0.5),
       "top-left": (0.0, 0.0), "top-right": (1.0, 0.0), "bottom-left": (0.0, 1.0), "bottom-right": (1.0, 1.0)}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
        ".webp": "image/webp"}


@dataclass
class ComposeResult:
    svg: str
    path: Path
    width_mm: float
    height_mm: float
    changed: bool = False
    warnings: list[str] = field(default_factory=list)
    detached: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ms: float = 0.0

    def to_json(self) -> dict:
        return {"path": str(self.path), "width_mm": self.width_mm, "height_mm": self.height_mm,
                "changed": self.changed, "warnings": self.warnings, "detached": self.detached,
                "missing": self.missing, "ms": round(self.ms, 2)}


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def split_svg(text: str) -> tuple[str, str]:
    """(root attributes, inner markup) of an SVG document."""
    text = _DOCTYPE.sub("", _DECL.sub("", text))
    m = _ROOT_OPEN.search(text)
    if not m:
        raise ValueError("not an SVG document")
    end = text.rfind("</svg>")
    return m.group(1), text[m.end(): end if end >= 0 else len(text)]


def namespace_ids(inner: str, prefix: str) -> str:
    """Prefix every id defined in ``inner`` (and every reference to one) with ``prefix::``."""
    ids = set(_ID.findall(inner))
    if not ids:
        return inner

    def id_sub(m: re.Match) -> str:
        return f'id="{prefix}::{m.group(1)}"'

    inner = _ID.sub(id_sub, inner)

    def ref_sub(m: re.Match) -> str:
        target = m.group(2)
        if target in ids:
            return f"{m.group(1)}{prefix}::{target}{m.group(3)}"
        return m.group(0)

    inner = re.sub(r'(url\(#)([^)\s]+)(\))', ref_sub, inner)
    inner = re.sub(r'((?:xlink:)?href="#)([^"]+)(")', ref_sub, inner)
    inner = inner.replace("*{stroke-linejoin", f"#{prefix} *{{stroke-linejoin")
    return inner


def _svg_size_pt(attrs: str) -> tuple[float, float] | None:
    vb = _VIEWBOX.search(attrs)
    if vb:
        parts = [float(x) for x in re.split(r"[\s,]+", vb.group(1).strip())]
        if len(parts) == 4:
            vw, vh = parts[2], parts[3]
            wh = {k: (float(v), u) for k, v, u in _WH.findall(attrs)}
            if "width" in wh and "height" in wh:
                return wh["width"][0] * _UNIT_TO_PT[wh["width"][1] or None], \
                       wh["height"][0] * _UNIT_TO_PT[wh["height"][1] or None]
            return vw, vh
    wh = {k: (float(v), u) for k, v, u in _WH.findall(attrs)}
    if "width" in wh and "height" in wh:
        return wh["width"][0] * _UNIT_TO_PT[wh["width"][1] or None], wh["height"][0] * _UNIT_TO_PT[wh["height"][1] or None]
    return None


def _viewbox(attrs: str) -> tuple[float, float, float, float] | None:
    vb = _VIEWBOX.search(attrs)
    if not vb:
        return None
    parts = [float(x) for x in re.split(r"[\s,]+", vb.group(1).strip())]
    return tuple(parts) if len(parts) == 4 else None  # type: ignore[return-value]


def _text_size(journal: dict) -> float:
    lo, hi = journal.get("minFontPt"), journal.get("maxFontPt")
    v = 7.0
    if lo is not None:
        v = max(v, lo)
    if hi is not None:
        v = min(v, hi)
    return v


class _Anchors:
    def __init__(self, doc: dict, manifests: dict[str, dict]):
        self.places = {p["id"]: p["place"] for p in doc.get("panels", [])}
        self.manifests = manifests

    def resolve(self, a: dict) -> tuple[float, float] | str:
        off = a.get("offset", [0, 0])
        dx, dy = off[0] * PT_PER_MM, off[1] * PT_PER_MM
        if "panel" not in a:
            return a["x"] * PT_PER_MM + dx, a["y"] * PT_PER_MM + dy
        pid = a["panel"]
        place = self.places.get(pid)
        if place is None:
            return f"panel {pid!r} no longer exists"
        ox, oy = place["x"] * PT_PER_MM, place["y"] * PT_PER_MM
        if "part" in a:
            m = self.manifests.get(pid)
            if m is None:
                return f"panel {pid!r} has not been built"
            part = m.get("parts", {}).get(a["part"])
            if part is None:
                return f"part {a['part']!r} is not in panel {pid!r} any more"
            box = part.get("bbox")
            if not box:
                return f"part {a['part']!r} is not drawn"
            x0, y0, x1, y1 = box
            fx, fy = _AT[a.get("at", "center")]
            return ox + x0 + fx * (x1 - x0) + dx, oy + y0 + fy * (y1 - y0) + dy
        if "data" in a:
            m = self.manifests.get(pid)
            if m is None:
                return f"panel {pid!r} has not been built"
            ax = m.get("axes", {}).get(a["axes"])
            if ax is None:
                return f"axes {a['axes']!r} is not in panel {pid!r} any more"
            bx0, by0, bx1, by1 = ax["bbox"]
            fx = _frac(a["data"][0], ax["xlim"], ax["xscale"])
            fy = _frac(a["data"][1], ax["ylim"], ax["yscale"])
            if isinstance(fx, str):
                return fx
            if isinstance(fy, str):
                return fy
            return ox + bx0 + fx * (bx1 - bx0) + dx, oy + by1 - fy * (by1 - by0) + dy
        return ox + a["x"] * PT_PER_MM + dx, oy + a["y"] * PT_PER_MM + dy


def _frac(v: float, lim: list[float], scale: str) -> float | str:
    lo, hi = lim
    if scale == "linear":
        return (v - lo) / (hi - lo) if hi != lo else 0.0
    if scale == "log":
        if v <= 0 or lo <= 0 or hi <= 0:
            return "a log-axis anchor must be positive"
        return (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    return f"anchoring to data on a {scale!r} axis is not supported"


def _style(a: dict, journal: dict) -> dict:
    s = {"color": "#000000", "width_pt": 0.75, "size_pt": _text_size(journal), "weight": "normal",
         "fill": "none", "gap_mm": 0.8, "leg_mm": 1.0}
    s.update(a.get("style", {}))
    return s


def _font(size: float, weight: str, color: str) -> str:
    w = "700" if weight == "bold" else "400"
    return f"font-family: {SVG_FONT_STACK}; font-size: {fmt(size)}px; font-weight: {w}; fill: {color}"


def _arrowhead(x1: float, y1: float, x2: float, y2: float, size: float, color: str) -> str:
    ang = math.atan2(y2 - y1, x2 - x1)
    back = size
    half = size * 0.45
    bx, by = x2 - back * math.cos(ang), y2 - back * math.sin(ang)
    px, py = -math.sin(ang), math.cos(ang)
    pts = [(x2, y2), (bx + half * px, by + half * py), (bx - half * px, by - half * py)]
    d = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in pts)
    return f'<polygon points="{d}" style="fill: {color}; stroke: none"/>'


def _render_annotation(a: dict, anchors: _Anchors, journal: dict) -> tuple[str | None, str | None]:
    s = _style(a, journal)
    aid = escape(a["id"])
    t = a["type"]
    color = s["color"]
    if t == "text":
        p = anchors.resolve(a["at"])
        if isinstance(p, str):
            return None, p
        anchor = a.get("align", "start")
        rot = s.get("rotate")
        transform = f' transform="rotate({fmt(rot)} {fmt(p[0])} {fmt(p[1])})"' if rot else ""
        return (f'<text id="{aid}" data-idofig-annotation="text" x="{fmt(p[0])}" y="{fmt(p[1])}"{transform} '
                f'style="{_font(s["size_pt"], s["weight"], color)}; text-anchor: {anchor}">{escape(a["text"])}</text>'), None
    p1 = anchors.resolve(a["from"])
    p2 = anchors.resolve(a["to"])
    for p in (p1, p2):
        if isinstance(p, str):
            return None, p
    (x1, y1), (x2, y2) = p1, p2  # type: ignore[misc]
    w = s["width_pt"]
    stroke = f"fill: none; stroke: {color}; stroke-width: {fmt(w)}; stroke-linecap: butt; stroke-linejoin: miter"
    if s.get("dash"):
        stroke += "; stroke-dasharray: " + " ".join(fmt(x) for x in s["dash"])
    if t in {"arrow", "line"}:
        head = a.get("head", "end" if t == "arrow" else "none")
        size = max(3.0, w * 5)
        sx1, sy1, sx2, sy2 = x1, y1, x2, y2
        L = math.hypot(x2 - x1, y2 - y1) or 1.0
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        parts = []
        if head in {"end", "both"}:
            sx2, sy2 = x2 - ux * size * 0.8, y2 - uy * size * 0.8
            parts.append(_arrowhead(x1, y1, x2, y2, size, color))
        if head in {"start", "both"}:
            sx1, sy1 = x1 + ux * size * 0.8, y1 + uy * size * 0.8
            parts.append(_arrowhead(x2, y2, x1, y1, size, color))
        line = f'<path d="M {fmt(sx1)} {fmt(sy1)} L {fmt(sx2)} {fmt(sy2)}" style="{stroke}"/>'
        return f'<g id="{aid}" data-idofig-annotation="{t}">{line}{"".join(parts)}</g>', None
    if t == "bracket":
        gap = s["gap_mm"] * PT_PER_MM
        leg = s["leg_mm"] * PT_PER_MM
        # Both legs are `leg_mm` long and the bar clears the outer anchor by `gap_mm`: the
        # significance-bracket convention. Legs that reached down to each anchor drew a long
        # line into the short bar of an unequal pair and read as a data mark.
        if a.get("side", "above") == "above":
            ybar = min(y1, y2) - gap - leg
            ly = ybar - 1.0
        else:
            ybar = max(y1, y2) + gap + leg
            ly = ybar + s["size_pt"]
        yleg = ybar + leg if a.get("side", "above") == "above" else ybar - leg
        d = f"M {fmt(x1)} {fmt(yleg)} L {fmt(x1)} {fmt(ybar)} L {fmt(x2)} {fmt(ybar)} L {fmt(x2)} {fmt(yleg)}"
        label = ""
        if a.get("label"):
            label = (f'<text x="{fmt((x1 + x2) / 2)}" y="{fmt(ly)}" style="{_font(s["size_pt"], s["weight"], color)}; '
                     f'text-anchor: middle">{escape(a["label"])}</text>')
        return f'<g id="{aid}" data-idofig-annotation="bracket"><path d="{d}" style="{stroke}"/>{label}</g>', None
    if t == "box":
        x, y = min(x1, x2), min(y1, y2)
        fill = s["fill"]
        style = stroke.replace("fill: none", f"fill: {fill}")
        return (f'<rect id="{aid}" data-idofig-annotation="box" x="{fmt(x)}" y="{fmt(y)}" '
                f'width="{fmt(abs(x2 - x1))}" height="{fmt(abs(y2 - y1))}" style="{style}"/>'), None
    return None, f"unknown annotation type {t!r}"


def compose(project: Project, figure_id: str, *, write: bool = True) -> ComposeResult:
    t0 = time.perf_counter()
    doc = S.load_figure(project.figure_json(figure_id))
    journal = J.load(doc.get("journal") or project.journal, str(project.root))
    width_mm = J.width_mm(journal, doc["width"])
    letters = J.letter_style(journal, doc.get("letters"))
    out_path = project.figure_dir(figure_id) / "figure.svg"
    warnings: list[str] = []
    missing: list[str] = []
    manifests: dict[str, dict] = {}
    body: list[str] = []

    panels = doc.get("panels", [])
    if doc.get("height"):
        height_mm = float(doc["height"]["mm"])
    else:
        height_mm = max([p["place"]["y"] + p["place"]["h"] for p in panels] or [50.0])
    W, H = width_mm * PT_PER_MM, height_mm * PT_PER_MM

    for pn in panels:
        pid = pn["id"]
        place = pn["place"]
        x, y = place["x"] * PT_PER_MM, place["y"] * PT_PER_MM
        if place["x"] + place["w"] > width_mm + 0.01:
            warnings.append(f"panel {pid!r} extends past the figure's {fmt(width_mm)} mm width")
        if "image" in pn:
            src = (project.root / pn["image"]).resolve()
            if not src.is_file() or project.root not in src.parents:
                missing.append(pid)
                warnings.append(f"image panel {pid!r}: {pn['image']} not found")
                continue
            body.append(_image_panel(pid, src, x, y, place))
            continue
        pdir = project.panel_dir(figure_id, pid)
        svg = _read(pdir / "panel.svg")
        man = _read(pdir / "manifest.json")
        if svg is None:
            missing.append(pid)
            continue
        if man is not None:
            try:
                manifests[pid] = json.loads(man)
            except ValueError:
                warnings.append(f"panel {pid!r}: manifest.json is not valid JSON")
        attrs, inner = split_svg(svg)
        size = _svg_size_pt(attrs)
        if size is not None:
            dw = abs(size[0] - place["w"] * PT_PER_MM) / PT_PER_MM
            dh = abs(size[1] - place["h"] * PT_PER_MM) / PT_PER_MM
            if dw > 0.05 or dh > 0.05:
                warnings.append(
                    f"panel {pid!r} was drawn at {fmt(size[0] / PT_PER_MM, 1)}×{fmt(size[1] / PT_PER_MM, 1)} mm "
                    f"but is placed as {fmt(place['w'], 1)}×{fmt(place['h'], 1)} mm; rebuild it"
                )
        body.append(
            f'<g id="{pid}" data-idofig-panel="{pid}" transform="translate({fmt(x)} {fmt(y)})">'
            f"{namespace_ids(inner, pid)}</g>"
        )

    if letters.get("show", True):
        size = float(letters["size_pt"])
        ox, oy = (v * PT_PER_MM for v in letters.get("offset_mm", [0, 0]))
        for pn in panels:
            letter = pn.get("letter")
            if not letter:
                continue
            text = J.format_letter(letter, letters)
            lx = pn["place"]["x"] * PT_PER_MM + ox
            ly = pn["place"]["y"] * PT_PER_MM + oy + size * 0.74
            body.append(
                f'<text id="{pn["id"]}.letter" data-idofig-role="letter" x="{fmt(lx)}" y="{fmt(ly)}" '
                f'style="{_font(size, letters.get("weight", "bold"), "#000000")}">{escape(text)}</text>'
            )

    anchors = _Anchors(doc, manifests)
    ann_out = []
    detached = []
    for a in doc.get("annotations", []):
        markup, problem = _render_annotation(a, anchors, journal)
        if problem:
            detached.append({"id": a["id"], "reason": problem})
        elif markup:
            ann_out.append(markup)
    if ann_out:
        body.append('<g id="annotations">' + "".join(ann_out) + "</g>")

    svg = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
        f'width="{fmt(width_mm)}mm" height="{fmt(height_mm)}mm" viewBox="0 0 {fmt(W)} {fmt(H)}" '
        f'data-idofig-figure="{escape(figure_id)}">\n'
        f'<rect id="figure.background" data-idofig-role="background" x="0" y="0" width="{fmt(W)}" height="{fmt(H)}" '
        'style="fill: #ffffff"/>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )
    changed = False
    if write:
        old = _read(out_path)
        if old != svg:
            write_atomic(out_path, svg)
            changed = True
    return ComposeResult(svg=svg, path=out_path, width_mm=width_mm, height_mm=height_mm, changed=changed,
                         warnings=warnings, detached=detached, missing=missing,
                         ms=(time.perf_counter() - t0) * 1000)


def _image_panel(pid: str, src: Path, x: float, y: float, place: dict) -> str:
    w, h = place["w"] * PT_PER_MM, place["h"] * PT_PER_MM
    if src.suffix.lower() == ".svg":
        attrs, inner = split_svg(src.read_text(encoding="utf-8"))
        vb = _viewbox(attrs)
        size = _svg_size_pt(attrs)
        if vb is None and size is not None:
            vb = (0.0, 0.0, size[0], size[1])
        if vb is None:
            vb = (0.0, 0.0, w, h)
        s = min(w / vb[2], h / vb[3]) if vb[2] and vb[3] else 1.0
        tx = x - vb[0] * s + (w - vb[2] * s) / 2
        ty = y - vb[1] * s + (h - vb[3] * s) / 2
        return (f'<g id="{pid}" data-idofig-panel="{pid}" data-idofig-image="svg" '
                f'transform="translate({fmt(tx)} {fmt(ty)}) scale({fmt(s, 6)})">{namespace_ids(inner, pid)}</g>')
    mime = MIME.get(src.suffix.lower(), "application/octet-stream")
    data = base64.b64encode(src.read_bytes()).decode("ascii")
    return (f'<image id="{pid}" data-idofig-panel="{pid}" data-idofig-image="raster" x="{fmt(x)}" y="{fmt(y)}" '
            f'width="{fmt(w)}" height="{fmt(h)}" preserveAspectRatio="xMidYMid meet" '
            f'xlink:href="data:{mime};base64,{data}"/>')
