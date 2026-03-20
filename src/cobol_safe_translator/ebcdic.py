"""EBCDIC and custom collation support for mainframe COBOL programs.

Uses Python's built-in cp037 codec (IBM EBCDIC US/Canada) — zero external deps.
EBCDIC sorts: special chars < lowercase < uppercase < digits,
unlike ASCII which sorts: digits < uppercase < lowercase.

Also supports custom ALPHABET definitions from COBOL SPECIAL-NAMES:
  ALPHABET MY-ALPHA IS "ABCD..." — literal collation sequence
  ALPHABET EBCDIC-SEQ IS EBCDIC  — named standard
"""

from __future__ import annotations


def ebcdic_key(s: str) -> bytes:
    """Return EBCDIC-encoded bytes for use as a sort/comparison key.

    Characters that can't be encoded in cp037 are replaced with b'?'.
    """
    return s.encode("cp037", errors="replace")


def build_collation_table(definition: str) -> dict[str, int]:
    """Build a character-to-sort-weight mapping from an ALPHABET definition.

    Supports:
      - "EBCDIC" / "STANDARD-1" / "STANDARD-2" / "NATIVE" — named standards
      - Quoted literal sequence — characters sorted in given order
    """
    upper_def = definition.upper().strip()
    if upper_def in ("NATIVE", ""):
        return {}  # empty = use default ASCII sort
    if upper_def in ("EBCDIC",):
        # Pre-built EBCDIC sort weight table for printable ASCII
        return {chr(i): ebcdic_key(chr(i))[0] for i in range(32, 127)}
    if upper_def in ("STANDARD-1",):
        return {}  # ASCII is default
    if upper_def in ("STANDARD-2",):
        # ISO 646 — effectively ASCII for printable range
        return {}

    # Literal sequence: strip quotes and build ordinal mapping
    seq = definition.strip("'\"")
    return {ch: idx for idx, ch in enumerate(seq)}


def custom_collation_key(s: str, table: dict[str, int]) -> tuple[int, ...]:
    """Return a sort key using a custom collation table.

    Characters not in the table sort after all mapped characters.
    """
    fallback = len(table) + 256
    return tuple(table.get(ch, fallback + ord(ch)) for ch in s)
