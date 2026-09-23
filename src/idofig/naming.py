"""Stable, meaningful names for the parts of a matplotlib figure.

Every part a canvas or an agent may address gets a name derived from what it *is*,
not from where it happens to be in the drawing, so the name survives new data, a new
matplotlib version and a reworked layout. The grammar (inspired by fluxplot):

====================================  ==============================================  ============
Part                                  Name                                            Stability
====================================  ==============================================  ============
axes                                  ``idofig.name(ax, "main")`` → ``main``,          named /
                                      otherwise ``ax0``, ``ax1`` …                     positional
titles, axis labels                   ``main.title``, ``main.xlabel``, ``main.ylabel``  semantic
a labelled line/scatter/bar series    ``main.series.<label>``                          semantic
one bar of a labelled bar series      ``main.series.<label>.<row>``                    positional
tick labels                           ``main.xtick.<text>``                            semantic
legend and its entries                ``main.legend``, ``main.legend.<label>``         semantic
spines, axis, background              ``main.spine.left``, ``main.xaxis``,             semantic
                                      ``main.background``
free text                             ``main.text.<text>``                             semantic
colorbar (``idofig.colorbar``)        ``cbar.<name>`` (its axes), ``cbar.<name>.solids`` named
unlabelled artists                    ``main.line0``, ``main.patch3`` …                 positional
====================================  ==============================================  ============

An author ``gid`` always wins. Two author gids that collide are an error; derived names
that collide become positional (``…​.2``) and are reported, never silently merged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.axis import Axis
from matplotlib.collections import Collection
from matplotlib.container import BarContainer, Container, ErrorbarContainer, StemContainer
from matplotlib.figure import Figure
from matplotlib.image import _ImageBase
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.spines import Spine
from matplotlib.text import Text

from .errors import NameCollisionError

AUTO = "_idofig_auto"


def slug(text: Any, limit: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).strip().lower()).strip("-")
    return (s[:limit].rstrip("-")) or "unnamed"


def kind_of(artist: Any) -> str | None:
    if isinstance(artist, Spine):
        return "spine"
    if isinstance(artist, Legend):
        return "legend"
    if isinstance(artist, Text):
        return "text"
    if isinstance(artist, Line2D):
        return "line"
    if isinstance(artist, Patch):
        return "patch"
    if isinstance(artist, Collection):
        return "collection"
    if isinstance(artist, _ImageBase):
        return "image"
    if isinstance(artist, Axes):
        return "axes"
    if isinstance(artist, Axis):
        return "axis"
    return None


@dataclass
class Part:
    name: str
    artists: list
    kind: str
    role: str
    stability: str
    parent: str | None = None
    group: bool = False
    members: list[str] = field(default_factory=list)


class PartTable:
    """Names → parts, in the order they were assigned (which is deterministic)."""

    def __init__(self) -> None:
        self.parts: dict[str, Part] = {}
        self.by_artist: dict[int, str] = {}
        self.warnings: list[str] = []
        self.axes_names: dict[int, str] = {}

    def __contains__(self, name: str) -> bool:
        return name in self.parts

    def claimed(self, artist: Any) -> bool:
        return id(artist) in self.by_artist

    def _free(self, name: str) -> str:
        if name not in self.parts:
            return name
        n = 2
        while f"{name}.{n}" in self.parts:
            n += 1
        return f"{name}.{n}"

    def add(self, name: str, artist: Any, role: str, stability: str, parent: str | None = None,
            *, kind: str | None = None, author: bool = False) -> str | None:
        kind = kind or kind_of(artist)
        if kind is None or self.claimed(artist):
            return self.by_artist.get(id(artist))
        if name in self.parts:
            if author:
                raise NameCollisionError(f"two parts both have the gid {name!r}; gids must be unique in a panel")
            new = self._free(name)
            self.warnings.append(f"name {name!r} is taken; this part was named {new!r} (positional)")
            name, stability = new, "positional"
        self.parts[name] = Part(name, [artist], kind, role, stability, parent)
        self.by_artist[id(artist)] = name
        if not author:
            artist.set_gid(name)
            setattr(artist, AUTO, True)
        return name

    def add_group(self, name: str, members: list[str], role: str, stability: str, parent: str | None) -> None:
        if name in self.parts or not members:
            return
        kinds = {self.parts[m].kind for m in members}
        artists = [a for m in members for a in self.parts[m].artists]
        self.parts[name] = Part(name, artists, kinds.pop() if len(kinds) == 1 else "mixed", role, stability,
                                parent, group=True, members=list(members))


def _author_gid(artist: Artist) -> str | None:
    gid = artist.get_gid()
    if gid and not getattr(artist, AUTO, False):
        return str(gid)
    return None


def _label(artist: Any) -> str | None:
    lab = artist.get_label() if hasattr(artist, "get_label") else None
    if isinstance(lab, str) and lab and not lab.startswith("_"):
        return lab
    return None


def _is_colorbar_axes(ax: Axes) -> bool:
    return getattr(ax, "_colorbar", None) is not None


def assign_structural(fig: Figure) -> PartTable:
    """Name everything that exists before the first draw (ticks come later)."""
    t = PartTable()

    # Author gids first: they are claims the author made, and they win.
    seen: dict[str, Artist] = {}
    for artist in fig.findobj(include_self=False):
        gid = _author_gid(artist)
        if gid is None or kind_of(artist) is None:
            continue
        if gid in seen and seen[gid] is not artist:
            raise NameCollisionError(
                f"two parts both have the gid {gid!r} ({type(seen[gid]).__name__} and "
                f"{type(artist).__name__}); gids must be unique in a panel"
            )
        seen[gid] = artist
        t.add(gid, artist, "author", "author", author=True)

    t.add("figure.background", fig.patch, "background", "semantic")
    for attr, name in (("_suptitle", "suptitle"), ("_supxlabel", "supxlabel"), ("_supylabel", "supylabel")):
        text = getattr(fig, attr, None)
        if text is not None and text.get_text():
            t.add(name, text, name, "semantic")
    for text in fig.texts:
        if text.get_text():
            t.add(f"text.{slug(text.get_text())}", text, "text", "semantic")
    for k, legend in enumerate(fig.legends):
        _name_legend(t, legend, "legend" if k == 0 else f"legend{k + 1}", None)

    index = 0
    cbar_index = 0
    for ax in fig.axes:
        if _author_gid(ax):
            name = _author_gid(ax)
        elif getattr(ax, "_idofig_name", None):
            name = ax._idofig_name
            t.add(name, ax, "axes", "named", kind="axes")
        elif _is_colorbar_axes(ax):
            cbar = ax._colorbar
            given = getattr(cbar, "_idofig_name", None)
            name = f"cbar.{given}" if given else f"cbar{cbar_index}"
            cbar_index += 1
            t.add(name, ax, "colorbar", "named" if given else "positional", kind="axes")
        else:
            name = f"ax{index}"
            t.add(name, ax, "axes", "positional", kind="axes")
        if not _is_colorbar_axes(ax):
            index += 1
        t.axes_names[id(ax)] = name
        _name_axes_contents(t, ax, name)
    return t


def _name_legend(t: PartTable, legend: Legend, name: str, parent: str | None) -> None:
    t.add(name, legend, "legend", "semantic", parent)
    frame = legend.get_frame()
    if frame is not None:
        t.add(f"{name}.frame", frame, "legend-frame", "semantic", name)
    for text in legend.get_texts():
        if text.get_text():
            t.add(f"{name}.{slug(text.get_text())}", text, "legend-entry", "semantic", name)
    title = legend.get_title()
    if title is not None and title.get_text():
        t.add(f"{name}.title", title, "legend-title", "semantic", name)


def _container_members(c: Container) -> list:
    if isinstance(c, BarContainer):
        return list(c.patches)
    if isinstance(c, ErrorbarContainer):
        data_line, caplines, barlinecols = c.lines
        return [a for a in [data_line, *caplines, *barlinecols] if a is not None]
    if isinstance(c, StemContainer):
        stem = c.stemlines
        stems = list(stem) if isinstance(stem, (list, tuple)) else [stem]
        return [a for a in [c.markerline, *stems, c.baseline] if a is not None]
    return [a for a in c if isinstance(a, Artist)]


def _name_axes_contents(t: PartTable, ax: Axes, p: str) -> None:
    t.add(f"{p}.background", ax.patch, "background", "semantic", p)
    for text, suffix in ((ax.title, "title"), (getattr(ax, "_left_title", None), "title-left"),
                         (getattr(ax, "_right_title", None), "title-right")):
        if text is not None and text.get_text():
            t.add(f"{p}.{suffix}", text, "title", "semantic", p)
    for axis, letter in ((ax.xaxis, "x"), (ax.yaxis, "y")):
        if axis.label.get_text():
            t.add(f"{p}.{letter}label", axis.label, f"{letter}label", "semantic", p)
        t.add(f"{p}.{letter}axis", axis, "axis", "semantic", p, kind="axis")
    for side, spine in ax.spines.items():
        t.add(f"{p}.spine.{slug(side)}", spine, "spine", "semantic", p)

    if _is_colorbar_axes(ax):
        cbar = ax._colorbar
        solids = getattr(cbar, "solids", None)
        if solids is not None:
            t.add(f"{p}.solids", solids, "colorbar-solids", "semantic", p)

    # Series: labelled containers, then labelled artists. Duplicate labels become a
    # group addressed by the label, with positional members.
    series: dict[str, list] = {}
    order: list[str] = []
    for c in ax.containers:
        lab = _label(c)
        members = [m for m in _container_members(c) if not t.claimed(m)]
        if lab and members:
            key = slug(lab)
            if key not in series:
                order.append(key)
            series.setdefault(key, []).append(("container", members))
    singles = [*ax.lines, *ax.collections, *ax.patches, *ax.images]
    claimed_by_container = {id(m) for runs in series.values() for kind, ms in runs for m in ms}
    for artist in singles:
        if t.claimed(artist) or id(artist) in claimed_by_container:
            continue
        lab = _label(artist)
        if lab:
            key = slug(lab)
            if key not in series:
                order.append(key)
            series.setdefault(key, []).append(("artist", [artist]))

    for key in order:
        runs = series[key]
        base = f"{p}.series.{key}"
        if len(runs) == 1 and runs[0][0] == "artist":
            t.add(base, runs[0][1][0], "series", "semantic", p)
            continue
        members: list[str] = []
        flat = [m for _, ms in runs for m in ms]
        for row, artist in enumerate(flat):
            n = t.add(f"{base}.{row}", artist, "mark", "positional", base)
            if n:
                members.append(n)
        t.add_group(base, members, "series", "semantic", p)
        if sum(1 for kind, _ in runs if kind == "artist") > 1 or len(runs) > 1:
            t.warnings.append(f"{len(runs)} artists in axes {p!r} share the label {key!r}; they are one group")

    counters = {"line": 0, "collection": 0, "patch": 0, "image": 0}
    prefix = {"line": "line", "collection": "coll", "patch": "patch", "image": "image"}
    for artist in singles:
        if t.claimed(artist):
            continue
        k = kind_of(artist)
        if k not in counters:
            continue
        t.add(f"{p}.{prefix[k]}{counters[k]}", artist, k, "positional", p)
        counters[k] += 1
    for c in ax.containers:  # unlabelled containers' members
        for artist in _container_members(c):
            if not t.claimed(artist):
                k = kind_of(artist)
                if k in counters:
                    t.add(f"{p}.{prefix[k]}{counters[k]}", artist, k, "positional", p)
                    counters[k] += 1

    for text in ax.texts:
        if text.get_text() and not t.claimed(text):
            t.add(f"{p}.text.{slug(text.get_text())}", text, "text", "semantic", p)
    legend = ax.get_legend()
    if legend is not None and not t.claimed(legend):
        _name_legend(t, legend, f"{p}.legend", p)


def tick_slug(text: str) -> str:
    """Tick labels keep their sign: '−0.5' → 'neg-0-5', '0.5' → '0-5'."""
    s = str(text).strip()
    neg = s[:1] in {"-", "−", "‒", "–"}
    body = slug(s[1:] if neg else s)
    return f"neg-{body}" if neg else body


def _drawn_ticks(axis) -> list:
    """The major ticks inside the view (matplotlib also keeps ticks it will not draw)."""
    try:
        drawn = axis._update_ticks()  # the list matplotlib itself draws
        majors = set(map(id, axis.get_major_ticks()))
        return [tk for tk in drawn if id(tk) in majors]
    except Exception:  # private API moved: fall back to every major tick
        return list(axis.get_major_ticks())


def assign_ticks(fig: Figure, t: PartTable) -> None:
    """Name major tick labels by their text. Call after a draw, when ticks exist."""
    for ax in fig.axes:
        p = t.axes_names.get(id(ax))
        if p is None:
            continue
        for axis, letter in ((ax.xaxis, "x"), (ax.yaxis, "y")):
            names: list[str] = []
            for tick in _drawn_ticks(axis):
                for label, suffix in ((tick.label1, "tick"), (tick.label2, "tick2")):
                    if label.get_visible() and label.get_text() and not t.claimed(label):
                        n = t.add(f"{p}.{letter}{suffix}.{tick_slug(label.get_text())}", label, "tick", "semantic", p)
                        if n:
                            names.append(n)
            if names:
                # Both sides: a colorbar draws only label2 (`ytick2.*`), and "all the y tick
                # labels" means those too — a group of the label1 side alone was empty there.
                t.add_group(f"{p}.{letter}tick.*", names, "ticks", "semantic", p)
