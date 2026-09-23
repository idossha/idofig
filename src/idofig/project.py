"""Where a project is, where its figures live, and which journal it is written for.

A project is the nearest ancestor directory that has any of:

* ``idofig.toml``
* ``pyproject.toml`` with a ``[tool.idofig]`` table
* ``suna.json`` (a SUNA project; its ``directories.figures`` is honoured)

``IDOFIG_ROOT`` overrides the search. Configuration keys (all optional):

``figures``  directory holding ``<figure-id>/figure.json`` (default ``figures``)
``journal``  a bundled journal id (``nature``, ``science``, ...) or a path to a JSON file
             with the same shape (default ``suna``)

In a SUNA project without its own setting, the figures directory is ``suna.json``'s
``directories.figures`` and the journal is ``suna.json``'s ``activeProfileId`` when idofig
bundles a preset of that id — so switching the journal in SUNA and building from a
terminal give the same figures.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ContextError

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def check_id(kind: str, value: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value) or ".." in value:
        raise ContextError(
            f"{kind} id {value!r} is not valid: use lowercase letters, digits, '-', '_' or '.', "
            "starting with a letter or digit"
        )
    return value


@dataclass
class Project:
    root: Path
    figures_dir: Path
    journal: str = "suna"
    config: dict = field(default_factory=dict)

    def figure_dir(self, figure_id: str) -> Path:
        check_id("figure", figure_id)
        return self.figures_dir / figure_id

    def figure_json(self, figure_id: str) -> Path:
        return self.figure_dir(figure_id) / "figure.json"

    def panel_dir(self, figure_id: str, panel_id: str) -> Path:
        check_id("panel", panel_id)
        return self.figure_dir(figure_id) / "panels" / panel_id

    def figure_ids(self) -> list[str]:
        if not self.figures_dir.is_dir():
            return []
        return sorted(
            p.name for p in self.figures_dir.iterdir() if (p / "figure.json").is_file() and ID_RE.match(p.name)
        )

    @property
    def state_dir(self) -> Path:
        """Machine-local scratch (staging, last errors). Never committed."""
        d = self.root / ".idofig"
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            (d / ".gitignore").write_text("*\n", encoding="utf-8")
        return d


def _read_toml_table(path: Path) -> dict | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if path.name == "idofig.toml":
        return data.get("tool", {}).get("idofig", data)
    tool = data.get("tool", {})
    return tool.get("idofig") if isinstance(tool, dict) and "idofig" in tool else None


def _is_root(d: Path) -> dict | None:
    """The project config if ``d`` is a project root, else None."""
    if (d / "idofig.toml").is_file():
        return _read_toml_table(d / "idofig.toml") or {}
    if (d / "pyproject.toml").is_file():
        table = _read_toml_table(d / "pyproject.toml")
        if table is not None:
            return table
    if (d / "suna.json").is_file():
        return {}
    return None


def find_project(start: Path | str | None = None) -> Project:
    env = os.environ.get("IDOFIG_ROOT")
    if env:
        root = Path(env).resolve()
        cfg = _is_root(root) or {}
        return _make(root, cfg)
    here = Path(start or os.getcwd()).resolve()
    if here.is_file():
        here = here.parent
    for d in [here, *here.parents]:
        cfg = _is_root(d)
        if cfg is not None:
            return _make(d, cfg)
    raise ContextError(
        f"no idofig project found at or above {here}. Create one with `idofig init`, or add a "
        "[tool.idofig] table to pyproject.toml, or set IDOFIG_ROOT."
    )


def _suna(root: Path) -> dict:
    try:
        data = json.loads((root / "suna.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _make(root: Path, cfg: dict) -> Project:
    suna = _suna(root) if (root / "suna.json").is_file() else {}
    figures = cfg.get("figures")
    if not figures:
        dirs = suna.get("directories")
        figures = dirs.get("figures") if isinstance(dirs, dict) else None
    figures_dir = (root / (figures or "figures")).resolve()
    if root not in figures_dir.parents and figures_dir != root:
        raise ContextError(f"figures directory {figures!r} must be inside the project {root}")
    journal = os.environ.get("IDOFIG_JOURNAL") or cfg.get("journal")
    if not journal:
        from .journals import bundled_ids

        active = suna.get("activeProfileId")
        journal = active if isinstance(active, str) and active in bundled_ids() else "suna"
    return Project(root=root, figures_dir=figures_dir, journal=str(journal), config=dict(cfg))
