# Working on idofig (humans and agents)

idofig makes publication figures reproducible and editable: producers (matplotlib scripts)
draw panels at their printed size, `figure.json` composes them, and every refinement lives
in a plain file the build applies. Read `README.md` for the idea and `SPEC.md` for the
file formats — SPEC is the contract; change it in the same commit as the code.

## Commands

```sh
uv venv && uv pip install -e ".[test]"
.venv/bin/python -m pytest          # must pass before a commit
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
   journal states no number, idofig states none (D4 in SUNA).

## Where things are

| file | what |
|---|---|
| `draw.py` | the producer API: `panels`, `panel`, `name`, `colorbar`, `save` |
| `naming.py` | the part-naming grammar |
| `styling.py`, `props.py` | style.json application; property registry and validation |
| `mplsetup.py`, `svgpost.py` | deterministic rc, bundled fonts, SVG post-processing |
| `compose.py` | figure.json + panels → figure.svg (letters, image panels, annotations) |
| `build.py` | producers, staging, lock, status, check, compliance |
| `spec.py` | figure.json / style.json schemas and edit operations |
| `serve.py`, `cli.py` | JSON-RPC server for apps; the command line |
| `locate.py`, `scaffold.py` | "where is this part made", templates |

## Writing producers (for agents working in a project)

See `docs/producers.md`.
