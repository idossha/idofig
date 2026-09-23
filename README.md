# idofig

**Reproducible, editable publication figures.** Code draws, a small spec composes, and a
canvas or an AI agent refines — through plain files that rebuild byte for byte.

```
figures/fig-dose/
  figure.json          SOURCE  width, producers, panels (placement in mm), letters, annotations
  dose.py              SOURCE  a producer: matplotlib code that draws one or more panels
  panels/dose/
    style.json         SOURCE  overrides on named parts (what a canvas writes)
    panel.svg          BUILT   the panel at its printed size
    manifest.json      BUILT   every named part: kind, box, current values; axes data mapping
  figure.svg           BUILT   the composed figure (committed, so a clone is readable without tools)
  figure.lock.json     BUILT   what each panel was built from, so idofig knows what is stale
```

## Why

Figures break reproducibility at the last step: a script makes the plot, then someone fixes
labels, colours and layout by hand, and the next data change throws that work away. idofig
keeps every one of those decisions in a file the build applies:

* **Parts have names that survive regeneration.** `main.xlabel`, `main.series.control`,
  `main.xtick.10`, `main.legend` — derived from what a part *is*, not where it happens to be.
* **Style edits are applied before layout**, with matplotlib's own setters, from
  `style.json`. A bigger font reflows the plot exactly as if it had been typed in the script,
  and `python dose.py` alone reproduces it.
* **Panels are drawn at their printed size and never scaled.** A 7 pt label is 7 pt in the
  figure, so journal rules can be checked exactly.
* **Nothing is lost silently.** An override whose part disappears is *detached* and reported,
  never applied to something else and never deleted.
* **Builds are deterministic.** Bundled fonts (Liberation Sans, Arial-metric), matplotlib
  defaults (your matplotlibrc never leaks in), fixed hash salt, no timestamps.

## Quick start

```sh
uv add --editable /path/to/idofig        # or: pip install -e /path/to/idofig
idofig init --journal nature              # writes idofig.toml
idofig new fig-dose --width double
idofig add-panel fig-dose dose --template bar
idofig build                              # runs dose.py, writes panel.svg + figure.svg
idofig style fig-dose dose main.xlabel fontsize=8 "text=dose (mg)"
idofig build                              # only the stale panel rebuilds
idofig check                              # CI: fresh, reproducible, within Nature's rules
```

A producer:

```python
import idofig as idf

p = idf.panels("dose", "time")            # sized from figure.json; journal style applied
ax = p["dose"].subplots(); idf.name(ax, "main")
ax.bar(groups, control, label="control")
ax.bar(groups, drug, bottom=control, label="drug")
ax.set_xlabel("dose")
...
idf.save(p)                               # names parts, applies style.json, writes SVG + manifest
```

`idofig build` runs producers with a private output directory and publishes only after the
run succeeds; a direct `python dose.py` publishes in place and recomposes the figure.

## figure.json (schema 2)

```json
{
  "schema": 2,
  "id": "fig-dose",
  "width": { "preset": "double" },
  "producers": [
    { "id": "make", "run": ["python", "figures/fig-dose/make.py"],
      "inputs": ["results/stats.csv", "code/plotting/*.py"], "panels": ["dose", "time"], "cost": "cheap" }
  ],
  "panels": [
    { "id": "dose", "letter": "a", "place": { "x": 0, "y": 0, "w": 88, "h": 60 } },
    { "id": "time", "letter": "b", "place": { "x": 92, "y": 0, "w": 88, "h": 60 } },
    { "id": "scheme", "letter": "c", "image": "figures/fig-dose/scheme.svg",
      "place": { "x": 0, "y": 64, "w": 180, "h": 40 } }
  ],
  "annotations": [
    { "id": "sig-1", "type": "bracket", "label": "**",
      "from": { "panel": "dose", "part": "main.series.control.0", "at": "top" },
      "to":   { "panel": "dose", "part": "main.series.control.2", "at": "top" } }
  ],
  "caption": { "title": "…" }
}
```

* `width`: `{"preset": "single" | "onehalf" | "double"}` from the journal, or `{"mm": 120}`.
* `producers[].run` is an argv list; `python` means the interpreter running idofig.
  `inputs` are project-relative paths or globs. Project modules a producer imports are
  discovered automatically.
* `panels[].place` is in millimetres from the figure's top-left. Resizing a panel makes it
  stale: it is redrawn at the new size, never stretched.
* Annotations (`text`, `arrow`, `line`, `bracket`, `box`) anchor to a figure position, a
  panel position, a **named part** (`{"panel", "part", "at"}`), or **data coordinates**
  (`{"panel", "axes", "data": [x, y]}`) — so a bracket follows its bars when the data move.
* Keys idofig does not own (`caption`, `namespace`, `label`, …) belong to the application
  embedding it and are preserved untouched.

## style.json

```json
{ "schema": 1, "parts": {
    "main.xlabel":      { "fontsize": 8, "text": "dose (mg)" },
    "main.series.drug": { "color": "#D55E00" },
    "main.xtick.*":     { "fontsize": 6 },
    "main.legend":      { "visible": false } } }
```

`idofig parts FIG PANEL` lists the names; `idofig style` edits the file with validation.
Wildcards (`*`) address groups; the most specific entry wins.

## Journals

Bundled presets (`idofig journals`) carry each journal's stated column widths, font floor
and ceiling, line weights and panel-label style, with sources. Where a journal states no
number, idofig states none. Select one in `idofig.toml` / `[tool.idofig]` (`journal =
"nature"`), per figure (`"journal"` in figure.json), or point at a JSON file.

## For applications

`idofig serve` speaks JSON-RPC over stdio (see `src/idofig/serve.py`): workspace, status,
compose (milliseconds), build (streamed events, cancellable), validated edits of
figure.json and style.json, and a safe restore for undo. SUNA embeds idofig this way.

See [SPEC.md](SPEC.md) for the complete file formats and the naming grammar.
