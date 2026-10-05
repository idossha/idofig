# idofig file formats and rules

Schemas: `figure.json` 2 and 3, `style.json` 1, `figure.lock.json` 1, `manifest.json` 1. Each
file carries its number in `"schema"`; this document describes those versions.

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
  .idofig/                  machine-local; never committed (idofig writes its own .gitignore: *)
    build.lock              one builder per project at a time (an app's server and a terminal)
    state.json              each producer's last failure, with the inputs it failed on
    staging/<run>/          a producer run's private output directory, removed after the run
```

Ids (figure, panel, producer, annotation, axes names) match `^[a-z0-9][a-z0-9._-]*$`.

**Finding the project.** The root is the nearest directory, at or above the working
directory (a producer run directly starts from its script's directory), that has
`idofig.toml`, a `pyproject.toml` with a `[tool.idofig]` table, or `suna.json`, checked in
that order. `IDOFIG_ROOT` names the root and skips the search.

Configuration (`idofig.toml`, top-level or under `[tool.idofig]`; or `[tool.idofig]` in
`pyproject.toml`):

| key | default | meaning |
|---|---|---|
| `figures` | `suna.json` → `directories.figures`, else `"figures"` | where figures live; must be inside the project |
| `journal` | `suna.json` → `activeProfileId` when idofig bundles a preset of that id, else `"suna"` | bundled preset id, or a path (absolute or project-relative) to a JSON preset |

The `suna.json` defaults apply whenever the root has a `suna.json`, and only to keys the
configuration leaves unset, so switching the journal in SUNA and building from a terminal
give the same figures. An `activeProfileId` idofig does not bundle falls back to `"suna"`.
`IDOFIG_JOURNAL` overrides the project's journal; a figure's own `journal` still wins.

**Running a producer.** `idofig build` and `idofig check` run a producer from the project
root with the environment they were started with, plus:

| variable | value |
|---|---|
| `IDOFIG_ROOT` | the project root |
| `IDOFIG_FIGURE` | the figure id |
| `IDOFIG_OUTPUT_DIR` | a private directory under `.idofig/staging/`; `idofig.save()` writes there. `build` publishes the panels only after the run succeeds; `check` compares them with the committed ones |
| `IDOFIG_ONLY` | comma-separated panel ids, set only when some of the producer's panels are wanted; `idofig.save()` skips the others |
| `IDOFIG_JOURNAL` | the figure's own `journal`, when figure.json sets one |
| `MPLBACKEND`, `PYTHONHASHSEED`, `PYTHONUNBUFFERED` | `Agg`, `0`, `1` |

Run directly (`python figures/fig-1/make.py`), idofig sets none of these (each save draws on
Agg, as `build` does; see Determinism): the script's
figure is the `figure=` it passes, else the `figures/<id>/` it sits in, else the one figure
whose producer `run` names it; `idofig.save()` then publishes in place, records the panels
in the lock (those a declared producer draws) and recomposes `figure.svg`.

## figure.json — schema 2 and 3

| key | owner | required | value |
|---|---|---|---|
| `schema` | idofig | yes | `2`, or `3` when the figure uses a key idofig 0.3 added (below) |
| `id` | idofig | yes | equals the directory name |
| `width` | idofig | yes | `{"preset": "single"\|"onehalf"\|"double"}` or `{"mm": n}`: the column, the figure's **maximum** width (below) |
| `height` | idofig | no | `{"mm": n}`: a **maximum** height; absent → only the journal's `maxHeightMm`, if it states one |
| `fit_margin_mm` | idofig | no | 0–50 mm of white kept around what the figure draws (default 0); schema 3 |
| `journal` | idofig | no | overrides the project's journal for this figure |
| `letters` | idofig | no | `{show, case: lower\|upper, weight: normal\|bold, size_pt, offset_mm: [dx, dy], wrapper: none\|parens\|period, color}`; `offset_mm` in mm, each within ±100; `color` is a colour as an annotation's is (default `#000000`); any other key is an error |
| `producers` | idofig | no | see below |
| `panels` | idofig | no | see below |
| `annotations` | idofig | no | see below |
| anything else | the application | no | preserved untouched (`caption`, `namespace`, `label`, …) |

**Fit (0.5.0).** A figure is always exactly as large as what it draws, both ways: every
panel (a trimmed one at its crop's size, see style.json), every letter (its cap height and
0.6 em a character, where `letters.offset_mm` and the panel's `letter_offset_mm` put it) and
every annotation that resolves (a text at 0.55 em a character, unrotated), plus
`fit_margin_mm` on each side. Empty bands above and to the left are cut by starting the view
there: figure.svg's `viewBox` is `<left> <top> W H` in points, and figure.json's coordinates
are untouched — a panel at `x: 10, y: 12` is still at 10, 12 mm; the view starts there.
Nothing of the fitted size is stored (compose's result reports `width_mm`, `height_mm`,
`left_mm`, `top_mm`; figure.svg's `width`/`height` carry it).

`width` and `height` are **maxima**, never sizes: the column (`width`) caps the width, and the
height is capped by `height` when figure.json states one and by the journal's `maxHeightMm`
when the journal states one (D4: no stated number, no cap). A figure past a cap is reported —
`the figure is 188 mm wide; its column allows 183 mm`, `the figure is 210 mm tall; Neuron
allows 200 mm` — advisory, from `compose`, `status` and `check`; nothing is shrunk, rescaled
or moved. Figures written for 0.4 or older read as before and need no edit: their `height`
was the paper's size and is now its cap, so an old figure only loses the empty paper it had.
No schema bump: an older idofig draws the same figure with that empty paper around it, not a
wrong one. (0.4 fitted only a figure with no `height`, kept the column's full width and
ignored annotations; 0.4's figure-edge findings are gone, as nothing drawn can cross an edge.)

**Schema 3** is schema 2 plus the keys an idofig older than 0.3 would ignore without a
word: a panel's `letter_offset_mm` and `letters.color`, and 0.4's `fit_margin_mm` (0.2.x checks no panel or letters key
it does not know, and composed those letters at the figure-wide place, in black, calling
figure.svg fresh). An edit writes `3` when the figure uses either and `2` when it uses
neither, so 0.2.x refuses the one file it would draw wrong ("schema must be 2") and reads
every other. It refuses it wherever it reads it, a producer included (`idofig.panels()` reads
figure.json, in a build or a direct `python make.py`): a producer whose `run` uses 0.2.x cannot
draw a panel of a schema-3 figure, so upgrade the idofig it runs before moving or colouring a
letter (`status` says so; see figure.lock.json). idofig reads either number whatever the keys
(a 0.3 development build wrote them under 2, and so does a hand edit; the next edit writes 3),
and until then `compose`, `status` and `check` warn: `figure.json uses letter_offset_mm or
letters.color under "schema": 2, which an idofig older than 0.3 reads and draws without them:
set "schema": 3`. Adding either key by hand, set `"schema": 3` with it.

**Producer** — `{id, run, inputs?, panels, cost?, timeout_s?}`

* `run`: argv list. `"python"`/`"python3"` as the first element means "the interpreter
  running idofig" (the project environment). Paths are project-relative.
* `inputs`: project-relative paths or globs the producer reads. Imported project modules
  are discovered and tracked automatically; data files must be declared.
* `panels`: panel ids this producer draws. A panel has at most one producer.
* `cost`: `cheap` (default; applications may rebuild automatically) or `expensive`.
* `timeout_s`: seconds after which a run is killed and fails (a build's own timeout wins).

**Panel** — `{id, letter?, letter_offset_mm?, place: {x, y, w, h}, image?}`

* `place` is the panel's printed box in mm. A produced panel is drawn at exactly `w × h`
  and placed without scaling; changing `w`/`h` makes it stale.
* `image`: a project-relative `.svg`, `.png`, `.jpg`/`.jpeg`, `.gif` or `.webp` placed
  (contain-fit) instead of drawn. Image panels have no producer and are never edited inside.
* `letter`: the panel label; drawn at compose time in the journal's style.
* `letter_offset_mm`: `[dx, dy]` in mm, y down, each within ±100 — moves this panel's letter
  from where the figure-wide rule puts it. A letter's top-left is at the panel's top-left
  corner + `letters.offset_mm` + `letter_offset_mm`, so it moves with its panel. Kept on a
  panel without a letter (it applies when one is set).

**Annotation** — `{id, type, …, style?}` drawn over the panels:

| type | fields |
|---|---|
| `text` | `at`, `text`, `align: start\|middle\|end` |
| `arrow` | `from`, `to`, `head: end\|start\|both\|none` (default `end`) |
| `line` | `from`, `to`, `head` (default `none`) |
| `bracket` | `from`, `to`, `label?`, `side: above\|below`; the bar clears the outer anchor by `gap_mm`, both legs are `leg_mm` |
| `box` | `from`, `to` (opposite corners) |

`style`: `color`, `fill`, `width_pt`, `size_pt`, `weight: normal|bold`, `dash: [pt…]`,
`gap_mm`, `leg_mm`, `rotate`. A colour is hex, a name or `none`, as matplotlib takes them — a
one-letter name in lower case only, a longer one in any case, and nothing around it (`K` and
`" red "` are refused) — here and in style.json; the spellings CSS does not know (`r`, `k`, …, `C0`–`C9`, `tab:blue`, a grey level such as `"0.5"`)
are composed into figure.svg as the hex they stand for, `C0`–`C9` as matplotlib's default
cycle. So is `letters.color`.

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
| `letter` | `panel`, `letter?`, `offset_mm?` | `letter` sets the panel's letter (`null` removes it); `offset_mm: [dx, dy]` sets its `letter_offset_mm` (`null` returns the letter to the figure-wide position). Only the fields sent change; an op with neither is an error |
| `panel.add` | `id`, `letter?`, `place`, `image?` | add a panel |
| `panel.remove` | `id` | remove a panel, and it from its producer (a producer left with no panels goes) |
| `producer.set` | `id`, `run?`, `inputs?`, `panels?`, `cost?`, `timeout_s?` | add a producer, or update the fields given |
| `producer.remove` | `id` | remove a producer |
| `annotation.add` | `annotation` | add an annotation |
| `annotation.update` | `id`, `patch` | merge `patch` into an annotation; a `null` value removes that field |
| `annotation.remove` | `id` | remove an annotation |
| `width` | `preset` or `mm`, `scale_panels?` | set the column (the maximum width); the layout is scaled to it (panels' `x`/`w`, point anchors' `x`) unless `scale_panels: false` |
| `height` | `mm` | set a maximum height; `null` removes it (the journal's `maxHeightMm` still caps) |
| `letters` | `patch` | merge into `letters`; a `null` value removes that field |
| `journal` | `journal` | per-figure journal; `null` removes it |
| `app.set` | `key`, `value` | set an application key (`caption`, …); idofig's own keys are refused |

## style.json — schema 1 and 2

```json
{ "schema": 1, "parts": { "<part name or pattern>": { "<property>": <value>, … } } }
{ "schema": 2, "layout": {"hspace_mm": 4, "wspace_mm": 6, "pad_mm": 1}, "trim_mm": 1, "parts": { … } }
```

**Panel-wide keys (0.4).** Schema 2 is schema 1 plus the keys an idofig older than 0.4 would
ignore without a word (it checks no top-level key but `parts`): an edit writes `2` when the
file uses one and `1` when it uses none, so 0.3 refuses the one file it would draw wrong.

* `layout` — the constrained layout engine's spacing, in mm on paper, applied before the save
  lays the panel out, so matplotlib re-flows the axes. `pad_mm` is the clear space around
  every axes' ink, the panel's edges included (the engine's `w_pad`/`h_pad`, in inches).
  `wspace_mm`/`hspace_mm` is the clear gap between neighbouring axes' ink, tick and axis
  labels included: the engine gives each side of an axes `wspace / 2 / ncols` of the figure,
  so idofig sets each gridspec's own `wspace` to `wspace_mm × ncols / W_mm` (one engine-wide
  fraction would be wrong for a grid of another shape). Where a gap is less than twice the pad,
  matplotlib uses the pads (its rule, kept: set `pad_mm` lower for a narrower gap). Each value
  is a finite number from 0 to 100; any other key is an error. A panel with no constrained
  layout (`idofig.panels(..., layout=None)`, axes placed with `axes_mm`) takes no spacing: the
  manifest's `warnings` say `style.json layout had no effect: …` and nothing moves — spacing never
  rewrites where a script placed an axes. To move one (or a group of them), give it an
  explicit `dx_mm`/`dy_mm` (Moving a part, below).
* `trim: true`, or `trim_mm: <margin>` (0–50 mm; alone it turns trim on, and `trim: false`
  keeps it off) — crop the panel to its ink plus the margin. The ink is every drawn part's box
  after styles and `dx_mm`/`dy_mm` (a panel's or an axes' background is not ink) and every
  axes' frame, within the panel. Nothing is rescaled: panel.svg keeps its drawn size, the
  manifest records the crop (`trim`), and compose places the crop's top-left corner at the
  panel's place, clipped to the crop, so the panel shrinks towards its top-left and no
  neighbour moves. The cropped size is derived at every build and stored nowhere else.

A script is never rewritten to space or crop a panel: both are refinements, and refinements
live in style.json (the producer owns what is drawn).

Patterns may use `*` (`main.xtick.*`, `*.xlabel`). Resolution order: patterns, then groups,
then single parts — the most specific wins. Every kind additionally accepts the common
geometry properties described below. Other properties by part kind:

| kind | properties |
|---|---|
| text | text, fontsize, fontweight, fontstyle, fontfamily, color, alpha, visible, rotation, dx_mm, dy_mm |
| line | color, linewidth, linestyle, alpha, visible, marker, markersize, markerfacecolor, markeredgecolor |
| patch | facecolor, edgecolor, color, linewidth, linestyle, alpha, visible, hatch |
| collection | facecolor, edgecolor, color, linewidth, alpha, visible, size, cmap, vmin, vmax |
| image | alpha, visible, cmap, vmin, vmax |
| axes | facecolor, visible, dx_mm, dy_mm, scale, rotate |
| axis | visible, tickdir (in\|out\|inout), ticklength (pt), tickwidth (pt) |
| spine | visible, linewidth, color |
| legend | visible, loc, frameon, fontsize, title, dx_mm, dy_mm, scale, rotate |

`text` and `title` apply only to single parts. Overrides are applied with matplotlib
setters before layout, so they reflow the panel. Restyling a series restyles its legend key.
An entry that matches nothing is **detached**; an invalid property is **ignored** — both
are reported in the manifest and by `status`/`check`, and neither is ever removed. A number
must be finite (`NaN` passes every bound) and, if an integer, small enough to be a float (one
beyond about 1.8 × 10^308, a 310-digit literal say, is not): a write that sets another is
refused, on a part, a group or a pattern, with a manifest or without, and a style.json that
holds one is refused whole, naming the file, as one holding a bare `NaN` is. A file with a bare `NaN` or `Infinity` in it, or a number too large for a
float (`1e999`), is not JSON — idofig reads it (a journal preset or a manifest too) as
invalid, naming the file, and writes no such file (a manifest idofig 0.2.2 wrote may hold a
`NaN`: `parts` and `locate` refuse it, naming it, and `style` writes the override unchecked,
as when there is no manifest); no server reply carries one (an answer that would is an error
for its request), and a request that holds one is a parse error (-32700), as a line that is
not JSON is.
A detached entry is re-attached by moving it to the part's new name
(`idofig style FIG PANEL OLD --move-to NEW`, or `move_style` on the server).

**Common artist geometry (0.9.0).** Every named artist kind accepts `dx_mm`, `dy_mm`
(finite millimetres, positive right/down), `scale` (finite, strictly positive uniform factor,
default 1), and `rotate` (finite clockwise degrees, default 0). No role-based geometry
refusals apply: ticks, legend entries, data lines, patches, collections, images, spines and
axes may all move independently. The legacy text `rotation` remains matplotlib's typography
setting, counter-clockwise, and is independent of the common clockwise `rotate`.

Geometry is applied after layout. Scale and turn are SVG group transforms about the centre
of the artist's untransformed built bounding box; axes use their frame centre. They carry
that artist's native clipping and child drawing with it. An image's native flip is preserved
inside a wrapper. A nested artist transforms first in its parent's coordinates, then inherits
its containing SVG groups' transforms. `dx_mm`/`dy_mm` are local parent-space displacement,
so a parent scale or turn also scales or turns that displacement. The matrix for a new
SVG-positioned artist is `translate(c + offset) ∘ rotate ∘ scale ∘ translate(-c)`.

Existing text, legend and axes offsets retain their post-layout matplotlib placement behavior:
annotation text moves while its arrow endpoint stays anchored; an axes moves its box and twins;
a legend keeps its anchor and size. Their raw frame already includes that displacement, so the
SVG matrix applies scale/rotation only. Newly movable artists (including individual tick and
legend labels) apply their displacement in SVG, avoiding matplotlib's tick-transform sharing.
The manifest's `offset_in_matrix` distinguishes the two representations; the public properties
and physical units are the same. The panel itself continues to be redrawn at its printed size.

A group or pattern applies geometry once to each addressed artist not already contained in
another addressed artist. Specific child overrides remain independent. Identity geometry
writes no SVG matrix. A missing drawable group is reported as a warning; no source override
is silently deleted. Non-finite input and nonpositive scale are rejected; finite values that
overflow the resulting SVG matrix fail the build instead of publishing corrupt coordinates.

Each individual part supplies `frame` (its raw built box in panel points), optional `own_matrix`
(its own SVG transform), and optional `matrix` (the composed transform through actual SVG
ancestors). `bbox` is the axis-aligned box after that composed transform. All coordinates are
crop-adjusted when `trim` applies. `effective_scale` includes nested scaling so checks read the
size actually printed. A canvas uses `frame` and the matrices for its handles and selection;
it must not transform an already transformed `bbox` a second time.

All of this lasts one save. Once the panel is written, the script's figure is as it was —
its layout engine, its titles' and legends' placement and anchors, each part where the script put it —
so a script that saves, changes the figure and saves again (a notebook re-running its save
cell) is laid out afresh, and an offset removed from style.json in between moves nothing.
A style override is not taken back: it is set on the script's part with matplotlib's setter
and stays set, so a script that saves again after an entry is removed from style.json still
draws the value that entry set, until it draws that part again (re-run the cell that draws
it, or the script; `build` always runs the script afresh).

A panel with no offset takes none of this: it is saved once, as before, and its panel.svg
has the bytes idofig 0.2.2 wrote — unless it has a named rasterized part, a 3D axes, an
axes background or legend frame named by a gid, whose group now carries its role
(`data-idofig-role`, see Part names), or a legend named by a gid, whose frame, entries and
title are now named after it; or unless its script changes the figure's size after
`idofig.panels()`: it is now saved at its place size (see Determinism), where 0.2.2 saved it
at the script's size and compose warned that it was drawn at another. `tests/golden/` holds such a panel, whose panel.svg is
0.2.2's to the byte, and a test checks under any matplotlib that the draws a save wraps
(tracking what was drawn, naming rasterized parts) add no byte.

**Tick marks.** `tickdir` sets the direction of an axis' major and minor tick marks;
`ticklength` and `tickwidth` set its major ones. They are applied with `tick_params` before
layout. A 3D axis (role `axis3d`) refuses them: it draws its tick marks from its own
settings, never from `tick_params`.

## Part names

See `src/idofig/naming.py` for the grammar. Stability classes, recorded per part:

* `author` — a `gid` the script set. Always wins; duplicates are an error. It names the
  part, and the part's `role` is still what it is (a tick label with a gid has the role
  `tick`), so a gid lifts none of a role's refusals, and an axes background or legend frame
  with a gid is marked `data-idofig-role="background"` (or `legend-frame`) in the SVG like
  one without. A legend's frame, entries and title are named after the name it has, its gid
  included (`key.frame`, `key.<entry>`, `key.title`, each with the parent `key`).
* `named` — an axes named with `idofig.name(ax, …)` or a colorbar with `idofig.colorbar(…, name=)`.
* `semantic` — derived from meaning: `main.xlabel`, `main.series.<label>`, `main.xtick.<text>`.
* `positional` — derived from order (`main.line0`, one bar of a series). Survives only while
  the drawing keeps its structure; the manifest says so.

A 3D axes' z axis is named like the other two (`main.zlabel`, `main.zaxis`, `main.ztick.<text>`);
its axes have the role `axis3d`. A 3D axis draws its pane and grid in groups of their own,
which carry no id, so each part's id is in the SVG once.

A rasterized part (`rasterized=True`) with a name that is not positional — an author gid, a
label, a colorbar's solids — keeps it in the SVG: its `<image>` is wrapped in `<g
id="<name>">`, one image per such part. Positional rasterized parts (`main.line0` …) merge
into one image as matplotlib draws them, with no id: an image each made 150 rasterized
traces 2.5 times larger. Label or `gid` a rasterized layer a canvas should select. A hidden
one, like any part that is not drawn, has no id in the SVG.

## manifest.json — schema 1

`{schema, figure, panel, render, size{w_pt,h_pt,w_mm,h_mm}, trim?{x_pt,y_pt,w_pt,h_pt}, parts{name: {kind, role,
stability, parent?, group?, members?, bbox, drawn?, props?, thinnest_pt?, effective_scale?, base?}}, axes{name: {bbox,
frame?, matrix?, xscale, yscale, xlim, ylim}}, style{applied, detached, invalid}, warnings}` — `render` is the `build.RENDER` of
the idofig that drew the panel (absent: 0.2.x). `trim` (a trimmed panel only) is the crop in
the drawn panel's points; every `bbox` of such a panel, a part's or an axes', is then
measured from the crop's corner — the frame compose places at the panel's place — so a
consumer that adds a box to the place needs no other change, and the ink check holds boxes
to the crop's size. `bbox` is `[x0, y0, x1, y1]` in the panel's
points with y downwards, whatever the figure's dpi, and a text's (a legend's too) is measured
with the text metrics the SVG is laid out with, the SVG renderer's (Agg's round it to whole
points and, under matplotlib < 3.11, pad a math text a point a side: a `log$_{10}$` xlabel
inside its panel was boxed outside it); it is `null` for a part that is not drawn
(hidden, or inside a hidden axes or legend, or an axis label, tick label, spine or
background of an axes turned off with `axis("off")`, or an annotation whose point is
outside its axes, which matplotlib skips). An axis has no box, drawn or not; `drawn: false`
marks one that is not drawn (in an axes turned off with `axis("off")`, or a hidden axes).
A text's box is the part its clipping lets through
(`null` if it hides all of it); a 3D axes' text (`ax.text(x, y, z, …)`) is measured where it
is drawn, at its projection. A collection matplotlib measures as an infinite box (a
scatter, a LineCollection, a pcolor, a hexbin, an eventplot, an EllipseCollection: most of
them, under matplotlib 3.11), and a quiver, whose box matplotlib gives tens of metres wide, is
measured from the marks it drew — its paths through the transforms and offsets it
draws them with, leaving out a mark at NaN or infinity, which is not drawn — and clipped
like a text (`null` if nothing it drew is seen, or it drew nothing, like a colorbar's
dividers); every other data mark's box, a fill_between's or a pcolormesh's included, is its
whole extent, clipped or not. A mark matplotlib does draw is counted wherever it is: a value
at or below 0 on a log axis, which matplotlib places 1000 decades down, stretches its
collection's box to the axes' edge.
`props` are the current values of the properties the part takes that idofig reads back —
all of them except a legend's `loc`, a patch's `color`, and a collection's `color`, its `size` unless its marks share one, and its `cmap`, `vmin` and `vmax` unless it
maps values to colours — less technically unsupported setters (3D axis tick-mark settings). An
editor cannot tell an override of one of those it does not read back from the script's
value. A colour is `#rrggbb`, or `none` when nothing is drawn in it (a bar's or a pcolor's
default edge, open markers); a collection's is `none` when it draws none, and `null` when its
marks differ, and its edge is `face` when each mark's edge is drawn in its own face colour
(`edgecolors="face"`, a scatter's default) and so merges into its fill. A scatter's '+', 'x',
'|', '_', '1'–'4' and tick markers have no fill: matplotlib edges them in `face` itself, and
their edge, the whole mark, reads the colour it is drawn in. A collection's `linewidth` is `null` when its
marks differ in width, as its colours are; `thinnest_pt` then holds the thinnest it draws
(what the stroke check reads). Its `alpha`, or an image's, is `null` when each mark has its
own (an array: `scatter(…, alpha=[…])`). A number matplotlib reports as NaN or infinite (a width or a font
size a script took from data with a gap, the limits of an all-NaN image) is `null`. A rasterized collection is measured with its marks (a scatter's
sizes, an ellipse's axes, a quiver's arrows) at the size they print at, not the size the raster
pass (at `savefig.dpi`) left them. `base` holds the
values the script drew before the overrides, for the properties overridden and read back
(for an offset, 0; for `scale` 1 and `rotate` 0); a script that saves twice keeps its own values there, unless it set a
value again between the saves.

**A scaled or rotated axes (0.7.0).** An axes' `props` carry its `scale` and `rotate`. Every
part drawn in an axes that is scaled or turned (the axes itself, its twins' parts, an inset's) has
its `bbox` as the axis-aligned box around its box mapped by the axes' matrix (a turned label's
box is the box around its turned box, not its ink), and, when the scale is not 1,
`effective_scale`: the scale it prints at, by which the size and stroke checks multiply its
`fontsize`, `linewidth`, `thinnest_pt` and `tickwidth` (its `props` stay the values set). Its
`axes` entry's `bbox` is the box around the turned frame; `frame` is the frame before the
transform and `matrix` the SVG matrix `[a, b, c, d, e, f]` that maps it, both in the same
points as `bbox` (a trimmed panel's measured from the crop's corner, so the matrix differs from
panel.svg's by the crop's offset): a canvas draws the turned frame as `matrix` applied to
`frame`'s corners and its centre is `frame`'s centre. A `{panel, axes, data}` anchor is placed
in `frame` and mapped by `matrix`, so it stays on its data point. Absent, all three mean
identity, as every manifest before 0.7.0. Since 0.9.0 every individual part also carries
`frame` and, when transformed, `matrix`/`own_matrix`, as specified in Common artist geometry
above. The same measurement rule applies through all actual SVG ancestor groups.

## figure.lock.json — schema 1

`{schema, figure, producers{id: {run, files{path: sha256|null}, journal, discovered,
built_with}}, panels{id: {producer, shared, size, style, svg, manifest, render,
builder_render, idofig}}, figure_svg}`.
A panel is **stale** when its producer's command, files or journal preset changed, its size
or style changed, its `panel.svg` differs from what the build wrote, or it was drawn under
another `render` number by a build this idofig would draw differently. `built_with` (the
Python, idofig, matplotlib and numpy versions of the process that drew the panels) is
recorded, never compared: a new version alone makes nothing stale. `render`
(`build.RENDER`) changes only in a release that draws an unchanged panel differently. The
lock records two: `render` is copied from the panel's manifest, so it is the render of the
idofig that drew the panel (a producer's `run` may name an interpreter with an idofig of its
own); `builder_render` is the render of the idofig that built it. Beside them, `idofig` is
the version that drew the panel, recorded per panel because a build of some of a producer's
panels rewrites its `built_with`; a reason names an entry without one, written by 0.2.x,
`idofig 0.2.x`. A panel drawn under
another render than this idofig's is stale while its `builder_render` differs too (a
rebuild may draw it differently; a panel with neither was built by idofig 0.2.x). When its
`builder_render` is this idofig's, the producer's own idofig drew it and rebuilding with that
idofig changes nothing: the panel is not stale, and `status` and `check` warn that it was
`drawn by idofig 0.2.2, the one its producer's run uses, …` and what to do — for an older
one, ``upgrade idofig where the producer runs, then `idofig build --force <fig>` ``. Drawn by
0.2.x in a figure.json that says schema 3, which 0.2.x refuses, the warning says instead that
that idofig `cannot read this figure.json (schema 3: a letter offset or colour), so its next
build fails`, and gives the same step. The lock does not see that upgrade, so the panel still
reads fresh; `check`, which runs the producer, then reports ``drawn by idofig 0.2.2 (render
1); its producer now draws with render 2 — `idofig build --force <fig>` redraws it`` rather
than "not reproducible".

**Upgrading to 0.9.0.** Render 3 rebuilds manifests with common geometry and composed
artist boxes. Named images gain an outer SVG group enclosing their native transform and clipping;
other unedited SVG drawing stays the same.

**Upgrading from 0.2.x.** Every panel is stale (render 2) until `idofig build` redraws it.
Its panel.svg keeps its bytes unless it has a named rasterized part (every continuous
colorbar: matplotlib rasterizes its solids), a 3D axes, an axes background or legend
frame named by a gid (it gains `data-idofig-role`), or a legend named by a gid, or its script
changes the figure's size after `idofig.panels()` (it is saved at its place size; 0.2.x saved
it at the script's size, and compose warned that it was drawn at another size). A legend's
gid now names its frame, entries and title: a figure legend's were named after `legend`
(`legend.<entry>`), and a style.json entry naming one is detached, reported, until it is
moved to `<gid>.<entry>`; an axes legend's had none. Its manifest:

* gains `render`, the values of the new properties, a patch's `linestyle`, `thinnest_pt`, and
  a box for each collection matplotlib measured as infinite (and a quiver's own);
* reads `none` for a colour nothing is drawn in (0.2.x wrote `#000000`), `face` for a
  collection's edge drawn in its face colour, and `null` for a width its marks do not share
  and for a number that is not finite (0.2.x wrote `NaN`);
* loses the boxes of parts that are never drawn, and measures others anew: a clipped text as
  far as it is seen (`null` if none of it is), a 3D axes' text at its projection, a
  rasterized collection with its marks at the size they print at, and every box of a panel
  whose figure dpi is not 72 (`set_dpi(300)`) in points (0.2.x measured it at dpi/72 its size
  and distance from the corner), and every text and legend in the SVG's text metrics (0.2.x
  measured them on Agg at 72 dpi);
* may gain a font warning, which `check` reports: a text in a generic family (`sans-serif`,
  `serif`, …) is checked as the face it resolves to (see Determinism).

## Determinism

Panels start from matplotlib's defaults plus the journal preset (`idofig.panels()` resets
the rc first, so a matplotlibrc never leaks in); fonts are the bundled Liberation Sans
(Arial metrics), named in the SVG as `Arial, 'Liberation Sans', Helvetica, sans-serif`; no
metadata; producers run with `PYTHONHASHSEED=0` and `MPLBACKEND=Agg`. A direct run sets no
`MPLBACKEND`: `idofig.panels()` selects Agg once it has found its figure, whatever a
matplotlibrc's `backend:` line names (`build`'s `MPLBACKEND` overrides that line too). A
session keeps its backend, chosen or not yet (a notebook's inline or widget backend,
IPython's `%matplotlib qt`, `python -i make.py` and `%run make.py` before anything is plotted,
an `MPLBACKEND` set for it; switched, none of the author's later plots showed, and matplotlib
3.8 closed their open figures). IPython is a session while its shell runs (Jupyter, the
IPython terminal, `%run`), not because a library imported it: seaborn imports ipywidgets
wherever it is installed, which imports IPython, and a plain run is still switched to Agg.
In a session each save draws its panel on an Agg canvas of its own at the figure's dpi, the
session's canvas and dpi given back after (a Retina display doubles a GUI's or a browser's
canvas dpi, which changes the layout: that doubling is undone, never a dpi the script set,
and the figure's own dpi is given back with it; an svg canvas cannot measure a part). What a script measures before it
saves — `ax.clabel`, adjustText, `fig.canvas.draw()` — a session measures on its own canvas,
so on a Retina GUI or an svg canvas such a panel may differ from `build`'s, and `check` then
reports it not reproducible: build it, or run the script, to write the panel to commit.
Rebuilding from the same inputs gives the same bytes; `idofig check` verifies it.

A script may change the rc after `idofig.panels()` (a house style, say), but every panel is
saved under a fixed rc context, `draw.SAVE_RC`, whatever the script set: `svg.fonttype =
none` (text stays text, so its size can be checked), `svg.hashsalt = "idofig"`,
`savefig.bbox = None` and `savefig.pad_inches = 0` (the panel is never cropped to its ink;
it is exactly its `place` size). Every save draws the panel at the size `idofig.panels()` made
it, whatever size the figure has by then, and gives the figure its size back after: a GUI
canvas sizes a figure to its window (macosx's, in whole pixels, as it is made: an 88 × 60 mm
panel was saved at 87.84 × 59.97 mm), and so does a window resized by hand, or a script's own
`set_size_inches`.

A text part whose font is neither the bundled Liberation Sans nor a face that ships with
matplotlib (its `mpl-data`, such as DejaVu Sans or DejaVu Sans Mono: the same file wherever
that matplotlib version is installed) gets a warning in the manifest, reported by `check`:
the panel may lay out differently on another machine. A generic family (`sans-serif`,
`serif`, …) is checked as the face it resolves to through matplotlib's `font.<family>` list,
which the warning names: `font 'sans-serif' resolves to 'Arial' here, which is not bundled
with idofig; …`.

## Checks

Most findings are advisory, reported and never blocking: they are warnings, so `check` still
passes.

| finding | reported by | text |
|---|---|---|
| a `{"mm": n}` width that is none of the journal's stated widths (within 0.5 mm) | `check`, the server's `rules` | `fig-1: width 170 mm matches none of Nature's widths (single 89 mm, double 183 mm)` |
| the fitted figure is wider than its column by more than 0.01 mm | `compose`, `status`, `check` | `the figure is 188 mm wide; its column allows 183 mm` |
| the fitted figure is taller than figure.json's `height` or the journal's `maxHeightMm` by more than 0.01 mm | `compose`, `status`, `check` | `the figure is 40 mm tall; its height allows 35 mm`, `the figure is 210 mm tall; Neuron allows 200 mm` |
| a named text, legend or axes part that is drawn leaves its panel's box by more than 0.2 mm | `check`, the server's `rules` | `fig-1/a: main.xlabel is 1.3 mm outside its panel's box` |
| panel letters smaller than the journal's `minFontPt` | `check`, the server's `rules` | `fig-1: panel letters are 4 pt; Nature requires at least 5 pt` |
| a drawn stroke — a line (not a markers-only one), spine, patch (not one whose edge has no line style), collection (its `thinnest_pt` when its marks differ in width) or an axis' major tick marks (its `tickwidth`) — thinner than the journal's `lineWeightPt.min` | `check`, the server's `rules` | `fig-1/a: main.series.links is 0.2 pt wide; Nature states at least 0.25 pt` |
| a drawn text larger than the journal's `maxFontPt` | `check`, the server's `rules` | `fig-1/a: main.title is 9 pt; Nature states at most 7 pt` |

Sizes and widths are the ones printed: a part with an `effective_scale` (drawn in a scaled axes,
see manifest.json) is checked at its `fontsize`, `linewidth`, `thinnest_pt` or `tickwidth`
times that scale, and reported at it (`main.xlabel is 5.6 pt` for a 7 pt label at `scale`
0.8); the ink check reads the transformed boxes.

One rule is not advisory: it is an error, and `check` fails on it.

| finding | reported by | text |
|---|---|---|
| a drawn text smaller than the journal's `minFontPt` | `check`, the server's `rules` | `fig-1/a: main.xlabel is 4 pt; Nature requires at least 5 pt` |

Each rule applies only where the journal states its number (D4). An edge drawn in no colour
(its manifest colour is `none`: pcolor's and a bar's default edge, a spine set to `none`) is
no stroke, whatever its width, and neither is one drawn in its own face colour (`face`: a
scatter's default edge), which merges into the fill, nor a patch's edge with no line style
(`linestyle: none`, which matplotlib draws 0 wide). A '+' or 'x' marker has no fill, so its
edge is a stroke and is checked (see manifest.json).

**One finding per group.** The members of a group that break the same rule — an axis' tick
labels (`main.xtick.*`), a series' bars, and, counted as its group, a legend's entries — are
one finding that names the group, with how many parts broke it and the range of their values:
`fig-1/a: main.xtick.* is 4–4.5 pt (3 parts); Nature requires at least 5 pt`. When one member
breaks it, the finding names that member. Every per-part finding has the form
`<figure>/<panel>: <part> is …`, and `<part>` is a part or group in that panel's manifest, so
an editor can select what a finding names.

A part that is not drawn has no box (see manifest.json), so it is never a finding, and a
clipped text is checked for the part of it that is seen. An axis has no box, drawn or not: its
tick marks are checked while it is `visible`, drawn and its `ticklength` is above 0 — not in an
axes turned off with `axis("off")`, which draws none; minor tick marks are not (idofig's rc draws them at 0.75 × the
major width, so its own defaults would be findings). A manifest another render wrote
(0.2.x measured parts it never drew, and a `set_dpi(300)` panel at 300/72 its size) is not
checked for ink, and only its lines and spines for stroke width, as 0.2.x checked them (it
wrote `#000000` for an edge drawn in no colour): its panel is stale until it is rebuilt, or,
drawn by the producer's own idofig, carries a warning that says so.
Data marks (lines, patches, collections, images) are not checked for ink outside the panel:
they are clipped to their axes, and matplotlib reports their box unclipped (a collection box
idofig measures is clipped; one matplotlib gives is not). Letters are not
checked against `maxFontPt`: no preset states a panel-label size, and labels are set larger
than the text they label; a journal that states no floor is silent about letters (D4).
