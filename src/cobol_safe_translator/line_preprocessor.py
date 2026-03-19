"""Line-level preprocessing for COBOL source text.

Handles format detection (fixed vs free), column stripping, continuation
line merging, and comment filtering.  Produces logical lines suitable for
the division splitter and downstream parsers.
"""

from __future__ import annotations

import re


# --- Format detection ---

def _detect_free_format(raw_text: str) -> bool:
    """Detect whether COBOL source uses free-format (no column-7 layout).

    Heuristics (positive = free, negative = fixed):
    - Free-format uses *> for comments (anywhere on line)
    - Free-format has division headers starting in cols 1-6
    - Fixed-format has sequence numbers in cols 1-6 and indicator in col 7
    - Fixed-format has identifier content in cols 73-80 (e.g., 'IF1014.2')

    When scores are tied, checks for structural fixed-format markers across
    the entire file. Files with no sequence numbers, no col-7 indicators,
    and no identification-area content default to free-format to avoid
    incorrectly stripping code that overflows into column 73+.
    """
    lines = raw_text.splitlines()
    free_score = 0
    fixed_score = 0
    checked = 0

    for line in lines[:80]:  # check first 80 lines
        if not line.strip():
            continue
        checked += 1

        # Strong free-format indicator: *> comment anywhere
        stripped = line.lstrip()
        if stripped.startswith("*>"):
            free_score += 3
            continue

        # Inline *> comment (after code)
        if " *>" in line:
            free_score += 2

        # Division/section headers in cols 1-6 (free-format)
        if re.match(r"^\s{0,6}(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION",
                     line, re.IGNORECASE):
            leading = len(line) - len(line.lstrip())
            if leading < 7:
                free_score += 2

        # Fixed-format indicators: col 7 markers and cols 1-6 content
        if len(line) > 6:
            cols16 = line[:6]
            col7 = line[6]
            if col7 in ("*", "-", "/", "D", "d") and (cols16.strip() == "" or cols16.strip().isdigit()):
                fixed_score += 2
            elif cols16.strip().isdigit() and col7 == " ":
                fixed_score += 1
            elif col7 == " " and cols16.strip() and not cols16.strip().isdigit():
                # Non-digit content in cols 1-6 with space in col 7
                fixed_score += 1

    if checked == 0:
        return False
    if free_score > fixed_score:
        return True
    if fixed_score > free_score:
        return False

    # Scores tied -- look for structural fixed-format markers across the file
    # to break the tie. Check for sequence numbers or identification areas.
    has_seq_numbers = False
    has_ident_area = False
    for line in lines:
        if not line.strip():
            continue
        if len(line) >= 6 and line[:6].strip().isdigit() and line[:6].strip():
            has_seq_numbers = True
            break
        if len(line) > 72 and line[72:].strip():
            has_ident_area = True
            break

    # If the file has sequence numbers or identification areas, it's fixed-format
    if has_seq_numbers or has_ident_area:
        return False
    # No fixed-format structural markers found -- treat as free-format
    return True


# --- Preprocessing ---

def _preprocess_free_format(raw_text: str) -> list[str]:
    """Preprocess free-format COBOL source into logical lines.

    Free-format COBOL:
    - No sequence numbers (cols 1-6)
    - No indicator area (col 7)
    - Comments use *> (can appear anywhere on line)
    - No column 72 limit
    - Continuation uses & at end of line (rare; we handle simple cases)
    """
    logical: list[str] = []

    for line in raw_text.splitlines():
        # Strip inline comments (*> to end of line, but not inside literals)
        content = _strip_free_comment(line).rstrip()
        if not content:
            continue

        # Skip full-line comments
        stripped = content.lstrip()
        if stripped.startswith("*"):
            continue

        logical.append(stripped)

    return logical


def _strip_free_comment(line: str) -> str:
    """Remove *> inline comments from a line, respecting string literals."""
    in_quote: str | None = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == '*' and i + 1 < len(line) and line[i + 1] == '>':
            return line[:i]
        i += 1
    return line


def preprocess_lines(raw_text: str) -> list[str]:
    """Strip sequence numbers (cols 1-6), indicator area (col 7), and cols 73+.

    Auto-detects free-format COBOL and uses appropriate preprocessing.
    Handles continuation lines and filters comment lines.
    Returns logical lines (continuations merged).
    """
    if _detect_free_format(raw_text):
        return _preprocess_free_format(raw_text)

    physical = raw_text.splitlines()
    logical: list[str] = []
    i = 0
    while i < len(physical):
        line = physical[i].expandtabs(8) if "\t" in physical[i] else physical[i]
        if len(line) < 7:
            # Too short to have content area
            i += 1
            continue

        indicator = line[6]

        # Comment or debug lines -- skip
        if indicator in ("*", "/", "D", "d"):
            i += 1
            continue

        # Content area: cols 8-72 (indices 7..72)
        content = line[7:72].rstrip() if len(line) > 7 else ""

        if not content:
            i += 1
            continue

        # Check if next line is a continuation
        merged = content
        while i + 1 < len(physical):
            next_line = physical[i + 1]
            if len(next_line) > 6 and next_line[6] == "-":
                # Continuation: strip leading spaces from content area
                cont_content = next_line[7:72].rstrip() if len(next_line) > 7 else ""
                # Merge continuation -- preserve a space to avoid fusing tokens
                stripped_prev = merged.rstrip()
                stripped_cont = cont_content.lstrip()
                # Detect if prev line has an unclosed string literal
                in_literal = False
                if stripped_cont and stripped_cont[0] in ('"', "'"):
                    quote = stripped_cont[0]
                    # Count unescaped quotes in prev -- odd means unclosed literal
                    if stripped_prev.count(quote) % 2 == 1:
                        in_literal = True
                # Also handle the old case: prev ends with quote AND cont starts with quote
                # (e.g., both closed -- strip both to merge)
                if not in_literal:
                    in_literal = (
                        (stripped_prev.endswith('"') and stripped_cont.startswith('"'))
                        or (stripped_prev.endswith("'") and stripped_cont.startswith("'"))
                    )
                if in_literal and stripped_cont and stripped_cont[0] in ('"', "'"):
                    # Strip the continuation quote delimiter and join without space
                    if stripped_prev.endswith(stripped_cont[0]):
                        # Prev ends with quote: strip trailing quote from prev and leading from cont
                        merged = stripped_prev[:-1] + stripped_cont[1:]
                    else:
                        # Unclosed literal: strip only leading quote from continuation
                        merged = stripped_prev + stripped_cont[1:]
                elif in_literal:
                    merged = stripped_prev + stripped_cont
                else:
                    merged = stripped_prev + " " + stripped_cont
                i += 1
            else:
                break

        logical.append(merged)
        i += 1

    return logical


def count_raw_lines(raw_text: str) -> tuple[int, int, int, int]:
    """Count total, code, comment, and blank lines from raw source."""
    is_free = _detect_free_format(raw_text)
    total = code = comments = blanks = 0
    for line in raw_text.splitlines():
        total += 1
        stripped = line.strip()
        if not stripped:
            blanks += 1
        elif is_free and stripped.startswith("*>"):
            comments += 1
        elif not is_free and len(line) > 6 and line[6] in ("*", "/"):
            comments += 1
        else:
            code += 1
    return total, code, comments, blanks
