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
drawn major gridlines (0.10.0)        ``main.xgrid.<tick text>``, group                semantic
                                      ``main.xgrid.*``
an unlabelled bar container (0.10.0)  ``main.bars0`` (a group over its bars)            positional
legend and its entries                ``main.legend``, ``main.legend.<label>``         semantic
spines, axis, background              ``main.spine.left``, ``main.xaxis``,             semantic
                                      ``main.background``
free text                             ``main.text.<text>``                             semantic
colorbar (``idofig.colorbar``)        ``cbar.<name>`` (its axes), ``cbar.<name>.solids`` named
unlabelled artists                    ``main.line0``, ``main.patch3`` …                 positional
====================================  ==============================================  ============

A 3D axes' z axis is named like x and y: ``main.zlabel``, ``main.zaxis``, ``main.ztick.<text>``;
its axes have the role ``axis3d``, and the 3D axes itself the role ``axes3d`` (0.11.0). A mesh
drawn with ``idofig.mesh`` is ``main.mesh.<name or file stem>`` (role ``mesh``, semantic). A
part an idofig helper drew is named by the helper (:func:`mark_part`, 0.13.0): ``brain.image``
(``idofig.image``), ``topo.field``, ``topo.head`` (``idofig.neuro.topomap``) and so on.
Free text is named by its axes and its text (``fig.text`` by its text alone), so a script that
draws its own tick labels with ``ax.text("5")`` more than once in one axes (or with
``fig.text`` on the figure) gets the same name twice; the second is ``….2`` (positional) and
reported — name such labels with a ``gid`` to address them. The same text in two axes is two
names.

An author ``gid`` always wins, as the name; the part's role is still what it is (a tick
label with a gid has the role ``tick``). Two author gids that collide are an error; derived names
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
PART = "_idofig_part"


def mark_part(artist: Artist, suffix: str, role: str | None = None) -> Artist:
    """Name ``artist`` ``<its axes>.<suffix>`` when it is saved (semantic); ``role`` defaults to
    its kind. For the parts an idofig helper draws, whose meaning the helper knows."""
    setattr(artist, PART, (suffix, role or kind_of(artist)))
    return artist


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
    container: Any = None  # the BarContainer a bar series group is (its values: marks.py)
    series: str | None = None  # a legend entry's: the series its handle is (legend_series)


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
        if kind is None:
            return self.by_artist.get(id(artist))
        if self.claimed(artist):
            claimed = self.parts[self.by_artist[id(artist)]]
            # A gid names the part; its role is still what the part is: left "author", a gid'd
            # tick label took an offset its role refuses (props.REFUSED_BY_ROLE).
            if claimed.role == "author":
                claimed.role = role
            return claimed.name
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


def axis_letters(ax: Axes) -> list[tuple[Axis, str]]:
    """An axes' axes with their letters; a 3D axes has a z axis, named like the other two
    (it was left out, so a 3D plot's z label and z ticks could not be addressed at all)."""
    out = [(ax.xaxis, "x"), (ax.yaxis, "y")]
    zaxis = getattr(ax, "zaxis", None)
    if zaxis is not None:
        out.append((zaxis, "z"))
    return out


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
        # A 3D axes is its own role (0.11.0): only it takes a view (props.VIEW).
        role = "axes3d" if getattr(ax, "name", None) == "3d" else "axes"
        if _author_gid(ax):
            name = _author_gid(ax)
            # A gid names it; its role is still what it is (left "author", a gid'd 2D axes took
            # a view and a gid'd 3D one was offered none).
            t.add(name, ax, "colorbar" if _is_colorbar_axes(ax) else role, "author", kind="axes")
        elif getattr(ax, "_idofig_name", None):
            name = ax._idofig_name
            t.add(name, ax, role, "named", kind="axes")
        elif _is_colorbar_axes(ax):
            cbar = ax._colorbar
            given = getattr(cbar, "_idofig_name", None)
            name = f"cbar.{given}" if given else f"cbar{cbar_index}"
            cbar_index += 1
            t.add(name, ax, "colorbar", "named" if given else "positional", kind="axes")
        else:
            name = f"ax{index}"
            t.add(name, ax, role, "positional", kind="axes")
        if not _is_colorbar_axes(ax):
            index += 1
        t.axes_names[id(ax)] = name
        _name_axes_contents(t, ax, name)
    return t


def _name_legend(t: PartTable, legend: Legend, name: str, parent: str | None) -> None:
    # Its frame, entries and title are named after the legend's name, its gid included: named
    # after "legend", a figure legend "key"'s entries had a parent that is no part.
    name = t.add(name, legend, "legend", "semantic", parent) or name
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
    # A 3D axis is its own role: it draws its tick marks from its own settings, so the tick
    # properties an axis takes are refused on it (props.REFUSED_BY_ROLE).
    axis_role = "axis3d" if getattr(ax, "name", None) == "3d" else "axis"
    for axis, letter in axis_letters(ax):
        if axis.label.get_text():
            t.add(f"{p}.{letter}label", axis.label, f"{letter}label", "semantic", p)
        t.add(f"{p}.{letter}axis", axis, axis_role, "semantic", p, kind="axis")
    for side, spine in ax.spines.items():
        t.add(f"{p}.spine.{slug(side)}", spine, "spine", "semantic", p)

    if _is_colorbar_axes(ax):
        cbar = ax._colorbar
        solids = getattr(cbar, "solids", None)
        if solids is not None:
            t.add(f"{p}.solids", solids, "colorbar-solids", "semantic", p)

    # A mesh (idofig.mesh, 0.11.0) is named by what it was given or its file, never by order.
    for coll in ax.collections:
        mesh = getattr(coll, "_idofig_mesh", None)
        if mesh is not None:
            t.add(f"{p}.mesh.{mesh['name']}", coll, "mesh", "semantic", p)
    # What an idofig helper drew (0.13.0: idofig.image, idofig.neuro) is named by what it is.
    for artist in [*ax.images, *ax.collections, *ax.lines, *ax.patches, *ax.texts]:
        part = getattr(artist, PART, None)
        if part is not None:
            t.add(f"{p}.{part[0]}", artist, part[1], "semantic", p)

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
            series.setdefault(key, []).append(("container", members, c))
    singles = [*ax.lines, *ax.collections, *ax.patches, *ax.images]
    claimed_by_container = {id(m) for runs in series.values() for _, ms, _ in runs for m in ms}
    for artist in singles:
        if t.claimed(artist) or id(artist) in claimed_by_container:
            continue
        lab = _label(artist)
        if lab:
            key = slug(lab)
            if key not in series:
                order.append(key)
            series.setdefault(key, []).append(("artist", [artist], None))

    for key in order:
        runs = series[key]
        base = f"{p}.series.{key}"
        if len(runs) == 1 and runs[0][0] == "artist":
            t.add(base, runs[0][1][0], "series", "semantic", p)
            continue
        members: list[str] = []
        flat = [m for _, ms, _ in runs for m in ms]
        for row, artist in enumerate(flat):
            n = t.add(f"{base}.{row}", artist, "mark", "positional", base)
            if n:
                members.append(n)
        t.add_group(base, members, "series", "semantic", p)
        if base in t and len(runs) == 1 and isinstance(runs[0][2], BarContainer):
            t.parts[base].container = runs[0][2]
        if sum(1 for kind, _, _ in runs if kind == "artist") > 1 or len(runs) > 1:
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
    # An unlabelled bar container (`ax.bar(x, h)`, `ax.hist(v)`) is one series too: its bars are
    # named one by one above, and grouped here so its values and its build step have a part.
    bars = 0
    for c in ax.containers:
        if isinstance(c, BarContainer) and not _label(c):
            names = [t.by_artist[id(a)] for a in c.patches if id(a) in t.by_artist]
            name = f"{p}.bars{bars}"
            if names and name not in t:
                t.add_group(name, names, "series", "positional", p)
                t.parts[name].container = c
                bars += 1

    for text in ax.texts:
        if text.get_text() and not t.claimed(text):
            t.add(f"{p}.text.{slug(text.get_text())}", text, "text", "semantic", p)
    legend = ax.get_legend()
    if legend is not None:  # with a gid too: skipped, it kept the role "author" and its entries no name
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
    """Name major tick labels by their text, and major gridlines by their tick's (0.10.0). Call
    after a draw, when ticks exist."""
    for ax in fig.axes:
        p = t.axes_names.get(id(ax))
        if p is None:
            continue
        flat = getattr(ax, "name", None) != "3d"  # a 3D axis draws its grid in one group of its own
        for axis, letter in axis_letters(ax):
            names: list[str] = []
            grids: list[str] = []
            for tick in _drawn_ticks(axis):
                for label, suffix in ((tick.label1, "tick"), (tick.label2, "tick2")):
                    if label.get_visible() and label.get_text():
                        # A tick label with an author gid keeps its name, outside the group,
                        # and `add` records that it is a tick label.
                        mine = not t.claimed(label)
                        n = t.add(f"{p}.{letter}{suffix}.{tick_slug(label.get_text())}", label, "tick", "semantic", p)
                        if n and mine:
                            names.append(n)
                # A gridline is named only when it is drawn: an unnamed one leaves matplotlib's
                # own group id, so a panel without a grid keeps its bytes.
                if flat and tick.gridline.get_visible():
                    text = tick.label1.get_text() or tick.label2.get_text() or f"{tick.get_loc():g}"
                    mine = not t.claimed(tick.gridline)
                    n = t.add(f"{p}.{letter}grid.{tick_slug(text)}", tick.gridline, "gridline", "semantic", p)
                    if n and mine:
                        grids.append(n)
            if grids:
                t.add_group(f"{p}.{letter}grid.*", grids, "grid", "semantic", p)
            if names:
                # Both sides: a colorbar draws only label2 (`ytick2.*`), and "all the y tick
                # labels" means those too — a group of the label1 side alone was empty there.
                t.add_group(f"{p}.{letter}tick.*", names, "ticks", "semantic", p)


def legend_series(fig: Figure, t: PartTable) -> None:
    """Join each legend entry to the series its handle is, by artist (``Part.series``).

    matplotlib keeps no link from an entry to the artist it was made from. A legend made from
    the axes' labelled artists (``ax.legend()``, ``fig.legend()``) lists them in the order
    ``get_legend_handles_labels`` returns, so when its texts are those labels one for one, entry
    k stands for handle k. Any other legend (hand-picked handles, texts changed afterwards) is
    joined to nothing: matching on the text alone joined an entry to whichever series happened
    to share its words.
    """
    legends = [(ax.get_legend(), [ax]) for ax in fig.axes] + [(lg, fig.axes) for lg in fig.legends]
    for legend, axes in legends:
        if legend is None:
            continue
        handles: list = []
        labels: list = []
        for ax in axes:
            h, lab = ax.get_legend_handles_labels()
            handles += h
            labels += lab
        texts = legend.get_texts()
        if [x.get_text() for x in texts] != labels:
            continue
        for text, handle in zip(texts, handles):
            entry = t.parts.get(t.by_artist.get(id(text), ""))
            if entry is None or entry.role != "legend-entry":
                continue
            artist = handle
            if isinstance(handle, Container):
                members = _container_members(handle)
                artist = members[0] if members else None
            name = t.by_artist.get(id(artist))
            part = t.parts.get(name or "")
            if part is None:
                continue
            parent = t.parts.get(part.parent or "")
            entry.series = part.parent if parent is not None and parent.group else name
