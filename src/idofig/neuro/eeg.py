"""``idofig.neuro.topomap``: a scalp map drawn by mne, its parts named (0.13.0; the ``eeg`` extra).

::

    ax = idf.name(idf.axes_mm(fig, 2, 2, 20, 20), "topo")
    im = neuro.topomap(ax, t_values, info, mask=cluster)
    idf.colorbar(im, name="t", cax=idf.axes_mm(fig, 24, 4, 1.5, 16))

mne interpolates and draws; idofig names what it drew — ``topo.field`` (the map), ``topo.head``,
``topo.nose``, ``topo.ear.left``, ``topo.ear.right`` (role ``outline``), ``topo.mask``,
``topo.sensors``, ``topo.contours`` — so style.json restyles a dot or an outline by name.
"""

from __future__ import annotations

import numpy as np

from ..errors import IdofigError
from ..naming import mark_part
from ..units import PT_PER_MM
from . import require


def _mask(mask, n: int) -> np.ndarray | None:
    """``mask`` (n booleans, or channel indices) as n booleans."""
    if mask is None:
        return None
    m = np.asarray(mask)
    if m.dtype == bool:
        if m.shape != (n,):
            raise IdofigError(f"mask has shape {m.shape}; there are {n} channels")
        return m
    out = np.zeros(n, dtype=bool)
    idx = m.astype(int).ravel()
    if idx.size and (idx.min() < 0 or idx.max() >= n):
        raise IdofigError(f"mask holds channel indices outside 0–{n - 1}")
    out[idx] = True
    return out


def _name_outlines(lines: list) -> None:
    """mne's head outlines by their shape, not their order: the head is the closed outline with
    the most points, the nose has three, the ears are left and right of the head's centre."""
    if not lines:
        return
    head = max(lines, key=lambda line: len(line.get_xdata()))
    x = np.asarray(head.get_xdata(), dtype=float)
    centre = (x.min() + x.max()) / 2
    mark_part(head, "head", "outline")
    for line in lines:
        if line is head:
            continue
        if len(line.get_xdata()) == 3:
            mark_part(line, "nose", "outline")
        else:
            side = "left" if np.mean(line.get_xdata()) < centre else "right"
            mark_part(line, f"ear.{side}", "outline")


def topomap(ax, values, pos, *, mask=None, sensors: bool = False, contours=0, cmap="RdBu_r", vlim=None,
            clip: bool = True, marker_mm: float = 0.8, mask_color="black", label: str | None = None,
            label_props: dict | None = None, **kwargs):
    """Draw the scalp map of ``values`` (one per channel) at ``pos`` (an mne ``Info`` or an
    (n, 2) array of positions) on ``ax`` with ``mne.viz.plot_topomap``; returns the map's image,
    for a colorbar.

    ``vlim`` defaults to ± the largest finite ``|value|``, centred on zero for the diverging
    ``cmap``. ``mask`` (n booleans, or channel indices) marks channels with filled dots
    ``marker_mm`` across in ``mask_color``; ``sensors`` draws the other channels as mne does;
    ``contours`` is mne's (0: none). With ``clip`` the map is clipped at the head outline itself
    (mne lets it run about 1 % past it). The outlines take the rc's ``axes.linewidth``. ``label``
    (a cluster's p, say) is written under the head as ``<axes>.label``, with ``label_props`` (a
    text's properties: ``color``, ``weight`` …).
    ``kwargs`` go to mne (``sphere``, ``extrapolate``, ``res``, ``image_interp``,
    ``mask_params`` merged over the dots')."""
    mne = require("mne", "eeg")
    from matplotlib import rcParams
    from matplotlib.patches import Circle

    values = np.asarray(values, dtype=float)
    if values.ndim != 1:
        raise IdofigError(f"a topomap takes one value per channel; got shape {values.shape}")
    if vlim is None:
        finite = np.abs(values[np.isfinite(values)])
        top = float(finite.max()) if finite.size and finite.max() > 0 else 1.0
        vlim = (-top, top)
    m = _mask(mask, len(values))
    size_pt = marker_mm * PT_PER_MM
    mask_params = {"marker": "o", "markerfacecolor": mask_color, "markeredgecolor": "none", "linewidth": 0,
                   "markersize": size_pt, **kwargs.pop("mask_params", {})}
    before = {id(a) for a in ax.get_children()}
    with mne.utils.use_log_level("error"):
        im, cn = mne.viz.plot_topomap(values, pos, axes=ax, show=False, mask=m, mask_params=mask_params,
                                      sensors=sensors, contours=contours, cmap=cmap, vlim=vlim, **kwargs)
    new_lines = [line for line in ax.lines if id(line) not in before]
    # The dots are the one new line with markers; mne draws the outlines without.
    mask_line = next((line for line in new_lines if m is not None and line.get_marker() not in ("None", "", None)),
                     None)
    outlines = [line for line in new_lines if line is not mask_line]
    for line in outlines:
        line.set_linewidth(rcParams["axes.linewidth"])
    _name_outlines(outlines)
    mark_part(im, "field")
    if mask_line is not None:
        mark_part(mask_line, "mask")
    if cn is not None:
        mark_part(cn, "contours")
    for coll in ax.collections:
        if id(coll) not in before and coll is not cn:
            mark_part(coll, "sensors")
    if label is not None:
        t = ax.text(0.5, -0.02, label, transform=ax.transAxes, ha="center", va="top", **(label_props or {}))
        mark_part(t, "label")
    head = next((line for line in outlines if getattr(line, "_idofig_part", ("",))[0] == "head"), None)
    if clip and head is not None:
        x, y = (np.asarray(d, dtype=float) for d in head.get_data())
        circle = Circle(((x.min() + x.max()) / 2, (y.min() + y.max()) / 2), (x.max() - x.min()) / 2,
                        transform=ax.transData)
        im.set_clip_path(circle)
        if cn is not None:
            cn.set_clip_path(circle)
    return im
