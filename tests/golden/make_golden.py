"""Regenerate the golden panel that tests/test_fine_control.py compares a no-offset build with.

The golden is what idofig drew for conftest's two-panel project (panel a, no style.json)
when the drawing last changed on purpose: a change to the path a panel with no offsets takes
must not change a byte of it. Which source draws it depends on why it is regenerated:

* A release that deliberately draws an unchanged panel differently (and bumps
  ``build.RENDER``): this checkout's source, ``make_golden.py src``. Drawn by the previous
  release, the golden would hold the old bytes and the test could never pass; it now records
  the new drawing, and later changes are compared with it.
* A new matplotlib (the test skips under any other than ``versions.json``'s): the last
  release's source, under that matplotlib, so the working tree is compared with what the
  release draws:

      git archive <last release commit> src | tar -x -C /tmp/prev
      .venv/bin/python tests/golden/make_golden.py /tmp/prev/src

  When that release is older than the commit that last bumped ``build.RENDER`` (0.12.0), that
  commit's source instead (this checkout, until it is committed): the test compares the
  manifest byte for byte too, and an older render wrote other manifests (0.2.2 had no render
  number and wrote ``#000000`` for an edge drawn in no colour), which no working tree matches.

It writes ``panel.svg``, ``manifest.json`` and ``versions.json`` (the idofig that drew them,
and the matplotlib and numpy the bytes depend on) beside itself. The committed files were
drawn by idofig 0.12.0 (render 6: a mesh over ``max_faces`` drawn simplified; this panel has
none, so only its ``render`` changed from 0.11.0's render 5, a 3D axes' role and view, and
0.10.0's render 4, data semantics); its ``panel.svg`` is byte for byte the one
0.2.2 (commit 99a8790) drew but for the ``data-index``/``data-value``/``data-key`` attributes
0.10.0 puts on its three bars, and 0.6.0, 0.7.0 and 0.8.0 changed only the manifest (an axes'
props gained ``dx_mm``/``dy_mm``, then ``scale``/``rotate``; a legend's, ``rotate``).
0.9.0 added common geometry/frame metadata; 0.10.0 adds ``data``, ``series``, ``anchors``,
``categories`` and ``build`` to the manifest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from conftest import make_project  # noqa: E402


def main(src: str) -> None:
    src = str(Path(src).resolve())
    env = {k: v for k, v in os.environ.items() if not k.startswith("IDOFIG_") and k != "MPLBACKEND"}
    env["PYTHONPATH"] = src
    with tempfile.TemporaryDirectory() as tmp:
        root = make_project(Path(tmp) / "proj")
        subprocess.run([sys.executable, "-m", "idofig", "build"], cwd=root, env=env, check=True,
                       stdout=subprocess.DEVNULL)
        panel = root / "figures" / "fig-1" / "panels" / "a"
        for name in ("panel.svg", "manifest.json"):
            shutil.copyfile(panel / name, HERE / name)
    probe = ("import json, idofig, matplotlib, numpy; print(json.dumps({'idofig': idofig.__version__, "
             "'matplotlib': matplotlib.__version__, 'numpy': numpy.__version__}))")
    versions = subprocess.run([sys.executable, "-c", probe], env=env, check=True, capture_output=True, text=True)
    (HERE / "versions.json").write_text(json.dumps(json.loads(versions.stdout), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
