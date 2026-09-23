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
   redrawing.
4. **Same inputs, same bytes.** Any change that makes a rebuild differ from the previous
   build (timestamps, versions, random ids, dict order, font fallback) is a bug.
   `tests/test_build.py::test_rebuild_is_byte_identical` guards it.
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
| `draw.py` | the producer API: `panels`, `panel`, `name`, `colorbar`, `save`, `mm`, `pt`, `axes_mm`, `resolve_context` |
| `naming.py` | the part-naming grammar |
| `styling.py`, `props.py` | style.json application; property registry and validation |
| `mplsetup.py`, `svgpost.py` | deterministic rc, bundled fonts, SVG post-processing |
| `compose.py` | figure.json + panels → figure.svg (letters, image panels, annotations) |
| `images.py` | the natural size of an image panel's file, read from its header (no imaging library) |
| `build.py` | producers, staging, lock, status, check, compliance |
| `spec.py` | figure.json / style.json schemas and edit operations |
| `project.py` | where a project is, where its figures live, and which journal it is written for |
| `journals.py`, `journals/` | journal figure presets (column widths, font floors, line weights, panel-label style); one JSON per bundled journal, copied from SUNA's sourced profiles |
| `serve.py`, `cli.py` | JSON-RPC server for apps; the command line |
| `locate.py`, `scaffold.py` | "where is this part made"; `init`, `new` and `add-panel` |
| `templates/` | the producer scripts `add-panel --template` copies: bar, line, scatter, heatmap, blank |
| `fonts/` | the bundled Liberation Sans faces and their licence (`OFL.txt`) |
| `units.py` | physical units: one SVG user unit is one typographic point |
| `fsutil.py` | small file helpers: atomic writes, canonical JSON, hashing |
| `errors.py` | every error idofig raises on purpose is an `IdofigError` |
| `_colornames.py` | the colour names matplotlib accepts, for validating without importing it (generated; do not edit) |

## Writing producers (for agents working in a project)

See `docs/producers.md`.
