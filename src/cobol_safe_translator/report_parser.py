"""REPORT SECTION parser for COBOL Report Writer.

Parses RD (Report Description) entries and their associated report groups
(TYPE IS DETAIL, CONTROL HEADING, CONTROL FOOTING, PAGE HEADING, etc.)
into structured ReportDescription / ReportGroup / ReportLine / ReportField
model objects.

Pipeline position: Called by parser.py during DATA DIVISION parsing.
"""

from __future__ import annotations

import re

from .models import (
    ReportDescription,
    ReportField,
    ReportGroup,
    ReportLine,
)


# --- RD clause patterns ---

_RD_NAME_RE = re.compile(r"^RD\s+([\w-]+)", re.IGNORECASE)
_CONTROLS_RE = re.compile(
    r"CONTROLS?\s+(?:IS|ARE)\s+(.*?)(?:PAGE|HEADING|FIRST|LAST|FOOTING|\.|$)",
    re.IGNORECASE,
)
_PAGE_LIMIT_RE = re.compile(r"PAGE\s+LIMITS?\s+(?:IS|ARE)?\s*(\d+)", re.IGNORECASE)
_HEADING_RE = re.compile(r"(?<!\w)HEADING\s+(\d+)", re.IGNORECASE)
_FIRST_DETAIL_RE = re.compile(r"FIRST\s+DETAIL\s+(\d+)", re.IGNORECASE)
_LAST_DETAIL_RE = re.compile(r"LAST\s+DETAIL\s+(\d+)", re.IGNORECASE)
_FOOTING_RE = re.compile(r"(?<!\w)FOOTING\s+(\d+)", re.IGNORECASE)

# --- Report group (01-level) patterns ---

_TYPE_RE = re.compile(
    r"TYPE\s+(?:IS\s+)?"
    r"(REPORT\s+HEADING|REPORT\s+FOOTING|"
    r"PAGE\s+HEADING|PAGE\s+FOOTING|"
    r"CONTROL\s+HEADING|CONTROL\s+FOOTING|"
    r"DETAIL|DE)"
    r"(?:\s+(FINAL|(?!NEXT\b)[\w-]+))?",
    re.IGNORECASE,
)
_NEXT_GROUP_RE = re.compile(
    r"NEXT\s+GROUP\s+(?:IS\s+)?(PLUS\s+)?(\d+)", re.IGNORECASE
)

# --- Line and field patterns ---

_LINE_ABS_RE = re.compile(r"LINE\s+(?:NUMBER\s+)?(?:IS\s+)?(\d+)", re.IGNORECASE)
_LINE_PLUS_RE = re.compile(r"LINE\s+(?:NUMBER\s+)?(?:IS\s+)?PLUS\s+(\d+)", re.IGNORECASE)
_COLUMN_RE = re.compile(r"COLUMN\s+(?:NUMBER\s+)?(?:IS\s+)?(\d+)", re.IGNORECASE)
_PIC_RE = re.compile(r"PIC(?:TURE)?\s+(?:IS\s+)?([\w$.,+\-*/()\s]+?)(?=\s+(?:SOURCE|SUM|VALUE|GROUP|COLUMN|LINE|\.|$)|\.\s*$|$)", re.IGNORECASE)
_SOURCE_RE = re.compile(r"SOURCE\s+(?:IS\s+)?([\w-]+(?:\([\w-]+\))?)", re.IGNORECASE)
_SUM_RE = re.compile(r"SUM\s+([\w-]+)", re.IGNORECASE)
_VALUE_RE = re.compile(r'VALUE\s+(?:IS\s+)?(?:ALL\s+)?((?:"[^"]*"|\'[^\']*\'|[^\s.]+))', re.IGNORECASE)
_GROUP_INDICATE_RE = re.compile(r"GROUP\s+INDICATE", re.IGNORECASE)
_LEVEL_RE = re.compile(r"^(\d{1,2})\s+([\w-]+)?")


def parse_report_section(lines: list[str]) -> list[ReportDescription]:
    """Parse REPORT SECTION lines into ReportDescription objects.

    Expects lines starting from the REPORT SECTION header through to the
    end of the section (before the next DATA DIVISION section).
    """
    # Join into one text block, then split on RD entries
    combined = " ".join(l.strip() for l in lines)

    # Split on RD keyword boundaries
    rd_blocks = re.split(r"(?=\bRD\s)", combined, flags=re.IGNORECASE)

    reports: list[ReportDescription] = []
    for block in rd_blocks:
        block = block.strip()
        if not block:
            continue
        m = _RD_NAME_RE.match(block)
        if not m:
            continue
        rd = _parse_rd_block(block, m.group(1).upper())
        reports.append(rd)

    return reports


def _parse_rd_block(block: str, rd_name: str) -> ReportDescription:
    """Parse a single RD block (from RD to just before the next RD or section end)."""
    rd = ReportDescription(name=rd_name)

    # Extract RD-level clauses
    controls_m = _CONTROLS_RE.search(block)
    if controls_m:
        raw_controls = controls_m.group(1).strip()
        rd.controls = [
            c.strip().upper() for c in re.split(r"[\s,]+", raw_controls)
            if c.strip() and c.strip().upper() not in ("ARE", "IS", "AND")
        ]

    page_m = _PAGE_LIMIT_RE.search(block)
    if page_m:
        rd.page_limit = int(page_m.group(1))

    heading_m = _HEADING_RE.search(block)
    if heading_m:
        rd.heading = int(heading_m.group(1))

    first_m = _FIRST_DETAIL_RE.search(block)
    if first_m:
        rd.first_detail = int(first_m.group(1))

    last_m = _LAST_DETAIL_RE.search(block)
    if last_m:
        rd.last_detail = int(last_m.group(1))

    footing_m = _FOOTING_RE.search(block)
    if footing_m:
        rd.footing = int(footing_m.group(1))

    # Split into 01-level groups and parse each
    # Find 01 level boundaries (01 followed by name or TYPE)
    group_starts = [m.start() for m in re.finditer(r"(?<!\d)01\s+", block)]
    for idx, start in enumerate(group_starts):
        end = group_starts[idx + 1] if idx + 1 < len(group_starts) else len(block)
        group_text = block[start:end].strip()
        group = _parse_report_group(group_text)
        if group:
            rd.groups.append(group)

    return rd


def _parse_report_group(text: str) -> ReportGroup | None:
    """Parse a single 01-level report group entry."""
    group = ReportGroup()

    # Extract group name (01 name TYPE IS ...)
    level_m = _LEVEL_RE.match(text)
    if level_m and level_m.group(2):
        name = level_m.group(2).upper()
        if name != "TYPE":
            group.name = name

    type_m = _TYPE_RE.search(text)
    if not type_m:
        return None  # not a report group

    type_str = type_m.group(1).upper()
    qualifier = type_m.group(2) or ""
    if qualifier:
        type_str = f"{type_str} {qualifier.upper()}"
    # Normalize abbreviated type
    if type_str.startswith("DE ") or type_str == "DE":
        type_str = "DETAIL" + type_str[2:]
    group.type_clause = type_str

    next_m = _NEXT_GROUP_RE.search(text)
    if next_m:
        group.next_group = f"PLUS {next_m.group(2)}" if next_m.group(1) else next_m.group(2)

    # Parse 02-level lines and their 03-level fields
    # Split on 02 level boundaries
    line_starts = [m.start() for m in re.finditer(r"(?<!\d)02\s+", text)]
    for idx, start in enumerate(line_starts):
        end = line_starts[idx + 1] if idx + 1 < len(line_starts) else len(text)
        line_text = text[start:end].strip()
        report_line = _parse_report_line(line_text)
        if report_line:
            group.lines.append(report_line)

    return group


def _parse_report_line(text: str) -> ReportLine | None:
    """Parse a 02-level LINE entry with its 03-level fields."""
    line = ReportLine()

    # Determine line number (absolute or PLUS)
    plus_m = _LINE_PLUS_RE.search(text)
    if plus_m:
        line.line_number = f"PLUS {plus_m.group(1)}"
    else:
        abs_m = _LINE_ABS_RE.search(text)
        if abs_m:
            line.line_number = int(abs_m.group(1))

    # Split on 03 level boundaries for fields
    field_starts = [m.start() for m in re.finditer(r"(?<!\d)03\s+", text)]
    for idx, start in enumerate(field_starts):
        end = field_starts[idx + 1] if idx + 1 < len(field_starts) else len(text)
        field_text = text[start:end].strip()
        report_field = _parse_report_field(field_text)
        if report_field:
            line.fields.append(report_field)

    return line if line.fields else None


def _parse_report_field(text: str) -> ReportField | None:
    """Parse a 03-level field entry (COLUMN, PIC, SOURCE/SUM/VALUE)."""
    rf = ReportField()

    # Extract field name (03 name COLUMN ...)
    level_m = _LEVEL_RE.match(text)
    if level_m and level_m.group(2):
        name = level_m.group(2).upper()
        if name != "COLUMN":
            rf.name = name

    col_m = _COLUMN_RE.search(text)
    if col_m:
        rf.column = int(col_m.group(1))

    pic_m = _PIC_RE.search(text)
    if pic_m:
        rf.pic = pic_m.group(1).strip().rstrip(".")

    source_m = _SOURCE_RE.search(text)
    if source_m:
        rf.source = source_m.group(1).upper()

    sum_m = _SUM_RE.search(text)
    if sum_m:
        rf.sum_field = sum_m.group(1).upper()

    value_m = _VALUE_RE.search(text)
    if value_m:
        val = value_m.group(1).strip()
        # Strip quotes
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            val = val[1:-1]
        rf.value = val

    if _GROUP_INDICATE_RE.search(text):
        rf.group_indicate = True

    return rf if (rf.pic or rf.source or rf.sum_field or rf.value) else None
