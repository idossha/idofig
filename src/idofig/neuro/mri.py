"""Cortical surfaces, volume slices and what is read from them (0.13.0; the ``mri`` extra, nibabel).

::

    ax = p["brain"].add_subplot(projection="3d"); idf.name(ax, "lh")
    neuro.surface(ax, "data/fsaverage5/lh.inflated", t_map, sulc="data/fsaverage5/lh.sulc",
                  threshold=2.0, vmin=-5, vmax=5)                    # lh.mesh.left, lateral, filling its axes

    neuro.surface_views(fig, 0, 0, 80, 20, {"left": "lh.pial", "right": "rh.pial"},
                        {"left": lh, "right": rh}, name="brain")     # four views at one scale

    ax = idf.name(idf.axes_mm(fig, 2, 2, 30, 36), "axial")
    target = neuro.centroid("data/roi.nii.gz", side="left")
    neuro.volume_slice(ax, "data/MNI152_T1_1mm.nii.gz", axis="z", at=target[2],
                       overlay="results/field.nii.gz", roi="data/roi.nii.gz", crosshair=target)
    pos, field = neuro.line_profile("results/field.nii.gz", through=target, axis="x")

A surface is an ``idofig.mesh`` (lit from the viewer, its view a style override); a slice is images
on one axes in millimetres, so volumes on different grids overlay without resampling. Every file
is input data: list it in the producer's ``inputs``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..errors import IdofigError
from ..naming import mark_part
from . import require

# (elev, azim) of a named view, in RAS coordinates (x right, y anterior, z superior); lateral
# and medial depend on the hemisphere. Ventral has anterior up, so the left hemisphere is on the
# right; dorsal has anterior up and the left hemisphere on the left.
VIEWS = {
    ("left", "lateral"): (0, 180), ("left", "medial"): (0, 0),
    ("right", "lateral"): (0, 0), ("right", "medial"): (0, 180),
    "dorsal": (90, -90), "ventral": (-90, 90), "anterior": (0, 90), "posterior": (0, -90),
}
GYRUS, SULCUS = "#c8c8c8", "#8c8c8c"  # a surface's anatomy where its values show nothing
FIT = 0.98  # a fitted surface fills this much of its axes' limiting side
_AXES = {"x": 0, "y": 1, "z": 2}


# ---------------------------------------------------------------------------- reading


def _surface_file(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices and triangles of a FreeSurfer surface (``lh.inflated``, ``rh.pial`` …), a GIFTI
    one (``.surf.gii``), or a file :func:`idofig.mesh` reads."""
    from .. import meshes

    if not path.is_file():
        raise IdofigError(f"{path} does not exist (a relative path is read from the project root)")
    if path.suffix.lower() in meshes.MESH_SUFFIXES:
        verts, faces, _ = meshes.read_mesh(path)
        return verts, faces
    nib = require("nibabel", "mri")
    try:
        if path.name.lower().endswith(".gii"):
            verts, faces = nib.load(str(path)).agg_data(("pointset", "triangle"))
        else:
            verts, faces = nib.freesurfer.read_geometry(str(path))
    except Exception as exc:  # nibabel raises a different type per format and failure
        raise IdofigError(f"{path}: not a surface idofig can read ({type(exc).__name__}: {exc})") from None
    if verts is None or faces is None:
        raise IdofigError(f"{path}: holds no triangles")
    return np.asarray(verts, dtype=float), np.asarray(faces, dtype=np.int64)


def _per_vertex(value, what: str) -> np.ndarray:
    """A value per vertex: an array, or a FreeSurfer morph file (``lh.sulc``, ``lh.curv``,
    ``lh.thickness``), an ``.mgh``/``.mgz`` or a GIFTI data file."""
    if not isinstance(value, (str, Path)):
        return np.asarray(value, dtype=float).ravel()
    path = Path(value)
    if not path.is_file():
        raise IdofigError(f"{what}: {path} does not exist (a relative path is read from the project root)")
    nib = require("nibabel", "mri")
    name = path.name.lower()
    try:
        if name.endswith((".mgh", ".mgz", ".nii", ".nii.gz")):
            data = np.asarray(nib.load(str(path)).get_fdata())
        elif name.endswith(".gii"):
            data = np.asarray(nib.load(str(path)).agg_data())
        else:
            data = nib.freesurfer.read_morph_data(str(path))
    except Exception as exc:
        raise IdofigError(f"{what}: {path} is not a per-vertex file idofig can read "
                          f"({type(exc).__name__}: {exc})") from None
    return np.asarray(data, dtype=float).ravel()


def _hemisphere(path: Path, hemi: str | None) -> str | None:
    if hemi is not None:
        if hemi not in ("left", "right"):
            raise IdofigError(f"hemi is 'left' or 'right' (got {hemi!r})")
        return hemi
    name = path.name.lower()
    if name.startswith(("lh.", "left")) or "hemi-l" in name or ".l." in name:
        return "left"
    if name.startswith(("rh.", "right")) or "hemi-r" in name or ".r." in name:
        return "right"
    return None


def parcel_values(annot, values: dict, default: float = np.nan) -> np.ndarray:
    """One value per vertex from one value per parcel: ``annot`` a FreeSurfer ``.annot`` (or a
    GIFTI label file), ``values`` {parcel name: value}; vertices of a parcel not in ``values``, or
    of none, get ``default`` (NaN: the surface shows its anatomy there). A name the file does not
    have is an error, never ignored."""
    nib = require("nibabel", "mri")
    path = Path(annot)
    if not path.is_file():
        raise IdofigError(f"{path} does not exist (a relative path is read from the project root)")
    try:
        if path.name.lower().endswith(".gii"):
            img = nib.load(str(path))
            labels = np.asarray(img.agg_data(), dtype=int)
            table = img.labeltable.get_labels_as_dict()
            names = {k: str(v) for k, v in table.items()}
        else:
            labels, _, raw = nib.freesurfer.read_annot(str(path))
            names = {i: (n.decode() if isinstance(n, bytes) else str(n)) for i, n in enumerate(raw)}
    except Exception as exc:
        raise IdofigError(f"{path}: not a parcellation idofig can read ({type(exc).__name__}: {exc})") from None
    index = {n: i for i, n in names.items()}
    missing = sorted(set(values) - set(index))
    if missing:
        raise IdofigError(f"{path.name} has no parcel {', '.join(map(repr, missing))} "
                          f"(it has {', '.join(sorted(index))})")
    out = np.full(len(labels), default, dtype=float)
    for name, value in values.items():
        out[labels == index[name]] = value
    return out


# ---------------------------------------------------------------------------- views


def view_angles(view, hemi: str | None = None) -> tuple[float, float]:
    """(elev, azim) of ``view``: a name in :data:`VIEWS` (``lateral``/``medial`` need ``hemi``) or
    ``(elev, azim)`` itself."""
    if not isinstance(view, str):
        elev, azim = view
        return float(elev), float(azim)
    if view in ("lateral", "medial"):
        if hemi is None:
            raise IdofigError(f"a {view} view needs the hemisphere: pass hemi='left' or 'right', or a file named "
                              "lh.*/rh.*")
        return VIEWS[(hemi, view)]
    if view not in VIEWS:
        raise IdofigError(f"unknown view {view!r}; choose lateral, medial, dorsal, ventral, anterior, posterior, "
                          "or (elev, azim)")
    return VIEWS[view]


def _screen(elev: float, azim: float) -> tuple[np.ndarray, np.ndarray]:
    """The directions (RAS) of the screen's right and up under matplotlib's camera at ``elev``,
    ``azim`` and no roll: up is z tilted toward the viewer, right is up × the direction to it."""
    e, a = np.radians(elev), np.radians(azim)
    toward = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
    up = np.array([-np.sin(e) * np.cos(a), -np.sin(e) * np.sin(a), np.cos(e)])
    return np.cross(up, toward), up


def _surfaces(surf) -> list[Path]:
    return [Path(surf)] if isinstance(surf, (str, Path)) else [Path(s) for s in surf]


def view_size(surf, view="lateral", hemi: str | None = None) -> tuple[float, float]:
    """Width and height (mm, in the surface's own units) of ``surf`` (one file, or several drawn
    together) seen from ``view`` orthographically: the box a fitted :func:`surface` fills, for
    sizing its axes."""
    paths = _surfaces(surf)
    verts = np.concatenate([_surface_file(p)[0] for p in paths])
    hemis = {_hemisphere(p, hemi) for p in paths}
    right, up = _screen(*view_angles(view, hemis.pop() if len(hemis) == 1 else None))
    return float(np.ptp(verts @ right)), float(np.ptp(verts @ up))


def fit(ax, margin: float = FIT) -> float:
    """Zoom the meshes on the 3D axes ``ax`` to fill ``margin`` of the box it was placed in, as it
    is turned now; returns the zoom (style.json's ``zoom`` overrides it). A 3D axes draws in the
    square of its shorter side, so a box that is not square could not be filled: the axes becomes
    the square of its longer side, centred on the box (its background is off, so it may overlap
    its neighbours), and the meshes fill the box. Exact for an orthographic view: what is measured
    is where matplotlib projects every vertex."""
    from matplotlib.transforms import Bbox
    from mpl_toolkits.mplot3d import proj3d

    from ..styling import _set_view, view_zoom

    verts = [np.asarray(c._idofig_vec[:3].T) for c in ax.collections if getattr(c, "_idofig_mesh", None) is not None]
    if not verts:
        raise IdofigError("fit zooms to the meshes on a 3D axes: draw one first")
    verts = np.concatenate(verts)
    fig = ax.figure
    box = getattr(ax, "_idofig_fit_box", None) or ax.get_position(original=True).frozen()
    ax._idofig_fit_box = box  # fitted again (another surface on the axes), it fills the same box
    fw, fh = fig.bbox.width, fig.bbox.height
    w_px, h_px = box.width * fw, box.height * fh
    side = max(w_px, h_px)
    cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    ax.set_position(Bbox.from_bounds(cx - side / 2 / fw, cy - side / 2 / fh, side / fw, side / fh))
    def shown():
        ax.apply_aspect()
        x, y, _ = proj3d.proj_transform(verts[:, 0], verts[:, 1], verts[:, 2], ax.get_proj())
        return ax.transData.transform(np.c_[x, y])

    w, h = np.ptp(shown(), axis=0)
    zoom = round(view_zoom(ax) * margin * min(w_px / w, h_px / h), 4)
    _set_view(ax, "zoom", zoom)
    # matplotlib draws the box a little off the square's centre: the square moves by as much
    drawn = shown()
    dx, dy = cx * fw - (drawn.min(axis=0)[0] + drawn.max(axis=0)[0]) / 2, cy * fh - (drawn.min(axis=0)[1] + drawn.max(axis=0)[1]) / 2
    pos = ax.get_position(original=True)
    ax.set_position(Bbox.from_bounds(pos.x0 + dx / fw, pos.y0 + dy / fh, pos.width, pos.height))
    return zoom


# ---------------------------------------------------------------------------- surface


def surface(ax, surf, values=None, *, sulc=None, hemi: str | None = None, view="lateral", threshold=None,
            cmap="RdBu_r", vmin=None, vmax=None, name: str | None = None, background=None, outline=None,
            outline_color=None, proj: str = "ortho", zoom_to_fit: bool = True, **kwargs):
    """Draw the cortical surface in ``surf`` (a FreeSurfer surface such as ``lh.inflated``, a
    GIFTI ``.surf.gii``, or any file :func:`idofig.mesh` reads; or a list of them, both
    hemispheres on one axes, with ``values``, ``sulc`` and ``outline`` lists to match) on the 3D
    axes ``ax``, coloured by ``values`` (one per vertex: an array or a per-vertex file) through
    ``cmap``/``vmin``/``vmax``. Returns the collection (a list for a list), each
    ``<axes>.mesh.<name, else its hemisphere, else its file's stem>``.

    Where ``values`` is NaN or ``|values| < threshold`` the surface shows its anatomy: ``sulc``
    (per vertex, file or array; FreeSurfer's sign, positive in a sulcus) in two greys, else
    ``background`` (default ``#c8c8c8``; a medial wall left NaN takes it). ``outline`` (a boolean
    per vertex: a region, a cluster) is drawn as its border, one face wide, in ``outline_color``
    (the rc's ``axes.edgecolor``). ``view`` starts the camera — ``lateral``, ``medial`` (one
    hemisphere: ``hemi``, or a file named ``lh.*``/``rh.*``/``*hemi-L*``…), ``dorsal``,
    ``ventral``, ``anterior``, ``posterior``, or ``(elev, azim)`` — in an orthographic ``proj``,
    and ``zoom_to_fit`` zooms the meshes to fill the axes (:func:`fit`); ``elev``, ``azim``,
    ``zoom`` … on the axes in style.json turn it from there. Axis and background off.
    ``kwargs`` go to :func:`idofig.mesh`'s drawing (``smooth``, ``shade``, ``max_faces``,
    ``rasterized``, ``alpha``)."""
    from matplotlib import rcParams

    from .. import meshes

    meshes._check_axes(ax, "idofig.neuro.surface")
    paths = _surfaces(surf)
    several = not isinstance(surf, (str, Path))

    def each(value, what):
        if value is None or not several:
            return [value] * len(paths)
        value = list(value)
        if len(value) != len(paths):
            raise IdofigError(f"{what} has {len(value)} entries for {len(paths)} surfaces")
        return value

    hemis = [_hemisphere(p, hemi) for p in paths]
    elev, azim = view_angles(view, hemis[0] if len(set(hemis)) == 1 else None)
    colls = []
    for path, h, vals, depth, region in zip(paths, hemis, each(values, "values"), each(sulc, "sulc"),
                                            each(outline, "outline")):
        verts, faces = _surface_file(path)
        n = len(verts)
        anatomy = None  # per face, from sulc
        if depth is not None:
            depth = _per_vertex(depth, "sulc")
            if len(depth) != n:
                raise IdofigError(f"sulc has {len(depth)} entries; {path.name} has {n} vertices")
            anatomy = np.where((depth[faces].mean(axis=1) > 0)[:, None], _rgba(SULCUS), _rgba(GYRUS))
        scalars = None
        if vals is not None:
            scalars = _per_vertex(vals, "values")
            if len(scalars) != n:
                raise IdofigError(f"values has {len(scalars)} entries; {path.name} has {n} vertices")
            if threshold is not None:
                scalars = np.where(np.abs(scalars) < threshold, np.nan, scalars)
        plain = background if background is not None else GYRUS
        colls.append(meshes.draw_triangles(
            ax, verts, faces, own=None if scalars is not None else anatomy, path=path,
            name=(name if name and not several else h or path.stem), color=plain if anatomy is None else None,
            scalars=scalars, cmap=cmap, vmin=vmin, vmax=vmax,
            background=None if scalars is None else (plain if anatomy is None else anatomy),
            outline=region, outline_color=outline_color or rcParams["axes.edgecolor"], **kwargs))
    ax.view_init(elev=elev, azim=azim)
    ax.set_proj_type(proj)
    ax.set_axis_off()
    ax.patch.set_visible(False)  # neighbouring views may overlap their squares; only the brain is drawn
    if zoom_to_fit:
        fit(ax)
    return colls if several else colls[0]


def surface_views(fig, left: float, bottom: float, width: float, height: float, surfaces: dict, values=None, *,
                  views=(("left", "lateral"), ("left", "medial"), ("right", "medial"), ("right", "lateral")),
                  sulc=None, outline=None, gap: float = 1.5, tags=None, name: str = "brain", **kwargs):
    """Several views of a cortex in a row, all at one scale, as large as fits in the box (mm from
    the panel's bottom-left), centred. ``surfaces`` {"left": file, "right": file}; ``values``,
    ``sulc``, ``outline`` dicts by hemisphere (or None); ``views`` (hemisphere — ``left``,
    ``right`` or ``both`` — and view, as :func:`surface` names it); ``gap`` mm between views.
    Each view is a 3D axes sized to the brain it shows and named ``<name>.<hemisphere>.<view>``,
    its meshes ``….mesh.left`` and so on; ``tags`` (True for "L lat" …, or one text per view)
    are drawn under the views as ``….tag``. ``kwargs`` go to :func:`surface`. Returns the axes
    and the scale (mm on the page per mm of brain)."""
    from .. import draw

    def pick(d, which):
        if d is None:
            return None
        hemis = ("left", "right") if which == "both" else (which,)
        return [d[h] for h in hemis]

    plan = []
    for which, view in views:
        if which not in ("left", "right", "both"):
            raise IdofigError(f"a view's hemisphere is 'left', 'right' or 'both' (got {which!r})")
        files = pick(surfaces, which)
        w, h = view_size(files, view, None if which == "both" else which)
        plan.append((which, view, files, w, h))
    if tags is True:
        side = {"left": "L ", "right": "R ", "both": ""}
        tags = [side[which] + (view[:3] if isinstance(view, str) else "") for which, view, *_ in plan]
    usable = width - gap * (len(plan) - 1)
    scale = min(usable / sum(p[3] for p in plan), height / max(p[4] for p in plan))
    x = left + (usable - scale * sum(p[3] for p in plan)) / 2
    axes = []
    for i, (which, view, files, w, h) in enumerate(plan):
        ax = draw.axes_mm(fig, x, bottom + (height - h * scale) / 2, w * scale, h * scale, projection="3d")
        view_name = view if isinstance(view, str) else f"{view[0]:g}-{view[1]:g}"
        draw.name(ax, f"{name}.{which}.{view_name}")
        surface(ax, files, pick(values, which), sulc=pick(sulc, which), outline=pick(outline, which),
                hemi=None if which == "both" else which, view=view, **kwargs)
        if tags:
            mark_part(ax.text2D(0.5, 0, tags[i], transform=ax.transAxes, ha="center", va="top"), "tag")
        axes.append(ax)
        x += w * scale + gap
    return axes, scale


def _rgba(color) -> np.ndarray:
    from matplotlib.colors import to_rgba

    return np.array(to_rgba(color))


# ---------------------------------------------------------------------------- volumes


def _volume(src, what: str):
    """``src`` (a path nibabel reads, a nibabel image, or ``(either, k)`` for the k-th volume of
    a 4-D file) turned to RAS: its data and the position (mm) of voxel 0 and the voxel size along
    x, y and z. An oblique volume is refused: its slice is not a plane of voxels."""
    nib = require("nibabel", "mri")
    index = None
    if isinstance(src, tuple):
        src, index = src
    if isinstance(src, (str, Path)):
        path = Path(src)
        if not path.is_file():
            raise IdofigError(f"{what}: {path} does not exist (a relative path is read from the project root)")
        try:
            img = nib.load(str(path))
        except Exception as exc:
            raise IdofigError(f"{what}: {path} is not a volume idofig can read "
                              f"({type(exc).__name__}: {exc})") from None
    else:
        img = src
    if index is not None:
        if len(img.shape) != 4 or not 0 <= index < img.shape[3]:
            raise IdofigError(f"{what}: volume {index} of a file of shape {img.shape}")
        img = img.slicer[..., index]
    img = nib.as_closest_canonical(img)
    a = np.asarray(img.affine, dtype=float)
    if not np.allclose(a[:3, :3], np.diag(np.diag(a[:3, :3])), atol=1e-4 * np.abs(a[:3, :3]).max()):
        raise IdofigError(f"{what} is oblique (its affine turns the voxel grid): resample it to an "
                          "axis-aligned grid first")
    data = np.asarray(img.dataobj, dtype=float)
    if data.ndim == 4 and data.shape[3] == 1:
        data = data[..., 0]
    if data.ndim != 3:
        raise IdofigError(f"{what} has shape {data.shape}; pass (file, k) for the k-th volume of a 4-D file")
    return data, a[:3, 3], np.diag(a[:3, :3])


def centroid(volume, threshold: float = 0.5, side: str | None = None) -> np.ndarray:
    """The centre (x, y, z mm) of the voxels of ``volume`` above ``threshold`` — an ROI, a group
    coverage map — on the subject's ``side`` only (``left``: x < 0, ``right``: x > 0) when given.
    Where to cut a slice through a target, or to aim a crosshair."""
    data, origin, step = _volume(volume, "volume")
    ijk = np.argwhere(data > threshold)
    xyz = origin + ijk * step
    if side is not None:
        if side not in ("left", "right"):
            raise IdofigError(f"side is 'left' or 'right' (got {side!r})")
        xyz = xyz[xyz[:, 0] < 0] if side == "left" else xyz[xyz[:, 0] > 0]
    if not len(xyz):
        raise IdofigError(f"no voxel of the volume is above {threshold:g}{f' on the {side}' if side else ''}")
    return xyz.mean(axis=0)


def _trilinear(data: np.ndarray, origin: np.ndarray, step: np.ndarray, points: np.ndarray,
               weight: np.ndarray | None) -> np.ndarray:
    """``data`` at ``points`` (N, 3 mm), trilinear over the voxels with a finite value (and
    ``weight`` > 0, which also weighs them); NaN where less than half the weight is there, so the
    edge of a mask is not eroded toward zero."""
    ijk = (points - origin) / step
    base = np.floor(ijk).astype(int)
    frac = ijk - base
    total = np.zeros(len(points))
    acc = np.zeros(len(points))
    for corner in np.ndindex(2, 2, 2):
        idx = base + corner
        w = np.prod(np.where(corner, frac, 1 - frac), axis=1)
        ok = np.all((idx >= 0) & (idx < data.shape), axis=1)
        v = np.zeros(len(points))
        m = np.zeros(len(points))
        i, j, k = idx[ok].T
        v[ok] = data[i, j, k]
        m[ok] = 1.0 if weight is None else weight[i, j, k]
        m[~np.isfinite(v)] = 0
        total += w * m
        acc += w * m * np.nan_to_num(v)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(total >= 0.5, acc / total, np.nan)


def line_profile(volume, through, axis: str = "x", *, start: float | None = None, stop: float | None = None,
                 step: float = 1.0, mask=None, average_mm: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """``volume`` sampled along the line through ``through`` (x, y, z mm) parallel to ``axis``,
    from ``start`` to ``stop`` (mm along that axis; default: the volume's span) every ``step``
    mm: returns the positions and the values. Trilinear over the voxels that are finite and inside
    ``mask`` (a volume on its grid, if given), NaN where less than half the weight is; with
    ``average_mm`` each sample is the mean over points every 1 mm out to that distance across the
    line in the two other axes. numpy only: the profile a slice's crosshair runs along."""
    if axis not in _AXES:
        raise IdofigError(f"axis is 'x', 'y' or 'z' (got {axis!r})")
    data, origin, size = _volume(volume, "volume")
    weight = None
    if mask is not None:
        mdata, morigin, msize = _volume(mask, "mask")
        if mdata.shape != data.shape or not (np.allclose(morigin, origin) and np.allclose(msize, size)):
            raise IdofigError("mask must be on the volume's grid (same shape and affine)")
        weight = (mdata > 0).astype(float)
    n = _AXES[axis]
    lo, hi = origin[n], origin[n] + size[n] * (data.shape[n] - 1)
    start = lo if start is None else start
    stop = hi if stop is None else stop
    positions = np.arange(start, stop + step / 2, step)
    offsets = np.arange(-np.floor(average_mm), np.floor(average_mm) + 1)
    others = [i for i in range(3) if i != n]
    samples = []
    for da in offsets:
        for db in offsets:
            pts = np.tile(np.asarray(through, dtype=float), (len(positions), 1))
            pts[:, n] = positions
            pts[:, others[0]] += da
            pts[:, others[1]] += db
            samples.append(_trilinear(data, origin, size, pts, weight))
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # a sample with no point inside stays NaN
        values = np.nanmean(np.stack(samples), axis=0)
    return positions, values


def _vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Unit normals per vertex: the sum of its faces' unnormalized normals (area-weighted)."""
    t = verts[faces]
    flat = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    out = np.zeros_like(verts)
    for k in range(3):
        np.add.at(out, faces[:, k], flat)
    length = np.linalg.norm(out, axis=1, keepdims=True)
    return np.divide(out, length, out=np.zeros_like(out), where=length > 0)


def _along_normals(data, origin, step, weight, verts, normals, radius: float, samples: int) -> np.ndarray:
    import warnings

    reads = [_trilinear(data, origin, step, verts + t * normals, weight)
             for t in np.linspace(-radius, radius, samples)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # a vertex no sample reached stays NaN
        return np.nanmean(np.stack(reads), axis=0)


def volume_to_surface(volume, surf, *, radius: float = 1.0, samples: int = 5, wider: float | None = 3.0,
                      wider_samples: int = 7, mask=None, cortex=None, fill: bool = True) -> np.ndarray:
    """One value per vertex of ``surf`` (a surface file :func:`surface` reads) from ``volume`` (a
    path, a nibabel image or ``(file, k)``; on the surface's mm, as an MNI map on an MNI surface):
    the mean of ``samples`` points along the vertex's normal from −``radius`` to +``radius`` mm,
    each trilinear over the voxels that are finite and inside ``mask`` (on the volume's grid; NaN
    where less than half the weight is). A vertex none of those reached is read again out to
    ``wider`` mm with ``wider_samples`` points (None: not). ``cortex`` (a boolean per vertex, or
    a per-vertex file such as FreeSurfer's ``lh.mask``, > 0 inside) makes every other vertex NaN —
    the medial wall, which :func:`surface` then shows as its background — and with ``fill`` a
    cortex vertex still unread takes the mean of its read neighbours, repeated inward (an island
    with none stays NaN). nilearn's ``vol_to_surf(kind="line")`` reads the same lines, but a NaN
    voxel makes its interpolated point NaN where this weighs it out: values differ only at the
    edge of a mask. numpy only."""
    path = Path(surf)
    verts, faces = _surface_file(path)
    data, origin, step = _volume(volume, "volume")
    weight = None
    if mask is not None:
        mdata, morigin, mstep = _volume(mask, "mask")
        if mdata.shape != data.shape or not (np.allclose(morigin, origin) and np.allclose(mstep, step)):
            raise IdofigError("mask must be on the volume's grid (same shape and affine)")
        weight = (mdata > 0).astype(float)
    normals = _vertex_normals(verts, faces)
    values = _along_normals(data, origin, step, weight, verts, normals, radius, samples)
    gap = ~np.isfinite(values)
    if wider is not None and gap.any():
        values[gap] = _along_normals(data, origin, step, weight, verts[gap], normals[gap], wider, wider_samples)
    if cortex is None:
        return values
    inside = _per_vertex(cortex, "cortex") > 0
    if len(inside) != len(verts):
        raise IdofigError(f"cortex has {len(inside)} entries; {path.name} has {len(verts)} vertices")
    values[~inside] = np.nan
    if fill:
        edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        src, dst = np.concatenate([edges, edges[:, ::-1]]).T
        missing = inside & ~np.isfinite(values)
        while missing.any():
            use = ~missing[src] & inside[src] & missing[dst]
            if not use.any():
                break
            total = np.bincount(dst[use], weights=values[src[use]], minlength=len(values))
            count = np.bincount(dst[use], minlength=len(values))
            done = missing & (count > 0)
            values[done] = total[done] / count[done]
            missing &= ~done
    return values


def _cut(data: np.ndarray, origin: np.ndarray, step: np.ndarray, axis: int, at: float, what: str):
    """The plane of ``data`` nearest ``at`` mm along ``axis``, as an image (rows up the second
    remaining axis, columns along the first), its extent in mm and its voxel centres (mm) along
    the columns and the rows."""
    k = int(np.rint((at - origin[axis]) / step[axis]))
    if not 0 <= k < data.shape[axis]:
        lo, hi = origin[axis], origin[axis] + step[axis] * (data.shape[axis] - 1)
        raise IdofigError(f"{what} spans {lo:g} to {hi:g} mm along {'xyz'[axis]}; {at:g} mm is outside it")
    plane = np.take(data, k, axis=axis)
    a, b = [i for i in range(3) if i != axis]
    xs = origin[a] + step[a] * np.arange(data.shape[a])
    ys = origin[b] + step[b] * np.arange(data.shape[b])
    extent = (xs[0] - step[a] / 2, xs[-1] + step[a] / 2, ys[0] - step[b] / 2, ys[-1] + step[b] / 2)
    return plane.T, extent, (xs, ys)


def _halo(colour, width: float, halo, halo_pt: float):
    """Path effects that draw a line ``halo_pt`` wider in ``halo`` under it, or none."""
    if halo is None:
        return []
    import matplotlib.patheffects as pe

    return [pe.Stroke(linewidth=width + halo_pt, foreground=halo), pe.Normal()]


def _mm(v: float) -> str:
    return f"{v:.0f}".replace("-", "−")


# Orientation letters by slice axis: (left, right) of the horizontal axis, (bottom, top) of the
# vertical one, neurological.
_LETTERS = {"z": (("L", "R"), ("P", "A")), "y": (("L", "R"), ("I", "S")), "x": (("P", "A"), ("I", "S"))}


def volume_slice(ax, anatomy=None, *, axis: str = "z", at: float = 0.0, overlay=None, cmap="RdBu_r",
                 vmin=None, vmax=None, norm=None, threshold=None, mask=None, roi=None, roi_color=None,
                 roi_width=None, crosshair=None, crosshair_color="white", crosshair_width=None,
                 halo=None, halo_pt: float = 0.8, orientation: bool | str = False, coordinate: bool = False,
                 extent=None, anatomy_limits=None, radiological: bool = False,
                 interpolation: str = "nearest", anatomy_interpolation: str = "bilinear"):
    """Draw the slice ``at`` mm along ``axis`` (``x`` sagittal, ``y`` coronal, ``z`` axial) of
    ``anatomy`` in grey, ``overlay`` over it through ``cmap`` (``vmin``/``vmax`` or ``norm``),
    and the outline of ``roi`` (> 0.5), on the 2D axes ``ax``; returns the overlay's image (for
    a colorbar), else the anatomy's. Each volume is a path nibabel reads, a nibabel image, or
    ``(file, k)``: the k-th volume of a 4-D file.

    The axes' units are mm, so volumes on different grids line up as they are, each cut at its
    voxel nearest ``at``, never resampled; ``extent=(left, right, bottom, top)`` (mm) crops the
    slice, else the anatomy (else the overlay) frames it. Axial and coronal slices are
    neurological (the subject's left on the left) unless ``radiological``; a sagittal one has
    anterior on the right. The overlay hides where it is NaN, ``|value| < threshold``, or
    ``mask`` (a volume on the overlay's grid) is 0. The anatomy is shown from its 1st to its
    99.5th percentile of non-zero voxels unless ``anatomy_limits=(lo, hi)``.

    Marks: the roi's outline (``roi_color``/``roi_width``, else the rc's ``axes.edgecolor`` and
    ``axes.linewidth``); ``crosshair`` (x, y, z mm: a point, its two in-plane coordinates drawn
    as lines across the slice in ``crosshair_color``); ``halo`` (a colour) draws those lines over
    one ``halo_pt`` wider, so a white line shows on a light map. ``orientation`` writes the sides'
    letters inside the slice (True: the horizontal pair in the top corners, L/R or P/A; ``"all"``:
    all four, at the edges' middles), white over a dark halo; ``coordinate`` writes under it where
    it is cut (``z = 12 mm``; every coordinate of ``crosshair`` when there is one).

    Parts: ``<axes>.anatomy``, ``<axes>.overlay``, ``<axes>.roi``, ``<axes>.crosshair.h``,
    ``<axes>.crosshair.v``, ``<axes>.mark.<letter>``, ``<axes>.coordinate``. Axis off."""
    from matplotlib import rcParams

    if axis not in _AXES:
        raise IdofigError(f"axis is 'x', 'y' or 'z' (got {axis!r})")
    if anatomy is None and overlay is None:
        raise IdofigError("a slice needs an anatomy, an overlay or both")
    if norm is not None and (vmin is not None or vmax is not None):
        raise IdofigError("give a norm or vmin/vmax, not both")
    n = _AXES[axis]
    a, b = [i for i in range(3) if i != n]
    shown = None
    frame = None
    if anatomy is not None:
        data, origin, step = _volume(anatomy, "anatomy")
        plane, box, _ = _cut(data, origin, step, n, at, "anatomy")
        if anatomy_limits is None:
            inside = data[(data != 0) & np.isfinite(data)]
            anatomy_limits = tuple(np.percentile(inside, (1, 99.5))) if inside.size else (0.0, 1.0)
        shown = ax.imshow(plane, cmap="gray", vmin=anatomy_limits[0], vmax=anatomy_limits[1], origin="lower",
                          extent=box, interpolation=anatomy_interpolation)
        mark_part(shown, "anatomy")
        frame = box
    if overlay is not None:
        data, origin, step = _volume(overlay, "overlay")
        plane, box, _ = _cut(data, origin, step, n, at, "overlay")
        hide = ~np.isfinite(plane)
        if threshold is not None:
            hide |= np.abs(np.nan_to_num(plane)) < threshold
        if mask is not None:
            mdata, morigin, mstep = _volume(mask, "mask")
            if mdata.shape != data.shape or not (np.allclose(morigin, origin) and np.allclose(mstep, step)):
                raise IdofigError("mask must be on the overlay's grid (same shape and affine)")
            hide |= _cut(mdata, morigin, mstep, n, at, "mask")[0] == 0
        shown = ax.imshow(np.ma.masked_where(hide, plane), cmap=cmap, norm=norm, vmin=vmin, vmax=vmax,
                          origin="lower", extent=box, interpolation=interpolation)
        mark_part(shown, "overlay")
        frame = frame or box
    if extent is not None:
        frame = tuple(float(v) for v in extent)
    if roi is not None:
        data, origin, step = _volume(roi, "roi")
        plane, _, (xs, ys) = _cut(data, origin, step, n, at, "roi")
        inside = np.nan_to_num(plane) > 0.5
        if inside.any() and not inside.all():
            width = roi_width if roi_width is not None else rcParams["axes.linewidth"]
            colour = roi_color or rcParams["axes.edgecolor"]
            cs = ax.contour(xs, ys, np.nan_to_num(plane), levels=[0.5], colors=[colour], linewidths=width)
            cs.set_path_effects(_halo(colour, width, halo, halo_pt))
            mark_part(cs, "roi")
    if crosshair is not None:
        point = np.asarray(crosshair, dtype=float)
        if point.shape != (3,):
            raise IdofigError(f"crosshair is a point (x, y, z mm); got {crosshair!r}")
        width = crosshair_width if crosshair_width is not None else rcParams["axes.linewidth"]
        effects = _halo(crosshair_color, width, halo, halo_pt)
        (h,) = ax.plot(frame[:2], [point[b]] * 2, color=crosshair_color, linewidth=width, path_effects=effects)
        (v,) = ax.plot([point[a]] * 2, frame[2:], color=crosshair_color, linewidth=width, path_effects=effects)
        mark_part(h, "crosshair.h")
        mark_part(v, "crosshair.v")
    ax.set_xlim(*frame[:2])
    ax.set_ylim(*frame[2:])
    if radiological and axis != "x":
        ax.invert_xaxis()
    if orientation:
        import matplotlib.patheffects as pe

        (west, east), (south, north) = _LETTERS[axis]
        if radiological and axis != "x":
            west, east = east, west
        dark = [pe.withStroke(linewidth=halo_pt * 1.6, foreground=rcParams["axes.edgecolor"])]
        spots = [(west, 0.03, 0.97, "left", "top"), (east, 0.97, 0.97, "right", "top")]
        if orientation == "all":
            spots = [(west, 0.02, 0.5, "left", "center"), (east, 0.98, 0.5, "right", "center"),
                     (south, 0.5, 0.02, "center", "bottom"), (north, 0.5, 0.98, "center", "top")]
        for letter, x, y, ha, va in spots:
            t = ax.text(x, y, letter, transform=ax.transAxes, ha=ha, va=va, color="white", path_effects=dark)
            mark_part(t, f"mark.{letter}")
    if coordinate:
        where = (", ".join(f"{c} = {_mm(v)}" for c, v in zip("xyz", np.asarray(crosshair, dtype=float)))
                 if crosshair is not None else f"{axis} = {_mm(at)}") + " mm"
        mark_part(ax.text(0.5, -0.02, where, transform=ax.transAxes, ha="center", va="top"), "coordinate")
    ax.set_aspect("equal")
    ax.set_axis_off()
    return shown
