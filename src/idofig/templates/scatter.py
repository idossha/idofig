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
x = rng.normal(size=60)
y = 0.6 * x + rng.normal(scale=0.5, size=60)
ax.scatter(x, y, s=8, color="#0072B2", label="participants")
ax.set_xlabel("predictor (z)")
ax.set_ylabel("outcome (z)")

idf.save(p)
