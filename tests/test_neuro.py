"""Raster renders and neuroscience panels (idofig 0.13.0, 2026-10-11): ``idofig.image`` places a
render at its own resolution, cropped and bled; ``idofig.neuro`` draws a topomap (mne), a cortical
surface (an idofig mesh) and a volume slice (nibabel), each part named by what it is.

Where the expected numbers come from: every image, surface and volume is made in the test. The
bled colours are the nearest drawn pixel's, counted by hand on a 1 × 5 and a 5 × 5 image. A
fitted image's box is the box's aspect against the image's (a 300 × 100 image in 40 × 40 mm is
40 × 13.33 mm, centred: 13.33 mm up). Surface views are checked against the camera's geometry,
not against VIEWS: looking along +x (from the subject's left) with z up, the screen's right is
d × up = x × z = −y, so anterior (+y) is on the left of a left lateral view and on the right of a
medial one. A slice's orientation is checked with one voxel set at a known position in mm: the
volume is stored with x flipped (LAS), so the voxel's index and its position disagree; the
neurological slice must still put x > 0 on the right. A topomap's head radius is mne's sphere
radius (0.095 m, its default for a montage with positions); its dots are the mask's channels.

Reproduce: `.venv/bin/python -m pytest tests/test_neuro.py` (needs the test extra: mne, nibabel).
"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from conftest import read  # noqa: E402

import idofig as idf  # noqa: E402
from idofig import neuro, rasters  # noqa: E402
from idofig import spec as S  # noqa: E402
from idofig.build import build  # noqa: E402
from idofig.errors import IdofigError  # noqa: E402
from idofig.naming import assign_structural  # noqa: E402
from idofig.scaffold import add_panel  # noqa: E402

mne = pytest.importorskip("mne")
nib = pytest.importorskip("nibabel")
trimesh = pytest.importorskip("trimesh")

SVG = "{http://www.w3.org/2000/svg}"
CHANNELS = ["Fp1", "Fpz", "Fp2", "F3", "Fz", "F4", "C3", "Cz", "C4", "P3", "Pz", "P4", "O1", "Oz", "O2"]


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def _names(fig) -> dict:
    return {n: p for n, p in assign_structural(fig).parts.items()}


def _info():
    info = mne.create_info(CHANNELS, 250.0, "eeg")
    info.set_montage(mne.channels.make_standard_montage("easycap-M1"))
    return info


def _hemisphere(path, subdivisions=3):
    """An ellipsoid left of the midline as a FreeSurfer surface, and its vertices."""
    s = trimesh.creation.icosphere(subdivisions=subdivisions)
    verts = (s.vertices * [30, 70, 50] + [-35, -10, 10]).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.freesurfer.write_geometry(str(path), verts, s.faces.astype(np.int32))
    return verts, s.faces


def _volume(path, shape=(21, 25, 19), step=2.0, origin=(-20.0, -24.0, -18.0), flip_x=False, value=None):
    """A volume of zeros on a ``step`` mm grid whose voxel 0 sits at ``origin`` (mm); ``value``
    {(x, y, z) mm: v} sets voxels. With ``flip_x`` it is stored LAS (x falls with the index)."""
    data = np.zeros(shape, dtype=np.float32)
    aff = np.diag([step, step, step, 1.0])
    aff[:3, 3] = origin
    for (x, y, z), v in (value or {}).items():
        data[tuple(int(round((c - o) / step)) for c, o in zip((x, y, z), origin))] = v
    if flip_x:
        data = data[::-1]
        aff = aff @ np.array([[-1, 0, 0, shape[0] - 1], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1.0]])
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, aff), str(path))
    return path


# ---------------------------------------------------------------------------- rasters


def test_crop_alpha_keeps_what_was_drawn_plus_its_pad():
    rgba = np.zeros((6, 8, 4))
    rgba[2:4, 3:6] = [1, 0, 0, 1]
    assert rasters.crop_alpha(rgba).shape == (2, 3, 4)
    assert rasters.crop_alpha(rgba, pad=1).shape == (4, 5, 4)
    assert rasters.crop_alpha(rgba, pad=5).shape == (6, 8, 4), "never past the image"
    assert rasters.crop_alpha(np.zeros((3, 3, 4))).shape == (3, 3, 4), "nothing drawn: as it is"
    assert rasters.crop_alpha(np.ones((3, 3, 3))).shape == (3, 3, 3), "no alpha: as it is"


def test_bleed_gives_transparent_pixels_the_nearest_drawn_colour_and_keeps_alpha():
    row = np.zeros((1, 5, 4))
    row[0, 0] = [1, 0, 0, 1]
    row[0, 4] = [0, 0, 1, 0.5]
    out = rasters.bleed(row)
    assert out[0, :, :3].tolist() == [[1, 0, 0], [1, 0, 0], [1, 0, 0], [0, 0, 1], [0, 0, 1]], "a tie goes left"
    assert out[..., 3].tolist() == row[..., 3].tolist()

    square = np.zeros((5, 5, 4))
    square[0, 0] = [0, 1, 0, 1]
    out = rasters.bleed(square)
    assert (out[..., :3] == [0, 1, 0]).all(), "rows and columns with nothing drawn are filled from the rest"
    assert out[..., 3].sum() == 1


def test_an_image_fits_its_box_centred_with_its_aspect_and_its_own_pixels(tmp_path):
    png = tmp_path / "r.png"
    pixels = np.zeros((40, 340, 4))
    pixels[10:30, 20:320] = [0.9, 0.6, 0.2, 1]  # 300 × 20 drawn in a 340 × 40 transparent frame
    plt.imsave(png, pixels)
    fig = plt.figure(figsize=(40 / 25.4, 40 / 25.4), dpi=72)
    ax = idf.image(fig, png, 0, 0, 40, 40, name="render")
    x0, y0, w, h = (v * 40 for v in ax.get_position().bounds)
    assert (w, h) == pytest.approx((40, 40 * 20 / 300)), "cropped to 300 × 20, then fitted"
    assert (x0, y0) == pytest.approx((0, (40 - h) / 2))
    img = ax.images[0]
    assert img.get_array().shape[:2] == (20, 300) and img.get_interpolation() == "none"
    names = _names(fig)
    assert names["render"].stability == "named" and names["render.image"].role == "image"
    assert names["render.image"].stability == "semantic"
    with pytest.raises(IdofigError, match="does not exist"):
        idf.image(fig, tmp_path / "missing.png", 0, 0, 10, 10, name="x")
    with pytest.raises(IdofigError, match="positive width"):
        idf.image(fig, png, 0, 0, 0, 10, name="x")


# ---------------------------------------------------------------------------- topomap


def test_a_topomap_names_its_field_outlines_and_dots():
    fig = plt.figure(figsize=(1.5, 1.5), dpi=72)
    ax = idf.name(fig.add_axes((0, 0, 1, 1)), "topo")
    values = np.linspace(-2, 3, len(CHANNELS))
    with plt.rc_context({"axes.linewidth": 0.4}):
        im = neuro.topomap(ax, values, _info(), mask=[CHANNELS.index("Cz"), CHANNELS.index("Pz")])
    names = _names(fig)
    for part, role in (("field", "image"), ("head", "outline"), ("nose", "outline"), ("ear.left", "outline"),
                       ("ear.right", "outline"), ("mask", "line")):
        assert names[f"topo.{part}"].role == role and names[f"topo.{part}"].stability == "semantic", part
    assert names["topo.field"].artists[0] is im
    assert im.get_clim() == (-3, 3), "± the largest |value|, centred on zero"
    mask = names["topo.mask"].artists[0]
    assert len(mask.get_xdata()) == 2 and mask.get_markersize() == pytest.approx(0.8 * 72 / 25.4)
    assert names["topo.head"].artists[0].get_linewidth() == 0.4, "the rc's axes.linewidth"
    left, right = (np.mean(names[f"topo.ear.{s}"].artists[0].get_xdata()) for s in ("left", "right"))
    assert left < 0 < right
    clip = im.get_clip_path()
    head_x = names["topo.head"].artists[0].get_xdata()
    assert clip is not None and (head_x.max() - head_x.min()) / 2 == pytest.approx(0.095, rel=0.01)


def test_a_topomap_draws_sensors_and_contours_when_asked_and_refuses_a_bad_mask():
    fig = plt.figure()
    ax = idf.name(fig.add_axes((0, 0, 1, 1)), "topo")
    neuro.topomap(ax, np.arange(len(CHANNELS), dtype=float), _info(), sensors=True, contours=3)
    names = _names(fig)
    assert "topo.sensors" in names and "topo.contours" in names and "topo.mask" not in names
    with pytest.raises(IdofigError, match="15 channels"):
        neuro.topomap(fig.add_axes((0, 0, 1, 1)), np.zeros(15), _info(), mask=np.ones(3, bool))
    with pytest.raises(IdofigError, match="outside"):
        neuro.topomap(fig.add_axes((0, 0, 1, 1)), np.zeros(15), _info(), mask=[15])


# ---------------------------------------------------------------------------- surface


def _screen_x(ax, point):
    from mpl_toolkits.mplot3d import proj3d

    ax.figure.canvas.draw()
    return proj3d.proj_transform(*point, ax.get_proj())[0]


@pytest.mark.parametrize("view, anterior_on", [("lateral", "left"), ("medial", "right")])
def test_a_left_hemisphere_faces_the_camera_its_view_names(tmp_path, view, anterior_on):
    surf = tmp_path / "lh.inflated"
    _hemisphere(surf)
    ax = plt.figure(figsize=(2, 2)).add_subplot(projection="3d")
    idf.name(ax, "brain")
    coll = neuro.surface(ax, surf, view=view)
    front, back = _screen_x(ax, (-35, 60, 10)), _screen_x(ax, (-35, -80, 10))
    assert (front < back) == (anterior_on == "left")
    assert _names(ax.figure)["brain.mesh.left"].artists[0] is coll, "named by its hemisphere, from lh.*"
    assert not ax.axison


def test_a_surface_shows_its_anatomy_below_threshold_and_its_values_above(tmp_path):
    surf = tmp_path / "lh.white"
    verts, faces = _hemisphere(surf, subdivisions=2)
    values = verts[:, 1] / 10.0  # anterior positive
    sulc = np.where(verts[:, 2] > 10, 1.0, -1.0)  # a "sulcus" above z = 10
    ax = plt.figure().add_subplot(projection="3d")
    coll = neuro.surface(ax, surf, values, sulc=sulc, threshold=2.0, cmap="Reds", vmin=0, vmax=8, shade=False,
                         view="dorsal")
    ax.figure.canvas.draw()
    below = (np.abs(values) < 2)[faces].any(axis=1)  # a vertex under the threshold hides its faces
    face_v = values[faces].mean(axis=1)
    face_s = sulc[faces].mean(axis=1)
    shown = np.ma.getdata(coll.get_array())
    assert np.isnan(shown[below]).all() and np.allclose(shown[~below], face_v[~below])
    rgb = coll._facecolor3d[:, :3]
    assert np.allclose(rgb[below & (face_s > 0)], [140 / 255] * 3), "a sulcus: #8c8c8c"
    assert np.allclose(rgb[below & (face_s <= 0)], [200 / 255] * 3), "a gyrus: #c8c8c8"
    above = ~below
    assert np.allclose(rgb[above], plt.get_cmap("Reds")(np.clip(face_v[above] / 8, 0, 1))[:, :3])


def test_a_mesh_background_colours_only_the_faces_whose_value_is_nan(tmp_path):
    path = tmp_path / "two.obj"  # two triangles side by side in z = 0
    path.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nv 1 1 0\nf 1 2 3\nf 2 4 3\n", encoding="ascii")
    ax = plt.figure().add_subplot(projection="3d")
    coll = idf.mesh(ax, path, scalars=[np.nan, 1.0], cmap="gray", vmin=0, vmax=1, shade=False,
                    background="#ff0000")
    ax.figure.canvas.draw()
    assert sorted(map(tuple, np.round(coll._facecolor3d[:, :3], 6))) == [(1, 0, 0), (1, 1, 1)]
    with pytest.raises(IdofigError, match="needs scalars"):
        idf.mesh(plt.figure().add_subplot(projection="3d"), path, background="red")
    with pytest.raises(IdofigError, match="one per face"):
        idf.mesh(plt.figure().add_subplot(projection="3d"), path, scalars=[1.0, 2.0], background=[(1, 0, 0, 1)] * 3)


def test_a_surface_reads_per_vertex_files_and_refuses_what_does_not_fit(tmp_path):
    surf = tmp_path / "surf.inflated"
    verts, _ = _hemisphere(surf, subdivisions=1)
    nib.freesurfer.write_morph_data(str(tmp_path / "x.curv"), verts[:, 0].astype(np.float32))
    ax = plt.figure().add_subplot(projection="3d")
    coll = neuro.surface(ax, surf, tmp_path / "x.curv", hemi="left", name="cortex")
    assert np.isfinite(coll.get_array()).all() and coll._idofig_mesh["name"] == "cortex"
    with pytest.raises(IdofigError, match="needs the hemisphere"):
        neuro.surface(plt.figure().add_subplot(projection="3d"), surf, view="lateral")
    with pytest.raises(IdofigError, match=f"{len(verts)} vertices"):
        neuro.surface(plt.figure().add_subplot(projection="3d"), surf, np.zeros(3), view="dorsal")
    with pytest.raises(IdofigError, match="3D axes"):
        neuro.surface(plt.figure().subplots(), surf, view="dorsal")
    with pytest.raises(IdofigError, match="unknown view"):
        neuro.surface(plt.figure().add_subplot(projection="3d"), surf, view="sideways")


# ---------------------------------------------------------------------------- slices


def test_a_slice_is_neurological_whatever_order_the_file_stores_x_in(tmp_path):
    anat = _volume(tmp_path / "anat.nii.gz", value={(10.0, 0.0, 0.0): 5.0}, flip_x=True)
    stored = nib.load(str(anat))
    assert nib.aff2axcodes(stored.affine)[0] == "L", "the file runs x right to left"
    fig = plt.figure()
    ax = idf.name(fig.add_axes((0, 0, 1, 1)), "axial")
    im = neuro.volume_slice(ax, anat, axis="z", at=0.0, anatomy_limits=(0, 5))
    rows, cols = np.nonzero(im.get_array() == 5)
    x0, x1, y0, y1 = im.get_extent()
    x = x0 + (cols[0] + 0.5) * (x1 - x0) / im.get_array().shape[1]
    assert x == pytest.approx(10.0) and ax.get_xlim()[0] < ax.get_xlim()[1], "x > 0 on the right"

    rad = idf.name(fig.add_axes((0, 0, 1, 1)), "rad")
    neuro.volume_slice(rad, anat, axis="z", at=0.0, radiological=True)
    assert rad.get_xlim()[0] > rad.get_xlim()[1]


def test_volumes_on_different_grids_overlay_in_mm_and_the_overlay_hides_what_it_should(tmp_path):
    anat = _volume(tmp_path / "anat.nii.gz", value={(0.0, 0.0, 0.0): 1.0})
    over = _volume(tmp_path / "t.nii.gz", shape=(15, 17, 13), step=3.0, origin=(-21.0, -24.0, -18.0),
                   value={(9.0, 0.0, 0.0): 4.0, (-9.0, 0.0, 0.0): 1.0, (0.0, 0.0, 0.0): np.nan})
    roi = _volume(tmp_path / "roi.nii.gz", shape=(15, 17, 13), step=3.0, origin=(-21.0, -24.0, -18.0),
                  value={(9.0, 0.0, 0.0): 1.0})
    fig = plt.figure()
    ax = idf.name(fig.add_axes((0, 0, 1, 1)), "axial")
    im = neuro.volume_slice(ax, anat, axis="z", at=0.5, overlay=over, threshold=2.0, vmin=-4, vmax=4, roi=roi)
    assert im.get_extent() == pytest.approx((-22.5, 22.5, -25.5, 25.5)), "voxel edges, in mm"
    assert ax.get_xlim() == pytest.approx((-21, 21)), "the anatomy frames the slice"
    shown = im.get_array()
    assert shown.count() == 1, "4 shows; 1 is under the threshold, NaN and 0 are hidden"
    names = _names(fig)
    assert {"axial.anatomy", "axial.overlay", "axial.roi"} <= set(names)
    assert names["axial.roi"].artists[0].get_linewidths()[0] == plt.rcParams["axes.linewidth"]
    with pytest.raises(IdofigError, match="outside"):
        neuro.volume_slice(fig.add_axes((0, 0, 1, 1)), anat, axis="z", at=40.0)
    with pytest.raises(IdofigError, match="mask must be on the overlay's grid"):
        neuro.volume_slice(fig.add_axes((0, 0, 1, 1)), overlay=over, mask=anat, axis="z")
    with pytest.raises(IdofigError, match="axis is"):
        neuro.volume_slice(fig.add_axes((0, 0, 1, 1)), anat, axis="w")


def test_an_oblique_volume_is_refused(tmp_path):
    aff = np.eye(4)
    aff[:2, :2] = [[np.cos(0.3), -np.sin(0.3)], [np.sin(0.3), np.cos(0.3)]]
    nib.save(nib.Nifti1Image(np.zeros((4, 4, 4), np.float32), aff), str(tmp_path / "o.nii.gz"))
    with pytest.raises(IdofigError, match="oblique"):
        neuro.volume_slice(plt.figure().subplots(), tmp_path / "o.nii.gz")


# ---------------------------------------------------------------------------- imports


def test_import_idofig_neuro_imports_neither_mne_nor_nibabel():
    probe = ("import sys, idofig, idofig.neuro\n"
             "print(sorted(m for m in ('mne', 'nibabel', 'matplotlib') if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", probe], check=True, capture_output=True, text=True).stdout
    assert out.strip() == "[]"
    code = ("from idofig import neuro\nassert neuro.topomap.__module__ == 'idofig.neuro.eeg'\n"
            "assert neuro.topomap is neuro.topomap and callable(neuro.surface)\n")
    subprocess.run([sys.executable, "-c", code], check=True)


# ---------------------------------------------------------------------------- panels


MAKE = '''
import mne
import numpy as np
import idofig as idf
from idofig import neuro
p = idf.panels("a", "b", layout=None)
info = mne.create_info({channels!r}, 250.0, "eeg")
info.set_montage(mne.channels.make_standard_montage("easycap-M1"))
ax = idf.name(idf.axes_mm(p["a"], 2, 2, 30, 30), "topo")
im = neuro.topomap(ax, np.linspace(-1, 1, {n}), info, mask=[0, 1])
idf.colorbar(im, name="t", cax=idf.axes_mm(p["a"], 36, 5, 1.5, 20))
idf.image(p["a"], "data/render.png", 50, 2, 30, 30, name="render")
ax = p["b"].add_axes((0, 0, 0.5, 1), projection="3d"); idf.name(ax, "lh")
neuro.surface(ax, "data/lh.inflated", np.load("data/t.npy"), threshold=0.5, vmin=-2, vmax=2)
ax = idf.name(idf.axes_mm(p["b"], 46, 2, 30, 30), "axial")
neuro.volume_slice(ax, "data/anat.nii.gz", axis="z", at=0, overlay="data/t.nii.gz", vmin=-4, vmax=4)
idf.save(p)
'''


@pytest.fixture
def neuro_project(project):
    root = project.root
    verts, _ = _hemisphere(root / "data/lh.inflated", subdivisions=2)
    np.save(root / "data/t.npy", verts[:, 1] / 30.0)
    _volume(root / "data/anat.nii.gz", value={(0.0, 0.0, 0.0): 1.0})
    _volume(root / "data/t.nii.gz", value={(4.0, 2.0, 0.0): 3.0})
    rgba = np.zeros((30, 50, 4))
    rgba[5:25, 5:45] = [0.2, 0.4, 0.8, 1]
    plt.imsave(root / "data/render.png", rgba)
    (root / "figures/fig-1/make.py").write_text(MAKE.format(channels=CHANNELS, n=len(CHANNELS)), encoding="utf-8")
    S.update_figure(project.figure_json("fig-1"), [{"op": "producer.set", "id": "make", "inputs": [
        "data/lh.inflated", "data/t.npy", "data/anat.nii.gz", "data/t.nii.gz", "data/render.png"]}])
    return project


def test_a_neuro_panel_names_its_parts_rebuilds_byte_for_byte_and_records_what_drew_it(neuro_project):
    assert build(neuro_project).ok
    d = neuro_project.figure_dir("fig-1")
    a = json.loads(read(d / "panels/a/manifest.json"))
    b = json.loads(read(d / "panels/b/manifest.json"))
    assert {"topo.field", "topo.head", "topo.nose", "topo.mask", "render.image"} <= set(a["parts"])
    assert {"lh.mesh.left", "axial.anatomy", "axial.overlay"} <= set(b["parts"])
    assert b["parts"]["lh.mesh.left"]["mesh"]["path"] == "data/lh.inflated"
    steps = [s["parts"] for s in a["build"]]
    assert any("topo.head" in s for s in steps if len(s) > 1), "an outline is scaffold, revealed first"
    lock = json.loads(read(d / "figure.lock.json"))
    built = lock["producers"]["make"]["built_with"]
    assert built["mne"] == mne.__version__ and built["nibabel"] == nib.__version__

    root = ET.fromstring(read(d / "panels/a/panel.svg"))
    image = next(el for el in root.iter() if el.get("id") == "render.image")
    png = base64.b64decode(next(image.iter(f"{SVG}image")).get("{http://www.w3.org/1999/xlink}href").split(",", 1)[1])
    assert struct.unpack(">II", png[16:24]) == (40, 20), "the render's own pixels, cropped, never resampled"

    before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert build(neuro_project, force=True).ok
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == before


def test_a_style_override_restyles_a_named_topomap_part(neuro_project):
    S.update_style(neuro_project.panel_dir("fig-1", "a") / "style.json", "topo.head", {"color": "#ff0000"})
    S.update_style(neuro_project.panel_dir("fig-1", "a") / "style.json", "topo.field", {"cmap": "viridis"})
    assert build(neuro_project).ok
    m = json.loads(read(neuro_project.panel_dir("fig-1", "a") / "manifest.json"))
    assert m["style"]["detached"] == [] and m["style"]["invalid"] == []
    assert m["parts"]["topo.head"]["props"]["color"] == "#ff0000"


def test_add_panel_scaffolds_a_topomap_producer_that_builds(project):
    res = add_panel(project, "fig-1", "eeg", template="topomap")
    assert "neuro.topomap(ax" in read(project.root / res["created"])
    assert build(project).ok
    parts = json.loads(read(project.panel_dir("fig-1", "eeg") / "manifest.json"))["parts"]
    assert {"main.field", "main.head", "main.mask", "cbar.value"} <= set(parts)


# ---------------------------------------------------------------------------- views, outlines, parcels (2)


def _ink_box(fig):
    """The drawn (non-white) pixels' box, x0, y0 from the bottom, x1, y1, in pixels."""
    fig.canvas.draw()
    rgba = np.asarray(fig.canvas.buffer_rgba())
    rows, cols = np.nonzero((rgba[..., :3] < 250).any(axis=-1))
    h = rgba.shape[0]
    return cols.min(), h - rows.max() - 1, cols.max(), h - rows.min() - 1


@pytest.mark.parametrize("view", ["lateral", "ventral", "anterior"])
def test_an_axes_sized_by_view_size_is_filled_by_the_fitted_surface(tmp_path, view):
    """Measured on the drawn pixels, not on the projection fit computes: an axes the shape of the
    surface's silhouette is filled to FIT (98 %) along both sides."""
    surf = tmp_path / "lh.white"
    _hemisphere(surf, subdivisions=3)
    w, h = neuro.view_size(surf, view)
    fig = plt.figure(figsize=(4, 4), dpi=100)
    scale = 3.0 / max(w, h)  # inches per mm of brain: the larger side 3 in
    ax = fig.add_axes((0.5 / 4, 0.5 / 4, w * scale / 4, h * scale / 4), projection="3d")
    neuro.surface(ax, surf, view=view, shade=False)
    x0, y0, x1, y1 = _ink_box(fig)
    assert (x1 - x0 + 1) / (w * scale * 100) == pytest.approx(0.98, abs=0.02), "the box it was placed in"
    assert (y1 - y0 + 1) / (h * scale * 100) == pytest.approx(0.98, abs=0.02)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((50 + w * scale * 50, 50 + h * scale * 50), abs=2)
    assert ax.get_position().width * 4 == pytest.approx(max(w, h) * scale), "the square a 3D axes draws in"


def test_surface_views_lay_out_every_view_at_one_scale(tmp_path):
    lh, rh = tmp_path / "lh.white", tmp_path / "rh.white"
    _hemisphere(lh, subdivisions=2)
    verts, faces = _hemisphere(rh, subdivisions=2)
    nib.freesurfer.write_geometry(str(rh), (verts * [-1, 1, 1]).astype(np.float32), faces[:, ::-1].astype(np.int32))
    fig = plt.figure(figsize=(120 / 25.4, 40 / 25.4))
    axes, scale = neuro.surface_views(fig, 0, 0, 120, 40, {"left": lh, "right": rh}, tags=True,
                                      views=(("left", "lateral"), ("right", "medial"), ("both", "ventral")))
    cells = []
    for ax, (which, view) in zip(axes, (("left", "lateral"), ("right", "medial"), ("both", "ventral"))):
        files = [lh, rh] if which == "both" else [lh if which == "left" else rh]
        w, h = neuro.view_size(files, view, None if which == "both" else which)
        box = ax._idofig_fit_box  # the cell each view fills
        assert (box.width * 120, box.height * 40) == pytest.approx((w * scale, h * scale))
        cells.append((box.x0 * 120, box.x1 * 120))
    names = _names(fig)
    assert {"brain.left.lateral.mesh.left", "brain.right.medial.mesh.right", "brain.both.ventral.mesh.left",
            "brain.both.ventral.mesh.right", "brain.left.lateral.tag"} <= set(names)
    assert names["brain.left.lateral.tag"].artists[0].get_text() == "L lat"
    assert [b[0] - a[1] for a, b in zip(cells, cells[1:])] == pytest.approx([1.5, 1.5]), "1.5 mm apart"
    widths = sum(b - a for a, b in cells) + 3
    tallest = max(ax._idofig_fit_box.height * 40 for ax in axes)
    assert widths == pytest.approx(120) or tallest == pytest.approx(40), "as large as fits"


def test_an_outline_draws_the_faces_on_a_regions_border(tmp_path):
    surf = tmp_path / "lh.white"
    verts, faces = _hemisphere(surf, subdivisions=2)
    region = verts[:, 1] > 0  # the anterior half
    ax = plt.figure().add_subplot(projection="3d")
    coll = neuro.surface(ax, surf, verts[:, 2], outline=region, outline_color="#ff0000", cmap="gray",
                         shade=False, view="dorsal")
    ax.figure.canvas.draw()
    count = region[faces].sum(axis=1)
    ring = (count > 0) & (count < 3)
    rgb = coll._facecolor3d[:, :3]
    assert ring.any() and np.allclose(rgb[ring], [1, 0, 0])
    assert not np.isclose(rgb[~ring], [1, 0, 0], atol=0.05).all(axis=1).any(), "no other face is the outline's red"


def test_parcel_values_spread_one_value_per_parcel_and_refuse_an_unknown_one(tmp_path):
    labels = np.array([0, 0, 1, 2, 1, -1])
    ctab = np.array([[25, 5, 25, 0, 0], [220, 20, 10, 0, 0], [20, 220, 60, 0, 0]])
    nib.freesurfer.write_annot(str(tmp_path / "lh.aparc.annot"), labels, ctab, [b"unknown", b"insula", b"precuneus"],
                               fill_ctab=True)
    out = neuro.parcel_values(tmp_path / "lh.aparc.annot", {"insula": 2.5, "precuneus": -1.0})
    assert np.array_equal(np.isnan(out), [True, True, False, False, False, True])
    assert out[[2, 3, 4]].tolist() == [2.5, -1.0, 2.5]
    with pytest.raises(IdofigError, match="no parcel 'caudate'"):
        neuro.parcel_values(tmp_path / "lh.aparc.annot", {"caudate": 1.0})


# ---------------------------------------------------------------------------- volumes (2)


def test_centroid_finds_a_blobs_centre_on_the_side_asked(tmp_path):
    vol = _volume(tmp_path / "roi.nii.gz", value={(-10.0, 0.0, 0.0): 1, (-12.0, 2.0, 0.0): 1, (10.0, 4.0, 2.0): 1},
                  flip_x=True)
    assert neuro.centroid(vol).tolist() == pytest.approx([-4.0, 2.0, 2 / 3])
    assert neuro.centroid(vol, side="left").tolist() == pytest.approx([-11.0, 1.0, 0.0])
    with pytest.raises(IdofigError, match="no voxel"):
        neuro.centroid(vol, threshold=5)


def test_a_line_profile_of_a_linear_field_is_that_field(tmp_path):
    """Trilinear sampling is exact on a field linear in x, y and z, averaged across or not."""
    shape, step, origin = (21, 25, 19), 2.0, np.array([-20.0, -24.0, -18.0])
    i, j, k = np.indices(shape)
    xyz = [origin[d] + step * idx for d, idx in enumerate((i, j, k))]
    field = 0.5 * xyz[0] + 0.1 * xyz[1] - 0.2 * xyz[2]
    aff = np.diag([step, step, step, 1.0])
    aff[:3, 3] = origin
    nib.save(nib.Nifti1Image(field.astype(np.float32), aff), str(tmp_path / "f.nii.gz"))
    pos, values = neuro.line_profile(tmp_path / "f.nii.gz", through=(0, 3.0, 1.0), axis="x", start=-10, stop=10,
                                     average_mm=1)
    assert pos.tolist() == list(np.arange(-10.0, 10.5, 1.0))
    assert values == pytest.approx(0.5 * pos + 0.1 * 3.0 - 0.2 * 1.0, abs=1e-5)
    pos, values = neuro.line_profile(tmp_path / "f.nii.gz", through=(0, 0, 0), axis="z")
    assert (pos[0], pos[-1]) == (-18.0, 18.0) and values == pytest.approx(-0.2 * pos, abs=1e-5)


def test_a_slice_draws_a_crosshair_letters_and_where_it_is_cut(tmp_path):
    data = np.zeros((21, 25, 19, 2), np.float32)
    data[..., 1] = 1.0
    aff = np.diag([2.0, 2.0, 2.0, 1.0])
    aff[:3, 3] = (-20, -24, -18)
    nib.save(nib.Nifti1Image(data, aff), str(tmp_path / "four.nii.gz"))
    fig = plt.figure()
    ax = idf.name(fig.add_axes((0, 0, 1, 1)), "axial")
    im = neuro.volume_slice(ax, overlay=(tmp_path / "four.nii.gz", 1), axis="z", at=-4.0, crosshair=(-6, 8, -4),
                            halo="black", orientation="all", coordinate=True, extent=(-10, 10, -12, 12))
    assert np.all(im.get_array() == 1), "the second volume of the 4-D file"
    names = _names(fig)
    h, v = names["axial.crosshair.h"].artists[0], names["axial.crosshair.v"].artists[0]
    assert list(h.get_ydata()) == [8, 8] and list(v.get_xdata()) == [-6, -6]
    assert list(h.get_xdata()) == [-10, 10] and ax.get_xlim() == (-10, 10) and ax.get_ylim() == (-12, 12)
    assert h.get_path_effects(), "a halo under the line"
    letters = {t.get_text(): t.get_position() for t in ax.texts if t.get_text() in "LRAP"}
    assert letters["L"][0] < 0.5 < letters["R"][0] and letters["P"][1] < 0.5 < letters["A"][1]
    assert names["axial.coordinate"].artists[0].get_text() == "x = −6, y = 8, z = −4 mm"
    rad = idf.name(fig.add_axes((0, 0, 1, 1)), "rad")
    neuro.volume_slice(rad, overlay=(tmp_path / "four.nii.gz", 1), orientation=True, radiological=True)
    marks = {t.get_text(): t.get_position()[0] for t in rad.texts}
    assert marks["R"] < marks["L"], "radiological: the subject's right on the left"
    with pytest.raises(IdofigError, match="volume 2"):
        neuro.volume_slice(fig.add_axes((0, 0, 1, 1)), overlay=(tmp_path / "four.nii.gz", 2))


# ---------------------------------------------------------------------------- marks


def test_electrodes_draw_signed_discs_and_labels_clear_of_each_other(tmp_path):
    fig = plt.figure(figsize=(40 / 25.4, 30 / 25.4), dpi=72)
    pixels = np.ones((300, 400, 3))
    ax = idf.image(fig, pixels, 0, 0, 40, 30, name="cap", trim=False)
    xy = [(100, 100), (120, 110), (300, 200), (200, 150), (210, 160)]  # pixels: two pairs crowd each other
    centres = neuro.electrodes(ax, xy, ["F3", "F4", "P8", "Cz", "C2"], colors=["#009E73"] * 2 + ["#E69F00"] * 3,
                               signs=[1, -1, 1, -1, 0])
    names = _names(fig)
    assert {"cap.electrode.f3", "cap.electrode.f3.sign", "cap.electrode.f3.sign.v", "cap.electrode.f4.sign",
            "cap.electrode.f3.label", "cap.electrode.c2"} <= set(names)
    assert "cap.electrode.f4.sign.v" not in names and "cap.electrode.c2.sign" not in names
    disc = names["cap.electrode.f3"].artists[0]
    assert disc.get_radius() == 1.15
    fig.canvas.draw()
    boxes = [names[f"cap.electrode.{k}.label"].artists[0].get_window_extent() for k in ("f3", "f4", "p8", "cz", "c2")]
    discs = [names[f"cap.electrode.{k}"].artists[0].get_window_extent() for k in ("f3", "f4", "p8", "cz", "c2")]
    for i, a in enumerate(boxes):
        assert all(not a.overlaps(b) for j, b in enumerate(boxes) if j != i)
        assert all(not a.overlaps(d) for d in discs)
    assert centres.shape == (5, 2)
    with pytest.raises(IdofigError, match="no clear place"):
        neuro.electrodes(ax, xy, ["F3", "F4", "P8", "Cz", "C2"], box=(0, 0, 4, 4))


def test_an_image_keeps_the_files_pixel_coordinates_after_its_crop():
    pixels = np.zeros((50, 80, 4))
    pixels[10:40, 20:70] = [0.2, 0.3, 0.4, 1]
    fig = plt.figure(figsize=(2, 2), dpi=72)
    ax = idf.image(fig, pixels, 0, 0, 50.8, 50.8, name="r")
    assert ax.images[0].get_extent() == [19.5, 69.5, 39.5, 9.5]
    assert ax.get_xlim() == (19.5, 69.5) and ax.get_ylim() == (39.5, 9.5), "y runs down, as in the file"


def test_project_and_callouts_place_labels_beside_their_anchors(tmp_path):
    surf = tmp_path / "lh.white"
    verts, _ = _hemisphere(surf, subdivisions=2)
    fig = plt.figure(figsize=(60 / 25.4, 40 / 25.4), dpi=72)
    ax = fig.add_axes((10 / 60, 5 / 40, 30 / 60, 30 / 40), projection="3d")
    neuro.surface(ax, surf, view="lateral", hemi="left")
    centre = (verts.min(axis=0) + verts.max(axis=0)) / 2
    assert neuro.project(ax, centre)[0] == pytest.approx([25, 20], abs=0.6), "the box's centre: the axes' centre"
    anchors = np.array([[20, 20], [21, 21], [30, 20], [30, 20.5]])
    over = neuro.callouts(fig, anchors, ["a", "b", "c", "d"], centre=(25, 20), spacing=2.0, reach=3)
    names = _names(fig)
    assert {"callouts.a", "callouts.a.leader", "callouts.d"} <= set(names)
    a, b = names["callouts.a"].artists[0], names["callouts.b"].artists[0]
    c, d = names["callouts.c"].artists[0], names["callouts.d"].artists[0]
    assert a.get_ha() == "right" and c.get_ha() == "left", "left of a left anchor, right of a right one"
    assert abs(a.get_position()[1] - b.get_position()[1]) >= 2.0 - 1e-9
    assert abs(c.get_position()[1] - d.get_position()[1]) >= 2.0 - 1e-9
    assert over.patch.get_visible() is False


def test_a_topomap_label_sits_under_the_head():
    fig = plt.figure()
    ax = idf.name(fig.add_axes((0, 0, 1, 1)), "topo")
    neuro.topomap(ax, np.arange(len(CHANNELS), dtype=float), _info(), label="p = 0.011",
                  label_props={"weight": "bold"})
    t = _names(fig)["topo.label"].artists[0]
    assert t.get_text() == "p = 0.011" and t.get_weight() == "bold" and t.get_position() == (0.5, -0.02)


def _linear_volume(path, coef=(0.5, 0.1, -0.2), shape=(41, 81, 61), step=2.0, origin=(-70.0, -90.0, -50.0)):
    """A field linear in x, y, z mm on a grid: trilinear reads it exactly."""
    i, j, k = np.indices(shape)
    xyz = [o + step * idx for o, idx in zip(origin, (i, j, k))]
    aff = np.diag([step, step, step, 1.0])
    aff[:3, 3] = origin
    nib.save(nib.Nifti1Image(sum(c * v for c, v in zip(coef, xyz)).astype(np.float32), aff), str(path))
    return path


def test_volume_to_surface_reads_a_linear_field_at_each_vertex(tmp_path):
    """Points at ±t along a normal average to the vertex's own value on a linear field."""
    surf = tmp_path / "lh.white"
    verts, _ = _hemisphere(surf, subdivisions=2)
    field = _linear_volume(tmp_path / "f.nii.gz")
    values = neuro.volume_to_surface(field, surf)
    assert values == pytest.approx(verts @ np.array([0.5, 0.1, -0.2]), abs=1e-4)


def test_volume_to_surface_reads_wider_then_fills_the_cortex_and_leaves_the_wall_nan(tmp_path):
    surf = tmp_path / "lh.white"
    verts, faces = _hemisphere(surf, subdivisions=2)
    shape, step, origin = (41, 81, 61), 2.0, np.array([-70.0, -90.0, -50.0])
    z = origin[2] + step * np.arange(shape[2])
    data = np.ones(shape, np.float32)
    data[..., z > 45] = np.nan  # the brain's top missing: the cap's vertices read nothing within ±1 mm
    aff = np.diag([step, step, step, 1.0])
    aff[:3, 3] = origin
    nib.save(nib.Nifti1Image(data, aff), str(tmp_path / "v.nii.gz"))
    narrow = neuro.volume_to_surface(tmp_path / "v.nii.gz", surf, wider=None)
    assert np.isfinite(narrow).sum() > len(verts) // 2 and np.isnan(narrow).any()
    cortex = verts[:, 0] < -35  # the lateral half is cortex, the medial half a "wall"
    out = neuro.volume_to_surface(tmp_path / "v.nii.gz", surf, cortex=cortex)
    assert np.isnan(out[~cortex]).all(), "the wall is NaN, for surface() to show as background"
    assert np.allclose(out[cortex], 1.0), "read, read wider, or filled from read neighbours: all 1"
    unfilled = neuro.volume_to_surface(tmp_path / "v.nii.gz", surf, cortex=cortex, fill=False)
    assert np.isnan(unfilled[cortex]).any(), "the fill had cortex to fill"
    with pytest.raises(IdofigError, match="vertices"):
        neuro.volume_to_surface(tmp_path / "v.nii.gz", surf, cortex=cortex[:5])
