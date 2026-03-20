"""Arithmetic verb translators (ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE).

Split from statement_translators.py to comply with the 500 LOC guideline.
Each function translates a specific COBOL arithmetic verb into Python code.
"""

from __future__ import annotations

from collections.abc import Callable

from .function_translators import _resolve_expr_ext, translate_function_intrinsic
from .utils import _upper_ops, resolve_target as _resolve_target


# Keywords that should be filtered from arithmetic operand/target lists
_ARITHMETIC_KEYWORDS = frozenset({
    "ROUNDED", "ON", "SIZE", "ERROR", "NOT",
})

# Valid operators inside COMPUTE expressions
_COMPUTE_OPERATORS = frozenset({"+", "-", "*", "/", "(", ")", "**"})

# COBOL bitwise operators → Python equivalents
_BITWISE_OPS: dict[str, str] = {
    "B-AND": "&", "B-OR": "|", "B-XOR": "^", "B-NOT": "~",
    "B-SHIFT-L": "<<", "B-SHIFT-R": ">>",
}


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
        return [f"{_resolve_target(t)}.multiply({source})" for t in targets]
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
        return [f"{_resolve_target(t)}.divide({divisor})" for t in targets]
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
        return [f"{_resolve_target(ops[0])}.divide({divisor})"]
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

        if not expr_parts:
            return [
                f"# COMPUTE: {' '.join(ops)}",
                f"# TODO(high): COMPUTE has no right-hand side — manual translation required",
            ]
        # Resolve expression via unified walker
        expr, has_unknown_func = _resolve_expr_ext(
            " ".join(expr_parts), resolve,
        )
        # Validate expression syntax — emit TODO on parse failure
        try:
            compile(expr, '<compute>', 'eval')
        except SyntaxError:
            return [
                f"# COMPUTE: {' '.join(ops)}",
                f"# TODO(high): expression could not be translated — manual review required",
            ]
        results = [f"# COMPUTE: {' '.join(ops)}"]
        if has_unknown_func:
            results.append(f"# TODO(high): unknown FUNCTION intrinsic replaced with 0 — verify")
        for t in targets:
            results.append(
                f"{_resolve_target(t)}.set({expr}{rounded_arg})"
            )
        return results
    return [f"# COMPUTE: could not parse operands: {' '.join(ops)}"]
