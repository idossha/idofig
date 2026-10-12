"""``idofig.image``: place a raster render in a panel at its own resolution (0.13.0).

::

    idf.image(fig, "results/renders/lh_lateral.png", 2, 10, 30, 24, name="brain")  # brain, brain.image

A render made elsewhere (Blender, a nilearn or PyVista screenshot, a microscope image) is input
data the producer reads: list the file in the producer's ``inputs``. It is fitted inside the box,
its aspect kept, centred, and embedded unresampled (``interpolation="none"``): the SVG carries
its own pixels, never ones resampled to a canvas dpi. A render with an alpha channel is cropped
to what it drew (:func:`crop_alpha`) and its transparent pixels take the colour of the nearest
drawn one (:func:`bleed`), so a viewer or a resampling filter that blends colour and alpha
separately draws no dark fringe around it. numpy only.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .errors import IdofigError
from .naming import mark_part


def crop_alpha(rgba: np.ndarray, pad: int = 0) -> np.ndarray:
    """``rgba`` (H, W, 4) cropped to its pixels with any alpha, plus ``pad`` pixels where the
    image has them; an image without alpha, or with nothing drawn, is returned as it is."""
    rgba = np.asarray(rgba)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        return rgba
    rows = np.flatnonzero(rgba[..., 3].any(axis=1))
    cols = np.flatnonzero(rgba[..., 3].any(axis=0))
    if rows.size == 0:
        return rgba
    top, left = max(rows[0] - pad, 0), max(cols[0] - pad, 0)
    return rgba[top:rows[-1] + pad + 1, left:cols[-1] + pad + 1]


def _nearest_along_rows(have: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """For every pixel, the column of the nearest ``have`` pixel in its row (left on a tie) and
    the distance to it (inf when its row has none)."""
    w = have.shape[1]
    cols = np.broadcast_to(np.arange(w), have.shape)
    left = np.maximum.accumulate(np.where(have, cols, -1), axis=1)
    right = np.minimum.accumulate(np.where(have, cols, w)[:, ::-1], axis=1)[:, ::-1]
    d_left = np.where(left >= 0, cols - left, np.inf)
    d_right = np.where(right < w, right - cols, np.inf)
    use_left = d_left <= d_right
    return np.where(use_left, left, right), np.where(use_left, d_left, d_right)


def bleed(rgba: np.ndarray) -> np.ndarray:
    """A copy of ``rgba`` (H, W, 4) whose fully transparent pixels have the colour of the nearest
    pixel with any alpha, along its row or its column (the row on a tie), repeated until every
    pixel has one; alpha is unchanged, so the image looks the same. matplotlib and many viewers
    filter colour and alpha separately: the black a renderer leaves under alpha 0 fringed every
    edge. An image without alpha, or with nothing drawn, is returned as it is."""
    out = np.array(rgba, copy=True)
    if out.ndim != 3 or out.shape[2] != 4:
        return out
    have = out[..., 3] > 0
    if have.all() or not have.any():
        return out
    rows, cols = np.indices(have.shape)
    while not have.all():
        c_row, d_row = _nearest_along_rows(have)
        r_col, d_col = (a.T for a in _nearest_along_rows(have.T))
        by_row = d_row <= d_col
        fill = ~have & np.isfinite(np.minimum(d_row, d_col))
        src_r = np.where(by_row, rows, r_col)[fill].astype(int)
        src_c = np.where(by_row, c_row, cols)[fill].astype(int)
        out[..., :3][fill] = out[..., :3][src_r, src_c]
        have = have | fill
    return out


def _read(src) -> np.ndarray:
    if isinstance(src, (str, Path)):
        import matplotlib.image as mpimg

        path = Path(src)
        if not path.is_file():
            raise IdofigError(f"{path} does not exist (a relative path is read from the project root)")
        try:
            return np.asarray(mpimg.imread(path))
        except Exception as exc:  # Pillow and matplotlib raise a different type per format
            raise IdofigError(f"{path}: not an image idofig can read ({type(exc).__name__}: {exc})") from None
    pixels = np.asarray(src)
    if pixels.ndim not in (2, 3) or (pixels.ndim == 3 and pixels.shape[2] not in (3, 4)) or not pixels.size:
        raise IdofigError(f"an image is (H, W), (H, W, 3) or (H, W, 4) pixels; got shape {pixels.shape}")
    return pixels


def image(fig, src, left: float, bottom: float, width: float, height: float, *, name: str,
          trim: bool = True, **kwargs):
    """Show the image ``src`` (a file matplotlib reads — PNG, or JPEG and TIFF through Pillow —
    or an array) in the box ``left, bottom, width, height`` (mm from the panel's bottom-left, as
    :func:`idofig.axes_mm`), as large as fits with its aspect kept, centred. Returns its axes,
    named ``name``, axis off; the image is ``<name>.image``. With ``trim`` an image with alpha
    is cropped to what it drew and bled (:func:`crop_alpha`, :func:`bleed`). ``kwargs`` go to
    ``imshow`` (``cmap``, ``vmin``, ``vmax`` for a 2-D array); ``interpolation`` is ``"none"``
    unless given: the file's own pixels are embedded. The axes' data coordinates are the file's
    pixels (x right, y down), whatever was cropped: draw on it at a point measured on the render."""
    from . import draw

    if not (width > 0 and height > 0):
        raise IdofigError(f"an image's box needs a positive width and height (got {width} × {height} mm)")
    pixels = _read(src)
    top = left_px = 0
    if trim and pixels.ndim == 3 and pixels.shape[2] == 4 and pixels[..., 3].any():
        rows = np.flatnonzero(pixels[..., 3].any(axis=1))
        cols = np.flatnonzero(pixels[..., 3].any(axis=0))
        top, left_px = int(rows[0]), int(cols[0])
        pixels = bleed(pixels[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1])
    h_px, w_px = pixels.shape[:2]
    w = min(width, height * w_px / h_px)
    h = w * h_px / w_px
    ax = draw.name(draw.axes_mm(fig, left + (width - w) / 2, bottom + (height - h) / 2, w, h), name)
    kwargs.setdefault("interpolation", "none")
    # The file's own pixel coordinates (x right, y down, centres on whole numbers), cropped or not,
    # so points measured on the render (electrodes, anchors) are drawn where they were measured.
    kwargs.setdefault("extent", (left_px - 0.5, left_px + w_px - 0.5, top + h_px - 0.5, top - 0.5))
    mark_part(ax.imshow(pixels, aspect="auto", **kwargs), "image")
    ax.set_axis_off()
    return ax
