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
  never applied to something else and never deleted; `idofig style … --move-to NEW` re-attaches it.
* **Builds are deterministic.** Bundled fonts (Liberation Sans, Arial-metric), matplotlib
  defaults (your matplotlibrc never leaks in), fixed hash salt, no timestamps. A house style
  a script loads cannot crop a panel or turn its text into paths: panels are saved under
  fixed settings.

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

## figure.json (schema 2, or 3)

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
* Each panel's `letter` is drawn at compose time in the journal's style; reordering
  `panels[]` does not reletter them. `letters` places and styles them all (`offset_mm`,
  `size_pt`, `case`, `weight`, `wrapper`, `color`); a panel's own `letter_offset_mm: [dx, dy]`
  moves just its letter from there — composing only, no redraw. A figure that uses
  `letter_offset_mm` or `letters.color` is written with `"schema": 3`, which an idofig
  older than 0.3 refuses rather than drawing those letters without them; any other stays 2.
  Adding either by hand, set `"schema": 3` too (compose warns until you do). An idofig older
  than 0.3 refuses a schema-3 figure.json wherever it reads it, a producer's
  `idofig.panels()` included: upgrade the idofig a producer runs before moving or colouring
  a letter.
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

Every refinement is a small named delta that survives the script being re-run:

| to adjust | where | unit |
|---|---|---|
| a panel's position or size | `figure.json` `panels[].place` | mm |
| every letter at once | `figure.json` `letters` | pt / mm |
| one panel's letter | `figure.json` `panels[].letter_offset_mm` | mm, y down |
| a part's look | `style.json` (`fontsize`, `color`, …) | pt, … |
| a text or legend part's position | `style.json` `dx_mm`, `dy_mm` | mm, y down |
| an axes, or a group of axes, with everything drawn in it | `style.json` `dx_mm`, `dy_mm` on its name or a pattern (`row1.*`) | mm, y down |
| an axes' size and angle, with everything drawn in it | `style.json` `scale` (0.25–4), `rotate` (−180–180, clockwise) on its name or a pattern | factor, degrees |
| an axis' tick marks | `style.json` on `main.xaxis`: `tickdir`, `ticklength`, `tickwidth` | pt |
| marks over the figure | `figure.json` `annotations` | mm, anchored to parts or data |
| the gaps between a panel's axes | `style.json` `layout`: `hspace_mm`, `wspace_mm`, `pad_mm` | mm |
| a panel's empty margin | `style.json` `trim: true` or `trim_mm` | mm |
| the figure's size | nothing: it always fits what is drawn (`fit_margin_mm`); `width` and `height` are maxima | mm |

`dx_mm`/`dy_mm` move a part after the layout is frozen, so it lands exactly that far from
where the script drew it and nothing else moves; the freeze lasts that one save, so a
script (or notebook) that saves again is laid out afresh. Tick labels cannot be moved, a
legend's entries and title move only with their legend, and a 3D axis takes no tick-mark
properties (it draws its ticks from its own settings) — a `gid` on the part changes none of
that.

Upgrading from idofig 0.2.x makes every panel stale (the lock's `render` number) until
`idofig build` redraws it; a panel whose producer runs an interpreter with an older idofig
of its own is not stale after that, but warns to upgrade that idofig and then run
`idofig build --force <fig>` — and, once a letter is moved or coloured (schema 3), that its
next build fails until then. See SPEC.md, *figure.lock.json*.

## Journals

Bundled presets (`idofig journals`) carry each journal's stated column widths, font floor
and ceiling, line weights and panel-label style, with sources. Where a journal states no
number, idofig states none. `idofig check` holds what was drawn to those numbers: text
below the font floor and a fixed `height` above the journal's maximum fail it; a width that is
none of the journal's, panel letters below the floor, text above the ceiling, a stroke
thinner than the line weight (an edge drawn in no colour, or in its own face colour, is no
stroke, but a '+' or 'x' marker is all stroke; a collection of several widths is held to its
thinnest; a drawn axis' tick marks are held to their `tickwidth`), ink outside a panel, and a panel or letter past the figure's edge are warnings. A group of parts that break a rule is one finding
naming the group (`main.xtick.* is 4 pt (6 parts); …`), not one per tick label.

Select one in `idofig.toml` / `[tool.idofig]` (`journal = "nature"`), per figure
(`"journal"` in figure.json), or point at a JSON file. A SUNA project that sets none follows
the journal chosen in SUNA (`suna.json`'s `activeProfileId`) when idofig bundles it.

## For applications

`idofig serve` speaks JSON-RPC 2.0 over stdio, one JSON object per line (a line that is not
strict JSON, one holding `NaN`, `Infinity` or `1e999` included, is answered with error -32700,
one that is not an object, a batch say, with -32600, and the server goes on). An application
keeps one server per project, so composing takes milliseconds rather than a Python
start-up; SUNA embeds idofig this way. `idofig rpc METHOD '{"param": …}'` calls one method
once, through the same code, and prints `{result}` or `{error}`. Every method
(`src/idofig/serve.py`):

| method | params | what it does |
|---|---|---|
| `hello` | | version, root, figures dir, journal, python |
| `workspace` | | every figure: document, manifests, styles, status, journal findings |
| `figure` | `figure` | one figure, as in `workspace` |
| `status` | `figures?` | figure statuses |
| `compose` | `figure` | writes figure.svg; the compose result |
| `build` | `figures?, only?, force?, include_expensive?, retry_failed?, timeout?` | queues a build; streams `event` notifications and answers with the build report |
| `cancel` | | stops the running build and drops the queued ones |
| `update_figure` | `figure, ops` | applies [edit operations](SPEC.md#edit-operations) and recomposes |
| `update_style` | `figure, panel, part, props` | merges `props` into a part's overrides (a `null` value removes one; `props: null` resets the part) |
| `update_panel_style` | `figure, panel, props` | sets style.json's panel-wide keys — `layout` {hspace_mm, wspace_mm, pad_mm} (merged; `null` removes), `trim`, `trim_mm`; answers like `update_style` |
| `move_style` | `figure, panel, from, to` | re-attaches a detached override to a part's new name |
| `restore` | `path, text, expect_sha` | undo: puts a figure.json or style.json back, only if unchanged since; answers the text it replaced (for redo) |
| `new_figure` | `figure, width?, extra?` | creates a figure (`extra`: application keys) |
| `add_panel` | `figure, panel, template?, script?, image?, place?, letter?` | adds a drawn panel (and a producer), or an image panel |
| `check` | `figures?, run?` | CI's verdict: fresh, reproducible, within the journal's rules |
| `parts` | `figure, panel` | the panel's manifest parts |
| `locate` | `figure, panel, part` | candidate code lines that make the part |
| `journal` | | the project's journal preset, resolved |
| `journals` | | the bundled journal presets |
| `props` | | the style property table, per part kind, and the properties refused by part role |
| `validate_style` | `kind, props, group?, role?` | problems with setting `props` on a part of `kind` (and the manifest's `role`; empty: valid) |
| `shutdown` | | stops the server |

The server announces itself with a `ready` event. A build streams `build.start`,
`producer.start`, `producer.output`, `producer.skipped`, `producer.done`, `figure.composed`
and `build.done`; builds queue behind each other rather than refuse. Edits answer the text
they replaced (`before`) and the new file's sha256 (`after_sha`), which is what `restore`
takes. A failed method answers an error with `data.type`, and `data.problems` when a file
would be invalid.

See [SPEC.md](SPEC.md) for the complete file formats and the naming grammar, and
[docs/producers.md](docs/producers.md) for how to build a figure that stays editable.
