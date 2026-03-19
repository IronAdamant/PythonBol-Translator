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
from .utils import FIGURATIVE_RESOLVE, _file_hint_from_record, _is_numeric_literal, _sanitize_numeric, _to_method_name, _to_python_name, _upper_ops, extract_from_expr, resolve_operand as _resolve_operand, resolve_target as _resolve_target

# Re-export from io_translators (split for LOC compliance)
from .io_translators import translate_accept, translate_rewrite, wrap_on_size_error  # noqa: F401

from .function_translators import translate_function_intrinsic


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
    has_rounded = "ROUNDED" in upper_ops
    rounded_arg = ", rounded=True" if has_rounded else ""
    if "GIVING" in upper_ops:
        giving_idx = upper_ops.index("GIVING")
        giving_targets = ops[giving_idx + 1:]
        if not giving_targets:
            return [f"# ADD GIVING: missing target operand: {' '.join(ops)}"]
        pre_giving = ops[:giving_idx]
        upper_pre = _upper_ops(pre_giving)
        if "TO" in upper_pre:
            to_idx = upper_pre.index("TO")
            all_sources = pre_giving[:to_idx] + pre_giving[to_idx + 1:]
        else:
            all_sources = pre_giving
        exprs = [resolve(s) for s in all_sources]
        sum_expr = " + ".join(exprs) if exprs else "0"
        results: list[str] = []
        for t in giving_targets:
            if t.upper() in _ARITHMETIC_KEYWORDS:
                break
            results.append(f"{_resolve_target(t)}.set({sum_expr}{rounded_arg})")
        if not results:
            return [f"# ADD GIVING: no valid target found: {' '.join(ops)}"]
        return results
    if "TO" in upper_ops:
        to_idx = upper_ops.index("TO")
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
    has_rounded = "ROUNDED" in upper_ops
    rounded_arg = ", rounded=True" if has_rounded else ""
    if "GIVING" in upper_ops:
        giving_idx = upper_ops.index("GIVING")
        giving_targets = ops[giving_idx + 1:]
        if not giving_targets:
            return [f"# SUBTRACT GIVING: missing target operand: {' '.join(ops)}"]
        pre_giving = ops[:giving_idx]
        upper_pre = _upper_ops(pre_giving)
        if "FROM" in upper_pre:
            from_idx = upper_pre.index("FROM")
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
            results.append(f"{_resolve_target(t)}.set({expr}{rounded_arg})")
        if not results:
            return [f"# SUBTRACT GIVING: no valid target found: {' '.join(ops)}"]
        return results
    if "FROM" in upper_ops:
        from_idx = upper_ops.index("FROM")
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
    has_rounded = "ROUNDED" in upper_ops
    rounded_arg = ", rounded=True" if has_rounded else ""
    if "BY" in upper_ops:
        by_idx = upper_ops.index("BY")
        if by_idx == 0:
            return [f"# MULTIPLY: missing source operand: {' '.join(ops)}"]
        source = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = upper_ops.index("GIVING")
            multiplicand = resolve(ops[by_idx + 1]) if (by_idx + 1 < len(ops) and by_idx + 1 < giving_idx) else "1"
            results: list[str] = []
            for t in ops[giving_idx + 1:]:
                if t.upper() in _ARITHMETIC_KEYWORDS:
                    break
                results.append(f"{_resolve_target(t)}.set({source} * {multiplicand}{rounded_arg})")
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
    rounded_arg: str = "",
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
        results.append(f"{_resolve_target(t)}.set({dividend} / {divisor}{rounded_arg})")
    if has_remainder and remainder_target:
        results.append(f"{_resolve_target(remainder_target)}.set(int({dividend}) % int({divisor}))")
    return results


def translate_divide(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate DIVIDE verb."""
    upper_ops = _upper_ops(ops)
    has_rounded = "ROUNDED" in upper_ops
    rounded_arg = ", rounded=True" if has_rounded else ""
    if "INTO" in upper_ops:
        into_idx = upper_ops.index("INTO")
        if into_idx == 0:
            return [f"# DIVIDE: missing divisor operand: {' '.join(ops)}"]
        divisor = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = upper_ops.index("GIVING")
            dividend = resolve(ops[into_idx + 1]) if into_idx + 1 < len(ops) and into_idx + 1 < giving_idx else "0"
            return _divide_giving_results(ops, giving_idx, dividend, divisor, rounded_arg)
        raw_targets = ops[into_idx + 1:]
        targets = [t for t in raw_targets if t.upper() not in _ARITHMETIC_KEYWORDS]
        if not targets:
            return [f"# DIVIDE: missing target operand: {' '.join(ops)}"]
        results: list[str] = []
        for t in targets:
            results.append(f"{_resolve_target(t)}.divide({divisor})")
        return results
    if "BY" in upper_ops:
        by_idx = upper_ops.index("BY")
        if by_idx == 0:
            return [f"# DIVIDE: missing dividend operand: {' '.join(ops)}"]
        dividend = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = upper_ops.index("GIVING")
            divisor = resolve(ops[by_idx + 1]) if by_idx + 1 < len(ops) and by_idx + 1 < giving_idx else "1"
            return _divide_giving_results(ops, giving_idx, dividend, divisor, rounded_arg)
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
        # e.g., TABLE ( 1 2 ) -> TABLE(1 2)
        ops = _merge_spaced_subscripts(ops)
        eq_idx = ops.index("=")
        has_rounded = any(t.upper() == "ROUNDED" for t in ops[:eq_idx])
        rounded_arg = ", rounded=True" if has_rounded else ""
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
        # Validate expression syntax — emit TODO on parse failure
        try:
            compile(expr, '<compute>', 'eval')
        except SyntaxError:
            return [
                f"# COMPUTE: {' '.join(ops)}",
                f"# TODO(high): expression could not be translated — manual review required",
            ]
        results = [f"# COMPUTE: {' '.join(ops)}"]
        for t in targets:
            results.append(
                f"{_resolve_target(t)}.set({expr}{rounded_arg})  # TODO(high): verify expression translation"
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
