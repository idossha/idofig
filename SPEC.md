# idofig file formats and rules (v0.1)

One user unit in every SVG idofig writes is one typographic point. All placement in
`figure.json` is in millimetres, measured from the figure's top-left corner.

## Layout of a project

```
<root>/                     has idofig.toml, or pyproject.toml with [tool.idofig], or suna.json
  figures/<figure-id>/
    figure.json             source
    <anything>.py           producers (anywhere in the project is allowed)
    panels/<panel-id>/
      style.json            source (optional)
      panel.svg             built
      manifest.json         built
    figure.svg              built, committed
    figure.lock.json        built, committed
  .idofig/                  machine-local (staging, last failures); ignored by git
```

Ids (figure, panel, producer, annotation, axes names) match `^[a-z0-9][a-z0-9._-]*$`.

Configuration (`idofig.toml`, or `[tool.idofig]` in `pyproject.toml`):

| key | default | meaning |
|---|---|---|
| `figures` | `"figures"` (or `suna.json` → `directories.figures`) | where figures live |
| `journal` | `"suna"` | bundled preset id, or a path to a JSON preset |

`IDOFIG_ROOT` and `IDOFIG_JOURNAL` override both.

## figure.json — schema 2

| key | owner | required | value |
|---|---|---|---|
| `schema` | idofig | yes | `2` |
| `id` | idofig | yes | equals the directory name |
| `width` | idofig | yes | `{"preset": "single"\|"onehalf"\|"double"}` or `{"mm": n}` |
| `height` | idofig | no | `{"mm": n}`; absent → the lowest panel edge |
| `journal` | idofig | no | overrides the project's journal for this figure |
| `letters` | idofig | no | `{show, case: lower\|upper, weight, size_pt, offset_mm: [dx, dy], wrapper: none\|parens\|period}` |
| `producers` | idofig | no | see below |
| `panels` | idofig | no | see below |
| `annotations` | idofig | no | see below |
| anything else | the application | no | preserved untouched (`caption`, `namespace`, `label`, …) |

**Producer** — `{id, run, inputs?, panels, cost?, timeout_s?}`

* `run`: argv list. `"python"`/`"python3"` as the first element means "the interpreter
  running idofig" (the project environment). Paths are project-relative.
* `inputs`: project-relative paths or globs the producer reads. Imported project modules
  are discovered and tracked automatically; data files must be declared.
* `panels`: panel ids this producer draws. A panel has at most one producer.
* `cost`: `cheap` (default; applications may rebuild automatically) or `expensive`.

**Panel** — `{id, letter?, place: {x, y, w, h}, image?}`

* `place` is the panel's printed box in mm. A produced panel is drawn at exactly `w × h`
  and placed without scaling; changing `w`/`h` makes it stale.
* `image`: a project-relative `.svg`, `.png`, `.jpg`, `.gif` or `.webp` placed (contain-fit)
  instead of drawn. Image panels have no producer and are never edited inside.
* `letter`: the panel label; drawn at compose time in the journal's style.

**Annotation** — `{id, type, …, style?}` drawn over the panels:

| type | fields |
|---|---|
| `text` | `at`, `text`, `align: start\|middle\|end` |
| `arrow` | `from`, `to`, `head: end\|start\|both\|none` (default `end`) |
| `line` | `from`, `to`, `head` (default `none`) |
| `bracket` | `from`, `to`, `label?`, `side: above\|below`; the bar clears the outer anchor by `gap_mm`, both legs are `leg_mm` |
| `box` | `from`, `to` (opposite corners) |

`style`: `color`, `fill`, `width_pt`, `size_pt`, `weight: normal|bold`, `dash: [pt…]`,
`gap_mm`, `leg_mm`, `rotate`.

**Anchor** (`at`, `from`, `to`), plus optional `offset: [dx_mm, dy_mm]`:

| form | meaning |
|---|---|
| `{x, y}` | mm from the figure's top-left |
| `{panel, x, y}` | mm from the panel's top-left |
| `{panel, part, at}` | a point of a named part's box; `at` ∈ center, top, bottom, left, right, top-left, top-right, bottom-left, bottom-right |
| `{panel, axes, data: [x, y]}` | a data coordinate of a named axes (linear or log scales) |

An anchor that no longer resolves makes its annotation **detached**: not drawn, reported
by `compose`, `status` and `check`, and kept in the file.

## Edit operations

Applications and agents edit figure.json with a list of operations (`update_figure` on the
server, `idofig rpc update_figure`), applied all-or-nothing to a fresh read and validated
before the atomic write. A field an operation does not take is an error, never ignored.

| op | fields | effect |
|---|---|---|
| `place` | `panel`, `x?`, `y?`, `w?`, `h?` | move or resize a panel (mm); a new `w`/`h` makes it stale |
| `letter` | `panel`, `letter` | set a panel's letter; `null` removes it |
| `panel.add` | `id`, `letter?`, `place`, `image?` | add a panel |
| `panel.remove` | `id` | remove a panel, and it from its producer (a producer left with no panels goes) |
| `producer.set` | `id`, `run?`, `inputs?`, `panels?`, `cost?`, `timeout_s?` | add a producer, or update the fields given |
| `producer.remove` | `id` | remove a producer |
| `annotation.add` | `annotation` | add an annotation |
| `annotation.update` | `id`, `patch` | merge `patch` into an annotation; a `null` value removes that field |
| `annotation.remove` | `id` | remove an annotation |
| `width` | `preset` or `mm`, `scale_panels?` | set the width; the layout is scaled to it (panels' `x`/`w`, point anchors' `x`) unless `scale_panels: false` |
| `height` | `mm` | fix the height; `null` returns to the lowest panel edge |
| `letters` | `patch` | merge into `letters`; a `null` value removes that field |
| `journal` | `journal` | per-figure journal; `null` removes it |
| `app.set` | `key`, `value` | set an application key (`caption`, …); idofig's own keys are refused |

## style.json — schema 1

```json
{ "schema": 1, "parts": { "<part name or pattern>": { "<property>": <value>, … } } }
```

Patterns may use `*` (`main.xtick.*`, `*.xlabel`). Resolution order: patterns, then groups,
then single parts — the most specific wins. Properties by part kind:

| kind | properties |
|---|---|
| text | text, fontsize, fontweight, fontstyle, fontfamily, color, alpha, visible, rotation |
| line | color, linewidth, linestyle, alpha, visible, marker, markersize, markerfacecolor, markeredgecolor |
| patch | facecolor, edgecolor, color, linewidth, linestyle, alpha, visible, hatch |
| collection | facecolor, edgecolor, color, linewidth, alpha, visible, size, cmap, vmin, vmax |
| image | alpha, visible, cmap, vmin, vmax |
| axes | facecolor, visible |
| axis | visible |
| spine | visible, linewidth, color |
| legend | visible, loc, frameon, fontsize, title |

`text` and `title` apply only to single parts. Overrides are applied with matplotlib
setters before layout, so they reflow the panel. Restyling a series restyles its legend key.
An entry that matches nothing is **detached**; an invalid property is **ignored** — both
are reported in the manifest and by `status`/`check`, and neither is ever removed.
A detached entry is re-attached by moving it to the part's new name
(`idofig style FIG PANEL OLD --move-to NEW`, or `move_style` on the server).

## Part names

See `src/idofig/naming.py` for the grammar. Stability classes, recorded per part:

* `author` — a `gid` the script set. Always wins; duplicates are an error.
* `named` — an axes named with `idofig.name(ax, …)` or a colorbar with `idofig.colorbar(…, name=)`.
* `semantic` — derived from meaning: `main.xlabel`, `main.series.<label>`, `main.xtick.<text>`.
* `positional` — derived from order (`main.line0`, one bar of a series). Survives only while
  the drawing keeps its structure; the manifest says so.

## manifest.json

`{schema, figure, panel, size{w_pt,h_pt,w_mm,h_mm}, parts{name: {kind, role, stability,
parent?, group?, members?, bbox, props?, base?}}, axes{name: {bbox, xscale, yscale, xlim,
ylim}}, style{applied, detached, invalid}, warnings}` — `bbox` is `[x0, y0, x1, y1]` in the
panel's points with y downwards; `props` are current values; `base` the values the code
produced before overrides.

## figure.lock.json

`{schema, figure, producers{id: {run, files{path: sha256|null}, journal, discovered,
built_with}}, panels{id: {producer, shared, size, style, svg, manifest}}, figure_svg}`.
A panel is **stale** when its producer's command, files or journal preset changed, its size
or style changed, or its `panel.svg` differs from what the build wrote.

## Determinism

Panels start from matplotlib's defaults plus the journal preset; fonts are the bundled
Liberation Sans (Arial metrics), named in the SVG as `Arial, 'Liberation Sans', Helvetica,
sans-serif`; `svg.fonttype = none`; `svg.hashsalt = "idofig"`; no metadata; producers run
with `PYTHONHASHSEED=0` and `MPLBACKEND=Agg`. Rebuilding from the same inputs gives the same
bytes; `idofig check` verifies it.
