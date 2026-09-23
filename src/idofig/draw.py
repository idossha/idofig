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

import os
import sys
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from . import journals as J
from . import spec as S
from .errors import ContextError, IdofigError
from .fsutil import dump_json, rel, write_atomic
from .project import Project, find_project
from .units import PT_PER_IN, mm_to_in, pt_to_mm


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
    import matplotlib.pyplot as plt

    from .mplsetup import apply_rc

    if not ids:
        raise ContextError("idofig.panels() needs at least one panel id")
    ctx = resolve_context(figure)
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
        place = entry["place"]
        f = plt.figure(figsize=(mm_to_in(place["w"]), mm_to_in(place["h"])), dpi=72, layout=layout)
        f._idofig = {"panel": pid, "figure": ctx.figure_id}
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


def _bbox(artist, renderer, height_pt: float):
    try:
        if not artist.get_visible():
            return None
        box = artist.get_window_extent(renderer)
    except Exception:
        return None
    if box is None or not all(map(lambda v: v == v and abs(v) != float("inf"), box.bounds)):
        return None
    if box.width == 0 and box.height == 0:
        return None
    r = lambda v: round(float(v), 3)  # noqa: E731
    return [r(box.x0), r(height_pt - box.y1), r(box.x1), r(height_pt - box.y0)]


def _union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _axes_info(ax, renderer, height_pt: float) -> dict:
    box = _bbox(ax, renderer, height_pt) or [0, 0, 0, 0]
    return {
        "bbox": box,
        "xscale": ax.get_xscale(),
        "yscale": ax.get_yscale(),
        "xlim": [float(v) for v in ax.get_xlim()],
        "ylim": [float(v) for v in ax.get_ylim()],
    }


def _check_fonts(table) -> list[str]:
    from matplotlib import font_manager

    from .mplsetup import FONT_FAMILY

    bad = set()
    for part in table.parts.values():
        if part.kind != "text":
            continue
        for artist in part.artists:
            try:
                fam = artist.get_fontfamily()
            except Exception:
                continue
            for f in fam:
                if f == FONT_FAMILY or f in {"sans-serif", "sans"}:
                    continue
                try:
                    path = font_manager.findfont(f, fallback_to_default=False)
                    if "LiberationSans" not in os.path.basename(path):
                        bad.add(f)
                except ValueError:
                    bad.add(f)
    return [f"font {f!r} is not bundled with idofig; this panel may lay out differently on other machines"
            for f in sorted(bad)]


def _save_one(ctx: Context, pid: str, fig, report: SaveReport) -> tuple[str, str]:
    from . import naming, styling
    from .svgpost import finish_panel_svg

    style_path = ctx.project.panel_dir(ctx.figure_id, pid) / "style.json"
    style = S.load_style(style_path)
    sreport = styling.StyleReport()

    table = naming.assign_structural(fig)
    styling.tick_params_from_style(fig, table, style)
    styling.apply(table, style, sreport, final=False)
    fig.canvas.draw()
    naming.assign_ticks(fig, table)
    styling.apply(table, style, sreport, final=True)

    buf = StringIO()
    fig.savefig(buf, format="svg", metadata={"Creator": None, "Date": None, "Format": None, "Type": None})
    width_pt = fig.get_figwidth() * PT_PER_IN
    height_pt = fig.get_figheight() * PT_PER_IN
    renderer = fig.canvas.get_renderer()

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
            box = _bbox(artist, renderer, height_pt)
            entry["bbox"] = box
            entry["props"] = styling.get_props(artist, part.kind)
            if part.role in {"background", "legend-frame"}:
                roles[n] = part.role
        if n in sreport.base:
            entry["base"] = sreport.base[n]
        parts[n] = entry

    axes = {}
    for ax in fig.axes:
        an = table.axes_names.get(id(ax))
        if an:
            axes[an] = _axes_info(ax, renderer, height_pt)

    warnings = list(table.warnings) + _check_fonts(table)
    manifest = {
        "schema": 1,
        "figure": ctx.figure_id,
        "panel": pid,
        "size": {"w_pt": round(width_pt, 3), "h_pt": round(height_pt, 3),
                 "w_mm": round(pt_to_mm(width_pt), 3), "h_mm": round(pt_to_mm(height_pt), 3)},
        "parts": parts,
        "axes": axes,
        "style": {"applied": sreport.applied, "detached": sreport.detached, "invalid": sreport.invalid},
        "warnings": warnings,
    }
    svg = finish_panel_svg(buf.getvalue(), panel=pid, roles=roles)
    if sreport.detached:
        report.detached[pid] = list(sreport.detached)
    if sreport.invalid:
        report.invalid[pid] = list(sreport.invalid)
    if warnings:
        report.warnings[pid] = warnings
    return svg, dump_json(manifest)


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

