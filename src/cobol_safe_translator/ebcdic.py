"""EBCDIC collation support for mainframe COBOL programs.

Uses Python's built-in cp037 codec (IBM EBCDIC US/Canada) — zero external deps.
EBCDIC sorts: special chars < lowercase < uppercase < digits,
unlike ASCII which sorts: digits < uppercase < lowercase.

Opt-in only via --ebcdic CLI flag.
"""

from __future__ import annotations


def ebcdic_key(s: str) -> bytes:
    """Return EBCDIC-encoded bytes for use as a sort/comparison key.

    Characters that can't be encoded in cp037 are replaced with b'?'.
    """
    return s.encode("cp037", errors="replace")
