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
