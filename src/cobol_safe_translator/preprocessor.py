"""COPY statement preprocessor and EXEC block stripper.

Pipeline position: Raw COBOL Source -> **Preprocessor** -> Parser

Runs BEFORE preprocess_lines. Operates on raw source text to:
  - Resolve COPY ... REPLACING statements by inlining copybook content
  - Strip EXEC CICS/SQL blocks, replacing them with TODO comments
"""

from __future__ import annotations

import re
from pathlib import Path

# Copybook file extensions to try when searching (in order)
_COPYBOOK_EXTENSIONS = (".cpy", ".CPY", ".cbl", ".CBL")

# Regex for COPY statement start — captures copybook name (with optional quotes)
# Matches: COPY copybook-name. | COPY 'copybook-name'. | COPY copybook-name REPLACING ...
_COPY_START_RE = re.compile(
    r"^\s{0,6}\s+"           # columns 1-7 (sequence + indicator area)
    r"COPY\s+"               # COPY keyword
    r"['\"]?([\w.+-]+)['\"]?" # copybook name (optionally quoted)
    r"\s*",                   # trailing whitespace
    re.IGNORECASE,
)

# Also match free-format COPY (no column constraints, for already-preprocessed lines)
_COPY_FREE_RE = re.compile(
    r"^\s*COPY\s+['\"]?([\w.+-]+)['\"]?\s*",
    re.IGNORECASE,
)

# Pseudo-text replacement pair: ==(text)== BY ==(text)==
_REPLACING_RE = re.compile(
    r"==\s*(.*?)\s*==\s+BY\s+==\s*(.*?)\s*==",
    re.IGNORECASE,
)

# EXEC ... END-EXEC block detection (may span multiple lines)
# Handles EXEC CICS, EXEC SQL, EXEC DLI, EXEC SQLIMS, and any other EXEC type
_EXEC_START_RE = re.compile(
    r"EXEC\s+(\w+)\b",
    re.IGNORECASE,
)
_END_EXEC_RE = re.compile(r"END-EXEC", re.IGNORECASE)


def find_copybook(
    name: str,
    search_paths: list[Path],
) -> Path | None:
    """Find a copybook file by name in search paths.

    Tries the name as-is first, then appends each copybook extension.
    Returns the first match found, or None.
    """
    # Strip any extension the user may have included
    base = Path(name).stem
    name_with_ext = Path(name).suffix != ""

    for directory in search_paths:
        if not directory.is_dir():
            continue
        # Try exact name first (if it has an extension)
        if name_with_ext:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        # Try base name with each copybook extension
        for ext in _COPYBOOK_EXTENSIONS:
            candidate = directory / (base + ext)
            if candidate.is_file():
                return candidate
        # Try exact name without extension match (e.g., "MYBOOK" as filename)
        if not name_with_ext:
            candidate = directory / name
            if candidate.is_file():
                return candidate

    return None


def _collect_copy_block(lines: list[str], start_idx: int) -> tuple[str, int]:
    """Collect a multi-line COPY statement, returning (full_text, end_idx).

    A COPY statement ends at the first period followed by optional whitespace.
    end_idx is the index of the LAST line consumed (inclusive).
    """
    collected = []
    i = start_idx
    while i < len(lines):
        collected.append(lines[i])
        # Check if this line contains the terminating period
        # Strip any trailing comment area for the check
        text = lines[i]
        content = text[7:72] if len(text) > 7 else text
        if content.rstrip().endswith("."):
            return "\n".join(collected), i
        i += 1
    # Unterminated COPY — return what we have
    return "\n".join(collected), i - 1


def _apply_replacements(
    text: str,
    replacements: list[tuple[str, str]],
) -> str:
    """Apply pseudo-text replacements to copybook content."""
    result = text
    for old, new in replacements:
        # Pseudo-text replacement is literal text substitution
        result = result.replace(old, new)
    return result


def _parse_replacements(copy_block: str) -> list[tuple[str, str]]:
    """Extract REPLACING pairs from a COPY statement block."""
    return _REPLACING_RE.findall(copy_block)


def _is_copy_line(line: str) -> re.Match | None:
    """Check if a line starts a COPY statement. Returns the match or None."""
    m = _COPY_START_RE.match(line)
    if m:
        return m
    # Try free-format match
    return _COPY_FREE_RE.match(line)


def _resolve_copy_statements(
    raw_text: str,
    search_paths: list[Path],
) -> str:
    """Resolve all COPY statements in the source, inlining copybook content."""
    lines = raw_text.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        m = _is_copy_line(line)
        if not m:
            result.append(line)
            i += 1
            continue

        copybook_name = m.group(1)

        # Collect the full COPY statement (may span multiple lines)
        copy_block, end_idx = _collect_copy_block(lines, i)
        replacements = _parse_replacements(copy_block)

        # Find the copybook
        copybook_path = find_copybook(copybook_name, search_paths)

        if copybook_path is None:
            searched = ", ".join(str(p) for p in search_paths)
            comment = (
                f"      * COPY {copybook_name} "
                f"— NOT FOUND (searched: {searched})"
            )
            result.append(comment)
        else:
            content = copybook_path.read_text(encoding="utf-8", errors="replace")
            if replacements:
                content = _apply_replacements(content, replacements)
            # Inline the copybook content (each line as-is)
            for cb_line in content.splitlines():
                result.append(cb_line)

        i = end_idx + 1

    return "\n".join(result)


def _strip_exec_blocks(raw_text: str) -> str:
    """Replace EXEC CICS/SQL ... END-EXEC blocks with TODO comments."""
    lines = raw_text.splitlines()
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        # Check content area for EXEC start
        content = line[7:72] if len(line) > 7 else line
        m = _EXEC_START_RE.search(content)
        if not m:
            # Also check free-format
            m = _EXEC_START_RE.search(line)
        if not m:
            result.append(line)
            i += 1
            continue

        exec_type = m.group(1).upper()
        # Collect lines until END-EXEC
        block_lines = []
        found_end = False
        while i < len(lines):
            block_lines.append(lines[i].rstrip())
            check = lines[i][7:72] if len(lines[i]) > 7 else lines[i]
            if _END_EXEC_RE.search(check) or _END_EXEC_RE.search(lines[i]):
                found_end = True
                i += 1
                break
            i += 1

        if not found_end:
            # Unterminated EXEC — still replace what we collected
            pass

        # Build the original text as a single line for the comment
        original_parts = []
        for bl in block_lines:
            # Extract content area, strip leading/trailing whitespace
            part = bl[7:72].strip() if len(bl) > 7 else bl.strip()
            if part:
                original_parts.append(part)
        original_text = " ".join(original_parts)

        result.append(
            f"      * TODO(high): EXEC {exec_type} block "
            f"— requires manual translation"
        )
        result.append(
            f"      * Original: {original_text}"
        )

    return "\n".join(result)


def resolve_copies(
    raw_text: str,
    copybook_paths: list[str | Path] | None = None,
) -> str:
    """Resolve COPY statements and strip EXEC blocks from raw COBOL source.

    Args:
        raw_text: Raw COBOL source text.
        copybook_paths: Directories to search for copybook files.
            If None or empty, COPY statements are left as-is (no resolution).

    Returns:
        Preprocessed source text with COPY statements resolved and
        EXEC blocks replaced with TODO comments.
    """
    result = raw_text

    # Resolve COPY statements if search paths are provided
    if copybook_paths:
        paths = [Path(p) for p in copybook_paths]
        result = _resolve_copy_statements(result, paths)

    # Always strip EXEC blocks
    result = _strip_exec_blocks(result)

    return result
