"""Moving an axes, or a named group of axes, within its panel (idofig 0.6.0, 2026-09-25):
`dx_mm`/`dy_mm` on an `axes` part, or on a pattern naming several (`row1.*`), move each axes'
box and everything drawn in it, once, after the layout is frozen.

Where the expected numbers come from: positions are read back from panel.svg with ElementTree
(an axes' background path, a text's x/y — what is printed) and compared with the offset given,
at 72/25.4 pt per mm; never from idofig's manifest, except where the manifest is the thing under
test (the trim box compose crops to). The panels are placed by hand with `axes_mm` at known
millimetres, and the constrained case is conftest's two-panel project.

Reproduce: `.venv/bin/python -m pytest tests/test_group_moves.py`.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import read, write

from idofig import props as P
from idofig import spec as S
from idofig.build import build

PT = 72 / 25.4
SVG = "{http://www.w3.org/2000/svg}"

BY_HAND = '''
import idofig as idf
p = idf.panels("a", layout=None)
f = p["a"]
for i, name in enumerate(("row.left", "row.right")):
    ax = idf.name(idf.axes_mm(f, 10 + i * 40, 15, 25, 20), name)
    ax.plot([0, 1], [0, 1], label="line")
    ax.set_xlabel("x")
    ax.set_title(name)
    ax.text(0.5, -0.4, "tag", transform=ax.transAxes, gid=f"{name}.tag")
    ax.imshow([[0, 1], [1, 0]], extent=(0, 1, 0, 1), aspect="auto")
    ax.legend(loc="upper left")
f.text(0.02, 0.95, "free", gid="free")
idf.save(p)
'''


def _project(tmp_path, monkeypatch, script):
    root = tmp_path / "proj"
    write(root / "idofig.toml", 'journal = "nature"\n')
    doc = {"schema": 2, "id": "fig-1", "width": {"preset": "double"},
           "producers": [{"id": "make", "run": ["python", "figures/fig-1/make.py"], "panels": ["a"]}],
           "panels": [{"id": "a", "place": {"x": 0, "y": 0, "w": 90, "h": 60}}], "annotations": []}
    write(root / "figures/fig-1/figure.json", json.dumps(doc))
    write(root / "figures/fig-1/make.py", script)
    monkeypatch.chdir(root)
    from idofig.project import find_project

    return find_project(root)


def _build(project, pid="a"):
    rep = build(project, ["fig-1"])
    assert rep.ok, rep
    return ET.fromstring(read(project.panel_dir("fig-1", pid) / "panel.svg"))


def _el(root, ident):
    return next(el for el in root.iter() if el.get("id") == ident)


def _frame(root, ident):
    d = next(_el(root, ident).iter(f"{SVG}path")).get("d")
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return min(nums[0::2]), min(nums[1::2])


def _text(root, ident):
    el = _el(root, ident)
    t = el if el.tag == f"{SVG}text" else next(el.iter(f"{SVG}text"))
    return float(t.get("x")), float(t.get("y"))


def _moved(before, after, ident, where=_text):
    (x0, y0), (x1, y1) = where(before, ident), where(after, ident)
    return round((x1 - x0) / PT, 3), round((y1 - y0) / PT, 3)


def _image(root, ident):
    """An image's corner: matplotlib writes it flipped (`scale(1 -1)`), so y is negated."""
    img = next(_el(root, ident).iter(f"{SVG}image"))
    return float(img.get("x")), -float(img.get("y"))


def test_an_axes_moves_with_everything_drawn_in_it_and_nothing_else_moves(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    before = _build(project)
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "row.right", {"dx_mm": -12, "dy_mm": 3})
    after = _build(project)
    assert _moved(before, after, "row.right.background", _frame) == (-12, 3)
    for part in ("row.right.xlabel", "row.right.title", "row.right.tag", "row.right.legend.line",
                 "row.right.xtick.0-0"):
        assert _moved(before, after, part) == (-12, 3), part
    # an image is snapped to whole pixels at the SVG's 72 dpi: within one pixel (0.353 mm)
    assert _moved(before, after, "row.right.image0", _image) == pytest.approx((-12, 3), abs=25.4 / 72)
    assert _moved(before, after, "row.left.background", _frame) == (0, 0)
    assert _moved(before, after, "row.left.xlabel") == (0, 0)
    assert _moved(before, after, "free") == (0, 0)


def test_a_pattern_moves_each_axes_it_names_once_with_its_parts(tmp_path, monkeypatch):
    """`row.*` names both axes and every part in them (a tag with a gid has no parent part):
    each moves by the offset once, not once for itself and again with its axes."""
    project = _project(tmp_path, monkeypatch, BY_HAND)
    before = _build(project)
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "row.*", {"dy_mm": -4})
    after = _build(project)
    m = json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))
    assert m["style"]["invalid"] == [] and "row.*" in m["style"]["applied"]
    for part in ("row.left.tag", "row.right.tag", "row.left.xlabel", "row.right.title"):
        assert _moved(before, after, part) == (0, -4), part
    for part in ("row.left.background", "row.right.background"):
        assert _moved(before, after, part, _frame) == (0, -4), part


def test_a_moved_axes_is_trimmed_where_it_now_is(tmp_path, monkeypatch):
    """Closing the gap between two axes narrows the trimmed panel by the move."""
    project = _project(tmp_path, monkeypatch, BY_HAND)
    S.update_panel_style(project.panel_dir("fig-1", "a") / "style.json", {"trim": True})
    _build(project)
    wide = json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))["trim"]
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "row.right", {"dx_mm": -10})
    _build(project)
    narrow = json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))["trim"]
    assert (wide["w_pt"] - narrow["w_pt"]) / PT == pytest.approx(10, abs=0.001)


def test_an_axes_in_a_constrained_panel_moves_after_the_layout_and_nothing_reflows(project):
    before = ET.fromstring(read(_panel(project)))
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main", {"dx_mm": 2.5})
    after = _build(project)
    assert _moved(before, after, "main.background", _frame) == (2.5, 0)
    assert _moved(before, after, "main.ylabel") == (2.5, 0)


def _panel(project):
    _build(project)
    return project.panel_dir("fig-1", "a") / "panel.svg"


@pytest.mark.parametrize("value", [float("inf"), float("nan"), "3", True])
def test_an_axes_offset_is_validated_like_a_labels(value):
    assert P.validate("axes", {"dx_mm": value}) and P.validate("axes", {"dy_mm": value})
    assert P.validate("axes", {"dx_mm": -100, "dy_mm": 100}) == []
