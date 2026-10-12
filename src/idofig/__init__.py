"""idofig — reproducible, editable publication figures.

Code draws (``idofig.panels`` → matplotlib → ``idofig.save``), a small spec composes
(``figures/<id>/figure.json``), and a canvas or an agent refines through two plain files:
``figure.json`` (layout, letters, annotations) and each panel's ``style.json`` (named-part
overrides). ``idofig build`` rebuilds exactly what is stale; ``idofig check`` proves a figure
reproduces byte for byte.

Importing ``idofig`` is cheap: matplotlib is imported only when a drawing function is used.
"""

from ._version import __version__

_DRAW = {"panels", "panel", "name", "colorbar", "save", "mm", "pt", "axes_mm", "resolve_context"}

__all__ = ["__version__", *sorted(_DRAW | {"mesh", "image"})]


def __getattr__(attr: str):
    if attr in _DRAW:
        from . import draw

        return getattr(draw, attr)
    if attr == "mesh":  # its module is `meshes`: a submodule named `mesh` would shadow the function
        from .meshes import mesh

        return mesh
    if attr == "image":  # its module is `rasters`, as `mesh`'s is `meshes`
        from .rasters import image

        return image
    raise AttributeError(f"module 'idofig' has no attribute {attr!r}")
