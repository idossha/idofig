"""Post-process matplotlib's SVG into an idofig panel: stable, attributed, font-portable.

String-level and conservative: matplotlib's output is regular, and a parser round-trip
would reorder namespaces and change bytes for no reason.
"""

from __future__ import annotations

import re

from .mplsetup import FONT_FAMILY, SVG_FONT_STACK

_DECL = re.compile(r"^<\?xml[^>]*\?>\s*", re.S)
_DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>\s*", re.S)
_METADATA = re.compile(r"\s*<metadata>.*?</metadata>", re.S)
_ROOT = re.compile(r"<svg\b([^>]*)>")


def _num(v: float) -> str:
    """A matrix entry, fixed to 6 places without trailing zeros (the same number, the same bytes)."""
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def transform_groups(svg: str, matrices: dict[str, tuple[float, ...]]) -> tuple[str, list[str]]:
    """Put ``transform="matrix(…)"`` on the first ``<g id="<name>">`` of each name (an axes'
    group, which holds everything drawn in it); returns the SVG and the names not found."""
    missing = []
    for name, m in matrices.items():
        tag = f'<g id="{name}">'
        if tag not in svg:
            missing.append(name)
            continue
        svg = svg.replace(tag, f'<g id="{name}" transform="matrix({" ".join(map(_num, m))})">', 1)
    return svg, missing


def wrap_images(svg: str, names: list[str]) -> str:
    """Give an image and its dedicated clip group one stable transformable parent.

    Matplotlib puts the clip outside the named image; transforming just the image moves it
    through stationary clipping. The native flip stays inside this wrapper unchanged.
    """
    for name in names:
        image = re.search(r'<image\b(?=[^>]*\bid="' + re.escape(name) + r'")[^>]*(?:/>|>.*?</image>)', svg, re.S)
        if image is None:
            continue
        start, end = image.span()
        clip = re.search(r'<g clip-path="[^"]+">\s*$', svg[:start])
        close = re.match(r'\s*</g>', svg[end:])
        if clip is not None and close is not None:
            start, end = clip.start(), end + close.end()
        native = svg[start:end].replace(f' id="{name}"', '', 1)
        svg = svg[:start] + f'<g id="{name}">{native}</g>' + svg[end:]
    return svg


def finish_panel_svg(svg: str, *, panel: str, roles: dict[str, str]) -> str:
    svg = _DECL.sub("", svg)
    svg = _DOCTYPE.sub("", svg)
    svg = _METADATA.sub("", svg)
    svg = svg.replace(f"font-family: '{FONT_FAMILY}'", f"font-family: {SVG_FONT_STACK}")

    def root(m: re.Match) -> str:
        attrs = m.group(1)
        return f'<svg{attrs} data-idofig-panel="{panel}">'

    svg = _ROOT.sub(root, svg, count=1)
    for name, role in roles.items():
        svg = svg.replace(f'<g id="{name}"', f'<g id="{name}" data-idofig-role="{role}"', 1)
    if not svg.endswith("\n"):
        svg += "\n"
    return '<?xml version="1.0" encoding="utf-8"?>\n' + svg
