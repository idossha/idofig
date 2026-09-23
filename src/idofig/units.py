"""Physical units. One SVG user unit in every idofig file is one typographic point."""

MM_PER_IN = 25.4
PT_PER_IN = 72.0
PT_PER_MM = PT_PER_IN / MM_PER_IN


def mm_to_pt(mm: float) -> float:
    return mm * PT_PER_MM


def pt_to_mm(pt: float) -> float:
    return pt / PT_PER_MM


def mm_to_in(mm: float) -> float:
    return mm / MM_PER_IN


def fmt(x: float, places: int = 3) -> str:
    """A number as short, deterministic SVG text: rounded, no trailing zeros, no '-0'."""
    r = round(float(x), places)
    if r == 0:
        return "0"
    s = f"{r:.{places}f}".rstrip("0").rstrip(".")
    return s
