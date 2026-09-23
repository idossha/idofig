from __future__ import annotations

import base64
import io
import json
import re
import time

from conftest import read, write

from idofig import spec as S
from idofig.build import build, status
from idofig.compose import compose
from idofig.fsutil import sha256_file
from idofig.serve import Server

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def test_compose_namespaces_ids_places_letters_and_is_fast(project):
    build(project)
    t0 = time.perf_counter()
    res = compose(project, "fig-1", write=False)
    assert (time.perf_counter() - t0) < 0.2
    svg = res.svg
    assert 'id="a::main.xlabel"' in svg and 'id="b::main.xlabel"' in svg
    assert 'id="a.letter"' in svg and ">a</text>" in svg
    assert 'transform="translate(260.787 0)"' in svg  # 92 mm → pt
    ids = re.findall(r'\bid="([^"]+)"', svg)
    assert len(ids) == len(set(ids)), "ids must be unique across panels"
    for ref in re.findall(r"url\(#([^)]+)\)", svg):
        assert ref in ids
    assert res.width_mm == 183


def test_annotations_anchor_to_parts_and_data_and_detach(project):
    build(project)
    S.update_figure(project.figure_json("fig-1"), [
        {"op": "annotation.add", "annotation": {
            "id": "sig", "type": "bracket", "label": "*",
            "from": {"panel": "a", "part": "main.series.control.0", "at": "top"},
            "to": {"panel": "a", "part": "main.series.control.2", "at": "top"}}},
        {"op": "annotation.add", "annotation": {
            "id": "note", "type": "text", "text": "peak", "at": {"panel": "b", "axes": "main", "data": [1, 1.8]}}},
        {"op": "annotation.add", "annotation": {
            "id": "lost", "type": "arrow", "from": {"x": 1, "y": 1},
            "to": {"panel": "a", "part": "main.series.missing"}}},
    ])
    res = compose(project, "fig-1")
    assert 'id="sig" data-idofig-annotation="bracket"' in res.svg
    # equal short legs: both leg ends sit at the same height, whatever the two bars' heights
    d = re.search(r'id="sig" data-idofig-annotation="bracket"><path d="([^"]+)"', res.svg).group(1)
    ys = [float(v) for v in re.findall(r"[ML] [-\d.]+ ([-\d.]+)", d)]
    assert ys[0] == ys[3] and ys[1] == ys[2] and ys[0] > ys[1]
    assert ">peak</text>" in res.svg
    assert res.detached == [{"id": "lost", "reason": "part 'main.series.missing' is not in panel 'a' any more"}]


def test_image_panels(project, tmp_path):
    (project.root / "figures/fig-1/scheme.png").write_bytes(PNG_1PX)
    write(project.root / "figures/fig-1/scheme.svg",
          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 5"><rect id="r" width="10" height="5"/></svg>')
    S.update_figure(project.figure_json("fig-1"), [
        {"op": "panel.add", "id": "png", "image": "figures/fig-1/scheme.png", "place": {"x": 0, "y": 64, "w": 40, "h": 20}},
        {"op": "panel.add", "id": "vec", "image": "figures/fig-1/scheme.svg", "place": {"x": 50, "y": 64, "w": 40, "h": 20}},
    ])
    build(project)
    svg = read(project.figure_dir("fig-1") / "figure.svg")
    assert 'data-idofig-image="raster"' in svg and "data:image/png;base64," in svg
    assert 'id="vec::r"' in svg


def test_spec_rejects_conflicts():
    doc = S.new_figure("f")
    doc["panels"] = [{"id": "a", "place": {"x": 0, "y": 0, "w": 10, "h": 10}}]
    doc["producers"] = [{"id": "p", "run": ["python", "x.py"], "panels": ["a"]},
                        {"id": "q", "run": ["python", "y.py"], "panels": ["a", "zz"]}]
    problems = S.validate_figure(doc, expected_id="f")
    assert any("drawn by two producers" in p for p in problems)
    assert any("'zz', which is not in panels" in p for p in problems)


def test_app_keys_are_preserved_and_owned_keys_protected(project):
    S.update_figure(project.figure_json("fig-1"), [{"op": "app.set", "key": "label", "value": "Graphical abstract"}])
    doc = json.loads(read(project.figure_json("fig-1")))
    assert doc["label"] == "Graphical abstract" and doc["caption"]["title"] == "A test figure."
    try:
        S.update_figure(project.figure_json("fig-1"), [{"op": "app.set", "key": "panels", "value": []}])
    except Exception as exc:  # noqa: BLE001
        assert "owned by idofig" in str(exc)
    else:
        raise AssertionError("expected refusal")


def _rpc(server, method, **params):
    out = io.StringIO()
    server.out = out
    server.dispatch({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    server.wait_idle(timeout=120)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    replies = [m for m in lines if m.get("id") == 1]
    events = [m["params"] for m in lines if m.get("method") == "event"]
    return replies[-1], events


def test_serve_workspace_style_validation_undo_and_build(project):
    build(project)
    srv = Server(project, out=io.StringIO())
    reply, _ = _rpc(srv, "workspace")
    fig = reply["result"]["figures"][0]
    assert fig["id"] == "fig-1" and "main.xlabel" in fig["manifests"]["a"]["parts"]

    reply, _ = _rpc(srv, "update_style", figure="fig-1", panel="a", part="main.nope", props={"fontsize": 8})
    assert "has no part 'main.nope'" in reply["error"]["message"]
    reply, _ = _rpc(srv, "update_style", figure="fig-1", panel="a", part="main.xlabel", props={"fontsize": "big"})
    assert reply["error"]["data"]["problems"]

    reply, _ = _rpc(srv, "update_style", figure="fig-1", panel="a", part="main.xlabel", props={"fontsize": 9})
    res = reply["result"]
    assert res["before"] is None
    reply, events = _rpc(srv, "build", figures=["fig-1"])
    assert reply["result"]["ok"] and any(e["event"] == "producer.done" for e in events)

    # undo the style edit: only allowed while the file is what we wrote
    reply, _ = _rpc(srv, "restore", path=res["path"], text=None, expect_sha=res["after_sha"])
    assert "result" in reply
    assert not (project.panel_dir("fig-1", "a") / "style.json").exists()

    reply, _ = _rpc(srv, "update_figure", figure="fig-1", ops=[{"op": "place", "panel": "a", "x": 1}])
    after_sha = reply["result"]["after_sha"]
    (project.figure_json("fig-1")).write_text(read(project.figure_json("fig-1")).replace('"x": 1', '"x": 2'))
    reply, _ = _rpc(srv, "restore", path="figures/fig-1/figure.json", text=reply["result"]["before"],
                    expect_sha=after_sha)
    assert "changed since this edit" in reply["error"]["message"]
    assert sha256_file(project.figure_json("fig-1")) != after_sha


def test_locate_finds_the_line_that_makes_a_part(project):
    from idofig.locate import locate

    build(project)
    hits = locate(project, "fig-1", "a", "main.xlabel")
    assert hits and hits[0]["file"] == "figures/fig-1/make.py" and "set_xlabel" in hits[0]["text"]
    hits = locate(project, "fig-1", "a", "main.series.trend")
    assert hits and 'label="trend"' in hits[0]["text"]


def test_a_misspelt_operation_field_is_refused_not_ignored(project):
    before = read(project.figure_json("fig-1"))
    for op in ({"op": "annotation.update", "id": "x", "set": {"text": "y"}},
               {"op": "place", "panel": "a", "width": 50},
               {"op": "no.such.op"}):
        try:
            S.update_figure(project.figure_json("fig-1"), [op])
        except S.SpecError as exc:
            assert "does not take" in str(exc) or "unknown operation" in str(exc)
        else:
            raise AssertionError(f"expected refusal of {op}")
    assert read(project.figure_json("fig-1")) == before


def test_a_narrower_figure_keeps_its_layout(project):
    build(project)
    srv = Server(project, out=io.StringIO())
    doc = json.loads(read(project.figure_json("fig-1")))
    width_before = doc["width"]
    reply, _ = _rpc(srv, "update_figure", figure="fig-1", ops=[{"op": "width", "preset": "single"}])
    after = reply["result"]["doc"]
    places = [p["place"] for p in after["panels"]]
    single = 89.0  # the default journal's single column
    assert all(p["x"] + p["w"] <= single + 1e-6 for p in places), places
    assert not any("extends past" in w for w in reply["result"]["compose"]["warnings"])
    # a resized panel is stale until it is redrawn at its new size
    st = status(project)[0].to_json()
    assert all(p["state"] == "stale" for p in st["panels"])
    # scale_panels: false leaves the layout to the caller
    reply, _ = _rpc(srv, "update_figure", figure="fig-1", ops=[{"op": "width", "scale_panels": False, **width_before}])
    assert [p["place"] for p in reply["result"]["doc"]["panels"]] == places
