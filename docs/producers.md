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
   and `idf.axes_mm(fig, left, bottom, width, height)`.

3. **Label what matters.** Give every series a `label=` (it becomes `main.series.<label>`
   and its legend key), put text in axis labels and titles, and use `gid=` for anything else
   a person might want to restyle on the canvas. Unlabelled artists get positional names.

4. **Be deterministic.** Seed every random generator; do not print timestamps into the
   figure; read inputs from files, not from the network.

5. **Save once.** `idf.save(p)` names every part, applies `style.json`, and writes
   `panel.svg` + `manifest.json` for each panel.

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
survive new data. To fold them into the script instead, edit the script, delete the
entries, rebuild, and confirm the panel.svg bytes did not change.
