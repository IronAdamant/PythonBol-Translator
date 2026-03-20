"""Verb-specific translation methods for PythonMapper.

Extracted from mapper.py to keep each module under 500 LOC.
Contains: MOVE, GO TO, arithmetic, PERFORM,
file status, DELETE, START, CANCEL, JSON, XML translation methods.

Screen I/O methods (_collect_screen_fields, _translate_screen_display,
_translate_screen_accept) have been moved to screen_codegen.py (ScreenCodegenMixin).
"""

from __future__ import annotations

import re

from .models import (
    CobolStatement,
    DataItem,
)
from . import statement_translators as st
from .io_translators import wrap_on_size_error
from .utils import (
    _is_numeric_literal,
    _sanitize_numeric,
    _to_method_name,
    _to_python_name,
    _upper_ops,
    resolve_operand as _resolve_operand_base,
    resolve_target as _resolve_target,
)

_FD_RE = re.compile(r"^\s*(?:FD|SD)\s+([\w-]+)", re.IGNORECASE)
_LEVEL_01_RE = re.compile(r"^\s*01\s+([\w-]+)", re.IGNORECASE)


class VerbTranslationMixin:
    """Verb-specific translation methods for PythonMapper."""

    def _build_record_to_file_map(self) -> None:
        """Build mapping from FD record names to SELECT file names.

        Scans raw lines to find FD/SD declarations and their 01-level records.
        This lets WRITE (which uses record names) find the correct file adapter.
        """
        current_fd: str | None = None
        for line in self.program.raw_lines:
            fd_m = _FD_RE.match(line)
            if fd_m:
                current_fd = fd_m.group(1).upper()
                continue
            if current_fd:
                lev_m = _LEVEL_01_RE.match(line)
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

    def _translate_move(self, ops: list[str]) -> list[str]:
        if ops and ops[0].upper() in ("CORRESPONDING", "CORR"):
            return self._translate_move_corresponding(ops)
        # Detect group-level MOVE
        upper_ops = _upper_ops(ops)
        if "TO" in upper_ops and not ops[0].upper().startswith(("ALL", "FUNCTION")):
            to_idx = upper_ops.index("TO")
            source = ops[0]
            targets = ops[to_idx + 1:]
            # Skip literals and figuratives — only data names can be groups
            if (not _is_numeric_literal(source)
                    and not source.startswith(("'", '"'))
                    and source.upper() not in (
                        "ZERO", "ZEROS", "ZEROES", "SPACE", "SPACES",
                        "HIGH-VALUE", "HIGH-VALUES", "LOW-VALUE", "LOW-VALUES",
                    )):
                src_item = self._find_data_item(source)
                if src_item and src_item.children and not src_item.pic:
                    # Source is a group item — try group MOVE for each target
                    return self._translate_group_move(src_item, source, targets)
        return st.translate_move(ops)

    def _translate_move_corresponding(self, ops: list[str]) -> list[str]:
        """Translate MOVE CORRESPONDING source TO target.

        In a flat data model, source and target groups may share the same
        Python field names.  When children are unique to each group we can
        qualify them (``group_field``), otherwise emit an assignment with
        a review note.
        """
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
                "# TODO(high): group items not found — manual field matching required",
            ]
        common = set(src_items) & set(tgt_items)
        if not common:
            return [f"# MOVE CORRESPONDING: no common field names between {src_name} and {tgt_name}"]
        results = [f"# MOVE CORRESPONDING {src_name} TO {tgt_name}"]
        from . import utils as _utils
        qmap = _utils._qualified_field_map
        for name in sorted(common):
            field_py = _to_python_name(name)
            # Use qualified map for resolution
            src_resolved = qmap.get((name, src_name.upper()), field_py)
            tgt_resolved = qmap.get((name, tgt_name.upper()), field_py)
            results.append(f"self.data.{tgt_resolved}.set(self.data.{src_resolved}.value)")
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

    def _find_data_item(self, name: str) -> DataItem | None:
        """Find a DataItem by name across all sections (case-insensitive)."""
        upper = name.upper()
        def _search(items: list[DataItem]) -> DataItem | None:
            for item in items:
                if item.name.upper() == upper:
                    return item
                if item.children:
                    found = _search(item.children)
                    if found:
                        return found
            return None
        return _search(self.program.all_data_items)

    @staticmethod
    def _collect_elementary_children(
        item: DataItem,
    ) -> list[tuple[str, int]]:
        """Recursively collect all elementary (leaf) children with their PIC sizes.

        Returns list of (COBOL-name, pic_size) tuples in left-to-right order,
        flattening nested group items.
        """
        result: list[tuple[str, int]] = []
        for child in item.children:
            if child.children:
                # Nested group — recurse
                result.extend(VerbTranslationMixin._collect_elementary_children(child))
            elif child.pic:
                result.append((child.name, child.pic.size))
        return result

    def _translate_group_move(
        self, src_item: DataItem, src_name: str, targets: list[str],
    ) -> list[str]:
        """Generate code for group-level MOVE (source is a group item).

        For group-to-group: concatenate source children, distribute across
        target children.
        For group-to-elementary: concatenate source children, set target.
        """
        src_children = self._collect_elementary_children(src_item)
        if not src_children:
            # No elementary children found — fall back to normal MOVE
            return st.translate_move(
                [src_name, "TO"] + targets,
            )

        # Build source concatenation expression
        src_parts: list[str] = []
        for child_name, sz in src_children:
            py = _to_python_name(child_name)
            src_parts.append(
                f"str(self.data.{py}.value).ljust({sz})[:{sz}]"
            )
        src_concat = " + ".join(src_parts)

        results: list[str] = []
        for tgt in targets:
            tgt_item = self._find_data_item(tgt)
            if tgt_item and tgt_item.children and not tgt_item.pic:
                # Group-to-group MOVE
                tgt_children = self._collect_elementary_children(tgt_item)
                if tgt_children:
                    results.append(
                        f"# Group MOVE: {src_name} TO {tgt}"
                    )
                    results.append(f"_grp_val = {src_concat}")
                    offset = 0
                    for child_name, sz in tgt_children:
                        py = _to_python_name(child_name)
                        results.append(
                            f"self.data.{py}.set("
                            f"_grp_val[{offset}:{offset + sz}])"
                        )
                        offset += sz
                else:
                    # Target group has no elementary children
                    results.append(
                        f"# Group MOVE {src_name} TO {tgt}: "
                        f"target has no elementary children"
                    )
            else:
                # Group-to-elementary MOVE — treat source as alphanumeric
                results.append(f"# Group-to-elementary MOVE: {src_name} TO {tgt}")
                results.append(
                    f"{_resolve_target(tgt)}.set({src_concat})"
                )
        return results

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
        results = [f"# {verb} CORRESPONDING {src_name} {to_kw} {tgt_name}"]
        from . import utils as _utils
        qmap = _utils._qualified_field_map
        for name in sorted(common):
            field_py = _to_python_name(name)
            src_resolved = qmap.get((name, src_name.upper()), field_py)
            tgt_resolved = qmap.get((name, tgt_name.upper()), field_py)
            results.append(f"self.data.{tgt_resolved}.{method}(self.data.{src_resolved}.value)")
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
        """Translate GO TO verb to Python.

        When a paragraph is known to be ALTER-modified (from CFG analysis),
        uses dynamic dispatch via getattr() so the target can be changed
        at runtime by ALTER statements.
        """
        if not ops:
            # Empty GO TO — must be ALTER-modified
            return [
                "getattr(self, self._goto_target_current)()"
                "  # ALTER-modified GO TO (dynamic dispatch)",
                "return",
            ]
        upper_ops = _upper_ops(ops)

        # Filter out the "TO" keyword if present
        filtered = [o for i, o in enumerate(ops) if upper_ops[i] != "TO"]
        upper_filtered = [u for u in upper_ops if u != "TO"]

        if not filtered:
            return [
                "getattr(self, self._goto_target_current)()"
                "  # ALTER-modified GO TO (dynamic dispatch)",
                "return",
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

        # Simple GO TO paragraph-name
        if len(filtered) == 1:
            method = _to_method_name(filtered[0])
            # Check if the containing paragraph is ALTER-modified
            alter_targets = getattr(self, '_alter_targets', set())
            # Find which paragraph we're in by checking if filtered[0] is an ALTER target
            # (ALTER changes where a paragraph's GO TO jumps, not the GO TO's own target)
            return [
                f"self.{method}()  # GO TO {filtered[0]}",
                "return",
            ]

        # Multiple targets without DEPENDING — ALTER-modified GO TO
        lines = [f"# GO TO with multiple targets: {' '.join(filtered)}"]
        # Use the first target's method name as the default state variable
        default_method = _to_method_name(filtered[0])
        py_current = _to_method_name(filtered[0])
        lines.append(
            f"getattr(self, getattr(self, '_goto_target_{py_current}', "
            f"'{default_method}'))()"
            f"  # ALTER-modified GO TO (dynamic dispatch)"
        )
        lines.append("return")
        return lines

    def _translate_alter(self, ops: list[str]) -> list[str]:
        """Translate ALTER verb: ALTER para-1 TO [PROCEED TO] para-2.

        Generates a state variable update that modifies which method a
        GO TO paragraph dispatches to at runtime.
        """
        upper_ops = _upper_ops(ops)
        # Filter out keywords TO, PROCEED
        filtered = [o for i, o in enumerate(ops)
                    if upper_ops[i] not in ("TO", "PROCEED")]
        if len(filtered) < 2:
            return [
                f"# ALTER {' '.join(ops)}",
                "# TODO(high): ALTER requires at least source and target paragraphs",
            ]
        altered_para = filtered[0]
        new_target = filtered[1]
        py_altered = _to_method_name(altered_para)
        py_target = _to_method_name(new_target)
        return [
            f"# ALTER {altered_para} TO PROCEED TO {new_target}",
            f"self._goto_target_{py_altered} = '{py_target}'",
        ]

    # --- SCREEN SECTION support ---

    def _translate_display_or_screen(self, stmt: CobolStatement) -> list[str]:
        """Route DISPLAY to screen handler or standard translator."""
        if stmt.operands:
            name = stmt.operands[0].upper()
            if name in self._screen_lookup:
                return self._translate_screen_display(self._screen_lookup[name])
        return st.translate_display(stmt, self._resolve_operand)

    def _translate_accept_or_screen(self, stmt: CobolStatement) -> list[str]:
        """Route ACCEPT to screen handler or standard translator."""
        if stmt.operands:
            name = stmt.operands[0].upper()
            if name in self._screen_lookup:
                return self._translate_screen_accept(self._screen_lookup[name])
        return st.translate_accept(stmt.operands, stmt.raw_text)

