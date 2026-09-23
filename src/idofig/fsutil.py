"""Small file helpers shared by every module: atomic writes, canonical JSON, hashing.

Nothing here imports matplotlib; the build engine and the server stay fast.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any


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


def dump_json(obj: Any) -> str:
    """Canonical JSON for files people diff: 2-space indent, UTF-8, trailing newline."""
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def write_json(path: Path | str, obj: Any) -> None:
    write_atomic(path, dump_json(obj))


def read_json(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


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
