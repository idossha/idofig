"""Panel {{panel}} of {{figure}}: <say in one sentence what this panel shows>.

Inputs: <the files this reads — list them under the producer's "inputs" in figure.json>.

Build:  idofig build {{figure}}        (or run this file directly: python {{script}})
"""

import numpy as np

import idofig as idf

p = idf.panels("{{panel}}")
ax = p["{{panel}}"].subplots()
idf.name(ax, "main")

rng = np.random.default_rng(0)  # fixed seed: the panel must rebuild identically
data = rng.normal(size=(8, 12)).cumsum(axis=1)
image = ax.imshow(data, aspect="auto", cmap="viridis", interpolation="nearest")
ax.set_xlabel("time bin")
ax.set_ylabel("channel")
idf.colorbar(image, name="value", ax=ax, label="value (a.u.)")

idf.save(p)
