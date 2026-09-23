"""Find where in a producer's code a named part is made ("open where it's defined").

Best effort and honest about it: text parts are found by their literal text, series by
their label, axes by their ``idofig.name`` call. Every hit is a candidate with the line
that matched; nothing is guessed when nothing matches.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import spec as S
from .fsutil import read_json
from .project import Project

_CALLS = {
    "xlabel": [r"set_xlabel\(", r"xlabel\("],
    "ylabel": [r"set_ylabel\(", r"ylabel\("],
    "title": [r"set_title\(", r"title\("],
    "suptitle": [r"suptitle\("],
}


def _needles(name: str, part: dict) -> list[str]:
    props = part.get("base") or {}
    text = props.get("text") or (part.get("props") or {}).get("text")
    role = part.get("role")
    out: list[str] = []
    if text:
        out.append(text)
    if role in {"series", "mark"}:
        label = name.split(".series.", 1)[-1].split(".")[0]
        out.append(f'label="{label}')
        out.append(f"label='{label}")
    if part.get("kind") == "axes" and part.get("stability") == "named":
        out.append(f'"{name}"')
        out.append(f"'{name}'")
    return [n for n in out if n]


def locate(project: Project, fid: str, pid: str, name: str) -> list[dict]:
    doc = S.load_figure(project.figure_json(fid))
    producer = S.producer_of(doc, pid)
    if producer is None:
        return []
    try:
        man = read_json(project.panel_dir(fid, pid) / "manifest.json")
    except FileNotFoundError:
        return []
    part = man.get("parts", {}).get(name)
    if part is None:
        return []
    files: list[Path] = []
    for arg in producer.get("run", [])[1:]:
        p = project.root / arg
        if p.suffix == ".py" and p.is_file():
            files.append(p)
    try:
        lock = read_json(project.figure_dir(fid) / "figure.lock.json")
        for f in lock.get("producers", {}).get(producer["id"], {}).get("discovered", []):
            p = project.root / f
            if p.is_file() and p not in files:
                files.append(p)
    except (FileNotFoundError, ValueError):
        pass
    needles = _needles(name, part)
    role_calls = _CALLS.get(part.get("role", ""), [])
    hits: list[dict] = []
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, start=1):
            score = 0
            if any(n in line for n in needles):
                score += 2
            if any(re.search(c, line) for c in role_calls):
                score += 1
            if score >= 2 or (score == 1 and not needles and role_calls):
                hits.append({"file": f.relative_to(project.root).as_posix(), "line": i, "text": line.strip(),
                             "score": score})
    hits.sort(key=lambda h: (-h["score"], h["file"], h["line"]))
    return hits[:10]
