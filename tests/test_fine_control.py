"""Fine control of a figure (idofig 0.3.0, 2026-09-24): per-panel letter offsets, strict
`letters`, part offsets (dx_mm/dy_mm), axis tick properties, the Agg backend, the ink and
letter checks, names on rasterized parts and on a 3D axes' z axis, the render number the
lock records, and what porting a figure pair found missing (the last section): boxes for
collections, one finding per group, stroke widths, a letter colour, generic font families.

Where the expected numbers come from: positions are read back from the SVG files with
ElementTree (what is printed), never from idofig's own manifest, and compared with the
offset given, converted at 72/25.4 pt per mm. The layout numbers (panel a at x 0, panel b
at x 92 mm, an 88 × 60 mm panel, Nature's 183 mm double width and 5 pt floor) are
conftest's and nature.json's. A manifest box is asserted only where the manifest is the
thing under test (what a canvas outlines, what the ink check reads).

The byte identity of a panel with no offsets is checked against tests/golden/, whose
panel.svg idofig 0.2.2 drew to the byte (tests/golden/make_golden.py regenerates it; its
docstring says from which source), and, under any matplotlib, against the same save with
nothing wrapped around the drawing. Not every 0.2.2 panel keeps its bytes: a named rasterized part (a colorbar's
solids included) is now wrapped in its own group, a 3D axes' z axis has names, a background
or legend frame with a gid is marked with its role, a legend with a gid names its entries
after it, a figure the script resized is saved at its place size, and a part that is never
drawn has no box — hence the render number (`build.RENDER`) that makes such panels stale.

A save's changes to the script's figure (a frozen layout, moved parts, wrapped draws) last
until the panel is written: the tests that save twice check that the second save is the
save of a figure that was never saved.

Reproduce: `.venv/bin/python -m pytest tests/test_fine_control.py`. The direct run's
determinism is `test_build.py`.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import matplotlib
import pytest
from conftest import read

from idofig import __version__, draw
from idofig import props as P
from idofig import spec as S
from idofig.build import RENDER, build, check, compliance, figure_status, lock_path
from idofig.build import status as figure_status_all
from idofig.compose import compose
from idofig.serve import Server

PT = 72 / 25.4  # points per mm
SVG = "{http://www.w3.org/2000/svg}"
GOLDEN = Path(__file__).parent / "golden"


def _svg_root(path):
    return ET.fromstring(read(path))


def _by_id(root, ident):
    for el in root.iter():
        if el.get("id") == ident:
            return el
    raise AssertionError(f"no element with id {ident!r}")


def _text_xy(root, ident):
    """x, y of a part's <text> (the part's own element, or the first one inside its group)."""
    el = _by_id(root, ident)
    text = el if el.tag == f"{SVG}text" else next(el.iter(f"{SVG}text"))
    return float(text.get("x")), float(text.get("y"))


def _moved_mm(before, after, ident):
    """How far a part's text moved between two panel SVGs, in mm (y down), to the µm: the SVG
    writes coordinates to 1e-6 pt, and a legend recomputed at the same place came out one step
    (3.5e-7 mm) off under matplotlib 3.8 and 3.10, which an exact 0 failed."""
    (x0, y0), (x1, y1) = _text_xy(before, ident), _text_xy(after, ident)
    return round((x1 - x0) / PT, 3), round((y1 - y0) / PT, 3)


def _panel_svg(project, pid="a"):
    return _svg_root(project.panel_dir("fig-1", pid) / "panel.svg")


def _manifest(project, pid="a"):
    return json.loads(read(project.panel_dir("fig-1", pid) / "manifest.json"))


def _style(project, part, props, pid="a"):
    S.update_style(project.panel_dir("fig-1", pid) / "style.json", part, props)


def _add_to_producer(project, code):
    """Insert ``code`` (indented for the per-panel loop) before the producer saves."""
    path = project.root / "figures/fig-1/make.py"
    body = "".join(f"    {line}\n" for line in code.strip().splitlines())
    path.write_text(read(path).replace("    ax.legend()\n", "    ax.legend()\n" + body), encoding="utf-8")


def _replace_in_producer(project, old, new):
    path = project.root / "figures/fig-1/make.py"
    assert old in read(path)
    path.write_text(read(path).replace(old, new), encoding="utf-8")


def _ink(project):
    _, warnings = compliance(project, "fig-1", S.load_figure(project.figure_json("fig-1")))
    return [w for w in warnings if "outside its panel's box" in w]


def _duplicate_ids(root):
    return [i for i, n in Counter(el.get("id") for el in root.iter() if el.get("id")).items() if n > 1]


# ----------------------------------------------------------------------------- letters (I1, I2)


def test_a_panels_letter_offset_adds_to_the_figure_wide_offset(project):
    before = ET.fromstring(compose(project, "fig-1", write=False).svg)
    ax0, ay0 = _text_xy(before, "a.letter")
    bx0, by0 = _text_xy(before, "b.letter")
    assert ax0 == 0 and bx0 == pytest.approx(92 * PT, abs=1e-3)  # each at its panel's corner

    S.update_figure(project.figure_json("fig-1"), [
        {"op": "letters", "patch": {"offset_mm": [1, 2]}},
        {"op": "letter", "panel": "a", "offset_mm": [0.5, -1.5]},
    ])
    after = ET.fromstring(compose(project, "fig-1", write=False).svg)
    ax, ay = _text_xy(after, "a.letter")
    bx, by = _text_xy(after, "b.letter")
    assert ax == pytest.approx((0 + 1 + 0.5) * PT, abs=1e-3)
    assert ay - ay0 == pytest.approx((2 - 1.5) * PT, abs=1e-3)
    assert bx == pytest.approx((92 + 1) * PT, abs=1e-3)  # b has no offset of its own
    assert by - by0 == pytest.approx(2 * PT, abs=1e-3)


def test_the_letter_op_touches_only_the_fields_it_is_sent(project):
    path = project.figure_json("fig-1")
    panel = lambda: S.panel_entry(S.load_figure(path), "a")  # noqa: E731

    S.update_figure(path, [{"op": "letter", "panel": "a", "offset_mm": [1.23456, -2]}])
    assert panel()["letter"] == "a", "moving a letter must not remove it"
    assert panel()["letter_offset_mm"] == [1.235, -2]  # rounded to µm, like place

    S.update_figure(path, [{"op": "letter", "panel": "a", "letter": "z"}])
    assert panel()["letter"] == "z" and panel()["letter_offset_mm"] == [1.235, -2]

    S.update_figure(path, [{"op": "letter", "panel": "a", "offset_mm": None}])
    assert "letter_offset_mm" not in panel() and panel()["letter"] == "z"

    before = read(path)
    for bad in ({"op": "letter", "panel": "a"}, {"op": "letter", "panel": "a", "offset_mm": [1]},
                {"op": "letter", "panel": "a", "offset_mm": "left"},
                {"op": "letter", "panel": "a", "offset_mm": [-500, 0]},  # drawn off any figure, no word said
                {"op": "letter", "panel": "a", "offset_mm": [1e308, 0]}):  # x="inf" in figure.svg
        with pytest.raises(S.SpecError):
            S.update_figure(path, [bad])
    assert read(path) == before, "a refused op leaves the file as it was"

    S.update_figure(path, [{"op": "letter", "panel": "a", "letter": None}])
    assert "letter" not in panel()
    # an offset on a panel without a letter is kept (it applies if a letter comes back)
    S.update_figure(path, [{"op": "letter", "panel": "a", "offset_mm": [1, 1]}])
    assert panel()["letter_offset_mm"] == [1, 1] and "a.letter" not in compose(project, "fig-1", write=False).svg


def test_a_figure_that_uses_a_0_3_key_says_schema_3_so_an_older_idofig_refuses_it(project):
    """idofig 0.2.x checks no panel or letters key it does not know: given `letter_offset_mm` or
    `letters.color` under "schema": 2, it composed every letter at the figure-wide place, in
    black, and called figure.svg fresh (two 0.2.2 servers left running in a project redrew five
    figures so). A file that uses one says 3, which 0.2.x refuses ("schema must be 2"); one that
    uses neither stays 2, which every idofig reads."""
    path = project.figure_json("fig-1")
    schema = lambda: json.loads(read(path))["schema"]  # noqa: E731
    for on, off in (({"op": "letter", "panel": "a", "offset_mm": [1, 0]},
                     {"op": "letter", "panel": "a", "offset_mm": None}),
                    ({"op": "letters", "patch": {"color": "#161514"}}, {"op": "letters", "patch": {"color": None}})):
        S.update_figure(path, [on])
        assert schema() == 3, on
        S.update_figure(path, [off])
        assert schema() == 2, off
    # What a hand edit or a 0.3 development build wrote (a 0.3 key under 2) is read, and 0.2.x
    # reads it too: every compose warns, and so status and check, until its next write says 3.
    doc = json.loads(read(path))
    doc["panels"][0]["letter_offset_mm"] = [0, 1]
    path.write_text(json.dumps(doc), encoding="utf-8")
    hint = ('figure.json uses letter_offset_mm or letters.color under "schema": 2, which an idofig older than '
            '0.3 reads and draws without them: set "schema": 3')
    assert figure_status(project, "fig-1").error is None and hint in figure_status(project, "fig-1").warnings
    assert f"fig-1: {hint}" in check(project, run=False).warnings
    S.update_figure(path, [{"op": "place", "panel": "b", "x": 93}])
    assert schema() == 3 and hint not in compose(project, "fig-1", write=False).warnings
    for bad in (1, 4, True, "3", None):
        assert S.validate_figure({**doc, "schema": bad}, expected_id="fig-1") == [
            f"schema must be 2 or 3 (found {bad!r})"], bad


def test_letters_are_validated_key_by_key():
    doc = S.new_figure("f")
    ok = {"show": True, "case": "upper", "weight": "normal", "size_pt": 9, "offset_mm": [0, 1], "wrapper": "parens"}
    assert S.validate_figure({**doc, "letters": ok}, expected_id="f") == []
    for letters, expect in (({"offset": [1, 2]}, "letters.offset is not a letters key"),
                            ({"weight": "heavy"}, "letters.weight must be normal or bold"),
                            ({"wrapper": "brackets"}, "letters.wrapper must be none, parens or period"),
                            ({"weight": ["bold"]}, "letters.weight must be normal or bold"),
                            ({"wrapper": {}}, "letters.wrapper must be none, parens or period"),
                            ({"case": ["upper"]}, "letters.case must be lower or upper"),
                            ({"offset_mm": [0, 101]}, "letters.offset_mm must be [dx, dy] in mm, each within ±100")):
        problems = S.validate_figure({**doc, "letters": letters}, expected_id="f")
        assert any(expect in p for p in problems), problems


def test_a_value_of_the_wrong_type_is_a_problem_and_breaks_no_other_figure(project):
    """`"weight": ["bold"]` raised "unhashable type" out of validation: `workspace` and `status`
    failed for the whole project with a message naming neither the file nor the key."""
    build(project)
    bad = json.loads(read(project.figure_json("fig-1"))) | {"id": "fig-2", "letters": {"weight": ["bold"]},
                                                           "width": {"preset": ["double"]}}
    bad["producers"][0]["cost"] = ["cheap"]
    bad["annotations"] = [{"id": "n", "type": ["text"]},
                          {"id": "m", "type": "arrow", "head": ["end"], "style": {"weight": {}},
                           "from": {"panel": ["a"], "x": 1, "y": 1}, "to": {"panel": "a", "part": "x", "at": []}}]
    (project.figures_dir / "fig-2").mkdir()
    project.figure_json("fig-2").write_text(json.dumps(bad))
    problems = S.validate_figure(bad, expected_id="fig-2")
    for expect in ("letters.weight must be normal or bold", "width must be", "producers[0].cost must be cheap",
                   "annotations[0].type must be one of", "annotations[1].head must be", "annotations[1].style.weight",
                   "annotations[1].from.panel ['a'] is not a panel", "annotations[1].to.at must be one of"):
        assert any(expect in p for p in problems), (expect, problems)
    states = {st.id: st for st in figure_status_all(project)}
    assert states["fig-1"].error is None and "letters.weight must be normal or bold" in states["fig-2"].error
    srv = Server(project, out=io.StringIO())
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "workspace"})
    figures = {f["id"]: f for f in json.loads(srv.out.getvalue().splitlines()[-1])["result"]["figures"]}
    assert "error" not in figures["fig-1"] and "letters.weight must be normal or bold" in figures["fig-2"]["error"]
    srv.out = io.StringIO()
    srv.dispatch({"jsonrpc": "2.0", "id": 2, "method": "update_figure",
                  "params": {"figure": "fig-1", "ops": [{"op": "letters", "patch": {"weight": ["bold"]}}]}})
    assert "letters.weight must be normal or bold" in json.loads(srv.out.getvalue())["error"]["data"]["problems"]


# ----------------------------------------------------------------------------- part offsets (I3)


def test_offsets_move_text_and_legend_exactly_and_nothing_else(project):
    build(project)
    svg0, man0 = _panel_svg(project), _manifest(project)
    _style(project, "main.xlabel", {"dx_mm": 2, "dy_mm": -1.5})
    _style(project, "main.legend", {"dx_mm": -3, "dy_mm": 4})
    assert build(project).ok
    svg1, man1 = _panel_svg(project), _manifest(project)

    for part, (dx, dy) in {"main.xlabel": (2, -1.5), "main.legend.control": (-3, 4),
                           "main.legend.trend": (-3, 4), "main.ylabel": (0, 0), "main.title": (0, 0)}.items():
        assert _moved_mm(svg0, svg1, part) == (pytest.approx(dx, abs=1e-3), pytest.approx(dy, abs=1e-3)), part
    assert man1["axes"] == man0["axes"], "the layout is frozen before the move: the axes stay put"
    # the box a canvas outlines moves with the ink, every edge by the offset
    lg0, lg1 = man0["parts"]["main.legend"]["bbox"], man1["parts"]["main.legend"]["bbox"]
    assert [(b - a) / PT for a, b in zip(lg0, lg1)] == pytest.approx([-3, 4, -3, 4], abs=1e-3)
    xl = man1["parts"]["main.xlabel"]
    assert xl["props"]["dx_mm"] == 2 and xl["base"] == {"dx_mm": 0, "dy_mm": 0}  # a script never offsets a part
    # every part reports what it takes, moved or not, so an editor can show it and tell an
    # override equal to the script's value; a tick label is not offered what it refuses
    assert man1["parts"]["main.ylabel"]["props"]["dx_mm"] == 0 and "base" not in man1["parts"]["main.ylabel"]
    assert "dx_mm" not in man1["parts"]["main.xtick.a"]["props"]


def test_a_horizontal_legend_move_leaves_its_box_at_the_same_height(project):
    """A legend pinned by its lower-left corner is measured by the manifest's renderer a
    little shorter than the SVG draws it: its box came out 0.34 mm lower after a move in x."""
    build(project)
    svg0, lg0 = _panel_svg(project), _manifest(project)["parts"]["main.legend"]["bbox"]
    _style(project, "main.legend", {"dx_mm": 0.5})
    assert build(project).ok
    lg1 = _manifest(project)["parts"]["main.legend"]["bbox"]
    assert _moved_mm(svg0, _panel_svg(project), "main.legend.control") == (pytest.approx(0.5, abs=1e-3), 0)
    assert [(b - a) / PT for a, b in zip(lg0, lg1)] == pytest.approx([0.5, 0, 0.5, 0], abs=1e-3)


def test_moving_an_expanded_legend_keeps_its_width(project):
    """matplotlib's legend-above-the-axes recipe: its width is its anchor box's, and pinned
    to a zero-size box it collapsed from 76 mm to 0."""
    _replace_in_producer(project, "    ax.legend()\n",
                         "    ax.legend(bbox_to_anchor=(0, 1.02, 1, 0.102), loc='lower left', ncols=2,"
                         " mode='expand', borderaxespad=0)\n")
    assert build(project).ok
    svg0, lg0 = _panel_svg(project), _manifest(project)["parts"]["main.legend"]["bbox"]
    _style(project, "main.legend", {"dx_mm": 1, "dy_mm": 1})
    assert build(project).ok
    svg1, lg1 = _panel_svg(project), _manifest(project)["parts"]["main.legend"]["bbox"]
    # each width is two edges the manifest rounds to 1e-3 pt, so two widths may differ by 2e-3
    assert lg1[2] - lg1[0] == pytest.approx(lg0[2] - lg0[0], abs=2e-3) and lg0[2] - lg0[0] > 50 * PT
    for part in ("main.legend.control", "main.legend.trend"):  # side by side, each moved exactly
        assert _moved_mm(svg0, svg1, part) == (pytest.approx(1, abs=1e-3), pytest.approx(1, abs=1e-3)), part


def test_moving_a_text_onto_a_best_placed_legend_leaves_the_legend_where_it_was(project):
    """A `loc="best"` legend avoids its axes' texts at every draw: without being frozen, it
    jumped 59.8 mm away from a text moved onto it."""
    _add_to_producer(project, 'ax.text(1.0, 0.2, "note")')
    assert build(project).ok
    svg0, parts = _panel_svg(project), _manifest(project)["parts"]
    legend, note = parts["main.legend"]["bbox"], parts["main.text.note"]["bbox"]
    dx, dy = round((legend[0] - note[0]) / PT + 1, 2), round((legend[1] - note[1]) / PT + 1, 2)
    _style(project, "main.text.note", {"dx_mm": dx, "dy_mm": dy})  # its corner 1 mm inside the legend
    assert build(project).ok
    svg1 = _panel_svg(project)
    assert _moved_mm(svg0, svg1, "main.text.note") == (pytest.approx(dx, abs=1e-3), pytest.approx(dy, abs=1e-3))
    assert _moved_mm(svg0, svg1, "main.legend.control") == (0, 0)


def test_a_legend_added_with_add_artist_stays_where_best_put_it(project):
    """matplotlib shows two legends in one axes with `ax.add_artist(first)`; the first is "best"
    by default and was not pinned, so it moved 57 mm away from a text moved elsewhere."""
    _add_to_producer(project, 'from matplotlib.lines import Line2D\n'
                              'extra = ax.legend(handles=[Line2D([], [], color="k", label="extra key")], loc="best",'
                              ' frameon=True)\n'
                              'ax.add_artist(extra)\n'
                              'ax.legend(loc="upper left")\n'
                              'ax.text(0.05, 0.05, "mover", transform=ax.transAxes)')
    assert build(project).ok
    svg0 = _panel_svg(project)
    _style(project, "main.text.mover", {"dx_mm": 60, "dy_mm": -40})
    assert build(project).ok
    svg1 = _panel_svg(project)
    assert _moved_mm(svg0, svg1, "main.text.mover") == (pytest.approx(60, abs=1e-3), pytest.approx(-40, abs=1e-3))

    def key(root):  # the unnamed legend's text, found by what it says
        text = next(el for el in root.iter(f"{SVG}text") if (el.text or "").strip() == "extra key")
        return float(text.get("x")), float(text.get("y"))

    assert key(svg1) == pytest.approx(key(svg0), abs=1e-3)


def test_a_moved_title_lands_exactly_and_the_other_titles_stay(project):
    """matplotlib lifts a title that dips below the axes top and lines the titles up at
    every draw: a title moved 6 mm down came out 1.6 mm down, and the left title rose."""
    _add_to_producer(project, 'ax.set_title("L", loc="left")')
    assert build(project).ok
    svg0 = _panel_svg(project)
    _style(project, "main.title", {"dx_mm": 1, "dy_mm": 6})  # well past the title's 6 pt pad
    assert build(project).ok
    svg1 = _panel_svg(project)
    assert _moved_mm(svg0, svg1, "main.title") == (pytest.approx(1, abs=1e-3), pytest.approx(6, abs=1e-3))
    assert _moved_mm(svg0, svg1, "main.title-left") == (0, 0)


def test_a_wildcard_moves_every_part_it_names_by_the_same_amount(project):
    build(project)
    svg0 = _panel_svg(project)
    _style(project, "main.*label", {"dx_mm": 1})
    assert build(project).ok
    svg1 = _panel_svg(project)
    for part in ("main.xlabel", "main.ylabel"):
        assert _moved_mm(svg0, svg1, part) == (pytest.approx(1, abs=1e-3), 0), part


def _arrow(root):
    """(start, tip) of the annotation arrow's shaft: ``M x y Q cx cy x y``."""
    d = next(_by_id(root, "arrow").iter(f"{SVG}path")).get("d").split()
    return (float(d[1]), float(d[2])), (float(d[-2]), float(d[-1]))


def test_an_annotation_text_moves_and_its_arrow_keeps_pointing_at_the_data(project):
    _add_to_producer(project, 'ax.annotate("peak", xy=(1, 1.8), xytext=(0.2, 2.2),\n'
                              '            arrowprops={"arrowstyle": "->", "shrinkA": 0, "shrinkB": 0, "gid": "arrow"})')
    assert build(project).ok
    svg0 = _panel_svg(project)
    _style(project, "main.text.peak", {"dx_mm": 1.5, "dy_mm": 1})
    assert build(project).ok
    svg1 = _panel_svg(project)
    assert _moved_mm(svg0, svg1, "main.text.peak") == (pytest.approx(1.5, abs=1e-3), pytest.approx(1, abs=1e-3))
    (start0, tip0), (start1, tip1) = _arrow(svg0), _arrow(svg1)
    # The arrow still ends at xy (shrinkB 0). Its vertex is set back along the shaft by half
    # the line width over the sine of the head's half-angle (~0.67 pt), so as the shaft turns
    # it moves by hundredths of a point; moving xy by the offset would move it ~5 pt.
    assert tip1 == pytest.approx(tip0, abs=0.05), "the arrow still ends at xy"
    assert start1[0] - start0[0] > 0.5 * PT and start1[1] - start0[1] > 0.3 * PT, "it starts at the moved text"


def test_a_high_dpi_panel_moves_parts_exactly_and_measures_them_in_points(project):
    """An SVG is drawn at 72 dpi whatever the figure's dpi. At a producer's `set_dpi(300)`
    (for sharper rasterized layers), a legend's 2 mm move landed (-4.35, +42.2) mm away, and
    every manifest box came out 300/72 times too large, so the ink check flagged the panel."""
    _add_to_producer(project, 'ax.annotate("peak", xy=(1, 1.8), xytext=(10, 10), textcoords="offset points")')
    assert build(project).ok
    at72 = _manifest(project)
    _add_to_producer(project, "f.set_dpi(300)")
    assert build(project).ok
    at300 = _manifest(project)
    assert {n: p["bbox"] for n, p in at300["parts"].items()} == {n: p["bbox"] for n, p in at72["parts"].items()}
    assert at300["axes"] == at72["axes"] and _ink(project) == []
    svg0 = _panel_svg(project)
    for part in ("main.legend", "main.xlabel", "main.text.peak"):
        _style(project, part, {"dx_mm": 2, "dy_mm": 1})
    assert build(project).ok
    svg1 = _panel_svg(project)
    for part in ("main.legend.control", "main.xlabel", "main.text.peak"):
        assert _moved_mm(svg0, svg1, part) == (pytest.approx(2, abs=1e-3), pytest.approx(1, abs=1e-3)), part


def test_a_panel_with_no_offsets_is_drawn_as_the_golden_was(project):
    """The no-offset path is guarded against bytes written before the change under test, not
    against itself: comparing a zero offset with none would pass whatever that path became.
    The golden holds what the last deliberate drawing change drew, panel.svg and manifest.json
    both; tests/golden/make_golden.py says from which source (never one older than the last
    `build.RENDER` bump: 0.2.x wrote other manifests, which no working tree can match)."""
    versions = json.loads(read(GOLDEN / "versions.json"))
    if matplotlib.__version__ != versions["matplotlib"]:
        pytest.skip(f"the golden panel was drawn with matplotlib {versions['matplotlib']}, not "
                    f"{matplotlib.__version__}: regenerate it with tests/golden/make_golden.py")
    assert build(project).ok
    pdir = project.panel_dir("fig-1", "a")
    for name in ("panel.svg", "manifest.json"):
        assert read(pdir / name) == read(GOLDEN / name), f"{name} differs from idofig {versions['idofig']}'s"


def _save_in_process(project, monkeypatch, out):
    """Run conftest's producer in this process (so a test can patch draw), staged to ``out``."""
    import runpy

    import matplotlib.pyplot as plt

    for key, value in {"IDOFIG_ROOT": project.root, "IDOFIG_FIGURE": "fig-1", "IDOFIG_OUTPUT_DIR": out}.items():
        monkeypatch.setenv(key, str(value))
    try:
        runpy.run_path(str(project.root / "figures/fig-1/make.py"))
    finally:
        plt.close("all")
    return {pid: read(out / pid / "panel.svg") for pid in ("a", "b")}


def test_what_a_save_wraps_around_the_drawing_adds_no_byte(project, monkeypatch, tmp_path):
    """The golden above runs only under the matplotlib it was drawn with (a CI that installs
    the next one skips it); this holds under any, and compares two idofig saves: of a 2D
    panel with no offset and nothing rasterized, one with the draws a save wraps
    (``draw._instrument``: the drawn-part tracking, the raster name groups) and one without.
    They only watch; were they to change every panel's bytes, every panel in every project
    would read as not reproducible. What both saves share (``SAVE_RC``, ``finish_panel_svg``)
    only the golden guards."""
    wrapped = _save_in_process(project, monkeypatch, tmp_path / "wrapped")

    def watch_nothing(table, undo):  # what 0.2.2 did: measure every part
        for part in table.parts.values():
            if not part.group:
                part.artists[0]._idofig_drawn = True

    monkeypatch.setattr(draw, "_instrument", watch_nothing)
    assert _save_in_process(project, monkeypatch, tmp_path / "bare") == wrapped


def test_a_panel_with_no_offsets_is_saved_once(project, monkeypatch, tmp_path):
    """Only a panel with an offset is laid out by a first save and then moved."""
    import matplotlib.pyplot as plt

    monkeypatch.setenv("IDOFIG_ROOT", str(project.root))
    monkeypatch.setenv("IDOFIG_OUTPUT_DIR", str(tmp_path / "staging"))
    saves = []
    plain = draw._svg
    monkeypatch.setattr(draw, "_svg", lambda fig: saves.append(fig) or plain(fig))
    project.panel_dir("fig-1", "a").mkdir(parents=True)
    for style, expected in (({}, 1), ({"main.xlabel": {"dx_mm": 1}}, 2)):
        (project.panel_dir("fig-1", "a") / "style.json").write_text(json.dumps({"schema": 1, "parts": style}))
        saves.clear()
        p = draw.panels("a", figure="fig-1")
        ax = p["a"].subplots()
        draw.name(ax, "main")
        ax.plot([0, 1], [0, 1])
        ax.set_xlabel("x")
        draw.save(p)
        plt.close("all")
        assert len(saves) == expected, style


def test_a_zero_offset_changes_no_byte_of_the_panel(project):
    _style(project, "main.xlabel", {"fontsize": 9})
    build(project)
    before = read(project.panel_dir("fig-1", "a") / "panel.svg")
    _style(project, "main.xlabel", {"dx_mm": 0, "dy_mm": 0})
    build(project)
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == before


def test_saving_twice_does_not_move_a_part_twice(project):
    """A second save once read the first one's override back as the script's value: base
    `dx_mm` 2 and `fontsize` 9, so an editor that drops an override equal to base would put
    the label 2 mm back and at the script's size."""
    _style(project, "main.xlabel", {"dx_mm": 2, "fontsize": 9})
    _style(project, "main.legend", {"dy_mm": 3})
    build(project)
    pdir = project.panel_dir("fig-1", "a")
    once, manifest = read(pdir / "panel.svg"), read(pdir / "manifest.json")
    script_size = json.loads(manifest)["parts"]["main.xlabel"]["base"]["fontsize"]
    assert json.loads(manifest)["parts"]["main.xlabel"]["base"] == {"dx_mm": 0, "fontsize": script_size}
    _replace_in_producer(project, "idf.save(p)", "idf.save(p)\nidf.save(p)")
    assert build(project).ok
    assert read(pdir / "panel.svg") == once and read(pdir / "manifest.json") == manifest
    # a value the script sets again between saves is the script's value again
    _replace_in_producer(project, "idf.save(p)\nidf.save(p)",
                         "idf.save(p)\nfor f in p.values():\n    f.axes[0].xaxis.label.set_fontsize(11)\nidf.save(p)")
    assert build(project).ok
    xl = _manifest(project)["parts"]["main.xlabel"]
    assert xl["base"] == {"dx_mm": 0, "fontsize": 11} and xl["props"]["fontsize"] == 9


def test_a_save_leaves_the_script_its_own_figure(project):
    """An offset froze the layout for good: a script that saved, set a longer y label and
    saved again (a notebook re-running its save cell) kept the first layout, and the label
    was clipped 2 mm off the panel only because the legend had a 0.5 mm offset."""
    _style(project, "main.legend", {"dx_mm": 0.5})
    longer = '    ax.set_ylabel("a much longer y label", fontsize=16)\n'
    _replace_in_producer(project, '    ax.set_ylabel("response")\n', longer)
    assert build(project).ok
    pdir = project.panel_dir("fig-1", "a")
    final = read(pdir / "panel.svg"), _manifest(project)["axes"]
    _replace_in_producer(project, longer, '    ax.set_ylabel("response")\n')
    _replace_in_producer(project, "idf.save(p)", "idf.save(p)\nfor f in p.values():\n"
                                                 '    f.axes[0].set_ylabel("a much longer y label", fontsize=16)\n'
                                                 "idf.save(p)")
    assert build(project).ok
    assert (read(pdir / "panel.svg"), _manifest(project)["axes"]) == final, "laid out as if drawn so from the start"
    assert _ink(project) == []


@pytest.fixture
def saver(project, monkeypatch, tmp_path):
    """``saved(fig, parts)``: the panel.svg (text) and manifest idofig writes for ``fig``, panel a,
    under a style.json of ``parts``, saved in this process, as a notebook saves one figure again
    and again. ``fresh()`` makes panel a's Figure."""
    import matplotlib.pyplot as plt

    monkeypatch.setenv("IDOFIG_ROOT", str(project.root))
    monkeypatch.setenv("IDOFIG_OUTPUT_DIR", str(tmp_path / "staging"))
    pdir = project.panel_dir("fig-1", "a")
    pdir.mkdir(parents=True, exist_ok=True)

    def saved(fig, parts):
        (pdir / "style.json").write_text(json.dumps({"schema": 1, "parts": parts}))
        draw.save(fig)
        out = tmp_path / "staging" / "a"
        return read(out / "panel.svg"), json.loads(read(out / "manifest.json"))

    saved.fresh = lambda: draw.panel("a", figure="fig-1")
    yield saved
    plt.close("all")


def test_an_offset_removed_between_saves_leaves_its_part_where_the_script_draws_it(saver):
    """An offset stayed on its part: a notebook that saved with `dx_mm: 3`, then removed the
    entry (or set it to 0) and saved again still drew the label 3 mm away, and its manifest
    said `dx_mm: 3` though no override applied."""
    f = saver.fresh()
    ax = f.subplots()
    draw.name(ax, "main")
    ax.plot([0, 1], [0, 1], label="up")
    ax.plot([0, 1], [1, 0], label="down")
    ax.set_xlabel("x")
    ax.set_title("t")
    ax.legend()  # "best": the save that moves a part pins it

    plain, _ = saver(f, {})
    moved, _ = saver(f, {"main.xlabel": {"dx_mm": 3}, "main.legend": {"dy_mm": 1}})
    assert _moved_mm(ET.fromstring(plain), ET.fromstring(moved), "main.xlabel") == (pytest.approx(3, abs=1e-3), 0)
    for parts in ({}, {"main.xlabel": {"dx_mm": 0, "dy_mm": 0}}):
        again, manifest = saver(f, parts)
        assert again == plain, parts
        assert manifest["parts"]["main.xlabel"]["props"]["dx_mm"] == 0


def _annotated(f):
    ax = f.subplots()
    draw.name(ax, "main")
    ax.plot([0, 1, 2], [0, 1, 0.5])
    ax.annotate("peak", xy=(1, 1), xytext=(0.2, 0.8), arrowprops={"arrowstyle": "->"})


def _three_d_label(f):
    ax = f.add_subplot(projection="3d")
    draw.name(ax, "main")
    ax.plot([0, 1, 2], [0, 1, 4], [0, 2, 1])
    ax.set_zlabel("depth")


def _titled(f):
    ax = f.subplots()
    draw.name(ax, "main")
    ax.plot([0, 1], [0, 1])
    ax.set_title("T")


def _best_legend(f):
    ax = f.subplots()
    draw.name(ax, "main")
    ax.plot([0, 1], [0.1, 0.2], label="low")
    ax.plot([0, 1], [0.9, 1.0], label="high")
    ax.text(0.5, 0.5, "note")
    ax.legend()  # "best": pinned by the save that moves the note


def _data_under_the_legend(f):  # "best" avoids data: laid out afresh, the legend moves
    ax = f.axes[0]
    ax.plot([0, 0.45], [0.02, 0.4])
    ax.plot([0.55, 1], [0.6, 0.98])


# recipe: (draw the panel, the part a save moves, what the script changes before its next save,
# the part that change would move). matplotlib shrinks a 3D axes in a constrained layout at each
# save of the same figure, plain matplotlib too, with or without a move: by about 4.6 pt a save
# below 3.11, a few 1e-4 pt from 3.11. So a save is compared with the save of a twin figure,
# made the same way and saved as often, never with an earlier save of its own figure: compared
# with its own first save, the second moved save of a 3D label failed under 3.8 and 3.10.
_RESTORED = {
    "annotation": (_annotated, "main.text.peak", None, "main.text.peak"),  # its text coordinates
    "3d-label": (_three_d_label, "main.zlabel", None, "main.zlabel"),  # the draw that adds the move back
    "title": (_titled, "main.title", lambda f: f.axes[0].xaxis.tick_top(), "main.title"),  # placed anew
    "best-legend": (_best_legend, "main.text.note", _data_under_the_legend, "main.legend.low"),  # "best" again
}


@pytest.mark.parametrize("recipe", sorted(_RESTORED))
def test_a_figure_saved_with_a_move_saves_next_as_one_never_moved(saver, recipe):
    """SPEC: a save's changes last one save. Each restore the save makes, removed, was still
    green before this test: a 3D label saved at dx_mm 2 stayed 2 mm off in the next plain save
    and moved 4 mm in the next moved one; an annotation kept its move; a "best" legend stayed
    pinned where data then covered it; a title placed by a moved save stayed below the top tick
    labels the script turned on after it."""
    make, part, change, watched = _RESTORED[recipe]
    f, twin = saver.fresh(), saver.fresh()  # the twin is never moved, and saved whenever f is
    make(f)
    make(twin)
    move = {part: {"dx_mm": 2, "dy_mm": 1}}
    for n in (1, 2):
        moved, plain = ET.fromstring(saver(f, move)[0]), ET.fromstring(saver(twin, {})[0])
        assert _moved_mm(plain, moved, part) == (pytest.approx(2, abs=1e-3), pytest.approx(1, abs=1e-3)), \
            f"save {n}: moved once, not twice"
        if watched != part:
            assert _text_xy(moved, watched) == pytest.approx(_text_xy(plain, watched), abs=0.01), f"save {n}"
    for fig in (f, twin) if change else ():
        change(fig)
    assert saver(f, {})[0] == saver(twin, {})[0], "saved as the figure it is, never moved"


# recipe: (make the legend, its part, whether saving the same figure again gives the same
# bytes). matplotlib's constrained layout places the axes of an expanded legend a few 1e-8
# of the panel differently at each save of the same figure — plain matplotlib too — which
# changes a clip path's hashed id: that one is compared by box, not by byte.
_ANCHORED_LEGENDS = {
    "inside": (lambda f, ax: ax.legend(bbox_to_anchor=(0.05, 0.95), loc="upper left"), "main.legend", True),
    "beside": (lambda f, ax: ax.legend(loc="center left", bbox_to_anchor=(1.0, 0.5)), "main.legend", True),
    "expanded": (lambda f, ax: ax.legend(bbox_to_anchor=(0, 1.02, 1, 0.102), loc="lower left", ncols=2,
                                         mode="expand", borderaxespad=0), "main.legend", False),
    "figure": (lambda f, ax: f.legend(bbox_to_anchor=(1, 1), loc="upper right"), "legend", True),
}


@pytest.mark.parametrize("recipe", sorted(_ANCHORED_LEGENDS))
def test_a_legend_the_script_anchored_gets_its_anchor_back_after_a_move(saver, recipe):
    """The anchor was put back through `set_bbox_to_anchor`, which wraps any box in its
    parent's transform: a script's own anchor, already in display units, came back read as
    fractions of the axes. The next save of a legend moved 1 mm drew it (+19839, -8312) mm
    away, and a plain save after that (+4564939, -1187669) mm away."""
    make_legend, part, same_bytes = _ANCHORED_LEGENDS[recipe]
    f = saver.fresh()
    ax = f.subplots()
    draw.name(ax, "main")
    ax.plot([0, 1], [0, 1], label="up")
    ax.plot([0, 1], [1, 0], label="down")
    make_legend(f, ax)

    def saved(parts):
        svg, manifest = saver(f, parts)
        return svg, manifest["parts"][part]["bbox"]

    plain, box0 = saved({})
    moved, box1 = saved({part: {"dx_mm": 1, "dy_mm": -0.5}})
    assert [(b - a) / PT for a, b in zip(box0, box1)] == pytest.approx([1, -0.5, 1, -0.5], abs=1e-3)
    for parts, (svg, box), why in (({part: {"dx_mm": 1, "dy_mm": -0.5}}, (moved, box1), "moved once, not twice"),
                                   ({}, (plain, box0), "where the script anchored it")):
        again, box_again = saved(parts)
        assert box_again == pytest.approx(box, abs=1e-3), why
        assert again == svg or not same_bytes, why


def test_a_number_that_is_not_finite_is_refused(project, monkeypatch):
    """NaN passes `v < lo` and `v > hi` alike: `dx_mm: NaN` (the CLI's `dx_mm=nan`, a JSON
    client, a hand-edited file) was listed applied, and its part left the SVG as an empty
    group, its legend with it. Checked only on a part the manifest names, it still reached
    style.json through a wildcard, and every workspace reply then carried a bare NaN, which
    JSON.parse rejects: SUNA waited for an answer that never came."""
    from idofig import cli
    from idofig.fsutil import loads

    build(project)
    for props in ({"dx_mm": math.nan}, {"dy_mm": -math.inf}, {"fontsize": math.nan}):
        assert "must be a finite number" in _refusal(project, "main.xlabel", props), props
    monkeypatch.chdir(project.root)
    style = project.panel_dir("fig-1", "a") / "style.json"
    for part in ("main.xlabel", "main.*label"):  # a wildcard gets no property check
        assert cli.main(["style", "fig-1", "a", part, "dx_mm=nan"]) == 2 and not style.exists(), part
    (project.panel_dir("fig-1", "a") / "manifest.json").unlink()  # nothing to check a part against
    with pytest.raises(S.SpecError, match="must be a finite number"):
        S.update_style(style, "main.xlabel", {"dy_mm": math.inf})
    assert not style.exists()

    # a hand-edited NaN is not JSON: the file is refused by name, like any other broken JSON
    style.write_text('{"schema": 1, "parts": {"main.xlabel": {"dx_mm": NaN}}}')
    report = build(project)
    assert not report.ok and "NaN is not a JSON number" in report.runs[0].error, report.to_json()
    srv = Server(project, out=io.StringIO())
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "workspace"})
    figure = loads(srv.out.getvalue().splitlines()[-1])["result"]["figures"][0]  # strict JSON, NaN refused
    assert figure["styles"]["a"] is None
    before = read(project.figure_json("fig-1"))
    with pytest.raises(S.SpecError, match=r"figure\.json is not valid:\n  - not JSON: .*nan"):  # none is written
        S.update_figure(project.figure_json("fig-1"), [{"op": "app.set", "key": "caption", "value": math.nan}])
    assert read(project.figure_json("fig-1")) == before


def test_no_reply_carries_a_number_json_has_not(project, monkeypatch):
    """JSON has no NaN or Infinity, and a reply with one is a line JSON.parse refuses: SUNA
    waited for an answer that never came. They came from files read leniently (a journal
    preset a Python tool wrote with a blank cell as `NaN`, a `1e999` that Python reads as inf)
    and from answers nothing checked; a refusal named no file."""
    from idofig.fsutil import loads
    from idofig.project import find_project

    def last(srv):  # the reply, parsed as strictly as JSON.parse does
        return loads(srv.out.getvalue().splitlines()[-1])

    build(project)
    srv = Server(project, out=io.StringIO())
    manifest = project.panel_dir("fig-1", "a") / "manifest.json"
    manifest.write_text(read(manifest).replace('"schema": 1', '"schema": 1, "x": NaN', 1))
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "parts", "params": {"figure": "fig-1", "panel": "a"}})
    assert last(srv)["error"]["message"] == (f"{manifest} is not valid:\n  - not valid JSON: "
                                             "NaN is not a JSON number")
    for text in ('{"schema": 1, "parts": {"main.xlabel": {"fontsize": 1e999}}}',
                 '{"schema": 1, "parts": {"main.xlabel": {"fontsize": Infinity}}}'):
        srv.dispatch({"jsonrpc": "2.0", "id": 2, "method": "restore", "params": {
            "path": "figures/fig-1/panels/a/style.json", "text": text, "expect_sha": None}})
        assert "panels/a/style.json is not valid:\n  - not valid JSON: " in last(srv)["error"]["message"], text
    fig = project.figure_json("fig-1")
    good = read(fig)
    fig.write_text(good.replace('"caption": {', '"caption": {"zoom": 1e999, ', 1))
    with pytest.raises(S.SpecError, match="not valid JSON: 1e999 is too large for a number"):
        S.load_figure(fig)
    fig.write_text(good)

    (project.root / "house.json").write_text(json.dumps({"id": "house", "minFontPt": 5, "extra": math.nan}))
    (project.root / "idofig.toml").write_text('journal = "house.json"\n')
    srv = Server(find_project(project.root), out=io.StringIO())
    srv.dispatch({"jsonrpc": "2.0", "id": 3, "method": "workspace"})
    assert "house.json is not valid:\n  - not valid JSON: NaN is not a JSON number" in last(srv)["error"]["message"]
    # a `width` op reads the preset too: named as itself, never as figure.json's "bad operation"
    srv.dispatch({"jsonrpc": "2.0", "id": 5, "method": "update_figure",
                  "params": {"figure": "fig-1", "ops": [{"op": "width", "mm": 170}]}})
    assert re.fullmatch(r"\S+/house\.json is not valid:\n  - not valid JSON: NaN is not a JSON number",
                        last(srv)["error"]["message"])

    # an answer with one, from wherever it came, is an error for that request, never a bare NaN
    monkeypatch.setattr(Server, "m_hello", lambda self, rid: {"zoom": math.inf})
    srv.dispatch({"jsonrpc": "2.0", "id": 4, "method": "hello"})
    reply = last(srv)
    assert reply["id"] == 4 and reply["error"]["message"].startswith("hello: the answer holds a number JSON cannot")


def test_a_line_that_is_no_request_object_is_refused_and_the_server_goes_on(project):
    """A JSON-RPC batch (`[{…}]`) or a bare `5` raised out of `serve`: the server ended with no
    reply, and every request after it went unanswered."""
    srv = Server(project, out=io.StringIO())
    srv.serve(io.StringIO('[{"jsonrpc": "2.0", "id": 1, "method": "hello"}]\n5\n'
                          '{"jsonrpc": "2.0", "id": 2, "method": "hello"}\n'))
    ready, *replies = (json.loads(line) for line in srv.out.getvalue().splitlines())
    assert [(r["id"], r["error"]["code"]) for r in replies[:2]] == [(None, -32600), (None, -32600)]
    assert replies[0]["error"]["message"] == "invalid request: expected a JSON object (batches are not supported)"
    assert replies[2]["id"] == 2 and "version" in replies[2]["result"]


def test_a_request_holding_a_number_json_cannot_carry_is_a_parse_error_and_the_server_goes_on(project):
    """Requests were read leniently: an id of NaN, Infinity or 1e999 (valid JSON, which Python
    reads as inf) could be echoed in no answer, the ValueError ended the server, and every
    request behind it went unanswered; `build {timeout: NaN}` failed later, never naming
    `timeout`. Read as strictly as replies are written, each is a parse error."""
    from idofig.fsutil import loads

    srv = Server(project, out=io.StringIO())
    srv.serve(io.StringIO("".join(f'{{"jsonrpc": "2.0", "id": {i}, "method": "nope"}}\n'
                                  for i in ("NaN", "Infinity", "1e999"))
                          + '{"jsonrpc": "2.0", "id": 1, "method": "build", "params": {"timeout": NaN}}\n'
                          + '{"jsonrpc": "2.0", "id": 2, "method": "hello"}\n'))
    ready, *replies = (loads(line) for line in srv.out.getvalue().splitlines())  # each line strict JSON
    assert [(r["id"], r["error"]["code"]) for r in replies[:4]] == [(None, -32700)] * 4
    assert replies[2]["error"]["message"] == "parse error: 1e999 is too large for a number"
    assert replies[4]["id"] == 2 and "version" in replies[4]["result"] and len(replies) == 5


def test_a_manifest_with_nan_in_it_is_named_and_does_not_stop_a_style_write(project, capsys):
    """idofig 0.2.2 wrote NaN into a manifest (an image's limits from all-NaN data), and a
    producer whose `run` uses that idofig still does. `idofig parts`, `idofig style` and
    `idofig locate` (and the server's `locate`, SUNA's figure_locate) ended in a traceback that
    named no file, and `idofig style` could write no override to the panel at all."""
    from idofig.cli import main

    build(project)
    manifest = project.panel_dir("fig-1", "a") / "manifest.json"
    manifest.write_text(read(manifest).replace('"schema": 1', '"schema": 1, "legacy": NaN', 1))
    named = f"idofig: {manifest} is not valid:\n  - not valid JSON: NaN is not a JSON number\n"
    for args in (["parts", "fig-1", "a"], ["locate", "fig-1", "a", "main.xlabel"]):
        capsys.readouterr()
        assert main(args) == 2 and capsys.readouterr().err == named, args
    # written without the per-part check the manifest would give, as the server's update_style does
    assert main(["style", "fig-1", "a", "main.xlabel", "fontsize=9"]) == 0
    assert S.load_style(project.panel_dir("fig-1", "a") / "style.json")["parts"] == {"main.xlabel": {"fontsize": 9}}
    srv = Server(project, out=io.StringIO())
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "locate",
                  "params": {"figure": "fig-1", "panel": "a", "part": "main.xlabel"}})
    error = json.loads(srv.out.getvalue().splitlines()[-1])["error"]
    assert error["message"] == named[len("idofig: "):-1] and "traceback" not in error["data"]


def test_an_integer_too_large_for_a_float_is_refused_by_name_not_a_crash(project):
    """Python reads a 400-digit JSON integer as an int, which the finiteness check converted to
    a float: OverflowError, and one style value failed the whole producer (no panel written)
    and every edit that carried it, with a message naming no part or property. Refused only
    where the manifest names the part, it then reached style.json through a pattern, or on a
    panel with no manifest: every workspace reply carried it, JSON.parse read it as Infinity,
    and JSON.stringify wrote that back as null, which update_style takes as "remove it"."""
    from idofig import cli

    huge = int("1" + "0" * 400)
    build(project)
    style = project.panel_dir("fig-1", "a") / "style.json"
    assert "dx_mm must be a finite number" in _refusal(project, "main.xlabel", {"dx_mm": huge})
    for props in ({"dx_mm": huge}, {"fontsize": huge}):
        with pytest.raises(S.SpecError, match=r"main\.\*label'\]\.\w+ must be a finite number"):
            S.update_style(style, "main.*label", props)
    assert cli.main(["style", "fig-1", "a", "main.*label", f"dx_mm={huge}"]) == 2
    (project.panel_dir("fig-1", "a") / "manifest.json").unlink()  # nothing to check a part against
    with pytest.raises(S.SpecError, match="must be a finite number"):
        S.update_style(style, "main.xlabel", {"fontsize": huge})
    assert not style.exists()
    # written by hand, the file is refused by name, as one with a bare NaN or 1e999 in it is
    style.write_text('{"schema": 1, "parts": {"main.xlabel": {"fontsize": %d}}}' % huge)
    report = build(project)
    assert not report.ok and "parts['main.xlabel'].fontsize must be a finite number" in report.runs[0].error
    for op in ({"op": "letter", "panel": "a", "offset_mm": [huge, 0]}, {"op": "place", "panel": "a", "x": huge},
               {"op": "annotation.add", "annotation": {"id": "n", "type": "text", "text": "t",
                                                        "at": {"x": huge, "y": 0}}}):
        with pytest.raises(S.SpecError):
            S.update_figure(project.figure_json("fig-1"), [op])


def test_a_limit_width_or_size_that_is_not_finite_is_recorded_as_null(project, saver, monkeypatch):
    """A manifest is JSON, which has no NaN, and idofig writes none: a colour limit computed
    from missing data (a percentile of all-NaN values), a line width or a font size taken from
    data with a gap, all of which matplotlib draws with, made the save of every panel of the
    producer fail in the JSON encoder, naming no panel (idofig 0.2.2 wrote the NaN). So did an
    alpha per mark, an array (`scatter(…, alpha=[…])`), which is no one alpha: `null`, as the
    colour of marks that differ."""
    _add_to_producer(project, 'import numpy as np\n'
                              'from matplotlib.collections import LineCollection\n'
                              'm = f.add_axes([0.6, 0.6, 0.3, 0.3])\n'
                              'm.imshow([[0, 1], [2, 3]], vmin=float("nan"), gid="map")\n'
                              'm.imshow([[0, 1], [2, 3]], alpha=np.array([[0.2, 0.5], [1, 1]]), gid="faded_map")\n'
                              'ax.plot([0, 1], [1, 2], lw=float("nan"), label="gap")\n'
                              'ax.text(0.5, 0.5, "unsized", fontsize=float("nan"))\n'
                              'ax.add_collection(LineCollection([[(0, 0), (1, 1)]], linewidths=float("nan"), label="links"))\n'
                              'ax.eventplot([[0.1, 0.5]], linewidths=float("nan"), label="spikes")\n'
                              'ax.scatter([0, 1, 2], [1, 2, 1], alpha=np.array([0.2, 0.5, 1.0]), label="faded")')
    assert build(project).ok
    parts = _manifest(project)["parts"]
    assert parts["map"]["props"]["vmin"] is None
    assert parts["main.series.gap"]["props"]["linewidth"] is None
    assert parts["main.text.unsized"]["props"]["fontsize"] is None
    for name in ("main.series.links", "main.series.spikes"):
        assert parts[name]["props"]["linewidth"] is None and "thinnest_pt" not in parts[name], name
    assert parts["main.series.faded"]["props"]["alpha"] is None and parts["faded_map"]["props"]["alpha"] is None
    # a value nothing cleaned is an error that names its panel, not an encoder traceback
    import numpy as np

    from idofig import styling
    from idofig.errors import IdofigError

    for value in (math.nan, np.array([0.5])):  # ValueError, TypeError
        monkeypatch.setattr(styling, "get_props", lambda artist, kind: {"linewidth": value})
        fig = saver.fresh()
        fig.subplots()
        with pytest.raises(IdofigError, match="^fig-1/a: the manifest holds a value JSON cannot carry"):
            saver(fig, {})


def test_a_tick_label_cannot_be_moved(project, monkeypatch, capsys):
    """Refused on every path that writes or checks a style: the server's update_style,
    move_style and validate_style, the `idofig style` command, and a build (each passes the
    part's role; dropping it from any one of the first four left every other test green).
    Written by hand, it is reported by `idofig status` too, which printed nothing of it."""
    from idofig import cli

    def call(method, **params):
        srv.out = io.StringIO()
        srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        return json.loads(srv.out.getvalue().splitlines()[-1])

    refused = "copies its transform to new ticks"
    build(project)
    style = project.panel_dir("fig-1", "a") / "style.json"
    srv = Server(project, out=io.StringIO())
    for part in ("main.xtick.a", "main.xtick.*"):
        reply = call("update_style", figure="fig-1", panel="a", part=part, props={"dx_mm": 1})
        assert refused in " ".join(reply["error"]["data"]["problems"]), part
    assert cli.main(["style", "fig-1", "a", "main.xtick.a", "dx_mm=1"]) == 2 and not style.exists()
    assert refused in " ".join(call("validate_style", kind="text", props={"dx_mm": 1}, role="tick")["result"])
    assert call("validate_style", kind="text", props={"dx_mm": 1})["result"] == []
    S.update_style(style, "main.xlabel", {"dx_mm": 1})
    before = read(style)
    reply = call("move_style", figure="fig-1", panel="a", **{"from": "main.xlabel", "to": "main.xtick.a"})
    assert refused in " ".join(reply["error"]["data"]["problems"]) and read(style) == before
    style.unlink()
    # written by hand, it is reported and not applied
    x0 = _text_xy(_panel_svg(project), "main.xtick.a")
    (project.panel_dir("fig-1", "a") / "style.json").write_text(
        json.dumps({"schema": 1, "parts": {"main.xtick.a": {"dx_mm": 1}}}))
    assert build(project).ok
    assert _manifest(project)["style"]["invalid"][0]["prop"] == "dx_mm"
    assert _text_xy(_panel_svg(project), "main.xtick.a") == x0
    monkeypatch.chdir(project.root)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert any(line.startswith("      ! ignored main.xtick.a.dx_mm: ") and line.endswith(refused)
               for line in capsys.readouterr().out.splitlines())
    assert P.describe()["refused_by_role"]["tick"] == ["dx_mm", "dy_mm"]
    assert P.describe()["kinds"]["text"]["dx_mm"] == {"type": "number", "min": -100, "max": 100, "unit": "mm"}


def _refusal(project, part, props):
    """What the server says to setting ``props`` on ``part`` of panel a."""
    srv = Server(project, out=io.StringIO())
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "update_style",
                  "params": {"figure": "fig-1", "panel": "a", "part": part, "props": props}})
    return " ".join(json.loads(srv.out.getvalue().splitlines()[-1])["error"]["data"]["problems"])


def test_a_legends_entries_and_title_move_only_with_the_legend(project):
    """A 5 mm move of one entry left its key behind and put its words past the frame, which
    kept its size and place."""
    _replace_in_producer(project, "    ax.legend()\n", '    ax.legend(title="kind")\n')
    assert build(project).ok
    svg0, parts = _panel_svg(project), _manifest(project)["parts"]
    for part in ("main.legend.control", "main.legend.title"):
        assert "dx_mm" not in parts[part]["props"], part
        assert "move the legend instead" in _refusal(project, part, {"dx_mm": 5}), part
    (project.panel_dir("fig-1", "a") / "style.json").write_text(json.dumps(
        {"schema": 1, "parts": {"main.legend.control": {"dx_mm": 5}, "main.legend.title": {"dy_mm": 1}}}))
    assert build(project).ok
    invalid = _manifest(project)["style"]["invalid"]
    assert sorted((i["part"], i["prop"]) for i in invalid) == [("main.legend.control", "dx_mm"),
                                                               ("main.legend.title", "dy_mm")]
    for part in ("main.legend.control", "main.legend.title"):
        assert _moved_mm(svg0, _panel_svg(project), part) == (0, 0), part
    assert P.describe()["refused_by_role"]["legend-entry"] == ["dx_mm", "dy_mm"]


def test_a_gid_names_a_part_but_keeps_what_its_role_refuses(project):
    """A part named by the author's gid had the role "author", which refuses nothing: a
    tick label with a gid took an offset, and a 3D axis with one listed tick marks as applied
    that left panel.svg unchanged."""
    _add_to_producer(project, 'ax.get_xticklabels()[1].set_gid("mid")')
    assert build(project).ok
    svg0, mid = _panel_svg(project), _manifest(project)["parts"]["mid"]
    assert (mid["role"], mid["stability"]) == ("tick", "author") and "dx_mm" not in mid["props"]
    assert "mid" not in _manifest(project)["parts"]["main.xtick.*"]["members"], "the gid keeps it out of the group"
    assert "copies its transform to new ticks" in _refusal(project, "mid", {"dx_mm": 3})
    (project.panel_dir("fig-1", "a") / "style.json").write_text(
        json.dumps({"schema": 1, "parts": {"mid": {"dx_mm": 3}}}))
    assert build(project).ok
    assert [i["prop"] for i in _manifest(project)["style"]["invalid"]] == ["dx_mm"]
    assert _moved_mm(svg0, _panel_svg(project), "mid") == (0, 0)

    _replace_in_producer(project, '    ax.get_xticklabels()[1].set_gid("mid")\n',
                         '    ax.patch.set_gid("plot-area")\n'
                         '    ax.get_legend().set_frame_on(True); ax.get_legend().get_frame().set_gid("key-box")\n')
    assert build(project).ok
    root, parts = _panel_svg(project), _manifest(project)["parts"]
    # a byte 0.2.2 did not write (its role was "author"), hence build.RENDER
    for gid, role in (("plot-area", "background"), ("key-box", "legend-frame")):
        assert parts[gid]["role"] == role and _by_id(root, gid).get("data-idofig-role") == role, gid

    _three_d(project, extra="ax.zaxis.set_gid('depth')")
    assert build(project).ok
    drawn, depth = read(project.panel_dir("fig-1", "a") / "panel.svg"), _manifest(project)["parts"]["depth"]
    assert depth["role"] == "axis3d" and depth["props"] == {"visible": True}
    (project.panel_dir("fig-1", "a") / "style.json").write_text(
        json.dumps({"schema": 1, "parts": {"depth": {"ticklength": 8, "tickdir": "in"}}}))
    assert build(project).ok
    assert sorted(i["prop"] for i in _manifest(project)["style"]["invalid"]) == ["tickdir", "ticklength"]
    assert _manifest(project)["style"]["applied"] == ["depth"]
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == drawn


# ----------------------------------------------------------------------------- axis ticks (I4)


def _tick_mark(root, axis_id):
    """(signed length, stroke width) of an axis' first tick mark, as the SVG draws it: the
    marker path is ``M 0 0 L 0 <length>``, positive when the tick points out of the axes."""
    path = next(el for el in _by_id(root, axis_id).iter(f"{SVG}path") if el.get("d", "").startswith("M 0 0"))
    length = float(path.get("d").split()[-1])
    width = float(path.get("style").split("stroke-width:")[1].split(";")[0])
    return length, width


def test_axis_tick_direction_length_and_width(project):
    build(project)
    x0, y0 = _tick_mark(_panel_svg(project), "main.xaxis"), _tick_mark(_panel_svg(project), "main.yaxis")
    # an unstyled axis reports the marks it drew, so an editor can show them
    assert _manifest(project)["parts"]["main.xaxis"]["props"] == {"visible": True, "tickdir": "out",
                                                                  "ticklength": x0[0], "tickwidth": x0[1]}
    _style(project, "main.xaxis", {"tickdir": "in", "ticklength": 4, "tickwidth": 1.2})
    assert build(project).ok
    root = _panel_svg(project)
    assert _tick_mark(root, "main.xaxis") == (-4, 1.2)  # inward: the mark points up into the axes
    assert _tick_mark(root, "main.yaxis") == y0
    xa = _manifest(project)["parts"]["main.xaxis"]
    assert xa["props"] == {"visible": True, "tickdir": "in", "ticklength": 4, "tickwidth": 1.2}
    assert xa["base"] == {"tickdir": "out", "ticklength": x0[0], "tickwidth": x0[1]}  # what the SVG drew before


def test_tickdir_turns_the_minor_tick_marks_too(project):
    """SPEC: `tickdir` sets major and minor tick marks; conftest's panel draws no minor ones."""
    def lengths(root):  # as _tick_mark reads them: positive out of the axes
        return sorted({float(el.get("d").split()[-1]) for el in _by_id(root, "main.xaxis").iter(f"{SVG}path")
                       if el.get("d", "").startswith("M 0 0")})

    _replace_in_producer(project, "    ax.legend()\n", "    ax.legend()\n    ax.set_xticks([0.5, 1.5], minor=True)\n")
    assert build(project).ok
    out = lengths(_panel_svg(project))
    assert len(out) == 2 and all(v > 0 for v in out), out  # major and minor, both out
    _style(project, "main.xaxis", {"tickdir": "in"})
    assert build(project).ok
    assert lengths(_panel_svg(project)) == sorted(-v for v in out), "major and minor both turn in"


# ----------------------------------------------------------------------------- backend (I5)


def _backend_after_panels(project, env):
    code = "import idofig as idf, matplotlib; idf.panels('a', figure='fig-1'); print(matplotlib.get_backend())"
    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"} | env
    out = subprocess.run([sys.executable, "-c", code], cwd=project.root, capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_panels_choose_agg_when_no_backend_is_chosen(project):
    assert _backend_after_panels(project, {}).lower() == "agg"  # "auto": the macosx canvas on a Mac


def test_a_python_i_session_keeps_the_backend_it_has_not_chosen_yet(project):
    """`python -i make.py` (or `%run make.py` in an IPython terminal) has chosen no backend
    when the script calls idofig.panels(), and idofig chose Agg for it: at the prompt,
    `plt.show()` warned that Agg is non-interactive and showed nothing. A session is never
    switched (each save draws on an Agg canvas of its own); a plain run is, but only once
    panels() has found its figure, so a call that fails switches nothing."""
    code = ("import matplotlib, matplotlib.cbook as cbook, idofig as idf\n"
            "cbook._get_running_interactive_framework = lambda: 'headless'  # no window, on any machine\n"
            "used = []\n"
            "matplotlib.use = lambda backend, **kw: used.append(backend)\n"
            "try:\n"
            "    idf.panels('a', figure='no-such-figure')\n"
            "except Exception as e:\n"
            "    print(type(e).__name__, len(used))\n"
            "idf.panels('a', figure='fig-1')\n"
            "print(*used)\n")
    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"}
    runs = {}
    for flags in ((), ("-i",)):
        out = subprocess.run([sys.executable, *flags, "-c", code], cwd=project.root, capture_output=True, text=True,
                             env=env, stdin=subprocess.DEVNULL)
        assert out.returncode == 0, out.stderr
        runs[flags] = out.stdout.split()
    assert runs[()] == ["SpecError", "0", "Agg"]  # no figures/no-such-figure/figure.json
    assert runs[("-i",)] == ["SpecError", "0"]


# A session's backend whose canvas lays panels out on a Retina display: its dpi doubled (72 → 144),
# as the macosx, Qt and browser (nbAgg, ipympl) canvases do, and the figure sized to its window in
# whole pixels, as macosx's canvas does when it is made (`FigureCanvasMac.resize`).
RETINA_LIKE = """
from matplotlib.backend_bases import FigureManagerBase as FigureManager  # noqa: F401
from matplotlib.backends.backend_agg import FigureCanvasAgg


class FigureCanvas(FigureCanvasAgg):
    def __init__(self, figure=None):
        super().__init__(figure)
        self._set_device_pixel_ratio(2)
        w, h = self.get_width_height()  # whole logical pixels, at the figure's own 72 dpi
        self.figure.set_size_inches(w / 72, h / 72, forward=False)
"""


@pytest.mark.parametrize("backend", ["module://retina_like", "svg"])
def test_a_session_keeps_its_backend_and_saves_as_build_does(project, tmp_path, backend):
    """idofig.panels() switched a session's backend to Agg unless its canvas was exactly Agg's:
    under %matplotlib widget, notebook or qt, no later plot of the kernel showed, and
    matplotlib 3.8 closed the author's open figures. The backend stays; each save draws on an
    Agg canvas at the figure's own dpi and its place size, so the panel is the one `build`
    writes — a Retina canvas or an svg one (which cannot measure a part) included — and the
    session gets its canvas, dpi and size back. A canvas that sizes the figure to whole pixels
    (macosx's, when it is made) had an 88 mm panel saved 249 pt wide, not 249.449 (compose
    warned; `check` called it not reproducible). A dpi the script set is its own: halved as if
    the canvas had doubled it, a
    `set_dpi(300)` panel with a table was laid out at 150 dpi. The figure's own dpi
    (`_original_dpi`, which the canvas doubles) stays 72: under matplotlib < 3.11 the Agg
    canvas reset it to 144, the doubling was not undone, and the session kept 144 as its own.
    (What a script measures before it saves, `clabel` say, a session measures on its own
    canvas: SPEC.md, Determinism.)"""
    _replace_in_producer(project, "import idofig as idf\n",
                         "import idofig as idf\nimport matplotlib, matplotlib.pyplot as plt\nmine = plt.figure()\n")
    _replace_in_producer(project, "idf.save(p)\n",
                         "idf.save(p)\nprint(matplotlib.get_backend(), plt.fignum_exists(mine.number),\n"
                         "      *(f'{type(f.canvas).__name__}@{f.dpi:g}/{f._original_dpi:g}/{f.get_figwidth() * 72:g}'\n"
                         "        for f in p.values()))\n")
    # laid out at 144 dpi, these rotated labels move the axes (conftest's short ones do not)
    _add_to_producer(project, 'ax.set_xticks(range(3), ["a long label one", "second longish", "third"])\n'
                              'ax.tick_params(axis="x", rotation=35)\n'
                              'if pid == "b":  # laid out at 150 dpi, a table is set in other sizes\n'
                              '    f.set_dpi(300)\n'
                              '    ax.table(cellText=[["1", "2"], ["3", "4"]], loc="bottom", bbox=[0, -0.6, 1, 0.3])')
    assert build(project).ok
    d = project.figure_dir("fig-1")
    built = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    (tmp_path / "retina_like.py").write_text(RETINA_LIKE)
    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"} | {
        "MPLBACKEND": backend, "PYTHONPATH": os.pathsep.join(filter(None, [str(tmp_path), os.environ.get("PYTHONPATH")]))}
    out = subprocess.run([sys.executable, "figures/fig-1/make.py"], cwd=project.root, capture_output=True, text=True,
                         env=env)
    assert out.returncode == 0, out.stderr
    canvas, width = ("FigureCanvas@144", "249") if backend == "module://retina_like" else ("FigureCanvasSVG@72", "249.449")
    assert out.stdout.split() == [backend, "True", f"{canvas}/72/{width}", f"{canvas.split('@')[0]}@300/72/{width}"], \
        "the session's backend, the author's figure, and each panel's canvas, dpi and size stay"
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == built


@pytest.mark.parametrize("ipython", [False, True])
def test_a_script_run_draws_on_agg_whatever_a_matplotlibrc_names(project, tmp_path, monkeypatch, ipython):
    """A `backend:` line in a matplotlibrc (`backend: macosx` on a Mac) counted as chosen, and a
    plain `python make.py` kept that canvas: what the script measured before saving was
    measured on it, and a panel whose contour labels `clabel` placed differed from `build`'s
    (here a canvas at device pixel ratio 2, as a Retina display gives macosx). A library that
    imports IPython (seaborn does, through ipywidgets, wherever that is installed) made such a
    run a session, which keeps its canvas: IPython is a session only while its shell runs."""
    (tmp_path / "retina_like.py").write_text(RETINA_LIKE)
    (tmp_path / "IPython").mkdir()
    (tmp_path / "IPython" / "__init__.py").write_text("version_info = (9, 0)  # matplotlib reads it\n"
                                                    "def get_ipython():\n    return None  # imported; no shell runs\n")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(tmp_path), os.environ.get("PYTHONPATH")])))
    if ipython:
        _replace_in_producer(project, "import idofig as idf\n", "import IPython  # as seaborn does\nimport idofig as idf\n")
    _add_to_producer(project, 'import numpy as np\n'
                              'c = f.add_axes([0.55, 0.55, 0.4, 0.4]); idf.name(c, "c")\n'
                              'c.clabel(c.contour(np.add.outer(np.linspace(0, 3, 20) ** 2, np.linspace(0, 2, 30))),'
                              ' fontsize=5)')
    assert build(project).ok
    d = project.figure_dir("fig-1")
    built = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    (tmp_path / "rc").mkdir()
    (tmp_path / "rc" / "matplotlibrc").write_text("backend: module://retina_like\n")
    env = {"MATPLOTLIBRC": str(tmp_path / "rc")}
    assert _backend_after_panels(project, env).lower() == "agg"
    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"} | env
    out = subprocess.run([sys.executable, "figures/fig-1/make.py"], cwd=project.root, capture_output=True, text=True,
                         env=env)
    assert out.returncode == 0, out.stderr
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == built


# ----------------------------------------------------------------------------- checks (I6)


def test_a_panel_past_the_figures_edge_is_reported_with_the_overhang(project):
    S.update_figure(project.figure_json("fig-1"), [{"op": "place", "panel": "b", "w": 96},
                                                   {"op": "height", "mm": 50}])
    warnings = compose(project, "fig-1", write=False).warnings
    assert "panel 'b' extends 5 mm past the figure's right edge" in warnings  # 92 + 96 − 183
    assert "panel 'a' extends 10 mm past the figure's bottom edge" in warnings  # 60 − 50
    assert "panel 'a' extends 10 mm past the figure's bottom edge" in figure_status(project, "fig-1").warnings
    S.update_figure(project.figure_json("fig-1"), [{"op": "place", "panel": "a", "x": -2, "y": -3}])
    warnings = compose(project, "fig-1", write=False).warnings
    assert "panel 'a' extends 2 mm past the figure's left edge" in warnings
    assert "panel 'a' extends 3 mm past the figure's top edge" in warnings


def test_a_letter_past_the_figures_edge_is_reported_with_the_overhang(project):
    """A letter moved off the figure is missing from print, and a canvas cannot show it to be
    dragged back: [-500, 0] was drawn at x=-1417 pt and nothing said so."""
    assert not any("letter" in w for w in compose(project, "fig-1", write=False).warnings)
    S.update_figure(project.figure_json("fig-1"), [{"op": "letter", "panel": "a", "offset_mm": [-5, 0]},
                                                   {"op": "letters", "patch": {"offset_mm": [0, -1.5]}}])
    warnings = [w for w in compose(project, "fig-1", write=False).warnings if "letter" in w]
    assert sorted(warnings) == ["the letter of panel 'a' extends 1.5 mm past the figure's top edge",
                                "the letter of panel 'a' extends 5 mm past the figure's left edge",
                                "the letter of panel 'b' extends 1.5 mm past the figure's top edge"]


def test_ink_outside_a_panels_box_is_reported_with_its_overhang_but_clipped_data_is_not(project):
    # Each text's outer edge is placed a known distance past one edge of the panel; its other
    # edge is inside, so the overhang is that distance whatever the text's size. Above and
    # below are the usual cases (a title, rotated tick labels), and each side is its own term.
    _add_to_producer(project, 'f.text(-0.01, 0.5, "left", ha="left", va="center")\n'
                              'f.text(-0.1 / 88, 0.3, "near", ha="left", va="center")\n'
                              'f.text(0.5, 1.02, "top", va="top")\n'
                              'f.text(0.3, -0.03, "bottom", va="bottom")\n'
                              'ax.plot([-10, 10], [0, 5], label="long")\n'
                              'ax.set_xlim(-0.5, 2.5)')
    assert build(project).ok
    ink = _ink(project)
    assert "fig-1/a: text.left is 0.88 mm outside its panel's box" in ink  # 1 % of the 88 mm panel
    assert "fig-1/a: text.top is 1.2 mm outside its panel's box" in ink  # 2 % of the 60 mm panel
    assert "fig-1/a: text.bottom is 1.8 mm outside its panel's box" in ink  # 3 % of it
    assert not any("text.near" in w for w in ink), "0.1 mm is within the 0.2 mm tolerance"
    # the long line runs far past the panel, but the axes clip it: not a finding
    assert not any("series" in w for w in ink), ink
    assert check(project, run=False).ok, "advisory: nothing here blocks"


def test_a_legend_or_an_axes_outside_its_panel_is_reported(project):
    """SPEC: a named text, legend or axes part is checked. The legend is moved until its frame,
    and not its entries, crosses the panel's edge: its entries count as its group, so moved far
    out they were a `main.legend` finding of their own, and a check that skipped legends passed."""
    _add_to_producer(project, 'side = f.add_axes([0.9, 0.5, 0.2, 0.3]); idf.name(side, "side")')
    assert build(project).ok
    man = _manifest(project)
    right, entries = man["parts"]["main.legend"]["bbox"][2], max(
        p["bbox"][2] for p in man["parts"].values() if p["role"] == "legend-entry")
    assert right - entries > 0.8 * PT, "moved 0.5 mm past the edge, the entries stay 0.3 mm or more inside it"
    _style(project, "main.legend", {"dx_mm": (man["size"]["w_pt"] - right) / PT + 0.5})  # 0.5 mm past the edge
    assert build(project).ok
    ink = _ink(project)
    assert "fig-1/a: side is 8.8 mm outside its panel's box" in ink  # 10 % of the panel's 88 mm
    assert [w for w in ink if "legend" in w] == ["fig-1/a: main.legend is 0.5 mm outside its panel's box"], ink


def test_a_text_larger_than_the_journal_states_is_one_finding(project):
    _style(project, "main.title", {"fontsize": 9})
    _style(project, "main.xtick.*", {"fontsize": 8})
    assert build(project).ok
    large = [w for w in _findings(project)[1] if "states at most" in w]
    assert sorted(large) == ["fig-1/a: main.title is 9 pt; Nature states at most 7 pt",
                             "fig-1/a: main.xtick.* is 8 pt (3 parts); Nature states at most 7 pt"]


def test_a_math_text_is_boxed_as_the_svg_draws_it(project):
    """Measured on Agg at 72 dpi, a text's box was rounded out to whole points and, under
    matplotlib < 3.11, a math text's padded a point a side: on axes placed by hand, a
    `log$_{10}$` xlabel whose ink ended 1.2 mm inside its panel was "0.71 mm outside its panel's
    box" (15 such findings on one project, under matplotlib 3.10). It is measured with the text
    metrics the SVG is laid out with. The layout is the reviewer's: the axes end 3 mm above the
    panel's bottom edge."""
    (project.root / "figures/fig-1/make.py").write_text(
        "import idofig as idf\n"
        "p = idf.panels('a', 'b', layout=None)\n"
        "for f in p.values():\n"
        "    ax = idf.axes_mm(f, 12, 9, 70, 48)\n"
        "    idf.name(ax, 'main')\n"
        "    ax.plot([0, 1, 2], [1, 3, 2])\n"
        "    ax.set_xlabel(r'log$_{10}$(HI + 1)')\n"
        "    ax.set_ylabel(r'Power ($\\mu$V$^2$)')\n"
        "idf.save(p)\n", encoding="utf-8")
    assert build(project).ok
    assert _manifest(project)["parts"]["main.xlabel"]["bbox"][3] < 60 * PT
    assert _ink(project) == []


def test_clipped_text_is_measured_as_far_as_it_is_seen(project):
    """matplotlib measures a text whole, clipped or not: a point label outside a zoomed view
    (`clip_on=True`), which nobody sees, was reported 109 mm outside its panel."""
    _add_to_producer(project, 'ax.text(-3, 1, "gone", clip_on=True)\n'
                              'ax.text(2.3, 1, "cut in half by the axes", clip_on=True)\n'
                              'ax.text(2.3, 0.5, "drawn whole", clip_on=False)')
    assert build(project).ok
    m = _manifest(project)
    parts, right = m["parts"], m["axes"]["main"]["bbox"][2]
    assert parts["main.text.gone"]["bbox"] is None
    cut, whole = parts["main.text.cut-in-half-by-the-axes"]["bbox"], parts["main.text.drawn-whole"]["bbox"]
    assert cut[2] == pytest.approx(right, abs=1e-3) and cut[0] == pytest.approx(whole[0], abs=1e-3)
    assert whole[2] > right + 5 * PT, "an unclipped text keeps its whole box"
    assert not any("gone" in w or "cut-in-half" in w for w in _ink(project)), _ink(project)


def test_an_annotation_matplotlib_skips_has_no_box(project):
    """An annotation whose point is outside its axes is not drawn at all (annotation_clip),
    and matplotlib measures it as a 1 pt box: the manifest put it at the panel's corner."""
    _add_to_producer(project, 'ax.annotate("far", xy=(30, 1), xytext=(40, 1.5), arrowprops={"arrowstyle": "->"})\n'
                              'ax.annotate("near", xy=(1, 1), xytext=(0.5, 1.5), arrowprops={"arrowstyle": "->"})')
    assert build(project).ok
    parts, ids = _manifest(project)["parts"], {el.get("id") for el in _panel_svg(project).iter()}
    assert parts["main.text.far"]["bbox"] is None and "main.text.far" not in ids
    assert parts["main.text.near"]["bbox"] is not None and "main.text.near" in ids


def test_boxes_an_older_idofig_measured_are_not_checked_for_ink(project):
    """0.2.x measured parts it never drew, at matplotlib's defaults, and a set_dpi(300) panel
    at 300/72 its size: 18 false findings on one project until every panel was rebuilt. Its
    manifests carry no render number; the panel is stale, which is its own finding."""
    assert build(project).ok
    path = project.panel_dir("fig-1", "a") / "manifest.json"
    manifest = json.loads(read(path))
    manifest["parts"]["main.xlabel"]["bbox"] = [-40.0, 10.0, -20.0, 20.0]  # 7 mm left of the panel
    path.write_text(json.dumps(manifest))
    assert _ink(project) == ["fig-1/a: main.xlabel is 14.11 mm outside its panel's box"]
    del manifest["render"]
    path.write_text(json.dumps(manifest))
    assert _ink(project) == []


def test_an_older_manifest_gets_only_the_stroke_checks_that_idofig_made(project):
    """0.2.x wrote "#000000" for an edge drawn in no colour: a bar's 0.3 pt edge, which is not
    drawn, became a finding under SUNA style's 0.5 pt with the patch and collection check, and
    stayed one until each panel was rebuilt. Lines and spines are checked as 0.2.x checked them."""
    _style(project, "main.series.control", {"linewidth": 0.3})  # no edge colour: nothing drawn
    _style(project, "main.series.trend", {"linewidth": 0.3})
    assert build(project).ok

    def thin():
        return [w for w in _findings(project, journal="suna", width={"mm": 178})[1]
                if w.startswith("fig-1/a: ") and " pt wide" in w]

    trend = ["fig-1/a: main.series.trend is 0.3 pt wide; SUNA style states at least 0.5 pt"]
    assert thin() == trend
    path = project.panel_dir("fig-1", "a") / "manifest.json"
    manifest = json.loads(read(path))
    del manifest["render"]  # what 0.2.2 wrote: no render number, and black for no colour
    for name in manifest["parts"]["main.series.control"]["members"]:
        manifest["parts"][name]["props"]["edgecolor"] = "#000000"
    path.write_text(json.dumps(manifest))
    assert thin() == trend


def _as_idofig_022(project):
    """The idofig the producer's run uses, which the lock does not track (an interpreter named in
    `run`): here an environment variable, under which the run does what 0.2.2 did — it refuses a
    figure.json whose schema is not 2 (0.2.x's `idofig.panels()` reads it) and writes other bytes."""
    _replace_in_producer(project, "p = idf.panels(", (
        "import os\n"
        "schema = json.loads(Path('figures/fig-1/figure.json').read_text())['schema']\n"
        "if os.environ.get('AS_IDOFIG_022') and schema != 2:\n"
        "    raise SystemExit(f'figures/fig-1/figure.json is not valid:\\n- schema must be 2 (found {schema})')\n"
        "p = idf.panels("))
    _replace_in_producer(project, "idf.save(p)", (
        "idf.save(p)\n"
        "import pathlib\n"
        "out = pathlib.Path(os.environ['IDOFIG_OUTPUT_DIR'])\n"
        "for pid in p if os.environ.get('AS_IDOFIG_022') else []:  # no render number, other bytes\n"
        "    m = json.loads((out / pid / 'manifest.json').read_text()); del m['render']\n"
        "    (out / pid / 'manifest.json').write_text(json.dumps(m))\n"
        "    (out / pid / 'panel.svg').write_text((out / pid / 'panel.svg').read_text() + '<!-- 0.2.2 -->')\n"
        "    run = json.loads((out / '_run.json').read_text()); run['versions']['idofig'] = '0.2.2'\n"
        "    (out / '_run.json').write_text(json.dumps(run))"))


def test_a_panel_the_producers_own_idofig_drew_warns_until_it_is_upgraded_and_redrawn(project, monkeypatch):
    """A producer may run an interpreter with an idofig of its own. Recorded under the
    builder's render number, its 0.2.2 panels showed fresh; recorded as drawn by 0.2.2 and
    stale for it, they were stale after every build (no rebuild can change what that idofig
    draws), `check` failed for good, and SUNA's automatic builds ran them again and again.
    Once that idofig is upgraded, the lock still says 0.2.2 drew the panel: `check`, which
    runs the producer, names the forced build that redraws it, as the warning did."""
    _as_idofig_022(project)
    monkeypatch.setenv("AS_IDOFIG_022", "1")
    assert build(project).ok
    lock = json.loads(read(lock_path(project, "fig-1")))
    assert {(e["render"], e["builder_render"]) for e in lock["panels"].values()} == {(1, RENDER)}
    step = "upgrade idofig where the producer runs, then `idofig build --force fig-1`"
    for _ in range(2):
        for p in figure_status(project, "fig-1").panels:
            assert p.state == "fresh", p
            assert any(w.startswith("drawn by idofig 0.2.2, the one its producer's run uses")
                       and w.endswith(step) for w in p.warnings), p.warnings
        again = build(project)
        assert again.ok and again.runs == [], "nothing to rebuild: a rebuild by that idofig draws the same"
    report = check(project, run=False)
    assert report.ok and sum("drawn by idofig 0.2.2" in w for w in report.warnings) == 2, report.to_json()

    monkeypatch.delenv("AS_IDOFIG_022")  # the producer's idofig is upgraded
    assert all(p.state == "fresh" for p in figure_status(project, "fig-1").panels), "the lock cannot see it"
    errors = check(project).errors
    assert sorted(errors) == [f"fig-1/{pid}: drawn by idofig 0.2.2 (render 1); its producer now draws with render "
                              f"{RENDER} — `idofig build --force fig-1` redraws it" for pid in ("a", "b")], errors
    assert build(project, force=True).ok
    assert all(p.state == "fresh" and not p.warnings for p in figure_status(project, "fig-1").panels)
    assert check(project).ok


def test_a_producer_on_idofig_0_2_cannot_read_a_schema_3_figure_and_status_says_so_first(project, monkeypatch,
                                                                                          capsys):
    """0.2.x reads figure.json in the producer too, and refuses a 3. Once a letter was moved
    (schema 3), every rebuild of a producer whose run uses 0.2.2 failed with a bare "schema must
    be 2", while status called its panels fresh and said only that they draw differently. The
    `idofig status` command printed no panel's warnings at all: it showed two green panels."""
    from idofig import cli

    _as_idofig_022(project)
    monkeypatch.setenv("AS_IDOFIG_022", "1")
    assert build(project).ok
    S.update_figure(project.figure_json("fig-1"), [{"op": "letter", "panel": "a", "offset_mm": [1, 0]}])
    cause = ("drawn by idofig 0.2.2, the one its producer's run uses, which cannot read this figure.json (schema 3: "
             "a letter offset or colour), so its next build fails: upgrade idofig where the producer runs, then "
             "`idofig build --force fig-1`")
    for p in figure_status(project, "fig-1").panels:
        assert p.state == "fresh" and cause in p.warnings, p
    monkeypatch.chdir(project.root)
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    assert capsys.readouterr().out.count(f"      ! {cause}\n") == 2
    assert build(project).ok, "composing the moved letter runs no producer"
    _style(project, "main.xlabel", {"fontsize": 8})
    failed = build(project)
    assert not failed.ok and "schema must be 2 (found 3)" in failed.runs[0].error, failed.to_json()

    monkeypatch.delenv("AS_IDOFIG_022")  # the producer's idofig is upgraded
    assert build(project, force=True).ok
    assert all(p.state == "fresh" and not p.warnings for p in figure_status(project, "fig-1").panels)


def test_parts_that_are_never_drawn_have_no_box_and_no_ink_finding(project):
    """An axes turned off, a hidden axes, a hidden legend: matplotlib still measures their
    labels, tick labels and entries at a default place, and each was flagged outside."""
    _add_to_producer(project, 'off = f.add_axes([0.6, 0.6, 0.3, 0.3]); idf.name(off, "off")\n'
                              'off.plot([0, 1], [0, 1]); off.set_xlabel("offlabel"); off.axis("off")\n'
                              'hid = f.add_axes([0.1, 0.6, 0.3, 0.3]); idf.name(hid, "hid")\n'
                              'hid.plot([0, 1], [0, 1]); hid.set_ylabel("hidlabel"); hid.set_visible(False)\n'
                              'img = f.add_axes([0.1, 0.1, 0.2, 0.2]); idf.name(img, "img")\n'
                              'img.imshow([[0, 1], [1, 0]]); img.imshow([[1, 0], [0, 1]], alpha=0.5)')
    _style(project, "main.legend", {"visible": False})
    assert build(project).ok
    assert _ink(project) == []
    parts, root = _manifest(project)["parts"], _panel_svg(project)
    ids = {el.get("id") for el in root.iter()}
    never = ["off.xlabel", "off.xtick.*", "off.spine.left", "hid.ylabel", "hid.xtick.*", "main.legend",
             "main.legend.control"]
    for name in never:
        assert parts[name]["bbox"] is None, name
        assert parts[name].get("group") or name not in ids, f"{name} is not in the SVG"
    assert parts["off.line0"]["bbox"] is not None, "axis('off') hides the axis, not the data"
    # two images in one axes are composited into one, never asked to draw: drawn all the same
    assert parts["img.image0"]["bbox"] and parts["img.image1"]["bbox"]
    assert parts["main.xlabel"]["bbox"] is not None


def test_letter_size_is_checked_against_the_journals_floor_only(project):
    doc = S.load_figure(project.figure_json("fig-1"))
    finding = "fig-1: panel letters are 4 pt; Nature requires at least 5 pt"
    assert finding in compliance(project, "fig-1", {**doc, "letters": {"size_pt": 4}})[1]
    # above Nature's 7 pt text ceiling: labels are set larger than text, and no preset
    # states a label size, so there is nothing to compare it with
    assert not any("letters" in w for w in compliance(project, "fig-1", {**doc, "letters": {"size_pt": 14}})[1])
    # a journal that states no floor states nothing about letters either
    assert not any("letters" in w for w in compliance(project, "fig-1", {**doc, "journal": "jneurosci",
                                                                           "width": {"mm": 170},
                                                                           "letters": {"size_pt": 4}})[1])


# ----------------------------------------------------------------------------- names (I7, I8)


def test_a_rasterized_part_keeps_its_name_in_the_svg(project):
    _add_to_producer(project, 'ax.scatter([0, 1, 2], [0.5, 1, 1.5], label="dots", rasterized=True)\n'
                              'ax.scatter([0, 1, 2], [1.5, 1, 0.5], label="rings", rasterized=True)\n'
                              'ax.scatter([0, 1, 2], [1, 1, 1], label="hidden", rasterized=True)')
    _style(project, "main.series.hidden", {"visible": False})
    assert build(project).ok
    root = _panel_svg(project)
    for part in ("main.series.dots", "main.series.rings"):
        images = list(_by_id(root, part).iter(f"{SVG}image"))
        assert len(images) == 1, f"{part} must wrap its own image"
    # a part that is not drawn is not in the SVG (it was, as an empty group)
    assert "main.series.hidden" not in {el.get("id") for el in root.iter()}
    assert _manifest(project)["parts"]["main.series.hidden"]["bbox"] is None


def test_unnamed_rasterized_parts_still_share_one_image(project):
    """An image per rasterized part made 150 per-trial traces 2.5 times larger (1.7 → 4.4 MB)
    and 500 of them six times; positional names are not worth that."""
    _add_to_producer(project, 'for i in range(40):\n'
                              '    ax.plot([0, 1, 2], [0.02 * i, 1, 1.5], lw=0.3, color="0.5", rasterized=True)\n'
                              'ax.scatter([0, 1, 2], [0.5, 1, 1.5], label="dots", rasterized=True)  # zorder 1: first\n'
                              # drawn after the traces, while their image is still pending: it must
                              # not land in this part's group (unflushed, the save failed outright)
                              'ax.plot([0, 1, 2], [0.2, 1.1, 1.6], label="mean", rasterized=True)')
    assert build(project).ok
    root, parts = _panel_svg(project), _manifest(project)["parts"]
    assert len(list(root.iter(f"{SVG}image"))) == 3  # the 40 traces merged, the named dots and mean on their own
    for part in ("main.series.dots", "main.series.mean"):
        assert len(list(_by_id(root, part).iter(f"{SVG}image"))) == 1, part
    traces = [p for n, p in parts.items() if n.startswith("main.line") and p["stability"] == "positional"]
    assert len(traces) == 40 and all(p["bbox"] for p in traces), "drawn, so measured, though not in the SVG by name"


def _three_d(project, extra=""):
    path = project.root / "figures/fig-1/make.py"
    path.write_text(
        "import idofig as idf\n"
        "p = idf.panels('a', 'b')\n"
        "for f in p.values():\n"
        "    ax = f.add_subplot(projection='3d'); idf.name(ax, 'main')\n"
        "    ax.plot([0, 1, 2], [0, 1, 4], [0, 2, 1])\n"
        "    ax.set_xlabel('x'); ax.set_ylabel('y'); ax.set_zlabel('depth'); ax.set_title('T')\n"
        f"    {extra}\n"
        "idf.save(p)\n", encoding="utf-8")


def test_a_3d_axes_names_its_z_axis_like_the_others(project):
    _three_d(project)
    assert build(project).ok
    m = _manifest(project)
    for name in ("main.zlabel", "main.zaxis", "main.ztick.*"):
        assert name in m["parts"], name
    assert m["parts"]["main.zlabel"]["props"]["text"] == "depth"
    assert not [w for w in m["warnings"] if "is taken" in w]
    # an Axis3D opens its pane, grid and axis groups with one gid: only the axis keeps it
    assert _duplicate_ids(_panel_svg(project)) == []


def test_a_3d_axes_labels_move_exactly_and_its_tick_marks_are_refused(project):
    """A 3D axis resets its label's transform at every draw: a move was listed as applied
    and drew nothing. Its tick marks ignore tick_params: refused, not reported applied."""
    _three_d(project)
    assert build(project).ok
    svg0 = _panel_svg(project)
    _style(project, "main.zlabel", {"dx_mm": 2, "dy_mm": 1})
    _style(project, "main.xlabel", {"dx_mm": -1})
    assert build(project).ok
    svg1, m = _panel_svg(project), _manifest(project)
    drawn = read(project.panel_dir("fig-1", "a") / "panel.svg")
    assert _moved_mm(svg0, svg1, "main.zlabel") == (pytest.approx(2, abs=1e-3), pytest.approx(1, abs=1e-3))
    assert _moved_mm(svg0, svg1, "main.xlabel") == (pytest.approx(-1, abs=1e-3), 0)
    assert _moved_mm(svg0, svg1, "main.ylabel") == (0, 0) and _moved_mm(svg0, svg1, "main.title") == (0, 0)

    assert m["parts"]["main.xaxis"]["role"] == "axis3d"
    assert m["parts"]["main.xaxis"]["props"] == {"visible": True}  # no tick values it does not draw by
    assert P.describe()["refused_by_role"]["axis3d"] == ["tickdir", "ticklength", "tickwidth"]
    _style(project, "main.xaxis", {"ticklength": 8})
    assert build(project).ok
    assert [i["prop"] for i in _manifest(project)["style"]["invalid"]] == ["ticklength"]
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == drawn


def test_a_3d_axes_text_is_measured_where_it_is_drawn(project):
    """A 3D text (`ax.text(x, y, z, …)`) is at its projection only while it draws: measured
    after, at its data x and y through the 2D transform, "peak" drawn inside its panel was
    boxed 2314 mm outside, and the ink check reported it. Its box is the text's own, as large
    as the same words drawn flat (`text2D`), and starts where the SVG draws it — not, say, the
    whole axes, which holds its anchor too."""
    _three_d(project, extra="ax.text(1, 2, 1, 'peak'); ax.text(0.5, 1, 0.5, 'slope', zdir='x'); "
                            "ax.text2D(0.1, 0.9, 'peak', transform=ax.transAxes, gid='flat')")
    assert build(project).ok
    parts, root = _manifest(project)["parts"], _panel_svg(project)
    anchors = {}
    for name in ("main.text.peak", "main.text.slope"):
        x0, y0, x1, y1 = parts[name]["bbox"]
        # where the SVG anchors it (its left end, on its baseline): x, y, or a turned text's translate
        text = next(_by_id(root, name).iter(f"{SVG}text"))
        at = re.search(r"translate\(([-\d.]+)[ ,]+([-\d.]+)\)", text.get("transform") or "")
        x, y = anchors[name] = tuple(float(v) for v in (at.groups() if at else (text.get("x"), text.get("y"))))
        assert x0 - 0.01 <= x <= x1 + 0.01 and y0 - 0.01 <= y <= y1 + 0.01, (name, parts[name]["bbox"], x, y)
    assert _rotation(root, "main.text.slope") != 0, "the second one is turned along its direction"
    (x0, y0, x1, y1), (fx0, fy0, fx1, fy1) = parts["main.text.peak"]["bbox"], parts["flat"]["bbox"]
    assert (x1 - x0, y1 - y0) == (pytest.approx(fx1 - fx0, abs=0.01), pytest.approx(fy1 - fy0, abs=0.01))
    assert x0 == pytest.approx(anchors["main.text.peak"][0], abs=0.5)
    assert not any("main.text." in w for w in _ink(project)), _ink(project)  # (its x label does dip out)


def _rotation(root, ident):
    """The angle a part's text is drawn at, counter-clockwise: ``rotate(-a x y)`` in the SVG
    (``translate(x y) rotate(-a)`` for a text turned by other than 90° steps)."""
    text = next(_by_id(root, ident).iter(f"{SVG}text"))
    return -float(re.search(r"rotate\(([-\d.]+)", text.get("transform") or "rotate(0").group(1))


def test_a_3d_axis_label_takes_the_rotation_it_is_given(project):
    """A 3D axis turns a label longer than 4 characters to its axis' angle at every draw:
    `rotation: 0` on the "depth" z label was listed applied, drawn at 87.4°, and its base read
    0 — the value before the draw, not the one the script drew."""
    _three_d(project)
    assert build(project).ok
    turned = _rotation(_panel_svg(project), "main.zlabel")
    assert turned > 45 and _manifest(project)["parts"]["main.zlabel"]["props"]["rotation"] == pytest.approx(turned)
    _style(project, "main.zlabel", {"rotation": 0})
    _style(project, "main.xlabel", {"rotation": 30})  # "x": never turned by its axis
    assert build(project).ok
    root, m = _panel_svg(project), _manifest(project)
    assert _rotation(root, "main.zlabel") == 0 and _rotation(root, "main.xlabel") == 30
    assert m["style"]["invalid"] == [] and sorted(m["style"]["applied"]) == ["main.xlabel", "main.zlabel"]
    assert m["parts"]["main.zlabel"]["base"]["rotation"] == pytest.approx(turned, abs=1e-6)
    assert m["parts"]["main.xlabel"]["base"]["rotation"] == 0


# ----------------------------------------------------------------------------- the lock


def test_a_panel_drawn_by_an_older_idofig_is_stale_until_redrawn(project):
    """0.2.2 recorded no render number. Its colorbar panels drew differently from 0.3.0,
    yet showed fresh while `check` failed them as not reproducible. Which idofig drew a panel
    was read from its producer's `built_with`, which rebuilding one panel (`only`, the
    Inspector's Rebuild) rewrites: the other read "drawn by idofig 0.3.0; idofig 0.3.0 may draw
    it differently"."""
    assert build(project).ok
    path = lock_path(project, "fig-1")
    lock = json.loads(read(path))
    assert {(e["render"], e["builder_render"]) for e in lock["panels"].values()} == {(RENDER, RENDER)}
    assert {e["idofig"] for e in lock["panels"].values()} == {__version__}
    for entry in lock["panels"].values():  # what 0.2.2 wrote: neither number, no version
        del entry["render"], entry["builder_render"], entry["idofig"]
    lock["producers"]["make"]["built_with"]["idofig"] = "0.2.2"
    path.write_text(json.dumps(lock), encoding="utf-8")
    old = f"drawn by idofig 0.2.x; idofig {__version__} may draw it differently"
    st = figure_status(project, "fig-1")
    for p in st.panels:
        assert p.state == "stale" and old in p.reasons, p
    assert not check(project, run=False).ok
    assert build(project, only=["a"]).ok
    b = next(p for p in figure_status(project, "fig-1").panels if p.id == "b")
    assert b.state == "stale" and b.reasons == [old], b
    assert f"fig-1/b: stale ({old})" in check(project, run=False).errors
    assert build(project).ok
    assert all(p.state == "fresh" and not p.warnings for p in figure_status(project, "fig-1").panels)
    # a later release reading this idofig's lock: drawn and built under an older render, so
    # a rebuild may draw it differently, whatever drew it
    lock = json.loads(read(path))
    for entry in lock["panels"].values():
        entry["render"] = entry["builder_render"] = RENDER - 1
    path.write_text(json.dumps(lock), encoding="utf-8")
    assert all(p.state == "stale" for p in figure_status(project, "fig-1").panels)


# ----------------------------------------------------------------------------- after a port (I10–I14)
# Found porting a 21-panel figure pair to idofig (2026-09-24): collections without a box,
# one finding per tick label, strokes never checked, a black-only letter, a font check that
# skipped `sans-serif`. Expected positions come from the SVG (the marks matplotlib wrote),
# expected counts from the conftest data (three groups) or the SVG's ids.


def _numbers(d):
    return [float(v) for v in d.replace("M", " ").replace("L", " ").replace("z", " ").split()]


def _clip_rect(root):
    rect = next(root.iter(f"{SVG}clipPath")).find(f"{SVG}rect")
    x, y = float(rect.get("x")), float(rect.get("y"))
    return x, y, x + float(rect.get("width")), y + float(rect.get("height"))


def test_a_collection_has_the_box_of_the_marks_it_drew_clipped_to_its_axes(project):
    """matplotlib 3.11 measures a scatter and a LineCollection as an infinite box: 118 of 152
    collections in a ported project had none, so a canvas could not select a data series and
    an annotation anchored to one detached."""
    _add_to_producer(project, 'from matplotlib.collections import LineCollection\n'
                              'ax.scatter([0, 1, 2], [0.5, 1, 1.5], s=36, label="pts")  # 6 pt across\n'
                              'ax.add_collection(LineCollection([[(0.2, 0.3), (1.6, 1.7)]], label="links"))\n'
                              'ax.add_collection(LineCollection([[(-20, 0.4), (20, 0.4)]], label="long"))\n'
                              'ax.scatter([50], [1], label="away")\n'
                              'ax.set_xlim(-0.5, 2.5)')
    assert build(project).ok
    root, parts = _panel_svg(project), _manifest(project)["parts"]
    uses = list(_by_id(root, "main.series.pts").iter(f"{SVG}use"))
    xs, ys = [float(u.get("x")) for u in uses], [float(u.get("y")) for u in uses]
    assert len(uses) == 3
    assert parts["main.series.pts"]["bbox"] == pytest.approx([min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3],
                                                             abs=0.01)
    x0, y0, x1, y1 = _numbers(next(_by_id(root, "main.series.links").iter(f"{SVG}path")).get("d"))
    assert parts["main.series.links"]["bbox"] == pytest.approx([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
                                                               abs=0.01)
    left, _, right, _ = _clip_rect(root)
    box = parts["main.series.long"]["bbox"]
    assert (box[0], box[2]) == (pytest.approx(left, abs=0.01), pytest.approx(right, abs=0.01)), "clipped to its axes"
    assert parts["main.series.away"]["bbox"] is None, "outside the view: nobody sees it"
    # a part anchor on a series now resolves
    S.update_figure(project.figure_json("fig-1"), [{"op": "annotation.add", "annotation": {
        "id": "n1", "type": "text", "text": "here", "at": {"panel": "a", "part": "main.series.pts", "at": "top"}}}])
    assert compose(project, "fig-1", write=False).detached == []


def test_a_rasterized_collection_has_the_box_it_has_drawn_as_vectors(project):
    """A rasterized collection is drawn in the raster pass, at savefig.dpi (600), and its marks
    kept the size that draw gave them: measured at 72 dpi, a scatter's box was 22 pt (7.8 mm,
    3 pt × (600/72 − 1)) too large on every side, where a canvas outlined and hit-tested it,
    and an EllipseCollection's 36–57 pt. A quiver's box, which matplotlib gives tens of metres
    wide whether it is rasterized or not, is its arrows' too."""
    _add_to_producer(project, 'from matplotlib.collections import EllipseCollection, RegularPolyCollection\n'
                              'for name, kw in (("pts", {}), ("raster", {"rasterized": True}),\n'
                              '                 ("below", {"zorder": 0})):\n'
                              '    ax.scatter([0, 1, 2], [0.5, 1, 1.5], s=36, label=name, **kw)\n'
                              '    ax.add_collection(RegularPolyCollection(\n'
                              '        4, rotation=0.5, sizes=[200], offsets=[(1, 1)], offset_transform=ax.transData,\n'
                              '        label=f"square-{name}", **kw))\n'
                              '    ax.add_collection(EllipseCollection(\n'
                              '        [10, 20], [5, 8], [0, 90], units="points", offsets=[(0.5, 1), (1.5, 1.5)],\n'
                              '        offset_transform=ax.transData, label=f"ellipse-{name}", **kw))\n'
                              '    ax.quiver([0, 1, 2], [0.5, 1, 1.5], [1, 1, -1], [1, -1, 1], label=f"arrows-{name}", **kw)\n'
                              'ax.set_rasterization_zorder(0.5)  # "below" is rasterized too')
    assert build(project).ok
    root, m = _panel_svg(project), _manifest(project)
    parts = m["parts"]
    assert len(list(root.iter(f"{SVG}image"))) == 5, "rasterized: an image each; below the zorder: one for all"
    for series in ("pts", "square-pts", "ellipse-pts", "arrows-pts"):
        vector = parts[f"main.series.{series}"]["bbox"]
        for how in ("raster", "below"):
            assert parts[f"main.series.{series.replace('pts', how)}"]["bbox"] == pytest.approx(vector, abs=1e-3), how
    # the vector scatter's box is the marks' (6 pt across) around the points the SVG draws
    uses = list(_by_id(root, "main.series.pts").iter(f"{SVG}use"))
    xs, ys = [float(u.get("x")) for u in uses], [float(u.get("y")) for u in uses]
    assert parts["main.series.pts"]["bbox"] == pytest.approx([min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3],
                                                             abs=0.01)
    # a square of circumradius √(200/π) pt, drawn as a diamond turned 0.5 rad: 2r·cos 0.5 each way
    x0, y0, x1, y1 = parts["main.series.square-pts"]["bbox"]
    side = 2 * math.sqrt(200 / math.pi) * math.cos(0.5)
    assert (x1 - x0, y1 - y0) == (pytest.approx(side, abs=0.01), pytest.approx(side, abs=0.01))
    # the ellipses: 10 × 5 pt at (0.5, 1), and 20 × 8 pt turned upright at (1.5, 1.5), so the
    # box runs from 5 pt left of the first to 4 pt right of the second, and from 2.5 pt below the
    # first to 10 pt above the second; the axes' scale (pt per unit) is its clip box in the SVG
    # over its limits. (Turned by other than a right angle, an ellipse's box is its curve's
    # control points', up to 0.2 pt larger than its ink.)
    left, top, right, bottom = _clip_rect(root)
    (xa, xb), (ya, yb) = m["axes"]["main"]["xlim"], m["axes"]["main"]["ylim"]
    x0, y0, x1, y1 = parts["main.series.ellipse-pts"]["bbox"]
    assert x1 - x0 == pytest.approx((right - left) / (xb - xa) + 5 + 4, abs=0.01)
    assert y1 - y0 == pytest.approx(0.5 * (bottom - top) / (yb - ya) + 2.5 + 10, abs=0.01)
    # the arrows: the corners of the polygons the SVG draws
    corners = [_numbers(el.get("d")) for el in _by_id(root, "main.series.arrows-pts").iter(f"{SVG}path")]
    xs, ys = [v for c in corners for v in c[0::2]], [v for c in corners for v in c[1::2]]
    assert len(corners) == 3
    assert parts["main.series.arrows-pts"]["bbox"] == pytest.approx([min(xs), min(ys), max(xs), max(ys)], abs=0.01)


def test_a_mark_at_nan_or_inf_is_left_out_of_its_collections_box(project):
    """A scatter's NaN point is not drawn, but matplotlib's extents counted it at display
    (0, 0): the series was boxed to its axes' lower-left corner (the panel's origin with
    clip_on=False), and a canvas outlined most of the plot as that series. Per-mark sizes go
    with their points: the NaN point's large one must not land on the point after it."""
    _add_to_producer(project, 'import numpy as np\n'
                              'ax.scatter([0, 1, 2], [0.5, 1, 1.5], s=20, label="plain")\n'
                              'ax.scatter([np.nan, 0, 1, 2], [1, 0.5, 1, 1.5], s=[400, 20, 20, 20], label="gap")\n'
                              'ax.scatter([0, 1, 2, 1], [0.5, 1, 1.5, np.inf], s=20, clip_on=False, label="free")\n'
                              'ax.scatter(np.ma.masked_array([0, 1, 2, 3], [0, 0, 0, 1]), [0.5, 1, 1.5, 1], s=20,'
                              ' label="masked")\n'
                              # on an axes of its own: conftest's categorical x axis fails matplotlib's
                              # "best" legend with an all-NaN scatter, idofig or not
                              'n = f.add_axes([0.6, 0.6, 0.3, 0.3]); idf.name(n, "n")\n'
                              'n.scatter([np.nan], [1], label="nothing")')
    assert build(project).ok
    parts = _manifest(project)["parts"]
    plain = parts["main.series.plain"]["bbox"]
    for series in ("gap", "free", "masked"):
        assert parts[f"main.series.{series}"]["bbox"] == pytest.approx(plain, abs=1e-3), series
    assert parts["n.series.nothing"]["bbox"] is None


def _findings(project, **doc_changes):
    doc = {**S.load_figure(project.figure_json("fig-1")), **doc_changes}
    return compliance(project, "fig-1", doc)


def test_the_members_of_a_group_that_break_a_rule_are_one_finding_naming_the_group(project):
    """One finding per tick label made 20 of a ported project's 73. The group is a part an
    editor selects (SUNA's ruleFinding reads `fig/panel: <part> is …`)."""
    _style(project, "main.xtick.*", {"fontsize": 4})
    _style(project, "main.xtick.b", {"fontsize": 4.5})
    _style(project, "main.ylabel", {"fontsize": 3}, pid="b")
    _style(project, "main.legend", {"fontsize": 4.8}, pid="b")  # its two entries, control and trend
    assert build(project).ok
    errors, _ = _findings(project)
    assert "fig-1/a: main.xtick.* is 4–4.5 pt (3 parts); Nature requires at least 5 pt" in errors  # A, B, C
    assert "fig-1/b: main.ylabel is 3 pt; Nature requires at least 5 pt" in errors
    assert "fig-1/b: main.legend is 4.8 pt (2 parts); Nature requires at least 5 pt" in errors
    assert not any(".xtick." in e and ".xtick.*" not in e for e in errors), errors
    for e in errors:
        panel, part = re.match(r"^fig-1/([A-Za-z0-9._-]+): (\S+) is ", e).groups()
        assert part in _manifest(project, panel)["parts"], f"{part} must be selectable"
    assert _manifest(project)["parts"]["main.xtick.*"]["group"] and len(errors) == 3
    # one member of a group breaking the rule is named itself
    _style(project, "main.xtick.*", {"fontsize": None})
    assert build(project).ok
    assert "fig-1/a: main.xtick.b is 4.5 pt; Nature requires at least 5 pt" in _findings(project)[0]


def test_a_legend_with_a_gid_names_its_entries_after_it(project):
    """A figure legend's gid named the legend, but its frame and entries were named after the
    derived "legend", their parent: no part. A finding grouping the entries named "legend",
    which no editor can select (a finding names a part or group in the manifest). An axes
    legend's gid left the legend the role "author" and its entries no name at all."""
    _add_to_producer(project, 'f.legend(fontsize=4).set_gid("key")\nax.get_legend().set_gid("axkey")')
    assert build(project).ok
    parts = _manifest(project)["parts"]
    for gid in ("key", "axkey"):
        assert parts[gid]["role"] == "legend", gid
        assert {n for n, p in parts.items() if p.get("parent") == gid} == {f"{gid}.{s}" for s in
                                                                           ("frame", "control", "trend")}
    assert [n for n, p in parts.items() if p.get("parent") and p["parent"] not in parts] == []
    small = "is 4 pt{}; Nature requires at least 5 pt"
    assert f"fig-1/a: key {small.format(' (2 parts)')}" in _findings(project)[0]
    # a manifest written before, its entries' parent a part it does not have, names each entry
    manifest = project.panel_dir("fig-1", "a") / "manifest.json"
    doc = json.loads(read(manifest))
    for part in doc["parts"].values():
        if part.get("parent") == "key":
            part["parent"] = "legend"
    manifest.write_text(json.dumps(doc))
    assert {f"fig-1/a: key.{e} {small.format('')}" for e in ("control", "trend")} <= set(_findings(project)[0])


def test_a_stroke_thinner_than_the_journals_line_weight_is_a_finding_wherever_it_is(project):
    """A network's links (a LineCollection) at 0.2 pt passed Nature's 0.25 pt: only lines and
    spines were checked. So did a raster plot's 0.1 pt spikes: an eventplot's width was not read.
    What draws no stroke (a colorbar's empty dividers, a markers-only line, a patch edge with no
    line style, which matplotlib draws 0 wide) is not a finding."""
    _add_to_producer(project, 'from matplotlib.collections import LineCollection\n'
                              'ax.add_collection(LineCollection([[(0, 0), (1, 1)]], linewidths=0.2, label="links"))\n'
                              'ax.add_collection(LineCollection([], linewidths=0.1, label="empty"))  # draws nothing\n'
                              'ax.plot([0, 1], [1, 1], "o", lw=0.1, label="dots")  # markers only: no stroke\n'
                              'ax.bar([0.5], [1], linestyle="none", edgecolor="k", linewidth=0.1, label="nostroke")\n'
                              'ax.bar([1.5], [1], linestyle="--", edgecolor="k", linewidth=0.1, label="dashed")\n'
                              # a raster plot: an EventCollection gives its width as one number
                              'ax.eventplot([[0.1, 0.5]], linewidths=0.1, label="spikes")\n'
                              # a weighted network: one width per edge, the thin one first or last
                              'for name, widths in (("net", [1.0, 0.1]), ("ten", [0.1, 1.0])):\n'
                              '    ax.add_collection(LineCollection([[(0, 0.5), (1, 1.5)], [(0, 1.5), (1, 0.5)]],\n'
                              '                                     linewidths=widths, label=name))')
    _style(project, "main.series.control", {"linewidth": 0.1, "edgecolor": "black"})
    assert build(project).ok
    root = _panel_svg(project)
    assert "stroke" not in _by_id(root, "main.series.nostroke.0").find(f"{SVG}path").get("style")
    thin = [w for w in _findings(project)[1] if w.startswith("fig-1/a:") and " pt wide" in w]
    assert sorted(thin) == ["fig-1/a: main.series.control is 0.1 pt wide (3 parts); Nature states at least 0.25 pt",
                            "fig-1/a: main.series.dashed.0 is 0.1 pt wide; Nature states at least 0.25 pt",
                            "fig-1/a: main.series.links is 0.2 pt wide; Nature states at least 0.25 pt",
                            "fig-1/a: main.series.net is 0.1 pt wide; Nature states at least 0.25 pt",
                            "fig-1/a: main.series.spikes is 0.1 pt wide; Nature states at least 0.25 pt",
                            "fig-1/a: main.series.ten is 0.1 pt wide; Nature states at least 0.25 pt"]
    parts = _manifest(project)["parts"]
    assert parts["main.series.spikes"]["props"]["linewidth"] == 0.1 and parts["main.series.spikes"]["bbox"]
    for name in ("main.series.net", "main.series.ten"):  # no one width, as colours whose marks differ
        assert parts[name]["props"]["linewidth"] is None and parts[name]["thinnest_pt"] == 0.1, name
    assert parts["main.series.links"]["props"]["linewidth"] == 0.2 and "thinnest_pt" not in parts["main.series.links"]
    assert [parts[f"main.series.{s}.0"]["props"]["linestyle"] for s in ("nostroke", "dashed", "control")] == \
        ["None", "--", "solid"]
    # a journal that states no line weight states nothing about strokes (D4)
    assert not [w for w in _findings(project, journal="jneurosci", width={"mm": 170})[1] if " pt wide" in w]


def test_an_edge_drawn_in_no_colour_is_not_a_stroke(project):
    """pcolor draws a 0.25 pt edge in no colour by default, and the manifest read that colour as
    #000000: an ordinary heatmap was a finding under SUNA's own 0.5 pt, and an editor showed
    black edges on bars that have none."""
    _add_to_producer(project, 'import numpy as np\n'
                              'ax.pcolor(np.arange(6.0).reshape(2, 3), gid="heat")\n'
                              'ax.pcolor(np.arange(6.0).reshape(2, 3), edgecolors="k", linewidth=0.25, gid="grid")\n'
                              # an edge in each mark's own face colour (a scatter's default) merges into it
                              'ax.scatter([0, 1, 2], [0.5, 1, 1.5], s=16, linewidths=0.1, label="dots")\n'
                              'ax.scatter([0, 1, 2], [1, 1, 1], s=16, c=[0, 1, 2], linewidths=0.1, label="mapped")\n'
                              'ax.scatter([0, 1, 2], [0, 0, 0], s=16, edgecolors="k", linewidths=0.1, label="ringed")')
    assert build(project).ok
    parts = _manifest(project)["parts"]
    assert parts["heat"]["props"]["edgecolor"] == "none" and parts["grid"]["props"]["edgecolor"] == "#000000"
    assert parts["main.series.control.0"]["props"]["edgecolor"] == "none"  # a bar's default edge
    for series in ("dots", "mapped"):
        assert parts[f"main.series.{series}"]["props"]["edgecolor"] == "face", series
    thin = [w for w in _findings(project, journal="suna", width={"mm": 178})[1] if w.startswith("fig-1/a: ")
            and " pt wide" in w]
    assert [w for w in thin if "heat" in w or "grid" in w or "series.dots" in w or "mapped" in w or "ringed" in w] == [
        "fig-1/a: grid is 0.25 pt wide; SUNA style states at least 0.5 pt",
        "fig-1/a: main.series.ringed is 0.1 pt wide; SUNA style states at least 0.5 pt"], thin


def test_a_mark_that_is_all_stroke_is_held_to_the_line_weight(project):
    """A '+', 'x' or '|' marker has no fill: matplotlib sets its edge to `face` itself, and that
    stroke is the whole mark. Read as `face`, which merges into a fill, a '+' drawn 0.1 pt wide
    passed Nature's 0.25 pt, while a ring of the same width was a finding. A face-coloured edge
    on marks with an inside (a filled scatter, a pcolormesh's cells, a hexbin's) is still none."""
    _add_to_producer(project, 'import numpy as np\n'
                              'ax.scatter([0, 1, 2], [0.5, 1, 1.5], marker="+", linewidths=0.1, label="plus")\n'
                              'ax.scatter([0, 1, 2], [1, 1, 1], marker="|", c=[0, 1, 2], linewidths=0.1, label="bars")\n'
                              'ax.scatter([0, 1, 2], [0, 0, 0], linewidths=0.1, label="dots")\n'
                              'ax.pcolormesh(np.arange(6.0).reshape(2, 3), edgecolors="face", linewidth=0.1, gid="mesh")\n'
                              'ax.hexbin([0, 1, 2], [0, 1, 2], gridsize=2, linewidths=0.1, gid="hex")')
    assert build(project).ok
    parts = _manifest(project)["parts"]
    plus = _by_id(_panel_svg(project), "main.series.plus").find(f".//{SVG}use").get("style")
    assert parts["main.series.plus"]["props"]["edgecolor"] == plus.split("stroke: ")[1].split(";")[0]
    assert parts["main.series.bars"]["props"]["edgecolor"] is None  # mapped: one colour per mark
    assert [parts[n]["props"]["edgecolor"] for n in ("main.series.dots", "mesh", "hex")] == ["face"] * 3
    thin = [w for w in _findings(project)[1] if w.startswith("fig-1/a: ") and " pt wide" in w]
    assert sorted(thin) == ["fig-1/a: main.series.bars is 0.1 pt wide; Nature states at least 0.25 pt",
                            "fig-1/a: main.series.plus is 0.1 pt wide; Nature states at least 0.25 pt"]


def test_tick_marks_thinner_than_the_line_weight_are_a_finding(project):
    """`tickwidth` makes an axis' tick marks thin, and 0.1 pt ones passed Nature's 0.25 pt: an
    axis has no box, so the check passed it over as not drawn. Marks of no length draw nothing,
    and idofig's own widths (panel b's) are no finding; nor are the marks of an axes turned off
    with axis("off") (an image's), which are never drawn and which nothing visible could fix."""
    _add_to_producer(project, 'img = f.add_axes([0.1, 0.1, 0.2, 0.2]); idf.name(img, "img")\n'
                              'img.imshow([[0, 1], [1, 0]]); img.axis("off")')
    _style(project, "main.xaxis", {"tickwidth": 0.1})
    _style(project, "main.yaxis", {"tickwidth": 0.1, "ticklength": 0})
    _style(project, "img.xaxis", {"tickwidth": 0.1})
    assert build(project).ok
    parts = _manifest(project)["parts"]
    assert parts["img.xaxis"]["drawn"] is False and parts["img.xaxis"]["props"]["tickwidth"] == 0.1
    assert "drawn" not in parts["main.xaxis"]
    ticks = _by_id(_panel_svg(project), "main.xaxis").find(f".//{SVG}use").get("style")
    assert "stroke-width: 0.1" in ticks, ticks
    thin = [w for w in _findings(project)[1] if " pt wide" in w]
    assert thin == ["fig-1/a: main.xaxis is 0.1 pt wide; Nature states at least 0.25 pt"], thin


def test_letters_take_a_colour_and_are_black_without_one(project):
    def letter_fill():
        style = _by_id(_svg_root(project.figure_dir("fig-1") / "figure.svg"), "a.letter").get("style")
        return style.split("fill: ")[1].split(";")[0]

    compose(project, "fig-1")
    assert letter_fill() == "#000000"
    S.update_figure(project.figure_json("fig-1"), [{"op": "letters", "patch": {"color": "#161514"}}])
    compose(project, "fig-1")
    assert letter_fill() == "#161514"
    doc = S.load_figure(project.figure_json("fig-1"))
    assert "letters.color must be a colour" in S.validate_figure({**doc, "letters": {"color": "ink"}})
    with pytest.raises(S.SpecError):
        S.update_figure(project.figure_json("fig-1"), [{"op": "letters", "patch": {"color": 3}}])


def test_a_colour_only_matplotlib_knows_is_composed_as_the_colour_it_stands_for(project):
    """`fill: C1`, `fill: 0.5` or `fill: r` is not CSS: every SVG renderer (SUNA's canvas and
    its PDF export) dropped it and drew the letter or annotation black, and nothing said so."""
    from matplotlib.colors import to_hex

    S.update_figure(project.figure_json("fig-1"), [{"op": "annotation.add", "annotation": {
        "id": "n", "type": "box", "from": {"x": 1, "y": 1}, "to": {"x": 5, "y": 5}}}])
    for spelling, css in (("C1", "#ff7f0e"), ("tab:red", "#d62728"), ("0.5", "#808080"), ("r", "#ff0000"),
                          ("#161514", "#161514"), ("steelblue", "steelblue"), ("none", "none")):
        S.update_figure(project.figure_json("fig-1"), [
            {"op": "letters", "patch": {"color": spelling}},
            {"op": "annotation.update", "id": "n", "patch": {"style": {"color": spelling, "fill": spelling}}}])
        root = ET.fromstring(compose(project, "fig-1", write=False).svg)
        letter, box = _by_id(root, "a.letter").get("style"), _by_id(root, "n").get("style")
        assert f"fill: {css}" in letter and f"stroke: {css}" in box and f"fill: {css};" in box, (spelling, letter, box)
    # every spelling matplotlib alone knows, checked against matplotlib's own reading of it
    import matplotlib.pyplot as plt

    cycle = [c["color"] for c in plt.rcParamsDefault["axes.prop_cycle"]]
    for name in sorted(P.COLOR_NAMES):
        expect = to_hex(name) if len(name) == 1 or name.startswith("tab:") else name
        assert P.css_color(name) == expect, name
    assert [P.css_color(f"C{i}") for i in range(10)] == [to_hex(c) for c in cycle]
    for grey in ("0", "0.25", "0.5", "0.75", "1", "1.0"):
        assert P.css_color(grey) == to_hex(grey), grey


def test_a_colour_is_what_matplotlib_takes_so_none_it_refuses_is_written(project):
    """`is_color` stripped and lower-cased what it checked: 'K', 'B' and ' red ' passed, reached
    style.json, and `set_color` raised at the draw — the producer failed, where an invalid
    property is reported and skipped. matplotlib reads a one-letter name in lower case only
    and nothing around a colour."""
    from matplotlib.colors import is_color_like

    spellings = [s for n in P.COLOR_NAMES for s in (n, n.upper(), n.title(), f" {n}", f"{n} ")]
    spellings += [f"C{i}" for i in range(10)] + ["c1", "C1\n", "#fff", "#FFF\n", "#ffffff80", "0.5", "NONE", ""]
    accepted = [s for s in spellings if P.is_color(s)]
    assert [s for s in accepted if not is_color_like(s)] == []
    assert {"Red", "TAB:BLUE", "k", "NONE", "C1"} <= set(accepted)  # names are read in any case but one letter
    build(project)
    for color in ("K", " red "):
        assert "must be a colour" in _refusal(project, "main.xlabel", {"color": color}), color
    (project.panel_dir("fig-1", "a") / "style.json").write_text(
        json.dumps({"schema": 1, "parts": {"main.xlabel": {"color": "K"}}}))
    assert build(project).ok, "written by hand, reported and skipped"
    assert [e["prop"] for e in _manifest(project)["style"]["invalid"]] == ["color"]


def _system_font():
    """A font on this machine that is neither idofig's nor matplotlib's own, or None."""
    from matplotlib import font_manager

    for entry in sorted(font_manager.fontManager.ttflist, key=lambda e: e.fname):
        if "LiberationSans" not in os.path.basename(entry.fname) and not draw._ships_with_matplotlib(entry.fname):
            return entry.name
    return None


def test_a_generic_family_is_checked_as_the_font_it_resolves_to(project):
    """`findfont("sans-serif")` reads a fontconfig pattern and raised, so the family was
    skipped: a house style resolving `sans-serif` to Arial got no warning."""
    _add_to_producer(project, 'f.text(0.1, 0.1, "plain", family="sans-serif")')
    assert build(project).ok
    assert not any("font" in w for w in _manifest(project)["warnings"]), "DejaVu Sans ships with matplotlib"
    _replace_in_producer(project, "idf.save(p)", 'import matplotlib\n'
                         'matplotlib.rcParams["font.sans-serif"] = ["Some Font Nobody Has"]\nidf.save(p)')
    assert build(project).ok
    assert ("font 'sans-serif' is not bundled with idofig; this panel may lay out differently on other machines"
            in _manifest(project)["warnings"])
    name = _system_font()
    if name is None:
        pytest.skip("skipping the resolved-name half: this machine has no font but idofig's and matplotlib's")
    _replace_in_producer(project, '["Some Font Nobody Has"]', repr([name]))
    assert build(project).ok
    assert (f"font 'sans-serif' resolves to {name!r} here, which is not bundled with idofig; this panel may lay "
            "out differently on other machines") in _manifest(project)["warnings"]
