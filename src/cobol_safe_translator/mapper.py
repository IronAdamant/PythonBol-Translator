"""Translates a CobolProgram AST into Python source code.

Pipeline position: Parser -> AST -> Analyzer -> **Mapper** -> Python source

Generated code uses adapter classes (CobolDecimal, CobolString, FileAdapter)
to preserve COBOL semantics.

The mapper is split across four modules for maintainability:
  - mapper.py          — Core orchestration (this file)
  - mapper_codegen.py  — Code generation methods (header, imports, data class, etc.)
  - mapper_verbs.py    — Verb-specific translation methods (MOVE, GO TO, etc.)
  - screen_codegen.py  — Screen section layout comments and I/O translation
"""

from __future__ import annotations

from .condition_translator import translate_condition as _translate_condition_impl
from .mapper_codegen import CodegenMixin
from .mapper_verbs import VerbTranslationMixin
from .screen_codegen import ScreenCodegenMixin
from .models import (
    CobolStatement,
    DataItem,
    SensitivityFlag,
    SoftwareMap,
)
from . import statement_translators as st
from . import string_translators as strt
from . import sort_translators as sort_t
from . import report_translators as rpt_t
from .utils import (
    _is_numeric_literal,
    _sanitize_numeric,
    _to_python_name,
    _upper_ops,
    resolve_operand as _resolve_operand_base,
)


_ARITHMETIC_VERBS = frozenset({"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"})
_ORPHAN_SCOPE_VERBS = frozenset({
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
    "END-WRITE", "END-CALL", "END-STRING",
})
_COMM_VERBS = frozenset({"ENABLE", "DISABLE", "SEND", "RECEIVE", "PURGE"})


class PythonMapper(CodegenMixin, ScreenCodegenMixin, VerbTranslationMixin):
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
        # Build screen name lookup for ACCEPT/DISPLAY screen-name support
        self._screen_lookup: dict[str, object] = {}
        for sf in self.program.screen_section:
            if sf.name:
                self._screen_lookup[sf.name.upper()] = sf
        self._verb_handlers = {
            "DISPLAY": lambda s: self._translate_display_or_screen(s),
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
            "ACCEPT": lambda s: self._translate_accept_or_screen(s),
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

    _resolve_operand = staticmethod(_resolve_operand_base)

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

    def _translate_condition(self, cond: str) -> str:
        """Two-pass COBOL condition to Python expression translator.

        Delegates to condition_translator module, passing the 88-level lookup.
        """
        return _translate_condition_impl(cond, self._condition_lookup)

    # --- Simple verb handlers (called from _verb_handlers / _translate_statement) ---

    def _translate_cancel(self, ops: list[str]) -> list[str]:
        """Translate CANCEL verb."""
        program = ops[0].strip('"').strip("'") if ops else "UNKNOWN"
        return [f"# CANCEL {program} — release subprogram resources (no-op in Python; garbage collected)"]

    def _translate_delete(self, ops: list[str]) -> list[str]:
        """Translate DELETE verb for indexed/relative files."""
        if not ops:
            return ["# DELETE: no file specified"]
        file_name = _to_python_name(ops[0])
        upper_ops = _upper_ops(ops)

        # Check for RECORD KEY clause: DELETE file-name RECORD [KEY IS field]
        key_expr = None
        if "KEY" in upper_ops:
            key_idx = upper_ops.index("KEY")
            offset = key_idx + 1
            if offset < len(upper_ops) and upper_ops[offset] == "IS":
                offset += 1
            if offset < len(ops):
                key_expr = self._resolve_operand(ops[offset])

        lines: list[str] = []
        if key_expr:
            lines.append(f"self.{file_name}.delete(key=str({key_expr}))")
        else:
            lines.append(f"self.{file_name}.delete()")

        # Handle INVALID KEY / NOT INVALID KEY clauses
        if "INVALID" in upper_ops:
            lines.append(f'if self.{file_name}.status == "23":')
            lines.append(f"    pass  # INVALID KEY handler")
        return lines

    def _translate_start(self, ops: list[str], raw: str) -> list[str]:
        """Translate START verb for indexed/relative files."""
        if not ops:
            return ["# START: no file specified"]
        file_name = ops[0]
        py_file = _to_python_name(file_name)
        upper_ops = _upper_ops(ops)
        comparison = "EQUAL"
        field = ""
        if "KEY" in upper_ops:
            key_idx = upper_ops.index("KEY")
            next_idx = key_idx + 1
            if next_idx < len(upper_ops) and upper_ops[next_idx] == "IS":
                next_idx += 1
            if next_idx < len(upper_ops):
                comp = upper_ops[next_idx]
                if comp in ("EQUAL", "=", "EQUALS"):
                    comparison = "EQUAL"
                    next_idx += 1
                elif comp in ("GREATER", ">"):
                    comparison = "GREATER"
                    next_idx += 1
                elif comp == "NOT" and next_idx + 1 < len(upper_ops) and upper_ops[next_idx + 1] in ("LESS", "<"):
                    comparison = "NOT LESS"
                    next_idx += 2
                elif comp in (">=",):
                    comparison = "GREATER OR EQUAL"
                    next_idx += 1
                if next_idx < len(upper_ops) and upper_ops[next_idx] == "THAN":
                    next_idx += 1
            if next_idx < len(ops):
                field = ops[next_idx]

        lines: list[str] = []
        if field:
            key_expr = self._resolve_operand(field)
            lines.append(
                f'self.{py_file}.start(key=str({key_expr}), '
                f'comparison="{comparison}")'
            )
        else:
            lines.append(
                f'self.{py_file}.start(key="", comparison="{comparison}")'
            )

        # Handle INVALID KEY clause
        if "INVALID" in upper_ops:
            lines.append(f'if self.{py_file}.status == "23":')
            lines.append(f"    pass  # INVALID KEY handler")
        return lines

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


def generate_python(software_map: SoftwareMap) -> str:
    """Generate Python source code from a SoftwareMap.

    When the program contains ``nested_programs``, each nested program
    is analyzed and translated into its own class within the same
    module.  Only the outermost program gets the
    ``if __name__ == "__main__"`` block.
    """
    from .analyzer import analyze

    mapper = PythonMapper(software_map)
    parts: list[str] = []

    # Header + imports (emitted once for the whole module)
    mapper._program_id = mapper.program.program_id or "UNNAMED"
    mapper._class_name = (
        _to_python_name(mapper._program_id).title().replace("_", "")
    )
    parts.append(mapper._header())
    parts.append(mapper._imports())

    # Main program data + class
    parts.append(mapper._data_class())
    parts.append(mapper._program_class())

    # Nested / concatenated programs
    for nested_prog in software_map.program.nested_programs:
        nested_smap = analyze(nested_prog)
        nested_mapper = PythonMapper(nested_smap)
        nested_mapper._program_id = nested_prog.program_id or "UNNAMED"
        nested_mapper._class_name = (
            _to_python_name(nested_mapper._program_id).title().replace("_", "")
        )
        # Emit a separator comment for clarity
        parts.append(
            f"# --- Nested/concatenated program: {nested_prog.program_id} ---\n"
        )
        # GLOBAL data linkage hint
        global_items = [
            item for item in software_map.program.all_data_items
            if item.is_global
        ]
        if global_items:
            names = ", ".join(item.name for item in global_items)
            parts.append(
                f"# TODO(high): GLOBAL data items from outer program ({names})"
                f" should be shared with this nested program.\n"
            )
        parts.append(nested_mapper._data_class())
        parts.append(nested_mapper._program_class())

    # Only the outermost program gets the main block
    parts.append(mapper._main_block())

    # CICS Flask template (appended as commented-out section)
    from .cics_translator import has_cics, generate_cics_template
    if has_cics(software_map.program):
        cics_template = generate_cics_template(software_map.program)
        if cics_template:
            parts.append("")
            parts.append("# " + "=" * 60)
            parts.append(
                "# CICS TRANSACTION FRAMEWORK (Flask template)"
            )
            parts.append(
                "# Uncomment and save as a separate file to use."
            )
            parts.append("# Install: pip install flask")
            parts.append("# " + "=" * 60)
            for tpl_line in cics_template.splitlines():
                parts.append(f"# {tpl_line}" if tpl_line else "#")

    return "\n".join(parts)
