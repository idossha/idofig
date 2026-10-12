"""What a panel's data marks drew, for a consumer that animates or queries them (0.10.0).

Four things go into the manifest (SPEC.md, manifest.json, *Data*), none into a source file:

* ``data`` on a data mark's part: what it drew — a line's or a scatter's x and y, a bar series'
  positions, values, baselines and category keys — as matplotlib holds them after unit
  conversion, up to :data:`DATA_CAP` values (beyond, a range and a sentence saying so);
* ``anchors`` and ``categories`` on an axes: two (data, panel point) pairs per axis, read from
  matplotlib's own data transform, and the category each value of a categorical axis stands for;
* in panel.svg, ``data-index`` (and ``data-value``, ``data-key``) on each bar, and on each mark of
  a scatter or a marker line an id ``<part>.<index>`` — positional, as an index is;
* ``build``: a default reveal order with a suggested entrance per step. idofig animates nothing.

Nothing here changes what is drawn: the SVG gains attributes on elements it already had.
"""

from __future__ import annotations

import html
import math
import re

import numpy as np
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D

from .naming import PartTable

# Values a series carries in the manifest, and marks a series names one by one in panel.svg. A
# 1000-point scatter adds 62 kB to its manifest and 44 kB to its panel.svg (measured, 0.10.0);
# past the cap both would grow without bound for a cloud nobody animates point by point.
DATA_CAP = 1000

# The closed vocabulary of `build` entrances (SPEC.md): a consumer maps each to its own effect.
ENTRANCES = ("fade", "draw-on", "grow", "stagger")

_NONE = {"None", "none", "", " ", None}
_SCAFFOLD = {"background", "spine", "axis", "axis3d", "xlabel", "ylabel", "zlabel", "title",
             "suptitle", "supxlabel", "supylabel", "outline"}
_MARKS = {"line", "collection", "patch", "image"}


def _f(v) -> float | None:
    """A finite float, or None (JSON carries no NaN; a gap in the data is a gap)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _floats(seq) -> list:
    return [_f(v) for v in seq]


def _array(values) -> np.ndarray:
    return np.ma.filled(np.ma.asarray(values, dtype=float), np.nan)


def categories(axis) -> list[str] | None:
    """The category each value of a categorical axis stands for (index = value), or None."""
    from matplotlib.category import UnitData

    units = getattr(axis, "units", None)
    if not isinstance(units, UnitData) or not units._mapping:
        return None
    return [str(k) for k, _ in sorted(units._mapping.items(), key=lambda kv: kv[1])]


def anchors(ax, height_pt: float) -> dict:
    """Two (data, point) pairs per linear or log axis of a flat axes, through matplotlib's data
    transform at 72 dpi (points, y down): ``{"x": [[x0, px0], [x1, px1]], "y": …}``."""
    if getattr(ax, "name", None) != "rectilinear":
        return {}
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    out = {}
    if ax.get_xscale() in ("linear", "log"):
        a, b = ax.transData.transform([(x0, y0), (x1, y0)])
        out["x"] = [[float(x0), round(float(a[0]), 3)], [float(x1), round(float(b[0]), 3)]]
    if ax.get_yscale() in ("linear", "log"):
        a, b = ax.transData.transform([(x0, y0), (x0, y1)])
        out["y"] = [[float(y0), round(height_pt - float(a[1]), 3)], [float(y1), round(height_pt - float(b[1]), 3)]]
    return out


def _xy(kind: str, x: np.ndarray, y: np.ndarray, values: np.ndarray | None) -> dict:
    n = len(x)
    d: dict = {"kind": kind, "n": n}
    if n > DATA_CAP:
        d["omitted"] = f"{n} values; the manifest stores at most {DATA_CAP}"
        for key, v in (("x_range", x), ("y_range", y)):
            fin = v[np.isfinite(v)]
            if fin.size:
                d[key] = [float(fin.min()), float(fin.max())]
        return d
    d["x"], d["y"] = _floats(x), _floats(y)
    if values is not None:
        d["values"] = _floats(values)
    return d


def _bars(container, ax) -> dict:
    vertical = getattr(container, "orientation", "vertical") != "horizontal"
    patches = list(container.patches)
    d: dict = {"kind": "bars", "n": len(patches), "orientation": "vertical" if vertical else "horizontal"}
    if len(patches) > DATA_CAP:
        d["omitted"] = f"{len(patches)} bars; the manifest stores at most {DATA_CAP}"
        return d
    if vertical:
        pos = [p.get_x() + p.get_width() / 2 for p in patches]
        d.update(positions=_floats(pos), values=_floats(p.get_height() for p in patches),
                 baselines=_floats(p.get_y() for p in patches))
    else:
        pos = [p.get_y() + p.get_height() / 2 for p in patches]
        d.update(positions=_floats(pos), values=_floats(p.get_width() for p in patches),
                 baselines=_floats(p.get_x() for p in patches))
    # A bar's key is the category it stands on: only when every bar is centred on one, and no
    # two on the same (grouped bars offset by hand from a category have no key, not a guess).
    cats = categories(ax.xaxis if vertical else ax.yaxis)
    if cats:
        keys = []
        for v in pos:
            k = round(v) if math.isfinite(v) else -1
            if not (0 <= k < len(cats) and abs(v - k) < 1e-9):
                break
            keys.append(cats[k])
        if len(keys) == len(patches) and len(set(keys)) == len(keys):
            d["keys"] = keys
    return d


def series_data(part) -> dict | None:
    """What a part drew, or None for a part that is not a line, a scatter or a bar series drawn
    in its axes' data coordinates (an ``axhline`` is half in axes coordinates; a 3D line's
    values are not where it is drawn)."""
    if part.group:
        c = part.container
        ax = c.patches[0].axes if c is not None and len(c.patches) else None
        return _bars(c, ax) if ax is not None else None
    artist = part.artists[0]
    ax = getattr(artist, "axes", None)
    if ax is None or getattr(ax, "name", None) == "3d":
        return None
    if isinstance(artist, Line2D):
        if artist.get_transform() != ax.transData:
            return None
        marked = artist.get_marker() not in _NONE
        if artist.get_linestyle() in _NONE and not marked:
            return None
        xy = _array(artist.get_xydata()).reshape(-1, 2)
        d = _xy("line" if artist.get_linestyle() not in _NONE else "points", xy[:, 0], xy[:, 1], None)
        d["_marks"] = marked
        return d
    if isinstance(artist, PathCollection):
        if artist.get_offset_transform() != ax.transData:
            return None
        off = _array(artist.get_offsets()).reshape(-1, 2)
        arr = artist.get_array()
        values = _array(arr).ravel() if arr is not None and np.size(arr) == len(off) else None
        d = _xy("points", off[:, 0], off[:, 1], values)
        d["_marks"] = True
        return d
    return None


def _num(v) -> str:
    return repr(float(v))


_G = re.compile(r"<g\b[^>]*>|</g>")


def _span(svg: str, name: str) -> tuple[int, int] | None:
    """Where ``<g id="name">`` starts and its matching ``</g>`` ends."""
    start = svg.find(f'<g id="{name}"')
    if start < 0:
        return None
    depth = 0
    for m in _G.finditer(svg, start):
        tag = m.group()
        if tag == "</g>":
            depth -= 1
        elif not tag.endswith("/>"):
            depth += 1
        if depth == 0:
            return start, m.end()
    return None


def _split(svg: str, name: str, d: dict, ids: set[str], taken) -> tuple[str, str | None]:
    """Give each mark a part drew its own id ``<name>.<index>``: the ``<use>`` elements a marker
    line or a scatter draws (or, a scatter whose marks differ in size, its ``<path>`` elements),
    in data order, one per finite point. Returns the SVG and, when the marks were left whole,
    why: matplotlib skips a mark outside the panel, so a count that does not match is never
    guessed at."""
    if d["n"] > DATA_CAP:
        return svg, f"more than {DATA_CAP} marks"
    span = _span(svg, name)
    if span is None:
        return svg, "its group is not in panel.svg (a rasterized part with a positional name)"
    a, b = span
    inner = svg[a:b]
    if "<image" in inner:
        return svg, "it is rasterized: its marks are one image"
    x, y = d["x"], d["y"]
    indices = [i for i in range(d["n"]) if x[i] is not None and y[i] is not None]
    if any(f"{name}.{i}" in ids or f"{name}.{i}" in taken for i in indices):
        return svg, "an id its marks would take is already in panel.svg"
    uses = [m.start() for m in re.finditer(r"<use\b", inner)]
    paths = [m.start() for m in re.finditer(r"<path\b", inner)] if not uses and "<defs" not in inner else []
    found = uses if len(uses) == len(indices) else paths if len(paths) == len(indices) else None
    if found is None:
        return svg, f"panel.svg draws {len(uses) or len(paths)} marks for its {len(indices)} points"
    values = d.get("values")
    out, last = [], 0
    for pos, i in zip(found, indices):
        cut = pos + (4 if inner.startswith("<use", pos) else 5)
        extra = f' data-value="{_num(values[i])}"' if values is not None and values[i] is not None else ""
        out += [inner[last:cut], f' id="{name}.{i}" data-index="{i}"{extra}']
        last = cut
    out.append(inner[last:])
    return svg[:a] + "".join(out) + svg[b:], None


def _tag_bars(svg: str, table: PartTable, part, d: dict) -> str:
    """``data-index``, ``data-value`` and ``data-key`` on each bar's own ``<g>``."""
    if "values" not in d:
        return svg
    keys = d.get("keys")
    for i, patch in enumerate(part.container.patches):
        name = table.by_artist.get(id(patch))
        if name is None:
            continue
        attrs = f' data-index="{i}"'
        if d["values"][i] is not None:
            attrs += f' data-value="{_num(d["values"][i])}"'
        if keys:
            attrs += f' data-key="{html.escape(keys[i], quote=True)}"'
        tag = f'<g id="{name}"'
        svg = svg.replace(tag, tag + attrs, 1)
    return svg


def annotate(svg: str, table: PartTable, parts: dict) -> str:
    """Put ``data`` on each data mark's manifest entry, and its marks' attributes in ``svg``."""
    ids = set(re.findall(r'\bid="([^"]+)"', svg))
    for name, part in table.parts.items():
        d = series_data(part)
        if d is None:
            continue
        marks = d.pop("_marks", False)
        if part.group:
            svg = _tag_bars(svg, table, part, d)
        elif marks:
            svg, why = _split(svg, name, d, ids, table.parts)
            d["addressable"] = why is None
            if why:
                d["why"] = why
        parts[name]["data"] = d
    return svg


def _entrance(entry: dict) -> str:
    d = entry.get("data") or {}
    if d.get("kind") == "bars":
        return "grow"
    if d.get("kind") == "points":
        return "stagger" if d.get("addressable") else "fade"
    if d.get("kind") == "line" or (not entry.get("group") and entry["kind"] == "line"):
        return "draw-on"
    return "fade"


def build_steps(fig, table: PartTable, parts: dict) -> list[dict]:
    """The default reveal order: every axes' scaffold, then the grid, then each data series in
    the order matplotlib draws it (zorder, then the order it was added), then legends and
    colorbars, then free text. Each step names parts (or groups) of the manifest; the figure's
    background and what is drawn inside a listed part (tick labels in an axis, entries in a
    legend, a group's members) are in no step of their own."""
    order = {id(ax): k for k, ax in enumerate(fig.axes)}
    by_name = {table.axes_names[id(ax)]: ax for ax in fig.axes if id(ax) in table.axes_names}
    child = {id(a): k for ax in fig.axes for k, a in enumerate(ax.get_children())}
    grouped = {m for p in table.parts.values() if p.group and p.role in ("series", "grid") for m in p.members}

    def artists(part):
        return [a for m in part.members for a in table.parts[m].artists] if part.group else part.artists

    def axes_of(part):
        # By the name's parent: an axes' background and axis labels have no `.axes` of their own.
        return by_name.get(part.parent or "") or getattr(artists(part)[0], "axes", None)

    def key(part):
        arts = artists(part)
        return (order.get(id(axes_of(part)), len(order)), min(a.get_zorder() for a in arts),
                min(child.get(id(a), 0) for a in arts))

    stages: dict[str, list] = {"scaffold": [], "grid": [], "data": [], "legend": [], "annotation": []}
    for name, part in table.parts.items():
        arts = artists(part)
        if name in grouped or name == "figure.background" or not arts:
            continue
        if not any(getattr(a, "_idofig_drawn", False) for a in arts):
            continue
        ax = axes_of(part)
        role, kind = part.role, part.kind
        if role == "colorbar":
            stages["legend"].append(part)
        elif getattr(ax, "_colorbar", None) is not None:
            continue  # drawn inside its colorbar, which is a step of its own
        elif role == "legend":
            stages["legend"].append(part)
        elif role == "grid":
            stages["grid"].append(part)
        elif role in _SCAFFOLD:
            stages["scaffold"].append(part)
        elif role in ("series", "mesh") or role in _MARKS or (role == "author" and kind in _MARKS):
            stages["data"].append(part)
        elif role == "text" or (role == "author" and kind == "text"):
            stages["annotation"].append(part)
    steps = []
    for stage in ("scaffold", "grid"):
        if stages[stage]:
            names = [p.name for p in sorted(stages[stage], key=lambda p: key(p)[0])]
            steps.append({"stage": stage, "parts": names, "entrance": "fade"})
    for stage in ("data", "legend", "annotation"):
        for p in sorted(stages[stage], key=key):
            steps.append({"stage": stage, "parts": [p.name], "entrance": _entrance(parts[p.name])})
    return steps
