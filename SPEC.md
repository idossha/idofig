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
    edit.lock               one writer of figure.json/style.json at a time (serve, rpc, `idofig style`)
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
| axes | facecolor, visible, dx_mm, dy_mm, scale, rotate; a 3D axes also elev, azim, roll, zoom, proj |
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
at the script's size and compose warned that it was drawn at another; or unless (0.10.0) it
draws bars, a scatter, a marker line or a grid, whose elements gain data attributes, mark ids
and gridline names (manifest.json, *Data*) — nothing is drawn differently. `tests/golden/`
holds such a panel, whose panel.svg is 0.2.2's to the byte but for its three bars' data
attributes, and a test checks under any matplotlib that the draws a save wraps (tracking what
was drawn, naming rasterized parts) add no byte.

**Tick marks.** `tickdir` sets the direction of an axis' major and minor tick marks;
`ticklength` and `tickwidth` set its major ones. They are applied with `tick_params` before
layout. A 3D axis (role `axis3d`) refuses them: it draws its tick marks from its own
settings, never from `tick_params`.

**A 3D axes' view (0.11.0).** A 3D axes (role `axes3d`) takes its view from style.json, applied
before layout like any other override, so an editor turns a mesh by writing a file and a
rebuild draws it:

| prop | value | applied as |
|---|---|---|
| `elev`, `azim`, `roll` | finite degrees, −180 … 180 | `ax.view_init(elev=…, azim=…, roll=…)`'s angles; the others and the vertical axis stay as the script set them (`view_init` itself resets what it is not given) |
| `zoom` | 0.1 … 10 | `ax.set_box_aspect(<its aspect>, zoom=…)` |
| `proj` | `ortho` \| `persp` | `ax.set_proj_type(…)`, only when it differs (a script's own focal length survives `persp`; a new `persp` has matplotlib's focal length 1) |

A 2D axes (role `axes`) and a colorbar refuse them, `only a 3D axes has a view`; the manifest's
`props` of a 3D axes carry the five as drawn (`zoom` read back from the box: its length over
matplotlib's 1.8294640721620434, × 25/24 since 3.9).

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

**Gridlines, bar series, marks (0.10.0).** A drawn major gridline is named after its tick's
label (its value when the tick has none): `main.xgrid.0-5`, role `gridline`, `semantic`, in the
group `main.xgrid.*` (role `grid`), and takes a line's properties. One that is not drawn (no
grid) is not named, so its panel keeps its bytes; a 3D axis' grid is not named. An unlabelled
bar container (`ax.bar(x, h)`, `ax.hist(v)`) is the group `main.bars0`, `main.bars1`, … in the
order the axes holds them (role `series`, `positional`) over its bars, which keep their names
(`main.patch3`); a labelled one was already the group `main.series.<label>`. A pattern such as
`main.*` matches the gridlines, as it matches the tick labels. A scatter's or a marker line's
marks are not parts: in panel.svg the mark of data index *i* is `<part>.<i>` (manifest.json,
*Data*), `positional` — an index names it, so a new point before it renumbers it — and no
style.json entry addresses one (it would be detached). A bar's index is positional too
(`main.series.control.0`); its category, where it has one, is `data-key`, which survives a
reordering and is what a consumer matches bars across two builds on.

A 3D axes' z axis is named like the other two (`main.zlabel`, `main.zaxis`, `main.ztick.<text>`);
its axes have the role `axis3d`, and the 3D axes itself the role `axes3d` (0.11.0; a 2D axes is
`axes`, a colorbar's `colorbar`, whatever names them, a gid included). A mesh drawn with
`idofig.mesh` is `<axes>.mesh.<name>` — the `name=` it was given, else its file's stem, as a slug
(`main.mesh.cortex`) — role `mesh`, `semantic`; a second one of the same name on that axes is
`….2`, positional, and reported. A 3D axis draws its pane and grid in groups of their own,
which carry no id, so each part's id is in the SVG once.

**Helper parts (0.13.0).** What `idofig.image` and `idofig.neuro` draw is named by the helper,
`<axes>.<what it is>`, `semantic`, whatever order it was drawn in: `<axes>.image` (role `image`);
a topomap's `<axes>.field` (`image`), `<axes>.head`, `<axes>.nose`, `<axes>.ear.left`,
`<axes>.ear.right` (role `outline`, revealed with the scaffold in `build`), `<axes>.mask` (`line`),
`<axes>.sensors` and `<axes>.contours` (`collection`), `<axes>.label` (`text`); a slice's
`<axes>.anatomy`, `<axes>.overlay` (`image`), `<axes>.roi` (`collection`), `<axes>.crosshair.h`
and `.v` (`line`), `<axes>.mark.<letter>` and `<axes>.coordinate` (`text`); a view's
`<axes>.tag`; an electrode's `<axes>.electrode.<name>` (`patch`) and its `.sign`, `.sign.v`,
`.leader` (`line`) and `.label` (`text`); a callout's `<name>.<label>` and `.leader`. A surface is
a mesh, `<axes>.mesh.<name>`. A gid on
such a part still wins, and a second part of one name on an axes is `….2`, positional, and
reported.

A rasterized part (`rasterized=True`) with a name that is not positional — an author gid, a
label, a colorbar's solids — keeps it in the SVG: its `<image>` is wrapped in `<g
id="<name>">`, one image per such part. Positional rasterized parts (`main.line0` …) merge
into one image as matplotlib draws them, with no id: an image each made 150 rasterized
traces 2.5 times larger. Label or `gid` a rasterized layer a canvas should select. A hidden
one, like any part that is not drawn, has no id in the SVG.

## manifest.json — schema 1

`{schema, figure, panel, render, size{w_pt,h_pt,w_mm,h_mm}, trim?{x_pt,y_pt,w_pt,h_pt}, parts{name: {kind, role,
stability, parent?, group?, members?, bbox, drawn?, props?, thinnest_pt?, effective_scale?, base?, data?, series?, mesh?}},
axes{name: {bbox, frame?, matrix?, xscale, yscale, xlim, ylim, anchors?, categories?}}, build[{stage, parts, entrance}],
style{applied, detached, invalid}, warnings}` — `render` is the `build.RENDER` of
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

**Data (0.10.0).** A part that is a line, a scatter or a bar series drawn in its axes' data
coordinates carries `data`, what it drew, as matplotlib holds it after unit conversion (a
category is its index, a date its day number); a value that is not finite is `null`:

| `kind` | from | fields |
|---|---|---|
| `line` | a `Line2D` with a line style (markers or not) | `n`, `x`, `y`, `addressable`/`why` when it has markers |
| `points` | a `Line2D` with markers and no line, a scatter (`PathCollection`) | `n`, `x`, `y`, `values` (a scatter's colour-mapped `c`, when it has one per point), `addressable`, `why?` |
| `bars` | a bar series group (`main.series.<label>`, `main.bars<k>`) | `n`, `orientation` (`vertical`\|`horizontal`), `positions` (each bar's centre on its category axis), `values` (signed height, or width), `baselines`, `keys?` |

`keys` is each bar's category when every bar is centred on a category of a categorical axis
and no two share one (bars offset from their category by hand have none). A line drawn partly
in axes coordinates (`axhline`), a 3D line, fills, images and meshes have no `data`; an
errorbar's data line and caps are lines of its group and carry their own. **Size cap:** a series stores at
most `DATA_CAP` = 1000 values; past it, `x`/`y`/`values` (or a bar series' arrays) are left
out, `omitted` says so (`"5000 values; the manifest stores at most 1000"`), and `x_range`,
`y_range` give the finite minimum and maximum. Nothing is truncated: a series has all its
values or none.

`addressable: true` means panel.svg gives the mark of each finite point *i* the id
`<part>.<i>` and `data-index="i"` (and `data-value` when the series has `values`); `false`
leaves the series one group and `why` says why: more than 1000 marks, rasterized, its group
not in panel.svg, an id taken, or `panel.svg draws 3 marks for its 4 points` — matplotlib skips
a mark it cannot place (a value ≤ 0 on a log axis), and a count that does not match is never
guessed at. A mark far outside the view is still drawn, clipped, and keeps its id. A bar
series' bars carry, on their own `<g>`, `data-index` (the bar's index in its container),
`data-value` and `data-key`.

A legend entry made from the axes' labelled artists (`ax.legend()`, `fig.legend()`) carries
`series`: the part (or group) its handle is. The join is by artist — the entry's handle is the
artist in the same place of `get_legend_handles_labels()`, used only when the legend's texts
are those labels one for one — never by text: a legend of hand-picked handles has no `series`.

**Mesh (0.11.0).** A part `idofig.mesh` drew carries `mesh: {path, faces, vertices,
file_faces, file_vertices, bounds}`: the file, relative to the project root in POSIX form
(absolute when it is outside the project); the triangles and vertices it drew (vertices as the
file stores them: an STL stores three per facet); the file's own triangles and vertices
(0.12.0; equal to the drawn ones unless the mesh was simplified, see Meshes); and `bounds`,
`[[xmin, ymin, zmin], [xmax, ymax, zmax]]` of the drawn triangles in data coordinates after
the file's node transforms, rounded to 6 decimals (a simplified mesh's corners move a little,
so its bounds may differ from the file's in the last digits). An editor loads the file
by `path` to show it in 3D, and the bounds are the box the panel frames.

**Anchors (0.10.0).** An axes of a flat projection gives, per linear or log axis, two
`[data, point]` pairs read from matplotlib's data transform at its limits: `anchors: {x: [[x0,
px0], [x1, px1]], y: [[y0, py0], [y1, py1]]}`, in the same points as `bbox` (y down, from the
crop's corner when trimmed: add `trim`'s `x_pt`/`y_pt` for panel.svg's own coordinates) and
before `matrix` (a turned axes' value is placed in `frame`, then mapped). A value `v` is at
`p0 + (v − d0) / (d1 − d0) × (p1 − p0)` on a linear axis, the same in `log v` on a log one. A
symlog, logit or function axis, and a polar or 3D axes, has no anchors for that axis.
`categories: {x: ["sham", "low", "high"]}` names the category each value of a categorical axis
stands for (value = index).

**Build (0.10.0).** `build` is a hint for an application that reveals the panel step by step;
idofig animates nothing. Each step names parts or groups of `parts` (a group expands to its
`members`; a series with `addressable` marks expands to `<part>.<i>`), a `stage` and an
`entrance`, in this order: one `scaffold` step (every axes' background, spines, axes, axis
labels and titles, and the figure's suptitles), one `grid` step (the gridline groups), one
`data` step per series or unnamed mark in the order matplotlib draws them (by axes, then
zorder, then the order they were added), one `legend` step per legend or colorbar, and one
`annotation` step per free text. Entrances are a closed vocabulary: `draw-on` (a line),
`grow` (a bar series, from its `baselines`), `stagger` (addressable points, by `data-index`),
`fade` (everything else). The figure's background, parts drawn inside a listed part (tick
labels in an axis, a legend's entries, a colorbar's contents) and parts that are not drawn are
in no step; what is drawn and unnamed is not in any step either, and stays visible throughout.

## figure.lock.json — schema 1

`{schema, figure, producers{id: {run, files{path: sha256|null}, journal, discovered,
built_with}}, panels{id: {producer, shared, size, style, svg, manifest, render,
builder_render, idofig}}, figure_svg}`.
A panel is **stale** when its producer's command, files or journal preset changed, its size
or style changed, its `panel.svg` differs from what the build wrote, or it was drawn under
another `render` number by a build this idofig would draw differently. `built_with` (the
Python, idofig, matplotlib and numpy versions of the process that drew the panels, and mne's
and nibabel's when the producer imported them, 0.13.0) is
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

**Upgrading to 0.13.0.** Render 6 still: nothing is stale and no panel is drawn differently.
`idofig.image` and `idofig.neuro` are new; a producer that imports mne or nibabel records their
versions in the lock's `built_with`, which is never compared.

**Upgrading to 0.12.0.** Render 6: every panel is stale once. A mesh of more than 100 000
triangles is drawn simplified (`max_faces`; pass `max_faces=None` to draw it whole, as 0.11.0
did), and every mesh part's `mesh` gains `file_faces` and `file_vertices`. Other panels are
drawn as before; unbumped, a large-mesh panel built by 0.11.0 read fresh while `check`, which
redraws it, failed it as not reproducible.

**Upgrading to 0.11.0.** Render 5: every panel is stale once. A 3D axes' role is `axes3d`, not
`axes`, and its `props` gain `elev`, `azim`, `roll`, `zoom`, `proj`; an axes named by a gid has
the role it is (`axes`, `axes3d` or `colorbar`), where it had `author`. Nothing is drawn
differently and no name changes: only manifests change. Unbumped, a 3D panel built by 0.10.0
read fresh while `check`, which redraws it, failed it as not reproducible.

**Upgrading to 0.10.0.** Render 4: every panel is stale once. Bars, scatters, marker lines
and drawn grids gain data attributes, mark ids and gridline names in panel.svg; nothing is
drawn differently, no existing name changes, and a panel with none of them keeps its bytes.
Manifests gain `data`, `series`, `anchors`, `categories` and `build`, and the gridline and
`main.bars<k>` parts: a pattern such as `main.*` now also styles the gridlines, and the stroke
check reads them (one finding for `main.xgrid.*`).

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

## Meshes (0.11.0)

`idofig.mesh(ax, path, *, name=None, color=None, scalars=None, cmap="viridis", vmin=None,
vmax=None, shade=True, smooth=True, alpha=None, rasterized=None, max_faces=100_000,
background=None)` draws a
triangle mesh file on a 3D axes
(`add_subplot(projection="3d")`; any other axes is an error) and returns its collection. The
file is input data the producer reads, like a `.npy` — never a figure format: list it in the
producer's `inputs`, or editing it leaves the panel fresh.

* `path`: `.glb`, `.gltf`, `.stl`, `.ply` or `.obj`, relative to the producer's working
  directory (the project root under `build`) or absolute, read with trimesh (a dependency
  imported only by `idofig.mesh`; `import idofig`, composing and the server never import it).
  A scene is flattened with each node's transform applied, nodes in name order. Vertices are
  kept as stored (none merged), so a per-vertex field computed for the file matches it.
  Triangles only; a scene's point clouds and paths are skipped, and a file with no triangle
  is an error.
* Colour, first that applies: `scalars` — one value per vertex (averaged over each face's
  three) or one per face (per vertex when the counts are equal), through `cmap`, `vmin`,
  `vmax` (style.json's collection `cmap`/`vmin`/`vmax` override them) — then `color`, then the
  file's own vertex or face colours (a glTF material sampled to colours), then `#c8c8c8`.
  `background` (0.13.0; one colour, or one per face; it needs `scalars`) colours the faces whose
  scalar is NaN — among per-vertex scalars, a face with a NaN corner — which otherwise take the
  colormap's "bad" colour (transparent); it follows a simplified face as its value does.
* `max_faces` (0.12.0): a file of more triangles is simplified to at most `max_faces`, about
  that many, before anything else is computed from it (normals, bounds, rasterizing); `None`
  draws every triangle, and anything but a whole number ≥ 1 or `None` is an error. A surface
  past 100 000 triangles is mostly triangles smaller than a printed pixel at a panel's size.
  The simplification is quadric edge collapse (fast-simplification, a dependency imported only
  then): vertices at the same position are merged first (an STL's three per facet; unmerged,
  no edge is shared and whole triangles were removed: 31 % of a test sphere's area was left),
  zero-area triangles are left out, and edges collapse until no more than `max_faces` remain.
  Every triangle left is one of the file's with its corners moved, so a value or colour per
  face follows it exactly: `scalars` per vertex are averaged per face on the file's mesh as
  before, then each drawn face takes its file face's value; per-face `scalars` and the file's
  own colours likewise. If which file face a drawn one came from cannot be recovered (the
  library's replay of its collapses disagreeing with its result), the mesh is refused, never
  drawn with colours on the wrong faces. The same file and arguments give the same triangles
  (the algorithm has no randomness; a rebuild is byte-identical), under a given
  fast-simplification build, as the bytes are under a given matplotlib. It needs
  fast-simplification 0.1.11 or later: 0.1.7 and 0.1.8 simplify differently on the first call in
  a process (a rebuild differed; `test_a_simplified_mesh_panel_rebuilds_byte_for_byte` fails
  under 0.1.7), and 0.1.9 and 0.1.10 require numpy 2. trimesh's own
  `simplify_quadric_decimation` calls the same library but cannot say which triangle each one
  came from, so idofig calls it directly. A 152 096-face surface
  built in 2.1 s whole, 1.7 s at 100 000 and 1.2 s at 50 000 (matplotlib 3.11.2, Apple M2 Max,
  2026-10-09; the simplification itself 0.1 s). Better still, commit a small file:
  `idofig mesh-simplify data/cortex.ply data/cortex-50k.ply --faces 50000` writes the same
  simplification as a file (`.ply` keeps the file's colours per face; `.glb`, `.obj` and `.stl`
  are written only for a file without colours, which they could not keep per face; writing over
  the file being read is refused).
* `shade=True` is a headlight: at every draw each face is `rgb × (0.35 + 0.65·|n·v|)`, n its
  normal and v the direction to the viewer under the axes' current elev, azim and roll (in
  the axes' box, where a normal is scaled by the inverse of the box's stretch), so a view set
  in style.json is lit from the front.
* `smooth=True` lights each face by a normal smoothed over its neighbours, not its own (lit
  flat, the small irregular triangles of a cortical surface come out speckled): each vertex's
  normal is the sum of the unnormalized normals (twice the area) of the faces around it,
  normalized, and a face's is the sum of its three corners', each first turned to the face's
  side. A face none of whose vertices another face shares (an STL's: three of its own per
  facet), or whose smoothed normal vanishes, keeps its own. The sums assume the file winds its
  faces consistently, as a manifold export does; where neighbours are wound oppositely a
  vertex's normal is partly cancelled, which no rule can mend without knowing the outside.
  `smooth=False` lights every face flat. Colours stay one per face.
* The projection is the one matplotlib draws, made for all triangles at once: the corners
  through `np.dot(M, …)`, a face's depth by the collection's zsort (the mean of its corners'),
  furthest first, the same 2D triangles, colours and returned zorder (a test compares them
  with matplotlib's own). Faces of equal depth are drawn in the file's order, as matplotlib
  before 3.11 draws them; 3.11's sort is not stable, and its order for a tie could differ by
  CPU. A collection clipped to the view (`axlim_clip`), with path codes or a fixed sort depth,
  or on a non-linear axis is projected by matplotlib itself. matplotlib before 3.11 projects
  face by face in Python: a 149k-face mesh's build took 12–14 s under 3.10.9 and takes 2.9 s.
* The axes' limits become the bounds of every mesh drawn on it so far (a flat mesh gets a
  thousandth of its largest extent across) and its box aspect their extents, one scale for x,
  y and z, at the axes' current zoom. Axis visibility is the script's (`ax.set_axis_off()`).
* No edges are drawn. Past `MESH_VECTOR_FACES` = 20 000 drawn faces (`rasterized=None`) the mesh is
  rasterized — at `savefig.dpi`, 600 or the journal's `minDpi` if higher — with antialiasing
  off, which leaves no seams between triangles; it keeps its name in panel.svg (one `<image>` in
  `<g id="main.mesh.cortex">`). A vector mesh's triangles may show hairline seams where an SVG
  viewer antialiases each one.
* matplotlib sorts a 3D axes' collections as wholes: two meshes that pass through each other
  are drawn one over the other. Put such meshes in one file.

`idofig add-panel FIG PANEL --mesh <project file>` (the RPC's `add_panel` with `mesh`; the
`mesh` template, implied) writes a producer that draws the file on a 3D axes named `main`,
axis off, with the file in its `inputs`. The file must be inside the project.

## Images and neuroscience panels (0.13.0)

Helpers that draw on an axes the producer made and name what they drew (Part names, *Helper
parts*). Every file they read is input data: list it in the producer's `inputs`, or editing it
leaves the panel fresh. Every size they take is in mm on the page.

**`idofig.image(fig, src, left, bottom, width, height, *, name, trim=True, **imshow)`** shows a
raster render — a file matplotlib reads (PNG; JPEG or TIFF through Pillow) or an (H, W), (H, W,
3) or (H, W, 4) array — as large as fits in the box (mm from the panel's bottom-left, as
`axes_mm`), its aspect kept, centred, on a new axes named `name`, axis off; the image is
`<name>.image`. It is embedded with `interpolation="none"` unless the call says otherwise: the
SVG carries the image's own pixels, never ones resampled to a dpi. With `trim`, an image with an
alpha channel is first cropped to its pixels with any alpha and bled (`rasters.bleed`): each
fully transparent pixel takes the colour of the nearest pixel with alpha along its row or column
(the row on a tie; repeated until every pixel has one), its alpha unchanged. A renderer leaves
black under alpha 0, and a filter or viewer that blends colour and alpha separately draws it as a
dark fringe. The axes' data coordinates are the file's pixels — x right, y down, a pixel's centre
on whole numbers — cropped or not, so a point measured on the render (an electrode, an anchor) is
drawn on it where it was measured. `rasters.crop_alpha` crops without bleeding. numpy only.

**`idofig.neuro`** (`pip install "idofig[eeg]"` for topomaps, `"idofig[mri]"` for surfaces,
slices and what is read from volumes, `"idofig[neuro]"` for both; the marks need neither;
importing `idofig.neuro` imports neither mne nor nibabel, and calling a helper without its extra
is an error that names it).

*Topomaps* (`eeg`):

* `topomap(ax, values, pos, *, mask=None, sensors=False, contours=0, cmap="RdBu_r", vlim=None,
  clip=True, marker_mm=0.8, mask_color="black", label=None, label_props=None, **mne_kwargs)`
  draws `mne.viz.plot_topomap` of one value per channel at `pos` (an mne `Info` or an (n, 2)
  array) and returns the map's image. `vlim` defaults to ± the largest finite |value|. `mask` (n
  booleans or channel indices) marks channels with filled dots `marker_mm` across (`mask_params`
  merges over them). The outlines take the rc's `axes.linewidth`; with `clip` the map is clipped
  at the head outline (the circle through its extremes), where mne clips about 1 % outside it.
  The outlines are named by shape, not order: the head is the outline with the most points, the
  nose the one with three, the ears left and right of the head's centre. `label` (a cluster's
  p, say) is written under the head, `<axes>.label`, with `label_props`.

*Surfaces* (`mri`):

* `surface(ax, surf, values=None, *, sulc=None, hemi=None, view="lateral", threshold=None,
  cmap="RdBu_r", vmin=None, vmax=None, name=None, background=None, outline=None,
  outline_color=None, proj="ortho", zoom_to_fit=True, **mesh_kwargs)` draws a cortical surface — a
  FreeSurfer surface (`lh.inflated`), a GIFTI `.surf.gii`, or any file `idofig.mesh` reads; or a
  list of them (both hemispheres on one axes, `values`, `sulc` and `outline` lists to match) — on
  a 3D axes as idofig meshes (Meshes: lit from the viewer, simplified past `max_faces`, the
  manifest's `mesh.path` the surface file), axis and background off, each named
  `<axes>.mesh.<name (one surface only), else its hemisphere, else its file's stem>`; returns the
  collection, or the list. `values` (per vertex: an array, a FreeSurfer morph file,
  `.mgh`/`.mgz`, or GIFTI data) colour it through `cmap`; a face with a vertex that is NaN or
  under `|threshold|` shows the anatomy instead: two greys from `sulc` (per vertex, FreeSurfer's
  sign: `#8c8c8c` where a face's mean is positive, a sulcus; `#c8c8c8` otherwise), else
  `background` (default `#c8c8c8`; a medial wall left NaN takes it). Without `values` the whole
  surface is its anatomy. The mesh's `background` is how: `idofig.mesh(..., background=)` (one
  colour, or one per face) colours the faces whose scalar is NaN, and style.json's
  `cmap`/`vmin`/`vmax` still restyle the rest. `outline` (a boolean per vertex: a region, a
  cluster) draws the faces with vertices both in and out of it — its border, one face wide — in
  `outline_color` (the rc's `axes.edgecolor`), over any value and hidden wherever the surface
  hides it. `view` starts the camera, in RAS (`VIEWS`): left `lateral` (elev 0, azim 180) and
  `medial` (0, 0), right `lateral` (0, 0) and `medial` (0, 180), `dorsal` (90, −90: anterior up,
  left on the left), `ventral` (−90, 90: anterior up, left on the right), `anterior` (0, 90),
  `posterior` (0, −90), or `(elev, azim)`; lateral and medial need one hemisphere (`hemi`, or a
  file named `lh.*`, `rh.*`, `*hemi-L*`, `*.L.*`, …). style.json's `elev`/`azim`/`roll`/`zoom`/
  `proj` on the axes turn it from there, as for any mesh.
* `fit(ax, margin=0.98)` (what `zoom_to_fit` does) zooms the meshes on a 3D axes to fill `margin`
  of the box the axes was placed in, under its view and projection, and returns the zoom (rounded
  to 4 decimals; style.json's `zoom` overrides it). A 3D axes draws in the square of its shorter
  side, so a box that is not square could not be filled: the axes is made the square of the box's
  longer side, centred on it (moved by the small offset matplotlib draws its box at, so the
  meshes are centred), and may overlap its neighbours, its background off. The fill is measured
  where matplotlib projects every vertex, and is exact in an orthographic view. The box is the
  axes' place when `fit` is first called on it; a later call fills the same box.
* `view_size(surf, view="lateral", hemi=None)` is the width and height, in the surface's mm, of
  one surface or several seen from `view` orthographically: the shape of the box a fitted surface
  fills, so a layout can size its axes and give several views one scale. Up on the screen is z
  turned toward the viewer, and right is up × the direction to the viewer.
* `surface_views(fig, left, bottom, width, height, surfaces, values=None, *, views=((left,
  lateral), (left, medial), (right, medial), (right, lateral)), sulc=None, outline=None, gap=1.5,
  tags=None, name="brain", **surface_kwargs)` lays out views in a row (each a hemisphere —
  `left`, `right` or `both` — and a view; `surfaces`, `values`, `sulc`, `outline` dicts by
  hemisphere) at one scale, as large as fits in the box, centred, `gap` mm apart: each view's box
  is its `view_size` times the scale, and its 3D axes, `<name>.<hemisphere>.<view>`, is fitted to
  it. `tags` (True: `L lat`, `R med`, `ven` …; or one text per view) are written under the views
  as `….tag`. Returns the axes and the scale (mm on the page per mm of brain).
* `parcel_values(annot, values, default=nan)` spreads {parcel name: value} over the vertices of a
  FreeSurfer `.annot` (or a GIFTI label file); a parcel not given, or no parcel, gets `default`;
  a name the file does not have is an error.

*Volumes* (`mri`). A volume is a path nibabel reads, a nibabel image, or `(either, k)`: the k-th
volume of a 4-D file. It is turned to RAS (`as_closest_canonical`: no resampling); an oblique
volume is an error.

* `volume_slice(ax, anatomy=None, *, axis="z", at=0.0, overlay=None, cmap="RdBu_r", vmin=None,
  vmax=None, norm=None, threshold=None, mask=None, roi=None, roi_color=None, roi_width=None,
  crosshair=None, crosshair_color="white", crosshair_width=None, halo=None, halo_pt=0.8,
  orientation=False, coordinate=False, extent=None, anatomy_limits=None, radiological=False,
  interpolation="nearest", anatomy_interpolation="bilinear")` cuts each volume at its voxel
  nearest `at` mm along `axis` (`x` sagittal, `y` coronal, `z` axial); `at` outside one is an
  error. The axes' units are mm (`imshow` extents at the voxel edges), so volumes on different
  grids line up as they are; `extent=(left, right, bottom, top)` crops the slice, else the anatomy
  (else the overlay) frames it. Axial and coronal slices are neurological (the subject's left on
  the left) unless `radiological`; sagittal has anterior on the right. The anatomy is grey from
  its 1st to 99.5th percentile of finite non-zero voxels unless `anatomy_limits`; the overlay is
  hidden where it is NaN, under `|threshold|`, or where `mask` (on the overlay's grid) is 0;
  `norm` and `vmin`/`vmax` exclude each other. The roi is its 0.5 contour in `roi_color`/
  `roi_width`, else the rc's `axes.edgecolor` and `axes.linewidth`. `crosshair` (x, y, z mm)
  draws its two in-plane coordinates as lines across the slice in `crosshair_color`
  (`crosshair_width`, else the rc's `axes.linewidth`). `halo` (a colour) draws the roi and the
  crosshair over a line `halo_pt` wider in it. `orientation` writes the sides' letters inside the
  slice, white over a dark halo: True the horizontal pair in the top corners (L and R, or P and A
  on a sagittal slice; swapped when radiological), `"all"` all four at the edges' middles (with
  P/A, I/S). `coordinate` writes under the slice where it is cut — `z = 12 mm`, or with a
  crosshair `x = −25, y = −22, z = −14 mm` (typographic minus, whole mm). Parts:
  `<axes>.anatomy`, `<axes>.overlay`, `<axes>.roi`, `<axes>.crosshair.h`, `<axes>.crosshair.v`,
  `<axes>.mark.<letter>`, `<axes>.coordinate`. Equal aspect, axis off. Returns the overlay's
  image, else the anatomy's.
* `centroid(volume, threshold=0.5, side=None)` is the mean position (x, y, z mm) of the voxels
  above `threshold`, on the subject's `left` (x < 0) or `right` (x > 0) only when `side` says;
  none is an error. Where to cut through a target, or aim a crosshair.
* `line_profile(volume, through, axis="x", *, start=None, stop=None, step=1.0, mask=None,
  average_mm=0.0)` samples the volume along the line through `through` parallel to `axis`, from
  `start` to `stop` mm along it (default: the volume's span) every `step` mm, and returns the
  positions and the values. Trilinear over the voxels that are finite and inside `mask` (on the
  volume's grid), weighed by it: NaN where less than half the weight is there, so an edge is not
  eroded toward zero. With `average_mm` each sample is the mean (NaN ignored) over points every
  1 mm out to that distance across the line in both other axes. numpy only. Exact on a field
  linear in x, y and z.

* `volume_to_surface(volume, surf, *, radius=1.0, samples=5, wider=3.0, wider_samples=7,
  mask=None, cortex=None, fill=True)` gives one value per vertex of a surface file: the mean (NaN
  ignored) of `samples` points along the vertex's normal (its faces' unnormalized normals summed,
  normalized) from −`radius` to +`radius` mm, each read as `line_profile` reads (trilinear over
  finite voxels inside `mask`, NaN under half the weight). A vertex none reached is read again to
  `wider` mm with `wider_samples` points (None: not). `cortex` (a boolean per vertex, or a
  per-vertex file, > 0 inside) makes every other vertex NaN (the medial wall); with `fill` a cortex
  vertex still unread takes the mean of its read neighbours, repeated inward, and an island with
  none stays NaN. nilearn's `vol_to_surf(kind="line")` samples the same lines but lets a NaN voxel
  make its point NaN: on the carrier-only letter's group means over fsaverage40k (2026-10-11) the
  two agreed on every NaN, at r ≥ 0.9986 with a median difference of 6·10⁻⁶ V/m, differing only at
  the brain mask's edge. numpy only.

*Marks* (no extra):

* `electrodes(ax, xy, names, *, colors="black", signs=None, radius_mm=1.15, labels=True,
  box=None, obstacles=None, label_color=None, fontsize=None, weight="bold", halo="white")` draws
  at each point (the axes' data units: a render's pixels, a cap map's coordinates) a disc
  `radius_mm` across in its colour with a white edge (0.6 pt), a white + or − (0.9 pt, 0.55 of the
  radius each way) from `signs` (1, −1; 0 or None: none), and with `labels` its name. Discs,
  signs and labels are drawn in mm from the axes' corner (they follow the axes wherever it is
  moved). The labels are placed by `place_labels(xy, sizes, radius, box, obstacles)`: each in one
  of 12 directions at 0.45, 1.9 or 3.4 mm beyond its disc, scored by 60 per mm² outside `box`
  (default the axes, less 0.3 mm), over a disc (the electrodes' and `obstacles`', x, y in data
  units and a radius in mm, each 0.25 mm wider) or over another label (each 0.35 mm wider), plus
  the step and 0.35·|sin| of the direction (beside before above or below); four labels or fewer
  by trying every combination, more by moving one at a time to its best place until none moves.
  A placement with labels overlapping each other or outside the box is an error, never drawn. A
  label set off from its disc gets a leader in its colour. Parts: `<axes>.electrode.<name>` (the
  disc), `….sign`, `….sign.v`, `….label`, `….leader`. Returns the labels' centres.
* `project(ax, points)` is where `points` (n × 3 on a 3D axes, n × 2 on a 2D one) are drawn, in mm
  from the panel's bottom-left, as the axes is placed and turned when it is called (place it with
  `axes_mm` on a `layout=None` panel so that is where it prints); a view turned later in
  style.json moves the drawing, not anchors computed before.
* `callouts(fig, anchors, labels, *, centre=None, reach=4.0, spacing=None, name="callouts",
  color=None, fontsize=None, gap=0.4)` draws, on a transparent axes over the whole panel named
  `name`, a leader from each anchor (panel mm) `reach` mm away from `centre` (default the anchors'
  mean) and its label `gap` mm beyond it — left of an anchor left of the centre, right of the
  others. The labels on each side are at least `spacing` mm apart (default 1.2 lines): sorted by
  height, pushed up until each clears the one below, then centred where they wanted to be. Parts
  `<name>.<label>`, `<name>.<label>.leader`.

`idofig add-panel FIG PANEL --template topomap` writes a producer that draws an example scalp
map with an mne montage, its dots and a colorbar.

## Docs for agents and the skill (0.13.0)

What an agent needs to work on figures ships with idofig, so it matches the version a project
runs: `docs/agents.md` (which file holds each adjustment, the rules, the neuroscience helpers, the
loop), `docs/producers.md`, this file, `README.md` and `CHANGELOG.md`. A wheel carries them as
`idofig/docs/<file>`; a checkout or an editable install reads them from the repository.
`idofig docs` prints the version and each one's path (`idofig docs spec` one path, `--json`
both); it imports only the standard library.

`idofig skill install` writes the pointer skill (`src/idofig/skill/SKILL.md`: when to use idofig,
and "run `idofig docs`, read `agents.md` first" — no API) as `idofig/SKILL.md` into each skill
directory: `--dir DIR` (repeatable), else the project's `.claude/skills` with `--project`, else
`~/.claude/skills` and, when it exists, `~/.agents/skills`. The file carries the marker
`<!-- idofig:managed-skill`; idofig rewrites only a file with it (`updated`; the same text is left
`current`). A target that is a link, or whose directory is (a copy another tool owns, which a
write would change through the link), or a file without the marker (one a user wrote) is
refused, every target checked before any is written; `--force` replaces it, a link by unlinking
the link itself, never writing to what it points to. Remove the marker to keep a file of your own.
`idofig skill show` prints the skill.

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

## The server (`idofig serve`)

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
| `update_figure` | `figure, ops` | applies [edit operations](#edit-operations) and recomposes |
| `update_style` | `figure, panel, part, props` | merges `props` into a part's overrides (a `null` value removes one; `props: null` resets the part) |
| `update_panel_style` | `figure, panel, props` | sets style.json's panel-wide keys — `layout` {hspace_mm, wspace_mm, pad_mm} (merged; `null` removes), `trim`, `trim_mm`; answers like `update_style` |
| `move_style` | `figure, panel, from, to` | re-attaches a detached override to a part's new name |
| `restore` | `path, text, expect_sha` | undo: puts a figure.json or style.json back, only if unchanged since; answers the text it replaced (for redo) |
| `new_figure` | `figure, width?, extra?` | creates a figure (`extra`: application keys) |
| `add_panel` | `figure, panel, template?, script?, image?, place?, letter?, mesh?` | adds a drawn panel (and a producer), or an image panel; `mesh` (a project mesh file) writes the `mesh` template's producer with the file in its `inputs` |
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

