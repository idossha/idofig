"""Marks laid over a neuro panel (0.13.0; no extra): electrodes with signed discs and labels that
keep clear of each other, and callouts that name points of a 3D view with leader lines.

::

    ax = idf.image(fig, "renders/montage.png", 0, 0, 30, 30, name="montage")   # pixel coordinates
    neuro.electrodes(ax, pts[["x_px", "y_px"]], ["FT7", "Fp2", "TP7", "P8"],
                     colors=[E1, E1, E2, E2], signs=[1, -1, 1, -1])         # montage.electrode.ft7 …

    anchors = neuro.project(ax3d, centroids)                                # panel mm
    neuro.callouts(fig, anchors, ["insula", "precuneus"], name="labels")

Every size is in mm on the page, whatever the axes' data units: a disc 1.15 mm across is 1.15 mm
on a render whose pixels are its data units and on a cap map in degrees.
"""

from __future__ import annotations

import numpy as np

from ..errors import IdofigError
from ..naming import mark_part, slug

STEPS = (0.45, 1.9, 3.4)  # mm a label may stand off its electrode's disc
ANGLES = np.deg2rad(np.arange(0, 360, 30))
CLASH = 60.0  # cost per mm² of a label outside its box, over a disc or over another label


def _mm_frame(ax):
    """The transform from mm inside ``ax`` (from its bottom-left corner) to the display, which
    follows the axes wherever idofig moves it, and the axes' size in mm."""
    from matplotlib.transforms import Affine2D

    fig = ax.figure
    w_mm, h_mm = ax.bbox.width / fig.dpi * 25.4, ax.bbox.height / fig.dpi * 25.4
    return Affine2D().scale(1 / w_mm, 1 / h_mm) + ax.transAxes, (w_mm, h_mm)


def _to_mm(ax, xy) -> np.ndarray:
    """Data points of ``ax`` as mm from its bottom-left corner."""
    _, (w_mm, h_mm) = _mm_frame(ax)
    frac = ax.transAxes.inverted().transform(ax.transData.transform(np.asarray(xy, dtype=float)))
    return frac * (w_mm, h_mm)


def _text_mm(fig, s: str, **kw) -> tuple[float, float]:
    t = fig.text(0, 0, s, **kw)
    box = t.get_window_extent(fig.canvas.get_renderer())
    t.remove()
    return box.width / fig.dpi * 25.4, box.height / fig.dpi * 25.4


def _overlap(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Overlap areas of every box in ``a`` with every box in ``b`` (x0, y0, x1, y1)."""
    dx = np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0])
    dy = np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1])
    return np.clip(dx, 0, None) * np.clip(dy, 0, None)


def place_labels(xy: np.ndarray, sizes: np.ndarray, radius: float, box, obstacles: np.ndarray):
    """Where each label goes around its point (mm): one of 12 directions at one of :data:`STEPS`
    beyond the disc of ``radius``, chosen together so that the labels stay inside ``box`` (x0, y0,
    x1, y1), off every disc in ``obstacles`` (k, 3: x, y, r) and off each other, as near their
    points as that allows, beside rather than above or below them. Four labels or fewer are
    placed by trying every combination; more by improving one at a time until none moves.
    Returns the centres (n, 2), the direction (n, 2) and the step index of each."""
    u = np.stack([np.cos(ANGLES), np.sin(ANGLES)], 1)
    k_a, n = len(ANGLES), len(xy)
    lean = 0.35 * np.abs(u[:, 1])
    obs = np.c_[obstacles[:, :2] - obstacles[:, 2:] - 0.25, obstacles[:, :2] + obstacles[:, 2:] + 0.25]
    inner = np.array([box[0] + 0.3, box[1] + 0.3, box[2] - 0.3, box[3] - 0.3])
    pad = np.array([-0.35, -0.35, 0.35, 0.35])
    cand, cent, unary = [], [], []
    for i in range(n):
        w, h = sizes[i]
        reach = w / 2 * np.abs(u[:, 0]) + h / 2 * np.abs(u[:, 1])
        c = (xy[i] + u[None] * (np.array(STEPS)[:, None, None] + radius + reach[None, :, None])).reshape(-1, 2)
        bx = np.c_[c - (w / 2, h / 2), c + (w / 2, h / 2)]
        outside = (w * h) - _overlap(bx, inner[None])[:, 0]
        cost = CLASH * outside + np.repeat(np.arange(len(STEPS)), k_a) + np.tile(lean, len(STEPS))
        if len(obs):
            cost = cost + CLASH * _overlap(bx, obs).sum(1)
        cand.append(bx)
        cent.append(c)
        unary.append(cost)
    pair = {(i, j): CLASH * _overlap(cand[i] + pad, cand[j] + pad) for i in range(n) for j in range(i + 1, n)}
    m = len(STEPS) * k_a
    if n <= 4:
        total = np.zeros((m,) * n)
        for i in range(n):
            total += unary[i].reshape([m if q == i else 1 for q in range(n)])
        for (i, j), cost in pair.items():
            total += cost.reshape([m if q in (i, j) else 1 for q in range(n)])
        best = list(np.unravel_index(np.argmin(total), total.shape)) if n else []
    else:
        best = [int(np.argmin(c)) for c in unary]
        for _ in range(50):
            moved = False
            for i in range(n):
                cost = unary[i].copy()
                for j in range(n):
                    if j != i:
                        cost += pair[(i, j)][:, best[j]] if i < j else pair[(j, i)][best[j], :]
                choice = int(np.argmin(cost))
                if choice != best[i]:
                    best[i], moved = choice, True
            if not moved:
                break
    chosen = np.array([cand[i][b] for i, b in enumerate(best)]).reshape(-1, 4)
    clash = n > 1 and _overlap(chosen, chosen)[~np.eye(n, dtype=bool)].max() > 0
    if clash or (chosen[:, :2] < np.asarray(box[:2]) - 1e-9).any() or (chosen[:, 2:] > np.asarray(box[2:]) + 1e-9).any():
        raise IdofigError(f"no clear place for every electrode label in a {box[2] - box[0]:.1f} × "
                          f"{box[3] - box[1]:.1f} mm box: give a larger box, smaller labels, or labels=False")
    return (np.array([cent[i][b] for i, b in enumerate(best)]).reshape(-1, 2),
            np.array([u[b % k_a] for b in best]).reshape(-1, 2), [b // k_a for b in best])


def electrodes(ax, xy, names, *, colors="black", signs=None, radius_mm: float = 1.15, labels: bool = True,
               box=None, obstacles=None, label_color=None, fontsize=None, weight="bold", halo="white"):
    """Draw an electrode at each point ``xy`` (n, 2, in ``ax``'s data units: a render's pixels, a
    cap map's coordinates): a disc ``radius_mm`` across in its colour (``colors``, one or one
    each) with a white edge, a white + or − on it from ``signs`` (1, −1, or 0/None for none), and
    with ``labels`` its name beside it, placed clear of the other labels, of every disc and of
    ``obstacles`` (k, 3: x, y in data units and a radius in mm) inside ``box`` (x0, y0, x1, y1 mm
    from the axes' corner; default the axes) — a label set off from its disc gets a leader line.
    Labels are in the electrode's colour unless ``label_color``, over a ``halo``. A layout with
    no clear place for every label is an error, never an overlap.

    Parts: ``<axes>.electrode.<name>`` (the disc), ``….sign`` and ``….sign.v`` (+'s upright),
    ``….label``, ``….leader``. Returns the label centres (mm in the axes)."""
    import matplotlib.patheffects as pe
    from matplotlib import rcParams
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle

    names = [str(n) for n in names]
    n = len(names)
    pts = np.asarray(xy, dtype=float).reshape(-1, 2)
    if len(pts) != n:
        raise IdofigError(f"{len(pts)} points for {n} electrode names")
    from matplotlib.colors import is_color_like

    colours = [colors] * n if is_color_like(colors) else list(colors)
    if len(colours) != n:
        raise IdofigError(f"{len(colours)} colours for {n} electrodes")
    signs = [0] * n if signs is None else [int(np.sign(s or 0)) for s in signs]
    transform, (w_mm, h_mm) = _mm_frame(ax)
    at = _to_mm(ax, pts)
    keys = [slug(nm) for nm in names]
    for (ex, ey), colour, sign, key in zip(at, colours, signs, keys):
        disc = Circle((ex, ey), radius_mm, facecolor=colour, edgecolor="white", linewidth=0.6, zorder=3,
                      transform=transform, clip_on=False)
        mark_part(ax.add_patch(disc), f"electrode.{key}")
        arm = 0.55 * radius_mm
        if sign:
            bar = Line2D([ex - arm, ex + arm], [ey, ey], color="white", linewidth=0.9, solid_capstyle="butt",
                         zorder=4, transform=transform, clip_on=False)
            mark_part(ax.add_line(bar), f"electrode.{key}.sign")
        if sign > 0:
            bar = Line2D([ex, ex], [ey - arm, ey + arm], color="white", linewidth=0.9, solid_capstyle="butt",
                         zorder=4, transform=transform, clip_on=False)
            mark_part(ax.add_line(bar), f"electrode.{key}.sign.v")
    if not labels or not n:
        return None
    font = {"fontsize": fontsize or rcParams["font.size"], "weight": weight}
    sizes = np.array([_text_mm(ax.figure, nm, **font) for nm in names])
    extra = np.zeros((0, 3))
    if obstacles is not None:
        obstacles = np.asarray(obstacles, dtype=float).reshape(-1, 3)
        extra = np.c_[_to_mm(ax, obstacles[:, :2]), obstacles[:, 2]]
    discs = np.r_[np.c_[at, np.full(n, radius_mm)], extra]
    centres, dirs, steps = place_labels(at, sizes, radius_mm, box or (0, 0, w_mm, h_mm), discs)
    effects = [pe.Stroke(linewidth=1.8, foreground=halo), pe.Normal()] if halo else []
    for i, key in enumerate(keys):
        colour = label_color or colours[i]
        if steps[i] > 0:
            reach = sizes[i] / 2 @ np.abs(dirs[i])
            start, end = at[i] + dirs[i] * (radius_mm + 0.15), centres[i] - dirs[i] * (reach + 0.2)
            line = Line2D([start[0], end[0]], [start[1], end[1]], color=colour, linewidth=rcParams["axes.linewidth"],
                          zorder=2, transform=transform, clip_on=False)
            mark_part(ax.add_line(line), f"electrode.{key}.leader")
        t = ax.text(*centres[i], names[i], color=colour, ha="center", va="center", zorder=5, transform=transform,
                    clip_on=False, path_effects=effects, **font)
        mark_part(t, f"electrode.{key}.label")
    return centres


def project(ax, points) -> np.ndarray:
    """Where ``points`` (n, 3 data coordinates of a 3D axes, or n, 2 of a 2D one) are drawn, as mm
    from the panel's bottom-left: anchors for :func:`callouts`. Read from the axes as it is placed
    and turned now (``layout=None`` and ``idf.axes_mm`` keep that where it prints); a view turned
    later in style.json moves the drawing, not anchors computed before it."""
    pts = np.asarray(points, dtype=float)
    pts = pts.reshape(1, -1) if pts.ndim == 1 else pts
    if getattr(ax, "name", None) == "3d":
        if pts.shape[1] != 3:
            raise IdofigError(f"a 3D axes' points are (x, y, z); got shape {pts.shape}")
        from mpl_toolkits.mplot3d import proj3d

        x, y, _ = proj3d.proj_transform(pts[:, 0], pts[:, 1], pts[:, 2], ax.get_proj())
        pts = np.c_[x, y]
    elif pts.shape[1] != 2:
        raise IdofigError(f"a 2D axes' points are (x, y); got shape {pts.shape}")
    return ax.transData.transform(pts) / ax.figure.dpi * 25.4


def callouts(fig, anchors, labels, *, centre=None, reach: float = 4.0, spacing: float | None = None,
             name: str = "callouts", color=None, fontsize=None, gap: float = 0.4):
    """Name points of a panel: each label is set ``reach`` mm out from its anchor (mm from the
    panel's bottom-left, as :func:`project` gives) away from ``centre`` (default: the anchors'
    mean), the labels on each side at least ``spacing`` mm apart (default: 1.2 lines), a leader
    from the anchor to the label, the text ``gap`` mm beyond it — left of a left anchor, right of
    a right one. Drawn on a transparent axes over the panel named ``name``: parts
    ``<name>.<label>`` and ``<name>.<label>.leader``. Returns that axes."""
    from matplotlib import rcParams

    from .. import draw

    pts = np.asarray(anchors, dtype=float).reshape(-1, 2)
    labels = [str(s) for s in labels]
    if len(labels) != len(pts):
        raise IdofigError(f"{len(labels)} labels for {len(pts)} anchors")
    w, h = fig.get_figwidth() * 25.4, fig.get_figheight() * 25.4
    over = draw.name(draw.axes_mm(fig, 0, 0, w, h), name)
    over.set_xlim(0, w)
    over.set_ylim(0, h)
    over.set_axis_off()
    over.patch.set_visible(False)
    if not len(pts):
        return over
    size = fontsize or rcParams["font.size"]
    spacing = spacing if spacing is not None else 1.2 * size * 25.4 / 72
    mid = np.asarray(centre, dtype=float) if centre is not None else pts.mean(axis=0)
    away = pts - mid
    length = np.linalg.norm(away, axis=1, keepdims=True)
    away = np.divide(away, length, out=np.tile([1.0, 0.0], (len(pts), 1)), where=length > 1e-9)
    ends = pts + away * reach
    right = pts[:, 0] >= mid[0]
    for side in (True, False):
        idx = np.flatnonzero(right == side)
        if len(idx) < 2:
            continue
        order = idx[np.argsort(ends[idx, 1], kind="stable")]
        ys = ends[order, 1].copy()
        for k in range(1, len(ys)):  # push up until each clears the one below it …
            ys[k] = max(ys[k], ys[k - 1] + spacing)
        ys -= (ys.mean() - ends[order, 1].mean())  # … then centre the column where the labels wanted to be
        ends[order, 1] = ys
    colour = color or rcParams["text.color"]
    for (ax_, ay), (ex, ey), label, is_right in zip(pts, ends, labels, right):
        (line,) = over.plot([ax_, ex], [ay, ey], color=colour, linewidth=rcParams["axes.linewidth"], clip_on=False)
        mark_part(line, f"{slug(label)}.leader")
        t = over.text(ex + (gap if is_right else -gap), ey, label, ha="left" if is_right else "right", va="center",
                      color=colour, fontsize=size, clip_on=False)
        mark_part(t, slug(label))
    return over
