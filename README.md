# idofig

**Reproducible, editable publication figures.** Matplotlib scripts draw panels at their
printed size, `figure.json` composes them, and every refinement (labels, colours, layout)
lives in a plain file the build applies, so a rebuild comes out byte for byte the same.

```
figures/fig-dose/
  figure.json        width, producers, panel placement (mm), letters, annotations
  dose.py            a producer: matplotlib code that draws one or more panels
  panels/dose/
    style.json       overrides on named parts
    panel.svg        built: the panel at its printed size
    manifest.json    built: every named part, its box and values
  figure.svg         built: the composed figure
```

## Quick start

```sh
pip install -e /path/to/idofig
idofig init --journal nature
idofig new fig-dose --width double
idofig add-panel fig-dose dose --template bar
idofig build
idofig style fig-dose dose main.xlabel fontsize=8 "text=dose (mg)"
idofig check                  # fresh, reproducible, within the journal's rules
```

```python
import idofig as idf

p = idf.panels("dose")
ax = p["dose"].subplots(); idf.name(ax, "main")
ax.bar(groups, control, label="control")
idf.save(p)                   # names parts, applies style.json, writes SVG + manifest
```

## Docs

* [SPEC.md](SPEC.md): file formats, naming grammar, journal checks, the JSON-RPC server
* [docs/producers.md](docs/producers.md): writing producers that stay editable
* [docs/agents.md](docs/agents.md): for AI agents (`idofig docs`, `idofig skill install`)
* [CHANGELOG.md](CHANGELOG.md): what changed, and what each upgrade makes stale

## Credits

idofig builds on ideas from [fluxplot](https://github.com/fluxsci/fluxplot) by fluxsci.

## License

See [LICENSE](LICENSE).
