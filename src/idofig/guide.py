"""The docs an agent reads, and the skill that points to them (``idofig docs``, ``idofig skill``;
0.13.0).

The knowledge an agent needs ships with idofig — ``docs/agents.md``, ``docs/producers.md``,
``SPEC.md`` — so it always matches the version a project runs; the skill installed into a
harness's skill directory only says where it is. A wheel carries the docs under
``idofig/docs/``; a checkout (or an editable install) reads them from the repository. Standard
library only, like every command that does not draw.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

from .errors import IdofigError
from .fsutil import write_atomic

# name → path in the repository; a wheel ships each as idofig/docs/<its file name>
DOCS = {"agents": "docs/agents.md", "producers": "docs/producers.md", "spec": "SPEC.md",
        "readme": "README.md", "changelog": "CHANGELOG.md"}
SKILL_MARKER = "<!-- idofig:managed-skill"
SKILL_NAME = "idofig"


def doc_paths() -> dict[str, Path]:
    """Where each of :data:`DOCS` is for this idofig: the copies a wheel ships, else the
    repository this package was imported from."""
    here = Path(__file__).resolve().parent
    shipped = {name: here / "docs" / Path(path).name for name, path in DOCS.items()}
    if all(p.is_file() for p in shipped.values()):
        return shipped
    root = here.parents[1]
    checkout = {name: root / path for name, path in DOCS.items()}
    if all(p.is_file() for p in checkout.values()):
        return checkout
    raise IdofigError(f"this idofig ({here}) carries no docs: reinstall it from a wheel or a checkout")


def skill_text() -> str:
    """The pointer skill this idofig installs."""
    return resources.files("idofig").joinpath("skill", "SKILL.md").read_text(encoding="utf-8")


def skill_targets(*, project_root: Path | None = None, dirs: list[str] | None = None) -> list[Path]:
    """Where ``idofig skill install`` writes: each of ``dirs`` (a harness's skill directory), else
    the project's ``.claude/skills``, else the user's ``~/.claude/skills`` and, when it exists,
    ``~/.agents/skills`` (Codex, Pi). Each gets ``idofig/SKILL.md``."""
    if dirs:
        roots = [Path(d).expanduser() for d in dirs]
    elif project_root is not None:
        roots = [project_root / ".claude" / "skills"]
    else:
        home = Path(os.environ.get("HOME") or Path.home())
        roots = [home / ".claude" / "skills"]
        if (home / ".agents" / "skills").is_dir():
            roots.append(home / ".agents" / "skills")
    return [r / SKILL_NAME / "SKILL.md" for r in roots]


def _foreign(path: Path) -> str | None:
    """Why ``path`` is not idofig's to rewrite, or None: a link (to another owner's copy, which a
    write would change through it) or a file without the managed marker (one a user wrote)."""
    if path.parent.is_symlink():
        return f"{path.parent} is a link to {os.readlink(path.parent)}"
    if path.is_symlink():
        return f"{path} is a link to {os.readlink(path)}"
    if path.exists() and SKILL_MARKER not in path.read_text(encoding="utf-8", errors="replace"):
        return f"{path} was not written by idofig (it has no managed marker)"
    return None


def install_skill(targets: list[Path], *, force: bool = False) -> list[dict]:
    """Write the pointer skill to each target; returns ``{path, action}`` per target, action
    ``written``, ``updated`` or ``current``. A target another owner holds (a link, or a file
    without the marker) is refused — every target is checked before any is written — unless
    ``force``, which replaces the link itself (never what it points to) or the file."""
    text = skill_text()
    refused = [(t, why) for t in targets if (why := _foreign(t))]
    if refused and not force:
        lines = "; ".join(why for _, why in refused)
        raise IdofigError(f"not replacing another owner's skill: {lines}. Remove it, or pass --force")
    out = []
    for target in targets:
        if target.parent.is_symlink():
            target.parent.unlink()
        if target.is_symlink():
            target.unlink()
        if target.is_file():
            current = target.read_text(encoding="utf-8", errors="replace")
            if current == text:
                out.append({"path": str(target), "action": "current"})
                continue
            action = "updated"
        else:
            action = "written"
        target.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(target, text)
        out.append({"path": str(target), "action": action})
    return out
