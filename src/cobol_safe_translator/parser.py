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

from .pic_parser import parse_pic
from .procedure_parser import parse_procedure
from .line_preprocessor import preprocess_lines, count_raw_lines  # noqa: F401


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
    r'SELECT\s+([\w-]+)\s+ASSIGN\s+(?:TO\s+)?'
    r"""(?:"([^"]+)"|'([^']+)'|([\w\-]+(?:\.[\w\-]+)*))""",
    re.IGNORECASE,
)
_FILE_STATUS_RE = re.compile(
    r"FILE\s+STATUS\s+(?:IS\s+)?([\w-]+)", re.IGNORECASE,
)
_ORGANIZATION_RE = re.compile(
    r"ORGANIZATION\s+(?:IS\s+)?(SEQUENTIAL|INDEXED|RELATIVE)", re.IGNORECASE,
)
_ACCESS_MODE_RE = re.compile(
    r"ACCESS\s+MODE\s+(?:IS\s+)?(SEQUENTIAL|RANDOM|DYNAMIC)", re.IGNORECASE,
)
_RECORD_KEY_RE = re.compile(
    r"RECORD\s+KEY\s+(?:IS\s+)?([\w-]+)", re.IGNORECASE,
)
_ALT_KEY_RE = re.compile(
    r"ALTERNATE\s+RECORD\s+KEY\s+(?:IS\s+)?([\w-]+)", re.IGNORECASE,
)


def parse_environment(lines: list[str]) -> list[FileControl]:
    """Extract SELECT/ASSIGN file controls with FILE STATUS, ORGANIZATION, ACCESS MODE, and keys."""
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
        access_mode = None
        record_key = None
        alternate_keys: list[str] = []
        fs_m = _FILE_STATUS_RE.search(block)
        if fs_m:
            file_status = fs_m.group(1).upper()
        org_m = _ORGANIZATION_RE.search(block)
        if org_m:
            organization = org_m.group(1).upper()
        acc_m = _ACCESS_MODE_RE.search(block)
        if acc_m:
            access_mode = acc_m.group(1).upper()
        rk_m = _RECORD_KEY_RE.search(block)
        if rk_m:
            record_key = rk_m.group(1).upper()
        for ak_m in _ALT_KEY_RE.finditer(block):
            alternate_keys.append(ak_m.group(1).upper())
        assign_to = m.group(2) or m.group(3) or m.group(4) or ""
        controls.append(FileControl(
            select_name=m.group(1).upper(),
            assign_to=assign_to,
            file_status=file_status,
            organization=organization,
            access_mode=access_mode,
            record_key=record_key,
            alternate_keys=alternate_keys,
        ))
    return controls


# --- DATA DIVISION ---

_LEVEL_RE = re.compile(r"^(\d{1,2})\s+([\w-]+)")
_PIC_RE = re.compile(r"PIC(?:TURE)?\s+(?:IS\s+)?(S?[0-9XAVZBS().,+\-$CRDB*P/]+)", re.IGNORECASE)
_VALUE_RE = re.compile(r'VALUE\s+(?:IS\s+)?("[^"]*"|\'[^\']*\'|[+\-]?\d+\.\d+|[^\s.]+)(?:\.|$|\s)', re.IGNORECASE)
_VALUES_RE = re.compile(r'VALUE(?:S)?\s+(?:IS\s+|ARE\s+)?(.*?)(?:\.\s*$|$)', re.IGNORECASE)
_OCCURS_RE = re.compile(r"OCCURS\s+(\d+)", re.IGNORECASE)
_OCCURS_DEPENDING_RE = re.compile(
    r"OCCURS\s+\d+\s+(?:TO\s+\d+\s+(?:TIMES\s+)?)?DEPENDING\s+(?:ON\s+)?([\w-]+)",
    re.IGNORECASE,
)
_REDEFINES_RE = re.compile(r"REDEFINES\s+([\w-]+)", re.IGNORECASE)
_USAGE_RE = re.compile(
    r"(?:USAGE\s+(?:IS\s+)?|(?<![A-Za-z0-9\"-]))"
    r"(COMP(?:UTATIONAL)?(?:-[0-9])?|BINARY|PACKED-DECIMAL|DISPLAY|INDEX)"
    r"(?=\s|\.|$)",
    re.IGNORECASE,
)
_EXTERNAL_RE = re.compile(r"\bEXTERNAL\b", re.IGNORECASE)
_GLOBAL_RE = re.compile(r"\bGLOBAL\b", re.IGNORECASE)
_JUSTIFIED_RE = re.compile(r"\bJUSTIFIED\b|\bJUST\b", re.IGNORECASE)
_BLANK_WHEN_ZERO_RE = re.compile(r"\bBLANK\s+WHEN\s+ZERO(?:S|ES)?\b", re.IGNORECASE)

# Section boundary keywords used to delimit DATA DIVISION sections.
_SECTION_BOUNDARIES = (
    "WORKING-STORAGE SECTION", "LINKAGE SECTION", "FILE SECTION",
    "LOCAL-STORAGE SECTION", "SCREEN SECTION",
    "COMMUNICATION SECTION", "REPORT SECTION",
)


def parse_data_division(lines: list[str]) -> tuple[list[DataItem], list[DataItem], list[DataItem], list[ReportDescription], list[DataItem]]:
    """Parse DATA DIVISION into file, working-storage, linkage items, report descriptions, and local-storage items."""
    section = "UNKNOWN"
    file_items: list[DataItem] = []
    ws_items: list[DataItem] = []
    linkage_items: list[DataItem] = []
    local_items: list[DataItem] = []

    # Detect and extract REPORT SECTION and SCREEN SECTION lines for their
    # dedicated parsers, so they do not get processed as regular data items.
    report_lines: list[str] = []
    screen_lines: list[str] = []
    remaining_lines: list[str] = []
    current_special: str | None = None  # "REPORT" or "SCREEN"
    for line in lines:
        upper = line.strip().upper()
        if "REPORT SECTION" in upper:
            current_special = "REPORT"
            report_lines.append(line)
            continue
        if "SCREEN SECTION" in upper:
            current_special = "SCREEN"
            continue  # skip the header line itself
        # Special section ends when another section starts
        if current_special and any(kw in upper for kw in _SECTION_BOUNDARIES):
            current_special = None
        if current_special == "REPORT":
            report_lines.append(line)
        elif current_special == "SCREEN":
            screen_lines.append(line)
        else:
            remaining_lines.append(line)

    reports = parse_report_section(report_lines) if report_lines else []
    lines = remaining_lines

    last_item: DataItem | None = None

    for line in lines:
        upper = line.strip().upper()
        if "FILE SECTION" in upper:
            section = "FILE"
            continue
        elif "WORKING-STORAGE SECTION" in upper:
            section = "WS"
            continue
        elif "LOCAL-STORAGE SECTION" in upper:
            section = "LOCAL"
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
        elif section == "LOCAL":
            local_items.append(item)
        elif section == "LINKAGE":
            linkage_items.append(item)

    # Build hierarchy
    file_items = _build_hierarchy(file_items)
    ws_items = _build_hierarchy(ws_items)
    linkage_items = _build_hierarchy(linkage_items)
    local_items = _build_hierarchy(local_items)
    return file_items, ws_items, linkage_items, reports, local_items


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

    is_external = bool(_EXTERNAL_RE.search(stripped))
    is_global = bool(_GLOBAL_RE.search(stripped))
    justified_right = bool(_JUSTIFIED_RE.search(stripped))
    blank_when_zero = bool(_BLANK_WHEN_ZERO_RE.search(stripped))

    occurs_depending: str | None = None
    od_m = _OCCURS_DEPENDING_RE.search(stripped)
    if od_m:
        occurs_depending = od_m.group(1).upper()

    return DataItem(
        level=level,
        name=name,
        pic=pic,
        value=value,
        occurs=occurs,
        redefines=redefines,
        usage=usage,
        is_external=is_external,
        is_global=is_global,
        justified_right=justified_right,
        blank_when_zero=blank_when_zero,
        occurs_depending=occurs_depending,
    )


def _level_hierarchy(flat_items: list, *, level77_independent: bool = False) -> list:
    """Build parent-child hierarchy from flat level-numbered items.

    Works with any type that has ``.level: int`` and ``.children: list``
    attributes (DataItem, ScreenField).

    When *level77_independent* is True, level-77 items are treated as
    independent root entries (COBOL DATA DIVISION semantics).
    """
    if not flat_items:
        return []

    roots: list = []
    stack: list = []

    for item in flat_items:
        if level77_independent and item.level == 77:
            stack.clear()
            roots.append(item)
            continue

        while stack and stack[-1].level >= item.level:
            stack.pop()

        if stack:
            stack[-1].children.append(item)
        else:
            roots.append(item)

        stack.append(item)

    return roots


def _build_hierarchy(flat_items: list[DataItem]) -> list[DataItem]:
    """Build parent-child hierarchy from flat level-numbered data items."""
    return _level_hierarchy(flat_items, level77_independent=True)


# --- SCREEN SECTION (delegated to screen_parser) ---
from .screen_parser import parse_screen_section, _extract_screen_lines  # noqa: F401, E402


# --- Multi-program splitting ---

_IDENT_DIV_RE = re.compile(
    r"^IDENTIFICATION\s+DIVISION", re.IGNORECASE,
)
_END_PROGRAM_RE = re.compile(
    r"^END\s+PROGRAM\s+[\w-]+\s*\.?\s*$", re.IGNORECASE,
)


def _split_programs(logical_lines: list[str]) -> list[list[str]]:
    """Split logical lines into per-program segments.

    Detects multiple IDENTIFICATION DIVISION boundaries.  If only one
    is found the full list is returned as a single segment (preserving
    backward compatibility).  ``END PROGRAM`` delimiter lines are
    stripped from each segment since they carry no semantic value for
    the parser.
    """
    boundaries: list[int] = []
    for i, line in enumerate(logical_lines):
        if _IDENT_DIV_RE.match(line.strip()):
            boundaries.append(i)

    # Single program — fast path (preserves all existing behaviour)
    if len(boundaries) <= 1:
        return [logical_lines]

    segments: list[list[str]] = []
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(logical_lines)
        segment = [
            ln for ln in logical_lines[start:end]
            if not _END_PROGRAM_RE.match(ln.strip())
        ]
        segments.append(segment)
    return segments


# --- Main parse entry point ---

def _parse_single_program(
    logical_lines: list[str],
    source_path: str,
    raw_lines: list[str],
) -> CobolProgram:
    """Parse a single program's logical lines into a CobolProgram AST."""
    divisions = split_divisions(logical_lines)

    program_id, author = parse_identification(divisions["IDENTIFICATION"])
    file_controls = parse_environment(divisions["ENVIRONMENT"])
    data_lines = divisions["DATA"]
    file_section, working_storage, linkage_section, report_section, local_storage = parse_data_division(data_lines)
    screen_lines = _extract_screen_lines(data_lines)
    screen_section = parse_screen_section(screen_lines) if screen_lines else []
    paragraphs, declaratives = parse_procedure(divisions["PROCEDURE"])

    return CobolProgram(
        program_id=program_id,
        source_path=source_path,
        author=author,
        file_controls=file_controls,
        file_section=file_section,
        working_storage=working_storage,
        linkage_section=linkage_section,
        local_storage=local_storage,
        report_section=report_section,
        screen_section=screen_section,
        paragraphs=paragraphs,
        declaratives=declaratives,
        raw_lines=raw_lines,
    )


def parse_cobol(
    source: str,
    source_path: str = "",
    copybook_paths: list[str | Path] | None = None,
    *,
    copy_paths: list[str | Path] | None = None,
) -> CobolProgram:
    """Parse COBOL source text into a CobolProgram AST.

    Supports multi-program source files (nested or concatenated).
    When multiple ``IDENTIFICATION DIVISION`` boundaries are found the
    source is split into segments and each segment is parsed
    independently.  Additional programs are attached to the first
    program's ``nested_programs`` list.

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
    source, sql_blocks = resolve_copies(
        source,
        copybook_paths,
        source_dir=source_dir,
        copy_paths=copy_paths,
    )

    logical_lines = preprocess_lines(source)
    segments = _split_programs(logical_lines)
    raw_lines = source.splitlines()

    # Parse the first (or only) program
    main_program = _parse_single_program(segments[0], source_path, raw_lines)

    # Attach extracted SQL blocks to the program
    main_program.sql_blocks = sql_blocks

    # Parse any additional programs and attach as nested_programs
    for segment in segments[1:]:
        nested = _parse_single_program(segment, source_path, [])
        main_program.nested_programs.append(nested)

    return main_program


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
