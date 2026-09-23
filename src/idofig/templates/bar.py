"""Panel {{panel}} of {{figure}}: <say in one sentence what this panel shows>.

Inputs: <the files this reads — list them in figures/{{figure}}/figure.json under the
producer's "inputs" so idofig knows when this panel is stale>.

Build:  idofig build {{figure}}        (or run this file directly: python {{script}})
"""

import idofig as idf

p = idf.panels("{{panel}}")
ax = p["{{panel}}"].subplots()
idf.name(ax, "main")

groups = ["A", "B", "C"]
values = [1.0, 2.5, 1.8]
ax.bar(groups, values, color="#0072B2", label="measured")
ax.set_xlabel("condition")
ax.set_ylabel("response (a.u.)")

idf.save(p)
