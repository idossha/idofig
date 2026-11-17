"""Every drawn line, patch, collection, image and text is a part (0.14.0).

Before, three things a script draws had no name, so no canvas could select one and no
style.json entry could move it: an arrow drawn with ``ax.annotate``, a line or an arrow added to
the figure itself, and an inset axes with everything in it. Found from SUNA's canvas: "the lines
and arrows do not move". Each is checked to be named, drawn under that id, and moved, scaled or
turned by the common geometry contract, measured from the manifest's boxes.
"""
from __future__ import annotations

import pytest
from conftest import read
from test_fine_control import PT, _add_to_producer, _by_id, _duplicate_ids, _ink, _manifest, _panel_svg, _style

from idofig.build import build

DRAWN = '''
from matplotlib.lines import Line2D
from matplotlib.patches import ConnectionPatch, FancyArrowPatch
ax.annotate("", xy=(1, 1.8), xytext=(0.2, 1.0), arrowprops={"arrowstyle": "->"})
ax.annotate("peak", xy=(1, 2.0), xytext=(0.2, 2.2), arrowprops={"arrowstyle": "->"})
f.add_artist(Line2D([0.2, 0.8], [0.5, 0.5], transform=f.transFigure, color="red"))
f.add_artist(FancyArrowPatch((0.3, 0.3), (0.7, 0.6), transform=f.transFigure, arrowstyle="->", mutation_scale=8))
f.add_artist(Line2D([0.2, 0.8], [0.4, 0.4], transform=f.transFigure, label="threshold"))
ins = ax.inset_axes([0.55, 0.55, 0.35, 0.35])
ins.plot([0, 1], [0, 1])
ins.annotate("", xy=(0.8, 0.8), xytext=(0.2, 0.5), arrowprops={"arrowstyle": "->"})
'''

NEW = ("main.arrow0", "main.text.peak.arrow", "line0", "patch0", "series.threshold",
       "main.inset0", "main.inset0.line0", "main.inset0.arrow0")


@pytest.fixture
def drawn(project):
    _add_to_producer(project, DRAWN)
    assert build(project).ok
    return project


def _box(project, name):
    return _manifest(project)["parts"][name]["bbox"]


def _travel(before, after):
    return [round((b - a) / PT, 2) for a, b in zip(before, after)]


def test_arrows_figure_artists_and_insets_are_parts_drawn_under_their_names(drawn):
    m, svg = _manifest(drawn), _panel_svg(drawn)
    for name in NEW:
        assert m["parts"][name]["bbox"] is not None, name
        _by_id(svg, name)
    parts = m["parts"]
    assert (parts["main.arrow0"]["kind"], parts["main.arrow0"]["role"], parts["main.arrow0"]["stability"]) == \
        ("patch", "arrow", "positional")
    # named after its words, and beside them, not inside: the words move without it
    assert (parts["main.text.peak.arrow"]["stability"], parts["main.text.peak.arrow"]["parent"]) == ("semantic", "main")
    assert parts["line0"].get("parent") is None and parts["series.threshold"]["stability"] == "semantic"
    assert (parts["main.inset0"]["kind"], parts["main.inset0"]["parent"]) == ("axes", "main")
    assert parts["main.inset0.line0"]["parent"] == "main.inset0"
    assert set(m["axes"]) == {"main", "main.inset0"}, "an inset's limits are in the manifest, for data anchors"
    assert _duplicate_ids(svg) == [] and _ink(drawn) == []


def test_naming_them_leaves_every_other_name_as_it_was(project):
    assert build(project).ok
    before = set(_manifest(project)["parts"])
    _add_to_producer(project, DRAWN)
    assert build(project).ok
    after = set(_manifest(project)["parts"])
    assert before <= after
    assert {n for n in after - before if "tick" not in n and "grid" not in n and ".inset0." not in n} == \
        {"main.arrow0", "main.text.peak", "main.text.peak.arrow", "line0", "patch0", "series.threshold", "main.inset0"}


@pytest.mark.parametrize("name", ["main.arrow0", "main.text.peak.arrow", "line0", "patch0", "main.inset0.line0",
                                  "main.inset0.arrow0"])
def test_each_moves_alone_by_its_offset(drawn, name):
    before = {n: _box(drawn, n) for n in NEW}
    _style(drawn, name, {"dx_mm": 2, "dy_mm": -1.5})
    assert build(drawn).ok
    for n in NEW:
        expected = [2, -1.5, 2, -1.5] if n == name else [0, 0, 0, 0]
        if n == "main.inset0" and name.startswith("main.inset0."):
            continue  # its box is its frame; what is drawn in it moved
        assert _travel(before[n], _box(drawn, n)) == pytest.approx(expected, abs=0.02), n
    _by_id(_panel_svg(drawn), name)


def test_an_arrow_scales_and_turns_about_its_own_box(drawn):
    x0, y0, x1, y1 = _box(drawn, "main.arrow0")
    _style(drawn, "main.arrow0", {"scale": 2})
    assert build(drawn).ok
    a0, b0, a1, b1 = _box(drawn, "main.arrow0")
    assert (a1 - a0, b1 - b0) == pytest.approx((2 * (x1 - x0), 2 * (y1 - y0)), rel=0.02)
    assert ((a0 + a1) / 2, (b0 + b1) / 2) == pytest.approx(((x0 + x1) / 2, (y0 + y1) / 2), abs=0.05)


def test_an_inset_moves_with_everything_in_it_and_with_its_host(drawn):
    inside = ("main.inset0", "main.inset0.line0", "main.inset0.arrow0")
    before = {n: _box(drawn, n) for n in (*inside, "main.arrow0", "line0")}
    _style(drawn, "main.inset0", {"dx_mm": -3, "dy_mm": 2})
    assert build(drawn).ok
    for n in inside:
        assert _travel(before[n], _box(drawn, n)) == pytest.approx([-3, 2, -3, 2], abs=0.02), n
    assert _travel(before["main.arrow0"], _box(drawn, "main.arrow0")) == pytest.approx([0, 0, 0, 0], abs=0.02)
    # its host moves too: off its locator, a moved inset used to be left where the host had been
    _style(drawn, "main", {"dx_mm": 1, "dy_mm": 1})
    assert build(drawn).ok
    for n in inside:
        assert _travel(before[n], _box(drawn, n)) == pytest.approx([-2, 3, -2, 3], abs=0.02), n
    assert _travel(before["main.arrow0"], _box(drawn, "main.arrow0")) == pytest.approx([1, 1, 1, 1], abs=0.02)
    assert _travel(before["line0"], _box(drawn, "line0")) == pytest.approx([0, 0, 0, 0], abs=0.02), "the figure's own line stays"


def test_a_host_alone_carries_its_inset(drawn):
    before = {n: _box(drawn, n) for n in ("main.inset0", "main.inset0.line0")}
    _style(drawn, "main", {"dx_mm": 2, "dy_mm": 0})
    assert build(drawn).ok
    for n, box in before.items():
        assert _travel(box, _box(drawn, n)) == pytest.approx([2, 0, 2, 0], abs=0.02), n


def test_an_inset_takes_a_name_and_an_arrow_a_gid(project):
    _add_to_producer(project, 'ins = ax.inset_axes([0.55, 0.55, 0.35, 0.35])\nidf.name(ins, "zoom")\nins.plot([0, 1], [0, 1])\n'
                              'ax.annotate("", xy=(1, 1.8), xytext=(0.2, 1.0), arrowprops={"arrowstyle": "->", "gid": "pointer"})')
    assert build(project).ok
    parts = _manifest(project)["parts"]
    assert (parts["zoom"]["stability"], parts["zoom"]["parent"], parts["zoom.line0"]["parent"]) == ("named", "main", "zoom")
    assert parts["pointer"]["stability"] == "author" and "main.arrow0" not in parts


def test_a_rebuild_with_them_is_byte_identical(drawn):
    first = {p: read(drawn.panel_dir("fig-1", "a") / p) for p in ("panel.svg", "manifest.json")}
    path = drawn.root / "figures/fig-1/make.py"
    path.write_text(read(path) + "\n# touched\n", encoding="utf-8")
    assert build(drawn).ok
    assert {p: read(drawn.panel_dir("fig-1", "a") / p) for p in first} == first


def test_an_arrow_takes_what_a_patch_takes():
    from idofig import props
    assert props.validate("patch", {"dx_mm": 1, "dy_mm": 1, "scale": 1.5, "rotate": 30, "edgecolor": "#ff0000"}, role="arrow") == []
