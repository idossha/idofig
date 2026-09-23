"""Panel {{panel}} of {{figure}}: <say in one sentence what this panel shows>.

Inputs: <the files this reads — list them under the producer's "inputs" in figure.json>.

Build:  idofig build {{figure}}        (or run this file directly: python {{script}})
"""

import idofig as idf

p = idf.panels("{{panel}}")
ax = p["{{panel}}"].subplots()
idf.name(ax, "main")

# draw here

idf.save(p)
