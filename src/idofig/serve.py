"""``idofig serve``: JSON-RPC 2.0 over stdio, one JSON object per line (no batches: a line
that is not strict JSON — NaN, Infinity and 1e999 are not — is answered with error -32700,
one that is not an object with -32600, and the server goes on).

Applications (SUNA) keep one server per project so composing takes milliseconds rather
than a Python start-up. Every write goes through the same functions the CLI uses.

Requests are handled in order. ``build`` requests queue on one worker thread (a second
build never refuses: it runs after the first, and finds nothing to do if the first already
covered it); each streams ``event`` notifications and answers when it is done.
``cancel`` stops the running build and drops the queued ones.

Methods
-------
hello                                   → version, root, figures dir, journal, python
workspace                               → every figure: document, manifests, styles, status
figure        {figure}                  → one figure, as in workspace (with `rules`: the journal's findings)
status        {figures?}                → figure statuses
compose       {figure}                  → compose result (figure.svg written)
build         {figures?, only?, force?, include_expensive?, retry_failed?, timeout?}  → build report
cancel                                  → {cancelled, dropped}: stops the running build, drops queued ones
update_figure {figure, ops}             → {before, after_sha, doc, compose}
update_style  {figure, panel, part, props}  → {before, after_sha, path}   (props null → reset the part)
move_style    {figure, panel, from, to}     → {before, after_sha, path}   (re-attach a detached override)
restore       {path, text, expect_sha}  → restores a file for undo, only if unchanged since;
                                          {restored, sha, previous, compose}: previous is the
                                          text it replaced (for redo)
new_figure    {figure, width?, extra?}  → {path}
add_panel     {figure, panel, template?, script?, image?, place?, letter?}
                                        → {figure, panel, script, created} (image: a project
                                          file, placed as it is)
check         {figures?, run?}          → CI's verdict: fresh, reproducible, within the journal's rules
parts         {figure, panel}           → the panel's manifest parts
locate        {figure, panel, part}     → candidate code lines that make the part
journal                                 → the project's journal preset (resolved)
journals                                → bundled journal presets
props                                   → the style property table, per part kind
validate_style {kind, props, group?, role?}  → the problems with setting props on a part of kind ([]: valid)
shutdown                                → {bye}
"""

from __future__ import annotations

import json
import platform
import sys
import threading
import traceback
from queue import Empty, Queue

from . import journals as J
from . import props as P
from . import scaffold
from . import spec as S
from ._version import __version__
from .build import build, check, compliance, edit_lock, figure_status, status
from .compose import compose
from .errors import IdofigError, SpecError
from .fsutil import loads, read_json, rel, sha256_file, write_atomic
from .project import Project


class Server:
    def __init__(self, project: Project, out=None):
        self.project = project
        self.out = out or sys.stdout
        self.write_lock = threading.Lock()
        self.build_thread: threading.Thread | None = None
        self.build_queue: Queue = Queue()
        self.building = False
        self.cancel_flag = threading.Event()
        self.running = True

    # -- transport
    def send(self, obj: dict) -> None:
        """Write one message; ValueError, before a byte is written, for a NaN or Infinity (a
        line JSON.parse refuses: the client waited for an answer that never came)."""
        line = json.dumps(obj, ensure_ascii=False, allow_nan=False)
        with self.write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    def notify(self, params: dict) -> None:
        self.send({"jsonrpc": "2.0", "method": "event", "params": params})

    def reply(self, rid, result=None, error: Exception | None = None) -> None:
        if rid is None:
            return
        if error is None:
            self.send({"jsonrpc": "2.0", "id": rid, "result": result})
            return
        data = {"type": type(error).__name__}
        if isinstance(error, SpecError):
            data["problems"] = error.problems
        if not isinstance(error, IdofigError):
            data["traceback"] = traceback.format_exc()[-4000:]
        self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(error), "data": data}})

    def serve(self, stream=None) -> None:
        stream = stream or sys.stdin
        self.notify({"event": "ready", "version": __version__, "root": str(self.project.root)})
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                # Strictly, as replies are written: an id of NaN or 1e999 could be echoed in no
                # answer, and the ValueError ended the server with every request behind it.
                msg = loads(line)
            except ValueError as exc:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}})
                continue
            self.dispatch(msg)
            if not self.running:
                break
        self.cancel_flag.set()
        self._drop_queued("the server is shutting down")
        if self.build_thread:
            self.build_queue.put(None)
            self.build_thread.join(timeout=5)

    def wait_idle(self, timeout: float = 300) -> None:
        """Block until every queued build has answered (tests; shutdown)."""
        import time

        t0 = time.monotonic()
        while (self.building or not self.build_queue.empty()) and time.monotonic() - t0 < timeout:
            time.sleep(0.02)

    def dispatch(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            # A batch (`[{…}]`) or a bare `5` raised out of `serve`: the server ended with no
            # reply, and every request queued behind it went unanswered.
            self.send({"jsonrpc": "2.0", "id": None, "error": {
                "code": -32600, "message": "invalid request: expected a JSON object (batches are not supported)"}})
            return
        rid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        handler = getattr(self, f"m_{method}", None) if isinstance(method, str) else None
        if handler is None:
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method!r}"}})
            return
        try:
            if method in _EDITS:
                with edit_lock(self.project):
                    result = handler(rid, **params)
            else:
                result = handler(rid, **params)
        except TypeError as exc:
            self.reply(rid, error=IdofigError(f"bad parameters for {method}: {exc}"))
            return
        except Exception as exc:  # noqa: BLE001 — every failure goes back to the client
            self.reply(rid, error=exc)
            return
        if result is not _DEFERRED:
            try:
                self.reply(rid, result)
            except ValueError as exc:
                self.reply(rid, error=IdofigError(f"{method}: the answer holds a number JSON cannot carry ({exc})"))

    # -- methods
    def m_hello(self, rid):
        return {"version": __version__, "root": str(self.project.root),
                "figures_dir": rel(self.project.figures_dir, self.project.root), "journal": self.project.journal,
                "python": sys.executable, "python_version": platform.python_version()}

    def _manifests(self, fid: str, doc: dict) -> dict:
        out = {}
        for pn in doc.get("panels", []):
            try:
                out[pn["id"]] = read_json(self.project.panel_dir(fid, pn["id"]) / "manifest.json")
            except (FileNotFoundError, ValueError):
                pass
        return out

    def _styles(self, fid: str, doc: dict) -> dict:
        out = {}
        for pn in doc.get("panels", []):
            try:
                out[pn["id"]] = S.load_style(self.project.panel_dir(fid, pn["id"]) / "style.json")
            except IdofigError:
                out[pn["id"]] = None
        return out

    def _figure_entry(self, fid: str) -> dict:
        entry: dict = {"id": fid}
        try:
            doc = S.load_figure(self.project.figure_json(fid))
            entry["doc"] = doc
            entry["manifests"] = self._manifests(fid, doc)
            entry["styles"] = self._styles(fid, doc)
            journal = J.load(doc.get("journal") or self.project.journal, str(self.project.root))
            entry["journal"] = journal.get("id") or doc.get("journal") or self.project.journal
            entry["width_mm"] = J.width_mm(journal, doc["width"])  # the column: a cap, not the size
            entry["max_height_mm"] = journal.get("maxHeightMm")  # null where the journal states none
            # The journal's figure rules on what matplotlib drew (the check CI runs, minus
            # the rebuild): an editor shows them beside the figure as it is edited.
            errors, warnings = compliance(self.project, fid, doc)
            entry["rules"] = {"errors": errors, "warnings": warnings}
        except IdofigError as exc:
            entry["error"] = str(exc)
        entry["status"] = figure_status(self.project, fid).to_json()
        entry["svg"] = rel(self.project.figure_dir(fid) / "figure.svg", self.project.root)
        return entry

    def m_workspace(self, rid):
        try:
            journal = J.load(self.project.journal, str(self.project.root))
        except IdofigError as exc:
            journal = {"id": self.project.journal, "error": str(exc)}
        return {"figures": [self._figure_entry(fid) for fid in self.project.figure_ids()],
                "journal": journal, "root": str(self.project.root),
                "figures_dir": rel(self.project.figures_dir, self.project.root)}

    def m_figure(self, rid, figure):
        if not self.project.figure_json(figure).is_file():
            raise IdofigError(f"no figure {figure!r} in {rel(self.project.figures_dir, self.project.root)}")
        return self._figure_entry(figure)

    def m_status(self, rid, figures=None):
        return [s.to_json() for s in status(self.project, figures)]

    def m_compose(self, rid, figure):
        return compose(self.project, figure, write=True).to_json()

    def m_build(self, rid, figures=None, only=None, force=False, include_expensive=True, timeout=None,
                retry_failed=True):
        job = {"figures": figures, "only": only, "force": force, "include_expensive": include_expensive,
               "timeout": timeout, "retry_failed": retry_failed}
        self.build_queue.put((rid, job))
        if self.build_thread is None or not self.build_thread.is_alive():
            self.build_thread = threading.Thread(target=self._build_worker, name="idofig-build", daemon=True)
            self.build_thread.start()
        return _DEFERRED

    def _build_worker(self) -> None:
        while True:
            item = self.build_queue.get()
            if item is None:
                return
            rid, job = item
            self.building = True
            self.cancel_flag.clear()
            try:
                self.notify({"event": "build.start", **{k: v for k, v in job.items() if v not in (None, False)}})
                report = build(self.project, job["figures"], only=job["only"], force=job["force"],
                               on_event=self.notify, cancelled=self.cancel_flag.is_set, timeout=job["timeout"],
                               include_expensive=job["include_expensive"], retry_failed=job["retry_failed"])
                result = report.to_json()
                self.notify({"event": "build.done", "ok": result["ok"], "figures": result["figures"]})
                self.reply(rid, result)
            except Exception as exc:  # noqa: BLE001
                self.notify({"event": "build.done", "ok": False, "error": str(exc)})
                self.reply(rid, error=exc)
            finally:
                self.building = False

    def _drop_queued(self, why: str) -> int:
        dropped = 0
        while True:
            try:
                item = self.build_queue.get_nowait()
            except Empty:
                return dropped
            if item is None:
                self.build_queue.put(None)
                return dropped
            self.reply(item[0], error=IdofigError(f"build cancelled: {why}"))
            dropped += 1

    def m_cancel(self, rid):
        running = self.building
        self.cancel_flag.set()
        dropped = self._drop_queued("cancelled")
        return {"cancelled": running, "dropped": dropped}

    def m_update_figure(self, rid, figure, ops):
        path = self.project.figure_json(figure)
        before_text = path.read_text(encoding="utf-8")
        root = str(self.project.root)
        _, after = S.update_figure(path, ops, width_of=lambda d: J.width_mm(
            J.load(d.get("journal") or self.project.journal, root), d["width"]))
        result = compose(self.project, figure, write=True)
        return {"before": before_text, "after_sha": sha256_file(path), "doc": after, "compose": result.to_json()}

    def m_update_style(self, rid, figure, panel, part, props=None):
        pdir = self.project.panel_dir(figure, panel)
        manifest = None
        try:
            manifest = read_json(pdir / "manifest.json")
        except (FileNotFoundError, ValueError):
            pass
        if props is not None and manifest is not None:
            parts = manifest.get("parts", {})
            if part not in parts and "*" not in part:
                raise IdofigError(f"panel {panel!r} has no part {part!r}; known parts: "
                                  f"{', '.join(sorted(parts)[:40])}")
            info = parts.get(part)
            if info is not None:
                problems = P.validate(info["kind"], {k: v for k, v in props.items() if v is not None},
                                      group=bool(info.get("group")), role=info.get("role"))
                if problems:
                    raise SpecError(f"{figure}/{panel}/{part}", problems)
        path = pdir / "style.json"
        before_text = path.read_text(encoding="utf-8") if path.exists() else None
        S.update_style(path, part, props)
        return {"before": before_text, "after_sha": sha256_file(path), "path": rel(path, self.project.root)}

    def m_update_panel_style(self, rid, figure, panel, props):
        """style.json's panel-wide keys (``layout``, ``trim``, ``trim_mm``); undone with ``restore``."""
        path = self.project.panel_dir(figure, panel) / "style.json"
        before_text = path.read_text(encoding="utf-8") if path.exists() else None
        S.update_panel_style(path, props)
        return {"before": before_text, "after_sha": sha256_file(path), "path": rel(path, self.project.root)}

    def m_move_style(self, rid, figure, panel, **kw):
        old, new = kw["from"], kw["to"]
        pdir = self.project.panel_dir(figure, panel)
        path = pdir / "style.json"
        try:
            parts = read_json(pdir / "manifest.json").get("parts", {})
        except (FileNotFoundError, ValueError):
            parts = {}
        if parts and new not in parts and "*" not in new:
            raise IdofigError(f"panel {panel!r} has no part {new!r}")
        before_text = path.read_text(encoding="utf-8") if path.exists() else None
        _, after = S.move_style(path, old, new)
        info = parts.get(new)
        if info is not None:
            problems = P.validate(info["kind"], after["parts"][new], group=bool(info.get("group")),
                                  role=info.get("role"))
            if problems:
                if before_text is not None:
                    write_atomic(path, before_text)
                raise SpecError(f"{figure}/{panel}/{new}", problems)
        return {"before": before_text, "after_sha": sha256_file(path), "path": rel(path, self.project.root)}

    def m_restore(self, rid, path, text, expect_sha):
        """Undo: put back ``text`` only if the file is still what our last write made it."""
        target = (self.project.root / path).resolve()
        if self.project.figures_dir not in target.parents or target.name not in {"figure.json", "style.json"}:
            raise IdofigError(f"{path} is not a figure.json or style.json of this project")
        current = sha256_file(target)
        if current != expect_sha:
            raise IdofigError(f"{path} changed since this edit (someone else wrote it); undo would overwrite that")
        previous = target.read_text(encoding="utf-8") if current is not None else None
        if text is None:
            target.unlink(missing_ok=True)
        else:
            try:
                doc = loads(text)
            except ValueError as exc:
                raise SpecError(path, [f"not valid JSON: {exc}"]) from None
            if target.name == "figure.json":
                problems = S.validate_figure(doc, expected_id=target.parent.name)
            else:
                problems = S.validate_style(doc)
            if problems:
                raise SpecError(path, problems)
            write_atomic(target, text)
        fid = target.parent.name if target.name == "figure.json" else target.parents[2].name
        composed = compose(self.project, fid, write=True).to_json() if target.name == "figure.json" else None
        return {"restored": path, "sha": sha256_file(target), "previous": previous, "compose": composed}

    def m_new_figure(self, rid, figure, width=None, extra=None):
        path = scaffold.new_figure(self.project, figure, width=width, extra=extra)
        compose(self.project, figure, write=True)
        return {"path": rel(path, self.project.root)}

    def m_add_panel(self, rid, figure, panel, template="bar", script=None, place=None, letter="auto", image=None):
        if image:
            return scaffold.add_image_panel(self.project, figure, panel, image, place=place, letter=letter)
        return scaffold.add_panel(self.project, figure, panel, template=template, script=script, place=place,
                                  letter=letter)

    def m_check(self, rid, figures=None, run=True):
        return check(self.project, figures, run=bool(run)).to_json()

    def m_parts(self, rid, figure, panel):
        return read_json(self.project.panel_dir(figure, panel) / "manifest.json").get("parts", {})

    def m_locate(self, rid, figure, panel, part):
        from .locate import locate

        return locate(self.project, figure, panel, part)

    def m_journal(self, rid):
        return J.load(self.project.journal, str(self.project.root))

    def m_journals(self, rid):
        return [J.load(j) for j in J.bundled_ids()]

    def m_props(self, rid):
        return P.describe()

    def m_validate_style(self, rid, kind, props, group=False, role=None):
        return P.validate(kind, props, group=group, role=role)

    def m_shutdown(self, rid):
        self.running = False
        return {"bye": True}


class _Deferred:
    pass


_DEFERRED = _Deferred()

# Methods that write figure.json or style.json: run under `edit_lock` (see there).
_EDITS = frozenset({"update_figure", "update_style", "update_panel_style", "move_style", "restore",
                    "new_figure", "add_panel"})


def main(project: Project) -> int:
    Server(project).serve()
    return 0

