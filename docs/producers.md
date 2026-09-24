# Writing a producer

A producer is a script that draws one or more panels. It is the only place data becomes
graphics, so it is what makes a figure reproducible.

## The checklist

1. **Declare it.** In `figures/<fig>/figure.json`, a producer lists its command, the panels
   it draws and the data files it reads:

   ```json
   { "id": "make", "run": ["python", "figures/fig-2/make.py"],
     "inputs": ["results/fig2_stats.csv"], "panels": ["dose", "time"] }
   ```

   Every panel it draws must exist in `panels` with a `place` (mm). Project modules it
   imports are tracked automatically; **data files must be listed in `inputs`**, or idofig
   cannot tell when the panel is stale.

2. **Get figures from idofig, at their printed size.**

   ```python
   import idofig as idf
   p = idf.panels("dose", "time")      # dict: panel id → matplotlib Figure (constrained layout)
   ax = p["dose"].subplots()
   idf.name(ax, "main")                # parts become main.xlabel, main.series.<label>, …
   ```

   Never set `figsize`, never call `tight_layout()` or `savefig()`, never scale fonts to fit:
   the panel is the size it prints at. For manual layouts use `idf.panels(..., layout=None)`
   and `idf.axes_mm(fig, left, bottom, width, height)` (mm from the panel's bottom-left).
   Leave the gaps between axes to the layout: `style.json` `layout` (`hspace_mm`,
   `wspace_mm`, `pad_mm`) spaces them in mm on paper, and `trim`/`trim_mm` crops a panel to its
   ink — an editor or an agent sets those, and never edits the script to do it. Spacing needs
   the constrained layout; a `layout=None` panel reports that it had no effect.
   `idf.panel("dose")` returns one Figure. A script that sits outside `figures/<fig>/` and
   is run directly finds its figure through the producer whose `run` names it, or through
   `idf.panels(..., figure="fig-2")`.

   A house style is fine, applied after `idf.panels()` (which resets the rc to matplotlib's
   defaults plus the journal preset, and selects the Agg backend whatever a matplotlibrc
   names; a notebook or an IPython session keeps its own — a plain run that merely imports
   IPython, as seaborn does, is no session — and each save draws on Agg: a
   panel is saved, never shown — but what a script measures before it saves, `ax.clabel`
   or adjustText, a session measures on its own canvas, so commit the panel `idofig build`
   or a script run writes). It styles the drawing, but every panel is still saved
   at its printed size with its text as text, whatever `savefig.bbox`, `savefig.pad_inches`
   or `svg.fonttype` say.

3. **Label what matters.** Give every series a `label=` (it becomes `main.series.<label>`
   and its legend key), put text in axis labels and titles, and use `gid=` for anything else
   a person might want to restyle on the canvas. Unlabelled artists get positional names.
   Make colorbars with `idf.colorbar(mappable, name="value", ax=ax)`: its axes becomes
   `cbar.value` rather than a positional `cbar0`. Mark heavy layers (dense meshes, thousands
   of points) `rasterized=True`: a labelled one keeps its name, as an image the canvas can
   select; unlabelled ones (per-trial traces) merge into one unnamed image, as small as
   matplotlib makes it.

4. **Be deterministic.** Seed every random generator; do not print timestamps into the
   figure; read inputs from files, not from the network. Keep to the bundled font (the
   default) or one that ships with matplotlib (DejaVu Sans Mono, say); any other font is
   reported as a warning, because the panel may lay out differently on another machine —
   `sans-serif` too, when a style's `font.sans-serif` list resolves it to a system font.

5. **Save once.** `idf.save(p)` names every part, applies `style.json`, and writes
   `panel.svg` + `manifest.json` for each panel. Under `idofig build` it writes to a private
   directory that is published only if the run succeeds; run directly (`python
   figures/fig-2/make.py`) it publishes in place and recomposes `figure.svg`. A notebook
   that saves the same figure again keeps each style override set on it: after deleting an
   entry from `style.json`, re-run the cell that draws the panel, not only the save.

6. **Heavy work goes elsewhere.** If computing the data takes more than a few seconds,
   write it to `results/` in an analysis script and let the producer only read and plot.
   Mark genuinely slow producers `"cost": "expensive"`.

## Verify

```sh
idofig build fig-2          # runs what is stale, recomposes figure.svg
idofig status               # fresh / stale (and why) / failed
idofig parts fig-2 dose     # the names a canvas or a style.json can address
idofig check                # reproducible byte for byte, within the journal's rules
```

## Refining without touching code

`style.json` beside a panel holds overrides by part name. People write it from the canvas;
agents may write it with `idofig style fig-2 dose main.xlabel fontsize=8`. Overrides
survive new data. A label or legend that sits in the wrong place is moved there too
(`dx_mm=1.5 dy_mm=-0.5`), and a panel letter by `letter_offset_mm` in figure.json (written
by hand, with `"schema": 3`, which an idofig older than 0.3 refuses rather than misdraw) — no
code change, and the move survives a re-run. To fold a look override (`fontsize`, `color`,
…) into the script instead, edit the script, delete the entries, rebuild, and confirm the
panel.svg bytes did not change. Moves stay where they are: idofig applies `dx_mm`/`dy_mm`
after the layout is frozen, which a script cannot (the same move made in the script is
absorbed by the constrained layout, and the bytes change), and a letter is drawn when the
figure is composed, never by the script.
