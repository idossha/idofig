# Changelog

What changed for people who make figures with idofig, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow `src/idofig/_version.py`.
Releases before 0.7.0 are described in their commit messages (`git log`) and in SPEC.md.

## [0.11.0] — unreleased

### Added

- **A 3D mesh is a panel you can turn without touching the script.** `idf.mesh(ax,
  "data/cortex.ply", scalars=field, cmap="inferno")` draws a `.glb`, `.gltf`, `.stl`, `.ply` or
  `.obj` on a 3D axes — coloured by a field per vertex or per face, by one colour, or by the
  file's own colours — lit from the viewer and smoothly over its shared vertices (`smooth=False`
  for flat facets), framed to its bounds on one scale, and rasterized
  at print resolution past 20 000 faces, keeping its name (`main.mesh.cortex`). The view is
  five style.json properties on the 3D axes — `elev`, `azim`, `roll`, `zoom`, `proj` — so an
  editor or `idofig style fig-3 brain main elev=10 azim=-90` turns it and a rebuild redraws it
  lit from the new side. **`idofig add-panel FIG PANEL --mesh data/head.glb`** (or the server's
  `add_panel` with `mesh`) writes the producer and lists the mesh in its inputs, so editing the
  mesh file makes the panel stale. The manifest says which file a mesh part drew, with its face
  and vertex counts and bounds. idofig now depends on trimesh, which only `idf.mesh` imports. A
  150 000-face surface builds in about 3 s under matplotlib 3.8 to 3.11 (matplotlib before 3.11
  alone took 12–20 s: idofig projects the triangles itself, drawing what matplotlib draws).

### Changed

- Upgrading makes every panel stale once (render 5). A 3D axes' part has the role `axes3d`
  and its manifest props carry its view; an axes named by a `gid` has its role (`axes`,
  `axes3d`, `colorbar`) rather than `author`, so a view set on a 2D axes or a colorbar is
  refused ("only a 3D axes has a view") and reported. Nothing is drawn differently and no name
  changes.

### Fixed

- `import idofig.compose` (and so the server and the command line) no longer imports
  matplotlib.

## [0.10.0] — unreleased

### Added

- **A panel's manifest says what its data marks drew, so slides can build a plot as a plot.**
  A line's, a scatter's and a bar series' parts carry `data` — x and y, a scatter's colour
  values, a bar's position, value, baseline and category — up to 1000 values a series; a
  larger series says the values were left out and gives their range instead. Each axes gives
  two data-to-point `anchors` per linear or log axis (and its `categories`), enough to place
  any value on the panel without matplotlib. Each legend entry names the `series` it stands
  for, joined by the artist it was made from, not by its text. A `build` list gives a default
  reveal order — axes, then grid, then each series in the order matplotlib draws it, then
  legends and colorbars, then free text — with an entrance for each step (`draw-on`, `grow`,
  `stagger`, `fade`). Read it in any `manifest.json`, or through the server's `workspace` and
  `parts`; nothing in `figure.json` or `style.json` changes.
- **Bars and points are addressable one by one in panel.svg.** Each bar carries `data-index`,
  `data-value` and, on a categorical axis, `data-key`; each mark of a scatter or a marker line
  gets its own id (`main.series.cells.3`) with `data-index` when every point is drawn — when
  matplotlib skips one (a value ≤ 0 on a log axis) or a series has more than 1000, the series
  stays one group and the manifest says why. These ids are positional: a point inserted
  before another renumbers it; a bar's `data-key` does not.
- **Gridlines have names** (`main.xgrid.0-5`, all of them `main.xgrid.*`), so a grid can be
  restyled, or revealed after its axes. An unlabelled bar container is now the group
  `main.bars0` over its bars.

### Changed

- Upgrading makes every panel stale once (render 4). A panel with bars, points or a grid gains
  the attributes and ids above; nothing is drawn differently, no existing part is renamed, and
  a panel with none of them keeps its bytes. A broad pattern such as `main.*` in style.json now
  also reaches the gridlines, and `check` holds a drawn grid to the journal's line weight (one
  finding for `main.xgrid.*`).

## [0.9.0] — unreleased

### Added

- Every named artist accepts physical position, clockwise rotation and positive uniform scale,
  including data marks, images, ticks and legend entries. Nested SVG transforms and clipping
  follow the selected artist, with accurate composed manifest boxes for canvas handles.
- Common geometry metadata includes the untransformed frame, own/composed matrices and actual
  printed scale. Render 3 refreshes old manifests. Named images gain a stable outer group containing
  their native flip and clipping; unedited vector drawing remains unchanged.

### Fixed

- **Two writers no longer lose an edit.** An app's `serve`, a one-shot `idofig rpc` and
  `idofig style` each read, merged and wrote `style.json` / `figure.json` with nothing between
  them, so two at once could drop one's entry. Edits now take `.idofig/edit.lock` (separate
  from `build.lock`, so an edit never waits on a build); undo's pre-image and `restore`'s check
  are read under it too.

### Changed

- Geometry no longer imposes arbitrary offset, rotation or scale ranges. Values must be finite
  and scale strictly positive; transforms that overflow SVG coordinates fail the build.

## [0.8.0] — unreleased

### Added

- **A legend can be rotated on its own.** `rotate` (degrees, −180 to 180, clockwise) on a
  legend part turns it — frame, keys, entries and title — about its centre, after its
  `dx_mm`/`dy_mm`: `idofig style FIG PANEL main.legend rotate=90`, or `update_style` on the
  server. Inside a turned axes it turns with the axes too. The script is not touched; nothing
  reflows. A panel without the entry, or with `rotate` 0, is written byte for byte as before; a
  manifest written by 0.8.0 gains `rotate` in each legend's `props`. No panel goes stale on
  upgrading.

## [0.7.0] — unreleased

### Added

- **An axes, or a group of axes, can be scaled and rotated with everything drawn in it.**
  `scale` (0.25–4) and `rotate` (degrees, −180 to 180, clockwise) on an axes part, or on a
  pattern naming several (`row1.*`), turn and size it about its box's centre, after the layout
  and after `dx_mm`/`dy_mm`; its ticks, labels, title, legend, images and marks come along.
  Set them with `idofig style FIG PANEL main scale=0.9 rotate=10`, or `update_style` on the
  server; a value out of range is refused with the range it must be in. The script is not
  touched and the panel is not redrawn at another size. The manifest boxes each part where it
  now is, gives the axes' untransformed `frame` and its `matrix` for a canvas to draw handles
  on, and `check` holds text and strokes to the size they print at (a 7 pt label at scale 0.8
  is checked, and reported, as 5.6 pt). A panel without these entries — or with `scale` 1 and
  `rotate` 0 — is written byte for byte as before; a manifest written by 0.7.0 gains the two
  values in each axes' `props`. No panel goes stale on upgrading.
