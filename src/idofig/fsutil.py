"""Small file helpers shared by every module: atomic writes, canonical JSON, hashing.

Nothing here imports matplotlib; the build engine and the server stay fast.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from .errors import NotJSONError, SpecError


def write_atomic(path: Path | str, data: str | bytes) -> None:
    """Write ``data`` to ``path`` via a temp file in the same directory and ``os.replace``.

    A reader never sees a half-written file, and a crash leaves the old file intact.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


# JSON has no NaN or Infinity, though Python's json reads and writes them: a reply carrying one
# is a line JSON.parse refuses, and SUNA waited for it. idofig writes none, and reads a file
# with one (or with a number too large for a float, `1e999`) as invalid JSON, naming the file.


def dump_json(obj: Any) -> str:
    """Canonical JSON for files people diff: 2-space indent, UTF-8, trailing newline."""
    return json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_json(path: Path | str, obj: Any) -> None:
    try:
        text = dump_json(obj)
    except ValueError as exc:  # a NaN where nothing checks numbers (figure.json's `app.set`)
        raise SpecError(path, [f"not JSON: {exc}"]) from None
    write_atomic(path, text)


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{text} is too large for a number")
    return value


def loads(text: str) -> Any:
    """``json.loads``, refusing NaN, Infinity and a number too large for a float (ValueError)."""
    return json.loads(text, parse_constant=_no_constant, parse_float=_finite)


def read_json(path: Path | str) -> Any:
    """A JSON file, read strictly (:func:`loads`). One that is not JSON is a ``NotJSONError``
    naming it (a ValueError too): unnamed, `parts`, `style` and `locate` ended in a traceback
    on a manifest idofig 0.2.2 wrote with a NaN in it."""
    try:
        with open(path, encoding="utf-8") as fh:
            return loads(fh.read())
    except ValueError as exc:  # UnicodeDecodeError too
        raise NotJSONError(path, [f"not valid JSON: {exc}"]) from None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SHA_CACHE: dict[str, tuple[tuple[int, int, int], str]] = {}
_SETTLE_NS = 2_000_000_000


def sha256_file(path: Path | str) -> str | None:
    """The file's sha256, or None when it does not exist.

    ``status`` hashes every input of every producer, and a server calls it after each
    file change, so digests are cached by (size, mtime, inode). A file modified in the
    last two seconds is always re-read: some filesystems keep mtimes to the second, and
    two same-size edits inside one tick must not look like one.
    """
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISDIR(st.st_mode):
        return None
    key = os.path.abspath(path)
    sig = (st.st_size, st.st_mtime_ns, st.st_ino)
    hit = _SHA_CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except (FileNotFoundError, IsADirectoryError):
        return None
    digest = h.hexdigest()
    if time.time_ns() - st.st_mtime_ns > _SETTLE_NS:
        if len(_SHA_CACHE) > 20000:
            _SHA_CACHE.clear()
        _SHA_CACHE[key] = (sig, digest)
    return digest


def sha256_json(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def rel(path: Path, root: Path) -> str:
    """``path`` relative to ``root`` in POSIX form (what every idofig file stores)."""
    return Path(os.path.relpath(path, root)).as_posix()
