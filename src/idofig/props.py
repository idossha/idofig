"""The style properties a canvas or an agent may set on a named part, by part kind.

This module is pure (no matplotlib) so the server can validate an edit before it is
written. ``style.apply`` in the drawing process maps each property to a matplotlib setter.

A part's *kind* is recorded in its panel manifest:

``text`` ``line`` ``patch`` ``collection`` ``image`` ``axes`` ``axis`` ``spine`` ``legend``
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable

from ._colornames import NAMES as COLOR_NAMES

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_CYCLE = re.compile(r"C[0-9]")
_GRAY = re.compile(r"0(?:\.\d+)?|1(?:\.0+)?")

LINESTYLES = {"-", "--", ":", "-.", "solid", "dashed", "dotted", "dashdot", "none", "None", ""}
MARKERS = {"", " ", "*", "+", ",", ".", "1", "2", "3", "4", "8", "<", ">", "D", "H", "None", "P", "X",
           "^", "_", "d", "h", "none", "o", "p", "s", "v", "x", "|"}
WEIGHTS = {"ultralight", "light", "normal", "regular", "book", "medium", "roman", "semibold",
           "demibold", "demi", "bold", "heavy", "extra bold", "black"}
FONTSTYLES = {"normal", "italic", "oblique"}
LEGEND_LOCS = {"best", "upper right", "upper left", "lower left", "lower right", "right", "center left",
               "center right", "lower center", "upper center", "center"}


def is_color(value: Any) -> bool:
    """Whether matplotlib takes ``value`` as a colour, read as it reads one: a one-letter name in
    lower case only, a longer one in any case, nothing around it (fullmatch: a `$` let "#fff\\n"
    through). Stripped and lower-cased, 'K' and ' red ' passed, and `set_color` raised at the draw."""
    if not isinstance(value, str):
        return False
    return bool(
        value.lower() == "none" or _HEX.fullmatch(value) or _CYCLE.fullmatch(value) or _GRAY.fullmatch(value)
        or (value if len(value) == 1 else value.lower()) in COLOR_NAMES
    )


# The spellings only matplotlib knows, as the hex they stand for, so figure.svg holds colours CSS
# knows: every SVG renderer drops `fill: C1` or `fill: 0.5`, and a letter came out black. C0–C9
# are matplotlib's default cycle (compose never imports matplotlib to read a project's own).
_TAB10 = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
          "#17becf")
_MATPLOTLIB_ONLY = {
    "b": "#0000ff", "g": "#008000", "r": "#ff0000", "c": "#00bfbf", "m": "#bf00bf", "y": "#bfbf00", "k": "#000000",
    "w": "#ffffff",
    **{f"tab:{n}": h for n, h in zip(("blue", "orange", "green", "red", "purple", "brown", "pink", "gray", "olive",
                                      "cyan"), _TAB10)},
    **{f"C{i}": h for i, h in enumerate(_TAB10)},
}


def css_color(value: str) -> str:
    """A colour :func:`is_color` accepts, as CSS writes it."""
    if _GRAY.fullmatch(value):
        return "#" + format(round(float(value) * 255), "02x") * 3  # as matplotlib's to_hex rounds
    return _MATPLOTLIB_ONLY.get(value) or _MATPLOTLIB_ONLY.get(value.lower()) or value  # "Tab:Blue" too


Check = Callable[[Any], "str | None"]


def _described(check: Check, **spec: Any) -> Check:
    """Attach a JSON description, so an application can build its editors from this table."""
    check.spec = {k: v for k, v in spec.items() if v is not None}  # type: ignore[attr-defined]
    return check


def is_finite_number(v: Any) -> bool:
    """A number matplotlib can take: a finite float, or an int small enough to be one. NaN passes
    every bound (`dx_mm: NaN` was listed applied and emptied its part from the SVG), and a
    310-digit int raised OverflowError out of the check, failing the whole producer."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


def _num(lo: float | None = None, hi: float | None = None, unit: str | None = None) -> Check:
    def check(v: Any) -> str | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "must be a number"
        if not is_finite_number(v):
            return "must be a finite number"
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
_OFFSET = _num(unit="mm")

# A part's move from where the script drew it, in mm with y down. Applied after the layout
# is frozen (``styling.apply_offsets``), so the part lands exactly that far away. An axes moves
# with everything drawn in it (0.6.0).
OFFSETS = ("dx_mm", "dy_mm")
# Uniform scale and clockwise turn about each artist's box centre, after layout.
# Identity (1, 0) writes nothing; all kinds share the same validators below.
TRANSFORMS = ("scale", "rotate")
_ROTATE = _num(unit="deg")
TICK_MARKS = ("tickdir", "ticklength", "tickwidth")
# A 3D axes' view (0.11.0), applied before layout; an editor that orients a mesh writes them.
VIEW = ("elev", "azim", "roll", "zoom", "proj")

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
    "axes": {
        "facecolor": _color, "visible": _bool, "elev": _num(-180, 180, "deg"), "azim": _num(-180, 180, "deg"),
        "roll": _num(-180, 180, "deg"), "zoom": _num(0.1, 10), "proj": _enum({"ortho", "persp"}),
    },
    "axis": {"visible": _bool, "tickdir": _enum({"in", "out", "inout"}), "ticklength": _WIDTH, "tickwidth": _WIDTH},
    "spine": {"visible": _bool, "linewidth": _WIDTH, "color": _color},
    "legend": {
        "visible": _bool, "loc": _enum(LEGEND_LOCS), "frameon": _bool, "fontsize": _SIZE, "title": _str,
    },
}

# Properties that only make sense on one artist, never on a group or a wildcard.
SINGLE_ONLY = {"text", "title"}

# Geometry is available for every artist; only unsupported matplotlib setters are refused.
REFUSED_BY_ROLE = {
    "axis3d": dict.fromkeys(TICK_MARKS, "a 3D axis draws its tick marks from its own settings, not from tick_params"),
    "axes": dict.fromkeys(VIEW, "only a 3D axes has a view"),
    "colorbar": dict.fromkeys(VIEW, "only a 3D axes has a view"),
}


def _positive(v: Any) -> str | None:
    problem = _num()(v)
    return problem or ("must be positive" if v <= 0 else None)


_SCALE = _described(_positive, type="number", exclusiveMin=0)
for _table in PROPS.values():
    _table.update(dx_mm=_OFFSET, dy_mm=_OFFSET, scale=_SCALE, rotate=_ROTATE)


def allowed(kind: str) -> list[str]:
    return sorted(PROPS.get(kind, {}))


def describe() -> dict:
    """The property table as JSON: ``{kinds: {kind: {prop: {type, min?, max?, unit?, options?}}},
    single_only, refused_by_role: {role: [prop…]}}``."""
    return {
        "kinds": {kind: {prop: dict(check.spec) for prop, check in table.items()}  # type: ignore[attr-defined]
                  for kind, table in PROPS.items()},
        "single_only": sorted(SINGLE_ONLY),
        "refused_by_role": {role: sorted(props) for role, props in REFUSED_BY_ROLE.items()},
    }


def validate(kind: str, props: dict, *, group: bool = False, role: str | None = None) -> list[str]:
    """Problems with setting ``props`` on a part of ``kind`` (and ``role``, as the manifest
    records it) — an empty list means valid."""
    table = PROPS.get(kind)
    if table is None:
        return [f"parts of kind {kind!r} cannot be styled"]
    refused = REFUSED_BY_ROLE.get(role, {})
    problems = []
    for key, value in props.items():
        check = table.get(key)
        if check is None:
            problems.append(f"{key!r} is not a {kind} property (allowed: {', '.join(sorted(table))})")
            continue
        if group and key in SINGLE_ONLY:
            problems.append(f"{key!r} can only be set on a single part, not a group")
            continue
        if key in refused:
            problems.append(f"{key}: {refused[key]}")
            continue
        msg = check(value)
        if msg:
            problems.append(f"{key} {msg}")
    return problems
