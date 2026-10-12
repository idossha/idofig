# Changelog

What changed for people who make figures with idofig, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow `src/idofig/_version.py`.
Releases before 0.7.0 are described in their commit messages (`git log`) and in SPEC.md.

## [0.13.0] — unreleased

### Added

- **A render made elsewhere is one call: `idf.image(fig, "renders/lh_lateral.png", 2, 10, 30, 24,
  name="brain")`.** It is fitted in the box (mm) with its aspect kept, centred, and embedded with its
  own pixels, never resampled. A render with a transparent background is cropped to what it drew
  and loses the dark fringe Blender, PyVista or nilearn leave around it. The image is the part
  `brain.image`. Its axes keeps the file's pixel coordinates, cropped or not, so a point measured
  on the render is drawn where it was measured. The cropping and the fringe fix are also
  `idofig.rasters.crop_alpha` and `idofig.rasters.bleed`, numpy only.
- **`idofig.neuro`: topomaps, cortical surfaces and MRI slices, each part named.**
  - `neuro.topomap(ax, values, info, mask=cluster)` draws mne's scalp map and names its parts
    `topo.field`, `topo.head`, `topo.nose`, `topo.ear.left`, `topo.ear.right`, `topo.mask`, so a
    style.json override recolours the significance dots or thins the outline. The map is clipped at
    the head outline, the dots are a fixed size in mm, and the colour scale is centred on zero.
    A `label` (a cluster's p) can sit under the head.
  - `neuro.surface(ax, "lh.inflated", t_map, sulc="lh.sulc", threshold=2)` draws a FreeSurfer or
    GIFTI surface as an idofig mesh, orthographic, zoomed to fill the box its axes was placed in.
    Below the threshold it shows the sulci in two greys, or one colour such as a medial wall's;
    `outline=` draws a region's or a cluster's border on it. Pass both hemispheres for a ventral
    or dorsal view. It opens on a named view (`lateral`, `medial`, `ventral` …) that style.json
    can turn.
  - `neuro.surface_views(fig, 0, 0, 120, 30, {"left": "lh.pial", "right": "rh.pial"}, values)`
    lays out several views in a row at one scale, each sized to the brain it shows, with
    `L lat`-style tags if you want them. `neuro.view_size` gives a view's shape for your own
    layouts.
  - `neuro.volume_slice(ax, "T1.nii.gz", axis="z", at=12, overlay="tmap.nii.gz", roi="roi.nii.gz",
    crosshair=target, orientation="all", coordinate=True)` cuts an anatomy, an overlay and an
    ROI outline at a position in mm, with a crosshair through a point, the sides' letters and
    `x = −25, y = −22, z = −14 mm` under it. Volumes on different grids line up without
    resampling, a 4-D file's k-th volume is `(file, k)`, `extent=` crops in mm, and slices are
    neurological by default.
  - `neuro.centroid(roi, side="left")` finds where to cut, `neuro.line_profile(field, through=target,
    axis="x")` samples a volume along the crosshair for a profile plot, and `neuro.parcel_values`
    turns one value per FreeSurfer parcel into one per vertex. `neuro.volume_to_surface(("groupmean.nii.gz",
    1), "lh.central.gii", cortex="lh.mask")` maps a volume onto the cortex along each vertex's
    normal, as nilearn's `vol_to_surf` does, so a producer can go from NIfTI to surface without a
    preprocessing step.
  - `neuro.electrodes(ax, xy, names, colors=..., signs=[1, -1, 1, -1])` draws signed electrode
    discs on a render or a cap map, with labels placed clear of each other and of the discs.
  - `neuro.callouts(fig, neuro.project(ax3d, points), labels)` names points of a brain view
    with leader lines.
  - Install with `pip install "idofig[neuro]"` (or `[eeg]` for mne alone, `[mri]` for nibabel).
    `import idofig` and `import idofig.neuro` import neither.
- `idofig add-panel fig-2 eeg --template topomap` writes a producer with an example scalp map.
- **Agents read the docs of the idofig a project runs.** `idofig docs` prints where this version's
  `agents.md` (how to work on figures: which file holds each adjustment, the rules, the
  neuroscience helpers), `producers.md` and `SPEC.md` are; a wheel now ships them. `idofig skill
  install` puts a short `idofig` skill into `~/.claude/skills` (and `~/.agents/skills`, or a
  project's `.claude/skills` with `--project`) that tells an agent to run `idofig docs`. It never
  writes over a skill another tool or you put there unless you pass `--force`.
- `idf.mesh(..., background=)` colours the faces whose value is NaN, which used to be transparent.
- A producer that imports mne or nibabel records their versions in figure.lock.json beside
  matplotlib's.

### Changed

- Nothing is stale after upgrading: panels that do not use the new helpers are drawn as before.

### Fixed

- `idf.colorbar(ScalarMappable(...), cax=cax)` no longer fails for a mappable drawn on no axes; it
  takes the figure from `cax` as well as from `ax`.

## [0.12.0] — unreleased

### Added

- **A huge mesh no longer makes a slow, heavy panel.** `idf.mesh` draws a file of more than
  100 000 triangles simplified to about that many (`max_faces=`; `max_faces=None` draws every
  one). The surface keeps its shape and its colours: each drawn triangle is one of the file's,
  so a field per vertex or per face and the file's own colours land where they were. The same
  file still builds the same bytes. A 152 000-face surface builds in 1.7 s at the default and
  1.2 s at `max_faces=50_000`, against 2.1 s whole.
- **`idofig mesh-simplify data/cortex.ply data/cortex-50k.ply --faces 50000`** writes the
  smaller mesh as a file, so a project can commit a small surface instead of a huge one. A
  `.ply` keeps the file's colours; `.glb`, `.obj` and `.stl` are written for a file without
  colours. The original is never overwritten.
- The manifest's `mesh` entry says how many triangles and vertices the file has
  (`file_faces`, `file_vertices`) beside the ones drawn (`faces`, `vertices`, unchanged in
  meaning).

### Changed

- Upgrading makes every panel stale once (render 6): a mesh panel drawn by 0.11.0 from a file
  of more than 100 000 triangles is drawn differently now. Other panels are drawn as before.
  idofig now depends on fast-simplification (a small compiled package with wheels for Linux,
  macOS and Windows), which only a simplification imports.

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
