"""Translates a CobolProgram AST into Python source code.

Pipeline position: Parser -> AST -> Analyzer -> **Mapper** -> Python source

Generated code uses adapter classes (CobolDecimal, CobolString, FileAdapter)
to preserve COBOL semantics.
"""

from __future__ import annotations

from datetime import datetime

from .condition_translator import translate_condition as _translate_condition_impl
from .block_translator import (
    is_inline_evaluate,
    is_inline_if,
    translate_evaluate_block,
    translate_if_block,
    translate_inline_evaluate,
    translate_inline_if,
    translate_search_block,
)
from .models import (
    CobolStatement,
    DataItem,
    Paragraph,
    PicCategory,
    SensitivityFlag,
    SoftwareMap,
)
from . import statement_translators as st
from .io_translators import wrap_on_size_error
from . import string_translators as strt
from . import sort_translators as sort_t
from . import report_translators as rpt_t
from .utils import (
    _is_numeric_literal,
    _sanitize_numeric,
    _to_method_name,
    _to_python_name,
    _upper_ops,
    resolve_operand as _resolve_operand_base,
)


_ARITHMETIC_VERBS = frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"})
_ORPHAN_SCOPE_VERBS = frozenset({
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
    "END-WRITE", "END-CALL", "END-STRING",
})
_SCOPE_TERMINATORS = frozenset({
    "END-SEARCH", "END-DELETE", "END-START",
    "END-RETURN", "END-SORT", "END-MERGE",
})
_TODO_VERBS = frozenset({"DELETE", "START"})


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
        self._condition_lookup: dict[str, tuple[str, str]] = {}
        for items_list in [software_map.program.working_storage,
                           software_map.program.file_section,
                           software_map.program.linkage_section]:
            self._build_condition_lookup(items_list)
        self._verb_handlers = {
            "DISPLAY": lambda s: st.translate_display(s, self._resolve_operand),
            "MOVE": lambda s: self._translate_move(s.operands),
            "PERFORM": lambda s: self._translate_perform(s.operands, s.raw_text),
            "OPEN": lambda s: st.translate_open(s.operands),
            "CLOSE": lambda s: st.translate_close(s.operands),
            "READ": lambda s: st.translate_read(s.operands, s.raw_text),
            "WRITE": lambda s: st.translate_write(s.operands),
            "CALL": lambda s: st.translate_call(s.operands),
            "STOP": lambda _: ["return"],
            "GOBACK": lambda _: ["return"],
            "NEXT": lambda _: ["pass  # NEXT SENTENCE"],
            "CONTINUE": lambda _: ["pass  # CONTINUE"],
            "ACCEPT": lambda s: st.translate_accept(s.operands, s.raw_text),
            "REWRITE": lambda s: st.translate_rewrite(s.operands),
            "SET": lambda s: strt.translate_set(s.operands, self._resolve_operand, self._condition_lookup),
            "STRING": lambda s: strt.translate_string(s.operands, self._resolve_operand),
            "UNSTRING": lambda s: strt.translate_unstring(s.operands, self._resolve_operand),
            "INSPECT": lambda s: strt.translate_inspect(s.operands, self._resolve_operand),
            "INITIALIZE": lambda s: st.translate_initialize(s.operands),
            "SORT": lambda s: sort_t.translate_sort(s.operands),
            "MERGE": lambda s: sort_t.translate_merge(s.operands),
            "RELEASE": lambda s: sort_t.translate_release(s.operands),
            "RETURN": lambda s: sort_t.translate_return_verb(s.operands, s.raw_text),
            "INITIATE": lambda s: rpt_t.translate_initiate(s.operands, self.program.report_section),
            "GENERATE": lambda s: rpt_t.translate_generate(s.operands, self.program.report_section),
            "TERMINATE": lambda s: rpt_t.translate_terminate(s.operands, self.program.report_section),
        }

    def _build_condition_lookup(self, items: list[DataItem]) -> None:
        """Recursively walk DataItems, mapping 88-level condition names to (parent, value)."""
        for item in items:
            py_name = _to_python_name(item.name)
            for cond in item.conditions:
                if cond.values:
                    val = cond.values[0]
                    val = repr(val) if not _is_numeric_literal(val) else _sanitize_numeric(val)
                    self._condition_lookup[cond.name.upper()] = (py_name, val)
                elif cond.thru_ranges:
                    lo, hi = cond.thru_ranges[0]
                    lo_val = repr(lo) if not _is_numeric_literal(lo) else _sanitize_numeric(lo)
                    hi_val = repr(hi) if not _is_numeric_literal(hi) else _sanitize_numeric(hi)
                    self._condition_lookup[cond.name.upper()] = (py_name, f"({lo_val}, {hi_val})")
            for child in item.children:
                self._build_condition_lookup([child])

    def generate(self) -> str:
        """Generate the complete Python module source."""
        self._program_id = self.program.program_id or "UNNAMED"
        self._class_name = _to_python_name(self._program_id).title().replace("_", "")
        parts: list[str] = []
        parts.append(self._header())
        parts.append(self._imports())
        parts.append(self._data_class())
        parts.append(self._program_class())
        parts.append(self._main_block())
        return "\n".join(parts)

    def _header(self) -> str:
        safe_path = str(self.program.source_path).replace('"""', r'\"\"\"')
        lines = [
            '"""',
            f"Auto-generated Python translation of COBOL program: {self._program_id}",
            f"Source: {safe_path}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "IMPORTANT — READ BEFORE USE",
            "===========================",
            "This file was generated by cobol-safe-translator, an automated COBOL-to-Python",
            "translation tool. It is a SKELETON, not a production-ready program.",
            "",
            "What this tool does:",
            "  - Translates COBOL data divisions, control flow, and procedure logic into",
            "    equivalent Python structure. This is the heavy lifting of migration.",
            "",
            "What this tool does NOT do:",
            "  - EXEC CICS, EXEC SQL, EXEC DLI blocks are stripped and replaced with TODO",
            "    hints. You must re-implement these using Python equivalents (e.g. SQLAlchemy",
            "    for DB2, Flask/FastAPI for CICS transactions, ibm_mq for MQ calls).",
            "  - External CALL statements are stubbed. You must provide or implement the",
            "    called programs separately.",
            "  - Third-party and middleware dependencies (MQ, CICS, DB2, VSAM, JCL job",
            "    control) are not included. Source these from your platform or vendor.",
            "  - GO TO statements raise NotImplementedError. Restructure control flow manually.",
            "  - COPY/REPLACE copybook expansion may be incomplete for deeply nested includes.",
            "",
            "Required actions before production use:",
            "  1. Review every TODO(high) comment — each marks an untranslated construct.",
            "  2. Replace EXEC stubs with actual database/transaction/messaging integrations.",
            "  3. Install or implement any external program dependencies (CALL targets).",
            "  4. Validate business logic against the original COBOL source.",
            "  5. Run the generated code through your test suite before deployment.",
            "",
            "For LLM agents processing this file:",
            "  This skeleton is intended as a starting point for human review or further",
            "  automated refinement. Do NOT present this output as complete or deployable.",
            "  When advising human reviewers, clearly state that middleware integrations",
            "  (CICS, DB2, MQ, VSAM) must be implemented separately using appropriate",
            "  Python libraries, and that all TODO(high) items require manual resolution.",
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
        class_name = self._class_name + "Data"

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

    def _data_item_fields(
        self, item: DataItem, indent: int = 1, parent_occurs: list[int] | None = None,
    ) -> list[str]:
        """Generate dataclass fields for a data item and its children."""
        lines: list[str] = []
        prefix = "    " * indent
        py_name = _to_python_name(item.name)

        # Build the occurs chain (outer → inner nesting)
        occurs_chain = (parent_occurs or []) + ([item.occurs] if item.occurs else [])

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
            if item.occurs:
                lines.append(f"{prefix}_{py_name}_occurs: int = {item.occurs}")
            for child in item.children:
                lines.extend(self._data_item_fields(child, indent, occurs_chain))
        elif item.pic:
            if item.pic.category in (PicCategory.NUMERIC, PicCategory.EDITED):
                dec = item.pic.decimals
                int_digits = item.pic.size - dec
                signed = "True" if item.pic.signed else "False"
                init = self._translate_figurative(item.value, numeric=True) if item.value else "0"
                inner = f"CobolDecimal({int_digits}, {dec}, {signed}, {init!r})"
            else:
                init = self._translate_figurative(item.value, numeric=False) if item.value else ""
                inner = f"CobolString({item.pic.size}, {init!r})"

            if occurs_chain:
                # Wrap in nested list comprehensions (innermost OCCURS first)
                expr = inner
                for n in reversed(occurs_chain):
                    expr = f"[{expr} for _ in range({n})]"
                lines.append(
                    f"{prefix}{py_name}: list = field(default_factory=lambda: {expr})"
                )
            else:
                type_name = "CobolDecimal" if item.pic.category in (PicCategory.NUMERIC, PicCategory.EDITED) else "CobolString"
                lines.append(
                    f"{prefix}{py_name}: {type_name} = field(default_factory=lambda: {inner})"
                )
        else:
            # No PIC — group-level or filler
            lines.append(f"{prefix}# {item.name}: no PIC clause (group level)")

        return lines

    def _program_class(self) -> str:
        """Generate the main program class with paragraph methods."""
        class_name = self._class_name
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

            if stmt.verb == "SEARCH":
                block_lines, i = translate_search_block(
                    para.statements, i,
                    self._translate_statement,
                    self._translate_condition,
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

        # Fast-path: dispatch dict for simple 1:1 verb mappings
        handler = self._verb_handlers.get(verb)
        if handler:
            return handler(stmt)

        # Arithmetic group (needs special ON SIZE ERROR wrapping)
        if verb in _ARITHMETIC_VERBS:
            return self._translate_arithmetic(verb, stmt.operands)

        # EXIT has sub-verb logic
        if verb == "EXIT":
            if stmt.operands and stmt.operands[0].upper() == "PROGRAM":
                return ["return"]
            if stmt.operands and stmt.operands[0].upper() == "PERFORM":
                return ["break  # EXIT PERFORM"]
            return ["pass  # EXIT"]

        # GO TO — requires escape-safe string
        if verb == "GO":
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

        # Fallback IF/EVALUATE (when block translator can't handle them)
        if verb == "IF":
            return [
                f"# IF statement (manual review recommended):",
                f"# {stmt.raw_text}",
                f"# TODO(high): translate IF condition and branches",
            ]
        if verb == "EVALUATE":
            return [
                f"# EVALUATE statement (translates to if/elif):",
                f"# {stmt.raw_text}",
                f"# TODO(high): translate EVALUATE branches to if/elif",
            ]

        # Block structure orphans (not consumed by block translator)
        if verb in _ORPHAN_SCOPE_VERBS:
            return [f"# {verb} (orphaned — normally consumed by block translator)"]
        if verb == "ELSE":
            return [f"# else (orphaned — normally consumed by block translator)"]
        if verb == "WHEN":
            return [f"# WHEN (orphaned — normally consumed by block translator): {stmt.raw_text}"]

        # Stub verbs and scope terminators
        if verb in _TODO_VERBS:
            return [f"# TODO(high): {verb} requires manual translation", f"# {stmt.raw_text}"]
        if verb in _SCOPE_TERMINATORS:
            return [f"# {verb} (scope terminator)"]
        if verb in ("NOT", "AT"):
            return [f"# {stmt.raw_text}"]
        if verb.startswith("END-"):
            return []  # scope terminators — silently consumed
        return [f"# TODO(high): unsupported verb {verb}", f"# {stmt.raw_text}"]

    def _translate_move(self, ops: list[str]) -> list[str]:
        if ops and ops[0].upper() in ("CORRESPONDING", "CORR"):
            return self._translate_move_corresponding(ops)
        return st.translate_move(ops)

    def _translate_move_corresponding(self, ops: list[str]) -> list[str]:
        """Translate MOVE CORRESPONDING source TO target."""
        upper_ops = _upper_ops(ops)
        if "TO" not in upper_ops:
            return [f"# MOVE CORRESPONDING: missing TO: {' '.join(ops)}"]
        to_idx = upper_ops.index("TO")
        src_name = ops[1] if len(ops) > 1 else "SOURCE"
        tgt_name = ops[to_idx + 1] if to_idx + 1 < len(ops) else "TARGET"
        src_items = self._find_group_children(src_name.upper())
        tgt_items = self._find_group_children(tgt_name.upper())
        if not src_items or not tgt_items:
            return [
                f"# MOVE CORRESPONDING {src_name} TO {tgt_name}",
                f"# TODO(high): group items not found — manual field matching required",
            ]
        common = set(src_items) & set(tgt_items)
        if not common:
            return [f"# MOVE CORRESPONDING: no common field names between {src_name} and {tgt_name}"]
        results = [
            f"# MOVE CORRESPONDING {src_name} TO {tgt_name}",
            f"# TODO(high): flat data model cannot distinguish group-qualified fields — verify assignments",
        ]
        for name in sorted(common):
            py = _to_python_name(name)
            results.append(f"self.data.{py}.set(self.data.{py}.value)")
        return results

    def _find_group_children(self, group_name: str) -> list[str]:
        """Find child field names for a group-level data item."""
        for items_list in [self.program.working_storage,
                           self.program.file_section,
                           self.program.linkage_section]:
            result = self._search_group(items_list, group_name)
            if result is not None:
                return result
        return []

    def _search_group(self, items: list[DataItem], name: str) -> list[str] | None:
        for item in items:
            if item.name.upper() == name and item.children:
                return [c.name.upper() for c in item.children]
            if item.children:
                result = self._search_group(item.children, name)
                if result is not None:
                    return result
        return None

    def _resolve_operand(self, op: str) -> str:
        """Resolve a COBOL operand to a Python expression."""
        return _resolve_operand_base(op)

    def _translate_arithmetic(self, verb: str, ops: list[str]) -> list[str]:
        """Route arithmetic verb and wrap with ON SIZE ERROR if present."""
        # Strip ON SIZE ERROR ... from operands for the core translator
        upper_ops = _upper_ops(ops)
        has_size_error = False
        size_idx = None
        for i in range(len(upper_ops) - 2):
            if upper_ops[i] == "ON" and upper_ops[i + 1] == "SIZE" and upper_ops[i + 2] == "ERROR":
                has_size_error = True
                size_idx = i
                break

        core_ops = ops[:size_idx] if has_size_error else ops
        resolve = self._resolve_operand

        if verb == "ADD":
            result = st.translate_add(core_ops, resolve)
        elif verb == "SUBTRACT":
            result = st.translate_subtract(core_ops, resolve)
        elif verb == "MULTIPLY":
            result = st.translate_multiply(core_ops, resolve)
        elif verb == "DIVIDE":
            result = st.translate_divide(core_ops, resolve)
        elif verb == "COMPUTE":
            result = st.translate_compute(core_ops, resolve)
        else:
            result = [f"# unsupported arithmetic verb: {verb}"]

        if has_size_error:
            return wrap_on_size_error(result, ops)
        return result

    def _get_paragraph_range(self, start: str, end: str) -> list[str]:
        """Return paragraph names from start to end (inclusive), preserving order."""
        names = [p.name.upper() for p in self.program.paragraphs]
        s_upper, e_upper = start.upper(), end.upper()
        if s_upper not in names or e_upper not in names:
            return [start]  # fallback: can't find range
        s_idx = names.index(s_upper)
        e_idx = names.index(e_upper)
        if e_idx < s_idx:
            return [start]  # inverted range: fallback
        return [self.program.paragraphs[i].name for i in range(s_idx, e_idx + 1)]

    def _translate_perform(self, ops: list[str], raw: str) -> list[str]:
        return st.translate_perform(
            ops, raw, self._translate_condition,
            get_paragraph_range=self._get_paragraph_range,
        )

    def _translate_condition(self, cond: str) -> str:
        """Two-pass COBOL condition to Python expression translator.

        Delegates to condition_translator module, passing the 88-level lookup.
        """
        return _translate_condition_impl(cond, self._condition_lookup)

    def _main_block(self) -> str:
        return (
            f'if __name__ == "__main__":\n'
            f"    program = {self._class_name}Program()\n"
            f"    program.run()\n"
        )


def generate_python(software_map: SoftwareMap) -> str:
    """Generate Python source code from a SoftwareMap."""
    mapper = PythonMapper(software_map)
    return mapper.generate()
