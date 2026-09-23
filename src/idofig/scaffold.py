"""Create projects, figures and panels from templates (``idofig init/new/add-panel``)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from . import journals as J
from . import spec as S
from .errors import IdofigError
from .fsutil import rel, write_atomic, write_json
from .project import Project, check_id

TEMPLATES = ("bar", "line", "scatter", "heatmap", "blank")
GAP_MM = 4.0


def init_project(root: Path, *, journal: str = "suna", figures: str = "figures") -> Path:
    root = root.resolve()
    cfg = root / "idofig.toml"
    if (root / "pyproject.toml").is_file() and "[tool.idofig]" in (root / "pyproject.toml").read_text("utf-8"):
        return root / "pyproject.toml"
    if cfg.exists():
        return cfg
    write_atomic(cfg, f'figures = "{figures}"\njournal = "{journal}"\n')
    (root / figures).mkdir(parents=True, exist_ok=True)
    return cfg


def new_figure(project: Project, fid: str, *, width: dict | None = None, extra: dict | None = None) -> Path:
    check_id("figure", fid)
    path = project.figure_json(fid)
    if path.exists():
        raise IdofigError(f"{rel(path, project.root)} already exists")
    doc = S.new_figure(fid, width=width)
    if extra:
        for k, v in extra.items():
            if k not in S.OWNED_KEYS:
                doc[k] = v
    problems = S.validate_figure(doc, expected_id=fid)
    if problems:
        raise IdofigError("; ".join(problems))
    write_json(path, doc)
    return path


def next_place(project: Project, doc: dict, *, w: float | None = None, h: float = 50.0) -> dict:
    """Where a new panel goes: the next slot in reading order, half the figure wide."""
    journal = J.load(doc.get("journal") or project.journal, str(project.root))
    width = J.width_mm(journal, doc["width"])
    w = w or round((width - GAP_MM) / 2, 2)
    panels = doc.get("panels", [])
    if not panels:
        return {"x": 0.0, "y": 0.0, "w": w, "h": h}
    last = panels[-1]["place"]
    x = last["x"] + last["w"] + GAP_MM
    if x + w <= width + 0.01:
        return {"x": round(x, 2), "y": last["y"], "w": w, "h": h}
    bottom = max(p["place"]["y"] + p["place"]["h"] for p in panels)
    return {"x": 0.0, "y": round(bottom + GAP_MM, 2), "w": w, "h": h}


def _next_letter(doc: dict) -> str | None:
    used = {p.get("letter") for p in doc.get("panels", [])}
    for c in "abcdefghijklmnopqrstuvwxyz":
        if c not in used:
            return c
    return None


def add_panel(project: Project, fid: str, pid: str, *, template: str = "bar", script: str | None = None,
              place: dict | None = None, letter: str | None = "auto") -> dict:
    """Register a panel and (unless ``script`` names an existing producer) write a producer for it."""
    check_id("panel", pid)
    if template not in TEMPLATES:
        raise IdofigError(f"unknown template {template!r}; choose from {', '.join(TEMPLATES)}")
    path = project.figure_json(fid)
    doc = S.load_figure(path)
    if S.panel_entry(doc, pid):
        raise IdofigError(f"panel {pid!r} already exists in {fid}")
    ops: list[dict] = []
    entry = {"op": "panel.add", "id": pid, "place": place or next_place(project, doc)}
    lt = _next_letter(doc) if letter == "auto" else letter
    if lt:
        entry["letter"] = lt
    ops.append(entry)
    created = None
    if script:
        existing = next((p for p in doc.get("producers", []) if script in p.get("run", [])), None)
        if existing:
            ops.append({"op": "producer.set", "id": existing["id"], "panels": [*existing["panels"], pid]})
        else:
            ops.append({"op": "producer.set", "id": pid, "run": ["python", script], "panels": [pid]})
    else:
        script = rel(project.figure_dir(fid) / f"{pid}.py", project.root)
        target = project.root / script
        if target.exists():
            raise IdofigError(f"{script} already exists; pass --script {script} to use it")
        text = resources.files("idofig").joinpath("templates", f"{template}.py").read_text(encoding="utf-8")
        text = text.replace("{{figure}}", fid).replace("{{panel}}", pid).replace("{{script}}", script)
        write_atomic(target, text)
        created = script
        ops.append({"op": "producer.set", "id": pid, "run": ["python", script], "inputs": [], "panels": [pid]})
    S.update_figure(path, ops)
    return {"figure": fid, "panel": pid, "script": script, "created": created}
