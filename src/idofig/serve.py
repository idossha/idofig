"""``idofig serve``: JSON-RPC 2.0 over stdio, one JSON object per line.

Applications (SUNA) keep one server per project so composing takes milliseconds rather
than a Python start-up. Every write goes through the same functions the CLI uses.

Requests are handled in order; ``build`` runs on a worker thread, streams ``event``
notifications while it runs, and answers when it is done. ``cancel`` stops it.

Methods
-------
hello                                   → version, root, figures dir, journal
workspace                               → every figure: document, manifests, status
status        {figures?}                → figure statuses
compose       {figure}                  → compose result (figure.svg written)
build         {figures?, only?, force?, include_expensive?}  → build report
cancel                                  → cancels the running build
update_figure {figure, ops}             → {before, after, compose}
update_style  {figure, panel, part, props}  → {before, after}   (props null → reset the part)
restore       {path, text, expect_sha}  → restores a file for undo, only if unchanged since
new_figure    {figure, width?, extra?}
add_panel     {figure, panel, template?, script?, place?}
parts         {figure, panel}           → the panel's manifest parts
locate        {figure, panel, part}     → candidate code lines that make the part
journals                               → bundled journal presets
shutdown
"""

from __future__ import annotations

import json
import sys
import threading
import traceback

from . import journals as J
from . import props as P
from . import scaffold
from . import spec as S
from ._version import __version__
from .build import build, figure_status, status
from .compose import compose
from .errors import IdofigError, SpecError
from .fsutil import read_json, rel, sha256_file, write_atomic
from .project import Project


class Server:
    def __init__(self, project: Project, out=None):
        self.project = project
        self.out = out or sys.stdout
        self.write_lock = threading.Lock()
        self.build_thread: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.running = True

    # -- transport
    def send(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False)
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
                msg = json.loads(line)
            except ValueError as exc:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}})
                continue
            self.dispatch(msg)
            if not self.running:
                break
        if self.build_thread:
            self.cancel_flag.set()
            self.build_thread.join(timeout=5)

    def dispatch(self, msg: dict) -> None:
        rid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        handler = getattr(self, f"m_{method}", None) if isinstance(method, str) else None
        if handler is None:
            self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown method {method!r}"}})
            return
        try:
            result = handler(rid, **params)
        except TypeError as exc:
            self.reply(rid, error=IdofigError(f"bad parameters for {method}: {exc}"))
            return
        except Exception as exc:  # noqa: BLE001 — every failure goes back to the client
            self.reply(rid, error=exc)
            return
        if result is not _DEFERRED:
            self.reply(rid, result)

    # -- methods
    def m_hello(self, rid):
        return {"version": __version__, "root": str(self.project.root),
                "figures_dir": rel(self.project.figures_dir, self.project.root), "journal": self.project.journal}

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

    def m_workspace(self, rid):
        figures = []
        for fid in self.project.figure_ids():
            entry: dict = {"id": fid}
            try:
                doc = S.load_figure(self.project.figure_json(fid))
                entry["doc"] = doc
                entry["manifests"] = self._manifests(fid, doc)
                entry["styles"] = self._styles(fid, doc)
                journal = J.load(doc.get("journal") or self.project.journal, str(self.project.root))
                entry["width_mm"] = J.width_mm(journal, doc["width"])
            except IdofigError as exc:
                entry["error"] = str(exc)
            entry["status"] = figure_status(self.project, fid).to_json()
            entry["svg"] = rel(self.project.figure_dir(fid) / "figure.svg", self.project.root)
            figures.append(entry)
        return {"figures": figures, "journal": self.project.journal}

    def m_status(self, rid, figures=None):
        return [s.to_json() for s in status(self.project, figures)]

    def m_compose(self, rid, figure):
        return compose(self.project, figure, write=True).to_json()

    def m_build(self, rid, figures=None, only=None, force=False, include_expensive=True, timeout=None):
        if self.build_thread and self.build_thread.is_alive():
            raise IdofigError("a build is already running; wait for it or cancel it")
        self.cancel_flag.clear()

        def work():
            try:
                report = build(self.project, figures, only=only, force=force, on_event=self.notify,
                               cancelled=self.cancel_flag.is_set, timeout=timeout,
                               include_expensive=include_expensive)
                self.reply(rid, report.to_json())
            except Exception as exc:  # noqa: BLE001
                self.reply(rid, error=exc)

        self.build_thread = threading.Thread(target=work, name="idofig-build", daemon=True)
        self.build_thread.start()
        return _DEFERRED

    def m_cancel(self, rid):
        self.cancel_flag.set()
        return {"cancelled": bool(self.build_thread and self.build_thread.is_alive())}

    def m_update_figure(self, rid, figure, ops):
        path = self.project.figure_json(figure)
        before_text = path.read_text(encoding="utf-8")
        _, after = S.update_figure(path, ops)
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
                                      group=bool(info.get("group")))
                if problems:
                    raise SpecError(f"{figure}/{panel}/{part}", problems)
        path = pdir / "style.json"
        before_text = path.read_text(encoding="utf-8") if path.exists() else None
        S.update_style(path, part, props)
        return {"before": before_text, "after_sha": sha256_file(path), "path": rel(path, self.project.root)}

    def m_restore(self, rid, path, text, expect_sha):
        """Undo: put back ``text`` only if the file is still what our last write made it."""
        target = (self.project.root / path).resolve()
        if self.project.figures_dir not in target.parents or target.name not in {"figure.json", "style.json"}:
            raise IdofigError(f"{path} is not a figure.json or style.json of this project")
        current = sha256_file(target)
        if current != expect_sha:
            raise IdofigError(f"{path} changed since this edit (someone else wrote it); undo would overwrite that")
        if text is None:
            target.unlink(missing_ok=True)
        else:
            if target.name == "figure.json":
                problems = S.validate_figure(json.loads(text), expected_id=target.parent.name)
            else:
                problems = S.validate_style(json.loads(text))
            if problems:
                raise SpecError(path, problems)
            write_atomic(target, text)
        return {"restored": path, "sha": sha256_file(target)}

    def m_new_figure(self, rid, figure, width=None, extra=None):
        path = scaffold.new_figure(self.project, figure, width=width, extra=extra)
        compose(self.project, figure, write=True)
        return {"path": rel(path, self.project.root)}

    def m_add_panel(self, rid, figure, panel, template="bar", script=None, place=None, letter="auto"):
        return scaffold.add_panel(self.project, figure, panel, template=template, script=script, place=place,
                                  letter=letter)

    def m_parts(self, rid, figure, panel):
        return read_json(self.project.panel_dir(figure, panel) / "manifest.json").get("parts", {})

    def m_locate(self, rid, figure, panel, part):
        from .locate import locate

        return locate(self.project, figure, panel, part)

    def m_journals(self, rid):
        return [J.load(j) for j in J.bundled_ids()]

    def m_validate_style(self, rid, kind, props, group=False):
        return P.validate(kind, props, group=group)

    def m_shutdown(self, rid):
        self.running = False
        return {"bye": True}


class _Deferred:
    pass


_DEFERRED = _Deferred()


def main(project: Project) -> int:
    Server(project).serve()
    return 0

