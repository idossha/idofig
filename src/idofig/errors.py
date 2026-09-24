"""Every error idofig raises on purpose is an ``IdofigError``.

Messages are written for a person (or an agent) who has to fix something: they
name the file, the panel or the part, and say what to do next.
"""


class IdofigError(Exception):
    """Base class for errors idofig raises deliberately."""


class SpecError(IdofigError):
    """A figure.json / style.json file is malformed or violates the spec."""

    def __init__(self, path, problems):
        self.path = str(path)
        self.problems = list(problems)
        lines = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(f"{self.path} is not valid:\n{lines}")


class NotJSONError(SpecError, ValueError):
    """A file idofig reads is not JSON (``fsutil.read_json``). A ValueError too, so a reader that
    goes on without a file it cannot read (a manifest, the lock) still does."""


class ContextError(IdofigError):
    """idofig could not tell which project, figure or panel a call belongs to."""


class NameCollisionError(IdofigError):
    """Two parts an author named explicitly ended up with the same name."""


class ProducerError(IdofigError):
    """A producer script failed or did not write what it declared."""
