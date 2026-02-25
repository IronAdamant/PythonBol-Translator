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

from .models import (
    CobolProgram,
    CobolStatement,
    DataItem,
    Paragraph,
    PicCategory,
    SensitivityFlag,
    SensitivityLevel,
    SoftwareMap,
)


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
        return (parts[0].isdigit() or parts[0] == "") and parts[1].isdigit()
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


# Keywords that should be filtered from arithmetic operand/target lists
_ARITHMETIC_KEYWORDS = frozenset({
    "ROUNDED", "ON", "SIZE", "ERROR", "NOT",
})


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
            self.program.program_id = "UNNAMED"
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
            f"Auto-generated Python translation of COBOL program: {self.program.program_id}",
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
        """Generate @dataclass for WORKING-STORAGE data items."""
        all_items = self.program.working_storage + self.program.file_section
        class_name = _to_python_name(self.program.program_id).title().replace('_', '') + "Data"

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
            py_name = f"{py_name}_{self._field_name_counts[py_name]}"
        else:
            self._field_name_counts[py_name] = 1

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
        class_name = _to_python_name(self.program.program_id).title().replace("_", "")
        data_class = f"{class_name}Data"

        lines = [f"class {class_name}Program:"]
        lines.append(f'    """Translated from COBOL program {self.program.program_id}."""')
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

        for stmt in para.statements:
            translated = self._translate_statement(stmt)
            for tl in translated:
                lines.append(f"        {tl}")

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
            return [f"# {verb}"]
        elif verb == "ELSE":
            return [f"# else:  (see surrounding IF)"]
        elif verb == "WHEN":
            return [f"# WHEN branch: {stmt.raw_text}"]
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
        elif verb == "SET":
            return [f"# SET: {stmt.raw_text}", f"# TODO(high): manual translation required"]
        elif verb == "GO":
            safe_text = stmt.raw_text.replace("\\", "\\\\").replace("'", "\\'").replace("{", "{{").replace("}", "}}")
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
        parts: list[str] = []
        # Filter out UPON clause (DISPLAY x UPON CONSOLE)
        operands = list(stmt.operands)
        for i, op in enumerate(operands):
            if op.upper() == "UPON":
                operands = operands[:i]
                break
        for op in operands:
            if (len(op) >= 2 and ((op.startswith('"') and op.endswith('"')) or (op.startswith("'") and op.endswith("'")))):
                # Quoted string literal — keep as-is
                parts.append(op)
            elif _is_numeric_literal(op):
                parts.append(op)
            else:
                # Data name reference
                parts.append(f"self.data.{_to_python_name(op)}.value")
        if parts:
            return [f"print({', '.join(parts)}, sep='')"]
        return ["print()"]

    def _translate_move(self, ops: list[str]) -> list[str]:
        # MOVE CORRESPONDING requires field-by-field matching
        if ops and ops[0].upper() == "CORRESPONDING":
            return [f"# TODO(high): MOVE CORRESPONDING — manual field matching required"]
        # MOVE ALL repeats a character to fill the target
        if ops and ops[0].upper() == "ALL":
            return [f"# TODO(high): MOVE ALL — repeats value to fill target field: {' '.join(ops)}"]
        if "TO" not in [o.upper() for o in ops]:
            return [f"# MOVE: could not parse operands: {' '.join(ops)}"]
        to_idx = next(i for i, o in enumerate(ops) if o.upper() == "TO")
        source = ops[0]
        targets = ops[to_idx + 1:]
        if not targets:
            return [f"# MOVE: missing target operand: {' '.join(ops)}"]

        # Resolve source value
        if source.startswith('"') or source.startswith("'"):
            src_expr = source
        elif _is_numeric_literal(source):
            src_expr = source
        elif source.upper().startswith("FUNCTION"):
            return [f"# TODO(high): MOVE FUNCTION — manual translation required"]
        elif source.upper() in ("ZEROS", "ZEROES", "ZERO"):
            src_expr = "0"
        elif source.upper() in ("SPACES", "SPACE"):
            src_expr = "' '"
        elif source.upper() in ("HIGH-VALUES", "HIGH-VALUE"):
            src_expr = "'\\xff'"
        elif source.upper() in ("LOW-VALUES", "LOW-VALUE"):
            src_expr = "'\\x00'"
        else:
            src_expr = f"self.data.{_to_python_name(source)}.value"

        results: list[str] = []
        for t in targets:
            target = _to_python_name(t)
            results.append(f"self.data.{target}.set({src_expr})")
        return results

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
        if not ops:
            return ["# ADD: no operands"]
        # ADD x [y ...] TO z [GIVING r]
        upper_ops = [o.upper() for o in ops]
        # Handle GIVING clause: result stored in GIVING target, not TO target
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            giving_targets = ops[giving_idx + 1:]
            if not giving_targets:
                return [f"# ADD GIVING: missing target operand: {' '.join(ops)}"]
            pre_giving = ops[:giving_idx]
            # Collect all source values (before TO, or all of pre_giving if no TO)
            if "TO" in [o.upper() for o in pre_giving]:
                to_idx = next(i for i, o in enumerate(pre_giving) if o.upper() == "TO")
                all_sources = pre_giving[:to_idx] + pre_giving[to_idx + 1:]
            else:
                all_sources = pre_giving
            exprs = [self._resolve_operand(s) for s in all_sources]
            sum_expr = " + ".join(exprs) if exprs else "0"
            results: list[str] = []
            for t in giving_targets:
                if t.upper() in _ARITHMETIC_KEYWORDS:
                    break
                if t.upper() != "ROUNDED":
                    results.append(f"self.data.{_to_python_name(t)}.set({sum_expr})")
            return results
        if "TO" in upper_ops:
            to_idx = next(i for i, o in enumerate(upper_ops) if o == "TO")
            sources = ops[:to_idx]
            targets = [t for t in ops[to_idx + 1:] if t.upper() not in _ARITHMETIC_KEYWORDS]
            if not sources or not targets:
                return [f"# ADD: missing operand(s): {' '.join(ops)}"]
            results = []
            for src in sources:
                src_expr = self._resolve_operand(src)
                for t in targets:
                    results.append(f"self.data.{_to_python_name(t)}.add({src_expr})")
            return results
        return [f"# ADD: could not parse operands: {' '.join(ops)}"]

    def _translate_subtract(self, ops: list[str]) -> list[str]:
        if not ops:
            return ["# SUBTRACT: no operands"]
        # SUBTRACT x [y ...] FROM z [GIVING r]
        upper_ops = [o.upper() for o in ops]
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            giving_targets = ops[giving_idx + 1:]
            pre_giving = ops[:giving_idx]
            if "FROM" in [o.upper() for o in pre_giving]:
                from_idx = next(i for i, o in enumerate(pre_giving) if o.upper() == "FROM")
                sources = pre_giving[:from_idx]
                base = pre_giving[from_idx + 1] if from_idx + 1 < len(pre_giving) else "0"
                base_expr = self._resolve_operand(base)
                sub_exprs = [self._resolve_operand(s) for s in sources]
                expr = base_expr + "".join(f" - {e}" for e in sub_exprs)
            else:
                expr = " - ".join(self._resolve_operand(s) for s in pre_giving) or "0"
            results: list[str] = []
            for t in giving_targets:
                if t.upper() in _ARITHMETIC_KEYWORDS:
                    break
                if t.upper() != "ROUNDED":
                    results.append(f"self.data.{_to_python_name(t)}.set({expr})")
            return results
        if "FROM" in upper_ops:
            from_idx = next(i for i, o in enumerate(upper_ops) if o == "FROM")
            sources = ops[:from_idx]
            targets = [t for t in ops[from_idx + 1:] if t.upper() not in _ARITHMETIC_KEYWORDS]
            if not sources or not targets:
                return [f"# SUBTRACT: missing operand(s): {' '.join(ops)}"]
            results = []
            for src in sources:
                src_expr = self._resolve_operand(src)
                for t in targets:
                    results.append(f"self.data.{_to_python_name(t)}.subtract({src_expr})")
            return results
        return [f"# SUBTRACT: could not parse operands: {' '.join(ops)}"]

    def _translate_multiply(self, ops: list[str]) -> list[str]:
        # MULTIPLY x BY y [GIVING z]
        upper_ops = [o.upper() for o in ops]
        if "BY" in upper_ops:
            by_idx = next(i for i, o in enumerate(upper_ops) if o == "BY")
            source = self._resolve_operand(ops[0])
            if "GIVING" in upper_ops:
                giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
                multiplicand = self._resolve_operand(ops[by_idx + 1]) if (by_idx + 1 < len(ops) and by_idx + 1 < giving_idx) else "1"
                results: list[str] = []
                for t in ops[giving_idx + 1:]:
                    if t.upper() in _ARITHMETIC_KEYWORDS:
                        break
                    if t.upper() != "ROUNDED":
                        results.append(f"self.data.{_to_python_name(t)}.set({source} * {multiplicand})")
                return results
            if by_idx + 1 >= len(ops):
                return [f"# MULTIPLY: missing target operand: {' '.join(ops)}"]
            target = _to_python_name(ops[by_idx + 1])
            return [f"self.data.{target}.multiply({source})"]
        return [f"# MULTIPLY: could not parse operands: {' '.join(ops)}"]

    def _translate_divide(self, ops: list[str]) -> list[str]:
        # DIVIDE x INTO y [GIVING z] [REMAINDER r]
        upper_ops = [o.upper() for o in ops]
        if "INTO" in upper_ops:
            into_idx = next(i for i, o in enumerate(upper_ops) if o == "INTO")
            divisor = self._resolve_operand(ops[0])
            if "GIVING" in upper_ops:
                giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
                dividend = self._resolve_operand(ops[into_idx + 1]) if into_idx + 1 < len(ops) and into_idx + 1 < giving_idx else "0"
                # Filter out REMAINDER, ROUNDED, ON SIZE ERROR keywords
                giving_targets = []
                has_remainder = False
                remainder_target = None
                i = giving_idx + 1
                while i < len(ops):
                    upper_op = ops[i].upper()
                    if upper_op == "REMAINDER":
                        has_remainder = True
                        if i + 1 < len(ops):
                            remainder_target = ops[i + 1]
                            i += 2
                        else:
                            i += 1
                        continue
                    if upper_op in _ARITHMETIC_KEYWORDS:
                        break
                    if upper_op != "ROUNDED":
                        giving_targets.append(ops[i])
                    i += 1
                results: list[str] = []
                results.append(f"# TODO: verify divisor is non-zero before division (COBOL EC-SIZE-ZERO-DIVIDE)")
                for t in giving_targets:
                    results.append(f"self.data.{_to_python_name(t)}.set({dividend} / {divisor})")
                if has_remainder and remainder_target:
                    results.append(f"# TODO(high): REMAINDER {remainder_target} — compute modulo manually")
                    results.append(f"# self.data.{_to_python_name(remainder_target)}.set({dividend} % {divisor})")
                return results
            if into_idx + 1 >= len(ops):
                return [f"# DIVIDE: missing target operand: {' '.join(ops)}"]
            target = _to_python_name(ops[into_idx + 1])
            return [f"self.data.{target}.divide({divisor})"]
        # DIVIDE x BY y GIVING z [REMAINDER r] (dividend is x, divisor is y)
        if "BY" in upper_ops:
            by_idx = next(i for i, o in enumerate(upper_ops) if o == "BY")
            dividend = self._resolve_operand(ops[0])
            if "GIVING" in upper_ops:
                giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
                divisor = self._resolve_operand(ops[by_idx + 1]) if by_idx + 1 < len(ops) and by_idx + 1 < giving_idx else "1"
                # Filter REMAINDER and ROUNDED from giving targets
                giving_targets = []
                has_remainder = False
                remainder_target = None
                i = giving_idx + 1
                while i < len(ops):
                    upper_op = ops[i].upper()
                    if upper_op == "REMAINDER":
                        has_remainder = True
                        if i + 1 < len(ops):
                            remainder_target = ops[i + 1]
                            i += 2
                        else:
                            i += 1
                        continue
                    if upper_op in _ARITHMETIC_KEYWORDS:
                        break
                    if upper_op != "ROUNDED":
                        giving_targets.append(ops[i])
                    i += 1
                results = []
                results.append(f"# TODO: verify divisor is non-zero before division (COBOL EC-SIZE-ZERO-DIVIDE)")
                for t in giving_targets:
                    results.append(f"self.data.{_to_python_name(t)}.set({dividend} / {divisor})")
                if has_remainder and remainder_target:
                    results.append(f"# TODO(high): REMAINDER {remainder_target} — compute modulo manually")
                    results.append(f"# self.data.{_to_python_name(remainder_target)}.set({dividend} % {divisor})")
                return results
            if by_idx + 1 >= len(ops):
                return [f"# DIVIDE BY: missing divisor: {' '.join(ops)}"]
            divisor = self._resolve_operand(ops[by_idx + 1])
            return [f"# TODO(high): DIVIDE BY without GIVING — manual translation required",
                    f"# {dividend} / {divisor}"]
        return [f"# DIVIDE: could not parse operands: {' '.join(ops)}"]

    def _translate_compute(self, ops: list[str]) -> list[str]:
        # COMPUTE target = expression
        _COMPUTE_OPERATORS = {"+", "-", "*", "/", "(", ")", "**"}
        if "=" in ops:
            eq_idx = ops.index("=")
            target = _to_python_name(ops[0])
            expr_parts = ops[eq_idx + 1:]
            resolved: list[str] = []
            for part in expr_parts:
                if part in _COMPUTE_OPERATORS:
                    resolved.append(part)
                else:
                    resolved.append(self._resolve_operand(part))
            expr = " ".join(resolved)
            return [
                f"# COMPUTE: {' '.join(ops)}",
                f"self.data.{target}.set({expr})  # TODO(high): verify expression translation",
            ]
        return [f"# COMPUTE: could not parse operands: {' '.join(ops)}"]

    def _translate_perform(self, ops: list[str], raw: str) -> list[str]:
        if not ops:
            return [f"# PERFORM with no target"]

        target = _to_method_name(ops[0])
        upper_ops = [o.upper() for o in ops]

        # PERFORM ... THRU/THROUGH — paragraph range, can't fully translate
        if "THRU" in upper_ops or "THROUGH" in upper_ops:
            return [
                f"# PERFORM THRU: {raw}",
                f"# TODO(high): PERFORM THRU/THROUGH requires manual translation (paragraph range)",
                f"self.{target}()  # only first paragraph — range endpoint missing",
            ]

        # PERFORM ... VARYING — needs FROM/BY/UNTIL which we can't fully translate
        if "VARYING" in upper_ops:
            varying_idx = next(i for i, o in enumerate(upper_ops) if o == "VARYING")
            return [
                f"# PERFORM VARYING: {raw}",
                f"# TODO(high): PERFORM VARYING requires manual translation (FROM/BY/UNTIL clauses)",
            ]

        # PERFORM ... UNTIL
        if "UNTIL" in upper_ops:
            until_idx = next(i for i, o in enumerate(ops) if o.upper() == "UNTIL")
            cond_parts = ops[until_idx + 1:]
            if not cond_parts:
                return [f"# PERFORM UNTIL: missing condition — {' '.join(ops)}"]
            cond = " ".join(cond_parts)
            return [
                f"# PERFORM {ops[0]} UNTIL {cond}",
                f"while not ({self._translate_condition(cond)}):",
                f"    self.{target}()",
            ]

        # PERFORM ... TIMES
        if "TIMES" in [o.upper() for o in ops]:
            times_idx = next(i for i, o in enumerate(ops) if o.upper() == "TIMES")
            if times_idx >= 2:
                # PERFORM para-name count TIMES
                times_op = ops[times_idx - 1]
                target = _to_method_name(ops[0])
            elif times_idx == 1:
                # PERFORM count TIMES (inline block, no paragraph name)
                times_op = ops[0]
                times_val = times_op if times_op.isdigit() else f"int(self.data.{_to_python_name(times_op)}.value)"
                return [
                    f"for _ in range({times_val}):",
                    f"    pass  # TODO(high): inline PERFORM TIMES — statements should be moved here",
                ]
            else:
                return [f"# PERFORM TIMES: invalid syntax — {' '.join(ops)}"]
            times_val = times_op if times_op.isdigit() else f"int(self.data.{_to_python_name(times_op)}.value)"
            return [
                f"for _ in range({times_val}):",
                f"    self.{target}()",
            ]

        return [f"self.{target}()"]

    def _translate_condition(self, cond: str) -> str:
        """Best-effort translation of a COBOL condition to Python."""
        c = cond.strip()
        # Strip COBOL IS keyword before comparisons (e.g., IS EQUAL TO -> EQUAL TO)
        c = re.sub(r'\bIS\s+', '', c)
        # Replace compound COBOL comparisons FIRST — longest patterns first to avoid partial matches
        c = c.replace(" NOT GREATER THAN OR EQUAL TO ", " < ")
        c = c.replace(" NOT LESS THAN OR EQUAL TO ", " > ")
        c = c.replace(" GREATER THAN OR EQUAL TO ", " >= ")
        c = c.replace(" LESS THAN OR EQUAL TO ", " <= ")
        c = c.replace(" NOT GREATER THAN ", " <= ")
        c = c.replace(" NOT LESS THAN ", " >= ")
        c = c.replace(" NOT EQUAL TO ", " != ")
        # Simple comparisons
        c = c.replace(" GREATER THAN ", " > ")
        c = c.replace(" LESS THAN ", " < ")
        c = c.replace(" EQUAL TO ", " == ")
        c = c.replace(" NOT = ", " != ")
        c = c.replace(" = ", " == ")
        # Separate parentheses from adjacent tokens before splitting
        c = re.sub(r'([()])', r' \1 ', c)
        # Convert data names and figurative constants
        tokens = c.split()
        result: list[str] = []
        for t in tokens:
            if t in ("(", ")"):
                result.append(t)
            elif t in (">", "<", "==", "!=", ">=", "<=", "AND", "OR", "NOT"):
                result.append(t.lower() if t in ("AND", "OR", "NOT") else t)
            elif _is_numeric_literal(t):
                result.append(t)
            elif t.startswith('"') or t.startswith("'"):
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
        return " ".join(result)

    def _translate_if(self, raw: str) -> list[str]:
        """Translate IF statement (simplified)."""
        return [
            f"# IF statement (manual review recommended):",
            f"# {raw}",
            f"# TODO(high): translate IF condition and branches",
        ]

    def _translate_evaluate(self, raw: str) -> list[str]:
        """Translate EVALUATE as if/elif chain."""
        return [
            f"# EVALUATE statement (translates to if/elif):",
            f"# {raw}",
            f"# TODO(high): translate EVALUATE branches to if/elif",
        ]

    def _translate_open(self, ops: list[str]) -> list[str]:
        if len(ops) >= 2:
            mode = ops[0].upper()
            file_names = ops[1:]
            results: list[str] = []
            for fn in file_names:
                py_name = _to_python_name(fn)
                if mode == "INPUT":
                    results.append(f"self.{py_name}.open_input()")
                elif mode == "OUTPUT":
                    results.append(f"# OPEN OUTPUT {fn} — write not supported (safety)")
                    results.append(f"# TODO(high): file output requires manual implementation")
            return results if results else [f"# OPEN: could not parse: {' '.join(ops)}"]
        return [f"# OPEN: could not parse: {' '.join(ops)}"]

    def _translate_close(self, ops: list[str]) -> list[str]:
        _CLOSE_KEYWORDS = {"WITH", "LOCK", "NO", "REWIND"}
        results: list[str] = []
        for op in ops:
            if op.upper() in _CLOSE_KEYWORDS:
                continue
            py_name = _to_python_name(op)
            results.append(f"self.{py_name}.close()")
        return results

    def _translate_read(self, ops: list[str], raw: str) -> list[str]:
        if ops:
            file_name = _to_python_name(ops[0])
            return [
                f"_record = self.{file_name}.read()",
                f"if _record is None:",
                f"    pass  # AT END — set EOF flag",
                f"    # {raw}",
            ]
        return [f"# READ: could not parse: {raw}"]

    def _translate_call(self, ops: list[str]) -> list[str]:
        if ops:
            target = ops[0].strip('"').strip("'")
            py_target = _to_python_name(target)
            args = [_to_python_name(o) for o in ops[2:] if o.upper() != "USING"]
            arg_str = ", ".join(f"self.data.{a}.value" for a in args) if args else ""
            return [
                f"# CALL '{target}'",
                f"# TODO(high): implement or import {py_target}({arg_str})",
            ]
        return [f"# CALL: no target specified"]

    def _translate_initialize(self, ops: list[str]) -> list[str]:
        results: list[str] = []
        for op in ops:
            py_name = _to_python_name(op)
            results.append(f"# INITIALIZE {op}")
            results.append(f"# self.data.{py_name}.set(0)  # or '' for alphanumeric")
        return results

    def _main_block(self) -> str:
        class_name = _to_python_name(self.program.program_id).title().replace("_", "")
        return (
            f'if __name__ == "__main__":\n'
            f"    program = {class_name}Program()\n"
            f"    program.run()\n"
        )


def generate_python(software_map: SoftwareMap) -> str:
    """Generate Python source code from a SoftwareMap."""
    mapper = PythonMapper(software_map)
    return mapper.generate()
