"""3D mesh panels (idofig 0.11.0, 2026-10-08): ``idofig.mesh`` reads .stl .ply .glb .obj with
trimesh and draws them on a 3D axes, lit from the viewer; a 3D axes has the role ``axes3d`` and
takes its view (``elev azim roll zoom proj``) from style.json; a mesh part's manifest says which
file it drew; ``add-panel --mesh`` scaffolds a producer that lists the mesh in its inputs.
Simplification (0.12.0, 2026-10-09): a mesh of more than ``max_faces`` triangles is drawn
decimated, its values and colours following the file's faces; ``idofig mesh-simplify`` writes
the smaller file.

Where the expected numbers come from: every mesh is made in the test. The .ply and .obj are
written here as text, so their vertices, faces and colours are the ones typed below, not
trimesh's; the .stl's counts are the format's (three vertices stored per facet); the .glb's
bounds are its box's corners moved by the node transforms by hand (a 90° turn about z swaps the
x and y extents). The headlight's colour is #c8c8c8 × (0.35 + 0.65 sin elev) for a triangle in
the plane z = 0 (its normal is z, the viewer's direction makes the angle elev with the plane),
rounded as matplotlib's to_hex rounds. The raster dpi is the PNG's own pixel width over its
width in points, read from panel.svg. A simplified mesh's colours are checked against its own
geometry: a field that is the vertex's x coordinate must give each drawn face about its drawn
centroid's x (decimation moves corners: the bounds are what 1280 → 400 faces measured on the
bumpy sphere, mean 0.031 and max 0.16, with room; a face given another face's value is off by
0.75 on average), and the drawn area must stay that of the file (98.7 % measured; an STL
decimated without merging its corners kept 31 %).

Reproduce: `.venv/bin/python -m pytest tests/test_meshes.py`. Rebuild byte identity of panels
without meshes is test_build.py's; a 3D axes' labels and ticks are test_fine_control.py's.
"""

from __future__ import annotations

import base64
import io
import json
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402
from conftest import read  # noqa: E402

import idofig as idf  # noqa: E402
from idofig import cli, meshes  # noqa: E402
from idofig import props as P  # noqa: E402
from idofig import spec as S  # noqa: E402
from idofig.build import build, figure_status  # noqa: E402
from idofig.errors import IdofigError  # noqa: E402
from idofig.scaffold import add_panel  # noqa: E402
from idofig.serve import Server  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"

# A square pyramid, base 2 × 4 at z 0, apex (1, 2, 3): 5 vertices, 6 faces, so per-vertex and
# per-face values cannot be confused; each vertex its own colour.
PYRAMID_V = [(0, 0, 0), (2, 0, 0), (2, 4, 0), (0, 4, 0), (1, 2, 3)]
PYRAMID_F = [(0, 1, 2), (0, 2, 3), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
PYRAMID_RGBA = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255), (0, 0, 0, 255)]


def _pyramid_ply(path):
    lines = ["ply", "format ascii 1.0", "element vertex 5", "property float x", "property float y",
             "property float z", "property uchar red", "property uchar green", "property uchar blue",
             "property uchar alpha", "element face 6", "property list uchar int vertex_indices", "end_header"]
    lines += [" ".join(map(str, (*v, *c))) for v, c in zip(PYRAMID_V, PYRAMID_RGBA)]
    lines += [f"3 {a} {b} {c}" for a, b, c in PYRAMID_F]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def _tetra_obj(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("v 0 0 0\nv 3 0 0\nv 0 2 0\nv 0 0 1\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n", encoding="ascii")
    return path


def _tetra_stl(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh([[0, 0, 0], [3, 0, 0], [0, 2, 0], [0, 0, 1]], [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
                    process=False).export(path)
    return path


def _two_boxes_glb(path):
    """A 1 × 2 × 3 box twice: turned 90° about z then moved to (10, 20, 30), and moved to (-10, 0, 0)."""
    box = trimesh.creation.box(extents=(1, 2, 3))
    scene = trimesh.Scene()
    turn = trimesh.transformations.rotation_matrix(np.pi / 2, (0, 0, 1))
    scene.add_geometry(box, node_name="right", transform=trimesh.transformations.translation_matrix((10, 20, 30)) @ turn)
    scene.add_geometry(box, node_name="left", transform=trimesh.transformations.translation_matrix((-10, 0, 0)))
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.export(path)
    return path


def _grid(path, faces):
    """A flat strip of ``faces`` triangles (two per unit square, one more if odd)."""
    n = (faces + 1) // 2
    xs = np.arange(n + 1, dtype=float)
    verts = np.concatenate([np.c_[xs, np.zeros(n + 1), np.zeros(n + 1)], np.c_[xs, np.ones(n + 1), xs * 0.01]])
    tris = [(i, i + 1, n + 1 + i) for i in range(n)] + [(i + 1, n + 2 + i, n + 1 + i) for i in range(n)]
    path.parent.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(verts, tris[:faces], process=False).export(path)
    return path


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _ax3d():
    return plt.figure(figsize=(3, 3), dpi=72).add_subplot(projection="3d")


def _face_rgb(coll):
    coll.axes.figure.canvas.draw()
    return np.round(coll.get_facecolor()[:, :3], 6)


# ---------------------------------------------------------------------------- reading files


def test_each_format_reads_its_triangles_and_a_scene_its_node_transforms(tmp_path):
    v, f, own = meshes.read_mesh(_pyramid_ply(tmp_path / "p.ply"))
    assert v.tolist() == [list(map(float, p)) for p in PYRAMID_V] and f.tolist() == [list(t) for t in PYRAMID_F]
    expected = [np.mean([PYRAMID_RGBA[i] for i in tri], axis=0) / 255 for tri in PYRAMID_F]
    assert np.allclose(own, expected), "per-face colours: the mean of each face's vertex colours"

    v, f, own = meshes.read_mesh(_tetra_obj(tmp_path / "t.obj"))
    assert (len(v), len(f), own) == (4, 4, None)
    v, f, own = meshes.read_mesh(_tetra_stl(tmp_path / "t.stl"))
    assert (len(v), len(f), own) == (12, 4, None), "an STL stores three vertices per facet; none are merged"

    v, f, own = meshes.read_mesh(_two_boxes_glb(tmp_path / "two.glb"))
    used = v[f].reshape(-1, 3)
    assert len(f) == 24 and own is None
    assert used.min(axis=0).tolist() == [-10.5, -1, -1.5] and used.max(axis=0).tolist() == [11, 20.5, 31.5]


def test_a_file_that_is_no_mesh_or_holds_no_triangles_is_refused(tmp_path):
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"not a mesh")
    with pytest.raises(IdofigError, match="bad.stl"):
        meshes.read_mesh(bad)
    with pytest.raises(IdofigError, match="a mesh is one of"):
        idf.mesh(_ax3d(), tmp_path / "x.npy")
    with pytest.raises(IdofigError, match="does not exist"):
        idf.mesh(_ax3d(), tmp_path / "missing.ply")


# ---------------------------------------------------------------------------- drawing


def test_a_mesh_needs_a_3d_axes(tmp_path):
    ax = plt.figure().subplots()
    with pytest.raises(IdofigError, match="3D axes"):
        idf.mesh(ax, _tetra_obj(tmp_path / "t.obj"))


def test_colour_precedence_scalars_then_color_then_the_file_then_grey(tmp_path):
    ply, stl = _pyramid_ply(tmp_path / "p.ply"), _tetra_stl(tmp_path / "t.stl")
    expected = sorted(map(tuple, np.round([np.mean([PYRAMID_RGBA[i] for i in t], axis=0)[:3] / 255
                                           for t in PYRAMID_F], 6)))
    assert sorted(map(tuple, _face_rgb(idf.mesh(_ax3d(), ply, shade=False)))) == expected
    assert np.allclose(_face_rgb(idf.mesh(_ax3d(), ply, color="#ff8000", shade=False)), [1, 128 / 255, 0], atol=1e-6)
    assert np.allclose(_face_rgb(idf.mesh(_ax3d(), stl, shade=False)), [200 / 255] * 3, atol=1e-6)

    per_vertex = idf.mesh(_ax3d(), ply, scalars=[0, 1, 2, 3, 4], color="red")
    assert np.allclose(per_vertex.get_array(), [np.mean(t) for t in PYRAMID_F]), "a vertex value, averaged per face"
    per_face = idf.mesh(_ax3d(), ply, scalars=[5, 4, 3, 2, 1, 0], cmap="gray", vmin=0, vmax=5, shade=False)
    assert np.allclose(per_face.get_array(), [5, 4, 3, 2, 1, 0])
    assert sorted(_face_rgb(per_face)[:, 0]) == pytest.approx([0, 0.2, 0.4, 0.6, 0.8, 1], abs=0.01)
    with pytest.raises(IdofigError, match="5 vertices and 6 faces"):
        idf.mesh(_ax3d(), ply, scalars=[1, 2, 3])


@pytest.mark.parametrize("elev", [90, 30, 0])
def test_the_headlight_follows_the_view(tmp_path, elev):
    """A triangle in z = 0 faces the viewer at elev 90 and is edge-on at 0: its grey is
    0.35 + 0.65·sin(elev) of #c8c8c8, recomputed at the draw from the view it is drawn with."""
    path = tmp_path / "tri.obj"
    path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="ascii")
    ax = _ax3d()
    coll = idf.mesh(ax, path)
    ax.view_init(elev=elev, azim=-60)
    assert _face_rgb(coll)[0] == pytest.approx([200 / 255 * (0.35 + 0.65 * np.sin(np.radians(elev)))] * 3, abs=1e-6)


def test_limits_and_box_follow_every_mesh_on_the_axes(tmp_path):
    ax = _ax3d()
    idf.mesh(ax, _pyramid_ply(tmp_path / "p.ply"))
    idf.mesh(ax, _tetra_obj(tmp_path / "t.obj"))  # x to 3: the union of the two
    lims = [ax.get_xlim3d(), ax.get_ylim3d(), ax.get_zlim3d()]
    lo, hi = [min(a[0] for a in lims), max(a[1] for a in lims)]
    extent = np.array([b - a for a, b in lims])
    assert lo < 1e-9 and hi > 3.9, "matplotlib's view margin may pad them; the bounds are inside"
    assert extent / extent[0] == pytest.approx(np.array([3, 4, 3]) / 3), "x, y and z on one scale (bounds 3 × 4 × 3)"
    aspect = np.asarray(ax._box_aspect)
    assert aspect / aspect[0] == pytest.approx(np.array([3, 4, 3]) / 3)


def test_more_faces_than_the_threshold_are_rasterized(tmp_path):
    big, small = _grid(tmp_path / "big.ply", meshes.MESH_VECTOR_FACES + 1), _grid(tmp_path / "s.ply", meshes.MESH_VECTOR_FACES)
    assert idf.mesh(_ax3d(), big).get_rasterized() and not idf.mesh(_ax3d(), small).get_rasterized()
    assert not idf.mesh(_ax3d(), big, rasterized=False).get_rasterized()


def _bumpy_sphere(path):
    """An icosphere (subdivision 3: 1280 faces, 642 shared vertices) with each vertex moved
    radially by a seeded 3 %: small irregular triangles, as on a cortical surface."""
    s = trimesh.creation.icosphere(subdivisions=3)
    scale = 1 + 0.03 * np.random.default_rng(0).standard_normal((len(s.vertices), 1))
    trimesh.Trimesh(s.vertices * scale, s.faces, process=False).export(path)
    return path


def _drawn(coll):
    return (np.array([p.vertices for p in coll.get_paths()]), np.array(coll._facecolors2d),
            np.array(coll._edgecolors2d))


@pytest.mark.parametrize("view", [(30, -60, "persp"), (-75, 200, "ortho")])
def test_the_projection_draws_what_matplotlibs_own_draws(tmp_path, view):
    """``MeshCollection._project`` is matplotlib's ``Poly3DCollection.do_3d_projection`` for
    whole triangles at once (before 3.11 that was a Python loop over every face): the same 2D
    triangles in the same order, the same colours and the same returned zorder. No two faces
    of this mesh are at the same depth, so every matplotlib orders them alike."""
    ax = _ax3d()
    coll = idf.mesh(ax, _bumpy_sphere(tmp_path / "s.ply"), color="#3070b0", alpha=0.8)
    ax.view_init(elev=view[0], azim=view[1])
    ax.set_proj_type(view[2])
    ax.figure.canvas.draw()
    assert coll._plain()
    zorder, ours = coll.do_3d_projection(), _drawn(coll)
    theirs_zorder = Poly3DCollection.do_3d_projection(coll)  # its lit colours are in _facecolor3d
    theirs = _drawn(coll)
    assert zorder == theirs_zorder and ours[0].shape == (1280, 4, 2)
    for mine, matplotlib_s in zip(ours, theirs):
        assert np.array_equal(mine, matplotlib_s)


def test_faces_of_equal_depth_are_drawn_in_the_files_order(tmp_path):
    """Seen square-on in an orthographic view every face of a flat mesh is at one depth;
    matplotlib 3.11 sorted them with an unstable argsort, whose order for a tie may differ by CPU."""
    path = tmp_path / "flat.ply"
    lines = ["ply", "format ascii 1.0", "element vertex 4", "property float x", "property float y", "property float z",
             "element face 4", "property list uchar int vertex_indices", "property uchar red",
             "property uchar green", "property uchar blue", "end_header",
             "0 0 0", "1 0 0", "1 1 0", "0 1 0",
             "3 0 1 2 10 0 0", "3 0 2 3 20 0 0", "3 0 1 3 30 0 0", "3 1 2 3 40 0 0"]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    ax = _ax3d()
    coll = idf.mesh(ax, path, shade=False)
    ax.view_init(elev=90, azim=0)
    ax.set_proj_type("ortho")
    ax.figure.canvas.draw()
    assert np.round(coll.get_facecolor()[:, 0] * 255).tolist() == [10, 20, 30, 40]


def _neighbour_steps(coll, faces):
    """|Δ light| across every edge two faces share."""
    light = coll._light()
    by_edge: dict = {}
    for f, tri in enumerate(faces):
        for e in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            by_edge.setdefault(tuple(sorted(e)), []).append(f)
    pairs = np.array([fs for fs in by_edge.values() if len(fs) == 2])
    return np.abs(light[pairs[:, 0]] - light[pairs[:, 1]])


def test_smooth_shading_varies_less_between_neighbours_and_leaves_unshared_faces_alone(tmp_path):
    sphere = _bumpy_sphere(tmp_path / "s.ply")
    faces = meshes.read_mesh(sphere)[1]
    steps = {}
    for smooth in (True, False):
        ax = _ax3d()
        coll = idf.mesh(ax, sphere, smooth=smooth)
        ax.figure.canvas.draw()
        steps[smooth] = _neighbour_steps(coll, faces)
    assert len(steps[True]) == 1920, "every edge of a closed 1280-face mesh is shared by two faces"
    assert steps[True].mean() < 0.5 * steps[False].mean(), (steps[True].mean(), steps[False].mean())

    stl = _tetra_stl(tmp_path / "t.stl")  # three vertices of its own per facet
    drawn = {}
    for smooth in (True, False):
        ax = _ax3d()
        drawn[smooth] = _face_rgb(idf.mesh(ax, stl, smooth=smooth))
    assert np.array_equal(drawn[True], drawn[False])


def test_import_idofig_imports_neither_matplotlib_nor_trimesh():
    code = ("import sys, idofig, idofig.build, idofig.serve, idofig.cli, idofig.compose, idofig.scaffold\n"
            "assert idofig.mesh.__module__ == 'idofig.meshes'\n"  # resolved lazily, it imports both
            "import idofig.meshes\nassert callable(idofig.mesh)\n")
    probe = ("import sys, idofig, idofig.build, idofig.serve, idofig.cli, idofig.compose, idofig.scaffold\n"
             "print(sorted(m for m in ('matplotlib', 'trimesh', 'mpl_toolkits') if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True).stdout
    assert out.strip() == "[]"
    subprocess.run([sys.executable, "-c", code], check=True)


# ---------------------------------------------------------------------------- simplification


def _area(verts, faces):
    t = np.asarray(verts)[np.asarray(faces)]
    return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2


def _colour_by_x(path):
    """The bumpy sphere with each vertex's red channel its x coordinate, from -1.1 to 1.1 over 0–255."""
    s = trimesh.load(_bumpy_sphere(path), process=False)
    red = np.round((s.vertices[:, 0] + 1.1) / 2.2 * 255)
    colours = np.c_[red, np.zeros((len(red), 2)), np.full(len(red), 255)].astype(np.uint8)
    trimesh.Trimesh(s.vertices, s.faces, vertex_colors=colours, process=False).export(path)
    return path


@pytest.mark.parametrize("colouring", ["per vertex", "per face", "file colours"])
def test_a_mesh_over_max_faces_is_drawn_simplified_and_its_values_follow_their_faces(tmp_path, colouring):
    path = _bumpy_sphere(tmp_path / "s.ply") if colouring != "file colours" else _colour_by_x(tmp_path / "s.ply")
    v, f, _ = meshes.read_mesh(path)
    kwargs = {"per vertex": {"scalars": v[:, 0]}, "per face": {"scalars": v[f][:, :, 0].mean(axis=1)},
              "file colours": {"shade": False}}[colouring]
    ax = _ax3d()
    coll = idf.mesh(ax, path, max_faces=400, **kwargs)
    info = coll._idofig_mesh
    drawn = coll._idofig_vec[:3].T.reshape(-1, 3, 3)  # the triangles drawn, in the order of their colours
    assert (info["file_faces"], info["file_vertices"]) == (1280, 642)
    assert 360 <= info["faces"] <= 400 and len(drawn) == info["faces"], "about max_faces, never more"
    assert info["vertices"] < 642
    if colouring == "file colours":
        values = coll._idofig_unlit[:, 0] * 2.2 - 1.1  # face order (a draw sorts them by depth)
    else:
        values = coll.get_array()
    err = np.abs(values - drawn[:, :, 0].mean(axis=1))
    assert err.mean() < 0.06 and err.max() < 0.3, (err.mean(), err.max())
    assert _area(drawn.reshape(-1, 3), np.arange(3 * len(drawn)).reshape(-1, 3)) == pytest.approx(_area(v, f), rel=0.03)


def test_simplifying_is_deterministic_and_none_draws_every_face(tmp_path):
    path = _bumpy_sphere(tmp_path / "s.ply")
    runs = [idf.mesh(_ax3d(), path, max_faces=400, scalars=np.arange(642.0)) for _ in range(2)]
    assert np.array_equal(runs[0]._idofig_vec, runs[1]._idofig_vec)
    assert np.array_equal(runs[0].get_array(), runs[1].get_array())
    whole = idf.mesh(_ax3d(), path, max_faces=None)._idofig_mesh
    assert (whole["faces"], whole["vertices"]) == (whole["file_faces"], whole["file_vertices"]) == (1280, 642)
    assert idf.mesh(_ax3d(), path, max_faces=1280)._idofig_mesh["faces"] == 1280, "at the limit: drawn whole"
    for bad in (0, -5, 2.5, True, "1000"):
        with pytest.raises(IdofigError, match="max_faces"):
            idf.mesh(_ax3d(), path, max_faces=bad)


def test_an_stl_is_simplified_over_merged_corners_without_holes(tmp_path):
    """An STL stores three vertices per facet: decimated as stored, no edge is shared and whole
    triangles go (31 % of the area was left); merged by position first, the surface stays."""
    s = trimesh.load(_bumpy_sphere(tmp_path / "s.ply"), process=False)
    stl = tmp_path / "s.stl"
    s.export(stl)
    v, f, _ = meshes.read_mesh(stl)
    assert len(v) == 3 * 1280
    coll = idf.mesh(_ax3d(), stl, max_faces=400)
    drawn = coll._idofig_vec[:3].T
    assert coll._idofig_mesh["faces"] <= 400
    assert _area(drawn, np.arange(len(drawn)).reshape(-1, 3)) == pytest.approx(_area(v, f), rel=0.03)


def test_mesh_simplify_writes_a_smaller_file_byte_for_byte_and_keeps_colours_where_it_can(tmp_path, capsys):
    src = _colour_by_x(tmp_path / "s.ply")
    a, b = tmp_path / "a.ply", tmp_path / "b.ply"
    assert cli.main(["mesh-simplify", str(src), str(a), "--faces", "400"]) == 0
    assert "from 1280 faces, 642 vertices" in capsys.readouterr().out
    assert cli.main(["mesh-simplify", str(src), str(b), "--faces", "400"]) == 0
    assert a.read_bytes() == b.read_bytes()
    small = trimesh.load(a, process=False)  # read back by trimesh, not by idofig
    assert 360 <= len(small.faces) <= 400 and small.visual.kind == "face"
    red = small.visual.face_colors[:, 0] / 255 * 2.2 - 1.1
    err = np.abs(red - small.vertices[small.faces][:, :, 0].mean(axis=1))
    assert err.mean() < 0.06 and err.max() < 0.3

    plain = _bumpy_sphere(tmp_path / "plain.ply")
    assert cli.main(["mesh-simplify", str(plain), str(tmp_path / "small.glb"), "--faces", "400"]) == 0
    assert len(meshes.read_mesh(tmp_path / "small.glb")[1]) <= 400
    capsys.readouterr()
    for args, message in (([str(src), str(src)], "is the file being simplified"),
                          ([str(src), str(tmp_path / "s.stl")], "only .ply keeps"),
                          ([str(src), str(tmp_path / "s.gltf")], "write .ply, .glb, .obj or .stl"),
                          ([str(tmp_path / "none.ply"), str(a)], "does not exist")):
        assert cli.main(["mesh-simplify", *args, "--faces", "400"]) == 2
        assert message in capsys.readouterr().err
    assert not (tmp_path / "s.stl").exists() and src.read_bytes() != a.read_bytes()


# ---------------------------------------------------------------------------- panels


MAKE = '''
import numpy as np
import idofig as idf
p = idf.panels("a", "b")
ax = p["a"].add_subplot(projection="3d"); idf.name(ax, "main")
idf.mesh(ax, "data/pyramid.ply", scalars=np.arange(5.0), cmap="inferno")
idf.mesh(ax, "data/cube.stl", name="Box Frame", alpha=0.5)
ax.set_axis_off()
bx = p["b"].add_subplot(projection="3d"); idf.name(bx, "main")
idf.mesh(bx, "data/grid.ply")
idf.save(p)
'''


@pytest.fixture
def mesh_project(project):
    _pyramid_ply(project.root / "data/pyramid.ply")
    trimesh.creation.box(extents=(2, 2, 2)).export(project.root / "data/cube.stl")  # its faces tie when seen edge-on
    _grid(project.root / "data/grid.ply", meshes.MESH_VECTOR_FACES + 1)
    (project.root / "figures/fig-1/make.py").write_text(MAKE, encoding="utf-8")
    S.update_figure(project.figure_json("fig-1"), [{"op": "producer.set", "id": "make",
                                                     "inputs": ["data/pyramid.ply", "data/cube.stl", "data/grid.ply"]}])
    return project


def _manifest(project, pid="a"):
    return json.loads(read(project.panel_dir("fig-1", pid) / "manifest.json"))


def _svg(project, pid="a"):
    return ET.fromstring(read(project.panel_dir("fig-1", pid) / "panel.svg"))


def _group(root, ident):
    return next(el for el in root.iter() if el.get("id") == ident)


def test_the_manifest_names_the_mesh_its_file_and_the_3d_axes_its_view(mesh_project):
    assert build(mesh_project).ok
    parts = _manifest(mesh_project)["parts"]
    pyramid, box, main = parts["main.mesh.pyramid"], parts["main.mesh.box-frame"], parts["main"]
    assert (pyramid["kind"], pyramid["role"], pyramid["stability"], pyramid["parent"]) == \
        ("collection", "mesh", "semantic", "main")
    assert pyramid["mesh"] == {"path": "data/pyramid.ply", "faces": 6, "vertices": 5, "file_faces": 6,
                               "file_vertices": 5, "bounds": [[0, 0, 0], [2, 4, 3]]}
    assert box["mesh"]["faces"] == 12 and box["mesh"]["bounds"] == [[-1, -1, -1], [1, 1, 1]]
    assert pyramid["props"]["cmap"] == "inferno" and box["props"]["alpha"] == 0.5
    assert pyramid["props"]["edgecolor"] == "none", "no stroke: the line-weight check has nothing to read"
    assert (main["role"], main["props"]["elev"], main["props"]["azim"], main["props"]["roll"]) == ("axes3d", 30, -60, 0)
    assert (main["props"]["zoom"], main["props"]["proj"]) == (1, "persp")
    m = _manifest(mesh_project)
    assert {"stage": "data", "parts": ["main.mesh.pyramid"], "entrance": "fade"} in m["build"]
    assert m["warnings"] == [] and m["style"]["invalid"] == []


def test_a_rasterized_mesh_keeps_its_name_at_print_resolution(mesh_project):
    assert build(mesh_project).ok
    root = _svg(mesh_project, "b")
    images = list(_group(root, "main.mesh.grid").iter(f"{SVG}image"))
    assert len(images) == 1 and len(list(root.iter(f"{SVG}image"))) == 1
    png = base64.b64decode(images[0].get("{http://www.w3.org/1999/xlink}href").split(",", 1)[1])
    width_px = struct.unpack(">I", png[16:20])[0]
    assert width_px / float(images[0].get("width")) * 72 == pytest.approx(600, rel=0.01), "savefig.dpi: 600"
    assert not list(_group(_svg(mesh_project), "main.mesh.pyramid").iter(f"{SVG}image")), "6 faces stay vector"


def test_the_view_is_set_by_name_before_the_draw(mesh_project):
    assert build(mesh_project).ok
    before = read(mesh_project.panel_dir("fig-1", "a") / "panel.svg")
    S.update_style(mesh_project.panel_dir("fig-1", "a") / "style.json", "main",
                   {"elev": 12.5, "azim": 140, "roll": -20, "zoom": 1.5, "proj": "ortho"})
    assert figure_status(mesh_project, "fig-1").panels[0].state == "stale"
    assert build(mesh_project).ok
    m = _manifest(mesh_project)
    main = m["parts"]["main"]
    assert {k: main["props"][k] for k in P.VIEW} == {"elev": 12.5, "azim": 140, "roll": -20, "zoom": 1.5, "proj": "ortho"}
    assert main["base"] == {"elev": 30, "azim": -60, "roll": 0, "zoom": 1, "proj": "persp"}
    assert m["style"]["applied"] == ["main"] and m["style"]["invalid"] == []
    assert read(mesh_project.panel_dir("fig-1", "a") / "panel.svg") != before


def test_the_headlight_lights_what_the_style_turns_to_the_front(project):
    """End to end: a grey triangle in z = 0 is drawn #c8c8c8 seen from above (elev 90) and
    #878787 (0.675 × 200 = 135) at elev 30."""
    (project.root / "data/tri.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="ascii")
    (project.root / "figures/fig-1/make.py").write_text(
        "import idofig as idf\np = idf.panels('a', 'b')\nfor f in p.values():\n"
        "    ax = f.add_subplot(projection='3d'); idf.name(ax, 'main'); idf.mesh(ax, 'data/tri.obj')\n"
        "idf.save(p)\n", encoding="utf-8")
    fills = {}
    for elev in (90, 30):
        S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main", {"elev": elev})
        assert build(project).ok
        path = next(_group(_svg(project), "main.mesh.tri").iter(f"{SVG}path"))
        fills[elev] = re.search(r"fill: (#[0-9a-f]{6})", path.get("style")).group(1)
    assert fills == {90: "#c8c8c8", 30: "#878787"}


def test_a_view_is_refused_on_a_2d_axes_and_a_colorbar(project):
    for role in ("axes", "colorbar"):
        assert P.validate("axes", {"elev": 10, "proj": "ortho"}, role=role) == \
            ["elev: only a 3D axes has a view", "proj: only a 3D axes has a view"]
    assert P.validate("axes", {"elev": 10, "azim": -180, "roll": 180, "zoom": 2, "proj": "persp"}, role="axes3d") == []
    assert P.validate("axes", {"elev": 181, "zoom": 0, "proj": "fish"}, role="axes3d") == [
        "elev must be ≤ 180", "zoom must be ≥ 0.1", "proj must be one of ['ortho', 'persp']"]
    assert P.describe()["refused_by_role"]["axes"] == sorted(P.VIEW) == P.describe()["refused_by_role"]["colorbar"]
    assert P.describe()["kinds"]["axes"]["proj"] == {"type": "enum", "options": ["ortho", "persp"]}

    # conftest's panels are 2D: the build reports the entry invalid and draws as before
    assert build(project).ok
    drawn = read(project.panel_dir("fig-1", "a") / "panel.svg")
    S.update_style(project.panel_dir("fig-1", "a") / "style.json", "main", {"elev": 10})
    assert build(project).ok
    assert [(i["part"], i["prop"]) for i in _manifest(project)["style"]["invalid"]] == [("main", "elev")]
    assert read(project.panel_dir("fig-1", "a") / "panel.svg") == drawn
    srv = Server(project, out=io.StringIO())
    out = io.StringIO()
    srv.out = out
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "update_style",
                  "params": {"figure": "fig-1", "panel": "a", "part": "main", "props": {"azim": 10}}})
    assert "only a 3D axes has a view" in json.loads(out.getvalue().splitlines()[-1])["error"]["data"]["problems"][0]


def test_a_mesh_panel_rebuilds_byte_for_byte(mesh_project):
    S.update_style(mesh_project.panel_dir("fig-1", "a") / "style.json", "main", {"elev": 0, "azim": 0})  # ties
    assert build(mesh_project).ok
    d = mesh_project.figure_dir("fig-1")
    before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert build(mesh_project, force=True).ok
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == before


def test_a_simplified_mesh_panel_rebuilds_byte_for_byte(project):
    _bumpy_sphere(project.root / "data/s.ply")
    (project.root / "figures/fig-1/make.py").write_text(
        "import numpy as np\nimport idofig as idf\np = idf.panels('a', 'b')\nfor f in p.values():\n"
        "    ax = f.add_subplot(projection='3d'); idf.name(ax, 'main')\n"
        "    idf.mesh(ax, 'data/s.ply', scalars=np.arange(642.0), max_faces=400)\nidf.save(p)\n", encoding="utf-8")
    assert build(project).ok
    m = _manifest(project)["parts"]["main.mesh.s"]["mesh"]
    assert (m["file_faces"], m["file_vertices"]) == (1280, 642) and m["faces"] <= 400
    d = project.figure_dir("fig-1")
    before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert build(project, force=True).ok
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == before


def test_editing_the_mesh_file_makes_its_panel_stale(mesh_project):
    assert build(mesh_project).ok
    (mesh_project.root / "data/pyramid.ply").write_text(
        read(mesh_project.root / "data/pyramid.ply").replace("1 2 3 0 0 0 255", "1 2 5 0 0 0 255"))
    state = {p.id: (p.state, p.reasons) for p in figure_status(mesh_project, "fig-1").panels}
    assert state["a"][0] == "stale" and any("data/pyramid.ply changed" in r for r in state["a"][1])


# ---------------------------------------------------------------------------- scaffold


def test_add_panel_scaffolds_a_mesh_producer_that_builds(project):
    _tetra_stl(project.root / "data/head.stl")
    res = add_panel(project, "fig-1", "brain", mesh="data/head.stl")
    assert res["created"] == "figures/fig-1/brain.py"
    producer = next(p for p in S.load_figure(project.figure_json("fig-1"))["producers"] if p["id"] == "brain")
    assert producer["inputs"] == ["data/head.stl"] and producer["run"] == ["python", "figures/fig-1/brain.py"]
    assert "idf.mesh(ax, 'data/head.stl')" in read(project.root / res["created"])
    assert build(project).ok
    m = _manifest(project, "brain")
    assert m["parts"]["main"]["role"] == "axes3d" and m["parts"]["main.mesh.head"]["mesh"]["faces"] == 4
    assert m["parts"]["main.xaxis"]["drawn"] is False, "the template turns the axes off"


def test_add_panel_mesh_through_the_cli_and_the_server_and_its_refusals(project):
    _tetra_obj(project.root / "data/t.obj")
    assert cli.main(["add-panel", "fig-1", "m1", "--template", "mesh", "--mesh", "data/t.obj"]) == 0
    srv = Server(project, out=io.StringIO())
    out = io.StringIO()
    srv.out = out
    srv.dispatch({"jsonrpc": "2.0", "id": 1, "method": "add_panel",
                  "params": {"figure": "fig-1", "panel": "m2", "template": "mesh", "mesh": "data/t.obj"}})
    assert json.loads(out.getvalue().splitlines()[-1])["result"]["created"] == "figures/fig-1/m2.py"
    inputs = {p["id"]: p["inputs"] for p in S.load_figure(project.figure_json("fig-1"))["producers"]}
    assert inputs["m1"] == inputs["m2"] == ["data/t.obj"]

    (project.root / "data/x.npy").write_bytes(b"")
    for kwargs, message in (({"template": "mesh"}, "needs a mesh file"),
                            ({"template": "bar", "mesh": "data/t.obj"}, "needs a mesh file"),
                            ({"mesh": "data/x.npy"}, "a mesh is one of"),
                            ({"mesh": "data/none.ply"}, "does not exist"),
                            ({"mesh": "../outside.ply"}, "outside the project")):
        with pytest.raises(IdofigError, match=message):
            add_panel(project, "fig-1", "m3", **kwargs)
