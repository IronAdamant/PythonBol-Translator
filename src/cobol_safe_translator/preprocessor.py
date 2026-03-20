"""COPY statement preprocessor and EXEC block stripper.

Pipeline position: Raw COBOL Source -> **Preprocessor** -> Parser

Runs BEFORE preprocess_lines. Operates on raw source text to:
  - Resolve COPY ... REPLACING statements by inlining copybook content
  - Strip EXEC CICS/SQL blocks, replacing them with TODO comments
"""

from __future__ import annotations

import re
from pathlib import Path

from .exec_block_handler import strip_exec_blocks
from .models import SqlBlock

# Copybook file extensions to try when searching (in order)
_COPYBOOK_EXTENSIONS = (
    ".cpy", ".CPY",
    ".cbl", ".CBL",
    ".cob", ".COB",
    ".cobol", ".COBOL",
    ".copy", ".COPY",
)

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

# Pseudo-text replacement pair with optional LEADING/TRAILING qualifier:
#   [LEADING|TRAILING] ==(text)== BY ==(text)==
_REPLACING_PSEUDO_RE = re.compile(
    r"(?:LEADING|TRAILING)?\s*==\s*(.*?)\s*==\s+BY\s+==\s*(.*?)\s*==",
    re.IGNORECASE,
)

# Full pseudo-text pattern that captures the optional qualifier
_REPLACING_QUALIFIED_RE = re.compile(
    r"(LEADING|TRAILING)?\s*==\s*(.*?)\s*==\s+BY\s+==\s*(.*?)\s*==",
    re.IGNORECASE | re.DOTALL,
)

# Non-pseudo-text replacement: word BY word (no == delimiters)
_REPLACING_WORD_RE = re.compile(
    r"(?:REPLACING\s+)?(\S+)\s+BY\s+(\S+)",
    re.IGNORECASE,
)

def find_copybook(
    name: str,
    search_paths: list[Path],
) -> Path | None:
    """Find a copybook file by name in search paths.

    Tries the name as-is first, then appends each copybook extension.
    Falls back to case-insensitive matching on Linux when exact case fails.
    Returns the first match found, or None.
    """
    # Strip any extension the user may have included
    base = Path(name).stem
    name_with_ext = Path(name).suffix != ""

    # --- Pass 1: exact-case lookups (fast, no directory listing) ---
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

    # --- Pass 2: case-insensitive fallback (handles Linux case mismatch) ---
    base_lower = base.lower()
    for directory in search_paths:
        if not directory.is_dir():
            continue
        try:
            for entry in directory.iterdir():
                if not entry.is_file():
                    continue
                entry_stem = entry.stem.lower()
                entry_suffix = entry.suffix.lower()
                if entry_stem != base_lower:
                    continue
                # If the COPY name had an extension, match it case-insensitively
                if name_with_ext:
                    if entry_suffix == Path(name).suffix.lower():
                        return entry
                else:
                    # Match against known copybook extensions
                    if entry_suffix in {e.lower() for e in _COPYBOOK_EXTENSIONS}:
                        return entry
                    # Also match bare filename (no extension)
                    if entry.name.lower() == base_lower:
                        return entry
        except OSError:
            continue

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
        # Handle both fixed-format (cols 8-72) and free-format (full line)
        if len(text) > 7 and not text[:6].strip().isalpha():
            content = text[7:72]
        else:
            content = text
        # Check fixed-format content area OR full line (for free-format)
        if content.rstrip().endswith(".") or text.rstrip().endswith("."):
            return "\n".join(collected), i
        i += 1
    # Unterminated COPY — return what we have
    return "\n".join(collected), i - 1


def _apply_replacements(
    text: str,
    replacements: list[tuple[str, str, str]],
) -> str:
    """Apply REPLACING substitutions to copybook content.

    Each replacement is *(old, new, qualifier)* where *qualifier* is one of
    ``"FULL"`` (default pseudo-text / whole-word), ``"LEADING"`` (prefix
    match), or ``"TRAILING"`` (suffix match).
    """
    result = text
    for old, new, qualifier in replacements:
        if qualifier == "LEADING":
            # Replace *old* only at the start of a COBOL word.
            # COBOL words contain [A-Za-z0-9-], so we use a lookbehind
            # that rejects preceding alphanumeric or hyphen characters.
            result = re.sub(
                r"(?<![A-Za-z0-9\-])" + re.escape(old) + r"(?=[A-Za-z0-9\-])",
                new, result,
            )
        elif qualifier == "TRAILING":
            # Replace *old* only at the end of a COBOL word.
            result = re.sub(
                r"(?<=[A-Za-z0-9\-])" + re.escape(old) + r"(?![A-Za-z0-9\-])",
                new, result,
            )
        else:  # FULL — literal text substitution (original behaviour)
            result = result.replace(old, new)
    return result


def _parse_replacements(copy_block: str) -> list[tuple[str, str, str]]:
    """Extract REPLACING pairs from a COPY statement block.

    Returns a list of ``(old_text, new_text, qualifier)`` tuples.
    *qualifier* is ``"FULL"`` (default), ``"LEADING"``, or ``"TRAILING"``.
    """
    replacements: list[tuple[str, str, str]] = []

    # --- 1. Try pseudo-text with optional LEADING/TRAILING qualifier ---
    for m in _REPLACING_QUALIFIED_RE.finditer(copy_block):
        qualifier = (m.group(1) or "FULL").upper()
        old_text = " ".join(m.group(2).split())   # normalise whitespace
        new_text = " ".join(m.group(3).split())
        if old_text:
            replacements.append((old_text, new_text, qualifier))

    if replacements:
        return replacements

    # --- 2. Fall back to non-pseudo-text: word BY word ---
    for m in _REPLACING_WORD_RE.finditer(copy_block):
        old_word = m.group(1).strip().rstrip(".")
        new_word = m.group(2).strip().rstrip(".")
        if old_word.upper() not in ("REPLACING",) and old_word:
            replacements.append((old_word, new_word, "FULL"))

    return replacements


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
    _seen: frozenset[str] | None = None,
) -> str:
    """Resolve all COPY statements in the source, inlining copybook content.

    Recursively resolves nested COPYs within copybooks before applying
    REPLACING, so the outer REPLACING operates on fully-expanded content
    (correct per COBOL standard).  Uses *_seen* (canonical paths) for
    cycle detection.
    """
    if _seen is None:
        _seen = frozenset()

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
            canon = str(copybook_path.resolve())
            if canon in _seen:
                # Circular dependency — skip to avoid infinite recursion
                result.append(
                    f"      * COPY {copybook_name} "
                    f"-- CIRCULAR DEPENDENCY (skipped)"
                )
            else:
                content = copybook_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                # Recursively resolve nested COPYs BEFORE applying REPLACING
                content = _resolve_copy_statements(
                    content, search_paths, _seen | {canon}
                )
                if replacements:
                    content = _apply_replacements(content, replacements)
                # Inline the copybook content (each line as-is)
                for cb_line in content.splitlines():
                    result.append(cb_line)

        i = end_idx + 1

    return "\n".join(result)


def _build_search_paths(
    source_dir: Path | None,
    copy_paths: list[Path] | None,
) -> list[Path]:
    """Build the ordered list of directories to search for copybooks.

    Search order:
      1. The source file's own directory (if known)
      2. Each directory in *copy_paths*, in order
      3. Immediate subdirectories of the source file's directory
    """
    paths: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            paths.append(p)

    # 1. Source file's own directory
    if source_dir is not None and source_dir.is_dir():
        _add(source_dir)

    # 2. User-specified copy_paths
    if copy_paths:
        for cp in copy_paths:
            if cp.is_dir():
                _add(cp)

    # 3. Subdirectories of the source file's directory
    if source_dir is not None and source_dir.is_dir():
        try:
            for child in sorted(source_dir.iterdir()):
                if child.is_dir():
                    _add(child)
        except OSError:
            pass

    return paths


def resolve_copies(
    raw_text: str,
    copybook_paths: list[str | Path] | None = None,
    *,
    source_dir: str | Path | None = None,
    copy_paths: list[str | Path] | None = None,
) -> tuple[str, list[SqlBlock]]:
    """Resolve COPY statements and strip EXEC blocks from raw COBOL source.

    Args:
        raw_text: Raw COBOL source text.
        copybook_paths: Legacy directories to search for copybook files.
            If None or empty, COPY statements are left as-is (no resolution)
            unless *source_dir* or *copy_paths* provide search directories.
        source_dir: Directory of the COBOL source file. Searched first,
            and its subdirectories are searched last.
        copy_paths: Additional directories to search for copybooks,
            searched after *source_dir* and before its subdirectories.

    Returns:
        Tuple of (preprocessed_text, sql_blocks) where preprocessed_text
        has COPY statements resolved and EXEC blocks replaced with TODO
        comments, and sql_blocks contains structured metadata for each
        EXEC SQL block found.
    """
    result = raw_text

    # Merge legacy copybook_paths into copy_paths for backwards compat
    merged_copy: list[Path] = []
    if copy_paths:
        merged_copy.extend(Path(p) for p in copy_paths)
    if copybook_paths:
        merged_copy.extend(Path(p) for p in copybook_paths)

    src_dir = Path(source_dir) if source_dir is not None else None

    # Build ordered search paths (source_dir -> copy_paths -> subdirs)
    search = _build_search_paths(src_dir, merged_copy or None)

    # Resolve COPY statements if any search paths are available
    # Recursion inside _resolve_copy_statements handles nested COPYs
    if search:
        result = _resolve_copy_statements(result, search)

    # Always strip EXEC blocks (also extracts SqlBlock metadata)
    result, sql_blocks = strip_exec_blocks(result)

    return result, sql_blocks
