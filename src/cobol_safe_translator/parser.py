"""Pure-Python regex/state-machine parser for a subset of COBOL.

Pipeline position: COBOL Source -> **Parser** -> AST (CobolProgram)

Handles:
  - Column-based preprocessing (strip cols 1-6 and 73+)
  - Continuation lines (col 7 = '-'), comment lines (col 7 = '*' or '/')
  - Division splitting
  - IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE division parsing
  - PIC clause expansion and categorization
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import (
    CobolProgram,
    ConditionName,
    DataItem,
    FileControl,
    PicClause,
    ReportDescription,
)
from .report_parser import parse_report_section

# Re-export PIC utilities so existing imports from .parser still work
from .pic_parser import (  # noqa: F401
    classify_pic,
    compute_pic_size,
    expand_pic,
    parse_pic,
)

# Re-export procedure parser so existing imports from .parser still work
from .procedure_parser import (  # noqa: F401
    KNOWN_VERBS,
    parse_procedure,
)

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

    # Scores tied — look for structural fixed-format markers across the file
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
    # No fixed-format structural markers found — treat as free-format
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

        # Comment or debug lines — skip
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
                # Merge continuation — preserve a space to avoid fusing tokens
                stripped_prev = merged.rstrip()
                stripped_cont = cont_content.lstrip()
                # Detect if prev line has an unclosed string literal
                in_literal = False
                if stripped_cont and stripped_cont[0] in ('"', "'"):
                    quote = stripped_cont[0]
                    # Count unescaped quotes in prev — odd means unclosed literal
                    if stripped_prev.count(quote) % 2 == 1:
                        in_literal = True
                # Also handle the old case: prev ends with quote AND cont starts with quote
                # (e.g., both closed — strip both to merge)
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


# --- Division splitting ---

_DIVISION_RE = re.compile(
    r"^(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION", re.IGNORECASE
)


def split_divisions(lines: list[str]) -> dict[str, list[str]]:
    """Split logical lines into division buckets."""
    divisions: dict[str, list[str]] = {
        "IDENTIFICATION": [],
        "ENVIRONMENT": [],
        "DATA": [],
        "PROCEDURE": [],
    }
    current: str | None = None

    for line in lines:
        m = _DIVISION_RE.match(line.strip())
        if m:
            current = m.group(1).upper()
            continue
        if current:
            divisions[current].append(line)

    return divisions


# --- IDENTIFICATION DIVISION ---

def parse_identification(lines: list[str]) -> tuple[str, str]:
    """Extract PROGRAM-ID and AUTHOR from IDENTIFICATION DIVISION lines."""
    program_id = ""
    author = ""
    for line in lines:
        upper = line.strip().upper()
        if upper.startswith("PROGRAM-ID"):
            program_id = _extract_value(line, "PROGRAM-ID")
        elif upper.startswith("AUTHOR"):
            author = _extract_value(line, "AUTHOR")
    return program_id, author


def _extract_value(line: str, keyword: str) -> str:
    """Extract the single-token value after 'KEYWORD. value.' or 'KEYWORD. value'."""
    # Remove keyword, then strip dots and whitespace
    idx = line.upper().find(keyword.upper())
    if idx == -1:
        return ""
    rest = line[idx + len(keyword):].strip().lstrip(".").strip().rstrip(".")
    # Take only the first token — PROGRAM-ID, AUTHOR etc. must be single identifiers
    parts = rest.split()
    first = parts[0] if parts else ""
    return first


# --- ENVIRONMENT DIVISION ---

_SELECT_RE = re.compile(
    r"SELECT\s+([\w-]+)\s+ASSIGN\s+TO\s+[\"']?([\w.\-]+)[\"']?",
    re.IGNORECASE,
)
_FILE_STATUS_RE = re.compile(
    r"FILE\s+STATUS\s+(?:IS\s+)?([\w-]+)", re.IGNORECASE,
)
_ORGANIZATION_RE = re.compile(
    r"ORGANIZATION\s+(?:IS\s+)?(SEQUENTIAL|INDEXED|RELATIVE)", re.IGNORECASE,
)


def parse_environment(lines: list[str]) -> list[FileControl]:
    """Extract SELECT/ASSIGN file controls with FILE STATUS and ORGANIZATION."""
    combined = " ".join(l.strip() for l in lines)
    controls: list[FileControl] = []

    # Split on SELECT keyword to process each file control entry
    # (FILE STATUS etc. appear between SELECT entries)
    select_blocks = re.split(r"(?=\bSELECT\b)", combined, flags=re.IGNORECASE)

    for block in select_blocks:
        m = _SELECT_RE.search(block)
        if not m:
            continue
        file_status = None
        organization = None
        fs_m = _FILE_STATUS_RE.search(block)
        if fs_m:
            file_status = fs_m.group(1).upper()
        org_m = _ORGANIZATION_RE.search(block)
        if org_m:
            organization = org_m.group(1).upper()
        controls.append(FileControl(
            select_name=m.group(1).upper(),
            assign_to=m.group(2),
            file_status=file_status,
            organization=organization,
        ))
    return controls


# --- DATA DIVISION ---

_LEVEL_RE = re.compile(r"^(\d{1,2})\s+([\w-]+)")
_PIC_RE = re.compile(r"PIC(?:TURE)?\s+(?:IS\s+)?(S?[0-9XAVZBS().,+\-$CRDB*P/]+)", re.IGNORECASE)
_VALUE_RE = re.compile(r'VALUE\s+(?:IS\s+)?("[^"]*"|\'[^\']*\'|[+\-]?\d+\.\d+|[^\s.]+)(?:\.|$|\s)', re.IGNORECASE)
_VALUES_RE = re.compile(r'VALUE(?:S)?\s+(?:IS\s+|ARE\s+)?(.*?)(?:\.\s*$|$)', re.IGNORECASE)
_OCCURS_RE = re.compile(r"OCCURS\s+(\d+)", re.IGNORECASE)
_REDEFINES_RE = re.compile(r"REDEFINES\s+([\w-]+)", re.IGNORECASE)
_USAGE_RE = re.compile(
    r"(?:USAGE\s+(?:IS\s+)?|(?<![A-Za-z0-9\"-]))"
    r"(COMP(?:UTATIONAL)?(?:-[0-9])?|BINARY|PACKED-DECIMAL|DISPLAY)"
    r"(?=\s|\.|$)",
    re.IGNORECASE,
)


def parse_data_division(lines: list[str]) -> tuple[list[DataItem], list[DataItem], list[DataItem], list[ReportDescription]]:
    """Parse DATA DIVISION into file, working-storage, linkage items, and report descriptions."""
    section = "UNKNOWN"
    file_items: list[DataItem] = []
    ws_items: list[DataItem] = []
    linkage_items: list[DataItem] = []

    # Detect and extract REPORT SECTION lines for the dedicated parser
    report_lines: list[str] = []
    non_report_lines: list[str] = []
    in_report = False
    for line in lines:
        upper = line.strip().upper()
        if "REPORT SECTION" in upper:
            in_report = True
            report_lines.append(line)
            continue
        # REPORT SECTION ends when another section starts
        if in_report and any(kw in upper for kw in (
            "WORKING-STORAGE SECTION", "LINKAGE SECTION", "FILE SECTION",
            "LOCAL-STORAGE SECTION", "SCREEN SECTION",
            "COMMUNICATION SECTION",
        )):
            in_report = False
        if in_report:
            report_lines.append(line)
        else:
            non_report_lines.append(line)

    reports = parse_report_section(report_lines) if report_lines else []
    lines = non_report_lines

    last_item: DataItem | None = None

    for line in lines:
        upper = line.strip().upper()
        if "FILE SECTION" in upper:
            section = "FILE"
            continue
        elif "WORKING-STORAGE SECTION" in upper:
            section = "WS"
            continue
        elif "LINKAGE SECTION" in upper:
            section = "LINKAGE"
            continue
        elif upper.startswith("FD ") or upper.startswith("SD "):
            # File descriptor — skip the FD line itself
            continue

        # Check for 88-level condition names first
        stripped = line.strip()
        level_m = _LEVEL_RE.match(stripped)
        if level_m and int(level_m.group(1)) == 88:
            cond = _parse_88_condition(line)
            if cond and last_item is not None:
                last_item.conditions.append(cond)
            continue

        item = _parse_data_item(line)
        if item is None:
            continue

        last_item = item
        if section == "FILE":
            file_items.append(item)
        elif section == "WS":
            ws_items.append(item)
        elif section == "LINKAGE":
            linkage_items.append(item)

    # Build hierarchy
    file_items = _build_hierarchy(file_items)
    ws_items = _build_hierarchy(ws_items)
    linkage_items = _build_hierarchy(linkage_items)
    return file_items, ws_items, linkage_items, reports


def _parse_88_condition(line: str) -> ConditionName | None:
    """Parse an 88-level condition name line.

    Handles: VALUE "A", VALUE "A" "B" "C", VALUE 1 THRU 10.
    """
    stripped = line.strip()
    level_m = _LEVEL_RE.match(stripped)
    if not level_m:
        return None
    name = level_m.group(2).upper()

    values_m = _VALUES_RE.search(stripped[level_m.end():])
    if not values_m:
        return ConditionName(name=name)

    raw_values = values_m.group(1).strip().rstrip(".")
    values: list[str] = []
    thru_ranges: list[tuple[str, str]] = []

    # Tokenize the value clause
    tokens: list[str] = []
    current = ""
    in_quote: str | None = None
    for ch in raw_values:
        if in_quote:
            current += ch
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            current += ch
        elif ch in (" ", "\t"):
            if current:
                tokens.append(current)
                current = ""
        else:
            current += ch
    if current:
        tokens.append(current)

    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Check for THRU/THROUGH range
        if i + 2 < len(tokens) and tokens[i + 1].upper() in ("THRU", "THROUGH"):
            lo = _strip_quotes(token)
            hi = _strip_quotes(tokens[i + 2])
            thru_ranges.append((lo, hi))
            i += 3
        else:
            values.append(_strip_quotes(token))
            i += 1

    return ConditionName(name=name, values=values, thru_ranges=thru_ranges)


def _strip_quotes(s: str) -> str:
    """Remove surrounding quotes from a string value."""
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_data_item(line: str) -> DataItem | None:
    """Parse a single data item line (non-88 levels)."""
    stripped = line.strip()
    if not stripped:
        return None

    level_m = _LEVEL_RE.match(stripped)
    if not level_m:
        return None

    level = int(level_m.group(1))
    name = level_m.group(2).upper()

    pic: PicClause | None = None
    pic_m = _PIC_RE.search(stripped)
    if pic_m:
        pic = parse_pic(pic_m.group(1).strip().rstrip("."))

    value: str | None = None
    value_m = _VALUE_RE.search(stripped)
    if value_m:
        value = _strip_quotes(value_m.group(1).strip())

    occurs: int | None = None
    occurs_m = _OCCURS_RE.search(stripped)
    if occurs_m:
        occurs = int(occurs_m.group(1))

    redefines: str | None = None
    redefines_m = _REDEFINES_RE.search(stripped)
    if redefines_m:
        redefines = redefines_m.group(1).upper()

    usage: str | None = None
    usage_m = _USAGE_RE.search(stripped)
    if usage_m:
        usage = usage_m.group(1).upper()

    return DataItem(
        level=level,
        name=name,
        pic=pic,
        value=value,
        occurs=occurs,
        redefines=redefines,
        usage=usage,
    )


def _build_hierarchy(flat_items: list[DataItem]) -> list[DataItem]:
    """Build parent-child hierarchy from flat level-numbered items.

    Returns only the top-level (01/77) items with children nested.
    Level 77 items are independent (no children) and always root-level.
    """
    if not flat_items:
        return []

    roots: list[DataItem] = []
    stack: list[DataItem] = []

    for item in flat_items:
        # Level 77 is always independent — never nested under another item
        if item.level == 77:
            stack.clear()
            roots.append(item)
            continue

        # Pop stack until we find a parent with a lower level
        while stack and stack[-1].level >= item.level:
            stack.pop()

        if stack:
            stack[-1].children.append(item)
        else:
            roots.append(item)

        stack.append(item)

    return roots


# --- Main parse entry point ---

def parse_cobol(
    source: str,
    source_path: str = "",
    copybook_paths: list[str | Path] | None = None,
    *,
    copy_paths: list[str | Path] | None = None,
) -> CobolProgram:
    """Parse COBOL source text into a CobolProgram AST.

    Args:
        source: Raw COBOL source text.
        source_path: Path to the source file (for metadata).
        copybook_paths: Directories to search for COPY copybooks.
            If provided, the preprocessor resolves COPY statements and
            strips EXEC CICS/SQL blocks before parsing.
        copy_paths: Additional directories to search for copybooks
            (searched after the source file's directory).
    """
    from .preprocessor import resolve_copies

    # Derive source directory from source_path when available
    source_dir: Path | None = None
    if source_path:
        sp = Path(source_path)
        if sp.parent.is_dir():
            source_dir = sp.parent

    # Always run preprocessor (handles both COPY resolution and EXEC stripping)
    source = resolve_copies(
        source,
        copybook_paths,
        source_dir=source_dir,
        copy_paths=copy_paths,
    )

    logical_lines = preprocess_lines(source)
    divisions = split_divisions(logical_lines)

    program_id, author = parse_identification(divisions["IDENTIFICATION"])
    file_controls = parse_environment(divisions["ENVIRONMENT"])
    file_section, working_storage, linkage_section, report_section = parse_data_division(divisions["DATA"])
    paragraphs = parse_procedure(divisions["PROCEDURE"])

    return CobolProgram(
        program_id=program_id,
        source_path=source_path,
        author=author,
        file_controls=file_controls,
        file_section=file_section,
        working_storage=working_storage,
        linkage_section=linkage_section,
        report_section=report_section,
        paragraphs=paragraphs,
        raw_lines=source.splitlines(),
    )


def parse_cobol_file(
    path: str | Path,
    copybook_paths: list[str | Path] | None = None,
    *,
    copy_paths: list[str | Path] | None = None,
) -> CobolProgram:
    """Parse a COBOL file from disk.

    Args:
        path: Path to the COBOL source file.
        copybook_paths: Directories to search for COPY copybooks.
        copy_paths: Additional directories to search for copybooks
            (searched after the source file's directory).
    """
    p = Path(path)
    source = p.read_text(encoding="utf-8", errors="replace")
    return parse_cobol(
        source,
        source_path=str(p),
        copybook_paths=copybook_paths,
        copy_paths=copy_paths,
    )
