---
name: idofig
description: >-
  Make, fix or refine a publication figure the idofig way — a figure is one
  directory (figures/<id>/): matplotlib producer scripts draw panels at their
  printed size, figure.json places panels and letters, style.json refines named
  parts; idofig.neuro draws topomaps, cortical surfaces, MRI slices, electrodes
  and renders. Use whenever the user asks to create a figure, fix a figure's
  layout, move a panel letter, nudge a label or legend, restyle part of a plot,
  draw a brain, scalp or slice panel, check a figure against a journal, or works
  in a folder with figures/*/figure.json or suna.json — including inside a SUNA
  project.
---

<!-- idofig:managed-skill — written by `idofig skill install`; replace this file with your own to opt out of updates -->

# idofig — the knowledge ships with idofig, not in this skill

Everything an agent needs is in the docs of the idofig the project runs, so it always
matches that version. This skill only says where they are.

1. Find the idofig the project uses: its venv's `idofig` (`.venv/bin/idofig`), else the
   one on PATH, else `python -m idofig`.
2. Run `idofig docs`: it prints that version and where its docs are. Read **`agents.md`**
   first (which file holds each adjustment, the rules, the neuroscience helpers, the loop),
   then `producers.md` for writing producers and `SPEC.md` for the exact contract.
3. In a SUNA project also read SUNA's `FIGURES.md` (the `suna` skill says where).
4. Work through the loop in `agents.md`: `idofig parts` → edit the right file →
   `idofig build` → look at `figure.svg` → `idofig check`.

Keep this skill thin: a capability belongs in idofig's docs, shipped with the code.
