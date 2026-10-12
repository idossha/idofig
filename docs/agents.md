# Working on figures with an agent

How an agent works on figures with idofig: which file holds each adjustment, the rules, how to
build a figure that stays editable, the neuroscience helpers, and the loop. The `idofig` skill
points here; `idofig docs` prints where this file and the others are for the installed idofig,
so what an agent reads always matches the idofig a project runs. The contract itself is
`SPEC.md` (file formats, edit ops, properties, checks); recipes are `producers.md`. In a SUNA
project also read SUNA's `FIGURES.md` (the `suna` skill says where).

## The model — one place for every adjustment

| to change | edit | unit | cost |
|---|---|---|---|
| source data, new drawing content, or the producer's default wording | the producer script | — | panel redraw |
| a panel's position / size | `figure.json` `panels[].place` | mm | recompose / redraw on w,h |
| all letters (size, case, weight, wrapper, color, offset) | `figure.json` `letters` | pt / mm | recompose |
| one panel's letter position | `figure.json` `panels[].letter_offset_mm: [dx, dy]` | mm, y down | recompose |
| a part's look (colour, width, font, text, visibility) | `panels/<p>/style.json` | pt … | panel redraw |
| any named semantic part's position | `style.json` `dx_mm`, `dy_mm` (idofig ≥ 0.9; discover running engine support) | mm, y down | panel redraw |
| any named semantic part's size or angle | `style.json` `scale` (positive), `rotate` (clockwise), about its frame centre | factor / degrees | panel redraw |
| native text angle | `style.json` `rotation` (counter-clockwise); distinct from common `rotate` | degrees | panel redraw |
| gaps between axes / empty margin | `style.json` `layout` {hspace_mm, wspace_mm, pad_mm} / `trim`, `trim_mm` | mm | panel redraw |
| tick marks of an axis | `style.json` on the axis part: `tickdir`, `ticklength`, `tickwidth` | pt | panel redraw |
| marks over the figure (arrows, brackets, boxes, text) | `figure.json` `annotations` | mm, anchored to parts/data | recompose |

## Rules

1. **Scripts own what is drawn; files refine it by name.** Never hand-edit `panel.svg`,
   `manifest.json` or `figure.svg` — they are builds. Never move a whole panel to fix where
   its letter sits: use `letter_offset_mm`. Never bake a nudge into a script when a
   `dx_mm`/`dy_mm` override says it by name (a script change is right when the drawing itself
   changes: glyphs, data, layout of the axes, or default wording). A named text's wording
   can also be overridden with `style.json` `text`; use the producer when changing its default.
2. **Edit through the ops when you can** — `python -m idofig rpc update_figure '{…}'` /
   `update_style '{…}'` (params are one JSON object; SPEC "Edit operations") validate,
   re-read and write atomically; a misspelt field is an error, never ignored. Hand edits are
   fine if a build validates them — but a hand-added `letter_offset_mm` or `letters.color`
   needs `"schema": 3` with it (the ops set it), so an older idofig refuses the file
   instead of drawing it wrong.
3. **Nothing derived is stored**: figure numbers never; each panel stores its letter string,
   drawn at compose time from the figure-wide `letters` style plus its own offset.
4. **Read the check's errors and warnings** (`idofig check`): a drawn text below the journal's
   font floor is an error; most other appearance findings are advisory. The current SPEC
   defines the checks. Fix them in the right file; never invent an unstated journal number.
5. **Reproducible:** `python figures/<id>/make.py` equals `idofig build`; same inputs, same
   bytes. Rebuild with `python -m idofig build [<fig>]`, then `idofig status --exit-code`.

## Building a figure that stays editable

One directory per figure; producers draw panels at printed size (`idf.panels`); NAME every
axes (`idf.name`, dotted prefixes for groups: `row1.brain.view0…3`), every series (`label=`),
every free text (`gid=`); `layout="constrained"` when spacing should stay adjustable,
`layout=None` + `idf.axes_mm` when geometry must be exact; geometry in named constants.
Refinement ladder — first rung that works: style.json restyle/nudge → `layout` spacing →
`trim` → axes/group move → figure.json placement → split into panels → (optional, settled
only) bake into the script's constants and delete the entries. Full guide: `producers.md`.

## Neuroscience panels and renders (idofig ≥ 0.13)

Never re-implement these in a project; a project keeps only its colours, condition names, data
loading and layout. Exact behaviour: SPEC "Images and neuroscience panels"; recipes:
`producers.md`. Install `idofig[neuro]` (mne + nibabel) in the project's venv.

| need | call |
|---|---|
| a Blender/PyVista/nilearn render, a micrograph | `idf.image(fig, path, l, b, w, h, name=)` — native pixels, alpha cropped and de-fringed; axes in the file's pixel coords |
| EEG/MEG scalp map, cluster dots, p under it | `neuro.topomap(ax, values, info_or_xy, mask=, vlim=, label=)` |
| cortex (FreeSurfer/GIFTI/PLY), one view filling its box | `neuro.surface(ax3d, surf, values, sulc=, threshold=, background=, outline=, view=)` |
| several views at one scale (L lat, med, ventral …) | `neuro.surface_views(fig, l, b, w, h, {"left":…, "right":…}, values, views=, tags=True)`; `neuro.view_size` for own layouts |
| NIfTI → per-vertex values (replaces nilearn `vol_to_surf`) | `neuro.volume_to_surface((file, k), surf, cortex="lh.mask")` |
| per-parcel values | `neuro.parcel_values(annot, {name: value})` |
| an MRI slice through a target, crosshair, ROI outline | `neuro.volume_slice(ax, T1, axis=, at=, overlay=, roi=, crosshair=neuro.centroid(roi), orientation=, coordinate=, extent=)` |
| a field profile along the crosshair | `neuro.line_profile(volume, through=, axis=)` |
| montage electrodes (± discs, clear labels) | `neuro.electrodes(ax, xy, names, colors=, signs=)` |
| labelled regions with leader lines | `neuro.callouts(fig, neuro.project(ax3d, points), labels)` |

A volume is a path, a nibabel image, or `(file, k)` for a 4-D file. Place 3D axes with
`idf.axes_mm` on a `layout=None` panel (a fitted surface makes its axes the square around the
box); set a surface's starting `view=` in the script and turn it later in style.json.

## Loop

Discover the running engine's properties with `idofig rpc props '{}'`; its role and type
validation determines which edits work. Authors choose the figure's content and presentation;
use the same operations for canvas and AI edits so both rebuild from the same source files.

`idofig parts <fig> <panel>` names what you can address → edit the right file (table) →
`idofig build` → render `figure.svg` (headless Chromium or `rsvg-convert`) and LOOK at it →
`idofig check`. In SUNA, the canvas does the same edits: select the semantic target, move/scale/rotate it,
and use the inspector for its supported appearance properties. Select the parent explicitly
when all its children should move; selected marks and legend children target themselves.
