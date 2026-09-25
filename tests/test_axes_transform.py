"""Scaling and rotating an axes, or a named group of axes (idofig 0.7.0, 2026-09-25): `scale`
and `rotate` on an `axes` part are one SVG transform on its group, about its box's centre, after
the layout and after `dx_mm`/`dy_mm`; the manifest boxes what it drew where it now is, and the
checks read the sizes it prints at.

Where the expected numbers come from: the transform is read back from panel.svg with ElementTree
and judged by what it does to the axes' background path (a rectangle matplotlib wrote): its
centre stays, its sides grow by the scale, its top edge turns clockwise by the angle — geometry,
not idofig's formula. Untransformed boxes come from a build of the same panel without the style;
font sizes from the manifest's `props` (what the script set). The panel has two axes
placed by hand at known millimetres (test_group_moves' BY_HAND).

Reproduce: `.venv/bin/python -m pytest tests/test_axes_transform.py`.
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import read
from test_group_moves import BY_HAND, _build, _el, _project

from idofig import cli
from idofig import props as P
from idofig import spec as S
from idofig.build import compliance


def _style(project, part, props):
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", part, props)


def _manifest(project):
    return json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))


def _matrix(root, ident):
    t = _el(root, ident).get("transform")
    assert t and t.startswith("matrix("), t
    return [float(v) for v in t[len("matrix("):-1].split()]


def _corners(root, ident):
    """The four corners of an axes' background rectangle, as matplotlib wrote its path."""
    d = next(_el(root, ident).iter("{http://www.w3.org/2000/svg}path")).get("d")
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return list(zip(nums[0::2], nums[1::2]))[:4]


def _apply(m, x, y):
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def test_scale_and_rotate_land_as_one_transform_about_the_axes_centre(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _style(project, "row.left", {"scale": 0.8, "rotate": 30})
    root = _build(project)
    m = _matrix(root, "row.left")
    corners = _corners(root, "row.left.background")
    moved = [_apply(m, x, y) for x, y in corners]
    centre = lambda pts: (sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4)  # noqa: E731
    assert centre(moved) == pytest.approx(centre(corners), abs=1e-3)  # about the box's centre
    side = lambda p, q: math.dist(p, q)  # noqa: E731
    assert side(moved[0], moved[1]) == pytest.approx(0.8 * side(corners[0], corners[1]), rel=1e-5)
    # matplotlib writes the rectangle from its bottom-left along the bottom edge: turned clockwise
    # (y down), that edge now points 30° below the horizontal
    (x0, y0), (x1, y1) = moved[0], moved[1]
    assert math.degrees(math.atan2(y1 - y0, x1 - x0)) == pytest.approx(30, abs=1e-4)
    # the other axes, and a figure text, are left alone
    assert _el(root, "row.right").get("transform") is None and _el(root, "free").get("transform") is None


def test_the_manifest_boxes_what_is_drawn_in_a_turned_axes_where_it_now_is(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _build(project)
    plain = _manifest(project)
    _style(project, "row.left", {"scale": 1.5, "rotate": -45})
    root = _build(project)
    man = _manifest(project)
    m = _matrix(root, "row.left")

    def around(box):
        pts = [_apply(m, x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
        return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]

    for part in ("row.left", "row.left.xlabel", "row.left.title", "row.left.tag", "row.left.legend"):
        assert man["parts"][part]["bbox"] == pytest.approx(around(plain["parts"][part]["bbox"]), abs=2e-3), part
        assert man["parts"][part]["effective_scale"] == 1.5, part
    for part in ("row.right", "row.right.xlabel", "free"):
        assert man["parts"][part]["bbox"] == plain["parts"][part]["bbox"] and "effective_scale" not in man["parts"][part]
    ax = man["axes"]["row.left"]
    assert ax["frame"] == plain["axes"]["row.left"]["bbox"]
    assert ax["bbox"] == pytest.approx(around(ax["frame"]), abs=2e-3)
    assert ax["matrix"] == pytest.approx(m, abs=1e-5)
    props = man["parts"]["row.left"]["props"]
    assert (props["scale"], props["rotate"]) == (1.5, -45)
    assert man["parts"]["row.left"]["base"] == {"scale": 1.0, "rotate": 0.0}
    assert "frame" not in man["axes"]["row.right"]


def test_the_checks_read_the_size_a_scaled_axes_prints_at(tmp_path, monkeypatch):
    """Nature's 5 pt floor: a label drawn at the rc size, scaled to half, prints at half of it."""
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _style(project, "row.left", {"scale": 0.5})
    _build(project)
    man = _manifest(project)
    size = man["parts"]["row.left.xlabel"]["props"]["fontsize"]
    assert size >= 5  # passes unscaled
    errors, _ = compliance(project, "fig-1", S.load_figure(project.figure_json("fig-1")))
    assert f"fig-1/a: row.left.xlabel is {round(size * 0.5, 3):g} pt; Nature requires at least 5 pt" in errors
    assert not any("row.right" in e for e in errors)


def test_the_ink_check_reads_the_scaled_box(tmp_path, monkeypatch):
    """row.right is 25 mm wide at x 50–75 mm of a 90 mm panel: tripled about its centre it spans
    25–100 mm, 10 mm past the edge (more with its labels)."""
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _style(project, "row.right", {"scale": 3})
    _build(project)
    _, warnings = compliance(project, "fig-1", S.load_figure(project.figure_json("fig-1")))
    hit = next(w for w in warnings if w.startswith("fig-1/a: row.right is "))
    assert float(hit.split(" is ")[1].split(" mm")[0]) >= 10


def test_a_pattern_scales_each_axes_it_names_and_nothing_twice(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _style(project, "row.*", {"rotate": 5})
    root = _build(project)
    man = _manifest(project)
    assert man["style"]["invalid"] == [] and "row.*" in man["style"]["applied"]
    assert _matrix(root, "row.left") and _matrix(root, "row.right")
    # only the axes groups carry a transform: a label inside is turned once, with its axes
    assert [el.get("id") for el in root.iter() if el.get("transform", "").startswith("matrix(")] == \
        ["row.left", "row.right"]


def test_identity_writes_the_same_panel_as_no_entry(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _build(project)
    svg = read(project.panel_dir("fig-1", "a") / "panel.svg")
    boxes = {n: p["bbox"] for n, p in _manifest(project)["parts"].items()}
    _style(project, "row.left", {"scale": 1, "rotate": 0})
    _build(project)
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == svg
    assert {n: p["bbox"] for n, p in _manifest(project)["parts"].items()} == boxes


@pytest.mark.parametrize("props, problem", [
    ({"scale": 5}, "scale must be ≤ 4"), ({"scale": 0.1}, "scale must be ≥ 0.25"),
    ({"scale": 0}, "scale must be ≥ 0.25"), ({"rotate": 181}, "rotate must be ≤ 180"),
    ({"rotate": -200}, "rotate must be ≥ -180"), ({"rotate": float("nan")}, "rotate must be a finite number"),
    ({"scale": "2"}, "scale must be a number"),
])
def test_out_of_range_values_are_refused(props, problem):
    assert P.validate("axes", props) == [problem]


def test_scale_and_rotate_are_axes_properties_only():
    assert P.validate("axes", {"scale": 0.25, "rotate": -180}) == []
    assert P.validate("axes", {"scale": 4, "rotate": 180}) == []
    assert "'scale' is not a text property" in P.validate("text", {"scale": 2})[0]
    assert P.describe()["kinds"]["axes"]["rotate"] == {"type": "number", "min": -180, "max": 180, "unit": "deg"}


def test_the_style_command_refuses_an_out_of_range_value_and_writes_nothing(tmp_path, monkeypatch, capsys):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _build(project)
    style = project.panel_dir("fig-1", "a") / "style.json"
    assert cli.main(["style", "fig-1", "a", "row.left", "scale=9"]) == 2 and not style.exists()
    assert "scale must be ≤ 4" in capsys.readouterr().err
    assert cli.main(["style", "fig-1", "a", "row.left.xlabel", "rotate=10"]) == 2 and not style.exists()
    assert cli.main(["style", "fig-1", "a", "row.left", "scale=0.9", "rotate=10"]) == 0
    assert json.loads(read(style))["parts"]["row.left"] == {"scale": 0.9, "rotate": 10}


def test_a_data_anchor_turns_with_its_axes(tmp_path, monkeypatch):
    """An annotation at the axes' data origin lands on the turned frame's corner in figure.svg."""
    from idofig.compose import compose

    project = _project(tmp_path, monkeypatch, BY_HAND)
    _style(project, "row.left", {"rotate": 90})
    _build(project)
    man = _manifest(project)
    ax = man["axes"]["row.left"]
    x0, _, _, y1 = ax["frame"]
    doc = S.load_figure(project.figure_json("fig-1"))
    doc["annotations"] = [{"id": "o", "type": "text", "text": "o",
                           "at": {"panel": "a", "axes": "row.left", "data": [ax["xlim"][0], ax["ylim"][0]]}}]
    project.figure_json("fig-1").write_text(json.dumps(doc), encoding="utf-8")
    compose(project, "fig-1", write=True)
    root = ET.fromstring(read(project.figure_dir("fig-1") / "figure.svg"))
    text = next(el for el in root.iter("{http://www.w3.org/2000/svg}text") if (el.text or "").strip() == "o")
    # the bottom-left corner, turned 90° clockwise about the centre, is the top-left
    cx, cy = (ax["frame"][0] + ax["frame"][2]) / 2, (ax["frame"][1] + ax["frame"][3]) / 2
    expected = (cx - (y1 - cy), cy + (x0 - cx))
    assert (float(text.get("x")), float(text.get("y"))) == pytest.approx(expected, abs=0.01)


def test_a_turned_panel_rebuilds_to_the_same_bytes(tmp_path, monkeypatch):
    from idofig.build import build

    project = _project(tmp_path, monkeypatch, BY_HAND)
    _style(project, "row.left", {"scale": 0.9, "rotate": 10, "dx_mm": 2})
    _build(project)
    panel = project.panel_dir("fig-1", "a")
    first = read(panel / "panel.svg"), read(panel / "manifest.json")
    assert build(project, ["fig-1"], force=True).ok
    assert (read(panel / "panel.svg"), read(panel / "manifest.json")) == first
