"""Apply a panel's style.json to named parts, before layout, with matplotlib's own setters.

Because overrides are applied to artists (not to the SVG afterwards), a bigger font
re-flows the layout exactly as if the author had typed it into the script.

Resolution order, so the most specific entry wins: wildcard patterns, then groups,
then single parts. An entry that matches nothing is *detached*: reported, kept in the
file, never applied to something else. An invalid property is reported and skipped.
"""

from __future__ import annotations

import fnmatch
import math
from contextlib import ExitStack
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable

import numpy as np
from matplotlib.axes import Axes
from matplotlib.collections import PathCollection
from matplotlib.colors import to_hex, to_rgba
from matplotlib.legend import Legend
from matplotlib.text import Annotation
from matplotlib.transforms import ScaledTranslation

from . import props as P
from .naming import PartTable, axis_letters, kind_of
from .units import MM_PER_IN


@dataclass
class StyleReport:
    applied: list[str] = field(default_factory=list)
    detached: list[str] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)
    base: dict[str, dict] = field(default_factory=dict)


class Undo(ExitStack):
    """What one save changes on the script's figure to write it (canvas, dpi, size, a frozen
    layout, moved parts, wrapped draws), put back when the save closes it, last change first.
    Left in place, a figure saved again (a notebook re-running its save cell) kept the first
    save's layout — a y label lengthened in between was clipped 2 mm off the panel — and an
    offset removed in between kept its part moved. Style overrides stay set (SPEC.md, Moving a
    part): putting one back takes more than a value (a size replaces every mark's size)."""

    def keep(self, obj: Any, *names: str) -> None:
        """Put these attributes back as they are now (the last named first)."""
        for name in names:
            self.callback(setattr, obj, name, getattr(obj, name))

    def set(self, obj: Any, name: str, value: Any) -> None:
        self.keep(obj, name)
        setattr(obj, name, value)

    def method(self, obj: Any, name: str, fn: Any) -> None:
        """Replace a method on one object; closing takes the replacement off again."""
        if name in vars(obj):
            self.keep(obj, name)
        else:
            self.callback(vars(obj).pop, name, None)  # its class's method answers again
        setattr(obj, name, fn)


def _hex(c: Any) -> str | None:
    """A colour as ``#rrggbb``, or ``none`` when it is fully transparent: matplotlib's "none" is
    (0, 0, 0, 0), and read as black, pcolor's default edge, drawn in no colour, was a stroke
    finding, and an editor showed black edges on bars that had none."""
    try:
        rgba = to_rgba(c)
    except (ValueError, TypeError):
        return None
    return "none" if rgba[3] == 0 else to_hex(rgba, keep_alpha=False)


def _shared_color(colors: Any) -> str | None:
    """A collection's colour: ``none`` when it draws none, its one colour, or None when its
    marks have several."""
    if len(colors) == 0 or not colors[:, 3].any():
        return "none"
    return _hex(colors[0]) if len(colors) == 1 else None


def _offsets(artist: Any) -> dict:
    """A part's style offsets: 0 unless ``apply`` recorded one for this save (a script never
    offsets a part, so 0 is its ``base`` too)."""
    return {k: getattr(artist, f"_idofig_{k}", 0.0) for k in P.OFFSETS}


def _transform(artist: Any) -> dict:
    """An axes' scale and rotate: identity unless ``apply`` recorded one for this save."""
    return {"scale": getattr(artist, "_idofig_scale", 1.0), "rotate": getattr(artist, "_idofig_rotate", 0.0)}


def _get_props(artist: Any, kind: str) -> dict:
    """Current values of the styleable properties (for the manifest and for 'was X in code').

    Not read back, so never in the manifest's ``props`` or ``base`` (SPEC.md says the same):
    a legend's ``loc``, a patch's ``color``, a collection's ``color``, its ``size`` unless its
    marks share one, and its ``cmap``/``vmin``/``vmax`` unless it maps values to colours."""
    try:
        if kind == "text":
            return {
                "text": artist.get_text(), "fontsize": _num(artist.get_fontsize()),
                "fontweight": artist.get_fontweight(), "fontstyle": artist.get_fontstyle(),
                "fontfamily": (artist.get_fontfamily() or [None])[0], "color": _hex(artist.get_color()),
                "alpha": _alpha(artist), "visible": artist.get_visible(),
                "rotation": _num(artist.get_rotation(), None),
                **_offsets(artist),
            }
        if kind == "line":
            return {
                "color": _hex(artist.get_color()), "linewidth": _num(artist.get_linewidth()),
                "linestyle": artist.get_linestyle(), "alpha": _alpha(artist), "visible": artist.get_visible(),
                "marker": str(artist.get_marker()), "markersize": _num(artist.get_markersize()),
                "markerfacecolor": _hex(artist.get_markerfacecolor()),
                "markeredgecolor": _hex(artist.get_markeredgecolor()),
            }
        if kind == "patch":
            # Read back so the stroke check skips an edge drawn with no line style (0 wide:
            # `bar(…, linestyle="none", linewidth=0.1)` was a finding). A dash pattern reads "--".
            ls = artist.get_linestyle()
            return {
                "facecolor": _hex(artist.get_facecolor()), "edgecolor": _hex(artist.get_edgecolor()),
                "linewidth": _num(artist.get_linewidth()),
                "linestyle": ls if isinstance(ls, str) else "--", "alpha": _alpha(artist),
                "visible": artist.get_visible(), "hatch": artist.get_hatch(),
            }
        if kind == "collection":
            # An edge in each mark's face colour (`edgecolors="face"`, a scatter's default) merges
            # into the fill: `face`, no stroke (read as the face colours, a scatter's 0.1 pt edge
            # was a finding), unless the mark is all stroke. What was set is read: a
            # colour-mapped collection's mapped colours replace `_edgecolors`.
            edge = getattr(artist, "_original_edgecolor", None)
            face = isinstance(edge, str) and edge.lower() == "face" and not _all_stroke(artist)
            # atleast_1d: an eventplot gives one width, not one per mark; iterated, it raised,
            # and its 0.1 pt spikes passed Nature's 0.25 pt unread.
            widths = {_num(w) for w in np.atleast_1d(artist.get_linewidth())}
            out = {
                "facecolor": _shared_color(artist.get_facecolor()),
                "edgecolor": "face" if face else _shared_color(artist.get_edgecolor()),
                # as for colours: null when the marks differ (the thinnest is `thinnest_pt`)
                "linewidth": widths.pop() if len(widths) == 1 else None,
                "alpha": _alpha(artist), "visible": artist.get_visible(),
            }
            if hasattr(artist, "get_sizes") and len(artist.get_sizes()) == 1:
                out["size"] = _num(artist.get_sizes()[0], None)
            if getattr(artist, "get_array", None) is not None and artist.get_array() is not None:
                out["cmap"] = artist.get_cmap().name
                vmin, vmax = artist.get_clim()
                out["vmin"], out["vmax"] = _num(vmin, 6), _num(vmax, 6)
            return out
        if kind == "image":
            vmin, vmax = artist.get_clim()
            return {"alpha": _alpha(artist), "visible": artist.get_visible(), "cmap": artist.get_cmap().name,
                    "vmin": _num(vmin, 6), "vmax": _num(vmax, 6)}
        if kind == "axes":
            return {"facecolor": _hex(artist.get_facecolor()), "visible": artist.get_visible(), **_offsets(artist),
                    **_transform(artist)}
        if kind == "axis":
            tick = artist.majorTicks[0]  # the tick every later one copies its settings from
            return {"visible": artist.get_visible(), "tickdir": tick.get_tickdir(),
                    "ticklength": _num(tick.tick1line.get_markersize()),
                    "tickwidth": _num(tick.tick1line.get_markeredgewidth())}
        if kind == "spine":
            return {"visible": artist.get_visible(), "linewidth": _num(artist.get_linewidth()),
                    "color": _hex(artist.get_edgecolor())}
        if kind == "legend":
            texts = artist.get_texts()
            return {"visible": artist.get_visible(), "frameon": artist.get_frame_on(),
                    "fontsize": _num(texts[0].get_fontsize()) if texts else None,
                    "title": artist.get_title().get_text(), **_offsets(artist),
                    "rotate": getattr(artist, "_idofig_rotate", 0.0)}
    except Exception:  # a getter a third-party artist does not implement
        return {}
    return {}


def get_props(artist: Any, kind: str) -> dict:
    """Style values and the common post-layout geometry contract."""
    return {**_get_props(artist, kind), **_offsets(artist), **_transform(artist)}


def svg_offset(part) -> bool:
    """Moves new artist kinds in SVG; preserve established text/legend/axes placement."""
    return part.kind not in {"text", "axes", "legend"} or part.role in {"tick", "legend-entry", "legend-title"}


def _num(v: Any, places: int | None = 3) -> float | None:
    """``v`` rounded to ``places`` (None: as it is), or None when it is no finite number.
    matplotlib draws with a NaN without a word (an all-NaN image's limits, `lw=float("nan")`),
    and a manifest is JSON, which has none: every panel's save failed in the encoder."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v if places is None else round(v, places)


def _alpha(artist: Any) -> float | None:
    """A part's one alpha, or None when it has none or each mark has its own (an array, which
    stopped every panel's save in the JSON encoder)."""
    a = artist.get_alpha()
    return None if np.ndim(a) else _num(a, None)


def _all_stroke(coll: Any) -> bool:
    """Whether a scatter's marks are strokes alone ('+', 'x', '|', '_', '1'–'4', tick markers):
    their edge, which matplotlib sets to ``face`` itself, is the whole mark, and read as
    ``face`` a '+' drawn 0.1 pt wide passed Nature's 0.25 pt. Only a scatter is asked: other
    collections' marks have an inside, and a pcolormesh makes paths of its cells only when
    asked (0.8 s for 700 × 700)."""
    if not isinstance(coll, PathCollection):
        return False
    return all(len(line) <= 2 for path in coll.get_paths() for line in path.to_polygons(closed_only=False))


def _set(artist: Any, kind: str, key: str, value: Any) -> None:
    if key in _MOVES:  # recorded now, applied once the layout is frozen (apply_offsets, axes_transforms)
        setattr(artist, f"_idofig_{key}", float(value))
    elif kind == "text":
        axis = _axis3d_of(artist) if key == "rotation" else None
        if axis is not None:
            # A 3D axis turns a label longer than 4 characters to its angle at every draw, over
            # any rotation set (`rotation: 0` on "depth" was drawn at 87.4°).
            axis.set_rotate_label(False)
        {"text": artist.set_text, "fontsize": artist.set_fontsize, "fontweight": artist.set_fontweight,
         "fontstyle": artist.set_fontstyle, "fontfamily": artist.set_fontfamily, "color": artist.set_color,
         "alpha": artist.set_alpha, "visible": artist.set_visible, "rotation": artist.set_rotation}[key](value)
    elif kind == "line":
        {"color": artist.set_color, "linewidth": artist.set_linewidth, "linestyle": artist.set_linestyle,
         "alpha": artist.set_alpha, "visible": artist.set_visible, "marker": artist.set_marker,
         "markersize": artist.set_markersize, "markerfacecolor": artist.set_markerfacecolor,
         "markeredgecolor": artist.set_markeredgecolor}[key](value)
    elif kind == "patch":
        {"facecolor": artist.set_facecolor, "edgecolor": artist.set_edgecolor, "color": artist.set_color,
         "linewidth": artist.set_linewidth, "linestyle": artist.set_linestyle, "alpha": artist.set_alpha,
         "visible": artist.set_visible, "hatch": artist.set_hatch}[key](value)
    elif kind == "collection":
        if key == "size":
            artist.set_sizes([value])
        elif key == "cmap":
            artist.set_cmap(value)
        elif key == "vmin":
            artist.set_clim(vmin=value)
        elif key == "vmax":
            artist.set_clim(vmax=value)
        else:
            {"facecolor": artist.set_facecolor, "edgecolor": artist.set_edgecolor, "color": artist.set_color,
             "linewidth": artist.set_linewidth, "alpha": artist.set_alpha, "visible": artist.set_visible}[key](value)
    elif kind == "image":
        if key == "cmap":
            artist.set_cmap(value)
        elif key == "vmin":
            artist.set_clim(vmin=value)
        elif key == "vmax":
            artist.set_clim(vmax=value)
        else:
            {"alpha": artist.set_alpha, "visible": artist.set_visible}[key](value)
    elif kind == "axes":
        {"facecolor": artist.set_facecolor, "visible": artist.set_visible}[key](value)
    elif kind == "axis":
        if key == "visible":
            artist.set_visible(value)
        elif key == "tickdir":  # minor ticks too: a figure with inward major and outward minor ticks looks broken
            artist.set_tick_params(which="both", direction=value)
        else:
            artist.set_tick_params(which="major", **{{"ticklength": "length", "tickwidth": "width"}[key]: value})
    elif kind == "spine":
        {"visible": artist.set_visible, "linewidth": artist.set_linewidth, "color": artist.set_edgecolor}[key](value)
    elif kind == "legend":
        if key == "visible":
            artist.set_visible(value)
        elif key == "frameon":
            artist.set_frame_on(value)
        elif key == "fontsize":
            for text in artist.get_texts():
                text.set_fontsize(value)
        elif key == "title":
            artist.set_title(value)
        elif key == "loc":
            if hasattr(artist, "set_loc"):
                artist.set_loc(value)
            else:  # matplotlib < 3.8
                artist._loc = artist.codes[value]


_LEGEND_KEYS = {"color", "facecolor", "edgecolor", "linewidth", "linestyle", "alpha", "marker", "markersize",
                "markerfacecolor", "markeredgecolor", "hatch"}


def _sync_legend(artist: Any, props: dict) -> None:
    """A legend entry is a copy of its artist made when the legend was built; restyling the
    series must restyle its key too, or the legend describes a different plot."""
    label = artist.get_label() if hasattr(artist, "get_label") else None
    if not isinstance(label, str) or not label or label.startswith("_"):
        return
    wanted = {k: v for k, v in props.items() if k in _LEGEND_KEYS}
    if not wanted:
        return
    ax = getattr(artist, "axes", None)
    legends = []
    if ax is not None and ax.get_legend() is not None:
        legends.append(ax.get_legend())
    fig = getattr(artist, "figure", None)
    if fig is not None:
        legends.extend(getattr(fig, "legends", []))
    for legend in legends:
        handles = getattr(legend, "legend_handles", None) or getattr(legend, "legendHandles", [])
        for handle, text in zip(handles, legend.get_texts()):
            if handle is None or text.get_text() != label:
                continue
            hk = kind_of(handle)
            for key, value in wanted.items():
                if hk and not P.validate(hk, {key: value}):
                    try:
                        _set(handle, hk, key, value)
                    except Exception:  # a handle type without that setter
                        pass


def _targets(table: PartTable, pattern: str) -> tuple[list[str], bool]:
    """Names of single parts an entry addresses, and whether it addresses a group."""
    if pattern in table.parts:
        part = table.parts[pattern]
        if part.group:
            return list(part.members), True
        return [pattern], False
    if "*" in pattern:
        hits = [n for n, part in table.parts.items() if not part.group and fnmatch.fnmatchcase(n, pattern)]
        return hits, True
    return [], False


def _movers(table: PartTable, names: list[str]) -> list[str]:
    """Of the parts an entry addresses, those a move moves itself: a part drawn in an axes the
    same entry moves comes along with its axes (moved again, `main.*` moved main's labels twice
    as far as main)."""
    contained = set()
    def descend(artist):
        for child in artist.get_children():
            if id(child) not in contained:
                contained.add(id(child))
                descend(child)
    for name in names:
        for artist in table.parts[name].artists:
            descend(artist)
    return [name for name in names if not any(id(a) in contained for a in table.parts[name].artists)]



# What moves a part as a whole, with what is drawn in it: taken in the final pass, and on a group
# or pattern entry by the parts not drawn in an axes the same entry moves (`_movers`).
_MOVES = P.OFFSETS + P.TRANSFORMS


def _specificity(pattern: str, table: PartTable) -> int:
    if "*" in pattern:
        return 0
    part = table.parts.get(pattern)
    return 1 if part is not None and part.group else 2


def apply(table: PartTable, style: dict, report: StyleReport, *, final: bool) -> None:
    """Apply every entry that resolves now. With ``final``, whatever still resolves to
    nothing is recorded as detached."""
    entries = sorted(style.get("parts", {}).items(), key=lambda kv: (_specificity(kv[0], table), kv[0]))
    for pattern, props in entries:
        names, group = _targets(table, pattern)
        if not names:
            if final and pattern not in report.applied and pattern not in report.detached:
                report.detached.append(pattern)
            continue
        good: dict[str, Any] = {}
        movers = _movers(table, names)
        for key, value in props.items():
            if key in _MOVES and not final:
                # Taken in the final pass, when every part has its role: before the draw, a tick
                # label with a gid is not known to be one, and its offset got past the refusal.
                continue
            problems = []
            for kind, role in {(table.parts[n].kind, table.parts[n].role)
                               for n in (movers if key in _MOVES else names)}:
                problems += P.validate(kind, {key: value}, group=group or len(names) > 1, role=role)
            if problems:
                entry = {"part": pattern, "prop": key, "reason": "; ".join(sorted(set(problems)))}
                if entry not in report.invalid:
                    report.invalid.append(entry)
            else:
                good[key] = value
        for name in names:
            part = table.parts[name]
            for artist in part.artists:
                kind = kind_of(artist) or part.kind
                base = report.base.setdefault(name, {})
                current = get_props(artist, kind)
                # An override stays set after a save, and a second save read it as the script's
                # value (base 9 pt for a 7 pt label). The script's value is kept with the value
                # set, and is base again unless the script has set the property since.
                earlier = artist.__dict__.setdefault("_idofig_base", {})
                for key, value in good.items():
                    if key in _MOVES and name not in movers:
                        continue
                    if key == "rotation" and not final and _axis3d_of(artist) is not None:
                        # The angle a 3D axis turns its label to is known once drawn (read before,
                        # base was 0 for a label drawn at 87.4°); set then, it still reaches the layout.
                        continue
                    if key not in base and key in current:
                        was = earlier.get(key)  # (the script's value, the value set) at an earlier save
                        base[key] = was[0] if was and was[1] == current[key] else current[key]
                    _set(artist, kind, key, value)
                after = get_props(artist, kind) if good else {}
                for key in good:
                    if key in base and key in after:
                        earlier[key] = (base[key], after[key])
                if kind in {"line", "patch", "collection"}:
                    _sync_legend(artist, good)
        if pattern not in report.applied:
            report.applied.append(pattern)
        if pattern in report.detached:
            report.detached.remove(pattern)


def offsets(table: PartTable) -> list[tuple[Any, float, float]]:
    """``(artist, dx_mm, dy_mm)`` for every part a style moves (``apply`` recorded them)."""
    out = []
    for part in table.parts.values():
        if part.group or svg_offset(part):  # SVG-only moves do not mutate matplotlib
            continue
        for artist in part.artists:
            dx, dy = _offsets(artist).values()
            if dx or dy:
                out.append((artist, dx, dy))
    return out


def forget_offsets(table: PartTable) -> None:
    """Drop the offsets ``apply`` recorded, once the save that moved them is written: an entry
    removed from style.json (or set to 0) before the next save leaves its part where the
    script draws it."""
    for part in table.parts.values():
        for artist in part.artists:
            for key in _MOVES:
                vars(artist).pop(f"_idofig_{key}", None)


def apply_offsets(fig, moves: list[tuple[Any, float, float]], undo: Undo) -> None:
    """Move each part by its offset (mm, y down) on a figure a save has just laid out, its
    layout frozen first: applied before the layout, a constrained layout absorbed the move (a
    3 pt xlabel nudge shrank the axes instead). A move is a translation evaluated at draw
    time, in the drawing's own dpi."""
    _freeze(fig, undo)
    moved_axes: set[int] = set()
    # Axes first: a moved legend's anchor is read where its axes already is.
    for artist, dx, dy in sorted(moves, key=lambda m: not isinstance(m[0], Axes)):
        dx_in, dy_in = dx / MM_PER_IN, -dy / MM_PER_IN
        shift = ScaledTranslation(dx_in, dy_in, fig.dpi_scale_trans)
        if isinstance(artist, Axes):
            _move_axes(artist, dx_in, dy_in, fig, undo, moved_axes)
        elif isinstance(artist, Legend):
            # Its anchor box moves, keeping its `loc`, padding and size: pinned by a corner to a
            # zero-size box, a mode="expand" legend collapsed to 0 mm, and one measured by the
            # manifest's renderer came out 0.34 mm lower. The anchor goes back as the attribute
            # it was: `set_bbox_to_anchor` reads a box in its parent's transform, and a script's
            # own anchor put back through it drew the legend metres off the panel.
            anchor = artist.get_bbox_to_anchor().transformed(fig.dpi_scale_trans.inverted())
            undo.keep(artist, "_bbox_to_anchor")
            artist.set_bbox_to_anchor(anchor.translated(dx_in, dy_in), transform=fig.dpi_scale_trans)
        elif isinstance(artist, Annotation):
            # It resets its transform at every draw: its text coordinates move instead, and its
            # arrow still ends at `xy`.
            undo.set(artist, "anncoords", partial(_shifted_coords, artist, artist.anncoords, shift))
        elif _axis3d_of(artist) is not None:
            undo.keep(artist, "_transform")
            undo.method(artist, "draw", partial(_draw_3d_label, artist, shift, artist.draw, {}))
        else:
            undo.keep(artist, "_transform", "_transformSet")
            artist.set_transform(artist.get_transform() + shift)


def _move_axes(ax, dx_in: float, dy_in: float, fig, undo: Undo, moved: set[int]) -> None:
    """Move an axes' box, and so everything drawn in it (its labels, ticks, title, legend, images,
    texts, annotations: all are placed from the box), as the save laid it out. Its twins share
    the box and move with it, once. `_set_position`, not `set_position`: that one takes the axes
    out of any later layout, and a notebook's next save left it where this save moved it. A
    locator (an inset, a colorbar made from `ax=`) places the box anew at every draw, so it is
    set aside for the save."""
    twins = ax._twinned_axes.get_siblings(ax)
    if any(id(t) in moved for t in twins):
        return
    moved.update(id(t) for t in twins)
    for t in twins:
        undo.callback(t.set_axes_locator, t.get_axes_locator())
        undo.callback(t._set_position, t.get_position(original=True), "original")
        undo.callback(t._set_position, t.get_position(), "active")
        t.set_axes_locator(None)
    w_in, h_in = fig.get_size_inches()
    ax._set_position(ax.get_position().translated(dx_in / w_in, dy_in / h_in), "both")  # its twins too


def axes_transforms(fig) -> dict[int, tuple[Any, tuple[float, ...], float]]:
    """``{id(ax): (ax, matrix, scale)}`` for every axes a style scales or rotates, its twins
    included (they share its box, and take the first sibling's values that are not identity).
    ``matrix`` is SVG's ``(a, b, c, d, e, f)`` in the panel's points, y down: translate to the
    box's centre ∘ rotate (clockwise, as SVG turns in y down) ∘ scale ∘ translate back, the box
    as the save drew it (after its layout, its locator and its ``dx_mm``/``dy_mm``). Read after
    the save's draw; the transform is on the axes' group (``svgpost.transform_groups``)."""
    w_pt, h_pt = fig.get_figwidth() * 72, fig.get_figheight() * 72
    out: dict[int, tuple[Any, tuple[float, ...], float]] = {}
    for ax in fig.axes:
        if id(ax) in out:
            continue
        twins = ax._twinned_axes.get_siblings(ax)
        values = next((v for t in twins if (v := _transform(t)) != {"scale": 1.0, "rotate": 0.0}), None)
        if values is None:
            continue
        s = float(values["scale"])
        box = ax.get_position()
        matrix = _about((box.x0 + box.x1) / 2 * w_pt, h_pt - (box.y0 + box.y1) / 2 * h_pt, s, float(values["rotate"]))
        for t in twins:
            out[id(t)] = (t, matrix, s)
    return out


def artist_transforms(table: PartTable, box_of: Callable[[Any], list[float] | None]
                      ) -> dict[int, tuple[Any, tuple[float, ...], float]]:
    """Local post-layout transforms, in panel points, about each artist's own box."""
    out = {}
    for part in table.parts.values():
        if part.kind == "axes" or part.group:
            continue
        for artist in part.artists:
            scale, rotate = _transform(artist).values()
            dx, dy = _offsets(artist).values() if svg_offset(part) else (0, 0)
            if (scale, rotate, dx, dy) == (1, 0, 0, 0):
                continue
            box = box_of(artist)
            if box:
                m = _about((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, scale, rotate)
                m = (*m[:4], m[4] + dx * 72 / MM_PER_IN, m[5] + dy * 72 / MM_PER_IN)
                if not all(math.isfinite(v) for v in m):
                    raise ValueError("artist transform exceeds finite SVG coordinates")
                out[id(artist)] = (artist, m, scale)
    return out


def _about(cx: float, cy: float, s: float, deg: float) -> tuple[float, ...]:
    """SVG's ``(a, b, c, d, e, f)`` for translate(c) ∘ rotate(deg, clockwise in y down) ∘ scale(s)
    ∘ translate(−c)."""
    r = math.radians(deg)
    a, b, c, d = s * math.cos(r), s * math.sin(r), -s * math.sin(r), s * math.cos(r)
    matrix = (a, b, c, d, cx - a * cx - c * cy, cy - b * cx - d * cy)
    if not all(math.isfinite(v) for v in matrix) or not 0 < a * d - b * c < math.inf:
        raise ValueError("artist transform exceeds finite invertible SVG coordinates")
    return matrix


def then(outer: tuple[float, ...], inner: tuple[float, ...]) -> tuple[float, ...]:
    """The SVG matrix of ``inner`` then ``outer`` (a group's inside a transformed group's)."""
    a1, b1, c1, d1, e1, f1 = outer
    a2, b2, c2, d2, e2, f2 = inner
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def map_box(box: list[float], m: tuple[float, ...]) -> list[float]:
    """The axis-aligned box around ``box`` ([x0, y0, x1, y1]) mapped by SVG matrix ``m``."""
    a, b, c, d, e, f = m
    xs = [a * x + c * y + e for x in (box[0], box[2]) for y in (box[1], box[3])]
    ys = [b * x + d * y + f for x in (box[0], box[2]) for y in (box[1], box[3])]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def _freeze(fig, undo: Undo) -> None:
    """Keep what matplotlib places anew at every draw where the save just placed it, so only a
    moved part moves: the layout (its engine is turned off); titles (matplotlib lifts one that
    dips below its axes and lines them up: a title moved 6 mm down came out 1.6 mm down); and
    every `loc="best"` legend of an axes, one shown with `ax.add_artist` too, as the fixed
    `loc` best chose (it avoids the axes' texts: it jumped 57 mm when a text moved)."""
    engine = fig.get_layout_engine()
    fig.set_layout_engine("none")  # a placeholder that keeps the engine's colorbar layout, so it goes back
    undo.callback(fig.set_layout_engine, engine if engine is not None else "none")
    for ax in fig.axes:
        undo.set(ax, "_autotitlepos", False)  # the positions the save computed, in axes fractions
        for legend in ax.get_children():
            if not isinstance(legend, Legend) or legend._loc != 0 or not legend.get_visible():  # 0: "best"
                continue
            # The frame the save drew, at the SVG's 72 dpi whatever the figure's (read at a
            # producer's 300 dpi, a (2, 1) mm move landed (-4.35, 42.2) mm away).
            frame = legend.legendPatch
            x0, y0, w, h = (v / 72 for v in (frame.get_x(), frame.get_y(), frame.get_width(), frame.get_height()))
            box = legend.get_bbox_to_anchor().transformed(fig.dpi_scale_trans.inverted())
            pad = legend.borderaxespad * legend._fontsize / 72  # as matplotlib pads an anchored legend
            across = {"left": box.x0 + pad, "center": box.x0 + (box.width - w) / 2, "right": box.x1 - pad - w}
            up = {"lower": box.y0 + pad, "center": box.y0 + (box.height - h) / 2, "upper": box.y1 - pad - h}
            side = min(across, key=lambda k: abs(across[k] - x0))
            height = min(up, key=lambda k: abs(up[k] - y0))
            undo.keep(legend, "_loc_used_default", "_loc")  # setting `_loc` back clears the first
            _set(legend, "legend", "loc", "center" if side == height == "center" else f"{height} {side}")


def _shifted_coords(artist, coords, shift, renderer):
    """An annotation's text coordinates, moved (``Annotation.anncoords`` takes a callable)."""
    return artist._get_xy_transform(renderer, coords) + shift


def _axis3d_of(artist):
    """The 3D axis ``artist`` is the label of, or None."""
    ax = getattr(artist, "axes", None)
    if getattr(ax, "name", None) != "3d":
        return None
    return next((axis for axis, _ in axis_letters(ax) if artist is axis.label), None)


def _draw_3d_label(artist, shift, plain, state: dict, renderer) -> None:
    """A moved 3D axis label's draw: its axis points the label's transform back at the data
    before every draw (`Axis3D._update_all_positions`), dropping the move, so it is added
    here — once for a label drawn on both sides after one reset."""
    if artist._transform is not state.get("moved"):
        state["moved"] = artist._transform + shift
        artist._transform = state["moved"]
    plain(renderer)


def tick_params_from_style(fig, table: PartTable, style: dict) -> None:
    """Tick-label wildcards (``main.xtick.*``) are applied through ``tick_params`` before the
    first draw, so layout accounts for them even though tick labels do not exist yet."""
    for pattern, props in style.get("parts", {}).items():
        for ax in fig.axes:
            p = table.axes_names.get(id(ax))
            if p is None:
                continue
            for _, letter in axis_letters(ax):
                if pattern != f"{p}.{letter}tick.*":
                    continue
                kw = {}
                if "fontsize" in props and not P.validate("text", {"fontsize": props["fontsize"]}):
                    kw["labelsize"] = props["fontsize"]
                if "color" in props and not P.validate("text", {"color": props["color"]}):
                    kw["labelcolor"] = props["color"]
                if "rotation" in props and not P.validate("text", {"rotation": props["rotation"]}):
                    kw["labelrotation"] = props["rotation"]
                if props.get("visible") is False:
                    kw.update({"labelbottom": False, "labeltop": False} if letter == "x" else
                              {"labelleft": False, "labelright": False})
                if kw:
                    ax.tick_params(axis=letter, which="major", **kw)


def apply_layout(fig, layout: dict, undo: Undo) -> list[str]:
    """style.json's ``layout`` (mm) on the constrained layout engine, before the save lays the
    panel out, so matplotlib re-flows the axes; ``undo`` puts the engine and gridspecs back.

    A mm means a mm on paper. ``pad_mm`` is the engine's ``w_pad``/``h_pad`` (inches): the
    clear space around every axes' ink, the panel's edges included. ``wspace_mm``/``hspace_mm``
    is the clear gap between neighbouring axes' ink (tick labels and axis labels included). The
    engine gives each side of an axes ``wspace / 2 / ncols`` of the figure as that margin
    (``_constrained_layout.get_margin_from_padding``), so the gap is ``wspace * W / ncols``:
    it is set on each gridspec as ``wspace_mm * ncols / W_mm`` — one engine-wide fraction
    would be wrong for every grid of another shape. Where a gap is less than twice the pad,
    matplotlib uses the pads (its rule, kept)."""
    from matplotlib.layout_engine import ConstrainedLayoutEngine

    if not layout:
        return []
    engine = fig.get_layout_engine()
    if not isinstance(engine, ConstrainedLayoutEngine):
        # Axes placed by hand (`layout=None`, axes_mm) or a tight layout: nothing re-flows, and
        # faking it by moving axes would rewrite what the script placed.
        return ["style.json layout had no effect: this panel has no constrained layout engine "
                "(its axes are placed by the script); set layout=\"constrained\" in idofig.panels() "
                "or space the axes in the script"]
    params = dict(engine._params)
    undo.callback(engine._params.update, params)
    if "pad_mm" in layout:
        pad_in = layout["pad_mm"] / MM_PER_IN
        engine.set(w_pad=pad_in, h_pad=pad_in)
    w_mm, h_mm = fig.get_figwidth() * MM_PER_IN, fig.get_figheight() * MM_PER_IN
    grids = {id(g): g for ax in fig.axes if (ss := ax.get_subplotspec()) is not None
             for g in [ss.get_gridspec()]}
    for gs in grids.values():
        nrows, ncols = gs.get_geometry()
        # ponytail: fractions of the whole panel; a gridspec inside a subfigure is spaced as if it spanned it.
        for key, attr, n, span in (("wspace_mm", "wspace", ncols, w_mm), ("hspace_mm", "hspace", nrows, h_mm)):
            if key not in layout:
                continue
            name = attr if hasattr(gs, attr) else f"_{attr}"  # GridSpecFromSubplotSpec keeps `_wspace`
            undo.set(gs, name, layout[key] * n / span)
    return []
