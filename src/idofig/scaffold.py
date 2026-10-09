"""Create projects, figures and panels from templates (``idofig init/new/add-panel``)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from . import journals as J
from . import spec as S
from .errors import IdofigError
from .fsutil import rel, write_atomic, write_json
from .project import Project, check_id

TEMPLATES = ("bar", "line", "scatter", "heatmap", "blank", "mesh")
MESH_SUFFIXES = (".glb", ".gltf", ".stl", ".ply", ".obj")  # what idofig.mesh reads (with trimesh)
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


def add_image_panel(project: Project, fid: str, pid: str, image: str, *, place: dict | None = None,
                    letter: str | None = "auto") -> dict:
    """Register a panel that places an image file as it is — no producer. The file must be
    inside the project (applications copy one in first); its natural aspect sizes the
    default place, so it is never stretched."""
    from .images import IMAGE_SUFFIXES, natural_size

    check_id("panel", pid)
    path = project.figure_json(fid)
    doc = S.load_figure(path)
    if S.panel_entry(doc, pid):
        raise IdofigError(f"panel {pid!r} already exists in {fid}")
    src = (project.root / image).resolve()
    if project.root.resolve() not in src.parents:
        raise IdofigError(f"{image} is outside the project; copy it into figures/{fid}/ first")
    if src.suffix.lower() not in IMAGE_SUFFIXES:
        raise IdofigError(f"{image}: an image panel takes {', '.join(sorted(IMAGE_SUFFIXES))}")
    if not src.is_file():
        raise IdofigError(f"{image} does not exist")
    if place is None:
        place = next_place(project, doc)
        size = natural_size(src)
        if size and size[0] > 0:
            place["h"] = round(place["w"] * size[1] / size[0], 2)
    entry = {"op": "panel.add", "id": pid, "place": place, "image": rel(src, project.root)}
    lt = _next_letter(doc) if letter == "auto" else letter
    if lt:
        entry["letter"] = lt
    S.update_figure(path, [entry])
    return {"figure": fid, "panel": pid, "script": None, "created": None, "image": entry["image"]}


def _mesh_input(project: Project, mesh: str) -> str:
    """``mesh`` as the project-relative path a producer reads and lists in its inputs."""
    src = (project.root / mesh).resolve()
    if project.root.resolve() not in src.parents:
        raise IdofigError(f"{mesh} is outside the project; copy it in (data/, say) first")
    if src.suffix.lower() not in MESH_SUFFIXES:
        raise IdofigError(f"{mesh}: a mesh is one of {', '.join(MESH_SUFFIXES)}")
    if not src.is_file():
        raise IdofigError(f"{mesh} does not exist")
    return rel(src, project.root)


def add_panel(project: Project, fid: str, pid: str, *, template: str | None = None, script: str | None = None,
              place: dict | None = None, letter: str | None = "auto", mesh: str | None = None) -> dict:
    """Register a panel and (unless ``script`` names an existing producer) write a producer for it.
    ``template="mesh"`` (implied by ``mesh``) draws the mesh file ``mesh`` on a 3D axes."""
    check_id("panel", pid)
    template = template or ("mesh" if mesh is not None else "bar")
    if template not in TEMPLATES:
        raise IdofigError(f"unknown template {template!r}; choose from {', '.join(TEMPLATES)}")
    if (template == "mesh") != (mesh is not None):
        raise IdofigError("the mesh template needs a mesh file (--mesh), and only it takes one")
    if mesh is not None and script:
        raise IdofigError("a mesh writes a producer from the mesh template; it takes no script")
    inputs = [_mesh_input(project, mesh)] if mesh is not None else []
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
        if inputs:  # a path is a Python string literal in the code, plain text in the docstring
            text = text.replace('"{{mesh}}"', repr(inputs[0])).replace("{{mesh}}", inputs[0])
        write_atomic(target, text)
        created = script
        ops.append({"op": "producer.set", "id": pid, "run": ["python", script], "inputs": inputs, "panels": [pid]})
    S.update_figure(path, ops)
    return {"figure": fid, "panel": pid, "script": script, "created": created}
