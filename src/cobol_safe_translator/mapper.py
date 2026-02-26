"""Translates a CobolProgram AST into Python source code.

Pipeline position: Parser -> AST -> Analyzer -> **Mapper** -> Python source

Generated code uses adapter classes (CobolDecimal, CobolString, FileAdapter)
to preserve COBOL semantics.
"""

from __future__ import annotations

import keyword
import re
import textwrap
from datetime import datetime

from .block_translator import (
    is_inline_evaluate,
    is_inline_if,
    translate_evaluate_block,
    translate_if_block,
    translate_inline_evaluate,
    translate_inline_if,
)
from .models import (
    CobolProgram,
    CobolStatement,
    DataItem,
    Paragraph,
    PicCategory,
    SensitivityFlag,
    SoftwareMap,
)
from . import statement_translators as st


def _is_numeric_literal(s: str) -> bool:
    """Check if a string is a numeric literal (integer or decimal)."""
    if not s:
        return False
    # Handle sign prefix
    check = s[1:] if s[0] in ("-", "+") and len(s) > 1 else s
    # Must have at least one digit and only digits/one decimal point
    parts = check.split(".")
    if len(parts) == 1:
        return parts[0].isdigit()
    if len(parts) == 2:
        return (parts[0].isdigit() or parts[0] == "") and (parts[1].isdigit() or parts[1] == "")
    return False


def _to_python_name(cobol_name: str) -> str:
    """Convert COBOL data name to a valid Python identifier.

    Handles: hyphens -> underscores, digit-leading names, Python keyword collisions.
    """
    name = cobol_name.lower().replace("-", "_")
    # Prefix with underscore if name starts with a digit
    if name and name[0].isdigit():
        name = f"f_{name}"
    # Suffix with underscore if name collides with a Python keyword
    if keyword.iskeyword(name):
        name = f"{name}_"
    # Remove any remaining invalid characters
    name = re.sub(r"[^\w]", "_", name)
    return name or "_unnamed"


_RESERVED_METHOD_NAMES = frozenset({"run", "__init__", "data"})


def _to_method_name(para_name: str) -> str:
    """Convert COBOL paragraph name to Python method name."""
    name = _to_python_name(para_name)
    if name in _RESERVED_METHOD_NAMES:
        name = f"para_{name}"
    return name


def _indent(text: str, level: int = 1) -> str:
    """Indent text by the given number of 4-space levels."""
    return textwrap.indent(text, "    " * level)


class PythonMapper:
    """Generates Python source from a CobolProgram AST and its analysis."""

    def __init__(self, software_map: SoftwareMap) -> None:
        self.program = software_map.program
        self.smap = software_map
        self._sensitive_names: set[str] = {
            f.data_name.upper() for f in software_map.sensitivities
        }
        self._sensitivity_lookup: dict[str, SensitivityFlag] = {
            f.data_name.upper(): f for f in software_map.sensitivities
        }

    def generate(self) -> str:
        """Generate the complete Python module source."""
        if not self.program.program_id:
            self._program_id = "UNNAMED"
        else:
            self._program_id = self.program.program_id
        parts: list[str] = []
        parts.append(self._header())
        parts.append(self._imports())
        parts.append(self._data_class())
        parts.append(self._program_class())
        parts.append(self._main_block())
        return "\n".join(parts)

    def _header(self) -> str:
        lines = [
            '"""',
            f"Auto-generated Python translation of COBOL program: {self._program_id}",
            f"Source: {self.program.source_path}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "WARNING: This is a machine-generated skeleton. Manual review is REQUIRED",
            "before using in production. See TODO comments for items needing attention.",
            '"""',
            "",
        ]
        return "\n".join(lines)

    def _imports(self) -> str:
        lines = [
            "from __future__ import annotations",
            "",
            "from dataclasses import dataclass, field",
            "from decimal import Decimal",
            "",
            "# Runtime adapters — install cobol-safe-translator or copy adapters.py",
            "from cobol_safe_translator.adapters import CobolDecimal, CobolString, FileAdapter",
            "",
            "",
        ]
        return "\n".join(lines)

    def _data_class(self) -> str:
        """Generate @dataclass for WORKING-STORAGE, FILE SECTION, and LINKAGE data items."""
        all_items = self.program.working_storage + self.program.file_section + self.program.linkage_section
        class_name = _to_python_name(self._program_id).title().replace('_', '') + "Data"

        if not all_items:
            # Emit an empty dataclass so the program class can reference it
            return f"@dataclass\nclass {class_name}:\n    pass\n\n"

        lines = ["@dataclass"]
        lines.append(f"class {class_name}:")
        lines.append('    """Working-storage and file section data items."""')
        lines.append("")

        self._field_name_counts: dict[str, int] = {}
        for item in all_items:
            lines.extend(self._data_item_fields(item, indent=1))

        lines.append("")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _translate_figurative(value: str, numeric: bool = True) -> str:
        """Translate COBOL figurative constants to Python values."""
        upper = value.upper().strip()
        if upper in ("ZEROS", "ZEROES", "ZERO"):
            return "0"
        if upper in ("SPACES", "SPACE"):
            return "" if numeric else " "
        if upper in ("HIGH-VALUES", "HIGH-VALUE"):
            return "0" if numeric else "\xff"
        if upper in ("LOW-VALUES", "LOW-VALUE"):
            return "0" if numeric else "\x00"
        return value

    def _data_item_fields(self, item: DataItem, indent: int = 1) -> list[str]:
        """Generate dataclass fields for a data item and its children."""
        lines: list[str] = []
        prefix = "    " * indent
        py_name = _to_python_name(item.name)

        # Deduplicate field names (e.g., multiple FILLER items)
        if py_name in self._field_name_counts:
            self._field_name_counts[py_name] += 1
            count = self._field_name_counts[py_name]
            py_name = f"{py_name}_{count}"
        else:
            self._field_name_counts[py_name] = 0

        # Sensitivity warning
        if item.name.upper() in self._sensitive_names:
            flag = self._sensitivity_lookup[item.name.upper()]
            lines.append(
                f"{prefix}# WARNING [{flag.level.value.upper()}]: "
                f"{flag.reason} — {flag.data_name} matches pattern '{flag.pattern_matched}'"
            )

        if item.children:
            # Group item — add a comment
            lines.append(f"{prefix}# Group: {item.name} (level {item.level:02d})")
            for child in item.children:
                lines.extend(self._data_item_fields(child, indent))
        elif item.pic:
            if item.pic.category in (PicCategory.NUMERIC, PicCategory.EDITED):
                dec = item.pic.decimals
                int_digits = item.pic.size - dec
                signed = "True" if item.pic.signed else "False"
                init = self._translate_figurative(item.value, numeric=True) if item.value else "0"
                lines.append(
                    f"{prefix}{py_name}: CobolDecimal = field("
                    f"default_factory=lambda: CobolDecimal({int_digits}, {dec}, {signed}, {init!r}))"
                )
            else:
                init = self._translate_figurative(item.value, numeric=False) if item.value else ""
                lines.append(
                    f"{prefix}{py_name}: CobolString = field("
                    f"default_factory=lambda: CobolString({item.pic.size}, {init!r}))"
                )
        else:
            # No PIC — group-level or filler
            lines.append(f"{prefix}# {item.name}: no PIC clause (group level)")

        return lines

    def _program_class(self) -> str:
        """Generate the main program class with paragraph methods."""
        class_name = _to_python_name(self._program_id).title().replace("_", "")
        data_class = f"{class_name}Data"

        lines = [f"class {class_name}Program:"]
        lines.append(f'    """Translated from COBOL program {self._program_id}."""')
        lines.append("")
        lines.append(f"    def __init__(self) -> None:")
        lines.append(f"        self.data = {data_class}()")

        # File adapters
        for fc in self.program.file_controls:
            py_name = _to_python_name(fc.select_name)
            lines.append(f'        self.{py_name} = FileAdapter("{fc.assign_to}")')

        lines.append("")

        # Generate methods for each paragraph
        for para in self.program.paragraphs:
            lines.append(self._paragraph_method(para))

        # run() method
        if self.program.paragraphs:
            first = _to_method_name(self.program.paragraphs[0].name)
            lines.append(f"    def run(self) -> None:")
            lines.append(f'        """Entry point — calls the first paragraph."""')
            lines.append(f"        self.{first}()")
            lines.append("")
        else:
            lines.append(f"    def run(self) -> None:")
            lines.append(f'        """Entry point — no paragraphs found."""')
            lines.append(f"        pass")
            lines.append("")

        lines.append("")
        return "\n".join(lines)

    def _paragraph_method(self, para: Paragraph) -> str:
        """Generate a method for a single COBOL paragraph."""
        method_name = _to_method_name(para.name)
        lines = [f"    def {method_name}(self) -> None:"]
        lines.append(f'        """Paragraph: {para.name}"""')

        if not para.statements:
            lines.append("        pass")
            lines.append("")
            return "\n".join(lines)

        i = 0
        while i < len(para.statements):
            stmt = para.statements[i]

            if stmt.verb == "IF":
                if is_inline_if(stmt):
                    block_lines = translate_inline_if(
                        stmt, self._translate_condition, indent=2,
                        translate_stmt_fn=self._translate_statement,
                    )
                    lines.extend(block_lines)
                    i += 1
                else:
                    block_lines, i = translate_if_block(
                        para.statements, i,
                        self._translate_statement,
                        self._translate_condition,
                        indent=2,
                    )
                    lines.extend(block_lines)
                continue

            if stmt.verb == "EVALUATE":
                if is_inline_evaluate(stmt):
                    block_lines = translate_inline_evaluate(
                        stmt, self._translate_condition,
                        self._resolve_operand, indent=2,
                    )
                    lines.extend(block_lines)
                    i += 1
                else:
                    block_lines, i = translate_evaluate_block(
                        para.statements, i,
                        self._translate_statement,
                        self._translate_condition,
                        self._resolve_operand,
                        indent=2,
                    )
                    lines.extend(block_lines)
                continue

            translated = self._translate_statement(stmt)
            for tl in translated:
                lines.append(f"        {tl}")
            i += 1

        lines.append("")
        return "\n".join(lines)

    def _translate_statement(self, stmt: CobolStatement) -> list[str]:
        """Translate a single COBOL statement to Python line(s)."""
        verb = stmt.verb
        ops = stmt.operands

        if verb == "DISPLAY":
            return self._translate_display(stmt)
        elif verb == "MOVE":
            return self._translate_move(ops)
        elif verb == "ADD":
            return self._translate_add(ops)
        elif verb == "SUBTRACT":
            return self._translate_subtract(ops)
        elif verb == "MULTIPLY":
            return self._translate_multiply(ops)
        elif verb == "DIVIDE":
            return self._translate_divide(ops)
        elif verb == "COMPUTE":
            return self._translate_compute(ops)
        elif verb == "PERFORM":
            return self._translate_perform(ops, stmt.raw_text)
        elif verb == "IF":
            return self._translate_if(stmt.raw_text)
        elif verb == "EVALUATE":
            return self._translate_evaluate(stmt.raw_text)
        elif verb in ("END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
                       "END-WRITE", "END-CALL", "END-STRING"):
            return [f"# {verb} (orphaned — normally consumed by block translator)"]
        elif verb == "ELSE":
            return [f"# else (orphaned — normally consumed by block translator)"]
        elif verb == "WHEN":
            return [f"# WHEN (orphaned — normally consumed by block translator): {stmt.raw_text}"]
        elif verb == "OPEN":
            return self._translate_open(ops)
        elif verb == "CLOSE":
            return self._translate_close(ops)
        elif verb == "READ":
            return self._translate_read(ops, stmt.raw_text)
        elif verb == "WRITE":
            return [f"# TODO(high): WRITE — file writing not supported (safety)", f"# {stmt.raw_text}"]
        elif verb == "CALL":
            return self._translate_call(ops)
        elif verb == "STOP":
            return ["return"]
        elif verb == "ACCEPT":
            return [f"# ACCEPT: {stmt.raw_text}", f"# TODO(high): ACCEPT — user input requires manual implementation"]
        elif verb == "REWRITE":
            record_name = ops[0] if ops else "RECORD"
            py_record = _to_python_name(record_name)
            file_hint = py_record.replace("_record", "_file").replace("_rec", "_file")
            return [
                f"# REWRITE {record_name}",
                f"# TODO(high): REWRITE — FileAdapter is read-only by design (safety guarantee)",
                f"# To implement: open file in write mode, seek to record, write updated data",
                f"# self.{file_hint}.rewrite(self.data.{py_record})",
            ]
        elif verb == "SET":
            return [f"# SET: {stmt.raw_text}", f"# TODO(high): manual translation required"]
        elif verb == "GO":
            safe_text = (
                stmt.raw_text
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace("{", "{{")
                .replace("}", "}}")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
            )
            return [
                f"raise NotImplementedError('GO TO not supported: {safe_text}')",
                f"# TODO(high): GO TO requires manual restructuring",
            ]
        elif verb in ("STRING", "UNSTRING", "INSPECT"):
            return [f"# TODO(high): {verb} — manual translation required", f"# {stmt.raw_text}"]
        elif verb == "INITIALIZE":
            return self._translate_initialize(ops)
        elif verb in ("NOT", "AT"):
            return [f"# {stmt.raw_text}"]
        else:
            return [f"# TODO(high): unsupported verb {verb}", f"# {stmt.raw_text}"]

    def _translate_display(self, stmt: CobolStatement) -> list[str]:
        return st.translate_display(stmt, self._resolve_operand)

    def _translate_move(self, ops: list[str]) -> list[str]:
        return st.translate_move(ops)

    def _resolve_operand(self, op: str) -> str:
        """Resolve a COBOL operand to a Python expression."""
        if op.startswith('"') or op.startswith("'"):
            return op
        if _is_numeric_literal(op):
            return op
        upper = op.upper()
        if upper in ("ZEROS", "ZEROES", "ZERO"):
            return "0"
        if upper in ("SPACES", "SPACE"):
            return "' '"
        if upper in ("HIGH-VALUES", "HIGH-VALUE"):
            return "'\\xff'"
        if upper in ("LOW-VALUES", "LOW-VALUE"):
            return "'\\x00'"
        return f"self.data.{_to_python_name(op)}.value"

    def _translate_add(self, ops: list[str]) -> list[str]:
        return st.translate_add(ops, self._resolve_operand)

    def _translate_subtract(self, ops: list[str]) -> list[str]:
        return st.translate_subtract(ops, self._resolve_operand)

    def _translate_multiply(self, ops: list[str]) -> list[str]:
        return st.translate_multiply(ops, self._resolve_operand)

    def _translate_divide(self, ops: list[str]) -> list[str]:
        return st.translate_divide(ops, self._resolve_operand)

    def _translate_compute(self, ops: list[str]) -> list[str]:
        return st.translate_compute(ops, self._resolve_operand)

    def _translate_perform(self, ops: list[str], raw: str) -> list[str]:
        return st.translate_perform(ops, raw, self._translate_condition)

    def _translate_condition(self, cond: str) -> str:
        """Best-effort translation of a COBOL condition to Python."""
        c = cond.strip()

        # Extract quoted strings, replacing with placeholders to protect them
        # from uppercasing and splitting
        literals: list[str] = []

        def _save_literal(m: re.Match) -> str:
            literals.append(m.group(0))
            return f"__LIT{len(literals) - 1}__"

        c = re.sub(r'"[^"]*"|\'[^\']*\'', _save_literal, c)

        # Uppercase for case-insensitive comparison operator matching
        c = c.upper()
        # COBOL class conditions: IS [NOT] NUMERIC / IS [NOT] ALPHABETIC
        # Must be handled BEFORE stripping IS keyword
        c = re.sub(r'\bIS\s+NOT\s+NUMERIC\b', '__CLASS_NOT_NUMERIC__', c)
        c = re.sub(r'\bIS\s+NOT\s+ALPHABETIC\b', '__CLASS_NOT_ALPHABETIC__', c)
        c = re.sub(r'\bNOT\s+NUMERIC\b', '__CLASS_NOT_NUMERIC__', c)
        c = re.sub(r'\bNOT\s+ALPHABETIC\b', '__CLASS_NOT_ALPHABETIC__', c)
        c = re.sub(r'\bIS\s+NUMERIC\b', '__CLASS_NUMERIC__', c)
        c = re.sub(r'\bIS\s+ALPHABETIC\b', '__CLASS_ALPHABETIC__', c)
        # Bare NUMERIC/ALPHABETIC (without IS) — must come AFTER IS/NOT variants
        c = re.sub(r'\bNUMERIC\b(?!__)', '__CLASS_NUMERIC__', c)
        c = re.sub(r'\bALPHABETIC\b(?!__)', '__CLASS_ALPHABETIC__', c)
        # Strip COBOL IS keyword (class conditions already handled above)
        # Use (?:^|\s) instead of \b to avoid corrupting data names ending in -IS
        c = re.sub(r'(?:^|\s)IS\s+(?!__CLASS)', ' ', c).strip()
        # Replace compound COBOL comparisons FIRST — longest patterns first to avoid partial matches
        c = c.replace(" NOT GREATER THAN OR EQUAL TO ", " < ")
        c = c.replace(" NOT LESS THAN OR EQUAL TO ", " > ")
        c = c.replace(" GREATER THAN OR EQUAL TO ", " >= ")
        c = c.replace(" LESS THAN OR EQUAL TO ", " <= ")
        c = c.replace(" NOT GREATER THAN ", " <= ")
        c = c.replace(" NOT LESS THAN ", " >= ")
        c = c.replace(" NOT EQUAL TO ", " != ")
        # Simple comparisons (long forms before short forms)
        c = c.replace(" GREATER THAN ", " > ")
        c = c.replace(" LESS THAN ", " < ")
        c = c.replace(" EQUAL TO ", " == ")
        # Short comparison forms (COBOL permits EQUAL, GREATER, LESS without TO/THAN)
        c = c.replace(" NOT > ", " <= ")
        c = c.replace(" NOT < ", " >= ")
        c = c.replace(" NOT = ", " != ")
        c = c.replace(" EQUAL ", " == ")
        c = c.replace(" GREATER ", " > ")
        c = c.replace(" LESS ", " < ")
        c = c.replace(" = ", " == ")
        # Separate parentheses from adjacent tokens before splitting
        c = re.sub(r'([()])', r' \1 ', c)
        # Convert data names and figurative constants
        tokens = c.split()
        result: list[str] = []
        for t in tokens:
            # Restore literal placeholders
            lit_m = re.match(r'^__LIT(\d+)__$', t)
            if lit_m:
                result.append(literals[int(lit_m.group(1))])
            elif t in ("(", ")"):
                result.append(t)
            elif t in (">", "<", "==", "!=", ">=", "<=", "AND", "OR"):
                result.append(t.lower() if t in ("AND", "OR") else t)
            elif t == "NOT":
                # Wrap the following comparison in parentheses so Python
                # evaluates "not (a > b)" rather than "(not a) > b".
                result.append("not")
            elif t == "__CLASS_NUMERIC__":
                # Look back — previous token is the subject
                if result:
                    subj = result.pop()
                    result.append(f"str({subj}).replace('.','').replace('-','').isdigit()")
                else:
                    result.append("False  # TODO(high): IS NUMERIC — no subject found")
            elif t == "__CLASS_ALPHABETIC__":
                if result:
                    subj = result.pop()
                    result.append(f"str({subj}).isalpha()")
                else:
                    result.append("False  # TODO(high): IS ALPHABETIC — no subject found")
            elif t == "__CLASS_NOT_NUMERIC__":
                if result:
                    subj = result.pop()
                    result.append(f"not str({subj}).replace('.','').replace('-','').isdigit()")
                else:
                    result.append("True  # TODO(high): IS NOT NUMERIC — no subject found")
            elif t == "__CLASS_NOT_ALPHABETIC__":
                if result:
                    subj = result.pop()
                    result.append(f"not str({subj}).isalpha()")
                else:
                    result.append("True  # TODO(high): IS NOT ALPHABETIC — no subject found")
            elif _is_numeric_literal(t):
                result.append(t)
            elif t.upper() in ("ZERO", "ZEROS", "ZEROES"):
                result.append("0")
            elif t.upper() in ("SPACE", "SPACES"):
                result.append("' '")
            elif t.upper() in ("HIGH-VALUE", "HIGH-VALUES"):
                result.append("'\\xff'")
            elif t.upper() in ("LOW-VALUE", "LOW-VALUES"):
                result.append("'\\x00'")
            else:
                result.append(f"self.data.{_to_python_name(t)}.value")
        # Post-process: wrap "not X op Y" into "not (X op Y)" to fix
        # Python operator precedence (not binds tighter than comparisons).
        _CMP_OPS = {">", "<", "==", "!=", ">=", "<="}
        fixed: list[str] = []
        i = 0
        while i < len(result):
            if result[i] == "not" and i + 3 < len(result) and result[i + 2] in _CMP_OPS:
                # not X op Y -> not (X op Y)
                fixed.append("not")
                fixed.append("(")
                fixed.append(result[i + 1])
                fixed.append(result[i + 2])
                fixed.append(result[i + 3])
                fixed.append(")")
                i += 4
            else:
                fixed.append(result[i])
                i += 1
        return " ".join(fixed)

    def _translate_if(self, raw: str) -> list[str]:
        """Fallback IF translation (used when block translator can't handle it)."""
        return [
            f"# IF statement (manual review recommended):",
            f"# {raw}",
            f"# TODO(high): translate IF condition and branches",
        ]

    def _translate_evaluate(self, raw: str) -> list[str]:
        """Fallback EVALUATE translation (used when block translator can't handle it)."""
        return [
            f"# EVALUATE statement (translates to if/elif):",
            f"# {raw}",
            f"# TODO(high): translate EVALUATE branches to if/elif",
        ]

    def _translate_open(self, ops: list[str]) -> list[str]:
        return st.translate_open(ops)

    def _translate_close(self, ops: list[str]) -> list[str]:
        return st.translate_close(ops)

    def _translate_read(self, ops: list[str], raw: str) -> list[str]:
        return st.translate_read(ops, raw)

    def _translate_call(self, ops: list[str]) -> list[str]:
        return st.translate_call(ops)

    def _translate_initialize(self, ops: list[str]) -> list[str]:
        return st.translate_initialize(ops)

    def _main_block(self) -> str:
        class_name = _to_python_name(self._program_id).title().replace("_", "")
        return (
            f'if __name__ == "__main__":\n'
            f"    program = {class_name}Program()\n"
            f"    program.run()\n"
        )


def generate_python(software_map: SoftwareMap) -> str:
    """Generate Python source code from a SoftwareMap."""
    mapper = PythonMapper(software_map)
    return mapper.generate()
