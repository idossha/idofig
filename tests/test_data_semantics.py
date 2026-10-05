"""The manifest's data semantics (0.10.0, SPEC.md manifest.json *Data*, *Anchors*, *Build*).

What it pins: a data mark's `data` is what the producer drew; an axes' `anchors` put a data value
where panel.svg draws it (trimmed, log and categorical axes included); a scatter's or a marker
line's marks get ids `<part>.<index>` only when every finite point is drawn; legend entries are
joined to their series by artist, never by text; `build` reveals scaffold, grid, data in
matplotlib's draw order, legends, then free text; member ids survive new data; rebuilding is
byte-identical.

Where the numbers come from: the expected values are the data file the producer reads (written
here), matplotlib's category rule (a category's value is its first-appearance index), and the
coordinates matplotlib wrote into panel.svg, read back with ElementTree — never the manifest
writer's own arithmetic. Reproduce: `.venv/bin/python -m pytest tests/test_data_semantics.py`.
Elsewhere: the bytes of a panel's SVG are the golden's (tests/golden/); the size cap's numbers
are measured in the 0.10.0 commit message, not asserted. 2026-10-04.
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import read, write

from idofig.build import build
from idofig.marks import DATA_CAP
from idofig.project import find_project

SVG = "{http://www.w3.org/2000/svg}"

DATA = {
    "x": [0.5, 1.5, 2.0, 3.25, 4.0],
    "y": [2.0, 3.5, 1.0, 4.5, 3.0],
    "c": [10.0, 20.0, 30.0, 40.0, 50.0],
    "line": [1.0, None, 2.5, 3.0, 2.0],
    "groups": ["sham", "low", "high"],
    "bars": [1.0, -0.5, 2.25],
    "logy": [1.0, 10.0, 100.0, 1000.0, 10000.0],
}

PRODUCER = '''
import json
from pathlib import Path
import numpy as np
import idofig as idf

d = json.loads(Path("data/d.json").read_text())
line = np.array([np.nan if v is None else v for v in d["line"]])
p = idf.panels("a", "b", "c")
ax = p["a"].subplots(); idf.name(ax, "main")
ax.grid(True)
ax.plot(d["x"], line, marker="o", label="mean")         # zorder 2, added first
ax.scatter(d["x"], d["y"], c=d["c"], label="cells")      # zorder 1: drawn before the line
ax.text(1, 1, "note")
ax.legend()
ax = p["b"].subplots(); idf.name(ax, "main")
ax.bar(d["groups"], d["bars"], label="effect")
ax.legend()
ax = p["c"].subplots(); idf.name(ax, "main")
ax.scatter(d["x"], d["logy"], label="growth")
ax.set_yscale("log")
idf.save(p)
'''


def _project(root, data=DATA, producer=PRODUCER):
    write(root / "idofig.toml", 'journal = "nature"\n')
    write(root / "data" / "d.json", json.dumps(data))
    fig = {"schema": 2, "id": "fig-1", "width": {"preset": "double"},
           "producers": [{"id": "make", "run": ["python", "figures/fig-1/make.py"], "inputs": ["data/d.json"],
                          "panels": ["a", "b", "c"]}],
           "panels": [{"id": pid, "place": {"x": k * 60.0, "y": 0, "w": 56, "h": 50}}
                      for k, pid in enumerate("abc")]}
    write(root / "figures" / "fig-1" / "figure.json", json.dumps(fig))
    write(root / "figures" / "fig-1" / "make.py", producer)
    # Panel b is trimmed: its anchors are measured from the crop's corner, as its boxes are.
    write(root / "figures" / "fig-1" / "panels" / "b" / "style.json", json.dumps({"schema": 2, "trim_mm": 1}))
    return find_project(root)


@pytest.fixture
def built(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    project = _project(root)
    monkeypatch.chdir(root)
    rep = build(project)
    assert rep.ok, rep.to_json()
    return project


def _panel(project, pid):
    d = project.panel_dir("fig-1", pid)
    return json.loads(read(d / "manifest.json")), ET.fromstring(read(d / "panel.svg")), read(d / "panel.svg")


def _to_pt(anchors, v, log=False):
    (d0, p0), (d1, p1) = anchors
    f = (lambda u: math.log10(u)) if log else (lambda u: u)
    return p0 + (f(v) - f(d0)) / (f(d1) - f(d0)) * (p1 - p0)


def _by_id(root):
    return {el.get("id"): el for el in root.iter() if el.get("id")}


def test_data_is_what_the_producer_drew(built):
    man, _, _ = _panel(built, "a")
    cells = man["parts"]["main.series.cells"]["data"]
    assert (cells["kind"], cells["n"]) == ("points", len(DATA["x"]))
    assert (cells["x"], cells["y"], cells["values"]) == (DATA["x"], DATA["y"], DATA["c"])
    mean = man["parts"]["main.series.mean"]["data"]
    assert (mean["kind"], mean["x"], mean["y"]) == ("line", DATA["x"], DATA["line"])  # the gap stays a gap

    man, _, _ = _panel(built, "b")
    bars = man["parts"]["main.series.effect"]["data"]
    # matplotlib's category rule: a category stands at the index of its first appearance.
    assert bars == {"kind": "bars", "n": 3, "orientation": "vertical",
                    "positions": [float(k) for k in range(3)], "values": DATA["bars"],
                    "baselines": [0.0] * 3, "keys": DATA["groups"]}
    assert man["axes"]["main"]["categories"] == {"x": DATA["groups"]}


def test_anchors_place_a_value_where_panel_svg_draws_it(built):
    # Points: each mark's <use x y> in panel.svg against its data through the anchors.
    man, root, _ = _panel(built, "a")
    anc = man["axes"]["main"]["anchors"]
    els = _by_id(root)
    for i, (x, y) in enumerate(zip(DATA["x"], DATA["y"])):
        use = els[f"main.series.cells.{i}"]
        assert float(use.get("x")) == pytest.approx(_to_pt(anc["x"], x), abs=0.01)
        assert float(use.get("y")) == pytest.approx(_to_pt(anc["y"], y), abs=0.01)

    # A log axis: interpolated in log space.
    man, root, _ = _panel(built, "c")
    anc = man["axes"]["main"]["anchors"]
    els = _by_id(root)
    for i, y in enumerate(DATA["logy"]):
        assert float(els[f"main.series.growth.{i}"].get("y")) == pytest.approx(_to_pt(anc["y"], y, log=True), abs=0.01)

    # Bars, in a trimmed panel: anchors are measured from the crop's corner, so the bar's path in
    # panel.svg (untrimmed) is the anchor plus the crop's offset; its top is baseline + value.
    man, root, _ = _panel(built, "b")
    anc, trim = man["axes"]["main"]["anchors"], man["trim"]
    els = _by_id(root)
    for i, (key, value) in enumerate(zip(DATA["groups"], DATA["bars"])):
        g = els[f"main.series.effect.{i}"]
        assert (g.get("data-index"), g.get("data-key"), float(g.get("data-value"))) == (str(i), key, value)
        nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", g.find(f"{SVG}path").get("d"))]
        xs, ys = nums[0::2], nums[1::2]
        assert (min(xs) + max(xs)) / 2 == pytest.approx(_to_pt(anc["x"], i) + trim["x_pt"], abs=0.01)
        assert sorted({round(v, 2) for v in ys}) == sorted({round(_to_pt(anc["y"], v) + trim["y_pt"], 2)
                                                            for v in (0.0, value)})


def test_marks_are_addressable_only_when_every_finite_point_is_drawn(built, tmp_path):
    man, root, _ = _panel(built, "a")
    els = _by_id(root)
    finite = [i for i, v in enumerate(DATA["line"]) if v is not None]
    assert man["parts"]["main.series.mean"]["data"]["addressable"] is True
    assert sorted(int(i.rsplit(".", 1)[1]) for i in els if i.startswith("main.series.mean.")) == finite
    assert all(els[f"main.series.mean.{i}"].get("data-index") == str(i) for i in finite)

    # A point matplotlib does not draw (a negative value on a log axis), and more marks than the
    # cap: the series stays one group, and the manifest says why. (A point far outside the view
    # is still drawn, clipped, so it keeps its id.)
    producer = '''
import idofig as idf
p = idf.panels("a", "b", "c")
ax = p["a"].subplots(); idf.name(ax, "main")
ax.scatter([0, 1, 2, 3], [1, 10, -5, 100], label="far")
ax.set_yscale("log")
ax = p["b"].subplots(); idf.name(ax, "main")
ax.scatter(range({n}), range({n}), label="many")
p["c"].subplots()
idf.save(p)
'''.replace("{n}", str(DATA_CAP + 1))
    project = _project(tmp_path / "edge", producer=producer)
    assert build(project).ok
    far = json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))["parts"]["main.series.far"]["data"]
    assert far["addressable"] is False and "3 marks for its 4 points" in far["why"]
    assert "main.series.far.0" not in read(project.panel_dir("fig-1", "a") / "panel.svg")
    many = json.loads(read(project.panel_dir("fig-1", "b") / "manifest.json"))["parts"]["main.series.many"]["data"]
    assert many["n"] == DATA_CAP + 1 and "x" not in many and str(DATA_CAP) in many["omitted"]
    assert many["x_range"] == [0.0, float(DATA_CAP)] and many["addressable"] is False


def test_legend_entries_join_their_series_by_artist_not_text(built, tmp_path):
    man, _, _ = _panel(built, "a")
    assert man["parts"]["main.legend.cells"]["series"] == "main.series.cells"
    assert man["parts"]["main.legend.mean"]["series"] == "main.series.mean"
    man, _, _ = _panel(built, "b")
    assert man["parts"]["main.legend.effect"]["series"] == "main.series.effect"  # a container: its group

    # Hand-picked handles whose text names another series: joined to nothing, not to "a".
    producer = '''
import idofig as idf
p = idf.panels("a", "b", "c")
ax = p["a"].subplots(); idf.name(ax, "main")
a, = ax.plot([0, 1], label="a")
b, = ax.plot([1, 0], label="b")
ax.legend([b], ["a"])
fig = p["b"]
left, right = fig.subplots(1, 2); idf.name(left, "l"); idf.name(right, "r")
left.plot([0, 1], label="up"); right.bar(["x"], [1], label="tall")
fig.legend()
p["c"].subplots()
idf.save(p)
'''
    project = _project(tmp_path / "legends", producer=producer)
    assert build(project).ok
    a = json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))["parts"]
    assert "series" not in a["main.legend.a"]
    b = json.loads(read(project.panel_dir("fig-1", "b") / "manifest.json"))["parts"]
    assert (b["legend.up"]["series"], b["legend.tall"]["series"]) == ("l.series.up", "r.series.tall")


def test_build_reveals_scaffold_grid_data_in_draw_order_legend_then_text(built):
    man, _, svg = _panel(built, "a")
    steps = man["build"]
    assert [s["stage"] for s in steps] == ["scaffold", "grid", "data", "data", "legend", "annotation"]
    names = [n for s in steps for n in s["parts"]]
    assert all(n in man["parts"] for n in names)  # every step names a part or a group of the manifest
    assert {"main.xaxis", "main.yaxis", "main.background", "main.spine.left"} <= set(steps[0]["parts"])
    assert steps[1]["parts"] == ["main.xgrid.*", "main.ygrid.*"]
    # The drawn gridlines are the group's members: one per drawn tick, as panel.svg has them.
    grid = man["parts"]["main.xgrid.*"]
    assert grid["group"] and len(grid["members"]) == len(man["parts"]["main.xtick.*"]["members"])
    assert all(f'id="{m}"' in svg for m in grid["members"])
    # Data steps in the order matplotlib drew them: the order their groups appear in panel.svg.
    data = [s["parts"][0] for s in steps if s["stage"] == "data"]
    assert data == sorted(data, key=lambda n: svg.index(f'id="{n}"')) == ["main.series.cells", "main.series.mean"]
    assert [s["entrance"] for s in steps if s["stage"] == "data"] == ["stagger", "draw-on"]
    assert steps[-2:] == [{"stage": "legend", "parts": ["main.legend"], "entrance": "fade"},
                          {"stage": "annotation", "parts": ["main.text.note"], "entrance": "fade"}]
    man, _, _ = _panel(built, "b")
    assert [s["entrance"] for s in man["build"] if s["stage"] == "data"] == ["grow"]


def test_a_gridline_group_takes_a_style_like_any_part(built):
    write(built.panel_dir("fig-1", "a") / "style.json",
          json.dumps({"schema": 1, "parts": {"main.xgrid.*": {"color": "#ff0000"}}}))
    assert build(built).ok
    man, root, _ = _panel(built, "a")
    assert man["style"]["applied"] == ["main.xgrid.*"] and not man["style"]["detached"]
    els = _by_id(root)
    for m in man["parts"]["main.xgrid.*"]["members"]:
        assert "stroke: #ff0000" in els[m].find(f"{SVG}path").get("style")


def test_member_names_survive_new_data_and_rebuilds_are_byte_identical(built):
    d = built.figure_dir("fig-1")
    first = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    build(built, force=True)
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == first

    def ids():
        return {pid: set(re.findall(r'id="(main\.series\.[^"]+)"', read(built.panel_dir("fig-1", pid) / "panel.svg")))
                for pid in "ab"}
    before = ids()
    moved = dict(DATA, y=[v + 0.25 for v in DATA["y"]], bars=[v * 2 for v in DATA["bars"]])
    write(built.root / "data" / "d.json", json.dumps(moved))
    assert build(built).ok
    assert ids() == before  # the same marks, the same names, wherever the new values put them
    man, root, _ = _panel(built, "b")
    assert [g.get("data-key") for g in root.iter(f"{SVG}g") if g.get("data-key")] == DATA["groups"]
    assert man["parts"]["main.series.effect"]["data"]["values"] == moved["bars"]
