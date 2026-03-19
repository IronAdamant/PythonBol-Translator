"""COBOL Report Writer verb translators (INITIATE, GENERATE, TERMINATE).

Translates REPORT WRITER constructs into Python code that produces
formatted text output, approximating the COBOL Report Writer's
automatic page/control-break handling with explicit print statements.

Pipeline position: Called by mapper.py for INITIATE, GENERATE, TERMINATE verbs.
"""

from __future__ import annotations

import re

from .models import ReportDescription, ReportField, ReportGroup
from .utils import _to_python_name


def _find_report(reports: list[ReportDescription], name: str) -> ReportDescription | None:
    """Find a ReportDescription by name (case-insensitive)."""
    upper = name.upper()
    for rd in reports:
        if rd.name.upper() == upper:
            return rd
    return None


def _field_value_expr(field: ReportField) -> str:
    """Generate a Python expression for a report field's value."""
    if field.value:
        return repr(field.value)
    if field.source:
        # Handle subscript syntax like StateName(StateNum)
        src = field.source
        if "(" in src:
            base, rest = src.split("(", 1)
            idx = rest.rstrip(")")
            return f"str(self.data.{_to_python_name(base)}[int(self.data.{_to_python_name(idx)}.value) - 1].value)"
        if src.upper() == "PAGE-COUNTER":
            return "str(self._rw_page_counter)"
        return f"str(self.data.{_to_python_name(src)}.value)"
    if field.sum_field:
        py_sum = _to_python_name(field.sum_field)
        return f"str(self._rw_sums.get('{py_sum}', 0))"
    return "''"


def _format_line_expr(group: ReportGroup, line_idx: int) -> list[str]:
    """Generate Python lines to build and print a single report line.

    Uses string formatting with column positions to approximate
    COBOL Report Writer LINE/COLUMN layout.
    """
    if line_idx >= len(group.lines):
        return []

    rline = group.lines[line_idx]
    lines: list[str] = []

    if not rline.fields:
        lines.append("self._rw_output.append('')")
        return lines

    # Find maximum column to determine line width
    max_col = max((f.column for f in rline.fields if f.column), default=80)
    max_width = max_col + 40  # padding beyond last column

    lines.append(f"_rw_line = ' ' * {max_width}")
    for field in rline.fields:
        col = max(field.column - 1, 0)  # COBOL columns are 1-based
        val_expr = _field_value_expr(field)
        # Extract size from PIC for formatting
        pic_size = _pic_display_size(field.pic) if field.pic else 20
        lines.append(
            f"_rw_val = {val_expr}"
        )
        lines.append(
            f"_rw_line = _rw_line[:{col}] + str(_rw_val)[:{pic_size}].ljust({pic_size}) + _rw_line[{col + pic_size}:]"
        )

    lines.append("self._rw_output.append(_rw_line.rstrip())")
    return lines


def _pic_display_size(pic: str) -> int:
    """Estimate the display width from a PIC string."""
    if not pic:
        return 10
    # Remove parenthesized repeats and count characters
    expanded = re.sub(r"(\w)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), pic)
    return max(len(expanded), 1)


def _groups_by_type(rd: ReportDescription, type_prefix: str) -> list[ReportGroup]:
    """Return report groups whose type starts with the given prefix."""
    prefix = type_prefix.upper()
    return [g for g in rd.groups if g.type_clause.upper().startswith(prefix)]


def translate_initiate(ops: list[str], reports: list[ReportDescription]) -> list[str]:
    """Translate INITIATE report-name.

    Sets up output buffer, page counter, and SUM accumulators.
    """
    if not ops:
        return ["# INITIATE: no report name specified"]

    report_name = ops[0]
    rd = _find_report(reports, report_name)

    lines: list[str] = [
        f"# INITIATE {report_name} (Report Writer)",
        "self._rw_output = []  # report output lines",
        "self._rw_page_counter = 1",
        "self._rw_line_counter = 0",
        "self._rw_sums = {}  # SUM accumulators",
    ]

    if rd:
        # Initialize SUM fields to 0
        for group in rd.groups:
            for rline in group.lines:
                for field in rline.fields:
                    if field.sum_field:
                        py_sum = _to_python_name(field.sum_field)
                        lines.append(f"self._rw_sums['{py_sum}'] = 0")
                        # Also track the named field for roll-forward
                        if field.name:
                            py_name = _to_python_name(field.name)
                            lines.append(f"self._rw_sums['{py_name}'] = 0")

        # Print REPORT HEADING groups
        rh_groups = _groups_by_type(rd, "REPORT HEADING")
        for group in rh_groups:
            lines.append("# Report Heading")
            for idx in range(len(group.lines)):
                lines.extend(_format_line_expr(group, idx))

        # Print first PAGE HEADING
        ph_groups = _groups_by_type(rd, "PAGE HEADING")
        if ph_groups:
            lines.append("# Page Heading")
            for group in ph_groups:
                for idx in range(len(group.lines)):
                    lines.extend(_format_line_expr(group, idx))

    return lines


def translate_generate(ops: list[str], reports: list[ReportDescription]) -> list[str]:
    """Translate GENERATE detail-line-name.

    Generates the detail line and accumulates SUM fields.
    """
    if not ops:
        return ["# GENERATE: no detail line specified"]

    detail_name = ops[0].upper()

    # Find the report that contains this detail group
    rd = None
    detail_group = None
    for r in reports:
        for g in r.groups:
            if g.name.upper() == detail_name:
                rd = r
                detail_group = g
                break
        if detail_group:
            break

    # Fallback: look for any DETAIL group if name matches report name
    if not detail_group:
        for r in reports:
            if r.name.upper() == detail_name:
                rd = r
                for g in r.groups:
                    if g.type_clause.upper().startswith("DETAIL"):
                        detail_group = g
                        break
                break

    if not rd or not detail_group:
        return [
            f"# GENERATE {ops[0]}",
            f"# TODO(high): Report Writer detail group '{ops[0]}' not found in REPORT SECTION",
        ]

    lines: list[str] = [f"# GENERATE {ops[0]}"]

    # --- Control break detection ---
    if rd.controls:
        for ctrl in rd.controls:
            if ctrl.upper() == "FINAL":
                continue
            py_ctrl = _to_python_name(ctrl)
            prev_attr = f"_rw_prev_{py_ctrl}"
            lines.append(f"if hasattr(self, '{prev_attr}') and self.data.{py_ctrl}.value != self.{prev_attr}:")
            # Emit matching CONTROL FOOTING groups
            cf_groups = [g for g in rd.groups
                         if g.type_clause.upper().startswith("CONTROL FOOTING")
                         and ctrl.upper() in g.type_clause.upper()]
            if cf_groups:
                lines.append(f"    # Control Footing for {ctrl}")
                for group in cf_groups:
                    for idx in range(len(group.lines)):
                        for fl in _format_line_expr(group, idx):
                            lines.append(f"    {fl}")
            # Emit matching CONTROL HEADING groups
            ch_groups = [g for g in rd.groups
                         if g.type_clause.upper().startswith("CONTROL HEADING")
                         and ctrl.upper() in g.type_clause.upper()]
            if ch_groups:
                lines.append(f"    # Control Heading for {ctrl}")
                for group in ch_groups:
                    for idx in range(len(group.lines)):
                        for fl in _format_line_expr(group, idx):
                            lines.append(f"    {fl}")
            # Save current value for next comparison
            lines.append(f"self.{prev_attr} = self.data.{py_ctrl}.value")

    # Accumulate SUM fields from the detail data
    for group in rd.groups:
        for rline in group.lines:
            for field in rline.fields:
                if field.sum_field:
                    py_sum = _to_python_name(field.sum_field)
                    src = field.sum_field
                    if "(" in src:
                        base, rest = src.split("(", 1)
                        idx = rest.rstrip(")")
                        py_idx = _to_python_name(idx)
                        val_expr = f"self.data.{_to_python_name(base)}[int(self.data.{py_idx}.value) - 1].value"
                    else:
                        val_expr = f"self.data.{_to_python_name(src)}.value"
                    lines.append(f"self._rw_sums['{py_sum}'] = self._rw_sums.get('{py_sum}', 0) + {val_expr}")
                    # Also update named field accumulator
                    if field.name:
                        py_name = _to_python_name(field.name)
                        lines.append(f"self._rw_sums['{py_name}'] = self._rw_sums.get('{py_name}', 0) + {val_expr}")

    # --- Page break detection ---
    if rd.page_limit > 0 or rd.last_detail > 0:
        limit = rd.last_detail if rd.last_detail > 0 else rd.page_limit
        lines.append(f"if self._rw_line_counter >= {limit}:")
        # Page footing
        pf_groups = _groups_by_type(rd, "PAGE FOOTING")
        if pf_groups:
            lines.append("    # Page Footing")
            for group in pf_groups:
                for idx in range(len(group.lines)):
                    for fl in _format_line_expr(group, idx):
                        lines.append(f"    {fl}")
        # New page heading
        ph_groups = _groups_by_type(rd, "PAGE HEADING")
        lines.append("    self._rw_page_counter += 1")
        lines.append("    self._rw_line_counter = 0")
        if ph_groups:
            lines.append("    # Page Heading")
            for group in ph_groups:
                for idx in range(len(group.lines)):
                    for fl in _format_line_expr(group, idx):
                        lines.append(f"    {fl}")

    # Format and print the detail line
    lines.append("# Detail line")
    for idx in range(len(detail_group.lines)):
        lines.extend(_format_line_expr(detail_group, idx))

    lines.append("self._rw_line_counter += 1")
    return lines


def translate_terminate(ops: list[str], reports: list[ReportDescription]) -> list[str]:
    """Translate TERMINATE report-name.

    Prints any CONTROL FOOTING FINAL and REPORT FOOTING groups,
    then writes accumulated output to the report file.
    """
    if not ops:
        return ["# TERMINATE: no report name specified"]

    report_name = ops[0]
    rd = _find_report(reports, report_name)

    lines: list[str] = [f"# TERMINATE {report_name} (Report Writer)"]

    if rd:
        # Print CONTROL FOOTING FINAL
        cf_final = [g for g in rd.groups if "FINAL" in g.type_clause.upper()
                     and "CONTROL FOOTING" in g.type_clause.upper()]
        for group in cf_final:
            lines.append("# Control Footing FINAL")
            for idx in range(len(group.lines)):
                lines.extend(_format_line_expr(group, idx))

        # Print REPORT FOOTING
        rf_groups = _groups_by_type(rd, "REPORT FOOTING")
        for group in rf_groups:
            lines.append("# Report Footing")
            for idx in range(len(group.lines)):
                lines.extend(_format_line_expr(group, idx))

    # Write output to report file
    rpt_filename = report_name.lower().replace("-", "_") + "_report.txt"
    lines.extend([
        f"# Write report output to file",
        f"with open({rpt_filename!r}, 'w') as _rw_f:",
        "    for _rw_line in self._rw_output:",
        "        _rw_f.write(_rw_line + '\\n')",
    ])

    return lines
