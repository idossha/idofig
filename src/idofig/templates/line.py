"""Panel {{panel}} of {{figure}}: <say in one sentence what this panel shows>.

Inputs: <the files this reads — list them under the producer's "inputs" in figure.json>.

Build:  idofig build {{figure}}        (or run this file directly: python {{script}})
"""

import numpy as np

import idofig as idf

p = idf.panels("{{panel}}")
ax = p["{{panel}}"].subplots()
idf.name(ax, "main")

t = np.linspace(0, 10, 200)
ax.plot(t, np.sin(t), color="#0072B2", label="control")
ax.plot(t, 0.8 * np.sin(t + 0.6), color="#D55E00", label="treated")
ax.set_xlabel("time (s)")
ax.set_ylabel("signal (a.u.)")
ax.legend()

idf.save(p)
