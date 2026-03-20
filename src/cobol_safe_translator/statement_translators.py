"""Individual COBOL verb translators for the Python mapper.

Extracted from mapper.py to comply with the 500 LOC per file guideline.
Each function translates a specific COBOL verb into Python code line(s).

All translator functions follow this signature:
    def translate_VERB(ops: list[str], resolve: Callable, ...) -> list[str]

where `resolve` is the operand resolver callback (PythonMapper._resolve_operand)
and the return value is a list of Python source lines.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import CobolStatement
from .utils import FIGURATIVE_RESOLVE, _is_numeric_literal, _sanitize_numeric, _to_method_name, _to_python_name, _upper_ops, resolve_operand as _resolve_operand, resolve_target as _resolve_target

# Re-export from io_translators (split for LOC compliance)
from .io_translators import translate_accept, translate_rewrite, wrap_on_size_error  # noqa: F401

# Re-export from arithmetic_translators (split for LOC compliance)
from .arithmetic_translators import translate_add, translate_subtract, translate_multiply, translate_divide, translate_compute, _merge_spaced_subscripts  # noqa: F401

# Re-export from file_translators (split for LOC compliance)
from .file_translators import translate_open, translate_write, translate_close, translate_read, translate_call, translate_initialize  # noqa: F401

from .function_translators import translate_function_intrinsic


def translate_display(
    stmt: CobolStatement,
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate DISPLAY verb."""
    parts: list[str] = []
    no_advancing = False
    operands = stmt.operands
    for i, op in enumerate(operands):
        if op.upper() == "UPON":
            operands = operands[:i]
            break
        if op.upper() == "WITH":
            if i + 2 < len(operands) and operands[i + 1].upper() == "NO" and operands[i + 2].upper() == "ADVANCING":
                no_advancing = True
            operands = operands[:i]  # WITH is always a clause marker, never a data name
            break
    parts = [resolve(op) for op in operands]
    end_kwarg = ", end=''" if no_advancing else ""
    if parts:
        return [f"print({', '.join(parts)}, sep=''{end_kwarg})"]
    return [f"print({end_kwarg.lstrip(', ')})"] if no_advancing else ["print()"]


def translate_move(ops: list[str]) -> list[str]:
    """Translate MOVE verb."""
    if ops and ops[0].upper() == "ALL":
        # MOVE ALL "X" TO WS-FIELD — fill field with repeated character
        if len(ops) >= 4 and ops[2].upper() == "TO":
            fill_char = ops[1].strip('"').strip("'")
            targets = ops[3:]
            results: list[str] = []
            for t in targets:
                py = _to_python_name(t)
                results.append(
                    f"self.data.{py}.set({fill_char!r} * self.data.{py}.size "
                    f"if hasattr(self.data.{py}, 'size') else {fill_char!r})"
                )
            return results
        return [f"# MOVE ALL: could not parse: {' '.join(ops)}"]
    upper_ops = _upper_ops(ops)
    if "TO" not in upper_ops:
        return [f"# MOVE: could not parse operands: {' '.join(ops)}"]
    to_idx = upper_ops.index("TO")
    source = ops[0]
    targets = ops[to_idx + 1:]
    if not targets:
        return [f"# MOVE: missing target operand: {' '.join(ops)}"]

    if source.startswith('"') or source.startswith("'"):
        # Escape backslashes for Python (COBOL has no escape sequences)
        inner = source[1:-1].replace('\\', '\\\\') if '\\' in source else source[1:-1]
        src_expr = f'{source[0]}{inner}{source[0]}'
    elif _is_numeric_literal(source):
        src_expr = _sanitize_numeric(source)
    elif source.upper() == "FUNCTION":
        # MOVE FUNCTION name[(args)] TO target
        # Parser tokenizes as ops: [FUNCTION, name, ..., TO, target]
        if to_idx >= 2:
            func_token = ops[1]
            paren_pos = func_token.find("(")
            if paren_pos >= 0:
                func_name = func_token[:paren_pos]
                raw_inner = func_token[paren_pos + 1:]
                if raw_inner.endswith(")"):
                    raw_inner = raw_inner[:-1]
                extra_args = ops[2:to_idx]
                if extra_args:
                    raw_args = (raw_inner + " " + " ".join(extra_args)).strip().rstrip(")")
                else:
                    raw_args = raw_inner.strip()
            else:
                func_name = func_token
                arg_tokens = ops[2:to_idx]
                raw_args_str = " ".join(arg_tokens)
                if raw_args_str.startswith("(") and raw_args_str.endswith(")"):
                    raw_args = raw_args_str[1:-1].strip()
                elif raw_args_str.startswith("("):
                    raw_args = raw_args_str[1:].rstrip(")").strip()
                else:
                    raw_args = raw_args_str
            translated = translate_function_intrinsic(func_name, raw_args, _resolve_operand)
            if translated is not None:
                src_expr = translated
            else:
                return [f"# TODO(high): MOVE FUNCTION {func_name} — unknown intrinsic, manual translation required"]
        else:
            return ["# TODO(high): MOVE FUNCTION — could not parse function name"]
    else:
        fig = FIGURATIVE_RESOLVE.get(source.upper())
        src_expr = fig if fig is not None else _resolve_operand(source)

    return [f"{_resolve_target(t)}.set({src_expr})" for t in targets]


def _parse_varying_clause(
    ops: list[str],
    start_idx: int,
) -> tuple[str, str, str, list[str], int] | None:
    """Parse a single VARYING/AFTER clause starting at *start_idx*.

    Expected token sequence (starting after VARYING or AFTER [VARYING]):
        variable FROM start BY step UNTIL cond-tokens...

    The condition tokens extend until the next AFTER keyword or end of *ops*.

    Returns (variable, from_val, by_val, cond_parts, end_idx) or None on
    parse failure.  *end_idx* is the index of the first token after this
    clause (the next AFTER, or len(ops)).
    """
    upper_ops = _upper_ops(ops)
    n = len(ops)

    # Skip optional VARYING after AFTER
    idx = start_idx
    if idx < n and upper_ops[idx] == "VARYING":
        idx += 1

    # variable
    if idx >= n:
        return None
    variable = ops[idx]
    idx += 1

    # FROM
    if idx >= n or upper_ops[idx] != "FROM":
        return None
    idx += 1
    if idx >= n:
        return None
    from_val = ops[idx]
    idx += 1

    # BY
    if idx >= n or upper_ops[idx] != "BY":
        return None
    idx += 1
    if idx >= n:
        return None
    by_val = ops[idx]
    idx += 1

    # UNTIL
    if idx >= n or upper_ops[idx] != "UNTIL":
        return None
    idx += 1

    # Condition tokens: everything until next AFTER or end
    cond_parts: list[str] = []
    while idx < n and upper_ops[idx] != "AFTER":
        cond_parts.append(ops[idx])
        idx += 1

    if not cond_parts:
        return None

    return (variable, from_val, by_val, cond_parts, idx)


def _translate_perform_varying(
    ops: list[str],
    raw: str,
    translate_condition: Callable[[str], str],
) -> list[str]:
    """Translate PERFORM [para] VARYING var FROM start BY step UNTIL cond.

    Supports single-variable and multi-VARYING (AFTER) nested loops.
    """
    upper_ops = _upper_ops(ops)

    # Locate the first VARYING keyword
    try:
        varying_idx = upper_ops.index("VARYING")
    except ValueError:
        return [
            f"# PERFORM VARYING: {raw}",
            f"# TODO(high): PERFORM VARYING requires manual translation (FROM/BY/UNTIL clauses)",
        ]

    # Inline (VARYING at position 0) vs paragraph call
    is_inline = (varying_idx == 0)
    if is_inline:
        para_call = None
    else:
        para_call = f"self.{_to_method_name(ops[0])}()"

    # ---- Parse all VARYING / AFTER clauses ----
    clauses: list[tuple[str, str, str, list[str]]] = []

    # First clause starts at the VARYING keyword
    parsed = _parse_varying_clause(ops, varying_idx)
    if parsed is None:
        return [
            f"# PERFORM VARYING: {raw}",
            f"# TODO(high): PERFORM VARYING requires manual translation (FROM/BY/UNTIL clauses)",
        ]
    variable, from_val, by_val, cond_parts, next_idx = parsed
    clauses.append((variable, from_val, by_val, cond_parts))

    # Subsequent AFTER clauses
    while next_idx < len(ops) and upper_ops[next_idx] == "AFTER":
        parsed = _parse_varying_clause(ops, next_idx + 1)
        if parsed is None:
            return [
                f"# PERFORM VARYING: {raw}",
                f"# TODO(high): PERFORM VARYING AFTER requires manual translation",
            ]
        variable, from_val, by_val, cond_parts, next_idx = parsed
        clauses.append((variable, from_val, by_val, cond_parts))

    # ---- Validate: reject zero step in any clause ----
    for variable, from_val, by_val, cond_parts in clauses:
        if _is_numeric_literal(by_val) and float(by_val) == 0:
            return [
                f"# PERFORM VARYING: {raw}",
                f"# TODO(high): PERFORM VARYING with zero step would generate infinite loop — manual translation required",
            ]

    # ---- Generate nested loop code ----
    lines: list[str] = [f"# {raw}"]
    depth = len(clauses)

    # Emit initialisation + while-not for each level
    for level, (variable, from_val, by_val, cond_parts) in enumerate(clauses):
        indent = "    " * level
        py_var = _to_python_name(variable)
        start_expr = from_val if _is_numeric_literal(from_val) else f"self.data.{_to_python_name(from_val)}.value"
        cond = " ".join(cond_parts)
        translated_cond = translate_condition(cond)

        lines.append(f"{indent}self.data.{py_var}.set({start_expr})")
        lines.append(f"{indent}while not ({translated_cond}):")

    # Emit the body (paragraph call or inline TODO) at innermost depth
    inner_indent = "    " * depth
    if para_call:
        lines.append(f"{inner_indent}{para_call}")
    else:
        lines.append(f"{inner_indent}pass  # TODO(high): inline PERFORM VARYING — statements should be moved here")

    # Emit step increments from innermost to outermost
    for level in range(depth - 1, -1, -1):
        variable, from_val, by_val, cond_parts = clauses[level]
        step_indent = "    " * (level + 1)
        py_var = _to_python_name(variable)
        step_expr = by_val if _is_numeric_literal(by_val) else f"self.data.{_to_python_name(by_val)}.value"
        lines.append(f"{step_indent}self.data.{py_var}.add({step_expr})")

    return lines


def translate_perform(
    ops: list[str],
    raw: str,
    translate_condition: Callable[[str], str],
    get_paragraph_range: Callable[[str, str], list[str]] | None = None,
) -> list[str]:
    """Translate PERFORM verb."""
    if not ops:
        return ["# PERFORM with no target"]

    target = _to_method_name(ops[0])
    upper_ops = _upper_ops(ops)

    if "THRU" in upper_ops or "THROUGH" in upper_ops:
        thru_idx = next(
            i for i, o in enumerate(upper_ops) if o in ("THRU", "THROUGH")
        )
        end_para = ops[thru_idx + 1] if thru_idx + 1 < len(ops) else None
        if end_para and get_paragraph_range:
            para_names = get_paragraph_range(ops[0], end_para)
            # Check for UNTIL after the THRU clause
            remaining_upper = _upper_ops(ops[thru_idx + 2:])
            if "UNTIL" in remaining_upper:
                until_offset = remaining_upper.index("UNTIL")
                cond_parts = ops[thru_idx + 2 + until_offset + 1:]
                if cond_parts:
                    cond = " ".join(cond_parts)
                    calls = [f"    self.{_to_method_name(p)}()" for p in para_names]
                    return [
                        f"# PERFORM {ops[0]} THRU {end_para} UNTIL {cond}",
                        f"while not ({translate_condition(cond)}):",
                    ] + calls
            calls = [f"self.{_to_method_name(p)}()" for p in para_names]
            return [f"# PERFORM {ops[0]} THRU {end_para}"] + calls
        return [
            f"# PERFORM THRU: {raw}",
            f"self.{target}()  # TODO(high): THRU endpoint not resolved",
        ]

    if "VARYING" in upper_ops:
        return _translate_perform_varying(ops, raw, translate_condition)

    if "UNTIL" in upper_ops:
        until_idx = upper_ops.index("UNTIL")
        cond_parts = ops[until_idx + 1:]
        if not cond_parts:
            return [f"# PERFORM UNTIL: missing condition — {' '.join(ops)}"]
        cond = " ".join(cond_parts)
        if until_idx == 0:
            return [
                f"# PERFORM UNTIL {cond} (inline — no paragraph)",
                f"while not ({translate_condition(cond)}):",
                f"    pass  # TODO(high): inline PERFORM UNTIL — statements should be moved here",
            ]
        return [
            f"# PERFORM {ops[0]} UNTIL {cond}",
            f"while not ({translate_condition(cond)}):",
            f"    self.{target}()",
        ]

    if "TIMES" in upper_ops:
        times_idx = upper_ops.index("TIMES")
        if times_idx >= 2:
            times_op = ops[times_idx - 1]
            is_inline = False
        elif times_idx == 1:
            times_op = ops[0]
            is_inline = True
        else:
            return [f"# PERFORM TIMES: invalid syntax — {' '.join(ops)}"]
        times_val = str(int(float(times_op))) if _is_numeric_literal(times_op) else f"int(self.data.{_to_python_name(times_op)}.value)"
        if is_inline:
            return [
                f"for _ in range({times_val}):",
                f"    pass  # TODO(high): inline PERFORM TIMES — statements should be moved here",
            ]
        return [
            f"for _ in range({times_val}):",
            f"    self.{_to_method_name(ops[0])}()",
        ]

    return [f"self.{target}()"]
