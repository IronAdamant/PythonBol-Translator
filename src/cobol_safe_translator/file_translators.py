"""File I/O and miscellaneous verb translators (OPEN, WRITE, CLOSE, READ, CALL, INITIALIZE).

Split from statement_translators.py to comply with the 500 LOC guideline.
Each function translates a specific COBOL file/misc verb into Python code.
"""

from __future__ import annotations

from .utils import (
    _file_hint_from_record,
    _is_numeric_literal,
    _to_method_name,
    _to_python_name,
    _upper_ops,
    extract_from_expr,
    resolve_operand as _resolve_operand,
    resolve_target as _resolve_target,
)


# Keywords that should be filtered from CLOSE operand lists
_CLOSE_KEYWORDS = frozenset({"WITH", "LOCK", "NO", "REWIND"})

_OPEN_MODES: dict[str, str] = {
    "INPUT": "open_input", "OUTPUT": "open_output",
    "EXTEND": "open_extend", "I-O": "open_io", "IO": "open_io",
}


def translate_open(ops: list[str]) -> list[str]:
    """Translate OPEN verb."""
    if len(ops) >= 2:
        method = _OPEN_MODES.get(ops[0].upper())
        if method:
            return [f"self.{_to_python_name(fn)}.{method}()" for fn in ops[1:]]
    return [f"# OPEN: could not parse: {' '.join(ops)}"]


def translate_write(ops: list[str]) -> list[str]:
    """Translate WRITE verb."""
    if not ops:
        return ["# WRITE: no record specified"]
    record_name = ops[0]
    py_record = _to_python_name(record_name)
    upper_ops = _upper_ops(ops)

    file_hint = _file_hint_from_record(py_record)

    # Check for FROM clause: WRITE record FROM data-name
    from_expr = extract_from_expr(ops, upper_ops)

    # Parse AFTER/BEFORE ADVANCING clause
    advancing_prefix = ""
    advancing_suffix = ""
    for adv_kw in ("AFTER", "BEFORE"):
        if adv_kw in upper_ops:
            adv_idx = upper_ops.index(adv_kw)
            # Skip optional ADVANCING keyword
            next_idx = adv_idx + 1
            if next_idx < len(upper_ops) and upper_ops[next_idx] == "ADVANCING":
                next_idx += 1
            if next_idx < len(upper_ops):
                adv_value = upper_ops[next_idx]
                if adv_value == "PAGE":
                    if adv_kw == "AFTER":
                        advancing_prefix = "'\\f' + "
                    else:
                        advancing_suffix = " + '\\f'"
                elif _is_numeric_literal(ops[next_idx]):
                    n = int(float(ops[next_idx]))
                    if adv_kw == "AFTER":
                        advancing_prefix = f"'\\n' * {n} + " if n > 0 else ""
                    else:
                        advancing_suffix = f" + '\\n' * {n}" if n > 0 else ""
                else:
                    # Variable number of lines
                    py_var = _to_python_name(ops[next_idx])
                    if adv_kw == "AFTER":
                        advancing_prefix = f"'\\n' * int(self.data.{py_var}.value) + "
                    else:
                        advancing_suffix = f" + '\\n' * int(self.data.{py_var}.value)"
            break  # Only process the first AFTER or BEFORE found

    write_data = f"str({from_expr})" if from_expr else f"str(self.data.{py_record}.value)"
    return [f"self.{file_hint}.write({advancing_prefix}{write_data}{advancing_suffix})"]


def translate_close(ops: list[str]) -> list[str]:
    """Translate CLOSE verb."""
    return [f"self.{_to_python_name(op)}.close()" for op in ops if op.upper() not in _CLOSE_KEYWORDS]


def _translate_read_body_verb(tokens: list[str]) -> list[str] | None:
    """Translate a simple verb inside an AT END / NOT AT END clause.

    Returns translated Python lines, or None if the verb is too complex
    for inline translation.
    """
    # Import here to avoid circular dependency (translate_move lives in
    # statement_translators which re-exports from this module).
    from .statement_translators import translate_move

    if not tokens:
        return None
    verb = tokens[0].upper()
    rest = tokens[1:]

    if verb == "DISPLAY":
        parts = [_resolve_operand(t) for t in rest]
        if parts:
            return [f"print({', '.join(parts)}, sep='')"]
        return ["print()"]
    if verb == "MOVE":
        lines = translate_move(rest)
        return lines if lines else None
    if verb == "SET":
        upper_rest = _upper_ops(rest)
        if "TO" in upper_rest:
            to_idx = upper_rest.index("TO")
            targets = rest[:to_idx]
            value = rest[to_idx + 1] if to_idx + 1 < len(rest) else None
            if targets and value:
                results: list[str] = []
                for t in targets:
                    results.append(f"{_resolve_target(t)}.set({_resolve_operand(value)})")
                return results
        return None
    if verb == "STOP" and rest and rest[0].upper() == "RUN":
        return ["return"]
    if verb == "PERFORM":
        if rest:
            return [f"self.{_to_method_name(rest[0])}()"]
        return None
    return None


def _split_at_end_body(tokens: list[str]) -> list[list[str]]:
    """Split AT END body tokens into individual verb statements.

    Recognizes verb boundaries by looking for known COBOL verbs.
    Returns a list of token-lists, one per verb.
    """
    _BODY_VERBS = frozenset({
        "DISPLAY", "MOVE", "SET", "STOP", "PERFORM", "ADD", "SUBTRACT",
        "COMPUTE", "GO", "STRING", "UNSTRING", "CALL", "EVALUATE",
        "IF", "CLOSE", "OPEN", "WRITE", "READ", "INITIALIZE",
    })
    stmts: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok.upper() in _BODY_VERBS and current:
            stmts.append(current)
            current = [tok]
        else:
            current.append(tok)
    if current:
        stmts.append(current)
    return stmts


def translate_read(ops: list[str], raw: str) -> list[str]:
    """Translate READ verb.

    Handles:
    - READ file-name
    - READ file-name INTO data-name
    - READ file-name KEY IS field-name
    - READ file-name AT END body
    - READ file-name NOT AT END body
    - Combinations of the above
    """
    if not ops:
        return [f"# READ: could not parse: {raw}"]

    file_name = _to_python_name(ops[0])
    upper_ops = _upper_ops(ops)

    # -- Extract INTO target --
    into_target: str | None = None
    if "INTO" in upper_ops:
        into_idx = upper_ops.index("INTO")
        if into_idx + 1 < len(ops):
            into_target = ops[into_idx + 1]

    # -- Extract KEY IS field --
    key_field: str | None = None
    if "KEY" in upper_ops:
        key_idx = upper_ops.index("KEY")
        # KEY IS field-name  or  KEY field-name
        offset = key_idx + 1
        if offset < len(upper_ops) and upper_ops[offset] == "IS":
            offset += 1
        if offset < len(ops):
            key_field = ops[offset]

    # -- Locate AT END and NOT AT END boundaries --
    at_end_tokens: list[str] = []
    not_at_end_tokens: list[str] = []

    # Find all positions where "AT" + "END" appear as consecutive tokens
    # Also find "NOT" + "AT" + "END" sequences
    not_at_end_start: int | None = None
    at_end_start: int | None = None

    i = 0
    while i < len(upper_ops):
        if (upper_ops[i] == "NOT"
                and i + 2 < len(upper_ops)
                and upper_ops[i + 1] == "AT"
                and upper_ops[i + 2] == "END"):
            not_at_end_start = i + 3
            i += 3
        elif (upper_ops[i] == "AT"
                and i + 1 < len(upper_ops)
                and upper_ops[i + 1] == "END"):
            at_end_start = i + 2
            i += 2
        else:
            i += 1

    # Collect body tokens for each clause
    if at_end_start is not None and not_at_end_start is not None:
        if at_end_start < not_at_end_start:
            # AT END ... NOT AT END ...
            # AT END body is from at_end_start to (not_at_end_start - 3)
            not_prefix = not_at_end_start - 3
            at_end_tokens = ops[at_end_start:not_prefix]
            not_at_end_tokens = ops[not_at_end_start:]
        else:
            # NOT AT END ... AT END ...
            at_prefix = at_end_start - 2
            not_at_end_tokens = ops[not_at_end_start:at_prefix]
            at_end_tokens = ops[at_end_start:]
    elif at_end_start is not None:
        at_end_tokens = ops[at_end_start:]
    elif not_at_end_start is not None:
        not_at_end_tokens = ops[not_at_end_start:]

    # Strip trailing END-READ from body tokens
    for token_list in (at_end_tokens, not_at_end_tokens):
        while token_list and token_list[-1].upper() == "END-READ":
            token_list.pop()

    # -- Build the read call --
    key_comment = f"  # KEY IS {key_field}" if key_field else ""
    lines: list[str] = [f"_record = self.{file_name}.read(){key_comment}"]

    has_at_end = bool(at_end_tokens)
    has_not_at_end = bool(not_at_end_tokens) or into_target is not None

    if has_at_end or has_not_at_end:
        # -- AT END branch (record is None) --
        lines.append("if _record is None:")
        if has_at_end:
            at_end_stmts = _split_at_end_body(at_end_tokens)
            at_end_lines: list[str] = []
            for stmt_tokens in at_end_stmts:
                translated = _translate_read_body_verb(stmt_tokens)
                if translated is not None:
                    at_end_lines.extend(translated)
                else:
                    at_end_lines.append(
                        f"pass  # TODO(high): AT END body — {' '.join(stmt_tokens)}"
                    )
            for line in at_end_lines:
                lines.append(f"    {line}")
        else:
            lines.append("    pass")

        # -- NOT AT END branch (else) --
        lines.append("else:")
        not_at_end_lines: list[str] = []
        if into_target is not None:
            py_target = _to_python_name(into_target)
            not_at_end_lines.append(f"self.data.{py_target}.set(_record)")
        if not_at_end_tokens:
            not_stmts = _split_at_end_body(not_at_end_tokens)
            for stmt_tokens in not_stmts:
                translated = _translate_read_body_verb(stmt_tokens)
                if translated is not None:
                    not_at_end_lines.extend(translated)
                else:
                    not_at_end_lines.append(
                        f"pass  # TODO(high): NOT AT END body — {' '.join(stmt_tokens)}"
                    )
        if not_at_end_lines:
            for line in not_at_end_lines:
                lines.append(f"    {line}")
        else:
            lines.append("    pass")
    else:
        # No AT END clause — simple read with optional INTO
        lines.append("if _record is None:")
        lines.append("    pass  # end of file")
        if into_target is not None:
            py_target = _to_python_name(into_target)
            lines.append("else:")
            lines.append(f"    self.data.{py_target}.set(_record)")

    return lines


_DLI_CALL_TARGETS = frozenset({
    "CBLTDLI", "AIBTDLI", "PLITDLI", "AERTDLI",
})

_DLI_FUNC_CODES: dict[str, str] = {
    "GU": "get_unique", "GHU": "get_unique",
    "GN": "get_next", "GHN": "get_next",
    "GNP": "get_next", "GHNP": "get_next",
    "ISRT": "insert", "REPL": "replace", "DLET": "delete",
    "PCB": "pcb_call", "CHKP": "checkpoint", "XRST": "restart",
    "ROLB": "rollback", "ROLL": "rollback",
}


def translate_call(ops: list[str]) -> list[str]:
    """Translate CALL verb, with special handling for DLI CALL interface."""
    if not ops:
        return ["# CALL: no target specified"]

    target = ops[0].strip('"').strip("'")
    upper_target = target.upper()

    # DLI CALL interface: CALL 'CBLTDLI' USING func-code, pcb, io-area, ssa...
    if upper_target in _DLI_CALL_TARGETS:
        return _translate_dli_call(target, ops)

    py_target = _to_python_name(target)
    args = [_to_python_name(o) for o in ops[2:] if o.upper() != "USING"]
    arg_str = ", ".join(f"self.data.{a}.value" for a in args) if args else ""
    return [
        f"# CALL '{target}'",
        f"# TODO(high): implement or import {py_target}({arg_str})",
    ]


def _translate_dli_call(target: str, ops: list[str]) -> list[str]:
    """Translate CALL 'CBLTDLI'/'AIBTDLI' USING func, pcb, io-area, [ssa...]."""
    # Parse USING arguments
    using_args: list[str] = []
    upper_ops = [o.upper() for o in ops]
    if "USING" in upper_ops:
        idx = upper_ops.index("USING") + 1
        using_args = [o for o in ops[idx:] if o.upper() not in ("BY", "REFERENCE", "CONTENT", "VALUE")]

    lines = [f"# DLI CALL '{target}' — IMS database operation"]

    if not using_args:
        lines.append(f"self._dli_db.call('{target}')  # no arguments parsed")
        return lines

    func_code = using_args[0]
    py_func = _to_python_name(func_code)
    func_upper = func_code.strip("'\"").upper()

    # Map DLI function code to Python method
    method = _DLI_FUNC_CODES.get(func_upper, "call")
    hold = ", hold=True" if func_upper.startswith("GH") else ""
    parent = ", within_parent=True" if func_upper.endswith("P") and func_upper != "REPL" else ""

    pcb_arg = _to_python_name(using_args[1]) if len(using_args) > 1 else "pcb"
    io_area = _to_python_name(using_args[2]) if len(using_args) > 2 else "io_area"

    # SSA arguments (segment search arguments) — remaining args
    ssa_args = [_to_python_name(a) for a in using_args[3:]] if len(using_args) > 3 else []
    ssa_str = f", ssa=[{', '.join(f'self.data.{s}.value' for s in ssa_args)}]" if ssa_args else ""

    if method in ("get_unique", "get_next"):
        lines.append(f"_dli_row = self._dli_db.{method}(self.data.{pcb_arg}.value{hold}{parent}{ssa_str})")
        lines.append("if _dli_row is None:")
        lines.append('    self._dli_status = "GE"  # not found')
        lines.append("else:")
        lines.append(f"    self.data.{io_area}.set(_dli_row)")
        lines.append('    self._dli_status = "  "  # success')
    elif method == "insert":
        lines.append(f"self._dli_db.insert(self.data.{pcb_arg}.value, data=self.data.{io_area}.value{ssa_str})")
        lines.append('self._dli_status = "  "')
    elif method == "replace":
        lines.append(f"self._dli_db.replace(self.data.{pcb_arg}.value, data=self.data.{io_area}.value)")
        lines.append('self._dli_status = "  "')
    elif method == "delete":
        lines.append(f"self._dli_db.delete(self.data.{pcb_arg}.value)")
        lines.append('self._dli_status = "  "')
    elif method == "checkpoint":
        lines.append(f"self._dli_db.checkpoint(self.data.{pcb_arg}.value)")
    elif method == "rollback":
        lines.append(f"self._dli_db.rollback()")
    else:
        lines.append(f"self._dli_db.call(self.data.{py_func}.value, self.data.{pcb_arg}.value)")

    return lines


def translate_initialize(ops: list[str]) -> list[str]:
    """Translate INITIALIZE verb, including REPLACING clause."""
    if not ops:
        return ["# INITIALIZE: no operands"]
    upper_ops = _upper_ops(ops)

    # Split targets from REPLACING clause
    replacing_idx = None
    if "REPLACING" in upper_ops:
        replacing_idx = upper_ops.index("REPLACING")

    targets = ops[:replacing_idx] if replacing_idx is not None else ops
    results: list[str] = []

    if replacing_idx is not None:
        # Parse REPLACING clause: REPLACING NUMERIC BY value ALPHANUMERIC BY value ...
        replacing_parts = ops[replacing_idx + 1:]
        upper_replacing = _upper_ops(replacing_parts)
        numeric_val = None
        alpha_val = None
        i = 0
        while i < len(upper_replacing):
            category = upper_replacing[i]
            if i + 2 < len(upper_replacing) and upper_replacing[i + 1] == "BY":
                val = replacing_parts[i + 2]
                upper_val = val.upper()
                if category == "NUMERIC":
                    if upper_val in ("ZERO", "ZEROS", "ZEROES"):
                        numeric_val = "0"
                    else:
                        numeric_val = val
                elif category in ("ALPHANUMERIC", "ALPHABETIC"):
                    if upper_val in ("SPACE", "SPACES"):
                        alpha_val = "' '"
                    elif val.startswith('"') or val.startswith("'"):
                        alpha_val = val
                    else:
                        alpha_val = f"'{val}'"
                i += 3
            else:
                i += 1

        for op in targets:
            py_name = _to_python_name(op)
            results.append(f"# INITIALIZE {op} REPLACING ...")
            if numeric_val is not None:
                results.append(f"self.data.{py_name}.set({numeric_val})  # numeric fields")
            if alpha_val is not None:
                results.append(f"self.data.{py_name}.set({alpha_val})  # alphanumeric fields")
            if numeric_val is None and alpha_val is None:
                results.append(f"# self.data.{py_name}.set(0)  # or '' for alphanumeric")
    else:
        for op in targets:
            py_name = _to_python_name(op)
            results.append(f"# INITIALIZE {op}")
            results.append(f"# self.data.{py_name}.set(0)  # or '' for alphanumeric")
    return results
