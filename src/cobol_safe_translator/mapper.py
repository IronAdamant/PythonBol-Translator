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
    UseDeclaration,
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
    resolve_figurative,
    resolve_operand as _resolve_operand_base,
)


_ARITHMETIC_VERBS = frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"})
_ORPHAN_SCOPE_VERBS = frozenset({
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
    "END-WRITE", "END-CALL", "END-STRING",
})
_COMM_VERBS = frozenset({"ENABLE", "DISABLE", "SEND", "RECEIVE", "PURGE"})


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
        self._build_condition_lookup(software_map.program.all_data_items)
        # Map python file names to their FILE STATUS variable python names
        self._file_status_lookup: dict[str, str] = {}
        for fc in self.program.file_controls:
            if fc.file_status:
                py_file = _to_python_name(fc.select_name)
                py_status = _to_python_name(fc.file_status)
                self._file_status_lookup[py_file] = py_status
        # Map record python names to their file adapter python names (for WRITE)
        self._record_to_file: dict[str, str] = {}
        self._build_record_to_file_map()
        self._verb_handlers = {
            "DISPLAY": lambda s: st.translate_display(s, self._resolve_operand),
            "MOVE": lambda s: self._translate_move(s.operands),
            "PERFORM": lambda s: self._translate_perform(s.operands, s.raw_text),
            "OPEN": lambda s: self._wrap_file_status(st.translate_open(s.operands), s.operands, "OPEN"),
            "CLOSE": lambda s: self._wrap_file_status(st.translate_close(s.operands), s.operands, "CLOSE"),
            "READ": lambda s: self._wrap_file_status(st.translate_read(s.operands, s.raw_text), s.operands, "READ"),
            "WRITE": lambda s: self._wrap_file_status(st.translate_write(s.operands), s.operands, "WRITE"),
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
            "SORT": lambda s: sort_t.translate_sort(s.operands, self.program.file_section),
            "MERGE": lambda s: sort_t.translate_merge(s.operands),
            "RELEASE": lambda s: sort_t.translate_release(s.operands),
            "RETURN": lambda s: sort_t.translate_return_verb(s.operands, s.raw_text),
            "INITIATE": lambda s: rpt_t.translate_initiate(s.operands, self.program.report_section),
            "GENERATE": lambda s: rpt_t.translate_generate(s.operands, self.program.report_section),
            "TERMINATE": lambda s: rpt_t.translate_terminate(s.operands, self.program.report_section),
            "USE": lambda s: [f"# USE declarative (handled via DECLARATIVES section): {s.raw_text}"],
            "CANCEL": lambda s: self._translate_cancel(s.operands),
            "DELETE": lambda s: self._translate_delete(s.operands),
            "START": lambda s: self._translate_start(s.operands, s.raw_text),
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

    def _build_record_to_file_map(self) -> None:
        """Build mapping from FD record names to SELECT file names.

        Scans raw lines to find FD/SD declarations and their 01-level records.
        This lets WRITE (which uses record names) find the correct file adapter.
        """
        import re
        fd_re = re.compile(r"^\s*(?:FD|SD)\s+([\w-]+)", re.IGNORECASE)
        level_re = re.compile(r"^\s*01\s+([\w-]+)", re.IGNORECASE)
        current_fd: str | None = None
        for line in self.program.raw_lines:
            fd_m = fd_re.match(line)
            if fd_m:
                current_fd = fd_m.group(1).upper()
                continue
            if current_fd:
                lev_m = level_re.match(line)
                if lev_m:
                    rec_name = lev_m.group(1).upper()
                    py_rec = _to_python_name(rec_name)
                    py_file = _to_python_name(current_fd)
                    self._record_to_file[py_rec] = py_file
                upper = line.strip().upper()
                # End of FD scope when another section or FD starts
                if any(kw in upper for kw in (
                    "WORKING-STORAGE SECTION", "LINKAGE SECTION",
                    "LOCAL-STORAGE SECTION", "PROCEDURE DIVISION",
                    "REPORT SECTION",
                )):
                    current_fd = None

    def _extract_file_names(self, ops: list[str], verb: str) -> list[str]:
        """Extract python file adapter names from I/O verb operands."""
        if verb == "OPEN" and len(ops) >= 2:
            return [_to_python_name(fn) for fn in ops[1:]]
        if verb == "CLOSE":
            _close_kw = frozenset({"WITH", "LOCK", "NO", "REWIND"})
            return [_to_python_name(op) for op in ops if op.upper() not in _close_kw]
        if verb == "READ" and ops:
            return [_to_python_name(ops[0])]
        if verb == "WRITE" and ops:
            py_record = _to_python_name(ops[0])
            # Use record-to-file map if available, fall back to heuristic
            if py_record in self._record_to_file:
                return [self._record_to_file[py_record]]
            from .utils import _file_hint_from_record
            return [_file_hint_from_record(py_record)]
        return []

    def _wrap_file_status(self, lines: list[str], ops: list[str], verb: str) -> list[str]:
        """Append FILE STATUS update lines after I/O operations when applicable."""
        if not self._file_status_lookup:
            return lines
        file_names = self._extract_file_names(ops, verb)
        status_lines: list[str] = []
        for fn in file_names:
            if fn in self._file_status_lookup:
                status_var = self._file_status_lookup[fn]
                status_lines.append(
                    f"self.data.{status_var}.set(self.{fn}.status)"
                )
        return lines + status_lines

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
            "  - GO TO statements are translated as method calls with return. Review control",
            "    flow for correctness, especially GO TO DEPENDING ON and ALTER-modified targets.",
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
        all_items = self.program.all_data_items
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

        # Data item attribute annotations
        if item.is_external:
            lines.append(f"{prefix}# EXTERNAL — shared across programs")
        if item.is_global:
            lines.append(f"{prefix}# GLOBAL — visible to nested programs")
        if item.justified_right:
            lines.append(f"{prefix}# JUSTIFIED RIGHT — value right-justified on MOVE")
        if item.blank_when_zero:
            lines.append(f"{prefix}# BLANK WHEN ZERO — display as spaces when value is zero")
        if item.occurs_depending:
            lines.append(f"{prefix}# OCCURS DEPENDING ON {item.occurs_depending} — dynamic array sizing")

        if item.children:
            # Group item — add a comment
            lines.append(f"{prefix}# Group: {item.name} (level {item.level:02d})")
            if item.occurs:
                lines.append(f"{prefix}_{py_name}_occurs: int = {item.occurs}")
            for child in item.children:
                lines.extend(self._data_item_fields(child, indent, occurs_chain))
        elif item.pic:
            usage_upper = (item.usage or "").upper()

            # COMP-1/COMP-2 -> float (single/double precision floating-point)
            if usage_upper in ("COMP-1", "COMP-2", "COMPUTATIONAL-1", "COMPUTATIONAL-2"):
                inner = "0.0"
                type_name = "float"
            # COMP-5 -> native binary int (no PIC-based truncation)
            elif usage_upper in ("COMP-5", "COMPUTATIONAL-5"):
                inner = "0"
                type_name = "int"
            elif item.pic.category in (PicCategory.NUMERIC, PicCategory.EDITED):
                dec = item.pic.decimals
                int_digits = item.pic.size - dec
                signed = "True" if item.pic.signed else "False"
                init = resolve_figurative(item.value, numeric=True) if item.value else "0"
                inner = f"CobolDecimal({int_digits}, {dec}, {signed}, {init!r})"
                type_name = "CobolDecimal"
            else:
                init = resolve_figurative(item.value, numeric=False) if item.value else ""
                inner = f"CobolString({item.pic.size}, {init!r})"
                type_name = "CobolString"

            if occurs_chain:
                # Wrap in nested list comprehensions (innermost OCCURS first)
                expr = inner
                for n in reversed(occurs_chain):
                    expr = f"[{expr} for _ in range({n})]"
                lines.append(
                    f"{prefix}{py_name}: list = field(default_factory=lambda: {expr})"
                )
            else:
                if type_name in ("float", "int"):
                    lines.append(f"{prefix}{py_name}: {type_name} = {inner}")
                else:
                    lines.append(
                        f"{prefix}{py_name}: {type_name} = field(default_factory=lambda: {inner})"
                    )
        elif item.usage and item.usage.upper() == "INDEX":
            # INDEX usage -- 1-based index value (no PIC needed)
            if occurs_chain:
                expr = "1"
                for n in reversed(occurs_chain):
                    expr = f"[{expr} for _ in range({n})]"
                lines.append(
                    f"{prefix}{py_name}: list = field(default_factory=lambda: {expr})"
                )
            else:
                lines.append(f"{prefix}{py_name}: int = 1")
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
            safe_path = fc.assign_to.replace("\\", "\\\\")
            lines.append(f'        self.{py_name} = FileAdapter("{safe_path}")')
            if fc.file_status:
                py_status = _to_python_name(fc.file_status)
                lines.append(
                    f'        # FILE STATUS linked: self.data.{py_status}'
                    f' updated from self.{py_name}.status after each I/O'
                )

        # Register USE declarative handlers
        for decl in self.program.declaratives:
            handler_name = _to_method_name(decl.section_name)
            targets_str = ", ".join(decl.targets) if decl.targets else "ALL"
            lines.append(
                f"        self._use_{handler_name} = self.{handler_name}"
                f"  # USE {decl.use_type} ON {targets_str}"
            )

        lines.append("")

        # Generate methods for declarative sections
        for decl in self.program.declaratives:
            lines.append(self._declarative_method(decl))

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

            # Inline PERFORM VARYING/UNTIL — consume body until END-PERFORM
            if (stmt.verb == "PERFORM" and stmt.operands
                    and stmt.operands[0].upper() in ("VARYING", "UNTIL", "WITH")):
                block_lines, i = self._translate_inline_perform_block(
                    para.statements, i,
                )
                lines.extend(block_lines)
                continue

            translated = self._translate_statement(stmt)
            for tl in translated:
                lines.append(f"        {tl}")
            i += 1

        lines.append("")
        return "\n".join(lines)

    def _declarative_method(self, decl: UseDeclaration) -> str:
        """Generate a method for a USE declarative section."""
        method_name = _to_method_name(decl.section_name)
        targets_str = ", ".join(decl.targets) if decl.targets else "ALL"
        global_str = " GLOBAL" if decl.is_global else ""
        lines = [f"    def {method_name}(self) -> None:"]
        lines.append(
            f'        """USE{global_str} {decl.before_after} {decl.use_type}'
            f' ON {targets_str}"""'
        )

        # Translate handler body paragraphs
        has_body = False
        for para in decl.paragraphs:
            if para.statements:
                has_body = True
                lines.append(f"        # --- {para.name} ---")
                for stmt in para.statements:
                    translated = self._translate_statement(stmt)
                    for tl in translated:
                        lines.append(f"        {tl}")

        if not has_body:
            lines.append(
                f"        pass  # TODO(high): implement USE {decl.use_type}"
                f" handler for {targets_str}"
            )

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

        # GO TO — translate to method call + return
        if verb == "GO":
            return self._translate_goto(stmt.operands, stmt.raw_text)

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

        # Communication verbs (legacy)
        if verb in _COMM_VERBS:
            return [f"# {verb} — legacy communication verb (map to modern messaging)"]
        if verb in ("NOT", "AT"):
            return [f"# {stmt.raw_text}"]
        if verb == "END":
            return []  # END PROGRAM / END METHOD — silently consumed
        if verb.startswith("END-"):
            return []  # scope terminators — silently consumed
        # ENTRY — alternate program entry point
        if verb == "ENTRY":
            entry_name = stmt.operands[0] if stmt.operands else "UNKNOWN"
            return [f"# ENTRY {entry_name} — alternate entry point (use as separate function if needed)"]
        # JSON GENERATE/PARSE — Enterprise COBOL v6 extension
        if verb == "JSON":
            return self._translate_json(stmt.operands, stmt.raw_text)
        # XML GENERATE/PARSE — Enterprise COBOL v4+ extension
        if verb == "XML":
            return self._translate_xml(stmt.operands, stmt.raw_text)
        # MicroFocus directives ($REGION, $END-REGION, etc.)
        if verb.startswith("$"):
            return []
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
        result = self._search_group(self.program.all_data_items, group_name)
        return result if result is not None else []

    def _search_group(self, items: list[DataItem], name: str) -> list[str] | None:
        for item in items:
            if item.name.upper() == name and item.children:
                return [c.name.upper() for c in item.children]
            if item.children:
                result = self._search_group(item.children, name)
                if result is not None:
                    return result
        return None

    _resolve_operand = staticmethod(_resolve_operand_base)

    def _translate_arithmetic(self, verb: str, ops: list[str]) -> list[str]:
        """Route arithmetic verb and wrap with ON SIZE ERROR if present."""
        # ADD/SUBTRACT CORRESPONDING
        if verb in ("ADD", "SUBTRACT") and ops and ops[0].upper() in ("CORRESPONDING", "CORR"):
            return self._translate_arith_corresponding(verb, ops)
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

    def _translate_arith_corresponding(self, verb: str, ops: list[str]) -> list[str]:
        """Translate ADD/SUBTRACT CORRESPONDING source TO/FROM target."""
        upper_ops = _upper_ops(ops)
        to_kw = "TO" if verb == "ADD" else "FROM"
        if to_kw not in upper_ops:
            return [f"# {verb} CORRESPONDING: missing {to_kw}: {' '.join(ops)}"]
        kw_idx = upper_ops.index(to_kw)
        src_name = ops[1] if len(ops) > 1 else "SOURCE"
        tgt_name = ops[kw_idx + 1] if kw_idx + 1 < len(ops) else "TARGET"
        src_items = self._find_group_children(src_name.upper())
        tgt_items = self._find_group_children(tgt_name.upper())
        if not src_items or not tgt_items:
            return [
                f"# {verb} CORRESPONDING {src_name} {to_kw} {tgt_name}",
                f"# TODO(high): group items not found — manual field matching required",
            ]
        common = set(src_items) & set(tgt_items)
        if not common:
            return [f"# {verb} CORRESPONDING: no common field names between {src_name} and {tgt_name}"]
        method = "add" if verb == "ADD" else "subtract"
        results = [
            f"# {verb} CORRESPONDING {src_name} {to_kw} {tgt_name}",
            f"# TODO(high): flat data model cannot distinguish group-qualified fields — verify operations",
        ]
        for name in sorted(common):
            py = _to_python_name(name)
            results.append(f"self.data.{py}.{method}(self.data.{py}.value)")
        return results

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

    def _translate_inline_perform_block(
        self, statements: list[CobolStatement], start: int,
    ) -> tuple[list[str], int]:
        """Handle inline PERFORM VARYING/UNTIL ... END-PERFORM as a block."""
        stmt = statements[start]
        # Generate the loop header via the normal PERFORM translator
        header_lines = st.translate_perform(
            stmt.operands, stmt.raw_text, self._translate_condition,
            get_paragraph_range=self._get_paragraph_range,
        )

        # Find the innermost while loop's indentation depth
        depth = 0
        for hl in header_lines:
            stripped = hl.lstrip()
            if stripped.startswith("while not ") or stripped.startswith("while True"):
                depth = (len(hl) - len(stripped)) // 4 + 1

        # Collect body statements until END-PERFORM
        body_stmts: list[CobolStatement] = []
        i = start + 1
        while i < len(statements):
            s = statements[i]
            if s.verb == "END-PERFORM":
                i += 1
                break
            body_stmts.append(s)
            i += 1

        # Translate body and place at innermost depth
        body_lines: list[str] = []
        for bs in body_stmts:
            for tl in self._translate_statement(bs):
                body_lines.append(f"{'    ' * depth}{tl}")

        # Ensure body has at least one executable statement (not just comments)
        if body_lines and all(bl.lstrip().startswith("#") for bl in body_lines):
            body_lines.insert(0, f"{'    ' * depth}pass")

        # Rebuild: header lines, replacing the pass/TODO with actual body,
        # then step increments
        result: list[str] = []
        for hl in header_lines:
            stripped = hl.lstrip()
            if stripped.startswith("pass  # TODO(high): inline PERFORM"):
                if body_lines:
                    for bl in body_lines:
                        result.append(f"        {bl}")
                else:
                    result.append(f"        {hl}")
            else:
                result.append(f"        {hl}")

        return result, i

    def _translate_perform(self, ops: list[str], raw: str) -> list[str]:
        return st.translate_perform(
            ops, raw, self._translate_condition,
            get_paragraph_range=self._get_paragraph_range,
        )

    def _translate_goto(self, ops: list[str], raw: str) -> list[str]:
        """Translate GO TO verb to Python."""
        if not ops:
            return [
                "raise NotImplementedError('GO TO with no target (ALTER-modified)')",
                "# TODO(high): ALTER-modified GO TO requires manual restructuring",
            ]
        upper_ops = _upper_ops(ops)

        # Filter out the "TO" keyword if present
        filtered = [o for i, o in enumerate(ops) if upper_ops[i] != "TO"]
        upper_filtered = [u for u in upper_ops if u != "TO"]

        if not filtered:
            return [
                "raise NotImplementedError('GO TO with no target')",
                "# TODO(high): GO TO requires manual restructuring",
            ]

        # GO TO ... DEPENDING ON variable
        if "DEPENDING" in upper_filtered:
            dep_idx = upper_filtered.index("DEPENDING")
            targets = filtered[:dep_idx]
            # Find the variable after DEPENDING [ON]
            var_idx = dep_idx + 1
            if var_idx < len(filtered) and upper_filtered[var_idx] == "ON":
                var_idx += 1
            if var_idx >= len(filtered):
                return [f"# GO TO DEPENDING: missing variable: {raw}"]
            dep_var = _resolve_operand_base(filtered[var_idx])
            lines = [f"# GO TO DEPENDING ON {filtered[var_idx]}"]
            for i, target in enumerate(targets, 1):
                method = _to_method_name(target)
                prefix = "if" if i == 1 else "elif"
                lines.append(f"{prefix} int({dep_var}) == {i}:")
                lines.append(f"    self.{method}()")
                lines.append(f"    return")
            return lines

        # Simple GO TO paragraph-name (possibly multiple targets from ALTER)
        if len(filtered) == 1:
            method = _to_method_name(filtered[0])
            return [
                f"self.{method}()  # GO TO {filtered[0]}",
                "return",
            ]

        # Multiple targets without DEPENDING — list of possible targets (from ALTER)
        lines = [f"# GO TO with multiple targets: {' '.join(filtered)}"]
        lines.append(f"# TODO(high): multiple GO TO targets suggest ALTER usage — pick the correct target")
        method = _to_method_name(filtered[0])
        lines.append(f"self.{method}()  # defaulting to first target")
        lines.append("return")
        return lines

    def _translate_condition(self, cond: str) -> str:
        """Two-pass COBOL condition to Python expression translator.

        Delegates to condition_translator module, passing the 88-level lookup.
        """
        return _translate_condition_impl(cond, self._condition_lookup)

    def _translate_cancel(self, ops: list[str]) -> list[str]:
        """Translate CANCEL verb."""
        program = ops[0].strip('"').strip("'") if ops else "UNKNOWN"
        return [f"# CANCEL {program} — release subprogram resources (no-op in Python; garbage collected)"]

    def _translate_delete(self, ops: list[str]) -> list[str]:
        """Translate DELETE verb."""
        if not ops:
            return ["# DELETE: no file specified"]
        file_name = _to_python_name(ops[0])
        return [f"self.{file_name}.delete()  # TODO(high): implement DELETE for indexed/relative file"]

    def _translate_start(self, ops: list[str], raw: str) -> list[str]:
        """Translate START verb."""
        if not ops:
            return ["# START: no file specified"]
        file_name = ops[0]
        upper_ops = _upper_ops(ops)
        comparison = "="
        field = ""
        if "KEY" in upper_ops:
            key_idx = upper_ops.index("KEY")
            next_idx = key_idx + 1
            if next_idx < len(upper_ops) and upper_ops[next_idx] == "IS":
                next_idx += 1
            if next_idx < len(upper_ops):
                comp = upper_ops[next_idx]
                if comp in ("EQUAL", "=", "EQUALS"):
                    comparison = "="
                    next_idx += 1
                elif comp in ("GREATER", ">"):
                    comparison = ">"
                    next_idx += 1
                elif comp == "NOT" and next_idx + 1 < len(upper_ops) and upper_ops[next_idx + 1] in ("LESS", "<"):
                    comparison = ">="
                    next_idx += 2
                elif comp in (">=",):
                    comparison = ">="
                    next_idx += 1
                if next_idx < len(upper_ops) and upper_ops[next_idx] == "THAN":
                    next_idx += 1
            if next_idx < len(ops):
                field = ops[next_idx]
        return [f"# TODO(high): START {file_name} KEY IS {comparison} {field} — position file pointer"]

    def _translate_json(self, ops: list[str], raw: str) -> list[str]:
        """Translate JSON GENERATE/PARSE verb."""
        if not ops:
            return [
                "import json",
                "# TODO(high): JSON GENERATE/PARSE — use json.dumps() or json.loads()",
            ]
        sub = ops[0].upper()
        if sub == "GENERATE":
            target = ops[1] if len(ops) > 1 else "TARGET"
            source = ""
            upper_ops = _upper_ops(ops)
            if "FROM" in upper_ops:
                from_idx = upper_ops.index("FROM")
                if from_idx + 1 < len(ops):
                    source = ops[from_idx + 1]
            return [
                f"# JSON GENERATE {target} FROM {source}",
                f"import json",
                f"# TODO(high): {_to_python_name(target)} = json.dumps(field_mapping)",
            ]
        if sub == "PARSE":
            source = ops[1] if len(ops) > 1 else "SOURCE"
            return [
                f"# JSON PARSE {source}",
                f"import json",
                f"# TODO(high): parsed = json.loads({_to_python_name(source)})",
            ]
        return [f"# TODO(high): unsupported JSON sub-verb {sub}", f"# {raw}"]

    def _translate_xml(self, ops: list[str], raw: str) -> list[str]:
        """Translate XML GENERATE/PARSE verb."""
        if not ops:
            return [
                "import xml.etree.ElementTree as ET",
                "# TODO(high): XML GENERATE/PARSE — use xml.etree.ElementTree",
            ]
        sub = ops[0].upper()
        if sub == "GENERATE":
            target = ops[1] if len(ops) > 1 else "TARGET"
            source = ""
            upper_ops = _upper_ops(ops)
            if "FROM" in upper_ops:
                from_idx = upper_ops.index("FROM")
                if from_idx + 1 < len(ops):
                    source = ops[from_idx + 1]
            return [
                f"# XML GENERATE {target} FROM {source}",
                f"import xml.etree.ElementTree as ET",
                f"# TODO(high): build XML from {_to_python_name(source or target)} fields using ET",
            ]
        if sub == "PARSE":
            source = ops[1] if len(ops) > 1 else "SOURCE"
            return [
                f"# XML PARSE {source}",
                f"import xml.etree.ElementTree as ET",
                f"# TODO(high): tree = ET.fromstring({_to_python_name(source)})",
            ]
        return [f"# TODO(high): unsupported XML sub-verb {sub}", f"# {raw}"]

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
