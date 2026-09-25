# Changelog

What changed for people who make figures with idofig, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow `src/idofig/_version.py`.
Releases before 0.7.0 are described in their commit messages (`git log`) and in SPEC.md.

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
