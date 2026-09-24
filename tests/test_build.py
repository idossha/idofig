from __future__ import annotations

import json
import os
import subprocess
import sys

from conftest import read, write

from idofig import spec as S
from idofig.build import build, check, figure_status


def _states(project):
    return {p.id: (p.state, p.reasons) for p in figure_status(project, "fig-1").panels}


def test_first_build_publishes_and_everything_is_fresh(project):
    rep = build(project)
    assert rep.ok, rep.to_json()
    d = project.figure_dir("fig-1")
    assert (d / "panels" / "a" / "panel.svg").is_file()
    assert (d / "panels" / "b" / "manifest.json").is_file()
    assert (d / "figure.svg").is_file()
    assert (d / "figure.lock.json").is_file()
    assert {k: v[0] for k, v in _states(project).items()} == {"a": "fresh", "b": "fresh"}
    assert figure_status(project, "fig-1").figure_svg == "fresh"


def test_rebuild_is_byte_identical(project):
    build(project)
    d = project.figure_dir("fig-1")
    before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    build(project, force=True)
    after = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert before == after


def test_direct_run_equals_build(project):
    """A direct run sets no MPLBACKEND (`build` sets Agg); on a Mac matplotlib then picked
    the macosx canvas, whose Retina dpi changed the layout, until idofig.panels() chose Agg."""
    build(project)
    d = project.figure_dir("fig-1")
    before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    env = {k: v for k, v in os.environ.items() if k != "MPLBACKEND"}
    subprocess.run([sys.executable, "figures/fig-1/make.py"], cwd=project.root, check=True, env=env)
    after = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert before == after


def test_input_change_makes_both_panels_stale_with_a_reason(project):
    build(project)
    data = json.loads(read(project.root / "data/values.json"))
    data["control"][0] = 3.0
    (project.root / "data/values.json").write_text(json.dumps(data))
    states = _states(project)
    assert states["a"][0] == "stale" and "data/values.json changed" in states["a"][1]
    assert states["b"][0] == "stale"


def test_style_edit_makes_only_that_panel_stale(project):
    build(project)
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main.xlabel", {"fontsize": 9})
    states = _states(project)
    assert states["a"] == ("stale", ["style.json changed"])
    assert states["b"][0] == "fresh"
    rep = build(project)
    assert [r.panels for r in rep.runs] == [["a"]]  # only the stale panel reran
    assert _states(project)["a"][0] == "fresh"


def test_resize_makes_panel_stale_and_redraws_at_new_size(project):
    build(project)
    S.update_figure(project.figure_json("fig-1"), [{"op": "place", "panel": "b", "w": 70}])
    assert _states(project)["b"] == ("stale", ["resized to 70×60 mm"])
    build(project)
    man = json.loads(read(project.panel_dir("fig-1", "b") / "manifest.json"))
    assert abs(man["size"]["w_mm"] - 70) < 0.01


def test_panel_edited_outside_is_detected(project):
    build(project)
    p = project.panel_dir("fig-1", "a") / "panel.svg"
    p.write_text(read(p).replace("condition", "CONDITION"))
    assert "panel.svg was changed outside idofig" in _states(project)["a"][1]


def test_imported_project_helper_is_tracked(project):
    write(project.root / "code" / "helpers.py", "SCALE = 1.0\n")
    src = read(project.root / "figures/fig-1/make.py")
    src = src.replace("import idofig as idf", "import sys\nsys.path.insert(0, 'code')\nimport helpers\nimport idofig as idf")
    (project.root / "figures/fig-1/make.py").write_text(src)
    build(project)
    lock = json.loads(read(project.figure_dir("fig-1") / "figure.lock.json"))
    assert "code/helpers.py" in lock["producers"]["make"]["files"]
    (project.root / "code/helpers.py").write_text("SCALE = 2.0\n")
    assert "code/helpers.py changed" in _states(project)["a"][1]


def test_failed_producer_keeps_old_output_and_reports(project):
    build(project)
    svg_before = read(project.panel_dir("fig-1", "a") / "panel.svg")
    src = read(project.root / "figures/fig-1/make.py")
    (project.root / "figures/fig-1/make.py").write_text(src + "\nraise RuntimeError('boom')\n")
    rep = build(project)
    assert not rep.ok
    assert "boom" in rep.runs[0].error
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == svg_before
    st = _states(project)
    assert st["a"][0] == "failed"
    (project.root / "figures/fig-1/make.py").write_text(src)
    assert build(project).ok
    assert _states(project)["a"][0] == "fresh"


def test_only_builds_the_requested_panel(project):
    rep = build(project, only=["b"])
    assert [r.panels for r in rep.runs] == [["b"]]
    assert not (project.panel_dir("fig-1", "a") / "panel.svg").exists()
    assert _states(project)["a"][0] == "missing"


def test_producer_that_skips_a_declared_panel_fails(project):
    fig = json.loads(read(project.figure_json("fig-1")))
    fig["panels"].append({"id": "c", "place": {"x": 0, "y": 64, "w": 88, "h": 40}})
    fig["producers"][0]["panels"].append("c")
    project.figure_json("fig-1").write_text(json.dumps(fig))
    rep = build(project)
    assert not rep.ok and "did not write panel 'c'" in rep.runs[0].error


def test_check_passes_on_a_fresh_project(project):
    build(project)
    rep = check(project)
    assert rep.ok, rep.errors


def test_check_catches_a_hand_edited_panel(project):
    build(project)
    p = project.panel_dir("fig-1", "a") / "panel.svg"
    p.write_text(read(p).replace("condition", "CONDITION"))
    rep = check(project)
    assert not rep.ok
    assert any("not reproducible" in e for e in rep.errors)


def test_check_enforces_the_journal_font_floor(project):
    build(project)
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main.xlabel", {"fontsize": 4})
    build(project)
    rep = check(project, run=False)
    assert any("main.xlabel is 4 pt; Nature requires at least 5 pt" in e for e in rep.errors)


def test_a_project_style_cannot_crop_a_panel_or_turn_its_text_into_paths(project):
    """A project's own rc (``savefig.bbox = "tight"``, text as paths) must not change what a
    panel is: its printed size, with text the checker can measure (rules 3 and 4)."""
    path = project.root / "figures/fig-1/make.py"
    text = read(path).replace("idf.save(p)", 'import matplotlib\nmatplotlib.rcParams.update({"savefig.bbox": "tight", "svg.fonttype": "path"})\nidf.save(p)')
    path.write_text(text, encoding="utf-8")
    assert build(project).ok
    svg = read(project.root / "figures/fig-1/panels/a/panel.svg")
    import re

    width = float(re.search(r'<svg[^>]*\bwidth="([\d.]+)pt"', svg).group(1))
    assert abs(width - 88 / 25.4 * 72) < 0.05
    assert "<text" in svg


def test_a_font_matplotlib_ships_is_not_flagged_but_a_system_font_is(project):
    """DejaVu Sans Mono comes with matplotlib (the lock records its version), so it lays out
    the same everywhere; a font found only on this machine does not."""
    path = project.root / "figures/fig-1/make.py"
    text = read(path).replace(
        "idf.save(p)",
        'for f in p.values():\n    f.text(0.1, 0.1, "mono", family="DejaVu Sans Mono")\n'
        '    f.text(0.2, 0.2, "elsewhere", family="Some Font Nobody Has")\nidf.save(p)',
    )
    path.write_text(text, encoding="utf-8")
    assert build(project).ok
    import json

    warnings = " ".join(json.loads(read(project.root / "figures/fig-1/panels/a/manifest.json")).get("warnings", []))
    assert "Some Font Nobody Has" in warnings
    assert "DejaVu Sans Mono" not in warnings
