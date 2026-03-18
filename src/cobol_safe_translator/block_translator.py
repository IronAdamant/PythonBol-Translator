"""Block-level translation for IF and EVALUATE COBOL statements.

The parser produces FLAT CobolStatement objects. This module reconstructs
block structure at the mapper level to generate Python if/elif/else blocks.

Pipeline position: Called by mapper.py during paragraph method generation.
"""

from __future__ import annotations

from typing import Callable

from .models import CobolStatement
from .utils import FIGURATIVE_RESOLVE, _is_numeric_literal, _to_python_name

_BLOCK_OPENERS = frozenset({"IF", "EVALUATE"})

# Verbs that indicate an inline IF/EVALUATE (body packed into operands)
_KNOWN_BODY_VERBS = frozenset({
    "DISPLAY", "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "COMPUTE", "PERFORM", "SET", "CALL", "GO", "STOP",
    "STRING", "UNSTRING", "INSPECT", "INITIALIZE",
    "OPEN", "CLOSE", "READ", "WRITE",
})


def _indent_line(line: str, indent: int) -> str:
    return ("    " * indent) + line


def translate_if_block(
    stmts: list[CobolStatement],
    start_idx: int,
    translate_stmt_fn: Callable[[CobolStatement], list[str]],
    translate_cond_fn: Callable[[str], str],
    indent: int = 0,
) -> tuple[list[str], int]:
    """Translate a multi-line IF block. Returns (python_lines, next_index)."""
    if_stmt = stmts[start_idx]
    cond_text = " ".join(if_stmt.operands)
    if not cond_text.strip():
        return [_indent_line("# TODO(high): IF block has no condition — manual translation required", indent)], start_idx + 1
    py_cond = translate_cond_fn(cond_text)

    lines: list[str] = [_indent_line(f"if {py_cond}:", indent)]

    then_body: list[str] = []
    else_body: list[str] = []
    in_else = False
    i = start_idx + 1

    while i < len(stmts):
        stmt = stmts[i]

        # Nested END-IFs are consumed by recursive calls, so the
        # first END-IF we see is always ours.
        if stmt.verb == "END-IF":
            i += 1
            break

        # ELSE at our level splits then/else
        if stmt.verb == "ELSE":
            in_else = True
            i += 1
            continue

        target = else_body if in_else else then_body
        if stmt.verb == "IF":
            nested_lines, i = translate_if_block(
                stmts, i, translate_stmt_fn, translate_cond_fn, indent + 1,
            )
            target.extend(nested_lines)
            continue
        if stmt.verb == "EVALUATE":
            nested_lines, i = translate_evaluate_block(
                stmts, i, translate_stmt_fn, translate_cond_fn,
                _fallback_resolve, indent + 1,
            )
            target.extend(nested_lines)
            continue

        # Regular statement — translate and add to current body
        translated = translate_stmt_fn(stmt)
        for tl in translated:
            target.append(_indent_line(tl, indent + 1))
        i += 1
    else:
        # Ran off the end without finding END-IF
        if not then_body and not else_body:
            then_body.append(
                _indent_line("pass  # TODO(high): missing END-IF", indent + 1)
            )

    def _has_code(body: list[str]) -> bool:
        """Check if body has any non-comment executable lines."""
        return any(ln.strip() and not ln.strip().startswith("#") for ln in body)

    if not _has_code(then_body):
        then_body.append(_indent_line("pass", indent + 1))
    lines.extend(then_body)

    if in_else:
        lines.append(_indent_line("else:", indent))
        if not _has_code(else_body):
            else_body.append(_indent_line("pass", indent + 1))
        lines.extend(else_body)

    return lines, i


def translate_evaluate_block(
    stmts: list[CobolStatement],
    start_idx: int,
    translate_stmt_fn: Callable[[CobolStatement], list[str]],
    translate_cond_fn: Callable[[str], str],
    resolve_operand_fn: Callable[[str], str],
    indent: int = 0,
) -> tuple[list[str], int]:
    """Translate a multi-line EVALUATE block. Returns (python_lines, next_index)."""
    eval_stmt = stmts[start_idx]
    subject_ops = eval_stmt.operands

    # Detect ALSO — emit TODO (not in scope)
    upper_ops = [o.upper() for o in subject_ops]
    if "ALSO" in upper_ops:
        lines = [
            _indent_line(f"# EVALUATE ALSO — too complex for auto-translation", indent),
            _indent_line(f"# {eval_stmt.raw_text}", indent),
            _indent_line(f"# TODO(high): translate EVALUATE ALSO manually", indent),
        ]
        # Skip to END-EVALUATE
        i = start_idx + 1
        depth = 1
        while i < len(stmts):
            if stmts[i].verb in _BLOCK_OPENERS:
                depth += 1
            elif stmts[i].verb in ("END-IF", "END-EVALUATE"):
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        return lines, i

    # Determine subject type: TRUE means conditions in WHEN, else equality
    is_true_subject = (
        len(subject_ops) == 1 and subject_ops[0].upper() == "TRUE"
    )
    subject_expr = None
    if not is_true_subject:
        subject_expr = resolve_operand_fn(subject_ops[0]) if subject_ops else "True"

    # Collect WHEN clauses with their bodies
    when_clauses: list[tuple[list[str], list[str]]] = []  # (condition_ops, body_lines)
    current_when_ops: list[str] | None = None
    current_body: list[str] = []

    i = start_idx + 1

    while i < len(stmts):
        stmt = stmts[i]

        if stmt.verb == "END-EVALUATE":
            if current_when_ops is not None:
                when_clauses.append((current_when_ops, current_body))
            i += 1
            break

        if stmt.verb == "WHEN":
            if current_when_ops is not None:
                when_clauses.append((current_when_ops, current_body))
            current_when_ops = list(stmt.operands)
            current_body = []
            i += 1
            continue

        if current_when_ops is not None:
            if stmt.verb == "IF":
                nested_lines, i = translate_if_block(
                    stmts, i, translate_stmt_fn, translate_cond_fn, indent + 1,
                )
                current_body.extend(nested_lines)
                continue
            if stmt.verb == "EVALUATE":
                nested_lines, i = translate_evaluate_block(
                    stmts, i, translate_stmt_fn, translate_cond_fn,
                    resolve_operand_fn, indent + 1,
                )
                current_body.extend(nested_lines)
                continue

        if current_when_ops is not None:
            translated = translate_stmt_fn(stmt)
            for tl in translated:
                current_body.append(_indent_line(tl, indent + 1))
        i += 1
    else:
        # Ran off the end without END-EVALUATE
        if current_when_ops is not None:
            when_clauses.append((current_when_ops, current_body))

    # Merge consecutive WHEN clauses with empty bodies (fall-through → OR)
    merged_clauses: list[tuple[list[list[str]], list[str]]] = []  # (list_of_when_ops, body_lines)
    for when_ops, body in when_clauses:
        if merged_clauses and not merged_clauses[-1][1]:
            # Previous clause had empty body — merge as fall-through
            merged_clauses[-1][0].append(when_ops)
            merged_clauses[-1] = (merged_clauses[-1][0], body)
        else:
            merged_clauses.append(([when_ops], body))

    # Generate if/elif/else chain
    lines: list[str] = []
    for clause_idx, (when_ops_list, body) in enumerate(merged_clauses):
        # Check if any sub-clause is OTHER
        is_other = any(
            len(ops) == 1 and ops[0].upper() == "OTHER" for ops in when_ops_list
        )

        # THRU/THROUGH — emit TODO
        has_thru = any(
            "THRU" in [o.upper() for o in ops] or "THROUGH" in [o.upper() for o in ops]
            for ops in when_ops_list
        )
        if has_thru:
            for ops in when_ops_list:
                lines.append(_indent_line(f"# TODO(high): WHEN THRU/THROUGH — manual translation required", indent))
                lines.append(_indent_line(f"# WHEN {' '.join(ops)}", indent))
            continue

        if is_other:
            keyword = "else:" if clause_idx > 0 else "if True:  # WHEN OTHER (no prior WHEN)"
        else:
            cond_parts: list[str] = []
            for ops in when_ops_list:
                if is_true_subject:
                    cond_parts.append(translate_cond_fn(" ".join(ops)))
                else:
                    # Handle WHEN x OR y OR z — split on OR keyword
                    or_groups: list[list[str]] = [[]]
                    for o in ops:
                        if o.upper() == "OR":
                            or_groups.append([])
                        else:
                            or_groups[-1].append(o)
                    for grp in or_groups:
                        if grp:
                            value = resolve_operand_fn(grp[0])
                            cond_parts.append(f"{subject_expr} == {value}")
            cond = " or ".join(cond_parts) if cond_parts else "True"
            prefix = "if" if clause_idx == 0 else "elif"
            keyword = f"{prefix} {cond}:"

        lines.append(_indent_line(keyword, indent))
        has_code = any(ln.strip() and not ln.strip().startswith("#") for ln in body)
        if not has_code:
            body.append(_indent_line("pass", indent + 1))
        lines.extend(body)

    if not lines:
        lines.append(
            _indent_line("pass  # TODO(high): empty EVALUATE block", indent)
        )

    return lines, i


def _fallback_resolve(op: str) -> str:
    """Fallback resolve_operand for nested blocks (when mapper's resolver is unavailable).

    Handles: quoted strings, numeric literals, figurative constants, and data names.
    Mirrors mapper._resolve_operand logic to avoid incorrect code generation.
    """
    if (op.startswith('"') and op.endswith('"')) or (op.startswith("'") and op.endswith("'")):
        return op
    if _is_numeric_literal(op):
        return op
    fig = FIGURATIVE_RESOLVE.get(op.upper())
    if fig is not None:
        return fig
    return f"self.data.{_to_python_name(op)}.value"


def is_inline_if(stmt: CobolStatement) -> bool:
    """Check if an IF statement has its body packed into operands (single-line)."""
    return any(o.upper() in _KNOWN_BODY_VERBS for o in stmt.operands)


def _translate_inline_body(
    body_parts: list[str],
    translate_stmt_fn: Callable[[CobolStatement], list[str]] | None,
    indent: int,
) -> list[str]:
    """Translate inline IF/ELSE body parts to Python lines."""
    lines: list[str] = []
    if translate_stmt_fn and body_parts:
        body_verb = body_parts[0].upper()
        body_operands = body_parts[1:]
        body_stmt = CobolStatement(
            verb=body_verb,
            raw_text=" ".join(body_parts),
            operands=body_operands,
        )
        translated = translate_stmt_fn(body_stmt)
        for tl in translated:
            lines.append(_indent_line(tl, indent))
    else:
        lines.append(
            _indent_line(f"pass  # TODO(high): inline body: {' '.join(body_parts)}", indent)
        )
    return lines


def translate_inline_if(
    stmt: CobolStatement,
    translate_cond_fn: Callable[[str], str],
    indent: int = 0,
    translate_stmt_fn: Callable[[CobolStatement], list[str]] | None = None,
) -> list[str]:
    """Translate an inline IF (condition + body packed in one statement's operands)."""
    ops = stmt.operands

    # Find boundary between condition and body (first known verb)
    verb_idx = next(
        (i for i, o in enumerate(ops) if o.upper() in _KNOWN_BODY_VERBS), None
    )
    if verb_idx is None or verb_idx == 0:
        return [
            _indent_line(f"# IF (inline, could not parse):", indent),
            _indent_line(f"# {stmt.raw_text}", indent),
            _indent_line(f"# TODO(high): translate inline IF manually", indent),
        ]

    cond_text = " ".join(ops[:verb_idx])
    remaining = [o for o in ops[verb_idx:] if o.upper() != "END-IF"]
    py_cond = translate_cond_fn(cond_text)

    # Split remaining into then-body and else-body at ELSE keyword
    then_parts: list[str] = []
    else_parts: list[str] = []
    in_else = False
    for o in remaining:
        if o.upper() == "ELSE":
            in_else = True
            continue
        if in_else:
            else_parts.append(o)
        else:
            then_parts.append(o)

    lines = [_indent_line(f"if {py_cond}:", indent)]
    lines.extend(_translate_inline_body(then_parts, translate_stmt_fn, indent + 1))

    if else_parts:
        lines.append(_indent_line("else:", indent))
        lines.extend(_translate_inline_body(else_parts, translate_stmt_fn, indent + 1))

    return lines


def is_inline_evaluate(stmt: CobolStatement) -> bool:
    """Check if an EVALUATE has everything packed into one statement's operands."""
    return "WHEN" in [o.upper() for o in stmt.operands]


def translate_inline_evaluate(
    stmt: CobolStatement,
    translate_cond_fn: Callable[[str], str],
    resolve_operand_fn: Callable[[str], str],
    indent: int = 0,
) -> list[str]:
    """Translate an inline EVALUATE (all packed in one statement)."""
    return [
        _indent_line(f"# EVALUATE (inline, too complex for auto-translation):", indent),
        _indent_line(f"# {stmt.raw_text}", indent),
        _indent_line(f"# TODO(high): translate inline EVALUATE manually", indent),
    ]
