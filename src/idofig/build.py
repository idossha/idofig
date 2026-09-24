"""Run producers, publish their panels, compose figures, and know what is stale.

The lock (``figures/<id>/figure.lock.json``) records what each panel was built from:
the producer's command, the sha256 of every file it declared or imported from the
project, the journal preset, the panel's size and its style.json. ``status`` compares
that record with the files as they are now, so it can say *why* a panel is stale.

Producers run from the project root with::

    IDOFIG_ROOT        the project root
    IDOFIG_FIGURE      the figure id
    IDOFIG_OUTPUT_DIR  a private staging directory; nothing is published until the run succeeds
    IDOFIG_ONLY        the panels wanted, when only some are stale

A failed run leaves every published file exactly as it was.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Callable

from . import journals as J
from . import spec as S
from ._version import __version__
from .compose import compose
from .errors import IdofigError
from .fsutil import dump_json, read_json, rel, sha256_file, sha256_json, write_atomic, write_json
from .project import Project
from .units import PT_PER_MM

Event = Callable[[dict], None]
LOCK_SCHEMA = 1
# How idofig draws a panel, as a number: bump it in a release that changes the bytes of a panel
# whose producer, inputs, size and style did not (2, 0.3.0: named rasterized parts grouped, a 3D
# z axis named, gid'd backgrounds marked with their role, no box for what is never drawn, boxes
# for collections, text boxes in the SVG's metrics, tick values). Without it 0.2.2's panels read
# fresh while `check` failed them. The lock records per panel `render`, from the manifest of the idofig that drew it (a producer's
# `run` may name an interpreter with its own), and `builder_render`, the builder's. Drawn under
# another number, a panel is stale only while its builder's differs too; otherwise the producer's
# own idofig drew it, and a rebuild changes nothing (stale, it was rebuilt forever): a warning.
RENDER = 2


def drawn_under(manifest: dict) -> int:
    """The render number of the idofig that wrote ``manifest`` (1: idofig 0.2.x), or that
    drew a lock's panel entry."""
    render = manifest.get("render", 1)
    return render if isinstance(render, int) and not isinstance(render, bool) else 1


def _drawn_by(entry: dict) -> str:
    """The idofig that drew a lock's panel entry, as a reason names it (an entry with no version
    was written by 0.2.x, or its producer's idofig recorded none)."""
    if entry.get("idofig"):
        return f"idofig {entry['idofig']}"
    drawn = drawn_under(entry)
    return "idofig 0.2.x" if drawn == 1 else f"{'an older' if drawn < RENDER else 'a newer'} idofig"


# ----------------------------------------------------------------------------- lock


def lock_path(project: Project, fid: str) -> Path:
    return project.figure_dir(fid) / "figure.lock.json"


def read_lock(project: Project, fid: str) -> dict:
    p = lock_path(project, fid)
    try:
        doc = read_json(p)
        if isinstance(doc, dict) and doc.get("schema") == LOCK_SCHEMA:
            doc.setdefault("producers", {})
            doc.setdefault("panels", {})
            return doc
    except (FileNotFoundError, ValueError):
        pass
    return {"schema": LOCK_SCHEMA, "figure": fid, "producers": {}, "panels": {}}


def write_lock(project: Project, fid: str, lock: dict) -> None:
    lock["producers"] = dict(sorted(lock["producers"].items()))
    lock["panels"] = dict(sorted(lock["panels"].items()))
    path = lock_path(project, fid)
    text = dump_json(lock)
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except FileNotFoundError:
        pass
    write_atomic(path, text)


@contextlib.contextmanager
def project_lock(project: Project):
    """One builder per project at a time (the app's server and a terminal may both build)."""
    path = project.state_dir / "build.lock"
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ----------------------------------------------------------------------------- fingerprints


def _producer_files(project: Project, producer: dict, discovered: list[str]) -> dict[str, str | None]:
    root = project.root
    files: set[str] = set()
    missing: set[str] = set()
    for arg in producer.get("run", [])[1:]:
        p = (root / arg)
        if p.suffix and p.is_file():
            try:
                files.add(rel(p.resolve(), root))
            except ValueError:
                pass
    for pattern in producer.get("inputs", []):
        hits = [p for p in root.glob(pattern) if p.is_file()]
        if not hits:
            missing.add(pattern)
        for p in hits:
            files.add(rel(p, root))
    for d in discovered:
        files.add(d)
    out: dict[str, str | None] = {f: sha256_file(root / f) for f in sorted(files)}
    for m in sorted(missing):
        out[m] = None
    return out


def _journal_sha(project: Project, doc: dict) -> str:
    return sha256_json(J.load(doc.get("journal") or project.journal, str(project.root)))


def _shared(producer: dict, files: dict, journal_sha: str) -> str:
    return sha256_json({"run": producer.get("run"), "files": files, "journal": journal_sha})


def _panel_own(project: Project, fid: str, doc: dict, pid: str) -> dict:
    entry = S.panel_entry(doc, pid) or {}
    place = entry.get("place", {})
    return {
        "size": [round(float(place.get("w", 0)), 3), round(float(place.get("h", 0)), 3)],
        "style": sha256_file(project.panel_dir(fid, pid) / "style.json"),
    }


# ----------------------------------------------------------------------------- status


@dataclass
class PanelStatus:
    id: str
    state: str  # fresh | stale | missing | image | orphan | failed
    producer: str | None = None
    cost: str | None = None  # the producer's: cheap (apps may rebuild it automatically) or expensive
    reasons: list[str] = field(default_factory=list)
    detached_styles: list[str] = field(default_factory=list)
    invalid_styles: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], {})} | {"id": self.id, "state": self.state}


@dataclass
class FigureStatus:
    id: str
    panels: list[PanelStatus] = field(default_factory=list)
    figure_svg: str = "fresh"  # fresh | stale | missing
    detached_annotations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def stale(self) -> bool:
        return self.figure_svg != "fresh" or any(p.state in {"stale", "missing", "failed"} for p in self.panels)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "stale": self.stale,
            "figure_svg": self.figure_svg,
            "panels": [p.to_json() for p in self.panels],
            "detached_annotations": self.detached_annotations,
            "warnings": self.warnings,
            **({"error": self.error} if self.error else {}),
        }


def _failures(project: Project) -> dict:
    try:
        return read_json(project.state_dir / "state.json")
    except (FileNotFoundError, ValueError):
        return {}


def _record_failure(project: Project, fid: str, prid: str, message: str | None,
                    fingerprint: str | None = None) -> None:
    state = _failures(project)
    fig = state.setdefault(fid, {})
    if message is None:
        if prid not in fig:
            if not fig:
                state.pop(fid, None)
            return
        fig.pop(prid, None)
        if not fig:
            state.pop(fid, None)
    else:
        fig[prid] = {"error": message[-4000:], "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "fingerprint": fingerprint}
    write_json(project.state_dir / "state.json", state)


def _fingerprint(shared: str, own: dict[str, dict]) -> str:
    """Everything a producer's run depended on: a failure is only final for these inputs."""
    return sha256_json({"shared": shared, "own": own})


def _describe(before: dict, now: dict) -> list[str]:
    reasons = []
    for f in sorted(set(before) | set(now)):
        a, b = before.get(f), now.get(f)
        if a == b:
            continue
        if f not in before:
            reasons.append(f"new input {f}")
        elif f not in now:
            reasons.append(f"{f} is no longer an input")
        elif b is None:
            reasons.append(f"{f} is missing")
        else:
            reasons.append(f"{f} changed")
    return reasons


def figure_status(project: Project, fid: str) -> FigureStatus:
    st = FigureStatus(id=fid)
    try:
        doc = S.load_figure(project.figure_json(fid))
    except IdofigError as exc:
        st.error = str(exc)
        st.figure_svg = "stale"
        return st
    lock = read_lock(project, fid)
    failures = _failures(project).get(fid, {})
    journal_sha = _journal_sha(project, doc)
    current_files: dict[str, dict] = {}
    for pr in doc.get("producers", []):
        discovered = lock["producers"].get(pr["id"], {}).get("discovered", [])
        current_files[pr["id"]] = _producer_files(project, pr, discovered)

    for pn in doc.get("panels", []):
        pid = pn["id"]
        if "image" in pn:
            ok = (project.root / pn["image"]).is_file()
            st.panels.append(PanelStatus(pid, "image" if ok else "missing",
                                         reasons=[] if ok else [f"{pn['image']} not found"]))
            continue
        pr = S.producer_of(doc, pid)
        ps = PanelStatus(pid, "fresh", producer=pr["id"] if pr else None,
                         cost=pr.get("cost", "cheap") if pr else None)
        render_note = None
        pdir = project.panel_dir(fid, pid)
        svg_sha = sha256_file(pdir / "panel.svg")
        entry = lock["panels"].get(pid)
        if pr is None:
            ps.state = "orphan" if svg_sha else "missing"
            ps.reasons.append("no producer draws this panel")
        elif pr["id"] in failures:
            failure = failures[pr["id"]]
            ps.error = failure["error"]
            now = _fingerprint(_shared(pr, current_files[pr["id"]], journal_sha),
                               {q: _panel_own(project, fid, doc, q) for q in pr["panels"]})
            if failure.get("fingerprint") in (None, now):
                ps.state = "failed"
        if pr is not None and ps.state == "fresh":
            if svg_sha is None:
                ps.state = "missing"
                ps.reasons.append("not built yet")
            elif entry is None:
                ps.state = "stale"
                ps.reasons.append("never built by idofig")
            else:
                files = current_files[pr["id"]]
                if _shared(pr, files, journal_sha) != entry.get("shared"):
                    ps.state = "stale"
                    before = lock["producers"].get(pr["id"], {}).get("files", {})
                    why = _describe(before, files)
                    if lock["producers"].get(pr["id"], {}).get("run") != pr.get("run"):
                        why.insert(0, "the producer's command changed")
                    if lock["producers"].get(pr["id"], {}).get("journal") != journal_sha:
                        why.insert(0, "the journal preset changed")
                    ps.reasons.extend(why or ["built from older inputs than the rest of its producer"])
                own = _panel_own(project, fid, doc, pid)
                if own["size"] != entry.get("size"):
                    ps.state = "stale"
                    ps.reasons.append(f"resized to {own['size'][0]:g}×{own['size'][1]:g} mm")
                if own["style"] != entry.get("style"):
                    ps.state = "stale"
                    ps.reasons.append("style.json changed")
                if svg_sha != entry.get("svg"):
                    ps.state = "stale"
                    ps.reasons.append("panel.svg was changed outside idofig")
                drawn = drawn_under(entry)  # a lock without one was written by 0.2.x
                if drawn != RENDER:
                    who = _drawn_by(entry)
                    if entry.get("builder_render", drawn) != RENDER:  # see RENDER
                        ps.state = "stale"
                        ps.reasons.append(f"drawn by {who}; idofig {__version__} may draw it differently")
                    else:
                        # After that idofig is upgraded the panel still reads fresh (the lock
                        # cannot see it), so the step names the forced build that redraws it. 0.2.x
                        # (render 1) reads figure.json in the producer too (`idofig.panels()`) and
                        # refuses a 3: once a letter was moved, every rebuild failed with a bare
                        # "schema must be 2" that named no cause.
                        what = ("cannot read this figure.json (schema 3: a letter offset or colour), so its "
                                "next build fails" if drawn == 1 and doc["schema"] == 3
                                else f"draws panels differently from idofig {__version__}")
                        render_note = (f"drawn by {who}, the one its producer's run uses, which {what}: "
                                       + (f"upgrade idofig where the producer runs, then `idofig build --force {fid}`"
                                          if drawn < RENDER else "upgrade the idofig that builds"))
            if ps.error is not None:
                if ps.state == "fresh":
                    ps.error = None  # the inputs went back to what the published panel was built from
                else:
                    ps.reasons.append("changed since the last failed build")
        try:
            man = read_json(pdir / "manifest.json")
            ps.detached_styles = list(man.get("style", {}).get("detached", []))
            ps.invalid_styles = list(man.get("style", {}).get("invalid", []))
            ps.warnings = list(man.get("warnings", []))
        except (FileNotFoundError, ValueError):
            pass
        if render_note:
            ps.warnings.append(render_note)
        st.panels.append(ps)

    try:
        result = compose(project, fid, write=False)
        st.detached_annotations = result.detached
        st.warnings.extend(result.warnings)
        try:
            on_disk = (project.figure_dir(fid) / "figure.svg").read_text(encoding="utf-8")
            st.figure_svg = "fresh" if on_disk == result.svg else "stale"
        except FileNotFoundError:
            st.figure_svg = "missing"
    except IdofigError as exc:
        st.error = str(exc)
        st.figure_svg = "stale"
    return st


def status(project: Project, figure_ids: list[str] | None = None) -> list[FigureStatus]:
    return [figure_status(project, fid) for fid in (figure_ids or project.figure_ids())]


# ----------------------------------------------------------------------------- running producers


def _argv(producer: dict) -> list[str]:
    argv = list(producer["run"])
    if argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    return argv


@dataclass
class RunResult:
    producer: str
    panels: list[str]
    ok: bool
    seconds: float
    output: str = ""
    error: str | None = None


def run_producer(project: Project, fid: str, doc: dict, producer: dict, panels: list[str], *,
                 staging: Path, on_event: Event | None = None, timeout: float | None = None,
                 cancelled: Callable[[], bool] | None = None) -> RunResult:
    staging.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "IDOFIG_ROOT": str(project.root),
        "IDOFIG_FIGURE": fid,
        "IDOFIG_OUTPUT_DIR": str(staging),
        "MPLBACKEND": "Agg",
        "PYTHONHASHSEED": "0",
        "PYTHONUNBUFFERED": "1",
    })
    if set(panels) != set(producer["panels"]):
        env["IDOFIG_ONLY"] = ",".join(panels)
    else:
        env.pop("IDOFIG_ONLY", None)
    if doc.get("journal"):
        env["IDOFIG_JOURNAL"] = doc["journal"]
    argv = _argv(producer)
    t0 = time.perf_counter()
    lines: list[str] = []
    emit = on_event or (lambda e: None)
    emit({"event": "producer.start", "figure": fid, "producer": producer["id"], "panels": panels, "argv": argv})
    try:
        proc = subprocess.Popen(argv, cwd=project.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
    except OSError as exc:
        return RunResult(producer["id"], panels, False, 0.0, error=f"cannot start {argv[0]!r}: {exc}")
    limit = timeout or producer.get("timeout_s")
    assert proc.stdout is not None
    queue: Queue[str | None] = Queue()

    def pump() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            queue.put(raw.rstrip("\n"))
        queue.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    def drain(block: bool) -> bool:
        """Forward output lines; True once the stream has ended."""
        while True:
            try:
                line = queue.get(timeout=0.05) if block else queue.get_nowait()
            except Empty:
                return False
            if line is None:
                return True
            lines.append(line)
            emit({"event": "producer.output", "figure": fid, "producer": producer["id"], "line": line})
            block = False

    ended = False
    while not ended:
        ended = drain(block=True)
        if cancelled and cancelled():
            proc.kill()
            proc.wait()
            return RunResult(producer["id"], panels, False, time.perf_counter() - t0, "\n".join(lines),
                             error="cancelled")
        if limit and time.perf_counter() - t0 > limit:
            proc.kill()
            proc.wait()
            return RunResult(producer["id"], panels, False, time.perf_counter() - t0, "\n".join(lines),
                             error=f"timed out after {limit:g} s")
    proc.wait()
    reader.join(timeout=1)
    output = "\n".join(lines)
    seconds = time.perf_counter() - t0
    if proc.returncode != 0:
        tail = "\n".join(lines[-40:])
        return RunResult(producer["id"], panels, False, seconds, output,
                         error=f"exited with code {proc.returncode}\n{tail}")
    for pid in panels:
        svg = staging / pid / "panel.svg"
        if not svg.is_file() or not (staging / pid / "manifest.json").is_file():
            return RunResult(producer["id"], panels, False, seconds, output,
                             error=f"did not write panel {pid!r} (does it call idofig.save() for every panel it declares?)")
        try:
            ET.fromstring(svg.read_bytes())
        except ET.ParseError as exc:
            return RunResult(producer["id"], panels, False, seconds, output,
                             error=f"panel {pid!r}: the SVG is not well-formed ({exc})")
    return RunResult(producer["id"], panels, True, seconds, output)


def _versions_from(staging: Path) -> tuple[list[str], dict]:
    try:
        run = read_json(staging / "_run.json")
        return list(run.get("discovered", [])), dict(run.get("versions", {}))
    except (FileNotFoundError, ValueError):
        return [], {}


def _record_build(project: Project, fid: str, doc: dict, producer: dict, panels: list[str], discovered: list[str],
                  versions: dict, lock: dict, *, before: dict | None = None) -> None:
    """Record what ``panels`` were built from.

    ``before`` holds the fingerprints taken *before* the producer ran (``files``, ``own``,
    ``journal``). An input edited while the producer was running must leave the panel stale,
    so the lock records what the run saw, never what is on disk after it.
    """
    journal_sha = before["journal"] if before else _journal_sha(project, doc)
    files = _producer_files(project, producer, discovered)
    if before:
        files = {f: before["files"].get(f, h) if f in before["files"] else h for f, h in files.items()}
    lock["producers"][producer["id"]] = {
        "run": producer["run"],
        "files": files,
        "journal": journal_sha,
        "discovered": discovered,
        "built_with": versions,
    }
    shared = _shared(producer, files, journal_sha)
    for pid in panels:
        pdir = project.panel_dir(fid, pid)
        own = before["own"][pid] if before else _panel_own(project, fid, doc, pid)
        try:  # just written, by the producer's own idofig maybe: 0.2.2 wrote a NaN into some
            drawn = drawn_under(read_json(pdir / "manifest.json"))
        except ValueError:
            drawn = 1
        lock["panels"][pid] = {
            "producer": producer["id"],
            "shared": shared,
            "size": own["size"],
            "style": own["style"],
            "svg": sha256_file(pdir / "panel.svg"),
            "manifest": sha256_file(pdir / "manifest.json"),
            # What drew it and what built it (see RENDER): recorded as the builder's, the 0.2.2
            # panels of a producer whose run names a venv with idofig 0.2.2 showed fresh. Per panel,
            # as `render` is: read from the producer's `built_with`, which a build of some of its
            # panels (`only`) rewrites, the others' reason named the new idofig as what drew them.
            "render": drawn,
            "builder_render": RENDER,
            "idofig": versions.get("idofig"),
        }
    known = {p["id"] for p in doc.get("panels", [])}
    for pid in list(lock["panels"]):
        if pid not in known:
            del lock["panels"][pid]
    for prid in list(lock["producers"]):
        if prid not in {p["id"] for p in doc.get("producers", [])}:
            del lock["producers"][prid]


def current_versions() -> dict:
    import importlib.metadata as md

    out = {"python": platform.python_version(), "idofig": __version__}
    for pkg in ("matplotlib", "numpy"):
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            pass
    return out


@dataclass
class BuildReport:
    figures: list[str] = field(default_factory=list)
    runs: list[RunResult] = field(default_factory=list)
    composed: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.runs)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "figures": self.figures,
            "runs": [
                {"producer": r.producer, "panels": r.panels, "ok": r.ok, "seconds": round(r.seconds, 3),
                 **({"error": r.error} if r.error else {})}
                for r in self.runs
            ],
            "composed": self.composed,
        }


def build(project: Project, figure_ids: list[str] | None = None, *, only: list[str] | None = None,
          force: bool = False, on_event: Event | None = None, cancelled: Callable[[], bool] | None = None,
          timeout: float | None = None, include_expensive: bool = True, retry_failed: bool = True) -> BuildReport:
    """Rebuild stale panels (all of ``only`` when given, everything with ``force``) and recompose.

    ``retry_failed=False`` is for automatic builds: a producer that failed on exactly these
    inputs is not run again until something it depends on changes.
    """
    rebuild = {"stale", "missing", "failed"} if retry_failed else {"stale", "missing"}
    report = BuildReport()
    emit = on_event or (lambda e: None)
    with project_lock(project):
        for fid in figure_ids or project.figure_ids():
            doc = S.load_figure(project.figure_json(fid))
            st = figure_status(project, fid)
            by_id = {p.id: p for p in st.panels}
            lock = read_lock(project, fid)
            for producer in doc.get("producers", []):
                wanted = [pid for pid in producer["panels"]
                          if (only is None or pid in only)
                          and (force or only is not None or by_id.get(pid) is None
                               or by_id[pid].state in rebuild)]
                if not wanted:
                    if all(by_id.get(pid) is not None and by_id[pid].state == "fresh" for pid in producer["panels"]):
                        _record_failure(project, fid, producer["id"], None)
                    continue
                if not include_expensive and producer.get("cost") == "expensive" and not force and only is None:
                    emit({"event": "producer.skipped", "figure": fid, "producer": producer["id"],
                          "reason": "expensive producers wait for an explicit build"})
                    continue
                staging = project.state_dir / "staging" / f"{fid}-{producer['id']}-{uuid.uuid4().hex[:8]}"
                journal_sha = _journal_sha(project, doc)
                prev = lock["producers"].get(producer["id"], {}).get("discovered", [])
                before = {"journal": journal_sha, "files": _producer_files(project, producer, prev),
                          "own": {q: _panel_own(project, fid, doc, q) for q in producer["panels"]}}
                try:
                    result = run_producer(project, fid, doc, producer, wanted, staging=staging, on_event=emit,
                                          timeout=timeout, cancelled=cancelled)
                    report.runs.append(result)
                    if result.ok:
                        for pid in wanted:
                            dest = project.panel_dir(fid, pid)
                            dest.mkdir(parents=True, exist_ok=True)
                            os.replace(staging / pid / "panel.svg", dest / "panel.svg")
                            os.replace(staging / pid / "manifest.json", dest / "manifest.json")
                        discovered, versions = _versions_from(staging)
                        _record_build(project, fid, doc, producer, wanted, discovered, versions, lock, before=before)
                        _record_failure(project, fid, producer["id"], None)
                    elif result.error != "cancelled":
                        shared = _shared(producer, before["files"], journal_sha)
                        _record_failure(project, fid, producer["id"], result.error,
                                        _fingerprint(shared, before["own"]))
                    emit({"event": "producer.done", "figure": fid, "producer": producer["id"], "ok": result.ok,
                          "seconds": round(result.seconds, 3), **({"error": result.error} if result.error else {})})
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
            composed = compose(project, fid, write=True)
            lock["figure_svg"] = sha256_file(composed.path)
            write_lock(project, fid, lock)
            report.figures.append(fid)
            report.composed.append({"figure": fid, **composed.to_json()})
            emit({"event": "figure.composed", "figure": fid, **composed.to_json()})
    return report


def after_direct_run(project: Project, fid: str, panels: list[str], script: Path | None,
                     discovered: list[str]) -> str:
    """A producer ran outside ``idofig build`` and published panels in place: record it
    in the lock (when a declared producer drew them) and recompose the figure."""
    doc = S.load_figure(project.figure_json(fid))
    with project_lock(project):
        lock = read_lock(project, fid)
        owners = {S.producer_of(doc, pid)["id"] for pid in panels if S.producer_of(doc, pid)}
        for prid in owners:
            producer = next(p for p in doc["producers"] if p["id"] == prid)
            mine = [pid for pid in panels if pid in producer["panels"]]
            _record_build(project, fid, doc, producer, mine, discovered, current_versions(), lock)
            _record_failure(project, fid, prid, None)
        composed = compose(project, fid, write=True)
        lock["figure_svg"] = sha256_file(composed.path)
        write_lock(project, fid, lock)
    return str(composed.path)


# ----------------------------------------------------------------------------- check


@dataclass
class CheckReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


# Kinds whose box is the ink a reader sees. A data mark is clipped to its axes but boxed
# unclipped (every zoomed plot would be flagged for data nobody sees), so it is not checked.
_INK_KINDS = {"text", "legend", "axes"}
_INK_TOLERANCE_MM = 0.2  # a spine's half-width at the panel edge is ~0.1 mm and is not a finding


def compliance(project: Project, fid: str, doc: dict) -> tuple[list[str], list[str]]:
    """The journal's figure rules on what was drawn, and ink drawn outside its panel's box.
    Findings name ``<figure>/<panel>: <part> is …`` so an editor can select the part."""
    errors: list[str] = []
    warnings: list[str] = []
    journal = J.load(doc.get("journal") or project.journal, str(project.root))
    jname = journal.get("name") or journal.get("id")
    lo, hi = journal.get("minFontPt"), journal.get("maxFontPt")
    lw = journal.get("lineWeightPt") or {}
    width = J.width_mm(journal, doc["width"])
    presets = {k: v for k, v in (journal.get("widthPresetsMm") or {}).items() if v}
    if "mm" in doc["width"] and presets and not any(abs(width - v) < 0.5 for v in presets.values()):
        warnings.append(f"{fid}: width {width:g} mm matches none of {jname}'s widths "
                        f"({', '.join(f'{k} {v:g} mm' for k, v in presets.items())})")
    max_h = journal.get("maxHeightMm")
    if max_h and doc.get("height") and doc["height"]["mm"] > max_h:
        errors.append(f"{fid}: height {doc['height']['mm']:g} mm exceeds {jname}'s {max_h:g} mm")
    # Letters are figure text, held to the journal's floor but not its ceiling: no preset states a
    # label size, and labels are set larger than the text they label (8 pt over Nature's 7; D4).
    letters = J.letter_style(journal, doc.get("letters"))
    size = float(letters["size_pt"])  # validated: a positive number
    if (letters.get("show", True) and lo is not None and size < lo - 1e-6
            and any(pn.get("letter") for pn in doc.get("panels", []))):
        warnings.append(f"{fid}: panel letters are {size:g} pt; {jname} requires at least {lo:g} pt")
    for pn in doc.get("panels", []):
        try:
            man = read_json(project.panel_dir(fid, pn["id"]) / "manifest.json")
        except (FileNotFoundError, ValueError):
            continue
        w_pt, h_pt = (man.get("size") or {}).get("w_pt"), (man.get("size") or {}).get("h_pt")
        # Boxes another render measured are not checked for ink: 0.2.x boxed parts it never drew
        # and a set_dpi(300) panel at 300/72 its size (18 false findings on one project).
        current = drawn_under(man) == RENDER
        parts = man.get("parts", {})
        # One finding per rule for a group's members (an axis' tick labels, a series' bars),
        # naming the group, which an editor selects: one per tick label made 20 of a port's 73.
        # A legend's entries count as its group when the legend is a part (a manifest written
        # before a figure legend's gid named its entries gives them a parent that is none).
        group_of = {m: g for g, part in parts.items() if part.get("group") for m in part.get("members", [])}
        group_of |= {n: part["parent"] for n, part in parts.items()
                     if part.get("role") == "legend-entry" and part.get("parent") in parts}
        found: dict[tuple[str, str], list[tuple[str, float]]] = {}  # (rule, part or group) → [(part, value)]

        def breaks(rule: str, name: str, value: float) -> None:
            found.setdefault((rule, group_of.get(name, name)), []).append((name, value))

        def thin(name: str, w: float | None) -> None:
            if w is not None and w > 0 and lw.get("min") is not None and w < lw["min"] - 1e-6:
                breaks("thin", name, w)

        for name, part in parts.items():
            box, props = part.get("bbox"), part.get("props") or {}
            if part.get("kind") == "axis":
                # No box, drawn or not: its major tick marks are its stroke while it is drawn and
                # they have a length (`tickwidth: 0.1` passed Nature's 0.25 pt; an image axes' under
                # axis("off") were findings nothing could fix). Its minor ones are not read:
                # idofig's rc draws them at 0.75 × the major width, its defaults included.
                if (current and part.get("drawn", True) and props.get("visible")
                        and (props.get("ticklength") or 0) > 0):
                    thin(name, props.get("tickwidth"))
                continue
            if not box:  # not drawn, so it breaks no rule (a colorbar's dividers were stroke findings)
                continue
            if current and part.get("kind") in _INK_KINDS and not part.get("group") and w_pt and h_pt:
                out = max(-box[0], -box[1], box[2] - w_pt, box[3] - h_pt) / PT_PER_MM
                if out > _INK_TOLERANCE_MM:
                    breaks("ink", name, round(out, 2))
            if part.get("kind") == "text" and props.get("text"):
                size = props.get("fontsize")
                if size is not None and lo is not None and size < lo - 1e-6:
                    breaks("small", name, size)
                if size is not None and hi is not None and size > hi + 1e-6:
                    breaks("large", name, size)
            # A drawn stroke of any kind thinner than the journal's line weight (a network's
            # LineCollection at 0.2 pt passed Nature's 0.25 pt). None: a markers-only line, an edge
            # in no colour (pcolor's default) or in its face colour (a scatter's, which merges into
            # its fill; an all-stroke '+' reads the colour it is drawn in). A manifest another
            # render wrote gets 0.2.x's line and spine check: it wrote "#000000" for no colour.
            if (part.get("kind") in ({"line", "spine", "patch", "collection"} if current else {"line", "spine"})
                    and props.get("linestyle") not in {"None", "none", "", " "}
                    and props.get("edgecolor", props.get("color")) not in {"none", "face"}):
                thin(name, part.get("thinnest_pt", props.get("linewidth")))
        texts = {"ink": "{v} mm outside its panel's box{n}",
                 "small": "{v} pt{n}; {j} requires at least {lo:g} pt",
                 "large": "{v} pt{n}; {j} states at most {hi:g} pt",
                 "thin": "{v} pt wide{n}; {j} states at least {lw:g} pt"}
        for (rule, unit), hits in found.items():
            values = sorted(v for _, v in hits)
            v = f"{values[0]:g}" if values[0] == values[-1] else f"{values[0]:g}–{values[-1]:g}"
            n = f" ({len(hits)} parts)" if len(hits) > 1 else ""
            text = texts[rule].format(v=v, n=n, j=jname, lo=lo, hi=hi, lw=lw.get("min"))
            (errors if rule == "small" else warnings).append(
                f"{fid}/{pn['id']}: {unit if len(hits) > 1 else hits[0][0]} is {text}")
    return errors, warnings


def check(project: Project, figure_ids: list[str] | None = None, *, run: bool = True,
          on_event: Event | None = None) -> CheckReport:
    """What CI runs: everything fresh, reproducible byte-for-byte, and within the journal's rules."""
    rep = CheckReport()
    for fid in figure_ids or project.figure_ids():
        st = figure_status(project, fid)
        if st.error:
            rep.errors.append(f"{fid}: {st.error}")
            continue
        doc = S.load_figure(project.figure_json(fid))
        for p in st.panels:
            if p.state in {"stale", "missing", "failed"}:
                rep.errors.append(f"{fid}/{p.id}: {p.state}" + (f" ({'; '.join(p.reasons)})" if p.reasons else "")
                                  + (f": {p.error.splitlines()[0]}" if p.error else ""))
            if p.detached_styles:
                rep.warnings.append(f"{fid}/{p.id}: detached style overrides: {', '.join(p.detached_styles)}")
            for inv in p.invalid_styles:
                rep.warnings.append(f"{fid}/{p.id}: ignored {inv['part']}.{inv['prop']}: {inv['reason']}")
            for w in p.warnings:
                rep.warnings.append(f"{fid}/{p.id}: {w}")
        if st.figure_svg != "fresh":
            rep.errors.append(f"{fid}: figure.svg is {st.figure_svg}; run `idofig build {fid}`")
        for d in st.detached_annotations:
            rep.warnings.append(f"{fid}: annotation {d['id']!r} is detached: {d['reason']}")
        for w in st.warnings:
            rep.warnings.append(f"{fid}: {w}")
        e, w = compliance(project, fid, doc)
        rep.errors.extend(e)
        rep.warnings.extend(w)
        if run:
            for producer in doc.get("producers", []):
                staging = project.state_dir / "staging" / f"check-{fid}-{producer['id']}-{uuid.uuid4().hex[:8]}"
                try:
                    res = run_producer(project, fid, doc, producer, list(producer["panels"]), staging=staging,
                                       on_event=on_event)
                    if not res.ok:
                        rep.errors.append(f"{fid}/{producer['id']}: rebuild failed: {res.error}")
                        continue
                    lock = read_lock(project, fid)
                    for pid in producer["panels"]:
                        fresh = (staging / pid / "panel.svg").read_bytes()
                        try:
                            committed = (project.panel_dir(fid, pid) / "panel.svg").read_bytes()
                        except FileNotFoundError:
                            committed = b""
                        if fresh == committed:
                            continue
                        # A producer whose own idofig was upgraded draws under a new render the
                        # lock cannot see: not irreproducible, but redrawn by a forced build.
                        entry = lock["panels"].get(pid)
                        try:  # run_producer checked it is there
                            now = drawn_under(read_json(staging / pid / "manifest.json"))
                        except ValueError:
                            now = None
                        if entry is not None and now is not None and now != drawn_under(entry):
                            rep.errors.append(
                                f"{fid}/{pid}: drawn by {_drawn_by(entry)} (render {drawn_under(entry)}); "
                                f"its producer now draws with render {now} — `idofig build --force {fid}` redraws it")
                        else:
                            rep.errors.append(f"{fid}/{pid}: not reproducible — a fresh build differs from the "
                                              "committed panel.svg")
                finally:
                    shutil.rmtree(staging, ignore_errors=True)
    return rep


def as_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)

