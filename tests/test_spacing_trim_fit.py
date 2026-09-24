"""Panel spacing, trim and figure fit (idofig 0.4.0, 2026-09-24): style.json `layout`
(hspace_mm, wspace_mm, pad_mm), `trim`/`trim_mm`, and a figure.json with no height fitting
what it draws (`fit_margin_mm`).

Where the expected numbers come from: axes frames are read back from panel.svg with
ElementTree (the path of each axes' background, what is printed), never from idofig's
manifest, and compared with the millimetres asked for, at 72/25.4 pt per mm. Spacing is
checked as a difference of two builds (a gap of 8 mm, then 14 mm, must move the frames 6 mm
apart): the tick labels and axis labels between the frames are the same in both, so the
difference is the spacing alone, whatever matplotlib measures them as. The grid's axes have
no ticks: tick labels change with the axes' size (a smaller axes chose other ticks, and its
frame moved 1.3 mm more than the padding did), axis labels do not. Trim is checked
against an axes placed by hand with `axes_mm` at a known place in mm; its frame's stroke
(0.8 pt, idofig's rc) sticks out by half its width, hence the 0.2 mm tolerance there and
nowhere else.

Reproduce: `.venv/bin/python -m pytest tests/test_spacing_trim_fit.py`.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import pytest
from conftest import read, write

from idofig import spec as S
from idofig.build import build
from idofig.compose import compose
from idofig.errors import SpecError

PT = 72 / 25.4
SVG = "{http://www.w3.org/2000/svg}"

GRID = '''
import idofig as idf
p = idf.panels("a")
axs = p["a"].subplots(2, 2)
for i, ax in enumerate(axs.flat):
    idf.name(ax, f"ax{i}")
    ax.plot([0, 1], [0, 1])
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel("x")
    ax.set_ylabel("y")
idf.save(p)
'''

BY_HAND = '''
import idofig as idf
p = idf.panels("a", layout=None)
ax = idf.axes_mm(p["a"], 10, 20, 30, 25)
idf.name(ax, "main")
ax.set_xticks([])
ax.set_yticks([])
idf.save(p)
'''


def _project(tmp_path, monkeypatch, script, place=None, letters=None):
    root = tmp_path / "proj"
    write(root / "idofig.toml", 'journal = "nature"\n')
    doc = {"schema": 2, "id": "fig-1", "width": {"preset": "double"},
           "producers": [{"id": "make", "run": ["python", "figures/fig-1/make.py"], "panels": ["a"]}],
           "panels": [{"id": "a", "letter": "a", "place": place or {"x": 0, "y": 0, "w": 80, "h": 80}}],
           "annotations": []}
    if letters is not None:
        doc["letters"] = letters
    write(root / "figures/fig-1/figure.json", json.dumps(doc))
    write(root / "figures/fig-1/make.py", script)
    monkeypatch.chdir(root)
    from idofig.project import find_project

    return find_project(root)


def _build(project):
    rep = build(project, ["fig-1"])
    assert rep.ok, rep
    return ET.fromstring(read(project.panel_dir("fig-1", "a") / "panel.svg"))


def _frame(root, ident):
    """(x0, y0, x1, y1) in pt of the path drawing an axes' background, read from the SVG."""
    for el in root.iter():
        if el.get("id") == ident:
            d = next(el.iter(f"{SVG}path")).get("d")
            nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", d)]
            xs, ys = nums[0::2], nums[1::2]
            return min(xs), min(ys), max(xs), max(ys)
    raise AssertionError(f"no {ident}")


def _panel_style(project, **props):
    S.update_panel_style(project.panel_dir("fig-1", "a") / "style.json", props)


def _manifest(project):
    return json.loads(read(project.panel_dir("fig-1", "a") / "manifest.json"))


# ----------------------------------------------------------------------------- spacing


def test_a_gap_in_mm_moves_neighbouring_axes_that_many_mm_apart(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, GRID)
    _panel_style(project, layout={"hspace_mm": 8, "wspace_mm": 8})
    a = _build(project)
    _panel_style(project, layout={"hspace_mm": 14, "wspace_mm": 11})
    b = _build(project)
    vgap = lambda r: _frame(r, "ax2.background")[1] - _frame(r, "ax0.background")[3]  # noqa: E731
    hgap = lambda r: _frame(r, "ax1.background")[0] - _frame(r, "ax0.background")[2]  # noqa: E731
    assert (vgap(b) - vgap(a)) / PT == pytest.approx(6, abs=0.01)
    assert (hgap(b) - hgap(a)) / PT == pytest.approx(3, abs=0.01)
    assert S.load_style(project.panel_dir("fig-1", "a") / "style.json")["schema"] == 2


def test_padding_in_mm_moves_the_outer_axes_in_from_the_panels_edge(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, GRID)
    _panel_style(project, layout={"pad_mm": 2, "hspace_mm": 12, "wspace_mm": 12})
    a = _build(project)
    _panel_style(project, layout={"pad_mm": 5})
    b = _build(project)
    assert (_frame(b, "ax0.background")[0] - _frame(a, "ax0.background")[0]) / PT == pytest.approx(3, abs=0.01)
    assert (_frame(b, "ax0.background")[1] - _frame(a, "ax0.background")[1]) / PT == pytest.approx(3, abs=0.01)


def test_spacing_a_panel_with_no_layout_engine_says_so_and_changes_nothing(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _build(project)
    before = read(project.panel_dir("fig-1", "a") / "panel.svg")
    _panel_style(project, layout={"hspace_mm": 10})
    _build(project)
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == before
    assert any("layout had no effect" in w for w in _manifest(project)["warnings"])


@pytest.mark.parametrize("props", [
    {"layout": {"hspace_mm": float("nan")}}, {"layout": {"wspace_mm": -1}}, {"layout": {"gap": 2}},
    {"layout": 3}, {"trim": "yes"}, {"trim_mm": float("inf")}, {"colour": 1},
])
def test_a_bad_panel_style_value_is_refused_and_the_file_is_untouched(tmp_path, props):
    path = tmp_path / "style.json"
    with pytest.raises(SpecError):
        S.update_panel_style(path, props)
    assert not path.exists()


def test_a_style_with_panel_keys_is_schema_2_and_without_them_1(tmp_path):
    path = tmp_path / "style.json"
    _, after = S.update_panel_style(path, {"trim": True})
    assert after["schema"] == 2
    _, after = S.update_panel_style(path, {"trim": None})
    assert after["schema"] == 1


# ----------------------------------------------------------------------------- trim


def test_trim_crops_to_the_ink_plus_its_margin_and_places_the_crop_at_the_panels_corner(tmp_path, monkeypatch):
    place = {"x": 20, "y": 10, "w": 80, "h": 80}
    project = _project(tmp_path, monkeypatch, BY_HAND, place=place, letters={"show": False})
    _panel_style(project, trim=True)
    _build(project)
    t = _manifest(project)["trim"]
    # axes_mm(10, 20, 30, 25) from the bottom-left of an 80 mm panel: top edge at 80 − 45 = 35 mm.
    for got, want in ((t["x_pt"], 10), (t["y_pt"], 35), (t["w_pt"], 30), (t["h_pt"], 25)):
        assert got / PT == pytest.approx(want, abs=0.2)
    _panel_style(project, trim_mm=2)
    _build(project)
    t2 = _manifest(project)["trim"]
    assert (t2["x_pt"] - t["x_pt"]) / PT == pytest.approx(-2, abs=0.001)
    assert (t2["w_pt"] - t["w_pt"]) / PT == pytest.approx(4, abs=0.001)
    # panel.svg keeps its drawn size (panels are never scaled); figure.svg crops it.
    assert 'width="226.771654pt"' in read(project.panel_dir("fig-1", "a") / "panel.svg")
    fig = ET.fromstring(read(project.figure_dir("fig-1") / "figure.svg"))
    g = next(el for el in fig.iter() if el.get("id") == "a")
    tx, ty = (float(v) for v in re.findall(r"-?[\d.]+", g.get("transform")))
    rect = next(g.iter(f"{SVG}rect"))
    assert (tx + float(rect.get("x"))) / PT == pytest.approx(place["x"], abs=0.001)
    assert (ty + float(rect.get("y"))) / PT == pytest.approx(place["y"], abs=0.001)
    assert float(rect.get("width")) == pytest.approx(t2["w_pt"], abs=0.001)


# ----------------------------------------------------------------------------- fit


def test_a_figure_with_no_height_fits_its_trimmed_panel_and_cuts_the_empty_band_above(tmp_path, monkeypatch):
    place = {"x": 0, "y": 12, "w": 80, "h": 80}
    project = _project(tmp_path, monkeypatch, BY_HAND, place=place, letters={"show": False})
    _panel_style(project, trim=True)
    _build(project)
    res = compose(project, "fig-1")
    h = _manifest(project)["trim"]["h_pt"] / PT
    assert res.top_mm == pytest.approx(12, abs=0.001)
    assert res.height_mm == pytest.approx(h, abs=0.001)
    root = ET.fromstring(read(res.path))
    x, y, w, hh = (float(v) for v in root.get("viewBox").split())
    assert (y / PT, hh / PT) == (pytest.approx(12, abs=0.001), pytest.approx(h, abs=0.001))
    assert json.loads(read(project.figure_json("fig-1")))["panels"][0]["place"] == place  # untouched

    S.update_figure(project.figure_json("fig-1"), [])
    doc = json.loads(read(project.figure_json("fig-1")))
    doc["fit_margin_mm"] = 2
    doc["schema"] = S.figure_schema(doc)
    assert doc["schema"] == 3
    project.figure_json("fig-1").write_text(json.dumps(doc))
    res = compose(project, "fig-1")
    assert res.top_mm == pytest.approx(10, abs=0.001)
    assert res.height_mm == pytest.approx(h + 4, abs=0.001)


def test_a_fitted_figure_takes_in_a_letter_above_its_panels(tmp_path, monkeypatch):
    place = {"x": 0, "y": 12, "w": 80, "h": 80}
    project = _project(tmp_path, monkeypatch, BY_HAND, place=place,
                       letters={"offset_mm": [0, -6], "size_pt": 8})
    _build(project)
    res = compose(project, "fig-1")
    assert res.top_mm == pytest.approx(6, abs=0.001)  # the letter's top: 12 − 6 mm
    assert res.height_mm == pytest.approx(12 + 80 - 6, abs=0.001)
    assert not res.warnings
