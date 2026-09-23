"""Journal figure presets: column widths, font floors, line weights, panel-label style.

The bundled presets are the ``figures`` sections of SUNA's sourced publisher profiles,
copied verbatim (``journals/*.json``). A ``null`` means the journal states no number,
and idofig then states none either: asking for ``{"preset": "onehalf"}`` against a
journal with no one-and-a-half width is an error, never a guess.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .errors import SpecError

WIDTH_PRESETS = ("single", "onehalf", "double")


@lru_cache(maxsize=None)
def bundled_ids() -> tuple[str, ...]:
    files = resources.files("idofig").joinpath("journals")
    return tuple(sorted(p.name[:-5] for p in files.iterdir() if p.name.endswith(".json")))


@lru_cache(maxsize=64)
def load(ref: str, root: str | None = None) -> dict:
    """A preset by bundled id, or by path (absolute, or relative to the project root)."""
    if ref in bundled_ids():
        text = resources.files("idofig").joinpath("journals", f"{ref}.json").read_text(encoding="utf-8")
        return json.loads(text)
    path = Path(ref)
    if not path.is_absolute() and root:
        path = Path(root) / path
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        # A full SUNA profile carries the figure preset under "figures".
        if "figures" in data and "widthPresetsMm" not in data:
            fig = dict(data["figures"])
            fig.setdefault("id", data.get("id", path.stem))
            fig.setdefault("name", data.get("journalName", fig["id"]))
            return fig
        return data
    raise SpecError(
        "journal", [f"unknown journal {ref!r}; bundled: {', '.join(bundled_ids())}, or give a path to a JSON preset"]
    )


def width_mm(journal: dict, width: dict) -> float:
    """Resolve a figure.json ``width`` object to millimetres."""
    if "mm" in width:
        return float(width["mm"])
    preset = width.get("preset")
    value = (journal.get("widthPresetsMm") or {}).get(preset)
    if value is None:
        raise SpecError(
            "figure.json",
            [
                f"journal {journal.get('id')!r} states no {preset!r} width; "
                'set "width": {"mm": <number>} instead'
            ],
        )
    return float(value)


def letter_style(journal: dict, override: dict | None) -> dict:
    """Panel-letter style: journal convention first, then the figure's own override."""
    label = journal.get("panelLabel") or {}
    style = {
        "show": True,
        "case": label.get("letterCase") or "lower",
        "weight": label.get("weight") or "bold",
        "wrapper": label.get("wrapper") or "none",
        "size_pt": 8.0,
        "offset_mm": [0.0, 0.0],
    }
    if override:
        style.update({k: v for k, v in override.items() if v is not None})
    return style


def format_letter(letter: str, style: dict) -> str:
    text = letter.upper() if style.get("case") == "upper" else letter.lower()
    wrapper = style.get("wrapper")
    if wrapper == "parens":
        return f"({text})"
    if wrapper == "period":
        return f"{text}."
    return text
