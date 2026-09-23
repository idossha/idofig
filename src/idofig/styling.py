"""Apply a panel's style.json to named parts, before layout, with matplotlib's own setters.

Because overrides are applied to artists (not to the SVG afterwards), a bigger font
re-flows the layout exactly as if the author had typed it into the script.

Resolution order, so the most specific entry wins: wildcard patterns, then groups,
then single parts. An entry that matches nothing is *detached*: reported, kept in the
file, never applied to something else. An invalid property is reported and skipped.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

from matplotlib.colors import to_hex

from . import props as P
from .naming import PartTable, kind_of


@dataclass
class StyleReport:
    applied: list[str] = field(default_factory=list)
    detached: list[str] = field(default_factory=list)
    invalid: list[dict] = field(default_factory=list)
    base: dict[str, dict] = field(default_factory=dict)


def _hex(c: Any) -> str | None:
    try:
        return to_hex(c, keep_alpha=False)
    except (ValueError, TypeError):
        return None


def get_props(artist: Any, kind: str) -> dict:
    """Current values of the styleable properties (for the manifest and for 'was X in code')."""
    try:
        if kind == "text":
            return {
                "text": artist.get_text(), "fontsize": round(float(artist.get_fontsize()), 3),
                "fontweight": artist.get_fontweight(), "fontstyle": artist.get_fontstyle(),
                "fontfamily": (artist.get_fontfamily() or [None])[0], "color": _hex(artist.get_color()),
                "alpha": artist.get_alpha(), "visible": artist.get_visible(), "rotation": artist.get_rotation(),
            }
        if kind == "line":
            return {
                "color": _hex(artist.get_color()), "linewidth": round(float(artist.get_linewidth()), 3),
                "linestyle": artist.get_linestyle(), "alpha": artist.get_alpha(), "visible": artist.get_visible(),
                "marker": str(artist.get_marker()), "markersize": round(float(artist.get_markersize()), 3),
                "markerfacecolor": _hex(artist.get_markerfacecolor()),
                "markeredgecolor": _hex(artist.get_markeredgecolor()),
            }
        if kind == "patch":
            return {
                "facecolor": _hex(artist.get_facecolor()), "edgecolor": _hex(artist.get_edgecolor()),
                "linewidth": round(float(artist.get_linewidth()), 3), "alpha": artist.get_alpha(),
                "visible": artist.get_visible(), "hatch": artist.get_hatch(),
            }
        if kind == "collection":
            fc = artist.get_facecolor()
            ec = artist.get_edgecolor()
            lw = artist.get_linewidth()
            out = {
                "facecolor": _hex(fc[0]) if len(fc) == 1 else None,
                "edgecolor": _hex(ec[0]) if len(ec) == 1 else None,
                "linewidth": round(float(lw[0]), 3) if len(lw) else None,
                "alpha": artist.get_alpha(), "visible": artist.get_visible(),
            }
            if hasattr(artist, "get_sizes") and len(artist.get_sizes()) == 1:
                out["size"] = float(artist.get_sizes()[0])
            if getattr(artist, "get_array", None) is not None and artist.get_array() is not None:
                out["cmap"] = artist.get_cmap().name
                vmin, vmax = artist.get_clim()
                out["vmin"], out["vmax"] = _num(vmin), _num(vmax)
            return out
        if kind == "image":
            vmin, vmax = artist.get_clim()
            return {"alpha": artist.get_alpha(), "visible": artist.get_visible(), "cmap": artist.get_cmap().name,
                    "vmin": _num(vmin), "vmax": _num(vmax)}
        if kind == "axes":
            return {"facecolor": _hex(artist.get_facecolor()), "visible": artist.get_visible()}
        if kind == "axis":
            return {"visible": artist.get_visible()}
        if kind == "spine":
            return {"visible": artist.get_visible(), "linewidth": round(float(artist.get_linewidth()), 3),
                    "color": _hex(artist.get_edgecolor())}
        if kind == "legend":
            texts = artist.get_texts()
            return {"visible": artist.get_visible(), "frameon": artist.get_frame_on(),
                    "fontsize": round(float(texts[0].get_fontsize()), 3) if texts else None,
                    "title": artist.get_title().get_text()}
    except Exception:  # a getter a third-party artist does not implement
        return {}
    return {}


def _num(v: Any) -> float | None:
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return None


def _set(artist: Any, kind: str, key: str, value: Any) -> None:
    if kind == "text":
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
        artist.set_visible(value)
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
        kinds = {table.parts[n].kind for n in names}
        for key, value in props.items():
            problems = []
            for kind in kinds:
                problems += P.validate(kind, {key: value}, group=group or len(names) > 1)
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
                for key, value in good.items():
                    if key not in base and key in current:
                        base[key] = current[key]
                    _set(artist, kind, key, value)
                if kind in {"line", "patch", "collection"}:
                    _sync_legend(artist, good)
        if pattern not in report.applied:
            report.applied.append(pattern)
        if pattern in report.detached:
            report.detached.remove(pattern)


def tick_params_from_style(fig, table: PartTable, style: dict) -> None:
    """Tick-label wildcards (``main.xtick.*``) are applied through ``tick_params`` before the
    first draw, so layout accounts for them even though tick labels do not exist yet."""
    for pattern, props in style.get("parts", {}).items():
        for ax in fig.axes:
            p = table.axes_names.get(id(ax))
            if p is None:
                continue
            for letter in ("x", "y"):
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
