"""The style properties a canvas or an agent may set on a named part, by part kind.

This module is pure (no matplotlib) so the server can validate an edit before it is
written. ``style.apply`` in the drawing process maps each property to a matplotlib setter.

A part's *kind* is recorded in its panel manifest:

``text`` ``line`` ``patch`` ``collection`` ``image`` ``axes`` ``axis`` ``spine`` ``legend``
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ._colornames import NAMES as COLOR_NAMES

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_CYCLE = re.compile(r"^C[0-9]$")
_GRAY = re.compile(r"^(?:0(?:\.\d+)?|1(?:\.0+)?)$")

LINESTYLES = {"-", "--", ":", "-.", "solid", "dashed", "dotted", "dashdot", "none", "None", ""}
MARKERS = {"", " ", "*", "+", ",", ".", "1", "2", "3", "4", "8", "<", ">", "D", "H", "None", "P", "X",
           "^", "_", "d", "h", "none", "o", "p", "s", "v", "x", "|"}
WEIGHTS = {"ultralight", "light", "normal", "regular", "book", "medium", "roman", "semibold",
           "demibold", "demi", "bold", "heavy", "extra bold", "black"}
FONTSTYLES = {"normal", "italic", "oblique"}
LEGEND_LOCS = {"best", "upper right", "upper left", "lower left", "lower right", "right", "center left",
               "center right", "lower center", "upper center", "center"}


def is_color(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    v = value.strip()
    return bool(
        v.lower() == "none" or _HEX.match(v) or _CYCLE.match(v) or _GRAY.match(v) or v.lower() in COLOR_NAMES
    )


Check = Callable[[Any], "str | None"]


def _described(check: Check, **spec: Any) -> Check:
    """Attach a JSON description, so an application can build its editors from this table."""
    check.spec = {k: v for k, v in spec.items() if v is not None}  # type: ignore[attr-defined]
    return check


def _num(lo: float | None = None, hi: float | None = None, unit: str | None = None) -> Check:
    def check(v: Any) -> str | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "must be a number"
        if lo is not None and v < lo:
            return f"must be ≥ {lo}"
        if hi is not None and v > hi:
            return f"must be ≤ {hi}"
        return None

    return _described(check, type="number", min=lo, max=hi, unit=unit)


def _color_check(v: Any) -> str | None:
    return None if is_color(v) else "must be a colour (#rrggbb, a matplotlib colour name, 'C0'…'C9' or 'none')"


def _bool_check(v: Any) -> str | None:
    return None if isinstance(v, bool) else "must be true or false"


def _str_check(v: Any) -> str | None:
    return None if isinstance(v, str) else "must be text"


def _enum(options: set[str]) -> Check:
    def check(v: Any) -> str | None:
        return None if isinstance(v, str) and v in options else f"must be one of {sorted(options)}"

    return _described(check, type="enum", options=sorted(options))


def _weight_check(v: Any) -> str | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 100 <= v <= 900:
        return None
    return None if isinstance(v, str) and v in WEIGHTS else "must be a font weight (e.g. 'bold' or 100–900)"


def _cmap_check(v: Any) -> str | None:
    return None if isinstance(v, str) and re.match(r"^[A-Za-z0-9_.:-]+$", v) else "must be a colormap name"


_color = _described(_color_check, type="color")
_bool = _described(_bool_check, type="bool")
_str = _described(_str_check, type="text")
_weight = _described(_weight_check, type="enum", options=["normal", "bold", "light", "semibold", "heavy"])
_cmap = _described(_cmap_check, type="text")


_ALPHA = _num(0, 1)
_WIDTH = _num(0, 100, "pt")
_SIZE = _num(0.1, 500, "pt")

PROPS: dict[str, dict[str, Callable[[Any], str | None]]] = {
    "text": {
        "text": _str, "fontsize": _SIZE, "fontweight": _weight, "fontstyle": _enum(FONTSTYLES),
        "fontfamily": _str, "color": _color, "alpha": _ALPHA, "visible": _bool, "rotation": _num(-360, 360),
    },
    "line": {
        "color": _color, "linewidth": _WIDTH, "linestyle": _enum(LINESTYLES), "alpha": _ALPHA, "visible": _bool,
        "marker": _enum(MARKERS), "markersize": _num(0, 100, "pt"), "markerfacecolor": _color, "markeredgecolor": _color,
    },
    "patch": {
        "facecolor": _color, "edgecolor": _color, "color": _color, "linewidth": _WIDTH,
        "linestyle": _enum(LINESTYLES), "alpha": _ALPHA, "visible": _bool, "hatch": _str,
    },
    "collection": {
        "facecolor": _color, "edgecolor": _color, "color": _color, "linewidth": _WIDTH, "alpha": _ALPHA,
        "visible": _bool, "size": _num(0, 10000), "cmap": _cmap, "vmin": _num(), "vmax": _num(),
    },
    "image": {"alpha": _ALPHA, "visible": _bool, "cmap": _cmap, "vmin": _num(), "vmax": _num()},
    "axes": {"facecolor": _color, "visible": _bool},
    "axis": {"visible": _bool},
    "spine": {"visible": _bool, "linewidth": _WIDTH, "color": _color},
    "legend": {
        "visible": _bool, "loc": _enum(LEGEND_LOCS), "frameon": _bool, "fontsize": _SIZE, "title": _str,
    },
}

# Properties that only make sense on one artist, never on a group or a wildcard.
SINGLE_ONLY = {"text", "title"}


def allowed(kind: str) -> list[str]:
    return sorted(PROPS.get(kind, {}))


def describe() -> dict:
    """The property table as JSON: ``{kinds: {kind: {prop: {type, min?, max?, unit?, options?}}}, single_only}``."""
    return {
        "kinds": {kind: {prop: dict(check.spec) for prop, check in table.items()}  # type: ignore[attr-defined]
                  for kind, table in PROPS.items()},
        "single_only": sorted(SINGLE_ONLY),
    }


def validate(kind: str, props: dict, *, group: bool = False) -> list[str]:
    """Problems with setting ``props`` on a part of ``kind`` (empty list: valid)."""
    table = PROPS.get(kind)
    if table is None:
        return [f"parts of kind {kind!r} cannot be styled"]
    problems = []
    for key, value in props.items():
        check = table.get(key)
        if check is None:
            problems.append(f"{key!r} is not a {kind} property (allowed: {', '.join(sorted(table))})")
            continue
        if group and key in SINGLE_ONLY:
            problems.append(f"{key!r} can only be set on a single part, not a group")
            continue
        msg = check(value)
        if msg:
            problems.append(f"{key} {msg}")
    return problems
