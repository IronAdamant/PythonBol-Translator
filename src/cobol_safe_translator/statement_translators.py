"""Individual COBOL verb translators for the Python mapper.

Extracted from mapper.py to comply with the 500 LOC per file guideline.
Each function translates a specific COBOL verb into Python code line(s).

All translator functions follow this signature:
    def translate_VERB(ops: list[str], resolve: Callable, ...) -> list[str]

where `resolve` is the operand resolver callback (PythonMapper._resolve_operand)
and the return value is a list of Python source lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from .models import CobolStatement

if TYPE_CHECKING:
    pass


def _to_python_name(cobol_name: str) -> str:
    """Convert COBOL data name to a valid Python identifier.

    Re-exported here to avoid circular imports. The canonical version
    lives in mapper.py.
    """
    import keyword
    import re

    name = cobol_name.lower().replace("-", "_")
    if name and name[0].isdigit():
        name = f"f_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    name = re.sub(r"[^\w]", "_", name)
    return name or "_unnamed"


def _is_numeric_literal(s: str) -> bool:
    """Check if a string is a numeric literal."""
    if not s:
        return False
    check = s[1:] if s[0] in ("-", "+") and len(s) > 1 else s
    parts = check.split(".")
    if len(parts) == 1:
        return parts[0].isdigit()
    if len(parts) == 2:
        return (parts[0].isdigit() or parts[0] == "") and (parts[1].isdigit() or parts[1] == "")
    return False


# Keywords that should be filtered from arithmetic operand/target lists
_ARITHMETIC_KEYWORDS = frozenset({
    "ROUNDED", "ON", "SIZE", "ERROR", "NOT",
})


def _to_method_name(para_name: str) -> str:
    """Convert COBOL paragraph name to Python method name."""
    _RESERVED = frozenset({"run", "__init__", "data"})
    name = _to_python_name(para_name)
    if name in _RESERVED:
        name = f"para_{name}"
    return name


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
    if ops and ops[0].upper() == "CORRESPONDING":
        return ["# TODO(high): MOVE CORRESPONDING — manual field matching required"]
    if ops and ops[0].upper() == "ALL":
        return [f"# TODO(high): MOVE ALL — repeats value to fill target field: {' '.join(ops)}"]
    if "TO" not in [o.upper() for o in ops]:
        return [f"# MOVE: could not parse operands: {' '.join(ops)}"]
    to_idx = next(i for i, o in enumerate(ops) if o.upper() == "TO")
    source = ops[0]
    targets = ops[to_idx + 1:]
    if not targets:
        return [f"# MOVE: missing target operand: {' '.join(ops)}"]

    if source.startswith('"') or source.startswith("'"):
        src_expr = source
    elif _is_numeric_literal(source):
        src_expr = source
    elif source.upper().startswith("FUNCTION"):
        return ["# TODO(high): MOVE FUNCTION — manual translation required"]
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


def translate_add(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate ADD verb."""
    if not ops:
        return ["# ADD: no operands"]
    upper_ops = [o.upper() for o in ops]
    if "GIVING" in upper_ops:
        giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
        giving_targets = ops[giving_idx + 1:]
        if not giving_targets:
            return [f"# ADD GIVING: missing target operand: {' '.join(ops)}"]
        pre_giving = ops[:giving_idx]
        if "TO" in [o.upper() for o in pre_giving]:
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
            if t.upper() != "ROUNDED":
                results.append(f"self.data.{_to_python_name(t)}.set({sum_expr})")
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
                results.append(f"self.data.{_to_python_name(t)}.add({src_expr})")
        return results
    return [f"# ADD: could not parse operands: {' '.join(ops)}"]


def translate_subtract(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate SUBTRACT verb."""
    if not ops:
        return ["# SUBTRACT: no operands"]
    upper_ops = [o.upper() for o in ops]
    if "GIVING" in upper_ops:
        giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
        giving_targets = ops[giving_idx + 1:]
        if not giving_targets:
            return [f"# SUBTRACT GIVING: missing target operand: {' '.join(ops)}"]
        pre_giving = ops[:giving_idx]
        if "FROM" in [o.upper() for o in pre_giving]:
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
            if t.upper() != "ROUNDED":
                results.append(f"self.data.{_to_python_name(t)}.set({expr})")
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
                results.append(f"self.data.{_to_python_name(t)}.subtract({src_expr})")
        return results
    return [f"# SUBTRACT: could not parse operands: {' '.join(ops)}"]


def translate_multiply(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate MULTIPLY verb."""
    upper_ops = [o.upper() for o in ops]
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
                if t.upper() != "ROUNDED":
                    results.append(f"self.data.{_to_python_name(t)}.set({source} * {multiplicand})")
            if not results:
                return [f"# MULTIPLY GIVING: no valid target found: {' '.join(ops)}"]
            return results
        raw_targets = ops[by_idx + 1:]
        targets = [t for t in raw_targets if t.upper() not in _ARITHMETIC_KEYWORDS and t.upper() != "ROUNDED"]
        if not targets:
            return [f"# MULTIPLY: missing target operand: {' '.join(ops)}"]
        results = []
        for t in targets:
            results.append(f"self.data.{_to_python_name(t)}.multiply({source})")
        return results
    return [f"# MULTIPLY: could not parse operands: {' '.join(ops)}"]


def translate_divide(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate DIVIDE verb."""
    upper_ops = [o.upper() for o in ops]
    if "INTO" in upper_ops:
        into_idx = next(i for i, o in enumerate(upper_ops) if o == "INTO")
        if into_idx == 0:
            return [f"# DIVIDE: missing divisor operand: {' '.join(ops)}"]
        divisor = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            dividend = resolve(ops[into_idx + 1]) if into_idx + 1 < len(ops) and into_idx + 1 < giving_idx else "0"
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
            results.append("# TODO: verify divisor is non-zero before division (COBOL EC-SIZE-ZERO-DIVIDE)")
            for t in giving_targets:
                results.append(f"self.data.{_to_python_name(t)}.set({dividend} / {divisor})")
            if has_remainder and remainder_target:
                results.append(f"# TODO(high): REMAINDER {remainder_target} — compute modulo manually")
                results.append(f"# self.data.{_to_python_name(remainder_target)}.set({dividend} % {divisor})")
            return results
        raw_targets = ops[into_idx + 1:]
        targets = [t for t in raw_targets if t.upper() not in _ARITHMETIC_KEYWORDS and t.upper() != "ROUNDED"]
        if not targets:
            return [f"# DIVIDE: missing target operand: {' '.join(ops)}"]
        results = []
        for t in targets:
            results.append(f"self.data.{_to_python_name(t)}.divide({divisor})")
        return results
    if "BY" in upper_ops:
        by_idx = next(i for i, o in enumerate(upper_ops) if o == "BY")
        if by_idx == 0:
            return [f"# DIVIDE: missing dividend operand: {' '.join(ops)}"]
        dividend = resolve(ops[0])
        if "GIVING" in upper_ops:
            giving_idx = next(i for i, o in enumerate(upper_ops) if o == "GIVING")
            divisor = resolve(ops[by_idx + 1]) if by_idx + 1 < len(ops) and by_idx + 1 < giving_idx else "1"
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
            results.append("# TODO: verify divisor is non-zero before division (COBOL EC-SIZE-ZERO-DIVIDE)")
            for t in giving_targets:
                results.append(f"self.data.{_to_python_name(t)}.set({dividend} / {divisor})")
            if has_remainder and remainder_target:
                results.append(f"# TODO(high): REMAINDER {remainder_target} — compute modulo manually")
                results.append(f"# self.data.{_to_python_name(remainder_target)}.set({dividend} % {divisor})")
            return results
        if by_idx + 1 >= len(ops):
            return [f"# DIVIDE BY: missing divisor: {' '.join(ops)}"]
        divisor = resolve(ops[by_idx + 1])
        return [f"# TODO(high): DIVIDE BY without GIVING — manual translation required",
                f"# {dividend} / {divisor}"]
    return [f"# DIVIDE: could not parse operands: {' '.join(ops)}"]


def translate_compute(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate COMPUTE verb."""
    _COMPUTE_OPERATORS = {"+", "-", "*", "/", "(", ")", "**"}
    if "=" in ops:
        eq_idx = ops.index("=")
        targets = [t for t in ops[:eq_idx] if t.upper() != "ROUNDED"]
        expr_parts = ops[eq_idx + 1:]
        resolved: list[str] = []
        for part in expr_parts:
            if part in _COMPUTE_OPERATORS:
                resolved.append(part)
            else:
                resolved.append(resolve(part))
        expr = " ".join(resolved)
        if not expr:
            return [
                f"# COMPUTE: {' '.join(ops)}",
                f"# TODO(high): COMPUTE has no right-hand side — manual translation required",
            ]
        results = [f"# COMPUTE: {' '.join(ops)}"]
        for t in targets:
            results.append(
                f"self.data.{_to_python_name(t)}.set({expr})  # TODO(high): verify expression translation"
            )
        return results
    return [f"# COMPUTE: could not parse operands: {' '.join(ops)}"]


def _translate_perform_varying(
    ops: list[str],
    raw: str,
    translate_condition: Callable[[str], str],
) -> list[str]:
    """Translate PERFORM [para] VARYING var FROM start BY step UNTIL cond.

    Supports single-variable VARYING only.  Multi-VARYING (nested loops) and
    any missing/out-of-order keyword fall back to TODO(high).
    """
    upper_ops = [o.upper() for o in ops]

    # Reject multi-VARYING (nested loops not supported)
    if upper_ops.count("VARYING") > 1:
        return [
            f"# PERFORM VARYING (multi): {raw}",
            f"# TODO(high): multi-VARYING nested loops require manual translation",
        ]

    # Locate required keywords
    try:
        varying_idx = upper_ops.index("VARYING")
        from_idx = upper_ops.index("FROM")
        by_idx = upper_ops.index("BY")
        until_idx = upper_ops.index("UNTIL")
    except ValueError:
        return [
            f"# PERFORM VARYING: {raw}",
            f"# TODO(high): PERFORM VARYING requires manual translation (FROM/BY/UNTIL clauses)",
        ]

    # Validate keyword order
    if not (varying_idx < from_idx < by_idx < until_idx):
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

    # Extract loop components
    loop_var = ops[varying_idx + 1] if varying_idx + 1 < from_idx else None
    start_val = ops[from_idx + 1] if from_idx + 1 < by_idx else None
    step_val = ops[by_idx + 1] if by_idx + 1 < until_idx else None
    cond_parts = ops[until_idx + 1:]

    if not loop_var or not start_val or not step_val or not cond_parts:
        return [
            f"# PERFORM VARYING: {raw}",
            f"# TODO(high): PERFORM VARYING requires manual translation (FROM/BY/UNTIL clauses)",
        ]

    if _is_numeric_literal(step_val) and float(step_val) == 0:
        return [
            f"# PERFORM VARYING: {raw}",
            f"# TODO(high): PERFORM VARYING with zero step would generate infinite loop — manual translation required",
        ]

    py_var = _to_python_name(loop_var)
    start_expr = start_val if _is_numeric_literal(start_val) else f"self.data.{_to_python_name(start_val)}.value"
    step_expr = step_val if _is_numeric_literal(step_val) else f"self.data.{_to_python_name(step_val)}.value"
    cond = " ".join(cond_parts)
    translated_cond = translate_condition(cond)

    lines = [
        f"# PERFORM VARYING {loop_var} FROM {start_val} BY {step_val} UNTIL {cond}",
        f"self.data.{py_var}.set({start_expr})",
        f"while not ({translated_cond}):",
    ]
    if para_call:
        lines.append(f"    {para_call}")
    else:
        lines.append(f"    pass  # TODO(high): inline PERFORM VARYING — statements should be moved here")
    lines.append(f"    self.data.{py_var}.add({step_expr})")
    return lines


def translate_perform(
    ops: list[str],
    raw: str,
    translate_condition: Callable[[str], str],
) -> list[str]:
    """Translate PERFORM verb."""
    if not ops:
        return ["# PERFORM with no target"]

    target = _to_method_name(ops[0])
    upper_ops = [o.upper() for o in ops]

    if "THRU" in upper_ops or "THROUGH" in upper_ops:
        return [
            f"# PERFORM THRU: {raw}",
            f"# TODO(high): PERFORM THRU/THROUGH requires manual translation (paragraph range)",
            f"self.{target}()  # only first paragraph — range endpoint missing",
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

    if "TIMES" in [o.upper() for o in ops]:
        times_idx = next(i for i, o in enumerate(ops) if o.upper() == "TIMES")
        if times_idx >= 2:
            times_op = ops[times_idx - 1]
            target = _to_method_name(ops[0])
        elif times_idx == 1:
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


def translate_open(ops: list[str]) -> list[str]:
    """Translate OPEN verb."""
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


def translate_close(ops: list[str]) -> list[str]:
    """Translate CLOSE verb."""
    _CLOSE_KEYWORDS = {"WITH", "LOCK", "NO", "REWIND"}
    results: list[str] = []
    for op in ops:
        if op.upper() in _CLOSE_KEYWORDS:
            continue
        py_name = _to_python_name(op)
        results.append(f"self.{py_name}.close()")
    return results


def translate_read(ops: list[str], raw: str) -> list[str]:
    """Translate READ verb."""
    if ops:
        file_name = _to_python_name(ops[0])
        upper_ops = [o.upper() for o in ops]
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
