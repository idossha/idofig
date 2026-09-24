"""figure.json (schema 2 or 3) and style.json (schema 1): validation, loading, and edits.

Both files are sources of truth that people, agents and the canvas edit. Every write
re-reads the file from disk, applies the change to that fresh copy, validates the
result and writes atomically, because someone else may have edited it since.

figure.json keys idofig owns: ``schema id width height journal letters producers panels
annotations``. Any other top-level key (``caption``, ``namespace``, ``label`` ...) belongs
to the application that embeds idofig and is preserved untouched.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Callable

from .errors import NotJSONError, SpecError
from .fsutil import read_json, write_json
from .project import ID_RE
from .props import is_color, is_finite_number

FIGURE_SCHEMA = 2  # a new figure's; see figure_schema
STYLE_SCHEMA = 1
OWNED_KEYS = {"schema", "id", "width", "height", "journal", "letters", "producers", "panels", "annotations"}
ANNOTATION_TYPES = {"text", "arrow", "line", "bracket", "box"}
ANCHOR_POSITIONS = {
    "center", "top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right",
}
PART_NAME_RE = re.compile(r"^[^\s\"'<>&]+$")
LETTER_KEYS = {"show", "case", "weight", "size_pt", "offset_mm", "wrapper", "color"}


# ----------------------------------------------------------------------------- helpers


_is_num = is_finite_number  # an int too large for a float is none: 10**400 raised OverflowError here


def _is_pair(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and all(_is_num(x) for x in v)


def _id_ok(v: Any) -> bool:
    return isinstance(v, str) and bool(ID_RE.match(v)) and ".." not in v


def _one_of(v: Any, options: Any) -> bool:
    """``v`` is one of the strings ``options``. With ``in`` alone, ``"weight": ["bold"]`` raised
    "unhashable type", and one such figure.json broke ``workspace`` for the whole project."""
    return isinstance(v, str) and v in options


# How far a letter moves from where the figure-wide rule puts it (mm, each way), as a part does:
# unbounded, [-500, 0] drew a letter off the figure unreported, and 1e308 wrote x="inf".
LETTER_OFFSET_MM = 100


def _is_letter_offset(v: Any) -> bool:
    return _is_pair(v) and all(abs(x) <= LETTER_OFFSET_MM for x in v)


# ----------------------------------------------------------------------------- figure.json


def validate_anchor(a: Any, where: str, panel_ids: set[str]) -> list[str]:
    p: list[str] = []
    if not isinstance(a, dict):
        return [f"{where} must be an object"]
    if "offset" in a:
        if not _is_pair(a["offset"]):
            p.append(f"{where}.offset must be [dx_mm, dy_mm]")
    if "panel" in a:
        if not _one_of(a["panel"], panel_ids):
            p.append(f"{where}.panel {a['panel']!r} is not a panel of this figure")
        if "part" in a:
            if not isinstance(a["part"], str) or not a["part"]:
                p.append(f"{where}.part must be a part name")
            if not _one_of(a.get("at", "center"), ANCHOR_POSITIONS):
                p.append(f"{where}.at must be one of {sorted(ANCHOR_POSITIONS)}")
        elif "data" in a:
            if not isinstance(a.get("axes"), str):
                p.append(f"{where}.axes (an axes name) is required with data")
            d = a["data"]
            if not (isinstance(d, list) and len(d) == 2 and all(_is_num(x) for x in d)):
                p.append(f"{where}.data must be [x, y] in data units")
        elif "x" in a or "y" in a:
            if not (_is_num(a.get("x")) and _is_num(a.get("y"))):
                p.append(f"{where} needs numeric x and y (mm from the panel's top-left)")
        else:
            p.append(f"{where} with a panel needs part, data or x/y")
    elif not (_is_num(a.get("x")) and _is_num(a.get("y"))):
        p.append(f"{where} needs x and y in mm, or a panel reference")
    return p


def validate_annotation(a: Any, i: int, panel_ids: set[str]) -> list[str]:
    where = f"annotations[{i}]"
    if not isinstance(a, dict):
        return [f"{where} must be an object"]
    p: list[str] = []
    if not _id_ok(a.get("id")):
        p.append(f"{where}.id must be an id (lowercase letters, digits, - _ .)")
    t = a.get("type")
    if not _one_of(t, ANNOTATION_TYPES):
        p.append(f"{where}.type must be one of {sorted(ANNOTATION_TYPES)}")
        return p
    if t == "text":
        p += validate_anchor(a.get("at"), f"{where}.at", panel_ids)
        if not isinstance(a.get("text"), str):
            p.append(f"{where}.text must be text")
        if not _one_of(a.get("align", "start"), {"start", "middle", "end"}):
            p.append(f"{where}.align must be start, middle or end")
    else:
        p += validate_anchor(a.get("from"), f"{where}.from", panel_ids)
        p += validate_anchor(a.get("to"), f"{where}.to", panel_ids)
    if t in {"arrow", "line"} and not _one_of(a.get("head", "end" if t == "arrow" else "none"),
                                              {"end", "start", "both", "none"}):
        p.append(f"{where}.head must be end, start, both or none")
    if t == "bracket":
        if "label" in a and not isinstance(a["label"], str):
            p.append(f"{where}.label must be text")
        if not _one_of(a.get("side", "above"), {"above", "below"}):
            p.append(f"{where}.side must be above or below")
    style = a.get("style", {})
    if not isinstance(style, dict):
        p.append(f"{where}.style must be an object")
    else:
        for k, v in style.items():
            if k in {"color", "fill"}:
                from .props import is_color

                if not is_color(v):
                    p.append(f"{where}.style.{k} must be a colour")
            elif k in {"width_pt", "size_pt", "gap_mm", "leg_mm", "rotate"}:
                if not _is_num(v):
                    p.append(f"{where}.style.{k} must be a number")
            elif k == "weight":
                if not _one_of(v, {"normal", "bold"}):
                    p.append(f"{where}.style.weight must be normal or bold")
            elif k == "dash":
                if not (isinstance(v, list) and all(_is_num(x) and x >= 0 for x in v)):
                    p.append(f"{where}.style.dash must be a list of lengths in pt")
            else:
                p.append(f"{where}.style.{k} is not an annotation style key")
    return p


def validate_figure(doc: Any, *, expected_id: str | None = None) -> list[str]:
    if not isinstance(doc, dict):
        return ["the file must contain a JSON object"]
    p: list[str] = []
    if doc.get("schema") is None and ("widthPreset" in doc or "namespace" in doc):
        return ["this is a figure.json from SUNA 1.x (no \"schema\": 2). idofig does not convert it: "
                "rebuild the figure with producers (see docs/producers.md); its figure.svg keeps working "
                "in the manuscript until then"]
    # Either schema is read whatever the keys (a 0.3 development build wrote the 0.3 keys under
    # 2, and so does a hand edit); a write gives the file the one it needs (figure_schema), and
    # compose warns about a 2 that needs a 3 until then.
    if doc.get("schema") not in (2, 3):
        p.append(f"schema must be 2 or 3 (found {doc.get('schema')!r})")
    fid = doc.get("id")
    if not _id_ok(fid):
        p.append("id must be a figure id (lowercase letters, digits, - _ .)")
    elif expected_id and fid != expected_id:
        p.append(f"id {fid!r} must equal the directory name {expected_id!r}")
    w = doc.get("width")
    if not isinstance(w, dict) or not (
        ("preset" in w and _one_of(w["preset"], {"single", "onehalf", "double"}) and len(w) == 1)
        or ("mm" in w and _is_num(w["mm"]) and w["mm"] > 0 and len(w) == 1)
    ):
        p.append('width must be {"preset": "single"|"onehalf"|"double"} or {"mm": <number>}')
    if "height" in doc and doc["height"] is not None:
        h = doc["height"]
        if not (isinstance(h, dict) and _is_num(h.get("mm")) and h["mm"] > 0):
            p.append('height must be {"mm": <number>} or absent')
    if "journal" in doc and not isinstance(doc["journal"], str):
        p.append("journal must be a journal id or path")
    if "letters" in doc:
        lt = doc["letters"]
        if not isinstance(lt, dict):
            p.append("letters must be an object")
        else:
            # Every key is checked: an unknown one used to pass and do nothing, so a typo such
            # as "offset" for "offset_mm" looked accepted while the letters never moved.
            for k in sorted(set(lt) - LETTER_KEYS):
                p.append(f"letters.{k} is not a letters key (allowed: {', '.join(sorted(LETTER_KEYS))})")
            if "case" in lt and not _one_of(lt["case"], {"lower", "upper"}):
                p.append("letters.case must be lower or upper")
            if "weight" in lt and not _one_of(lt["weight"], {"normal", "bold"}):
                p.append("letters.weight must be normal or bold")
            if "wrapper" in lt and not _one_of(lt["wrapper"], {"none", "parens", "period"}):
                p.append("letters.wrapper must be none, parens or period")
            if "size_pt" in lt and not (_is_num(lt["size_pt"]) and lt["size_pt"] > 0):
                p.append("letters.size_pt must be a positive number")
            if "show" in lt and not isinstance(lt["show"], bool):
                p.append("letters.show must be true or false")
            if "offset_mm" in lt and not _is_letter_offset(lt["offset_mm"]):
                p.append(f"letters.offset_mm must be [dx, dy] in mm, each within ±{LETTER_OFFSET_MM}")
            if "color" in lt and not is_color(lt["color"]):
                p.append("letters.color must be a colour")

    panels = doc.get("panels", [])
    panel_ids: set[str] = set()
    image_panels: set[str] = set()
    if not isinstance(panels, list):
        p.append("panels must be a list")
        panels = []
    for i, pn in enumerate(panels):
        where = f"panels[{i}]"
        if not isinstance(pn, dict):
            p.append(f"{where} must be an object")
            continue
        pid = pn.get("id")
        if not _id_ok(pid):
            p.append(f"{where}.id must be a panel id (lowercase letters, digits, - _ .)")
        elif pid in panel_ids:
            p.append(f"{where}.id {pid!r} is used twice")
        else:
            panel_ids.add(pid)
        if "letter" in pn and pn["letter"] is not None and not (
            isinstance(pn["letter"], str) and 0 < len(pn["letter"]) <= 3
        ):
            p.append(f"{where}.letter must be a short label such as 'a', or null")
        if "letter_offset_mm" in pn and not _is_letter_offset(pn["letter_offset_mm"]):
            p.append(f"{where}.letter_offset_mm must be [dx, dy] in mm, each within ±{LETTER_OFFSET_MM}")
        place = pn.get("place")
        if not isinstance(place, dict) or not all(_is_num(place.get(k)) for k in ("x", "y", "w", "h")):
            p.append(f"{where}.place must be {{x, y, w, h}} in mm")
        elif place["w"] <= 0 or place["h"] <= 0:
            p.append(f"{where}.place w and h must be positive")
        if "image" in pn:
            if not isinstance(pn["image"], str) or not pn["image"]:
                p.append(f"{where}.image must be a project-relative path")
            elif _id_ok(pid):
                image_panels.add(pid)

    producers = doc.get("producers", [])
    owner: dict[str, str] = {}
    if not isinstance(producers, list):
        p.append("producers must be a list")
        producers = []
    prod_ids: set[str] = set()
    for i, pr in enumerate(producers):
        where = f"producers[{i}]"
        if not isinstance(pr, dict):
            p.append(f"{where} must be an object")
            continue
        prid = pr.get("id")
        if not _id_ok(prid):
            p.append(f"{where}.id must be an id")
        elif prid in prod_ids:
            p.append(f"{where}.id {prid!r} is used twice")
        else:
            prod_ids.add(prid)
        run = pr.get("run")
        if not (isinstance(run, list) and run and all(isinstance(x, str) and x for x in run)):
            p.append(f"{where}.run must be a non-empty list of strings (argv), e.g. [\"python\", \"figures/x/make.py\"]")
        inputs = pr.get("inputs", [])
        if not (isinstance(inputs, list) and all(isinstance(x, str) and x for x in inputs)):
            p.append(f"{where}.inputs must be a list of project-relative paths or globs")
        else:
            for x in inputs:
                if x.startswith("/") or ".." in Path(x).parts:
                    p.append(f"{where}.inputs {x!r} must be inside the project (relative, no '..')")
        outs = pr.get("panels")
        if not (isinstance(outs, list) and outs and all(isinstance(x, str) for x in outs)):
            p.append(f"{where}.panels must list the panel ids this producer draws")
            outs = []
        for x in outs:
            if x not in panel_ids:
                p.append(f"{where}.panels names {x!r}, which is not in panels")
            elif x in image_panels:
                p.append(f"{where}.panels names {x!r}, which is an image panel")
            elif x in owner:
                p.append(f"panel {x!r} is drawn by two producers ({owner[x]!r} and {prid!r})")
            else:
                owner[x] = str(prid)
        if not _one_of(pr.get("cost", "cheap"), {"cheap", "expensive"}):
            p.append(f"{where}.cost must be cheap or expensive")
        if "timeout_s" in pr and not (_is_num(pr["timeout_s"]) and pr["timeout_s"] > 0):
            p.append(f"{where}.timeout_s must be a positive number")

    anns = doc.get("annotations", [])
    if not isinstance(anns, list):
        p.append("annotations must be a list")
        anns = []
    ann_ids: set[str] = set()
    for i, a in enumerate(anns):
        p += validate_annotation(a, i, panel_ids)
        if isinstance(a, dict) and isinstance(a.get("id"), str):
            if a["id"] in ann_ids:
                p.append(f"annotations[{i}].id {a['id']!r} is used twice")
            ann_ids.add(a["id"])
    return p


def figure_schema(doc: dict) -> int:
    """The schema a figure.json is written with: 3 when it uses a key an idofig older than 0.3
    would ignore without a word (a panel's `letter_offset_mm`, `letters.color`), else 2. Under
    2, two 0.2.2 servers left running redrew five figures' letters at the figure-wide place, in
    black, and called them fresh; 0.2.x refuses a 3. A key like those goes on this list."""
    uses_3 = "color" in doc.get("letters", {}) or any("letter_offset_mm" in pn for pn in doc.get("panels", []))
    return 3 if uses_3 else 2


def load_figure(path: Path | str, *, expected_id: str | None = None) -> dict:
    path = Path(path)
    try:
        doc = read_json(path)  # not JSON: a SpecError naming the file
    except FileNotFoundError:
        raise SpecError(path, ["file not found"]) from None
    problems = validate_figure(doc, expected_id=expected_id or path.parent.name)
    if problems:
        raise SpecError(path, problems)
    return doc


def new_figure(figure_id: str, *, width: dict | None = None) -> dict:
    return {
        "schema": FIGURE_SCHEMA,
        "id": figure_id,
        "width": width or {"preset": "double"},
        "producers": [],
        "panels": [],
        "annotations": [],
    }


def producer_of(doc: dict, panel_id: str) -> dict | None:
    for pr in doc.get("producers", []):
        if panel_id in pr.get("panels", []):
            return pr
    return None


def panel_entry(doc: dict, panel_id: str) -> dict | None:
    for pn in doc.get("panels", []):
        if pn.get("id") == panel_id:
            return pn
    return None


# ----------------------------------------------------------------------------- edits


def _find(items: list, key: str, where: str) -> dict:
    for it in items:
        if isinstance(it, dict) and it.get("id") == key:
            return it
    raise SpecError("figure.json", [f"{where} {key!r} does not exist"])


def apply_ops(doc: dict, ops: list[dict], width_of: Callable[[dict], float] | None = None) -> dict:
    """Apply edit operations to a copy of ``doc``. Validation happens after, on the result.

    ``width_of`` resolves a document's width to millimetres (it needs the journal); with it,
    a ``width`` op scales the layout to the new width (see ``_scale_layout``)."""
    if not isinstance(ops, list) or not all(isinstance(op, dict) for op in ops):
        raise SpecError("figure.json", ["ops must be a list of objects"])
    try:
        return _apply_ops(doc, ops, width_of)
    except KeyError as exc:
        raise SpecError("figure.json", [f"operation is missing the field {exc.args[0]!r}"]) from None
    except NotJSONError:  # the journal preset a `width` op reads (width_of) names itself, not a bad operation
        raise
    except (TypeError, ValueError, OverflowError) as exc:  # OverflowError: a `place` of 10**400 mm
        raise SpecError("figure.json", [f"bad operation: {exc}"]) from None


# The fields each operation takes. A misspelt field is refused rather than ignored: an edit
# sent as {"op": "annotation.update", "set": …} used to succeed and change nothing, which is
# the silent kind of wrong an agent cannot see.
OP_FIELDS: dict[str, set[str]] = {
    "place": {"panel", "x", "y", "w", "h"},
    "letter": {"panel", "letter", "offset_mm"},
    "panel.add": {"id", "letter", "place", "image"},
    "panel.remove": {"id"},
    "producer.set": {"id", "run", "inputs", "panels", "cost", "timeout_s"},
    "producer.remove": {"id"},
    "annotation.add": {"annotation"},
    "annotation.update": {"id", "patch"},
    "annotation.remove": {"id"},
    "width": {"preset", "mm", "scale_panels"},
    "height": {"mm"},
    "letters": {"patch"},
    "journal": {"journal"},
    "app.set": {"key", "value"},
}


def _check_op_fields(op: dict) -> None:
    kind = op.get("op")
    allowed = OP_FIELDS.get(kind)  # type: ignore[arg-type]
    if allowed is None:
        raise SpecError("figure.json", [f"unknown operation {kind!r}"])
    extra = sorted(k for k in op if k != "op" and k not in allowed)
    if extra:
        raise SpecError("figure.json", [
            f"operation {kind!r} does not take {', '.join(repr(k) for k in extra)}; "
            f"it takes {', '.join(sorted(allowed))}"])


def _scale_layout(doc: dict, r: float) -> None:
    """Scale the layout horizontally by ``r``: every panel's x and w, and the x of every
    point anchor (a free point, or a point in a panel). Part and data anchors follow their
    part by themselves. Panels whose width changes are redrawn by the next build."""
    for pn in doc.get("panels", []):
        place = dict(pn.get("place", {}))
        for k in ("x", "w"):
            if k in place:
                place[k] = round(float(place[k]) * r, 3)
        pn["place"] = place
    for a in doc.get("annotations", []):
        for key in ("at", "from", "to"):
            anchor = a.get(key)
            if isinstance(anchor, dict) and "x" in anchor and "part" not in anchor and "data" not in anchor:
                anchor["x"] = round(float(anchor["x"]) * r, 3)


def _apply_ops(doc: dict, ops: list[dict], width_of: Callable[[dict], float] | None = None) -> dict:
    for op in ops:
        _check_op_fields(op)
    out = copy.deepcopy(doc)
    out.setdefault("producers", [])
    out.setdefault("panels", [])
    out.setdefault("annotations", [])
    for op in ops:
        kind = op.get("op")
        if kind == "place":
            pn = _find(out["panels"], op["panel"], "panel")
            place = dict(pn.get("place", {}))
            for k in ("x", "y", "w", "h"):
                if k in op:
                    place[k] = round(float(op[k]), 3)
            pn["place"] = place
        elif kind == "letter":
            # Only the fields sent change: read as null, a missing `letter` removed the letter.
            if "letter" not in op and "offset_mm" not in op:
                raise SpecError("figure.json", ["operation 'letter' needs letter, offset_mm or both"])
            pn = _find(out["panels"], op["panel"], "panel")
            if "letter" in op:
                if op["letter"] is None:
                    pn.pop("letter", None)
                else:
                    pn["letter"] = op["letter"]
            if "offset_mm" in op:
                off = op["offset_mm"]
                if off is None:
                    pn.pop("letter_offset_mm", None)
                else:  # rounded to µm like `place`; anything that is not [dx, dy] fails validation
                    pn["letter_offset_mm"] = [round(v, 3) for v in off] if _is_pair(off) else copy.deepcopy(off)
        elif kind == "panel.add":
            entry = {k: op[k] for k in ("id", "letter", "place", "image") if k in op}
            out["panels"].append(entry)
        elif kind == "panel.remove":
            _find(out["panels"], op["id"], "panel")
            out["panels"] = [p for p in out["panels"] if p.get("id") != op["id"]]
            for pr in out["producers"]:
                pr["panels"] = [x for x in pr.get("panels", []) if x != op["id"]]
            out["producers"] = [pr for pr in out["producers"] if pr.get("panels")]
        elif kind == "producer.set":
            entry = {k: op[k] for k in ("id", "run", "inputs", "panels", "cost", "timeout_s") if k in op}
            existing = [pr for pr in out["producers"] if pr.get("id") == entry.get("id")]
            if existing:
                existing[0].update(entry)
            else:
                out["producers"].append(entry)
        elif kind == "producer.remove":
            _find(out["producers"], op["id"], "producer")
            out["producers"] = [pr for pr in out["producers"] if pr.get("id") != op["id"]]
        elif kind == "annotation.add":
            out["annotations"].append(copy.deepcopy(op["annotation"]))
        elif kind == "annotation.update":
            a = _find(out["annotations"], op["id"], "annotation")
            for k, v in op.get("patch", {}).items():
                if k == "id":
                    continue
                if v is None:
                    a.pop(k, None)
                else:
                    a[k] = copy.deepcopy(v)
        elif kind == "annotation.remove":
            _find(out["annotations"], op["id"], "annotation")
            out["annotations"] = [a for a in out["annotations"] if a.get("id") != op["id"]]
        elif kind == "width":
            # A figure made narrower keeps its layout: panels are scaled to the new width
            # (and redrawn at it) unless the caller places them itself (scale_panels: false).
            # Left alone, a double-column layout set to one column hangs 90 mm past its edge.
            old = width_of(out) if width_of and op.get("scale_panels", True) else None
            out["width"] = {"preset": op["preset"]} if "preset" in op else {"mm": op["mm"]}
            if old:
                new = width_of(out)
                if abs(new - old) > 1e-9:
                    _scale_layout(out, new / old)
        elif kind == "height":
            if op.get("mm") is None:
                out.pop("height", None)
            else:
                out["height"] = {"mm": op["mm"]}
        elif kind == "letters":
            lt = dict(out.get("letters", {}))
            for k, v in op.get("patch", {}).items():
                if v is None:
                    lt.pop(k, None)
                else:
                    lt[k] = v
            if lt:
                out["letters"] = lt
            else:
                out.pop("letters", None)
        elif kind == "journal":
            if op.get("journal") is None:
                out.pop("journal", None)
            else:
                out["journal"] = op["journal"]
        elif kind == "app.set":
            key = op["key"]
            if key in OWNED_KEYS:
                raise SpecError("figure.json", [f"{key!r} is owned by idofig; use its own operation"])
            if op.get("value") is None:
                out.pop(key, None)
            else:
                out[key] = copy.deepcopy(op["value"])
        else:
            raise SpecError("figure.json", [f"unknown operation {kind!r}"])
    return out


def update_figure(path: Path | str, ops: list[dict],
                  width_of: Callable[[dict], float] | None = None) -> tuple[dict, dict]:
    """Read fresh, apply ``ops``, validate, write atomically. Returns (before, after)."""
    path = Path(path)
    before = load_figure(path)
    after = apply_ops(before, ops, width_of)
    problems = validate_figure(after, expected_id=path.parent.name)
    if problems:
        raise SpecError(path, problems)
    after["schema"] = figure_schema(after)  # on a valid figure; 2 or 3 is valid either way
    if after != before:
        write_json(path, after)
    return before, after


# ----------------------------------------------------------------------------- style.json


def validate_style(doc: Any) -> list[str]:
    if not isinstance(doc, dict):
        return ["the file must contain a JSON object"]
    p: list[str] = []
    if doc.get("schema") != STYLE_SCHEMA:
        p.append(f"schema must be {STYLE_SCHEMA}")
    parts = doc.get("parts", {})
    if not isinstance(parts, dict):
        return p + ["parts must be an object mapping part names to properties"]
    for name, props in parts.items():
        if not PART_NAME_RE.match(name):
            p.append(f"part name {name!r} is not valid")
        if not isinstance(props, dict) or not props:
            p.append(f"parts[{name!r}] must be a non-empty object of properties")
            continue
        for k, v in props.items():
            if not isinstance(v, (str, int, float, bool)):
                p.append(f"parts[{name!r}].{k} must be a string, number or boolean")
            elif not isinstance(v, (str, bool)) and not is_finite_number(v):
                # Here, where every write passes (the property check runs only on a part the
                # manifest names): `dx_mm=nan` on a wildcard reached the file, and every workspace
                # reply carried a NaN JSON.parse rejects; a 400-digit int came back as null.
                p.append(f"parts[{name!r}].{k} must be a finite number")
    return p


def load_style(path: Path | str) -> dict:
    """The style file, or an empty one when it does not exist."""
    path = Path(path)
    if not path.exists():
        return {"schema": STYLE_SCHEMA, "parts": {}}
    doc = read_json(path)  # not JSON: a SpecError naming the file
    problems = validate_style(doc)
    if problems:
        raise SpecError(path, problems)
    doc.setdefault("parts", {})
    return doc


def move_style(path: Path | str, old: str, new: str) -> tuple[dict, dict]:
    """Re-attach ``old``'s overrides to ``new`` — how a detached override (its part was
    renamed by a script change) is put back to work. Moved properties win over ones ``new``
    already had. Read fresh, validate, write atomically."""
    path = Path(path)
    before = load_style(path)
    parts = before.get("parts", {})
    if old not in parts:
        raise SpecError(path, [f"there are no overrides for {old!r}"])
    if old == new:
        return before, before
    after = copy.deepcopy(before)
    moved = after["parts"].pop(old)
    merged = dict(after["parts"].get(new, {}))
    merged.update(moved)
    after["parts"][new] = merged
    problems = validate_style(after)
    if problems:
        raise SpecError(path, problems)
    write_json(path, after)
    return before, after


def update_style(path: Path | str, part: str, props: dict | None) -> tuple[dict, dict]:
    """Merge ``props`` into one part's overrides (a ``None`` value removes that property;
    ``props=None`` removes the part's overrides). Read fresh, validate, write atomically."""
    path = Path(path)
    before = load_style(path)
    after = copy.deepcopy(before)
    parts = after.setdefault("parts", {})
    if props is None:
        parts.pop(part, None)
    else:
        cur = dict(parts.get(part, {}))
        for k, v in props.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        if cur:
            parts[part] = cur
        else:
            parts.pop(part, None)
    problems = validate_style(after)
    if problems:
        raise SpecError(path, problems)
    if after != before:
        if parts:
            write_json(path, after)
        elif path.exists():
            write_json(path, after)
    return before, after
