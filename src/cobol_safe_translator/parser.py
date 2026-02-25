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
    CobolStatement,
    DataItem,
    FileControl,
    Paragraph,
    PicCategory,
    PicClause,
)

# --- Preprocessing ---

def preprocess_lines(raw_text: str) -> list[str]:
    """Strip sequence numbers (cols 1-6), indicator area (col 7), and cols 73+.

    Handles continuation lines and filters comment lines.
    Returns logical lines (continuations merged).
    """
    physical = raw_text.splitlines()
    logical: list[str] = []
    i = 0
    while i < len(physical):
        line = physical[i]
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
                in_literal = (
                    (stripped_prev.endswith('"') and stripped_cont.startswith('"'))
                    or (stripped_prev.endswith("'") and stripped_cont.startswith("'"))
                )
                if in_literal:
                    # Strip the trailing quote from prev and leading quote from cont
                    # to avoid duplicate quote characters at the join point
                    merged = stripped_prev[:-1] + stripped_cont[1:]
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
    total = code = comments = blanks = 0
    for line in raw_text.splitlines():
        total += 1
        stripped = line.strip()
        if not stripped:
            blanks += 1
        elif len(line) > 6 and line[6] in ("*", "/", "D", "d"):
            comments += 1
        else:
            code += 1
    return total, code, comments, blanks


# --- PIC parsing ---

_PIC_REPEAT = re.compile(r"(CR|DB|[A9XZVBS,.\-+$])\((\d+)\)", re.IGNORECASE)


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
    has_edit = any(c in upper for c in ("Z", "B", ",", ".", "+", "-", "CR", "DB", "$"))

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
        decimals = sum(1 for c in after_v if c in ("9",))

    # Handle CR/DB as 2-position editing symbols before char loop
    cr_db_extra = clean.upper().count("CR") + clean.upper().count("DB")
    # Remove CR and DB for per-character counting to avoid double-counting
    count_clean = clean.upper().replace("CR", "").replace("DB", "")

    size = cr_db_extra * 2  # Each CR/DB occupies 2 display positions
    for c in count_clean:
        if c in ("9", "X", "A", "Z"):
            size += 1
        elif c in (".", ",", "B", "+", "-", "$"):
            size += 1
        elif c == "V":
            pass  # implied decimal, no display position
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
    """Extract the value after 'KEYWORD. value.' or 'KEYWORD. value'."""
    # Remove keyword, then strip dots and whitespace
    idx = line.upper().index(keyword.upper()) + len(keyword)
    rest = line[idx:].strip().lstrip(".").strip().rstrip(".")
    return rest.strip()


# --- ENVIRONMENT DIVISION ---

_SELECT_RE = re.compile(
    r"SELECT\s+([\w-]+)\s+ASSIGN\s+TO\s+[\"']?([\w.\-]+)[\"']?",
    re.IGNORECASE,
)


def parse_environment(lines: list[str]) -> list[FileControl]:
    """Extract SELECT/ASSIGN file controls."""
    combined = " ".join(l.strip() for l in lines)
    controls: list[FileControl] = []
    for m in _SELECT_RE.finditer(combined):
        controls.append(FileControl(
            select_name=m.group(1).upper(),
            assign_to=m.group(2),
        ))
    return controls


# --- DATA DIVISION ---

_LEVEL_RE = re.compile(r"^(\d{1,2})\s+([\w-]+)")
_PIC_RE = re.compile(r"PIC(?:TURE)?\s+(S?[0-9XAVZBS().,+\-$CRDB]+)", re.IGNORECASE)
_VALUE_RE = re.compile(r'VALUE\s+("[^"]*"|\'[^\']*\'|[^\s.]+)(?:\.|$|\s)', re.IGNORECASE)
_OCCURS_RE = re.compile(r"OCCURS\s+(\d+)", re.IGNORECASE)
_REDEFINES_RE = re.compile(r"REDEFINES\s+([\w-]+)", re.IGNORECASE)


def parse_data_division(lines: list[str]) -> tuple[list[DataItem], list[DataItem]]:
    """Parse DATA DIVISION into file section and working-storage items."""
    section = "UNKNOWN"
    file_items: list[DataItem] = []
    ws_items: list[DataItem] = []

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

        item = _parse_data_item(line)
        if item is None:
            continue

        if section == "FILE":
            file_items.append(item)
        elif section == "WS":
            ws_items.append(item)

    # Build hierarchy
    file_items = _build_hierarchy(file_items)
    ws_items = _build_hierarchy(ws_items)
    return file_items, ws_items


def _parse_data_item(line: str) -> DataItem | None:
    """Parse a single data item line."""
    stripped = line.strip()
    if not stripped:
        return None

    level_m = _LEVEL_RE.match(stripped)
    if not level_m:
        return None

    level = int(level_m.group(1))
    name = level_m.group(2).upper()

    # Skip 88-level condition names
    if level == 88:
        return None

    pic: PicClause | None = None
    pic_m = _PIC_RE.search(stripped)
    if pic_m:
        pic = parse_pic(pic_m.group(1).strip().rstrip("."))

    value: str | None = None
    value_m = _VALUE_RE.search(stripped)
    if value_m:
        value = value_m.group(1).strip().strip('"').strip("'")

    occurs: int | None = None
    occurs_m = _OCCURS_RE.search(stripped)
    if occurs_m:
        occurs = int(occurs_m.group(1))

    redefines: str | None = None
    redefines_m = _REDEFINES_RE.search(stripped)
    if redefines_m:
        redefines = redefines_m.group(1).upper()

    return DataItem(
        level=level,
        name=name,
        pic=pic,
        value=value,
        occurs=occurs,
        redefines=redefines,
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


# --- PROCEDURE DIVISION ---

_PARAGRAPH_RE = re.compile(r"^([\w-]+)\.$")
_VERB_RE = re.compile(r"^([\w-]+)")

# Verbs we explicitly recognize
KNOWN_VERBS = frozenset({
    "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
    "DISPLAY", "ACCEPT", "PERFORM", "GO", "IF", "ELSE", "EVALUATE",
    "WHEN", "READ", "WRITE", "OPEN", "CLOSE", "CALL", "STOP",
    "SET", "STRING", "UNSTRING", "INSPECT", "INITIALIZE",
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
    "NOT", "END-WRITE", "END-CALL", "END-STRING",
})


def parse_procedure(lines: list[str]) -> list[Paragraph]:
    """Parse PROCEDURE DIVISION into paragraphs and statements."""
    paragraphs: list[Paragraph] = []
    current_para: Paragraph | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Strip trailing period for paragraph detection
        para_m = _PARAGRAPH_RE.match(stripped)
        if para_m:
            candidate = para_m.group(1).upper()
            # Check it looks like a paragraph name (not a standalone verb)
            if candidate not in KNOWN_VERBS:
                current_para = Paragraph(name=candidate)
                paragraphs.append(current_para)
                continue

        if current_para is None:
            # Statements before any paragraph — create implicit main
            current_para = Paragraph(name="__MAIN__")
            paragraphs.append(current_para)

        # Parse statements from this line
        stmts = _parse_statements(stripped)
        current_para.statements.extend(stmts)

    return paragraphs


def _split_operands(text: str) -> list[str]:
    """Split operand text into tokens, preserving quoted strings as single tokens."""
    tokens: list[str] = []
    current = ""
    in_quote: str | None = None

    for ch in text:
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

    return tokens


def _parse_statements(line: str) -> list[CobolStatement]:
    """Parse one logical line into statement(s).

    Handles simple single-verb lines. Multi-statement lines
    (separated by periods or scope terminators) are kept as one
    statement for simplicity in the MVP.
    """
    stripped = line.strip().rstrip(".")
    if not stripped:
        return []

    verb_m = _VERB_RE.match(stripped)
    if not verb_m:
        return []

    verb = verb_m.group(1).upper()
    rest = stripped[verb_m.end():].strip()

    # Split remaining text into operands, preserving quoted strings
    operands = _split_operands(rest) if rest else []

    return [CobolStatement(verb=verb, raw_text=line.strip(), operands=operands)]


# --- Main parse entry point ---

def parse_cobol(source: str, source_path: str = "") -> CobolProgram:
    """Parse COBOL source text into a CobolProgram AST."""
    logical_lines = preprocess_lines(source)
    divisions = split_divisions(logical_lines)

    program_id, author = parse_identification(divisions["IDENTIFICATION"])
    file_controls = parse_environment(divisions["ENVIRONMENT"])
    file_section, working_storage = parse_data_division(divisions["DATA"])
    paragraphs = parse_procedure(divisions["PROCEDURE"])

    return CobolProgram(
        program_id=program_id,
        source_path=source_path,
        author=author,
        file_controls=file_controls,
        file_section=file_section,
        working_storage=working_storage,
        paragraphs=paragraphs,
        raw_lines=source.splitlines(),
    )


def parse_cobol_file(path: str | Path) -> CobolProgram:
    """Parse a COBOL file from disk."""
    p = Path(path)
    source = p.read_text(encoding="utf-8", errors="replace")
    return parse_cobol(source, source_path=str(p))
