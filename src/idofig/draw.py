"""The API a producer script uses: ``panels`` → draw → ``save``.

::

    import idofig as fig

    p = fig.panels("dose", "time")          # sized from figure.json (mm), journal style applied
    ax = p["dose"].subplots(); fig.name(ax, "main")
    ax.bar(groups, control, label="control")
    ax.set_xlabel("dose (mg)")
    ...
    fig.save(p)                              # names parts, applies style.json, writes SVG + manifest

Run it through ``idofig build`` or directly with ``python path/to/script.py``; both
produce the same bytes. A direct run publishes the panels and recomposes the figure.
"""

from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field
from functools import partial
from io import StringIO
from pathlib import Path

from . import journals as J
from . import spec as S
from .errors import ContextError, IdofigError
from .fsutil import dump_json, rel, write_atomic
from .project import Project, find_project
from .units import PT_PER_IN, PT_PER_MM, mm_to_in, pt_to_mm


@dataclass
class Context:
    project: Project
    figure_id: str
    figure: dict
    output_dir: Path | None
    only: set[str] | None
    script: Path | None
    journal: dict = field(default_factory=dict)

    @property
    def staged(self) -> bool:
        return self.output_dir is not None


def _script_path() -> Path | None:
    main = sys.modules.get("__main__")
    f = getattr(main, "__file__", None)
    if f and Path(f).is_file():
        return Path(f).resolve()
    if sys.argv and sys.argv[0] and Path(sys.argv[0]).is_file():
        return Path(sys.argv[0]).resolve()
    return None


def resolve_context(figure: str | None = None) -> Context:
    script = _script_path()
    project = find_project(os.environ.get("IDOFIG_ROOT") or (script.parent if script else None))
    fid = figure or os.environ.get("IDOFIG_FIGURE")
    if not fid and script is not None:
        try:
            relparts = script.relative_to(project.figures_dir).parts
            if len(relparts) >= 2 and (project.figures_dir / relparts[0] / "figure.json").is_file():
                fid = relparts[0]
        except ValueError:
            pass
        if not fid:
            srel = rel(script, project.root)
            owners = []
            for candidate in project.figure_ids():
                try:
                    doc = S.load_figure(project.figure_json(candidate))
                except IdofigError:
                    continue
                if any(srel in pr.get("run", []) for pr in doc.get("producers", [])):
                    owners.append(candidate)
            if len(owners) == 1:
                fid = owners[0]
            elif len(owners) > 1:
                raise ContextError(f"{srel} is a producer of several figures ({', '.join(owners)}); "
                                   "pass figure=... to idofig.panels()")
    if not fid:
        raise ContextError(
            "cannot tell which figure these panels belong to: run the script through `idofig build`, "
            "keep it inside figures/<id>/, list it in a producer's run, or pass figure=... to idofig.panels()"
        )
    doc = S.load_figure(project.figure_json(fid))
    out = os.environ.get("IDOFIG_OUTPUT_DIR")
    only = os.environ.get("IDOFIG_ONLY")
    journal = J.load(doc.get("journal") or project.journal, str(project.root))
    return Context(
        project=project,
        figure_id=fid,
        figure=doc,
        output_dir=Path(out) if out else None,
        only=set(x for x in only.split(",") if x) if only else None,
        script=script,
        journal=journal,
    )


def _use_agg() -> None:
    """Select Agg, the backend ``build`` runs producers with, unless this is a session.

    Kept, the canvas a plain ``python make.py`` gets (macosx on a Mac, or a matplotlibrc's)
    measured what the script measures before saving (``clabel``) otherwise than ``build``. A
    session — a notebook, IPython, ``python -i``, an MPLBACKEND set for it, even before it has
    chosen one — keeps its backend: switched, none of its later plots showed, and matplotlib
    3.8 closed its figures (each save draws on Agg anyway, :func:`_on_agg`). IPython is a
    session while its shell runs, not when a library imports it (seaborn does, via ipywidgets).
    """
    import matplotlib

    ipython = sys.modules.get("IPython")
    shell = ipython is not None and getattr(ipython, "get_ipython", lambda: None)() is not None
    session = os.environ.get("MPLBACKEND") or sys.flags.interactive or hasattr(sys, "ps1") or shell
    if not session:
        matplotlib.use("Agg")


def _on_agg(fig, undo) -> None:
    """Draw this save on an Agg canvas at the figure's own dpi and at the size ``panels`` made
    it, as ``build`` does (rule 4); ``undo`` gives the session back its canvas, dpi and size.
    A session's canvas lays a panel out otherwise: a Retina display doubles its dpi (72 → 144),
    and an svg canvas cannot measure a part."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    canvas = fig.canvas
    # Read before a new canvas is made: under matplotlib < 3.11 it resets `_original_dpi` to the
    # doubled dpi, the doubling was never undone, and the session kept 144 as the figure's own.
    own = fig._original_dpi
    if type(canvas) is not FigureCanvasAgg:
        undo.callback(fig.set_canvas, canvas)
        undo.keep(fig, "_original_dpi")
        FigureCanvasAgg(fig)  # it makes itself the figure's canvas
    # Only the canvas's scaling is undone: a dpi the script set (`set_dpi(300)`), halved to 150,
    # laid the panel out otherwise.
    ratio = getattr(canvas, "device_pixel_ratio", 1)
    if ratio != 1 and math.isclose(fig.dpi, own * ratio):
        undo.set(fig, "dpi", own)
    # A GUI canvas sizes the figure to its window (macosx's to whole pixels: an 88 × 60 mm panel
    # was saved at 87.84 × 59.97 mm), and a script may resize it: a panel is saved at its place
    # size (rule 3); forward=False leaves the window as it is.
    size = getattr(fig, "_idofig", {}).get("size_in")
    have = tuple(fig.get_size_inches())
    if size is not None and have != size:
        undo.callback(fig.set_size_inches, *have, False)
        fig.set_size_inches(*size, forward=False)


class Panels(dict):
    """Panel id → matplotlib Figure, in the order requested."""

    def __init__(self, ctx: Context, items):
        super().__init__(items)
        self.ctx = ctx


def panels(*ids: str, figure: str | None = None, layout: str | None = "constrained") -> Panels:
    """Create one matplotlib Figure per panel, at the panel's physical size from figure.json.

    ``layout`` is passed to matplotlib (``"constrained"`` by default, so style overrides
    re-flow the layout; ``None`` if the script positions its axes itself). Do not call
    ``tight_layout()`` afterwards: it runs once, before overrides are applied.
    """
    if not ids:
        raise ContextError("idofig.panels() needs at least one panel id")
    ctx = resolve_context(figure)
    _use_agg()  # after the context: a call that fails changes nothing
    import matplotlib.pyplot as plt

    from .mplsetup import apply_rc

    apply_rc(ctx.journal)
    out = []
    for pid in ids:
        entry = S.panel_entry(ctx.figure, pid)
        if entry is None:
            raise ContextError(
                f"panel {pid!r} is not in {rel(ctx.project.figure_json(ctx.figure_id), ctx.project.root)}; "
                f"add it there (or with `idofig add-panel {ctx.figure_id} {pid}`)"
            )
        if "image" in entry:
            raise ContextError(f"panel {pid!r} is an image panel; it is placed, not drawn")
        size = (mm_to_in(entry["place"]["w"]), mm_to_in(entry["place"]["h"]))
        f = plt.figure(figsize=size, dpi=72, layout=layout)
        f._idofig = {"panel": pid, "figure": ctx.figure_id, "size_in": size}  # what each save draws it at
        out.append((pid, f))
    return Panels(ctx, out)


def panel(pid: str, *, figure: str | None = None, layout: str | None = "constrained"):
    """One panel's matplotlib Figure (see :func:`panels`)."""
    return panels(pid, figure=figure, layout=layout)[pid]


def name(ax, value: str):
    """Give an axes a stable name; its parts become ``<value>.xlabel`` and so on."""
    from .project import check_id

    ax._idofig_name = check_id("axes", value)
    return ax


def colorbar(mappable, *, name: str | None = None, **kwargs):
    """``Figure.colorbar`` with a stable name: its axes becomes ``cbar.<name>``."""
    fig = mappable.axes.figure if getattr(mappable, "axes", None) is not None else kwargs.get("ax").figure
    cbar = fig.colorbar(mappable, **kwargs)
    if name:
        from .project import check_id

        cbar._idofig_name = check_id("colorbar", name)
    return cbar


# ---------------------------------------------------------------------------- saving


@dataclass
class SaveReport:
    panels: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    detached: dict[str, list[str]] = field(default_factory=dict)
    invalid: dict[str, list[dict]] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    figure_svg: str | None = None


def _finite(box) -> bool:
    return box is not None and all(map(math.isfinite, box.bounds))


def _bbox(artist, renderer, height_pt: float, *, clipped: bool = False):
    """``artist``'s box in the panel's points, y down; with ``clipped``, only the part its
    clipping lets through (None if it hides all of it)."""
    from matplotlib.collections import Collection
    from matplotlib.quiver import Quiver

    try:
        if not artist.get_visible():
            return None
        box = _extent(artist, renderer)
        # A quiver's box from matplotlib is finite but wrong (its positions go through the data
        # transform twice: arrows drawn at [196, 144, 330, 263] pt were boxed 7 m across), so it
        # is measured from its marks too.
        if isinstance(artist, Collection) and (not _finite(box) or isinstance(artist, Quiver)):
            box, clipped = _collection_extent(artist), True
        if box is not None and clipped:
            box = _clip(artist, box)
    except Exception:
        return None
    if not _finite(box):
        return None
    if box.width == 0 and box.height == 0:
        return None
    r = lambda v: round(float(v), 3)  # noqa: E731
    return [r(box.x0), r(height_pt - box.y1), r(box.x1), r(height_pt - box.y0)]


def _collection_extent(coll):
    """Where a collection drew its marks, in display units: its paths through the transforms its
    own draw uses (``_prepare_points``). matplotlib 3.11 boxes a scatter, a LineCollection, a
    pcolor, a hexbin or an eventplot as infinite: 118 of a ported project's 152 collections had
    no box, so a canvas could not select a series and an annotation anchored to one detached.
    Only such a box (or a quiver's, see :func:`_bbox`) is computed here; :func:`_bbox` clips it."""
    import numpy as np
    from matplotlib.collections import EllipseCollection
    from matplotlib.path import get_path_collection_extents
    from matplotlib.quiver import Quiver
    from matplotlib.transforms import Affine2D

    sizes = coll.get_sizes() if hasattr(coll, "set_sizes") else None
    if sizes is not None and len(sizes):
        # A mark's scale is what the last draw set, for its dpi: a rasterized scatter, drawn at
        # savefig.dpi (600), was boxed 22 pt too large on every side. Set again for the dpi
        # measured, as its draw does (a RegularPolyCollection's turns them too).
        coll.set_sizes(sizes, coll.figure.dpi)
        if getattr(coll, "_rotation", 0):
            coll._transforms = Affine2D().rotate(-coll._rotation).get_matrix() @ coll._transforms
    # So are an ellipse's and a quiver arrow's (a rasterized EllipseCollection was boxed 36–57
    # pt too far out on each side).
    if isinstance(coll, EllipseCollection):
        coll._set_transforms()
    elif isinstance(coll, Quiver):
        coll._init()
    transform, offset_trf, offsets, paths = coll._prepare_points()
    transforms = coll.get_transforms()
    offsets = np.asarray(offsets, dtype=float)
    # A mark at NaN or inf is not drawn, but the extents count it at display (0, 0): a scatter
    # with one NaN point was boxed to its axes' corner. Its size and path go with it.
    keep = np.isfinite(offsets).all(axis=1)
    if not keep.all():
        if not keep.any():
            return None
        if len(transforms) == len(offsets):
            transforms = transforms[keep]
        if len(paths) == len(offsets):
            paths = [p for p, k in zip(paths, keep) if k]
        offsets = offsets[keep]
    return get_path_collection_extents(transform.frozen(), paths, transforms, offsets, offset_trf.frozen())


def _extent(artist, renderer):
    """``artist.get_window_extent``, except for a 3D axes' text, which ``Text3D.draw`` puts at its
    projection only while it draws: measured after, "peak" drawn at (162, 54) pt was boxed at
    (6758, -6558), 2314 mm outside its panel. It is measured where its draw puts it."""
    art3d = sys.modules.get("mpl_toolkits.mplot3d.art3d")  # imported by any 3D axes
    if art3d is None or not isinstance(artist, art3d.Text3D):
        return artist.get_window_extent(renderer)
    import numpy as np
    from matplotlib import cbook
    from mpl_toolkits.mplot3d import proj3d

    at = np.array([artist._x, artist._y, artist._z], dtype=float)
    xs, ys, zs = np.array([at, at + artist._dir_vec]).T  # the point, and one along the text's direction
    project = getattr(proj3d, "_scale_proj_transform", None)  # matplotlib 3.11: through the axes' scales
    px, py, _ = project(xs, ys, zs, artist.axes) if project else proj3d.proj_transform(xs, ys, zs, artist.axes.M)
    angle = art3d._norm_text_angle(math.degrees(math.atan2(py[1] - py[0], px[1] - px[0])))
    with cbook._setattr_cm(artist, _x=px[0], _y=py[0], _rotation=angle):
        return artist.get_window_extent(renderer)


def _clip(artist, box):
    """The part of ``box`` its artist's clipping lets through, or None. matplotlib measures a
    text whole: a point label (``clip_on=True``) outside a zoomed view, which nobody sees, was
    reported 109 mm outside its panel. Texts and the collections idofig measures are clipped;
    other data marks keep matplotlib's whole box (build.compliance does not check them)."""
    from matplotlib.transforms import Bbox

    if not artist.get_clip_on():
        return box
    path = artist.get_clip_path()
    for clip in (artist.get_clip_box(), path.get_fully_transformed_path().get_extents() if path is not None else None):
        if clip is not None:
            cut = Bbox.intersection(box, clip)
            # Hidden when clipping takes a side the box had: a horizontal LineCollection has no
            # height to lose (dropped, it ran across its axes).
            if cut is None or cut.width <= 0 < box.width or cut.height <= 0 < box.height:
                return None
            box = cut
    return box


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _axes_info(ax, renderer, height_pt: float, mats: dict) -> dict:
    box = _bbox(ax, renderer, height_pt) or [0, 0, 0, 0]
    info = {
        "bbox": box,
        "xscale": ax.get_xscale(),
        "yscale": ax.get_yscale(),
        "xlim": [float(v) for v in ax.get_xlim()],
        "ylim": [float(v) for v in ax.get_ylim()],
    }
    if id(ax) in mats and box[2] > box[0]:
        # Scaled or rotated (0.7.0): `bbox` is the box around the turned frame; `frame` is the
        # frame before the turn and `matrix` maps it (and a data point placed in it) to the panel.
        from .styling import map_box

        m = mats[id(ax)][1]
        info.update(bbox=map_box(box, m), frame=box, matrix=[round(v, 6) for v in m])
    return info


def _host_transform(part, table, mats: dict):
    """The (matrix, scale) of the scaled or rotated axes a part is drawn in, or None: the part's
    own axes (an axes' is itself), else its parent's, walked up (a legend's texts have none),
    and an inset's parent axes (its group is inside its parent's)."""
    artist = part.artists[0]
    ax = artist if part.kind == "axes" else getattr(artist, "axes", None)
    parent = part.parent
    while ax is None and parent in table.parts:
        up = table.parts[parent]
        ax = up.artists[0] if up.kind == "axes" else getattr(up.artists[0], "axes", None)
        parent = up.parent
    while ax is not None:
        if id(ax) in mats:
            return mats[id(ax)][1:]
        if ax.axes is ax:
            return None
        ax = ax.axes
    return None


def _ships_with_matplotlib(path: str) -> bool:
    """A face from matplotlib's own mpl-data (DejaVu Sans, DejaVu Sans Mono, …): the same file on
    every machine with the same matplotlib, which the lock records — as reproducible as ours."""
    import matplotlib

    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(matplotlib.get_data_path())]) == \
            os.path.realpath(matplotlib.get_data_path())
    except ValueError:
        return False


def _check_fonts(table) -> list[str]:
    from matplotlib import font_manager

    from .mplsetup import FONT_FAMILY

    bad: dict[str, str | None] = {}  # family → the face a generic family resolves to here
    for part in table.parts.values():
        if part.kind != "text":
            continue
        for artist in part.artists:
            try:
                fam = artist.get_fontfamily()
            except Exception:
                continue
            for f in fam:
                if f == FONT_FAMILY:
                    continue
                # A generic family ('sans-serif', …) is checked as the face it resolves to. Given
                # as a string, findfont reads a fontconfig pattern ('-' starts a size) and raised,
                # so it was skipped: Arial first in `font.sans-serif` warned of nothing. A
                # one-item list is a family, never a pattern.
                try:
                    path = font_manager.findfont(font_manager.FontProperties(family=[f]), fallback_to_default=False)
                except ValueError:
                    bad[f] = None
                    continue
                if "LiberationSans" not in os.path.basename(path) and not _ships_with_matplotlib(path):
                    generic = f.lower() in font_manager.font_family_aliases
                    bad[f] = font_manager.get_font(path).family_name if generic else None
    out = []
    for f in sorted(bad):
        what = f"font {f!r}" + (f" resolves to {bad[f]!r} here, which" if bad[f] else "")
        out.append(f"{what} is not bundled with idofig; this panel may lay out differently on other machines")
    return out


# The settings a saved panel depends on for its size, its text and its bytes (rule 4).
SAVE_RC = {"svg.fonttype": "none", "svg.hashsalt": "idofig", "savefig.bbox": None, "savefig.pad_inches": 0}


def _svg(fig) -> str:
    """The panel's SVG. A panel is its printed size and its text stays text, whatever the
    script set: a project style that turns on ``savefig.bbox = "tight"`` would otherwise
    crop the panel (rule 3), and ``svg.fonttype = "path"`` would hide every font size from
    the checker."""
    import matplotlib

    buf = StringIO()
    with matplotlib.rc_context(SAVE_RC):
        fig.savefig(buf, format="svg", bbox_inches=fig.bbox_inches,
                    metadata={"Creator": None, "Date": None, "Format": None, "Type": None})
    return buf.getvalue()


def _flush_raster(renderer) -> None:
    """Emit the image of the rasterized artists drawn so far (what matplotlib does after a
    rasterized artist when it does not composite)."""
    if getattr(renderer, "_rasterizing", False) and renderer._raster_depth == 0:
        renderer.stop_rasterizing()
        renderer._rasterizing = False


def _draw_named(artist, plain, raster_name, renderer) -> None:
    """A named artist's ``draw`` during a save (see :func:`_instrument`)."""
    # A hidden artist draws nothing, nor does an annotation whose point is outside its axes
    # (its draw returns on `_check_xy`): counted drawn, it got matplotlib's 1 pt box at the
    # panel's corner.
    check = getattr(artist, "_check_xy", None)
    drawn = artist.get_visible() and (check is None or bool(check(renderer)))
    if drawn:
        artist._idofig_drawn = True
    # Wrapped, a part that draws nothing left an empty <g id> in the SVG (and no box).
    if raster_name is None or not drawn:
        plain(renderer)
        return
    _flush_raster(renderer)  # a previous part's pending image must not land in this group
    renderer.open_group(raster_name, gid=raster_name)
    try:
        plain(renderer)
        _flush_raster(renderer)
    finally:
        renderer.close_group(raster_name)


def _recording(artist, plain, *args, **kwargs):
    """``plain`` (an image's ``make_image``), recording that the artist was drawn when visible."""
    if artist.get_visible():
        artist._idofig_drawn = True
    return plain(*args, **kwargs)


def _without_gid(artist, plain, renderer) -> None:
    """``plain`` (a 3D axis' ``draw_pane`` or ``draw_grid``) with the artist's gid off."""
    gid = artist.get_gid()
    artist.set_gid(None)
    try:
        plain(renderer)
    finally:
        artist.set_gid(gid)


def _instrument(table, undo) -> None:
    """Wrap the named artists' draws for the save that writes the panel (``undo`` unwraps them).

    * Only what is drawn gets a box (``_idofig_drawn``): matplotlib measures the labels of an
      axes turned off, anything in a hidden axes and a hidden legend's entries all the same,
      and the ink check flagged them at their default places. An image an axes composites is
      asked only for its image (``make_image``), which counts.
    * A rasterized part whose name is not positional keeps it: its ``<image>`` goes in ``<g
      id="<name>">`` (matplotlib opens the part's group on the raster renderer, so it never
      reached the SVG). Positional ones still share one image: an image each made 150 traces
      1.7 → 4.4 MB.
    * A 3D axis opens its pane and grid groups with its gid too; only the axis keeps it.
    """
    for name, part in table.parts.items():
        if part.group:
            continue
        artist = part.artists[0]
        artist._idofig_drawn = False
        raster_name = name if artist.get_rasterized() and part.stability != "positional" else None
        undo.method(artist, "draw", partial(_draw_named, artist, artist.draw, raster_name))
        if part.kind == "image":
            undo.method(artist, "make_image", partial(_recording, artist, artist.make_image))
        for method in ("draw_pane", "draw_grid"):  # an Axis3D's
            if part.kind == "axis" and hasattr(artist, method):
                undo.method(artist, method, partial(_without_gid, artist, getattr(artist, method)))


def _save_one(ctx: Context, pid: str, fig, report: SaveReport) -> tuple[str, str]:
    from . import naming, styling
    from .build import RENDER
    from . import svgpost
    from .svgpost import finish_panel_svg

    style_path = ctx.project.panel_dir(ctx.figure_id, pid) / "style.json"
    style = S.load_style(style_path)
    sreport = styling.StyleReport()

    table = naming.assign_structural(fig)
    with styling.Undo() as undo:  # what the save changes to write the panel, put back once it is written
        undo.callback(styling.forget_offsets, table)
        _on_agg(fig, undo)
        layout_warnings = styling.apply_layout(fig, style.get("layout"), undo)
        styling.tick_params_from_style(fig, table, style)
        styling.apply(table, style, sreport, final=False)
        fig.canvas.draw()
        naming.assign_ticks(fig, table)
        styling.apply(table, style, sreport, final=True)

        moves = styling.offsets(table)
        if moves:
            # Parts move within the layout a save computes, frozen: `fig.canvas.draw()` measures
            # text otherwise, and frozen after it the axes sat 0.68 pt off. A panel with no
            # offset is saved once, as before (tests/golden/).
            _svg(fig)
            styling.apply_offsets(fig, moves, undo)
        _instrument(table, undo)
        svg_text = _svg(fig)
        mats = styling.axes_transforms(fig)
        svg_text, unplaced = svgpost.transform_groups(
            svg_text, {table.axes_names[k]: m for k, (_, m, _) in mats.items()
                       if k in table.axes_names and table.parts[table.axes_names[k]].artists[0]._idofig_drawn})
        width_pt = fig.get_figwidth() * PT_PER_IN
        height_pt = fig.get_figheight() * PT_PER_IN
        # Boxes are in the SVG's units, points, at 72 dpi whatever the figure's: measured at a
        # producer's `set_dpi(300)`, every box was 300/72 too large, far outside the panel.
        undo.set(fig, "dpi", 72)
        parts, axes, roles = _measure(fig, table, sreport, height_pt, mats)

    warnings = list(table.warnings) + layout_warnings + _check_fonts(table)
    warnings += [f"{name}: scale/rotate had no effect: its group is not in panel.svg (a rasterized axes "
                 f"with a positional name); name it" for name in unplaced]
    trim = None
    if style.get("trim", "trim_mm" in style):  # trim_mm alone turns it on; trim: false keeps it off
        trim = _trim(parts, axes, width_pt, height_pt, style.get("trim_mm", 0.0) * PT_PER_MM)
        if trim is None:
            warnings.append("style.json trim had no effect: the panel draws nothing to crop to")
    manifest = {
        "schema": 1,
        "figure": ctx.figure_id,
        "panel": pid,
        # How this idofig draws (build.RENDER): the lock records it from here, so a panel an older
        # idofig drew is stale, and the ink check skips the boxes an older one measured.
        "render": RENDER,
        "size": {"w_pt": round(width_pt, 3), "h_pt": round(height_pt, 3),
                 "w_mm": round(pt_to_mm(width_pt), 3), "h_mm": round(pt_to_mm(height_pt), 3)},
        **({"trim": trim} if trim else {}),
        "parts": parts,
        "axes": axes,
        "style": {"applied": sreport.applied, "detached": sreport.detached, "invalid": sreport.invalid},
        "warnings": warnings,
    }
    svg = finish_panel_svg(svg_text, panel=pid, roles=roles)
    if sreport.detached:
        report.detached[pid] = list(sreport.detached)
    if sreport.invalid:
        report.invalid[pid] = list(sreport.invalid)
    if warnings:
        report.warnings[pid] = warnings
    try:
        return svg, dump_json(manifest)
    except (ValueError, TypeError) as exc:
        # A value get_props did not clean (a NaN, an array) is named with its panel, not left a
        # bare encoder traceback.
        raise IdofigError(f"{ctx.figure_id}/{pid}: the manifest holds a value JSON cannot carry ({exc})") from None


def _trim(parts: dict, axes: dict, width_pt: float, height_pt: float, margin_pt: float) -> dict | None:
    """The box the drawn ink fills plus ``margin_pt``, within the panel, as ``{x_pt, y_pt, w_pt,
    h_pt}`` in the panel's points; every box in ``parts`` and ``axes`` is moved to be measured
    from its corner, which compose places at the panel's place. Measured after the offsets, so
    a nudged label is inside. A background (the panel's, an axes') is not ink. Nothing is
    rescaled (rule 3): the panel.svg keeps its drawn size, compose crops it."""
    boxes = [pt["bbox"] for pt in parts.values()
             if pt.get("bbox") and not pt.get("group") and pt.get("role") != "background"]
    boxes += [a["bbox"] for a in axes.values() if a.get("bbox") and a["bbox"][2] > a["bbox"][0]]
    ink = _union(boxes)
    if ink is None:
        return None
    x0, y0 = max(0.0, ink[0] - margin_pt), max(0.0, ink[1] - margin_pt)
    x1, y1 = min(width_pt, ink[2] + margin_pt), min(height_pt, ink[3] + margin_pt)
    if x1 <= x0 or y1 <= y0:
        return None
    r = lambda v: round(float(v), 3)  # noqa: E731
    x0, y0 = r(x0), r(y0)
    for entry in [*parts.values(), *axes.values()]:
        for key in ("bbox", "frame"):
            b = entry.get(key)
            if b:
                entry[key] = [r(b[0] - x0), r(b[1] - y0), r(b[2] - x0), r(b[3] - y0)]
        if "matrix" in entry:  # measured from the crop's corner too: T(-x0, -y0) ∘ M ∘ T(x0, y0)
            a, b, c, d, e, f = entry["matrix"]
            entry["matrix"] = [a, b, c, d, round(e + a * x0 + c * y0 - x0, 6), round(f + b * x0 + d * y0 - y0, 6)]
    return {"x_pt": x0, "y_pt": y0, "w_pt": r(x1 - x0), "h_pt": r(y1 - y0)}


def _measure(fig, table, sreport, height_pt: float, mats: dict) -> tuple[dict, dict, dict]:
    """The manifest's parts and axes, measured on the figure the save just wrote (its offsets
    still applied), and the roles the SVG marks. A part drawn in a scaled or rotated axes is
    boxed around its turned box (``mats``, from ``styling.axes_transforms``), and records the
    scale it prints at (``effective_scale``), which the size and stroke checks multiply by."""
    import numpy as np

    from . import props as P
    from . import styling

    from matplotlib.backends.backend_svg import RendererSVG

    # Measured with the text metrics the SVG was laid out with, the SVG renderer's. Agg's round a
    # text to whole pixels at 72 dpi and, under matplotlib < 3.11, pad a math text a pixel a side:
    # a `log$_{10}$` xlabel whose ink was 1.2 mm inside its panel was boxed 0.7 mm outside it.
    renderer = RendererSVG(fig.get_figwidth() * PT_PER_IN, height_pt, StringIO())
    parts: dict[str, dict] = {}
    roles: dict[str, str] = {}
    for n, part in table.parts.items():
        entry: dict = {"kind": part.kind, "role": part.role, "stability": part.stability}
        if part.parent:
            entry["parent"] = part.parent
        if part.group:
            entry["group"] = True
            entry["members"] = part.members
            entry["bbox"] = _union(parts[m].get("bbox") for m in part.members if m in parts)
        else:
            artist = part.artists[0]
            entry["bbox"] = (_bbox(artist, renderer, height_pt, clipped=part.kind == "text")
                             if artist._idofig_drawn else None)
            host = _host_transform(part, table, mats) if mats else None
            if host is not None:
                if entry["bbox"]:
                    entry["bbox"] = styling.map_box(entry["bbox"], host[0])
                if host[1] != 1:
                    entry["effective_scale"] = round(host[1], 6)
            if part.kind == "axis" and not artist._idofig_drawn:
                # An axis has no box, drawn or not, so this says it was not (an axes turned off
                # with axis("off"), a hidden axes): its tick marks were held to the line weight.
                entry["drawn"] = False
            # What an editor shows and compares an override with, less what the role refuses.
            refused = P.REFUSED_BY_ROLE.get(part.role, {})
            entry["props"] = {k: v for k, v in styling.get_props(artist, part.kind).items() if k not in refused}
            if part.kind == "collection" and "linewidth" in entry["props"] and entry["props"]["linewidth"] is None:
                # Marks of several widths have none; the stroke check reads the thinnest drawn
                # (read from the first mark, [1.0, 0.1] passed Nature's 0.25 pt).
                drawn = [w for w in np.atleast_1d(artist.get_linewidth()) if 0 < w < math.inf]  # NaN is neither
                if drawn:
                    entry["thinnest_pt"] = round(float(min(drawn)), 3)
            if part.role in {"background", "legend-frame"}:
                roles[n] = part.role
        if n in sreport.base:
            entry["base"] = sreport.base[n]
        parts[n] = entry

    axes = {}
    for ax in fig.axes:
        an = table.axes_names.get(id(ax))
        if an:
            axes[an] = _axes_info(ax, renderer, height_pt, mats)
    return parts, axes, roles


def _discovered(root: Path) -> list[str]:
    """Project files this process imported (helpers a producer uses), for staleness."""
    out = set()
    skip = {".venv", "venv", ".idofig", "site-packages", "node_modules", ".git"}
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f or not f.endswith(".py"):
            continue
        try:
            p = Path(f).resolve()
            relp = p.relative_to(root)
        except (ValueError, OSError):
            continue
        if any(part in skip for part in relp.parts):
            continue
        out.add(relp.as_posix())
    return sorted(out)


def save(*objs, figure: str | None = None) -> SaveReport:
    """Write each panel's SVG and manifest.

    Accepts the result of :func:`panels`, a single Figure made by :func:`panel`, or several.
    When the script runs outside ``idofig build`` the panels are published in place and the
    figure is recomposed.
    """
    figs: list = []
    ctx: Context | None = None
    for obj in objs:
        if isinstance(obj, Panels):
            ctx = ctx or obj.ctx
            figs.extend(obj.items())
        elif isinstance(obj, dict):
            figs.extend(obj.items())
        elif isinstance(obj, (list, tuple)):
            for f in obj:
                figs.append((f._idofig["panel"], f))
        else:
            info = getattr(obj, "_idofig", None)
            if info is None:
                raise ContextError("idofig.save() takes figures made by idofig.panels() or idofig.panel()")
            figs.append((info["panel"], obj))
    if ctx is None:
        ctx = resolve_context(figure or (figs[0][1]._idofig["figure"] if figs else None))

    report = SaveReport()
    outputs: list[tuple[str, str, str]] = []
    for pid, fig in figs:
        if ctx.only is not None and pid not in ctx.only:
            report.skipped.append(pid)
            continue
        svg, manifest = _save_one(ctx, pid, fig, report)
        outputs.append((pid, svg, manifest))
        report.panels.append(pid)

    if ctx.staged:
        for pid, svg, manifest in outputs:
            d = ctx.output_dir / pid
            write_atomic(d / "panel.svg", svg)
            write_atomic(d / "manifest.json", manifest)
        from .build import current_versions

        write_atomic(ctx.output_dir / "_run.json",
                     dump_json({"discovered": _discovered(ctx.project.root), "versions": current_versions()}))
    else:
        for pid, svg, manifest in outputs:
            d = ctx.project.panel_dir(ctx.figure_id, pid)
            write_atomic(d / "panel.svg", svg)
            write_atomic(d / "manifest.json", manifest)
        from .build import after_direct_run

        report.figure_svg = after_direct_run(
            ctx.project, ctx.figure_id, [pid for pid, _, _ in outputs], ctx.script, _discovered(ctx.project.root)
        )
    for pid, items in report.detached.items():
        print(f"idofig: {ctx.figure_id}/{pid}: {len(items)} style override(s) detached: {', '.join(items)}",
              file=sys.stderr)
    for pid, items in report.invalid.items():
        for it in items:
            print(f"idofig: {ctx.figure_id}/{pid}: ignored {it['part']}.{it['prop']}: {it['reason']}",
                  file=sys.stderr)
    return report


def mm(value: float) -> float:
    """Millimetres → inches, for the rare figsize or axes position a script sets itself."""
    return mm_to_in(value)


def pt(value_mm: float) -> float:
    """Millimetres → points."""
    from .units import mm_to_pt

    return mm_to_pt(value_mm)


def axes_mm(fig, left: float, bottom: float, width: float, height: float, **kwargs):
    """Add an axes at an exact position in millimetres from the panel's bottom-left."""
    w_mm = fig.get_figwidth() * 25.4
    h_mm = fig.get_figheight() * 25.4
    return fig.add_axes((left / w_mm, bottom / h_mm, width / w_mm, height / h_mm), **kwargs)

