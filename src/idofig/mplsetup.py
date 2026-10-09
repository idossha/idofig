"""Deterministic matplotlib settings: bundled fonts, journal sizes, SVG that diffs cleanly.

Every panel starts from matplotlib's defaults (a user's matplotlibrc never leaks in),
uses Liberation Sans (metric-compatible with Arial, bundled, so a layout computed on a
Linux CI box is the layout computed on a Mac), keeps text as ``<text>`` so sizes can be
measured, and fixes the hash salt so element ids do not change between runs.
"""

from __future__ import annotations

from importlib import resources

FONT_FAMILY = "Liberation Sans"
# How the font is named in the SVG: Arial on machines that have it (identical metrics),
# the bundled face everywhere else.
SVG_FONT_STACK = "Arial, 'Liberation Sans', Helvetica, sans-serif"
_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    from matplotlib import font_manager

    fonts = resources.files("idofig").joinpath("fonts")
    for name in ("Regular", "Bold", "Italic", "BoldItalic"):
        with resources.as_file(fonts.joinpath(f"LiberationSans-{name}.ttf")) as path:
            font_manager.fontManager.addfont(str(path))
    _registered = True


def _clamp(value: float, lo: float | None, hi: float | None) -> float:
    if lo is not None:
        value = max(value, lo)
    if hi is not None:
        value = min(value, hi)
    return value


def rc_for(journal: dict) -> dict:
    """rcParams for a journal preset. Sizes are house defaults (7 pt text, 6 pt ticks)
    moved inside the journal's stated floor/ceiling; where it states none, none applies."""
    lo, hi = journal.get("minFontPt"), journal.get("maxFontPt")
    text = _clamp(7.0, lo, hi)
    small = _clamp(6.0, lo, hi)
    lw = journal.get("lineWeightPt") or {}
    axes_lw = _clamp(0.6, lw.get("min"), lw.get("max"))
    line_lw = _clamp(1.0, lw.get("min"), lw.get("max"))
    min_dpi = (journal.get("formats") or {}).get("minDpi") or 300
    return {
        "font.family": [FONT_FAMILY],
        "font.size": text,
        "axes.titlesize": text,
        "axes.labelsize": text,
        "xtick.labelsize": small,
        "ytick.labelsize": small,
        "legend.fontsize": small,
        "legend.title_fontsize": text,
        "figure.titlesize": text,
        "figure.labelsize": text,
        "axes.linewidth": axes_lw,
        "xtick.major.width": axes_lw,
        "ytick.major.width": axes_lw,
        "xtick.minor.width": axes_lw * 0.75,
        "ytick.minor.width": axes_lw * 0.75,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "xtick.minor.size": 1.5,
        "ytick.minor.size": 1.5,
        "lines.linewidth": line_lw,
        "lines.markersize": 3.0,
        "patch.linewidth": axes_lw,
        "legend.frameon": False,
        "mathtext.fontset": "custom",
        "mathtext.rm": FONT_FAMILY,
        "mathtext.it": f"{FONT_FAMILY}:italic",
        "mathtext.bf": f"{FONT_FAMILY}:bold",
        "mathtext.sf": FONT_FAMILY,
        "svg.fonttype": "none",
        "svg.hashsalt": "idofig",
        "figure.dpi": 72,
        "savefig.dpi": max(600, int(min_dpi)),
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.bbox": None,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }


def apply_rc(journal: dict) -> None:
    """Reset to matplotlib defaults, then apply the journal preset."""
    import matplotlib  # here, not at the top: compose reads SVG_FONT_STACK and must not import it (rule 7)
    import matplotlib.pyplot as plt  # noqa: F401  (pyplot owns the global rc state people use)

    register_fonts()
    matplotlib.rcdefaults()
    matplotlib.rcParams.update(rc_for(journal))
