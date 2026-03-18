"""PIC clause parsing utilities for COBOL data items.

Handles expansion of PIC shorthand (e.g., 9(5) -> 99999),
classification into categories, and size computation.
"""

from __future__ import annotations

import re

from .models import PicCategory, PicClause

# --- PIC parsing ---

_PIC_REPEAT = re.compile(r"(CR|DB|[A9XZVBS,.\-+$P/])\((\d+)\)", re.IGNORECASE)


def expand_pic(raw: str) -> str:
    """Expand PIC shorthand: 9(5) -> 99999, X(3) -> XXX, etc."""
    result = raw.upper().strip()
    # Remove leading PIC/PICTURE keyword if present
    for prefix in ("PIC ", "PICTURE "):
        if result.startswith(prefix):
            result = result[len(prefix):]
            break

    def _expand(m: re.Match) -> str:
        char = m.group(1)
        count = int(m.group(2))
        return char * count

    return _PIC_REPEAT.sub(_expand, result)


def classify_pic(expanded: str) -> PicCategory:
    """Determine the PIC category from an expanded PIC string."""
    upper = expanded.upper()
    has_nine = "9" in upper
    has_x = "X" in upper
    has_a = "A" in upper
    has_edit = any(tok in upper for tok in ("CR", "DB")) or any(c in upper for c in "ZB,.+-$")

    if has_edit:
        return PicCategory.EDITED
    if has_x and not has_nine:
        return PicCategory.ALPHANUMERIC
    if has_a and not has_nine and not has_x:
        return PicCategory.ALPHABETIC
    if has_nine and not has_x and not has_a:
        return PicCategory.NUMERIC
    if has_x:
        return PicCategory.ALPHANUMERIC
    return PicCategory.UNKNOWN


def compute_pic_size(expanded: str) -> tuple[int, int, bool]:
    """Return (total_size, decimal_places, is_signed) from expanded PIC."""
    upper = expanded.upper()
    signed = "S" in upper

    # Remove sign character for size calculation
    clean = upper.replace("S", "")

    # Count decimals (digits after V)
    decimals = 0
    if "V" in clean:
        _, after_v = clean.split("V", 1)
        decimals = after_v.count("9")

    # Handle CR/DB as 2-position editing symbols before char loop
    cr_db_extra = clean.count("CR") + clean.count("DB")
    # Remove CR and DB for per-character counting to avoid double-counting
    count_clean = clean.replace("CR", "").replace("DB", "")

    size = cr_db_extra * 2  # Each CR/DB occupies 2 display positions
    for c in count_clean:
        if c != "V":  # V is implied decimal, no display position
            size += 1
    return size, decimals, signed


def parse_pic(raw: str) -> PicClause:
    """Parse a PIC clause string into a PicClause dataclass."""
    expanded = expand_pic(raw)
    category = classify_pic(expanded)
    size, decimals, signed = compute_pic_size(expanded)
    return PicClause(
        raw=raw.strip(),
        expanded=expanded,
        category=category,
        size=size,
        decimals=decimals,
        signed=signed,
    )
