"""Generate Python code from extracted EXEC DLI blocks.

Translates structured DliBlock metadata into Python code that models
IMS DL/I hierarchical database operations using a dict-based API.

DL/I verbs map to database operations:
  GU/GHU  — Get Unique (by key) → db.get(segment, key)
  GN/GHN  — Get Next (sequential) → cursor.fetchone()
  GNP/GHNP — Get Next within Parent → cursor.fetchone() (filtered)
  ISRT    — Insert → db.insert(segment, data)
  REPL    — Replace → db.update(segment, data)
  DLET    — Delete → db.delete(segment, key)
"""

from __future__ import annotations

from .models import DliBlock
from .utils import _to_python_name as _cobol_to_python_name


def generate_dli_imports() -> list[str]:
    """Return import lines for DLI support."""
    return [
        "# DLI/IMS — configure with your hierarchical DB adapter",
        "# Example: from your_ims_adapter import DliDatabase",
        "",
    ]


def generate_dli_init() -> list[str]:
    """Return __init__ lines for DLI setup."""
    return [
        '        # DLI/IMS connection — configure for your database',
        '        # Example: self._dli_db = DliDatabase(psb_name)',
        '        self._dli_db = None  # TODO(high): configure DLI/IMS connection',
        '        self._dli_status = ""  # GE=not found, spaces=success',
    ]


def translate_dli_block(block: DliBlock) -> list[str]:
    """Translate a single DliBlock into Python code lines."""
    dli_type = block.dli_type.upper()
    seg = block.segment_name or "segment"
    py_seg = _cobol_to_python_name(seg)

    match dli_type:
        case "GU" | "GHU":
            return _translate_get_unique(block, py_seg)
        case "GN" | "GHN":
            return _translate_get_next(block, py_seg)
        case "GNP" | "GHNP":
            return _translate_get_next_parent(block, py_seg)
        case "ISRT":
            return _translate_insert(block, py_seg)
        case "REPL":
            return _translate_replace(block, py_seg)
        case "DLET":
            return _translate_delete(block, py_seg)
        case _:
            return [f"# DLI: (unrecognized type: {dli_type})", f"# {block.raw_dli}"]


def _translate_get_unique(block: DliBlock, py_seg: str) -> list[str]:
    hold = "hold=True" if "H" in block.dli_type else ""
    lines = [f"# DLI: {block.dli_type} {block.segment_name}"]

    ssa_arg = ""
    if block.ssa_fields:
        ssa_arg = f", ssa={block.ssa_fields!r}"
    lines.append(
        f"_dli_row = self._dli_db.get_unique('{py_seg}'{ssa_arg}"
        f"{', ' + hold if hold else ''})"
    )
    lines.append("if _dli_row is None:")
    lines.append('    self._dli_status = "GE"  # not found')
    lines.append("else:")
    if block.host_variables:
        py_var = _cobol_to_python_name(block.host_variables[0])
        lines.append(f"    self.data.{py_var}.set(_dli_row)")
    lines.append('    self._dli_status = "  "  # success')
    return lines


def _translate_get_next(block: DliBlock, py_seg: str) -> list[str]:
    lines = [f"# DLI: {block.dli_type} {block.segment_name}"]
    lines.append(f"_dli_row = self._dli_db.get_next('{py_seg}')")
    lines.append("if _dli_row is None:")
    lines.append('    self._dli_status = "GB"  # end of database')
    lines.append("else:")
    if block.host_variables:
        py_var = _cobol_to_python_name(block.host_variables[0])
        lines.append(f"    self.data.{py_var}.set(_dli_row)")
    lines.append('    self._dli_status = "  "  # success')
    return lines


def _translate_get_next_parent(block: DliBlock, py_seg: str) -> list[str]:
    lines = [f"# DLI: {block.dli_type} {block.segment_name} (within parent)"]
    lines.append(f"_dli_row = self._dli_db.get_next('{py_seg}', within_parent=True)")
    lines.append("if _dli_row is None:")
    lines.append('    self._dli_status = "GE"  # not found in parent')
    lines.append("else:")
    if block.host_variables:
        py_var = _cobol_to_python_name(block.host_variables[0])
        lines.append(f"    self.data.{py_var}.set(_dli_row)")
    lines.append('    self._dli_status = "  "  # success')
    return lines


def _translate_insert(block: DliBlock, py_seg: str) -> list[str]:
    lines = [f"# DLI: ISRT {block.segment_name}"]
    data_arg = ""
    if block.host_variables:
        py_var = _cobol_to_python_name(block.host_variables[0])
        data_arg = f", data=self.data.{py_var}.value"
    lines.append(f"self._dli_db.insert('{py_seg}'{data_arg})")
    lines.append('self._dli_status = "  "  # success')
    return lines


def _translate_replace(block: DliBlock, py_seg: str) -> list[str]:
    lines = [f"# DLI: REPL {block.segment_name}"]
    data_arg = ""
    if block.host_variables:
        py_var = _cobol_to_python_name(block.host_variables[0])
        data_arg = f", data=self.data.{py_var}.value"
    lines.append(f"self._dli_db.replace('{py_seg}'{data_arg})")
    lines.append('self._dli_status = "  "  # success')
    return lines


def _translate_delete(block: DliBlock, py_seg: str) -> list[str]:
    lines = [f"# DLI: DLET {block.segment_name}"]
    lines.append(f"self._dli_db.delete('{py_seg}')")
    lines.append('self._dli_status = "  "  # success')
    return lines
