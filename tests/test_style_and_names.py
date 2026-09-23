from __future__ import annotations

import io
import json

import pytest
from conftest import read

from idofig import spec as S
from idofig.build import build, status
from idofig.serve import Server
from idofig.naming import slug, tick_slug


def manifest(project, pid="a"):
    return json.loads(read(project.panel_dir("fig-1", pid) / "manifest.json"))


def test_semantic_names(project):
    build(project)
    parts = manifest(project)["parts"]
    for name in ["main", "main.xlabel", "main.ylabel", "main.title", "main.series.control",
                 "main.series.control.0", "main.series.trend", "main.legend", "main.legend.control",
                 "main.xtick.a", "main.xtick.*", "main.spine.left", "figure.background"]:
        assert name in parts, name
    assert parts["main.series.control"]["group"] is True
    assert parts["main.series.control.0"]["stability"] == "positional"
    assert parts["main.xlabel"]["stability"] == "semantic"
    svg = read(project.panel_dir("fig-1", "a") / "panel.svg")
    assert 'id="main.xlabel"' in svg
    assert 'id="figure.background" data-idofig-role="background"' in svg


def test_names_survive_a_data_change(project):
    build(project)
    before = set(manifest(project)["parts"])
    data = json.loads(read(project.root / "data/values.json"))
    data["control"] = [5.0, 0.2, 3.3]
    data["line"] = [0.1, 0.2, 9.0]
    (project.root / "data/values.json").write_text(json.dumps(data))
    build(project)
    after = set(manifest(project)["parts"])
    stable = {n for n in before if not n.startswith("main.ytick")}  # y tick values move with the data
    assert stable <= after


def test_style_is_applied_before_layout_and_base_is_recorded(project):
    build(project)
    ax_before = manifest(project)["axes"]["main"]["bbox"]
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main.xlabel",
                   {"fontsize": 14, "text": "dose (mg)"})
    build(project)
    m = manifest(project)
    xl = m["parts"]["main.xlabel"]
    assert xl["props"]["fontsize"] == 14 and xl["props"]["text"] == "dose (mg)"
    assert xl["base"] == {"fontsize": 7.0, "text": "condition"}
    # constrained layout made room: the axes got shorter
    assert m["axes"]["main"]["bbox"][3] < ax_before[3]
    assert "dose (mg)" in read(project.panel_dir("fig-1", "a") / "panel.svg")


def test_detached_and_invalid_entries_are_reported_not_applied(project):
    build(project)
    path = project.panel_dir("fig-1", "a") / "style.json"
    path.write_text(json.dumps({"schema": 1, "parts": {
        "main.series.gone": {"color": "red"},
        "main.xlabel": {"fontsize": "huge", "color": "#ff0000"},
    }}))
    build(project)
    st = manifest(project)["style"]
    assert st["detached"] == ["main.series.gone"]
    assert st["invalid"][0]["part"] == "main.xlabel" and st["invalid"][0]["prop"] == "fontsize"
    assert manifest(project)["parts"]["main.xlabel"]["props"]["color"] == "#ff0000"


def test_wildcards_and_specificity(project):
    build(project)
    path = project.panel_dir("fig-1", "a") / "style.json"
    path.write_text(json.dumps({"schema": 1, "parts": {
        "main.xtick.*": {"fontsize": 5, "color": "#555555"},
        "main.xtick.b": {"color": "#ff0000"},
    }}))
    build(project)
    parts = manifest(project)["parts"]
    assert parts["main.xtick.a"]["props"]["fontsize"] == 5
    assert parts["main.xtick.a"]["props"]["color"] == "#555555"
    assert parts["main.xtick.b"]["props"]["color"] == "#ff0000"


def test_series_restyle_restyles_its_legend_key(project):
    build(project)
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main.series.trend", {"color": "#009e73"})
    build(project)
    svg = read(project.panel_dir("fig-1", "a") / "panel.svg")
    assert svg.count("stroke: #009e73") >= 2  # the line and its legend key


def test_group_style_applies_to_every_member(project):
    build(project)
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main.series.control", {"facecolor": "#cc79a7"})
    build(project)
    parts = manifest(project)["parts"]
    for i in range(3):
        assert parts[f"main.series.control.{i}"]["props"]["facecolor"] == "#cc79a7"


def test_slugs():
    assert slug("Time (s)") == "time-s"
    assert slug("") == "unnamed"
    assert tick_slug("−0.5") == "neg-0-5"
    assert tick_slug("0.5") == "0-5"


def test_author_gid_collision_is_an_error(project):
    src = read(project.root / "figures/fig-1/make.py")
    src = src.replace('ax.set_xlabel("condition")', 'ax.set_xlabel("condition", gid="dup"); ax.set_ylabel("r", gid="dup")')
    (project.root / "figures/fig-1/make.py").write_text(src)
    rep = build(project)
    assert not rep.ok and "gid 'dup'" in rep.runs[0].error


@pytest.mark.parametrize("bad", [
    {"schema": 2, "id": "fig-1", "width": {"preset": "huge"}},
    {"schema": 1, "id": "fig-1", "width": {"mm": 100}},
])
def test_invalid_figure_json_is_rejected(bad):
    assert S.validate_figure(bad, expected_id="fig-1")


def test_a_renamed_part_detaches_its_override_and_move_style_reattaches_it(project):
    build(project)
    style = project.panel_dir("fig-1", "a") / "style.json"
    S.update_style(style, "main.series.trend", {"color": "#009e73"})
    src = read(project.root / "figures/fig-1/make.py")
    assert 'label="trend"' in src
    (project.root / "figures/fig-1/make.py").write_text(src.replace('label="trend"', 'label="fit"'))
    build(project)
    st = status(project)[0].to_json()
    a = next(p for p in st["panels"] if p["id"] == "a")
    assert a["detached_styles"] == ["main.series.trend"]
    # kept in the file, not applied, not lost
    assert "main.series.trend" in json.loads(read(style))["parts"]

    srv = Server(project, out=io.StringIO())
    srv.out = io.StringIO()
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "move_style",
                  "params": {"figure": "fig-1", "panel": "a", "from": "main.series.trend", "to": "main.series.fit"}})
    reply = json.loads(srv.out.getvalue().splitlines()[-1])
    assert reply["result"]["before"] is not None
    assert json.loads(read(style))["parts"] == {"main.series.fit": {"color": "#009e73"}}
    build(project)
    a = next(p for p in status(project)[0].to_json()["panels"] if p["id"] == "a")
    assert not a.get("detached_styles")
    assert "stroke: #009e73" in read(project.panel_dir("fig-1", "a") / "panel.svg")
