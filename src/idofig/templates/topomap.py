"""Panel {{panel}} of {{figure}}: <say in one sentence what this panel shows>.

A scalp map drawn by mne (pip install "idofig[eeg]"); its parts are main.field, main.head,
main.nose, main.ear.left, main.ear.right and main.mask, restyled in style.json by name. Replace
the example values with your own read from results/ (and list the file in the producer's
"inputs" in figure.json), and the montage with your recording's.

Build:  idofig build {{figure}}        (or run this file directly: python {{script}})
"""

import mne
import numpy as np

import idofig as idf
from idofig import neuro

CHANNELS = ["Fp1", "Fpz", "Fp2", "F7", "F3", "Fz", "F4", "F8", "T7", "C3", "Cz", "C4", "T8",
            "P7", "P3", "Pz", "P4", "P8", "O1", "Oz", "O2"]
info = mne.create_info(CHANNELS, sfreq=250.0, ch_types="eeg")
info.set_montage(mne.channels.make_standard_montage("easycap-M1"))
values = np.linspace(-2.0, 2.0, len(CHANNELS))  # example values: one per channel
significant = [CHANNELS.index("Cz"), CHANNELS.index("Pz")]

p = idf.panels("{{panel}}", layout=None)
fig = p["{{panel}}"]
w, h = fig.get_figwidth() * 25.4, fig.get_figheight() * 25.4  # mm
size = min(w - 8, h) - 2
ax = idf.name(idf.axes_mm(fig, 1, (h - size) / 2, size, size), "main")
im = neuro.topomap(ax, values, info, mask=significant, sphere="eeglab")
idf.colorbar(im, name="value", cax=idf.axes_mm(fig, size + 3, h / 2 - size / 3, 1.5, 2 * size / 3))

idf.save(p)
