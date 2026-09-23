"""Failure memory, races between edits and builds, the build queue, and SUNA discovery."""

from __future__ import annotations

import io
import json
import threading
import time

from conftest import read, write

from idofig import spec as S
from idofig.build import build, figure_status
from idofig.project import find_project
from idofig.serve import Server


def _state(project, pid="a"):
    return next(p for p in figure_status(project, "fig-1").panels if p.id == pid)


def _break_producer(project):
    path = project.root / "figures/fig-1/make.py"
    good = read(path)
    path.write_text(good.replace("idf.save(p)", "raise SystemExit('boom')"), encoding="utf-8")
    return path, good


def test_a_failure_is_final_only_for_the_inputs_it_saw(project):
    assert build(project).ok
    path, good = _break_producer(project)
    rep = build(project)
    assert not rep.ok
    st = _state(project)
    assert st.state == "failed" and "boom" in st.error
    # nothing changed: an automatic rebuild must not retry it forever
    assert build(project, retry_failed=False).runs == []
    # the author edits the script again: now it is stale, and the last error stays visible
    path.write_text(good.replace("idf.save(p)", "raise SystemExit('still boom')"), encoding="utf-8")
    st = _state(project)
    assert st.state == "stale" and "changed since the last failed build" in st.reasons and st.error
    # fixing it publishes again and clears the failure
    path.write_text(good, encoding="utf-8")
    assert build(project).ok
    assert _state(project).state == "fresh" and _state(project).error is None


def test_published_files_survive_a_failed_build(project):
    build(project)
    before = read(project.panel_dir("fig-1", "a") / "panel.svg")
    _break_producer(project)
    build(project)
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == before


def test_an_edit_made_while_the_producer_runs_leaves_the_panel_stale(project):
    """The lock must record what the run saw, not what is on disk when it finishes."""
    build(project)
    path = project.root / "figures/fig-1/make.py"
    path.write_text(read(path).replace("import idofig as idf", "import time, idofig as idf\ntime.sleep(1.5)"),
                    encoding="utf-8")
    style = project.panel_dir("fig-1", "a") / "style.json"

    def edit_midway():
        time.sleep(0.6)
        S.update_style(style, "main.xlabel", {"fontsize": 9})

    t = threading.Thread(target=edit_midway)
    t.start()
    assert build(project).ok
    t.join()
    st = _state(project)
    assert st.state == "stale" and "style.json changed" in st.reasons


def test_journal_follows_suna_json_when_the_project_does_not_set_one(tmp_path, monkeypatch):
    root = tmp_path / "paper"
    write(root / "suna.json", json.dumps({"activeProfileId": "nature", "directories": {"figures": "figs"}}))
    (root / "figs").mkdir()
    proj = find_project(root)
    assert proj.journal == "nature" and proj.figures_dir == (root / "figs").resolve()
    write(root / "suna.json", json.dumps({"activeProfileId": "my-lab-house-style"}))
    assert find_project(root).journal == "suna"
    write(root / "pyproject.toml", '[tool.idofig]\njournal = "science"\n')
    assert find_project(root).journal == "science"


def _collect(server):
    out = io.StringIO()
    server.out = out
    return out


def _messages(out):
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_builds_queue_instead_of_refusing(project):
    srv = Server(project, out=io.StringIO())
    out = _collect(srv)
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "build", "params": {}})
    srv.dispatch({"jsonrpc": "2.0", "id": 2, "method": "build", "params": {"figures": ["fig-1"]}})
    srv.wait_idle(120)
    replies = {m["id"]: m for m in _messages(out) if "id" in m}
    assert replies[1]["result"]["ok"] and replies[2]["result"]["ok"]
    # the second found the first had done everything
    assert replies[2]["result"]["runs"] == []


def test_restore_answers_the_replaced_text_so_redo_works(project):
    build(project)
    srv = Server(project, out=io.StringIO())
    out = _collect(srv)
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "update_figure",
                  "params": {"figure": "fig-1", "ops": [{"op": "place", "panel": "a", "x": 3}]}})
    edit = _messages(out)[-1]["result"]
    srv.dispatch({"jsonrpc": "2.0", "id": 2, "method": "restore",
                  "params": {"path": "figures/fig-1/figure.json", "text": edit["before"],
                             "expect_sha": edit["after_sha"]}})
    undo = _messages(out)[-1]["result"]
    assert json.loads(undo["previous"])["panels"][0]["place"]["x"] == 3
    assert undo["compose"]["path"].endswith("figure.svg")
    srv.dispatch({"jsonrpc": "2.0", "id": 3, "method": "restore",
                  "params": {"path": "figures/fig-1/figure.json", "text": undo["previous"],
                             "expect_sha": undo["sha"]}})
    assert "result" in _messages(out)[-1]
    assert S.load_figure(project.figure_json("fig-1"))["panels"][0]["place"]["x"] == 3
