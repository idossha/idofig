"""Panel {{panel}} of {{figure}}: <say in one sentence what this panel shows>.

Inputs: {{mesh}} (listed under the producer's "inputs" in figure.json, so editing it makes the
panel stale). The view (elev, azim, roll, zoom, proj) is set on main in style.json, not here.

Build:  idofig build {{figure}}        (or run this file directly: python {{script}})
"""

import idofig as idf

p = idf.panels("{{panel}}")
ax = p["{{panel}}"].add_subplot(projection="3d")
idf.name(ax, "main")

idf.mesh(ax, "{{mesh}}")  # colour it with scalars=..., cmap=..., or color=...
ax.set_axis_off()

idf.save(p)
