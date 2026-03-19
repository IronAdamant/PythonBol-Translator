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


_EXEC_HINTS: dict[tuple[str, str], str] = {
    ("CICS", "SEND"): "UI output -> print() or template rendering",
    ("CICS", "RECEIVE"): "UI input -> input() or request parsing",
    ("CICS", "READ"): "VSAM read -> db cursor.execute('SELECT ...')",
    ("CICS", "WRITE"): "VSAM write -> db cursor.execute('INSERT ...')",
    ("CICS", "REWRITE"): "VSAM update -> db cursor.execute('UPDATE ...')",
    ("CICS", "DELETE"): "VSAM delete -> db cursor.execute('DELETE ...')",
    ("CICS", "RETURN"): "return control -> return or sys.exit()",
    ("CICS", "XCTL"): "transfer control -> function call or import",
    ("CICS", "LINK"): "call subprogram -> function call",
    ("CICS", "START"): "start transaction -> async task / queue",
    ("CICS", "SYNCPOINT"): "commit -> db connection.commit()",
    ("SQL", "SELECT"): "cursor.execute('SELECT ...')",
    ("SQL", "INSERT"): "cursor.execute('INSERT ...')",
    ("SQL", "UPDATE"): "cursor.execute('UPDATE ...')",
    ("SQL", "DELETE"): "cursor.execute('DELETE ...')",
    ("SQL", "OPEN"): "cursor = connection.cursor()",
    ("SQL", "CLOSE"): "cursor.close()",
    ("SQL", "FETCH"): "row = cursor.fetchone()",
    ("SQL", "COMMIT"): "connection.commit()",
    ("SQL", "ROLLBACK"): "connection.rollback()",
    ("SQL", "DECLARE"): "cursor declaration (prepare SQL)",
    ("DLI", "GU"): "DL/I Get Unique -> db query by key",
    ("DLI", "GN"): "DL/I Get Next -> cursor.fetchone()",
    ("DLI", "ISRT"): "DL/I Insert -> cursor.execute('INSERT ...')",
    ("DLI", "REPL"): "DL/I Replace -> cursor.execute('UPDATE ...')",
    ("DLI", "DLET"): "DL/I Delete -> cursor.execute('DELETE ...')",
}

# Regex to find the first verb/keyword after EXEC TYPE
_EXEC_VERB_RE = re.compile(
    r"EXEC\s+\w+\s+(\w+)", re.IGNORECASE,
)

# Regex to extract host variables (:VAR-NAME) from SQL text
_HOST_VAR_RE = re.compile(r":([A-Za-z][\w-]*)")


def _cobol_to_python_name(name: str) -> str:
    """Convert a COBOL variable name to a Python-compatible name."""
    return name.strip().replace("-", "_").lower()


def _sql_hint(sql_text: str) -> list[str]:
    """Parse EXEC SQL text and return enhanced hint lines.

    Returns a list of hint strings (without the '* EXEC SQL hint: ' prefix).
    Falls back to an empty list if parsing fails.
    """
    try:
        # Normalize whitespace for easier parsing
        text = " ".join(sql_text.split())
        # Remove EXEC SQL prefix and END-EXEC suffix
        text = re.sub(r"^EXEC\s+SQL\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*END-EXEC\.?\s*$", "", text, flags=re.IGNORECASE)
        upper = text.upper().strip()

        # INCLUDE SQLCA
        if upper.startswith("INCLUDE") and "SQLCA" in upper:
            return ["sqlcode = 0  # SQLCA: check after each SQL operation"]

        # WHENEVER SQLERROR / NOT FOUND
        m = re.match(
            r"WHENEVER\s+(SQLERROR|NOT\s+FOUND)\s+(.*)",
            upper,
        )
        if m:
            condition = m.group(1).strip()
            action = m.group(2).strip()
            return [f"# WHENEVER {condition} {action}"]

        # DECLARE cursor-name CURSOR FOR ...
        m = re.match(
            r"DECLARE\s+(\S+)\s+CURSOR\s+FOR\s+(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            sql_body = m.group(2).strip()
            return [
                f"cursor_{cursor_name} = connection.cursor()",
                f'cursor_{cursor_name}.execute("{sql_body}")',
            ]

        # OPEN cursor-name
        m = re.match(r"OPEN\s+(\S+)\s*$", text, re.IGNORECASE)
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            return [
                f"cursor_{cursor_name}.execute(sql_{cursor_name})"
                f"  # OPEN CURSOR",
            ]

        # FETCH cursor-name INTO :var1, :var2, ...
        m = re.match(
            r"FETCH\s+(\S+)\s+INTO\s+(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            host_vars = _HOST_VAR_RE.findall(m.group(2))
            lines = [f"row = cursor_{cursor_name}.fetchone()  # FETCH"]
            for idx, var in enumerate(host_vars):
                py_var = _cobol_to_python_name(var)
                lines.append(f"self.data.{py_var}.set(row[{idx}])")
            return lines

        # CLOSE cursor-name
        m = re.match(r"CLOSE\s+(\S+)\s*$", text, re.IGNORECASE)
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            return [f"cursor_{cursor_name}.close()"]

        # SELECT ... INTO :var1, :var2 FROM ...
        m = re.match(
            r"(SELECT\s+.+?)\s+INTO\s+(.+?)\s+FROM\s+(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            select_part = m.group(1).strip()
            into_part = m.group(2).strip()
            from_part = m.group(3).strip()
            host_vars = _HOST_VAR_RE.findall(into_part)
            sql_stmt = f"{select_part} FROM {from_part}"
            lines = [f'row = cursor.execute("{sql_stmt}").fetchone()']
            for idx, var in enumerate(host_vars):
                py_var = _cobol_to_python_name(var)
                lines.append(f"self.data.{py_var}.set(row[{idx}])")
            return lines

        # INSERT / UPDATE / DELETE / bare SELECT (DML without cursor)
        m = re.match(
            r"(INSERT|UPDATE|DELETE|SELECT)\b(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            sql_stmt = text.strip()
            return [f'cursor.execute("{sql_stmt}")']

        # COMMIT / ROLLBACK
        if upper.startswith("COMMIT"):
            return ["connection.commit()"]
        if upper.startswith("ROLLBACK"):
            return ["connection.rollback()"]

        return []
    except Exception:
        return []


def _exec_hint(exec_type: str, original_text: str) -> str:
    """Return a Python-equivalent hint for an EXEC block, or empty string."""
    m = _EXEC_VERB_RE.search(original_text)
    if not m:
        return ""
    verb = m.group(1).upper()
    hint = _EXEC_HINTS.get((exec_type, verb), "")
    return hint


# --- CICS enhanced hint extraction ---

_CICS_MAP_RE = re.compile(r"(?:SEND|RECEIVE)\s+MAP\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_TRANSID_RE = re.compile(r"START\s+TRANSID\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_PROGRAM_RE = re.compile(r"(?:LINK|XCTL)\s+PROGRAM\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_COMMAREA_RE = re.compile(r"COMMAREA\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_RESP_RE = re.compile(r"RESP\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_RESP2_RE = re.compile(r"RESP2\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)


def _cics_hint(cics_text: str) -> list[str]:
    """Extract structured CICS hints from an EXEC CICS block.

    Returns a list of hint comment strings with extracted details.
    """
    hints: list[str] = []

    map_m = _CICS_MAP_RE.search(cics_text)
    if map_m:
        hints.append(f"      * CICS MAP: {map_m.group(1).strip()}")

    transid_m = _CICS_TRANSID_RE.search(cics_text)
    if transid_m:
        hints.append(f"      * CICS TRANSID: {transid_m.group(1).strip()}")

    prog_m = _CICS_PROGRAM_RE.search(cics_text)
    if prog_m:
        prog_name = prog_m.group(1).strip()
        comm_m = _CICS_COMMAREA_RE.search(cics_text)
        comm_name = comm_m.group(1).strip() if comm_m else ""
        if comm_name:
            hints.append(f"      * CICS PROGRAM: {prog_name}, COMMAREA: {comm_name}")
        else:
            hints.append(f"      * CICS PROGRAM: {prog_name}")

    resp_m = _CICS_RESP_RE.search(cics_text)
    if resp_m:
        resp_name = resp_m.group(1).strip()
        resp2_m = _CICS_RESP2_RE.search(cics_text)
        resp2_name = resp2_m.group(1).strip() if resp2_m else ""
        if resp2_name:
            hints.append(f"      * CICS RESP: {resp_name}, RESP2: {resp2_name}")
        else:
            hints.append(f"      * CICS RESP: {resp_name}")

    return hints


def strip_exec_blocks(raw_text: str) -> str:
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
        while i < len(lines):
            block_lines.append(lines[i].rstrip())
            check = lines[i][7:72] if len(lines[i]) > 7 else lines[i]
            if _END_EXEC_RE.search(check) or _END_EXEC_RE.search(lines[i]):
                i += 1
                break
            i += 1

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

        # Enhanced SQL metadata extraction
        if exec_type == "SQL":
            sql_hints = _sql_hint(original_text)
            if sql_hints:
                for sh in sql_hints:
                    result.append(f"      * EXEC SQL hint: {sh}")
            else:
                # Fall back to generic hint
                hint = _exec_hint(exec_type, original_text)
                if hint:
                    result.append(f"      * Hint: {hint}")
        elif exec_type == "CICS":
            cics_hints = _cics_hint(original_text)
            if cics_hints:
                for ch in cics_hints:
                    result.append(ch)
            hint = _exec_hint(exec_type, original_text)
            if hint:
                result.append(f"      * Hint: {hint}")
        else:
            hint = _exec_hint(exec_type, original_text)
            if hint:
                result.append(f"      * Hint: {hint}")

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
) -> str:
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
        Preprocessed source text with COPY statements resolved and
        EXEC blocks replaced with TODO comments.
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

    # Always strip EXEC blocks
    result = strip_exec_blocks(result)

    return result
