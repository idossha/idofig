# Working on idofig (humans and agents)

idofig makes publication figures reproducible and editable: producers (matplotlib scripts)
draw panels at their printed size, `figure.json` composes them, and every refinement lives
in a plain file the build applies. Read `README.md` for the idea and `SPEC.md` for the
file formats — SPEC is the contract; change it in the same commit as the code.

## Commands

```sh
uv venv && uv pip install -e ".[test]"   # the test extra brings pytest and ruff
.venv/bin/python -m pytest               # must pass before a commit
.venv/bin/ruff check src tests --select F,E9
```

## Rules

1. **Nothing is lost silently.** A style override or annotation that stops resolving is
   *detached* and reported, never applied elsewhere, never deleted.
2. **Names come from meaning.** Never make a derived name depend on drawing order when a
   role, a label or a text is available. Anything positional is marked `positional`.
3. **Panels are never scaled.** A panel is drawn at its printed size; resizing means
   redrawing. Any named artist inside it may move, scale or turn through the common
   style.json geometry contract (0.9.0; SPEC.md); clipping and measured boxes follow its
   SVG transform so previews and checks describe what actually prints.
4. **Same inputs, same bytes.** Any change that makes a rebuild differ from the previous
   build (timestamps, versions, random ids, dict order, font fallback) is a bug.
   `tests/test_build.py::test_rebuild_is_byte_identical` guards it. `tests/golden/` holds
   the bytes of a panel with no offsets as the last drawing change left them, and
   `tests/golden/make_golden.py` regenerates it — from which source depends on why:
   * a release that deliberately draws an unchanged panel differently bumps `build.RENDER`
     (so such panels go stale) and regenerates the golden from **this checkout**: the
     golden then records the new drawing, and the next change is compared with it;
   * a new matplotlib (the golden test skips under any version but the one in
     `versions.json`) regenerates it from **the last release's** source under that
     matplotlib, so the working tree is still compared with what the release draws; from
     the commit that last bumped `build.RENDER` when that release is older (the test
     compares manifest.json byte for byte too, and an older render wrote other manifests).

   Under any matplotlib, `test_what_a_save_wraps_around_the_drawing_adds_no_byte` checks
   that the draws a save wraps (tracking what was drawn, naming rasterized parts) add no
   byte: it compares two idofig saves, so a change to what both share (`draw.SAVE_RC`,
   `svgpost.finish_panel_svg`) only the golden catches.
5. **One implementation.** The CLI, the server and the Python API call the same functions;
   applications embedding idofig never re-implement composing, naming or staleness.
6. **Read fresh, validate, write atomically.** Every edit of figure.json/style.json re-reads
   the file, applies the change, validates, and replaces the file atomically.
7. **Composing never imports matplotlib.** `compose`, `build`, `serve` and `cli` stay on the
   standard library so they start in milliseconds.
8. **Journal numbers come with a source.** Presets are copied from sourced profiles; where a
   journal states no number, idofig states none (SUNA's D4, "no invented threshold").

## Where things are

All under `src/idofig/`.

| file | what |
|---|---|
| `__init__.py` | the package; the producer API is imported lazily from `draw.py`, so `import idofig` is cheap |
| `meshes.py` | `idofig.mesh` (0.11.0): reads a mesh file with trimesh (imported there only), simplifies one over `max_faces` with fast-simplification (0.12.0; also `idofig mesh-simplify`), draws it on a 3D axes as a `MeshCollection`: smoothed normals, a headlight recomputed from the view at every draw, and its own vectorized projection (matplotlib's, for all triangles at once; equal-depth faces in the file's order); named `<axes>.mesh.<name>` |
| `rasters.py` | `idofig.image` (0.13.0): places a render at its own resolution in a mm box, aspect kept; `crop_alpha` and `bleed` (numpy only) remove a transparent background's margin and dark fringe |
| `neuro/` | `idofig.neuro` (0.13.0), behind extras: `eeg.py` `topomap` (mne, `[eeg]`), `mri.py` surfaces (`surface`, `surface_views`, `view_size`, `fit`: a 3D axes made the square around its box, zoomed to fill it; sulcal background, outlines), volumes (`volume_slice` with crosshair/letters/coordinate, `centroid`, `line_profile`, `volume_to_surface`) and `parcel_values` (nibabel, `[mri]`); `annotate.py` `electrodes` (`place_labels`), `project`, `callouts` (no extra); module names differ from function names so an import never shadows a function. Each names what it draws through `naming.mark_part` |
| `draw.py` | the producer API: `panels`, `panel`, `name`, `colorbar`, `save`, `mm`, `pt`, `axes_mm`, `resolve_context`; `panels` selects the Agg backend unless it runs in a session, `save` draws on an Agg canvas of its own, lays a panel out, moves offset parts, keeps named rasterized parts' names, measures only what was drawn (with the SVG's text metrics, not Agg's), then puts back what it changed to write the panel (canvas, dpi, size, layout, placements, moves, wrapped draws); style overrides stay set on the script's figure |
| `naming.py` | the part-naming grammar; legend entries joined to their series by artist |
| `marks.py` | what data marks drew (`data`), axes `anchors`/`categories`, mark ids and data attributes in panel.svg, the `build` hint (0.10.0) |
| `styling.py`, `props.py` | style application and one capability registry: pre-layout styling, legacy post-layout offsets, common `axes_transforms`/`artist_transforms` matrices; `svgpost.transform_groups` applies them and `draw._measure` follows actual SVG ancestry. Validates finite geometry and unsupported setters; `css_color` normalizes colours |
| `mplsetup.py`, `svgpost.py` | deterministic rc, bundled fonts, SVG post-processing |
| `compose.py` | figure.json + panels → figure.svg (letters, image panels, annotations) |
| `images.py` | the natural size of an image panel's file, read from its header (no imaging library) |
| `build.py` | producers, staging, lock, status, check, compliance |
| `spec.py` | figure.json (schema 2, or 3 when it uses a 0.3 key) / style.json schemas and edit operations |
| `project.py` | where a project is, where its figures live, and which journal it is written for |
| `journals.py`, `journals/` | journal figure presets (column widths, font floors, line weights, panel-label style); one JSON per bundled journal, copied from SUNA's sourced profiles |
| `serve.py`, `cli.py` | JSON-RPC server for apps; the command line |
| `locate.py`, `scaffold.py` | "where is this part made"; `init`, `new` and `add-panel` |
| `templates/` | the producer scripts `add-panel --template` copies: bar, line, scatter, heatmap, blank, mesh (`--mesh`), topomap |
| `fonts/` | the bundled Liberation Sans faces and their licence (`OFL.txt`) |
| `guide.py`, `skill/SKILL.md` | `idofig docs` (where this version's agent docs are: shipped in the wheel by pyproject's `force-include`, else the checkout) and `idofig skill install` (the pointer skill; refuses links and unmarked files) |
| `units.py` | physical units: one SVG user unit is one typographic point |
| `fsutil.py` | small file helpers: atomic writes, canonical JSON (strict: no NaN or Infinity either way; a file that is not JSON is an error naming it), hashing |
| `errors.py` | every error idofig raises on purpose is an `IdofigError` |
| `_colornames.py` | the colour names matplotlib accepts, for validating without importing it (generated; do not edit) |

## Docs for agents

`docs/agents.md` is what the `idofig` skill sends an agent to (through `idofig docs`): keep it
in step with the code in the same commit, as SPEC is. A new capability an agent should reach for
gets a row there; the skill (`src/idofig/skill/SKILL.md`) stays a pointer with no API in it.

## Writing producers (for agents working in a project)

See `docs/producers.md`. A 3D mesh is input data, like a `.npy`: list the file in the
producer's `inputs`, draw it on a 3D axes with `idf.mesh(ax, "data/head.glb")` (part
`main.mesh.head`; `scalars=`/`cmap=`/`color=` colour it, otherwise its own vertex colours; it is
lit smoothly over shared vertices, `smooth=False` for flat facets), and
never set the view in the script — `elev`, `azim`, `roll`, `zoom` and `proj` on the 3D axes in
style.json are where an editor or an agent turns it. Keep meshes small: past `max_faces=100_000`
triangles one is drawn simplified, but a huge file is still read and simplified at every build
and weighs on the repository — commit a small surface instead
(`idofig mesh-simplify data/head.ply data/head-50k.ply --faces 50000`).

A render made elsewhere is placed with `idf.image(fig, path, left, bottom, width, height,
name=...)`, never resampled in the script. EEG topomaps, cortical surfaces and MRI slices are
drawn with `idofig.neuro` (`topomap`, `surface`, `volume_slice`) rather than re-implemented in a
project; the project keeps its colours, labels and data loading. A surface's `view=` is only
where it starts — turn it in style.json.
