"""The ``idofig`` command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import journals as J
from . import scaffold
from . import spec as S
from ._version import __version__
from .build import build, check, status
from .compose import compose
from .errors import IdofigError
from .fsutil import read_json, rel
from .project import find_project

GLYPH = {"fresh": "✓", "stale": "•", "missing": "∅", "failed": "✗", "image": "▣", "orphan": "?"}


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _width(value: str | None) -> dict | None:
    if value is None:
        return None
    if value in J.WIDTH_PRESETS:
        return {"preset": value}
    try:
        return {"mm": float(value)}
    except ValueError:
        raise IdofigError(f"--width must be single, onehalf, double or a number of mm (got {value!r})") from None


def _place(value: str | None) -> dict | None:
    if not value:
        return None
    try:
        x, y, w, h = (float(v) for v in value.split(","))
    except ValueError:
        raise IdofigError("--place must be x,y,w,h in mm") from None
    return {"x": x, "y": y, "w": w, "h": h}


def _value(text: str):
    low = text.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none", "reset"}:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def cmd_status(args) -> int:
    project = find_project()
    sts = status(project, args.figures or None)
    if args.json:
        _print_json([s.to_json() for s in sts])
        return 0
    stale = 0
    for s in sts:
        head = "stale" if s.stale else "fresh"
        stale += s.stale
        print(f"{s.id}  [{head}]  figure.svg {s.figure_svg}")
        if s.error:
            print(f"    error: {s.error}")
        for p in s.panels:
            line = f"  {GLYPH.get(p.state, ' ')} {p.id:<16} {p.state}"
            if p.reasons:
                line += f"  ({'; '.join(p.reasons)})"
            print(line)
            if p.error:
                print("      " + p.error.splitlines()[0])
            if p.detached_styles:
                print(f"      detached style: {', '.join(p.detached_styles)}")
        for d in s.detached_annotations:
            print(f"  ! annotation {d['id']}: {d['reason']}")
        for w in s.warnings:
            print(f"  ! {w}")
    return 1 if (args.exit_code and stale) else 0


def cmd_build(args) -> int:
    project = find_project()
    only = [x for x in (args.only or "").split(",") if x] or None

    def show(e: dict) -> None:
        if args.json:
            return
        kind = e.get("event")
        if kind == "producer.start":
            print(f"▶ {e['figure']}: {e['producer']} → {', '.join(e['panels'])}", flush=True)
        elif kind == "producer.output" and args.verbose:
            print(f"    {e['line']}", flush=True)
        elif kind == "producer.done":
            mark = "✓" if e["ok"] else "✗"
            print(f"  {mark} {e['producer']} ({e['seconds']:.2f} s)", flush=True)
            if not e["ok"]:
                print("    " + (e.get("error") or "").replace("\n", "\n    "), flush=True)
        elif kind == "producer.skipped":
            print(f"  – {e['producer']} skipped: {e['reason']}")
        elif kind == "figure.composed":
            note = "written" if e["changed"] else "unchanged"
            print(f"  ◻ {e['figure']}/figure.svg {note} ({e['ms']:.1f} ms)")
            for d in e.get("detached", []):
                print(f"    ! annotation {d['id']}: {d['reason']}")
            for w in e.get("warnings", []):
                print(f"    ! {w}")

    report = build(project, args.figures or None, only=only, force=args.force, on_event=show,
                   include_expensive=not args.skip_expensive)
    if args.json:
        _print_json(report.to_json())
    return 0 if report.ok else 1


def cmd_compose(args) -> int:
    project = find_project()
    result = compose(project, args.figure, write=True)
    if args.json:
        _print_json(result.to_json())
    else:
        print(f"{rel(result.path, project.root)} {'written' if result.changed else 'unchanged'} "
              f"({result.width_mm:g}×{result.height_mm:g} mm, {result.ms:.1f} ms)")
        for w in result.warnings:
            print(f"  ! {w}")
        for d in result.detached:
            print(f"  ! annotation {d['id']}: {d['reason']}")
    return 0


def cmd_check(args) -> int:
    project = find_project()
    rep = check(project, args.figures or None, run=not args.no_run)
    if args.json:
        _print_json(rep.to_json())
    else:
        for e in rep.errors:
            print(f"✗ {e}")
        for w in rep.warnings:
            print(f"! {w}")
        print("check passed" if rep.ok else f"check failed: {len(rep.errors)} problem(s)")
    return 0 if rep.ok else 1


def cmd_init(args) -> int:
    path = scaffold.init_project(Path.cwd(), journal=args.journal, figures=args.figures_dir)
    print(f"idofig project: {path}")
    return 0


def cmd_new(args) -> int:
    project = find_project()
    path = scaffold.new_figure(project, args.figure, width=_width(args.width))
    print(f"created {rel(path, project.root)}")
    return 0


def cmd_add_panel(args) -> int:
    project = find_project()
    res = scaffold.add_panel(project, args.figure, args.panel, template=args.template, script=args.script,
                             place=_place(args.place))
    if res["created"]:
        print(f"created {res['created']} — edit it, then `idofig build {args.figure}`")
    else:
        print(f"panel {args.panel} is drawn by {res['script']}")
    return 0


def cmd_style(args) -> int:
    project = find_project()
    path = project.panel_dir(args.figure, args.panel) / "style.json"
    if args.reset:
        S.update_style(path, args.part, None)
        print(f"reset {args.part}")
        return 0
    props = {}
    for kv in args.props:
        if "=" not in kv:
            raise IdofigError(f"expected key=value, got {kv!r}")
        k, v = kv.split("=", 1)
        props[k] = _value(v)
    try:
        parts = read_json(project.panel_dir(args.figure, args.panel) / "manifest.json").get("parts", {})
    except FileNotFoundError:
        parts = {}
    if parts and args.part not in parts and "*" not in args.part:
        raise IdofigError(f"panel {args.panel!r} has no part {args.part!r} (see `idofig parts {args.figure} {args.panel}`)")
    info = parts.get(args.part)
    if info:
        from .props import validate

        problems = validate(info["kind"], {k: v for k, v in props.items() if v is not None}, group=bool(info.get("group")))
        if problems:
            raise IdofigError("; ".join(problems))
    S.update_style(path, args.part, props)
    print(f"{rel(path, project.root)}: {args.part} ← {json.dumps(props)}  (rebuild: idofig build {args.figure})")
    return 0


def cmd_parts(args) -> int:
    project = find_project()
    man = read_json(project.panel_dir(args.figure, args.panel) / "manifest.json")
    parts = man.get("parts", {})
    if args.json:
        _print_json(parts)
        return 0
    for name, p in parts.items():
        props = p.get("props") or {}
        extra = f" “{props['text']}”" if props.get("text") else ""
        print(f"{name:<40} {p['kind']:<10} {p['stability']:<10}{extra}")
    return 0


def cmd_locate(args) -> int:
    from .locate import locate

    hits = locate(find_project(), args.figure, args.panel, args.part)
    if args.json:
        _print_json(hits)
        return 0
    if not hits:
        print(f"no line found that makes {args.part} (it may be set in a helper or computed)")
        return 1
    for h in hits:
        print(f"{h['file']}:{h['line']}: {h['text']}")
    return 0


def cmd_journals(args) -> int:
    rows = [J.load(j) for j in J.bundled_ids()]
    if args.json:
        _print_json(rows)
        return 0
    for j in rows:
        w = j.get("widthPresetsMm") or {}
        widths = ", ".join(f"{k} {v:g}" for k, v in w.items() if v) or "no stated widths"
        print(f"{j['id']:<18} {j.get('name', ''):<28} {widths} mm; min font {j.get('minFontPt') or '—'} pt")
    return 0


def cmd_serve(args) -> int:
    from .serve import main

    return main(find_project())


def cmd_rpc(args) -> int:
    """One server method, once: the same code path an application's ``serve`` uses."""
    import io

    from .serve import Server

    try:
        params = json.loads(args.params) if args.params else {}
    except ValueError as exc:
        print(json.dumps({"error": {"message": f"params are not JSON: {exc}"}}))
        return 2
    if not isinstance(params, dict):
        print(json.dumps({"error": {"message": "params must be a JSON object"}}))
        return 2
    server = Server(find_project(), out=io.StringIO())
    server.dispatch({"jsonrpc": "2.0", "id": 1, "method": args.method, "params": params})
    server.wait_idle()
    replies = [json.loads(line) for line in server.out.getvalue().splitlines()]
    answer = next((m for m in reversed(replies) if m.get("id") == 1), None)
    if answer is None:
        print(json.dumps({"error": {"message": f"{args.method} did not answer"}}))
        return 1
    if "error" in answer:
        print(json.dumps({"error": answer["error"]}, ensure_ascii=False))
        return 1
    print(json.dumps({"result": answer["result"]}, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="idofig", description="Reproducible, editable publication figures.")
    ap.add_argument("--version", action="version", version=f"idofig {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status", help="which panels are stale, and why")
    p.add_argument("figures", nargs="*")
    p.add_argument("--json", action="store_true")
    p.add_argument("--exit-code", action="store_true", help="exit 1 when anything is stale")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("build", help="rebuild stale panels and recompose figures")
    p.add_argument("figures", nargs="*")
    p.add_argument("--only", help="comma-separated panel ids")
    p.add_argument("--force", action="store_true", help="rebuild even fresh panels")
    p.add_argument("--skip-expensive", action="store_true", help="leave producers marked expensive alone")
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="show producer output")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("compose", help="recompose figure.svg from figure.json and the built panels")
    p.add_argument("figure")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_compose)

    p = sub.add_parser("check", help="CI: fresh, reproducible, within the journal's rules")
    p.add_argument("figures", nargs="*")
    p.add_argument("--no-run", action="store_true", help="skip the rebuild-and-compare step")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("init", help="make the current directory an idofig project")
    p.add_argument("--journal", default="suna")
    p.add_argument("--figures-dir", default="figures")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("new", help="create a figure")
    p.add_argument("figure")
    p.add_argument("--width", help="single, onehalf, double, or millimetres")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("add-panel", help="add a panel (and a producer from a template)")
    p.add_argument("figure")
    p.add_argument("panel")
    p.add_argument("--template", default="bar", choices=scaffold.TEMPLATES)
    p.add_argument("--script", help="an existing producer script that will draw this panel too")
    p.add_argument("--place", help="x,y,w,h in mm")
    p.set_defaults(fn=cmd_add_panel)

    p = sub.add_parser("style", help="set style overrides on a named part (key=value …)")
    p.add_argument("figure")
    p.add_argument("panel")
    p.add_argument("part")
    p.add_argument("props", nargs="*")
    p.add_argument("--reset", action="store_true", help="remove every override of this part")
    p.set_defaults(fn=cmd_style)

    p = sub.add_parser("parts", help="list a panel's named parts")
    p.add_argument("figure")
    p.add_argument("panel")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_parts)

    p = sub.add_parser("locate", help="find the code line that makes a named part")
    p.add_argument("figure")
    p.add_argument("panel")
    p.add_argument("part")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_locate)

    p = sub.add_parser("journals", help="list the bundled journal presets")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_journals)

    p = sub.add_parser("serve", help="JSON-RPC over stdio for applications")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("rpc", help="call one server method once and print {result} or {error} as JSON")
    p.add_argument("method")
    p.add_argument("params", nargs="?", help="a JSON object")
    p.set_defaults(fn=cmd_rpc)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.fn(args)
    except IdofigError as exc:
        print(f"idofig: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
