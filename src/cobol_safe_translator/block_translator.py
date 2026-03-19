"""Block-level translation for IF and SEARCH COBOL statements.

The parser produces FLAT CobolStatement objects. This module reconstructs
block structure at the mapper level to generate Python if/elif/else blocks
and SEARCH for-loops.

EVALUATE block translation lives in evaluate_translator.py but is
re-exported here for backward compatibility.

Pipeline position: Called by mapper.py during paragraph method generation.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .models import CobolStatement
from .utils import _has_code, _indent_line, resolve_operand as _fallback_resolve, _to_python_name, _upper_ops

# Verbs that indicate an inline IF/EVALUATE (body packed into operands)
_KNOWN_BODY_VERBS = frozenset({
    "DISPLAY", "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE",
    "COMPUTE", "PERFORM", "SET", "CALL", "GO", "STOP",
    "STRING", "UNSTRING", "INSPECT", "INITIALIZE",
    "OPEN", "CLOSE", "READ", "WRITE",
    "ACCEPT", "REWRITE", "GOBACK", "EXIT", "NEXT", "CONTINUE",
    "SEARCH", "SORT", "MERGE", "RELEASE", "RETURN", "DELETE", "START",
    "INITIATE", "GENERATE", "TERMINATE",
})


def _try_nested_block(
    stmt: CobolStatement,
    stmts: list[CobolStatement],
    i: int,
    translate_stmt_fn: Callable[[CobolStatement], list[str]],
    translate_cond_fn: Callable[[str], str],
    resolve_fn: Callable[[str], str],
    indent: int,
    target: list[str],
) -> int | None:
    """Dispatch nested IF/EVALUATE/SEARCH blocks.

    Returns new index if the statement was handled, or None if not a nested block.
    """
    if stmt.verb == "IF":
        nested, new_i = translate_if_block(
            stmts, i, translate_stmt_fn, translate_cond_fn, indent,
        )
        target.extend(nested)
        return new_i
    if stmt.verb == "EVALUATE":
        from .evaluate_translator import translate_evaluate_block as _eval_block
        nested, new_i = _eval_block(
            stmts, i, translate_stmt_fn, translate_cond_fn, resolve_fn, indent,
        )
        target.extend(nested)
        return new_i
    if stmt.verb == "SEARCH":
        nested, new_i = translate_search_block(
            stmts, i, translate_stmt_fn, translate_cond_fn, indent,
        )
        target.extend(nested)
        return new_i
    return None


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
        new_i = _try_nested_block(
            stmt, stmts, i, translate_stmt_fn, translate_cond_fn,
            _fallback_resolve, indent + 1, target,
        )
        if new_i is not None:
            i = new_i
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

    if not _has_code(then_body):
        then_body.append(_indent_line("pass", indent + 1))
    lines.extend(then_body)

    if in_else:
        lines.append(_indent_line("else:", indent))
        if not _has_code(else_body):
            else_body.append(_indent_line("pass", indent + 1))
        lines.extend(else_body)

    return lines, i


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


# Re-export EVALUATE translators (mapper_codegen imports them via block_translator)
from .evaluate_translator import translate_evaluate_block, is_inline_evaluate, translate_inline_evaluate  # noqa: F401,E402


# ---------------------------------------------------------------------------
# SEARCH block translation
# ---------------------------------------------------------------------------

def _parse_search_operands(operands: list[str]) -> tuple[str, bool, bool]:
    """Extract table name and flags from SEARCH operands.

    Returns (table_name, is_search_all, has_at_end).
    The parser folds AT END into the SEARCH operands (since AT and END are
    in _OPERAND_VERBS).  Statements between SEARCH and the first WHEN are
    the AT END body only when AT END was present in the operands.
    """
    is_all = False
    has_at_end = False
    table_name = ""
    upper_ops = _upper_ops(operands)
    for idx, upper in enumerate(upper_ops):
        if upper == "ALL":
            is_all = True
        elif upper == "AT" and idx + 1 < len(upper_ops) and upper_ops[idx + 1] == "END":
            has_at_end = True
        elif upper not in ("AT", "END") and not table_name:
            table_name = operands[idx]
    return table_name, is_all, has_at_end


def translate_search_block(
    stmts: list[CobolStatement],
    start_idx: int,
    translate_stmt_fn: Callable[[CobolStatement], list[str]],
    translate_cond_fn: Callable[[str], str],
    indent: int = 0,
) -> tuple[list[str], int]:
    """Translate a SEARCH / SEARCH ALL block into a Python for-loop.

    Scans forward from *start_idx* collecting AT END and WHEN clauses
    until END-SEARCH.  Returns (python_lines, next_index).

    Serial SEARCH generates::

        _found = False
        for _idx in range(len(self.data.table)):
            if condition_1:
                action_1
                _found = True
                break
        if not _found:
            at_end_action

    SEARCH ALL is approximated as a linear scan (we cannot guarantee the
    table is sorted at run-time).
    """
    search_stmt = stmts[start_idx]
    table_name, is_search_all, has_at_end = _parse_search_operands(
        search_stmt.operands
    )

    if not table_name:
        # Cannot determine table — fall back to TODO
        return [
            _indent_line(
                "# TODO(high): SEARCH could not determine table name", indent
            ),
            _indent_line(f"# {search_stmt.raw_text}", indent),
        ], start_idx + 1

    py_table = _to_python_name(table_name)

    # ------------------------------------------------------------------
    # Collect AT END body and WHEN clauses.
    #
    # The parser folds "AT END" into the SEARCH operands.  If has_at_end
    # is True, statements between the SEARCH stmt and the first WHEN are
    # the AT END body.  Otherwise those stray statements are ignored (or
    # placed in a fallback bucket).
    # ------------------------------------------------------------------
    at_end_body: list[str] = []
    when_clauses: list[tuple[str, list[str]]] = []  # (condition_text, body)
    current_when_cond: str | None = None
    current_body: list[str] = []
    i = start_idx + 1

    while i < len(stmts):
        stmt = stmts[i]

        if stmt.verb == "END-SEARCH":
            if current_when_cond is not None:
                when_clauses.append((current_when_cond, current_body))
            i += 1
            break

        if stmt.verb == "WHEN":
            # Flush previous WHEN clause if any
            if current_when_cond is not None:
                when_clauses.append((current_when_cond, current_body))
            current_when_cond = " ".join(stmt.operands)
            current_body = []
            i += 1
            continue

        # Decide which body this statement belongs to
        if current_when_cond is not None:
            target = current_body
            body_indent = indent + 2  # inside the for + if
        elif has_at_end:
            target = at_end_body
            body_indent = indent + 1  # inside "if not _found:"
        else:
            # No AT END and no WHEN yet — stray statement, collect anyway
            target = at_end_body
            body_indent = indent + 1

        # Handle nested blocks
        new_i = _try_nested_block(
            stmt, stmts, i, translate_stmt_fn, translate_cond_fn,
            _fallback_resolve, body_indent, target,
        )
        if new_i is not None:
            i = new_i
            continue

        translated = translate_stmt_fn(stmt)
        for tl in translated:
            target.append(_indent_line(tl, body_indent))
        i += 1
    else:
        # Ran off the end without END-SEARCH
        if current_when_cond is not None:
            when_clauses.append((current_when_cond, current_body))

    # --- Generate Python code ---
    lines: list[str] = []

    if is_search_all:
        lines.append(
            _indent_line(
                f"# SEARCH ALL {table_name} (binary search approximated as linear)",
                indent,
            )
        )
    else:
        lines.append(_indent_line(f"# SEARCH {table_name}", indent))

    lines.append(_indent_line("_found = False", indent))
    # Use the _occurs constant generated in the data class
    lines.append(
        _indent_line(
            f"for _idx in range(getattr(self.data, '_{py_table}_occurs', 1)):",
            indent,
        )
    )

    # Detect index variable from WHEN conditions (subscript patterns like NAME(IDX))
    _idx_var = None
    for cond_text, _ in when_clauses:
        m = re.search(r'\w[\w-]*\((\w[\w-]*)\)', cond_text)
        if m and not m.group(1).isdigit():
            _idx_var = _to_python_name(m.group(1))
            break
    if _idx_var:
        lines.append(_indent_line(f"self.data.{_idx_var}.set(_idx + 1)", indent + 1))

    if not when_clauses:
        lines.append(
            _indent_line(
                "pass  # TODO(high): SEARCH has no WHEN clauses", indent + 1
            )
        )
    else:
        for cond_text, body in when_clauses:
            py_cond = translate_cond_fn(cond_text)
            lines.append(_indent_line(f"if {py_cond}:", indent + 1))
            if _has_code(body):
                lines.extend(body)
            else:
                lines.append(_indent_line("pass", indent + 2))
            lines.append(_indent_line("_found = True", indent + 2))
            lines.append(_indent_line("break", indent + 2))

    if at_end_body:
        lines.append(_indent_line("if not _found:", indent))
        lines.extend(at_end_body)

    return lines, i
