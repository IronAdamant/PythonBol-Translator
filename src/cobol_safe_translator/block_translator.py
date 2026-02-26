"""Block-level translation for IF and EVALUATE COBOL statements.

The parser produces FLAT CobolStatement objects. This module reconstructs
block structure at the mapper level to generate Python if/elif/else blocks.

Pipeline position: Called by mapper.py during paragraph method generation.
"""

from __future__ import annotations

from typing import Callable

from .models import CobolStatement

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
                _noop_resolve, indent + 1,
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

    if not then_body:
        then_body.append(_indent_line("pass", indent + 1))
    lines.extend(then_body)

    if in_else:
        lines.append(_indent_line("else:", indent))
        if not else_body:
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

    # Generate if/elif/else chain
    lines: list[str] = []
    for clause_idx, (when_ops, body) in enumerate(when_clauses):
        is_other = len(when_ops) == 1 and when_ops[0].upper() == "OTHER"

        # THRU/THROUGH — emit TODO
        upper_when = [o.upper() for o in when_ops]
        if "THRU" in upper_when or "THROUGH" in upper_when:
            lines.append(_indent_line(f"# TODO(high): WHEN THRU/THROUGH — manual translation required", indent))
            lines.append(_indent_line(f"# WHEN {' '.join(when_ops)}", indent))
            continue

        if is_other:
            keyword = "else:"
        else:
            if is_true_subject:
                cond = translate_cond_fn(" ".join(when_ops))
            else:
                value = resolve_operand_fn(when_ops[0]) if when_ops else "''"
                cond = f"{subject_expr} == {value}"
            prefix = "if" if clause_idx == 0 else "elif"
            keyword = f"{prefix} {cond}:"

        lines.append(_indent_line(keyword, indent))
        if not body:
            lines.append(_indent_line("pass", indent + 1))
        else:
            lines.extend(body)

    if not lines:
        lines.append(
            _indent_line("pass  # TODO(high): empty EVALUATE block", indent)
        )

    return lines, i


def _noop_resolve(op: str) -> str:
    """Fallback resolve_operand for nested blocks."""
    return f"self.data.{op.lower().replace('-', '_')}.value"


def is_inline_if(stmt: CobolStatement) -> bool:
    """Check if an IF statement has its body packed into operands (single-line)."""
    return any(o.upper() in _KNOWN_BODY_VERBS for o in stmt.operands)


def translate_inline_if(
    stmt: CobolStatement,
    translate_cond_fn: Callable[[str], str],
    indent: int = 0,
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
    body_parts = [o for o in ops[verb_idx:] if o.upper() != "END-IF"]
    py_cond = translate_cond_fn(cond_text)

    return [
        _indent_line(f"if {py_cond}:", indent),
        _indent_line(f"pass  # TODO(high): inline body: {' '.join(body_parts)}", indent + 1),
    ]


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
