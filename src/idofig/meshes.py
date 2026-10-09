"""``idofig.mesh``: draw a triangle mesh file on a 3D axes (0.11.0).

::

    ax = p["brain"].add_subplot(projection="3d"); idf.name(ax, "main")
    idf.mesh(ax, "data/cortex.ply", scalars=field, cmap="inferno", name="cortex")  # main.mesh.cortex

The file (``.glb .gltf .stl .ply .obj``) is input data the producer reads, like a ``.npy``: list it
in the producer's ``inputs``. It is read with trimesh, imported here only, so ``import idofig`` and
composing stay free of it. A mesh of more than ``max_faces`` (100 000) triangles is simplified
before it is drawn (:func:`simplify`, fast-simplification's quadric decimation). The view
(``elev``, ``azim``, ``roll``, ``zoom``, ``proj``) is a style override on the 3D axes (styling.py),
never a script edit; a rebuild draws the mesh from it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.colors import to_rgba, to_rgba_array
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from .errors import IdofigError
from .fsutil import write_atomic
from .naming import slug
from .scaffold import MESH_SUFFIXES
from .styling import view_zoom

# More faces than this are drawn as one raster image (at savefig.dpi, 600 dpi or the journal's
# floor if higher), which keeps the mesh's name in panel.svg: 200k vector triangles is tens of MB.
MESH_VECTOR_FACES = 20_000
# More faces than this are simplified before drawing: a 150k-face surface drawn whole is mostly
# triangles smaller than a printed pixel, and every one of them is projected and sorted.
MAX_FACES = 100_000
DEFAULT_COLOR = "#c8c8c8"
AMBIENT, DIFFUSE = 0.35, 0.65  # headlight: rgb * (AMBIENT + DIFFUSE * |n·v|)


class MeshCollection(Poly3DCollection):
    """Triangles lit from the viewer. The face colours are recomputed from the axes' current
    view at every draw, so a view set in style.json is lit from the front: shaded once when
    made (``Poly3DCollection(shade=True)``), a mesh turned to its back was drawn in its own
    shadow.

    Its projection is one array operation over every triangle (:meth:`_project`). matplotlib
    before 3.11 projects and sorts face by face in Python: a 145k-face cortex took 41 s of a
    45 s producer run, three draws a save. Faces of equal depth are drawn in the file's order,
    as matplotlib before 3.11 draws them; 3.11's ``argsort`` is not stable, and which of two
    coplanar triangles came last could differ by CPU."""

    def __init__(self, verts: np.ndarray, faces: np.ndarray, *, shade: bool, smooth: bool, **kwargs) -> None:
        triangles = verts[faces]
        self._idofig_shade = shade
        self._idofig_normals = _normals(verts, faces, triangles, smooth)
        # x, y, z, 1 of every corner, face by face: the array matplotlib projects with np.dot(M, …)
        self._idofig_vec = np.vstack([triangles.reshape(-1, 3).T, np.ones(3 * len(faces))])
        super().__init__(triangles, **kwargs)

    def set_facecolor(self, c) -> None:
        super().set_facecolor(c)
        self._idofig_unlit = self._facecolor3d  # what the script or a style set, before the light

    def do_3d_projection(self):
        mapped = self._A
        base = self.to_rgba(mapped) if mapped is not None else self._idofig_unlit
        rgba = np.array(np.broadcast_to(to_rgba_array(base, self._alpha), (len(self._idofig_normals), 4)))
        if self._idofig_shade:
            rgba[:, :3] *= self._light()[:, None]
        self._facecolor3d = rgba
        self._A = None  # else matplotlib puts the unlit mapped colours back over the lit ones
        try:
            return self._project() if self._plain() else super().do_3d_projection()
        finally:
            self._A = mapped

    def _plain(self) -> bool:
        """Whether :meth:`_project` draws this as matplotlib would: not clipped to the view,
        no path codes or fixed sort depth (``idofig.mesh`` sets none), linear axes."""
        ax = self.axes
        return (not getattr(self, "_axlim_clip", False) and self._codes3d is None and self._sort_zpos is None
                and all(getattr(ax, f"get_{a}scale")() == "linear" for a in "xyz") and len(self._idofig_normals) > 0)

    def _project(self):
        """``Poly3DCollection.do_3d_projection`` for whole triangles at once: the same
        projection (``np.dot(M, vec) / w``), depth (the zsort function over each face's three
        corners), furthest first, colours in that order, and the same returned zorder (the
        nearest corner's depth)."""
        n = len(self._idofig_normals)
        vecw = np.dot(self.axes.M, self._idofig_vec)
        corners = (vecw[:3] / vecw[3]).T.reshape(n, 3, 3)
        depth = self._zsortfunc(corners[..., 2], axis=-1)
        order = np.argsort(-depth, kind="stable")  # stable: a tie keeps the file's order
        PolyCollection.set_verts(self, corners[order, :, :2], self._closed)
        self._facecolors2d = self._facecolor3d[order]
        edge = self._edgecolor3d
        self._edgecolors2d = edge[order] if len(edge) == n else edge
        return np.min(corners[..., 2])

    def _light(self) -> np.ndarray:
        """AMBIENT + DIFFUSE·|n·v| per face: v is the direction to the viewer (``_view_w``, set by
        the draw's ``get_proj``) in the axes' world box, where a normal is scaled by the inverse
        of the box's stretch of each data axis."""
        ax = self.axes
        lims = np.array(ax.get_w_lims(), dtype=float).reshape(3, 2)
        world_per_data = np.asarray(ax._roll_to_vertical(ax._box_aspect), dtype=float) / (lims[:, 1] - lims[:, 0])
        n = self._idofig_normals / world_per_data
        length = np.linalg.norm(n, axis=1)
        n = np.divide(n, length[:, None], out=np.zeros_like(n), where=length[:, None] > 0)
        return AMBIENT + DIFFUSE * np.abs(n @ np.asarray(ax._view_w, dtype=float))


def _unit(n: np.ndarray) -> np.ndarray:
    length = np.linalg.norm(n, axis=1)
    return np.divide(n, length[:, None], out=np.zeros_like(n), where=length[:, None] > 0)


def _normals(verts: np.ndarray, faces: np.ndarray, triangles: np.ndarray, smooth: bool) -> np.ndarray:
    """The normal each face is lit by. Flat: its own. Smooth: the sum of its corners' vertex
    normals, each the sum of the unnormalized normals (twice the area) of the faces around the
    vertex, normalized — lit flat, the small irregular triangles of a cortical surface came out
    speckled. A corner's normal is turned to the face's side before the sum, so a face whose
    neighbours are wound the other way is not darkened by its own corners (|n·v| ignores the
    side); a vertex where neighbours of opposite winding cancel still points wrong, which no
    rule can mend without knowing the outside. A face whose vertices no other face shares (an
    STL's) or whose smoothed normal vanishes keeps its own normal."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    flat = np.cross(b - a, c - a)
    if not smooth or not len(faces):
        return flat
    corners = faces.ravel()
    vertex = np.stack([np.bincount(corners, weights=np.repeat(flat[:, k], 3), minlength=len(verts))
                       for k in range(3)], axis=1)
    at = _unit(vertex)[faces]  # (F, 3 corners, 3)
    at *= np.where(np.einsum("fck,fk->fc", at, flat) < 0, -1.0, 1.0)[..., None]
    summed = at.sum(axis=1)
    alone = (np.bincount(corners, minlength=len(verts))[faces] == 1).all(axis=1)
    keep = alone | (np.linalg.norm(summed, axis=1) < 1e-6)
    return np.where(keep[:, None], flat, summed)


def _file_colors(geometry) -> np.ndarray | None:
    """A trimesh geometry's own colours, per face (F, 4) in 0–1, or None when it has none."""
    visual = geometry.visual
    if visual.kind == "texture":  # a glTF material or texture: sampled to colours
        visual = visual.to_color()
    if visual.kind == "vertex":
        c = np.asarray(visual.vertex_colors, dtype=float) / 255
        per_face = c[geometry.faces].mean(axis=1) if c.ndim == 2 else c
    elif visual.kind == "face":
        per_face = np.asarray(visual.face_colors, dtype=float) / 255
    else:
        return None
    return np.array(np.broadcast_to(per_face, (len(geometry.faces), 4)))


def read_mesh(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Vertices (V, 3), triangles (F, 3) and the file's own colours per face (F, 4) or None.

    A scene is flattened with each node's transform applied, nodes in name order (not the
    file's). Vertices are as the file stores them (``process=False``): merged, a .ply's vertex
    count no longer matched the per-vertex field computed for it."""
    import trimesh

    try:
        scene = trimesh.load(str(path), force="scene", process=False)
    except Exception as exc:  # trimesh raises a different type per format and failure
        raise IdofigError(f"{path}: not a mesh idofig can read ({type(exc).__name__}: {exc})") from None
    verts, faces, colors, offset = [], [], [], 0
    for node in sorted(scene.graph.nodes_geometry):
        matrix, key = scene.graph[node]
        geometry = scene.geometry[key]
        if not isinstance(geometry, trimesh.Trimesh) or not len(geometry.faces):
            continue  # a point cloud or a path draws no triangle
        verts.append(trimesh.transformations.transform_points(geometry.vertices, matrix))
        faces.append(np.asarray(geometry.faces) + offset)
        colors.append(_file_colors(geometry))
        offset += len(geometry.vertices)
    if not faces:
        raise IdofigError(f"{path}: holds no triangles")
    own = None
    if any(c is not None for c in colors):
        grey = to_rgba(DEFAULT_COLOR)
        own = np.concatenate([c if c is not None else np.tile(grey, (len(f), 1)) for c, f in zip(colors, faces)])
    return np.concatenate(verts).astype(float), np.concatenate(faces), own


def simplify(verts: np.ndarray, faces: np.ndarray, max_faces: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``verts``/``faces`` decimated to at most about ``max_faces`` triangles, and for each new
    triangle the index of the file's triangle it is (its corners moved), so a value or colour per
    face carries over exactly: quadric decimation only collapses edges, so every triangle left is
    one of the file's whose three corners still map to three vertices, in the file's order.

    Vertices at the same position are merged first (an STL stores three per facet; unmerged,
    no edge could collapse) and zero-area triangles left out (they draw nothing). The same
    input gives the same arrays (fast-simplification 0.1.7 and 0.1.8 did not on a process's first
    call; 0.1.11 is the floor). When fast-simplification's
    replay of its collapses does not give back the triangles it returned, which triangle each
    came from is unknown and the colours would land on the wrong faces: refused."""
    import fast_simplification

    merged, inverse = np.unique(verts, axis=0, return_inverse=True)
    tris = inverse.reshape(-1)[faces]
    kept = np.flatnonzero((tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2]))
    # Only vertices a triangle uses, numbered densely: fast-simplification before 0.2.0 mapped
    # every vertex after an unused one to the wrong index (its issue #60).
    used, dense = np.unique(tris[kept], return_inverse=True)
    merged, tris = merged[used], np.ascontiguousarray(dense.reshape(-1, 3), dtype=np.int64)
    if len(tris) <= max_faces:
        return merged, tris, kept
    points, new_faces, collapses = fast_simplification.simplify(merged, tris, target_count=max_faces,
                                                                return_collapses=True)
    # The replay reads float32 points before 0.2.0; only its vertex mapping is used here.
    to_new = fast_simplification.replay_simplification(merged.astype(np.float32), tris, collapses)[2]
    mapped = to_new[tris]
    alive = np.flatnonzero((mapped[:, 0] != mapped[:, 1]) & (mapped[:, 1] != mapped[:, 2])
                           & (mapped[:, 0] != mapped[:, 2]))
    if not np.array_equal(mapped[alive], new_faces):
        raise IdofigError("simplifying the mesh lost track of which triangle each one came from, so its "
                          "colours cannot follow: draw it with max_faces=None")
    return np.asarray(points, dtype=float), np.asarray(new_faces, dtype=np.int64), kept[alive]


def _check_faces(value, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise IdofigError(f"{what} must be a whole number ≥ 1 (got {value!r})")


def simplify_file(src: Path, out: Path, faces: int) -> dict:
    """Write ``src`` decimated to about ``faces`` triangles as ``out`` (.ply .glb .obj .stl), so a
    project can commit a small surface: what ``idofig mesh-simplify`` does. The file's own
    colours go along per face, which only .ply keeps (glTF has none per face, STL none at all):
    with colours, any other ``out`` is refused rather than writing them away."""
    import trimesh

    _check_faces(faces, "faces")
    src, out = Path(src), Path(out)
    if not src.is_file():
        raise IdofigError(f"{src} does not exist")
    suffix = out.suffix.lower()
    if suffix not in (".ply", ".glb", ".obj", ".stl"):
        raise IdofigError(f"{out}: write .ply, .glb, .obj or .stl")
    if out.resolve() == src.resolve():
        raise IdofigError(f"{out} is the file being simplified: write the smaller mesh beside it")
    verts, tris, own = read_mesh(src)
    if own is not None and suffix != ".ply":
        raise IdofigError(f"{src.name} has colours of its own, which only .ply keeps per face: write {out.stem}.ply")
    new_verts, new_faces, source = simplify(verts, tris, faces)
    colors = None if own is None else np.round(own[source] * 255).astype(np.uint8)
    data = trimesh.Trimesh(new_verts, new_faces, face_colors=colors, process=False).export(file_type=suffix[1:])
    write_atomic(out, data)
    return {"file_faces": int(len(tris)), "file_vertices": int(len(verts)),
            "faces": int(len(new_faces)), "vertices": int(len(new_verts))}


def mesh(ax, path, *, name: str | None = None, color=None, scalars=None, cmap="viridis", vmin=None,
         vmax=None, shade: bool = True, smooth: bool = True, alpha: float | None = None,
         rasterized: bool | None = None, max_faces: int | None = MAX_FACES):
    """Draw the triangle mesh in ``path`` (.glb .gltf .stl .ply .obj; relative to the producer's
    working directory, the project root) on the 3D axes ``ax``; returns the collection, named
    ``<axes>.mesh.<name or file stem>``.

    Colour: ``scalars`` (one per vertex, averaged per face, or one per face; per vertex when the
    two counts are equal) through ``cmap``/``vmin``/``vmax``, else ``color``, else the file's own
    vertex or face colours, else ``#c8c8c8``. ``shade`` lights it from the viewer at every draw,
    each face by the normal smoothed over its vertices' neighbours (``smooth``) or its own.
    The axes' limits become the bounds of its meshes and its box their extents (one scale for
    x, y and z). More than ``max_faces`` faces are simplified to about that many first (:func:`simplify`;
    ``None`` draws every one), each drawn face coloured as the file's face it was. More than
    ``MESH_VECTOR_FACES`` drawn faces are rasterized unless ``rasterized`` says."""
    if getattr(ax, "name", None) != "3d":
        raise IdofigError("idofig.mesh draws on a 3D axes: make it with add_subplot(projection='3d')")
    path = Path(path)
    if path.suffix.lower() not in MESH_SUFFIXES:
        raise IdofigError(f"{path}: a mesh is one of {', '.join(MESH_SUFFIXES)}")
    if not path.is_file():
        raise IdofigError(f"{path} does not exist (a relative path is read from the project root)")
    if max_faces is not None:
        _check_faces(max_faces, "max_faces (None draws every face)")
    verts, faces, own = read_mesh(path)
    file_counts = {"file_faces": int(len(faces)), "file_vertices": int(len(verts))}
    kwargs: dict = {"edgecolors": "none", "linewidths": 0}
    if scalars is not None:
        values = np.asarray(scalars, dtype=float)
        if values.ndim != 1 or len(values) not in (len(verts), len(faces)):
            raise IdofigError(f"scalars has shape {values.shape}; {path.name} has {len(verts)} vertices and "
                              f"{len(faces)} faces: give one value per vertex or per face")
        face_values = values[faces].mean(axis=1) if len(values) == len(verts) else values
    else:
        face_values = None
    if max_faces is not None and len(faces) > max_faces:
        verts, faces, source = simplify(verts, faces, max_faces)
        face_values = None if face_values is None else face_values[source]
        own = None if own is None else own[source]
    triangles = verts[faces]
    if face_values is None:
        kwargs["facecolors"] = color if color is not None else (own if own is not None else DEFAULT_COLOR)
    rasterized = len(faces) > MESH_VECTOR_FACES if rasterized is None else rasterized
    # Rasterized, antialiased triangles leave hairline seams between them in the image.
    coll = MeshCollection(verts, faces, shade=shade, smooth=smooth, antialiased=not rasterized, **kwargs)
    if face_values is not None:
        coll.set_array(face_values)
        coll.set_cmap(cmap)
        coll.set_clim(vmin, vmax)
    if alpha is not None:
        coll.set_alpha(alpha)
    coll.set_rasterized(rasterized)
    lo, hi = triangles.reshape(-1, 3).min(axis=0), triangles.reshape(-1, 3).max(axis=0)
    coll._idofig_mesh = {
        "name": slug(name if name is not None else path.stem),
        "path": path.resolve(),
        "faces": int(len(faces)),
        "vertices": int(len(verts)),
        **file_counts,
        "bounds": [[round(float(v), 6) for v in lo], [round(float(v), 6) for v in hi]],
    }
    ax.add_collection3d(coll)
    _frame(ax, lo, hi)
    return coll


def _frame(ax, lo: np.ndarray, hi: np.ndarray) -> None:
    """Limits to the bounds of every mesh drawn on ``ax`` so far, box to their extents."""
    if hasattr(ax, "_idofig_mesh_bounds"):
        lo, hi = np.minimum(lo, ax._idofig_mesh_bounds[0]), np.maximum(hi, ax._idofig_mesh_bounds[1])
    ax._idofig_mesh_bounds = (lo, hi)
    extent = hi - lo
    extent = np.where(extent > 0, extent, (extent.max() or 1.0) * 1e-3)  # a flat mesh still has a box
    mid = (lo + hi) / 2
    ax.set_xlim3d(mid[0] - extent[0] / 2, mid[0] + extent[0] / 2)
    ax.set_ylim3d(mid[1] - extent[1] / 2, mid[1] + extent[1] / 2)
    ax.set_zlim3d(mid[2] - extent[2] / 2, mid[2] + extent[2] / 2)
    ax.set_box_aspect(tuple(extent), zoom=view_zoom(ax))
