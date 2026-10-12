"""``idofig.neuro``: the panels a neuroscience figure draws again and again (0.13.0).

::

    from idofig import neuro

    neuro.topomap(ax, values, info, mask=cluster)               # topo.field, topo.head, topo.mask …
    neuro.surface(ax, "data/lh.inflated", t_map, sulc="data/lh.sulc", threshold=2)  # main.mesh.left
    neuro.volume_slice(ax, "data/T1.nii.gz", axis="z", at=12, overlay="results/tmap.nii.gz",
                       roi="data/roi.nii.gz", crosshair=neuro.centroid("data/roi.nii.gz"), coordinate=True)
    neuro.surface_views(fig, 0, 0, 80, 20, {"left": "lh.pial", "right": "rh.pial"}, values)   # four views
    neuro.electrodes(ax, xy_px, ["F3", "F4"], colors=["#009E73"] * 2, signs=[1, -1])
    neuro.callouts(fig, neuro.project(ax3d, points), ["insula", "precuneus"])

Each draws on an axes the producer made and named, and names what it draws by what it is, so a
canvas or style.json addresses the head outline, the significance dots or the overlay. Each
needs an extra: ``pip install "idofig[eeg]"`` (mne) for :func:`topomap`, ``"idofig[mri]"``
(nibabel) for surfaces, slices and what is read from volumes, ``"idofig[neuro]"`` for both; the
marks (electrodes, callouts) need neither. Like
``import idofig``, importing this package imports none of them.
"""

from __future__ import annotations

# By the extra each needs; a module named like its function would shadow it once imported.
_WHERE = {
    "topomap": "eeg",
    **dict.fromkeys(("surface", "surface_views", "view_size", "view_angles", "fit", "parcel_values", "volume_slice",
                     "centroid", "line_profile", "volume_to_surface", "VIEWS"), "mri"),
    **dict.fromkeys(("electrodes", "project", "callouts", "place_labels"), "annotate"),
}

__all__ = sorted(_WHERE)


def __getattr__(attr: str):
    if attr in _WHERE:
        from importlib import import_module

        return getattr(import_module(f".{_WHERE[attr]}", __name__), attr)
    raise AttributeError(f"module 'idofig.neuro' has no attribute {attr!r}")


def require(module: str, extra: str):
    """``module`` imported, or an error that names the extra which installs it."""
    from importlib import import_module

    from ..errors import IdofigError

    try:
        return import_module(module)
    except ImportError:
        raise IdofigError(f"this panel needs {module}: pip install \"idofig[{extra}]\"") from None
