# Changelog

What changed for people who make figures with idofig, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow `src/idofig/_version.py`.
Releases before 0.7.0 are described in their commit messages (`git log`) and in SPEC.md.

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
