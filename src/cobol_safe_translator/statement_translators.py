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

# Re-export from function_translators (split for LOC compliance)
from .function_translators import translate_function_intrinsic  # noqa: F401


# Keywords that should be filtered from arithmetic operand/target lists
_ARITHMETIC_KEYWORDS = frozenset({
    "ROUNDED", "ON", "SIZE", "ERROR", "NOT",
})

# Keywords that should be filtered from CLOSE operand lists
_CLOSE_KEYWORDS = frozenset({"WITH", "LOCK", "NO", "REWIND"})

# Valid operators inside COMPUTE expressions
_COMPUTE_OPERATORS = frozenset({"+", "-", "*", "/", "(", ")", "**"})

# COBOL bitwise operators → Python equivalents
_BITWISE_OPS: dict[str, str] = {
    "B-AND": "&", "B-OR": "|", "B-XOR": "^", "B-NOT": "~",
    "B-SHIFT-L": "<<", "B-SHIFT-R": ">>",
}


def translate_display(
    stmt: CobolStatement,
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate DISPLAY verb."""
    parts: list[str] = []
    no_advancing = False
    operands = list(stmt.operands)
    for i, op in enumerate(operands):
        if op.upper() == "UPON":
            operands = operands[:i]
            break
        if op.upper() == "WITH":
            if i + 2 < len(operands) and operands[i + 1].upper() == "NO" and operands[i + 2].upper() == "ADVANCING":
                no_advancing = True
            operands = operands[:i]  # WITH is always a clause marker, never a data name
            break
    for op in operands:
        parts.append(resolve(op))
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
    elif source.upper().startswith("FUNCTION"):
        return ["# TODO(high): MOVE FUNCTION — manual translation required"]
    else:
        fig = FIGURATIVE_RESOLVE.get(source.upper())
        src_expr = fig if fig is not None else _resolve_operand(source)

    results: list[str] = []
    for t in targets:
        results.append(f"{_resolve_target(t)}.set({src_expr})")
    return results


def translate_add(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate ADD verb."""
    if not ops:
        return ["# ADD: no operands"]
    upper_ops = _upper_ops(ops)
    if "GIVING" in upper_ops:
        giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
        giving_targets = ops[giving_idx + 1:]
        if not giving_targets:
            return [f"# ADD GIVING: missing target operand: {' '.join(ops)}"]
        pre_giving = ops[:giving_idx]
        if "TO" in _upper_ops(pre_giving):
            to_idx = next(i for i, o in enumerate(pre_giving) if o.upper() == "TO")
            all_sources = pre_giving[:to_idx] + pre_giving[to_idx + 1:]
        else:
            all_sources = pre_giving
        exprs = [resolve(s) for s in all_sources]
        sum_expr = " + ".join(exprs) if exprs else "0"
        results: list[str] = []
        for t in giving_targets:
            if t.upper() in _ARITHMETIC_KEYWORDS:
                break
            results.append(f"{_resolve_target(t)}.set({sum_expr})")
        if not results:
            return [f"# ADD GIVING: no valid target found: {' '.join(ops)}"]
        return results
    if "TO" in upper_ops:
        to_idx = next(i for i, o in enumerate(upper_ops) if o == "TO")
        sources = ops[:to_idx]
        targets = [t for t in ops[to_idx + 1:] if t.upper() not in _ARITHMETIC_KEYWORDS]
        if not sources or not targets:
            return [f"# ADD: missing operand(s): {' '.join(ops)}"]
        results = []
        for src in sources:
            src_expr = resolve(src)
            for t in targets:
                results.append(f"{_resolve_target(t)}.add({src_expr})")
        return results
    return [f"# ADD: could not parse operands: {' '.join(ops)}"]


def translate_subtract(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate SUBTRACT verb."""
    if not ops:
        return ["# SUBTRACT: no operands"]
    upper_ops = _upper_ops(ops)
    if "GIVING" in upper_ops:
        giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
        giving_targets = ops[giving_idx + 1:]
        if not giving_targets:
            return [f"# SUBTRACT GIVING: missing target operand: {' '.join(ops)}"]
        pre_giving = ops[:giving_idx]
        if "FROM" in _upper_ops(pre_giving):
            from_idx = next(i for i, o in enumerate(pre_giving) if o.upper() == "FROM")
            sources = pre_giving[:from_idx]
            base = pre_giving[from_idx + 1] if from_idx + 1 < len(pre_giving) else "0"
            base_expr = resolve(base)
            sub_exprs = [resolve(s) for s in sources]
            expr = base_expr + "".join(f" - {e}" for e in sub_exprs)
        else:
            expr = " - ".join(resolve(s) for s in pre_giving) or "0"
        results: list[str] = []
        for t in giving_targets:
            if t.upper() in _ARITHMETIC_KEYWORDS:
                break
            results.append(f"{_resolve_target(t)}.set({expr})")
        if not results:
            return [f"# SUBTRACT GIVING: no valid target found: {' '.join(ops)}"]
        return results
    if "FROM" in upper_ops:
        from_idx = next(i for i, o in enumerate(upper_ops) if o == "FROM")
        sources = ops[:from_idx]
        targets = [t for t in ops[from_idx + 1:] if t.upper() not in _ARITHMETIC_KEYWORDS]
        if not sources or not targets:
            return [f"# SUBTRACT: missing operand(s): {' '.join(ops)}"]
        results = []
        for src in sources:
            src_expr = resolve(src)
            for t in targets:
                results.append(f"{_resolve_target(t)}.subtract({src_expr})")
        return results
    return [f"# SUBTRACT: could not parse operands: {' '.join(ops)}"]


def translate_multiply(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate MULTIPLY verb."""
    upper_ops = _upper_ops(ops)
    if "BY" in upper_ops:
        by_idx = next(i for i, o in enumerate(upper_ops) if o == "BY")
        if by_idx == 0:
            return [f"# MULTIPLY: missing source operand: {' '.join(ops)}"]
        source = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            multiplicand = resolve(ops[by_idx + 1]) if (by_idx + 1 < len(ops) and by_idx + 1 < giving_idx) else "1"
            results: list[str] = []
            for t in ops[giving_idx + 1:]:
                if t.upper() in _ARITHMETIC_KEYWORDS:
                    break
                results.append(f"{_resolve_target(t)}.set({source} * {multiplicand})")
            if not results:
                return [f"# MULTIPLY GIVING: no valid target found: {' '.join(ops)}"]
            return results
        raw_targets = ops[by_idx + 1:]
        targets = [t for t in raw_targets if t.upper() not in _ARITHMETIC_KEYWORDS]
        if not targets:
            return [f"# MULTIPLY: missing target operand: {' '.join(ops)}"]
        results = []
        for t in targets:
            results.append(f"{_resolve_target(t)}.multiply({source})")
        return results
    return [f"# MULTIPLY: could not parse operands: {' '.join(ops)}"]


def _divide_giving_results(
    ops: list[str], giving_idx: int, dividend: str, divisor: str,
) -> list[str]:
    """Parse GIVING targets and optional REMAINDER, returning translated lines."""
    giving_targets: list[str] = []
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
        giving_targets.append(ops[i])
        i += 1
    results = ["# TODO: verify divisor is non-zero before division (COBOL EC-SIZE-ZERO-DIVIDE)"]
    for t in giving_targets:
        results.append(f"{_resolve_target(t)}.set({dividend} / {divisor})")
    if has_remainder and remainder_target:
        results.append(f"{_resolve_target(remainder_target)}.set(int({dividend}) % int({divisor}))")
    return results


def translate_divide(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate DIVIDE verb."""
    upper_ops = _upper_ops(ops)
    if "INTO" in upper_ops:
        into_idx = next(i for i, o in enumerate(upper_ops) if o == "INTO")
        if into_idx == 0:
            return [f"# DIVIDE: missing divisor operand: {' '.join(ops)}"]
        divisor = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            dividend = resolve(ops[into_idx + 1]) if into_idx + 1 < len(ops) and into_idx + 1 < giving_idx else "0"
            return _divide_giving_results(ops, giving_idx, dividend, divisor)
        raw_targets = ops[into_idx + 1:]
        targets = [t for t in raw_targets if t.upper() not in _ARITHMETIC_KEYWORDS]
        if not targets:
            return [f"# DIVIDE: missing target operand: {' '.join(ops)}"]
        results: list[str] = []
        for t in targets:
            results.append(f"{_resolve_target(t)}.divide({divisor})")
        return results
    if "BY" in upper_ops:
        by_idx = next(i for i, o in enumerate(upper_ops) if o == "BY")
        if by_idx == 0:
            return [f"# DIVIDE: missing dividend operand: {' '.join(ops)}"]
        dividend = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            divisor = resolve(ops[by_idx + 1]) if by_idx + 1 < len(ops) and by_idx + 1 < giving_idx else "1"
            return _divide_giving_results(ops, giving_idx, dividend, divisor)
        if by_idx + 1 >= len(ops):
            return [f"# DIVIDE BY: missing divisor: {' '.join(ops)}"]
        divisor = resolve(ops[by_idx + 1])
        return [f"# TODO(high): DIVIDE BY without GIVING — manual translation required",
                f"# {dividend} / {divisor}"]
    return [f"# DIVIDE: could not parse operands: {' '.join(ops)}"]


def _merge_spaced_subscripts(tokens: list[str]) -> list[str]:
    """Merge space-separated subscripts into their parent identifiers.

    In COBOL, ``TABLE (1 2)`` is equivalent to ``TABLE(1 2)``.
    The tokenizer may split these when a space precedes the paren.
    This function re-attaches ``(`` ... ``)`` groups to the preceding
    identifier so that resolve_operand can handle them properly.

    Only merges when the token before ``(`` looks like a COBOL
    identifier (contains a letter) and is NOT an arithmetic operator
    or keyword.
    """
    result: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Check if this is a standalone "(" preceded by an identifier
        if (tok == "(" and result
                and result[-1] not in _COMPUTE_OPERATORS
                and result[-1].upper() not in _BITWISE_OPS
                and result[-1].upper() not in ("=", "ROUNDED", "FUNCTION",
                                                "LENGTH", "OF", "IN",
                                                "NOT", "AND", "OR")
                and any(c.isalpha() for c in result[-1])):
            # Collect tokens until closing ")"
            depth = 1
            inner_tokens: list[str] = []
            j = i + 1
            while j < len(tokens) and depth > 0:
                if tokens[j] == "(":
                    depth += 1
                elif tokens[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                if tokens[j] != ",":  # skip standalone commas
                    inner_tokens.append(tokens[j])
                j += 1
            # Merge: attach (inner) to the identifier
            inner = " ".join(inner_tokens)
            result[-1] = f"{result[-1]}({inner})"
            i = j + 1  # skip past closing ")"
        else:
            result.append(tok)
            i += 1
    return result


def translate_compute(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate COMPUTE verb."""
    if "=" in ops:
        # Pre-process: merge space-separated subscripts into identifiers
        # e.g., TABLE ( 1 2 ) → TABLE(1 2)
        ops = _merge_spaced_subscripts(ops)
        eq_idx = ops.index("=")
        targets = [t for t in ops[:eq_idx] if t.upper() != "ROUNDED"]
        expr_parts = ops[eq_idx + 1:]

        # Detect LENGTH OF pattern — translate to len()
        resolved: list[str] = []
        i = 0
        while i < len(expr_parts):
            part = expr_parts[i]
            upper_part = part.upper()
            # Free-format compiler directives (>>ELSE, >>END-IF) — stop here
            if part.startswith(">>"):
                break
            # COPY statement leaked into COMPUTE — stop here
            if upper_part == "COPY":
                break
            # FUNCTION intrinsic — translate known functions inline
            if upper_part == "FUNCTION" and i + 1 < len(expr_parts):
                func_token = expr_parts[i + 1]
                # Split function name from parenthesized arguments
                paren_pos = func_token.find("(")
                consumed = 2  # FUNCTION + func_name/func_name(args)
                if paren_pos >= 0:
                    func_name = func_token[:paren_pos]
                    raw_inner = func_token[paren_pos + 1:]
                    if raw_inner.endswith(")"):
                        raw_inner = raw_inner[:-1]
                    raw_args = raw_inner.strip()
                else:
                    func_name = func_token
                    raw_args = ""
                    # Check for space-separated parens: FUNCTION LENGTH ( args )
                    if i + 2 < len(expr_parts) and expr_parts[i + 2] == "(":
                        # Collect tokens until closing )
                        arg_tokens: list[str] = []
                        j = i + 3
                        depth = 1
                        while j < len(expr_parts) and depth > 0:
                            if expr_parts[j] == "(":
                                depth += 1
                            elif expr_parts[j] == ")":
                                depth -= 1
                                if depth == 0:
                                    break
                            arg_tokens.append(expr_parts[j])
                            j += 1
                        raw_args = " ".join(arg_tokens)
                        consumed = j + 1 - i  # skip past closing )
                translated = translate_function_intrinsic(func_name, raw_args, resolve)
                if translated is not None:
                    resolved.append(translated)
                else:
                    # Use bare 0 — no inline comment (would break expressions)
                    resolved.append("0")
                i += consumed
            elif upper_part == "LENGTH" and i + 2 < len(expr_parts) and expr_parts[i + 1].upper() == "OF":
                field = expr_parts[i + 2]
                resolved.append(f"len(str({resolve(field)}))")
                i += 3
            elif upper_part in ('OF', 'IN') and i + 1 < len(expr_parts):
                # Qualification: skip OF/IN and the group name
                i += 2
            elif part in _COMPUTE_OPERATORS:
                resolved.append(part)
                i += 1
            elif upper_part in _BITWISE_OPS:
                resolved.append(_BITWISE_OPS[upper_part])
                i += 1
            else:
                resolved.append(resolve(part))
                i += 1
        # Strip trailing operator (from multi-line COMPUTE split at line boundary)
        while resolved and resolved[-1] in ('+', '-', '*', '/', '&', '|', '^', '<<', '>>'):
            resolved.pop()
        expr = " ".join(resolved)
        if not expr:
            return [
                f"# COMPUTE: {' '.join(ops)}",
                f"# TODO(high): COMPUTE has no right-hand side — manual translation required",
            ]
        results = [f"# COMPUTE: {' '.join(ops)}"]
        for t in targets:
            results.append(
                f"{_resolve_target(t)}.set({expr})  # TODO(high): verify expression translation"
            )
        return results
    return [f"# COMPUTE: could not parse operands: {' '.join(ops)}"]


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
        until_idx = next(i for i, o in enumerate(ops) if o.upper() == "UNTIL")
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
        times_idx = next(i for i, o in enumerate(ops) if o.upper() == "TIMES")
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

    # Determine file name from record name (convention: remove -RECORD/-REC suffix)
    file_hint = py_record.replace("_record", "").replace("_rec", "")
    if not file_hint or file_hint == py_record:
        file_hint = py_record + "_file"

    # Check for FROM clause: WRITE record FROM data-name
    from_expr = None
    if "FROM" in upper_ops:
        from_idx = upper_ops.index("FROM")
        if from_idx + 1 < len(ops):
            from_expr = f"self.data.{_to_python_name(ops[from_idx + 1])}.value"

    if from_expr:
        return [f"self.{file_hint}.write(str({from_expr}))"]
    return [f"self.{file_hint}.write(str(self.data.{py_record}.value))"]


def translate_close(ops: list[str]) -> list[str]:
    """Translate CLOSE verb."""
    return [f"self.{_to_python_name(op)}.close()" for op in ops if op.upper() not in _CLOSE_KEYWORDS]


def translate_read(ops: list[str], raw: str) -> list[str]:
    """Translate READ verb."""
    if ops:
        file_name = _to_python_name(ops[0])
        upper_ops = _upper_ops(ops)
        at_end_action = ""
        if "AT" in upper_ops and "END" in upper_ops:
            end_idx = upper_ops.index("END")
            at_end_parts = ops[end_idx + 1:]
            if at_end_parts:
                at_end_action = f"  # AT END action: {' '.join(at_end_parts)}"
        return [
            f"_record = self.{file_name}.read()",
            f"if _record is None:",
            f"    pass  # TODO(high): AT END — implement EOF handling{at_end_action}",
        ]
    return [f"# READ: could not parse: {raw}"]


def translate_call(ops: list[str]) -> list[str]:
    """Translate CALL verb."""
    if ops:
        target = ops[0].strip('"').strip("'")
        py_target = _to_python_name(target)
        args = [_to_python_name(o) for o in ops[2:] if o.upper() != "USING"]
        arg_str = ", ".join(f"self.data.{a}.value" for a in args) if args else ""
        return [
            f"# CALL '{target}'",
            f"# TODO(high): implement or import {py_target}({arg_str})",
        ]
    return ["# CALL: no target specified"]


def translate_initialize(ops: list[str]) -> list[str]:
    """Translate INITIALIZE verb."""
    results: list[str] = []
    for op in ops:
        py_name = _to_python_name(op)
        results.append(f"# INITIALIZE {op}")
        results.append(f"# self.data.{py_name}.set(0)  # or '' for alphanumeric")
    return results
