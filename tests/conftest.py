from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from idofig.project import find_project

PRODUCER = '''
import json
from pathlib import Path
import idofig as idf

data = json.loads(Path("data/values.json").read_text())
p = idf.panels(*{panels!r})
for pid, f in p.items():
    ax = f.subplots()
    idf.name(ax, "main")
    ax.bar(data["groups"], data["control"], label="control", color="#0072B2")
    ax.plot(range(len(data["groups"])), data["line"], label="trend", color="#D55E00")
    ax.set_xlabel("condition")
    ax.set_ylabel("response")
    ax.set_title(f"panel {{pid}}")
    ax.legend()
idf.save(p)
'''


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("IDOFIG_ROOT", "IDOFIG_FIGURE", "IDOFIG_OUTPUT_DIR", "IDOFIG_ONLY", "IDOFIG_JOURNAL"):
        monkeypatch.delenv(k, raising=False)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return path


def make_project(root: Path, *, panels=("a", "b"), journal="nature") -> Path:
    write(root / "idofig.toml", f'journal = "{journal}"\n')
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "values.json").write_text(
        json.dumps({"groups": ["A", "B", "C"], "control": [1.0, 2.0, 1.5], "line": [1.2, 1.8, 1.6]}),
        encoding="utf-8",
    )
    fig = {
        "schema": 2,
        "id": "fig-1",
        "width": {"preset": "double"},
        "producers": [
            {"id": "make", "run": ["python", "figures/fig-1/make.py"], "inputs": ["data/values.json"],
             "panels": list(panels)}
        ],
        "panels": [
            {"id": pid, "letter": chr(ord("a") + i), "place": {"x": i * 92.0, "y": 0, "w": 88, "h": 60}}
            for i, pid in enumerate(panels)
        ],
        "annotations": [],
        "caption": {"title": "A test figure."},
    }
    write(root / "figures" / "fig-1" / "figure.json", json.dumps(fig, indent=2) + "\n")
    write(root / "figures" / "fig-1" / "make.py", PRODUCER.format(panels=tuple(panels)))
    return root


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = make_project(tmp_path / "proj")
    monkeypatch.chdir(root)
    return find_project(root)


def read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def env_python() -> str:
    return os.environ.get("PYTHON", "python")
