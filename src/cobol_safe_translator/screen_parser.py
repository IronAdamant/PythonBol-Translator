"""SCREEN SECTION parser for COBOL source.

Parses SCREEN SECTION definitions into ScreenField trees with support
for LINE, COLUMN, VALUE, PIC, USING/FROM/TO clauses, BLANK SCREEN,
display attributes, and foreground/background colors.
"""

from __future__ import annotations

import re

from .models import ScreenField
from .parser import _level_hierarchy, _LEVEL_RE, _SECTION_BOUNDARIES

# --- SCREEN SECTION regex constants ---

_SCREEN_LINE_RE = re.compile(r"\bLINE\s+(?:NUMBER\s+(?:IS\s+)?)?(\d+)", re.IGNORECASE)
_SCREEN_COL_RE = re.compile(r"\b(?:COL(?:UMN)?)\s+(?:NUMBER\s+(?:IS\s+)?)?(\d+)", re.IGNORECASE)
_SCREEN_VALUE_RE = re.compile(r"""\bVALUE\s+(?:IS\s+)?("[^"]*"|'[^']*')""", re.IGNORECASE)
_SCREEN_PIC_RE = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(S?[0-9XAVZBS().,+\-$CRDB*P/]+)", re.IGNORECASE)
_SCREEN_USING_RE = re.compile(r"\bUSING\s+([\w-]+)", re.IGNORECASE)
_SCREEN_FROM_RE = re.compile(r"\bFROM\s+([\w-]+)", re.IGNORECASE)
_SCREEN_TO_RE = re.compile(r"\bTO\s+([\w-]+)", re.IGNORECASE)
_SCREEN_BLANK_RE = re.compile(r"\bBLANK\s+SCREEN\b", re.IGNORECASE)
_SCREEN_ATTRS = (
    "HIGHLIGHT", "LOWLIGHT", "BLINK", "REVERSE-VIDEO", "UNDERLINE",
    "SECURE", "AUTO", "REQUIRED", "FULL", "BELL",
)
_SCREEN_FG_RE = re.compile(r"\bFOREGROUND-COLO(?:U)?R\s+(?:IS\s+)?(\d+)", re.IGNORECASE)
_SCREEN_BG_RE = re.compile(r"\bBACKGROUND-COLO(?:U)?R\s+(?:IS\s+)?(\d+)", re.IGNORECASE)

# Keywords that appear directly after a level number and should NOT be
# treated as the field name.  When the parser sees "05 LINE 1 ..." the
# second token is "LINE" which is a clause keyword, not a name.
_SCREEN_CLAUSE_KEYWORDS = frozenset({
    "LINE", "COL", "COLUMN", "BLANK", "VALUE", "PIC", "PICTURE",
    "USING", "FROM", "TO", "HIGHLIGHT", "LOWLIGHT", "BLINK",
    "REVERSE-VIDEO", "UNDERLINE", "SECURE", "AUTO", "REQUIRED",
    "FULL", "BELL", "FOREGROUND-COLOR", "FOREGROUND-COLOUR",
    "BACKGROUND-COLOR", "BACKGROUND-COLOUR", "FILLER",
})


def _merge_screen_continuations(lines: list[str]) -> list[str]:
    """Merge continuation lines (those without a leading level number) into
    the preceding entry so that multi-line screen field definitions are
    parsed as a single string."""
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _LEVEL_RE.match(stripped):
            merged.append(stripped)
        elif merged:
            # Continuation -- append to the previous entry
            merged[-1] = merged[-1].rstrip(".") + " " + stripped
    return merged


def parse_screen_section(lines: list[str]) -> list[ScreenField]:
    """Parse SCREEN SECTION lines into a list of ScreenField trees.

    Each 01-level entry becomes a root ScreenField with nested children
    built from level numbers (same hierarchy approach as data items).
    """
    flat: list[ScreenField] = []

    for line in _merge_screen_continuations(lines):
        stripped = line.strip()
        if not stripped:
            continue

        # Match level number + name
        level_m = _LEVEL_RE.match(stripped)
        if not level_m:
            continue

        level = int(level_m.group(1))
        raw_name = level_m.group(2).strip().upper().rstrip(".")
        # If the token after the level number is a clause keyword,
        # this is an unnamed field (e.g. "05 LINE 1 COL 1 ...")
        if raw_name in _SCREEN_CLAUSE_KEYWORDS:
            name = ""
        else:
            name = raw_name

        sf = ScreenField(level=level, name=name)

        # LINE clause
        line_m = _SCREEN_LINE_RE.search(stripped)
        if line_m:
            sf.line = int(line_m.group(1))

        # COLUMN clause
        col_m = _SCREEN_COL_RE.search(stripped)
        if col_m:
            sf.column = int(col_m.group(1))

        # VALUE clause
        val_m = _SCREEN_VALUE_RE.search(stripped)
        if val_m:
            raw_val = val_m.group(1)
            sf.value = raw_val[1:-1]  # strip quotes

        # PIC clause
        pic_m = _SCREEN_PIC_RE.search(stripped)
        if pic_m:
            sf.pic = pic_m.group(1).strip().rstrip(".")

        # USING clause
        using_m = _SCREEN_USING_RE.search(stripped)
        if using_m:
            sf.using = using_m.group(1).upper()

        # FROM clause
        from_m = _SCREEN_FROM_RE.search(stripped)
        if from_m:
            sf.from_field = from_m.group(1).upper()

        # TO clause (only if not part of FOREGROUND-/BACKGROUND-COLOR)
        to_m = _SCREEN_TO_RE.search(stripped)
        if to_m:
            # Ensure this TO is not inside a COLOR clause
            to_pos = to_m.start()
            preceding = stripped[:to_pos].upper()
            if not preceding.rstrip().endswith(("FOREGROUND-COLOR", "FOREGROUND-COLOUR",
                                                "BACKGROUND-COLOR", "BACKGROUND-COLOUR")):
                sf.to_field = to_m.group(1).upper()

        # BLANK SCREEN
        if _SCREEN_BLANK_RE.search(stripped):
            sf.blank_screen = True

        # Display attributes
        upper_stripped = stripped.upper()
        for attr in _SCREEN_ATTRS:
            if attr in upper_stripped:
                sf.attributes.append(attr)

        # Foreground/background color
        fg_m = _SCREEN_FG_RE.search(stripped)
        if fg_m:
            sf.attributes.append(f"FOREGROUND-COLOR {fg_m.group(1)}")
        bg_m = _SCREEN_BG_RE.search(stripped)
        if bg_m:
            sf.attributes.append(f"BACKGROUND-COLOR {bg_m.group(1)}")

        flat.append(sf)

    return _level_hierarchy(flat)


def _extract_screen_lines(data_lines: list[str]) -> list[str]:
    """Extract SCREEN SECTION lines from DATA DIVISION lines.

    Returns only the content lines inside the SCREEN SECTION (not the
    header itself).  Used by _parse_single_program to feed the screen
    parser without changing parse_data_division's return type.
    """
    screen_lines: list[str] = []
    in_screen = False
    for line in data_lines:
        upper = line.strip().upper()
        if "SCREEN SECTION" in upper:
            in_screen = True
            continue  # skip the header line
        if in_screen and any(kw in upper for kw in _SECTION_BOUNDARIES):
            in_screen = False
        if in_screen:
            screen_lines.append(line)
    return screen_lines
