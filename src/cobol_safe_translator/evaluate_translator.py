"""EVALUATE block translation for COBOL EVALUATE/WHEN statements.

Extracted from block_translator.py to keep modules under 500 LOC.
Handles single-subject, multi-subject (ALSO), and inline EVALUATE forms.

Pipeline position: Called by block_translator._try_nested_block() and
mapper_codegen.py during paragraph method generation.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import CobolStatement
from .utils import _has_code, _indent_line, _upper_ops


def _split_on_also(tokens: list[str]) -> list[list[str]]:
    """Split a token list on ALSO keyword into sub-lists."""
    groups: list[list[str]] = [[]]
    for t in tokens:
        if t.upper() == "ALSO":
            groups.append([])
        else:
            groups[-1].append(t)
    return groups


def _translate_evaluate_also(
    stmts: list[CobolStatement],
    start_idx: int,
    translate_stmt_fn: Callable[[CobolStatement], list[str]],
    translate_cond_fn: Callable[[str], str],
    resolve_operand_fn: Callable[[str], str],
    indent: int = 0,
) -> tuple[list[str], int]:
    """Translate EVALUATE subj1 ALSO subj2 ... with multi-subject WHEN clauses."""
    from .block_translator import _try_nested_block  # late import: avoid circular

    eval_stmt = stmts[start_idx]
    subjects = _split_on_also(eval_stmt.operands)

    # Resolve each subject
    subject_exprs: list[str | None] = []
    is_true: list[bool] = []
    for subj in subjects:
        subj_text = " ".join(subj).strip().upper()
        if subj_text == "TRUE":
            subject_exprs.append(None)
            is_true.append(True)
        else:
            subject_exprs.append(resolve_operand_fn(subj[0]) if subj else "True")
            is_true.append(False)

    # Collect WHEN clauses
    when_clauses: list[tuple[list[str], list[str]]] = []
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
            new_i = _try_nested_block(
                stmt, stmts, i, translate_stmt_fn, translate_cond_fn,
                resolve_operand_fn, indent + 1, current_body,
            )
            if new_i is not None:
                i = new_i
                continue
            translated = translate_stmt_fn(stmt)
            for tl in translated:
                current_body.append(_indent_line(tl, indent + 1))
        i += 1
    else:
        if current_when_ops is not None:
            when_clauses.append((current_when_ops, current_body))

    # Generate if/elif/else chain
    lines: list[str] = []
    for clause_idx, (when_ops, body) in enumerate(when_clauses):
        # Split WHEN values on ALSO to match subject count
        when_parts = _split_on_also(when_ops)
        is_other = all(
            len(p) == 1 and p[0].upper() == "OTHER" for p in when_parts
        )

        if is_other:
            keyword = "else:" if clause_idx > 0 else "if True:  # WHEN OTHER"
        else:
            cond_parts: list[str] = []
            for j, part in enumerate(when_parts):
                part_text = " ".join(part).strip()
                if part_text.upper() == "ANY":
                    continue  # ANY matches everything — no condition needed
                if part_text.upper() == "OTHER":
                    continue
                if j < len(is_true) and is_true[j]:
                    cond_parts.append(translate_cond_fn(part_text))
                elif j < len(subject_exprs) and subject_exprs[j] and part:
                    cond_parts.append(
                        f"{subject_exprs[j]} == {resolve_operand_fn(part[0])}"
                    )
                else:
                    cond_parts.append(translate_cond_fn(part_text))

            cond = " and ".join(cond_parts) if cond_parts else "True"
            prefix = "if" if clause_idx == 0 else "elif"
            keyword = f"{prefix} {cond}:"

        lines.append(_indent_line(keyword, indent))
        if not _has_code(body):
            body.append(_indent_line("pass", indent + 1))
        lines.extend(body)

    if not lines:
        lines.append(_indent_line("pass  # TODO(high): empty EVALUATE ALSO", indent))

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
    from .block_translator import _try_nested_block  # late import: avoid circular

    eval_stmt = stmts[start_idx]
    subject_ops = eval_stmt.operands

    upper_ops = _upper_ops(subject_ops)

    # Multi-subject EVALUATE: EVALUATE subj1 ALSO subj2 ...
    if "ALSO" in upper_ops:
        return _translate_evaluate_also(
            stmts, start_idx, translate_stmt_fn, translate_cond_fn,
            resolve_operand_fn, indent,
        )

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
            new_i = _try_nested_block(
                stmt, stmts, i, translate_stmt_fn, translate_cond_fn,
                resolve_operand_fn, indent + 1, current_body,
            )
            if new_i is not None:
                i = new_i
                continue
            translated = translate_stmt_fn(stmt)
            for tl in translated:
                current_body.append(_indent_line(tl, indent + 1))
        i += 1
    else:
        # Ran off the end without END-EVALUATE
        if current_when_ops is not None:
            when_clauses.append((current_when_ops, current_body))

    # Merge consecutive WHEN clauses with empty bodies (fall-through -> OR)
    merged_clauses: list[tuple[list[list[str]], list[str]]] = []  # (list_of_when_ops, body_lines)
    for when_ops, body in when_clauses:
        if merged_clauses and not merged_clauses[-1][1]:
            # Previous clause had empty body -- merge as fall-through
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

        # THRU/THROUGH -- generate range comparison
        has_thru = any(
            any(o.upper() in ("THRU", "THROUGH") for o in ops)
            for ops in when_ops_list
        )
        if has_thru:
            thru_cond_parts: list[str] = []
            for ops in when_ops_list:
                upper_when = _upper_ops(ops)
                thru_idx = None
                for ti, tok in enumerate(upper_when):
                    if tok in ("THRU", "THROUGH"):
                        thru_idx = ti
                        break
                if thru_idx is not None and thru_idx > 0 and thru_idx + 1 < len(ops):
                    lo_val = resolve_operand_fn(ops[0]) if not is_true_subject else ops[0]
                    hi_val = resolve_operand_fn(ops[thru_idx + 1]) if not is_true_subject else ops[thru_idx + 1]
                    if subject_expr:
                        thru_cond_parts.append(f"{lo_val} <= {subject_expr} <= {hi_val}")
                    else:
                        thru_cond_parts.append(f"{lo_val} <= {hi_val}")
                else:
                    # Non-THRU value in the same WHEN list -- equality check
                    if is_true_subject:
                        thru_cond_parts.append(translate_cond_fn(" ".join(ops)))
                    elif subject_expr:
                        thru_cond_parts.append(f"{subject_expr} == {resolve_operand_fn(ops[0])}")
            cond = " or ".join(thru_cond_parts) if thru_cond_parts else "True"
            prefix = "if" if clause_idx == 0 else "elif"
            lines.append(_indent_line(f"{prefix} {cond}:", indent))
            if not _has_code(body):
                body.append(_indent_line("pass", indent + 1))
            lines.extend(body)
            continue

        if is_other:
            keyword = "else:" if clause_idx > 0 else "if True:  # WHEN OTHER (no prior WHEN)"
        else:
            cond_parts: list[str] = []
            for ops in when_ops_list:
                if is_true_subject:
                    cond_parts.append(translate_cond_fn(" ".join(ops)))
                else:
                    # Handle WHEN x OR y OR z -- split on OR keyword
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
        if not _has_code(body):
            body.append(_indent_line("pass", indent + 1))
        lines.extend(body)

    if not lines:
        lines.append(
            _indent_line("pass  # TODO(high): empty EVALUATE block", indent)
        )

    return lines, i


def is_inline_evaluate(stmt: CobolStatement) -> bool:
    """Check if an EVALUATE has everything packed into one statement's operands."""
    return any(o.upper() == "WHEN" for o in stmt.operands)


def translate_inline_evaluate(
    stmt: CobolStatement,
    translate_cond_fn: Callable[[str], str],
    resolve_operand_fn: Callable[[str], str],
    indent: int = 0,
) -> list[str]:
    """Translate an inline EVALUATE (all packed in one statement).

    Splits operands on WHEN keywords and generates if/elif/else.
    Falls back to a TODO comment for unparseable cases.
    """
    ops = list(stmt.operands)
    upper = _upper_ops(ops)

    # Find WHEN positions
    when_indices = [i for i, t in enumerate(upper) if t == "WHEN"]
    if not when_indices:
        return [
            _indent_line(f"# EVALUATE (inline): {stmt.raw_text}", indent),
            _indent_line(f"# TODO(high): no WHEN found in inline EVALUATE", indent),
        ]

    # Subject is everything before first WHEN
    subj_tokens = ops[:when_indices[0]]
    subj_text = " ".join(subj_tokens).strip().upper()
    is_true_subject = subj_text == "TRUE"
    subject_expr = None
    if not is_true_subject and subj_tokens:
        subject_expr = resolve_operand_fn(subj_tokens[0])

    # Split into WHEN clauses: each clause is (value_tokens, body_tokens)
    clauses: list[tuple[list[str], list[str]]] = []
    for ci, wi in enumerate(when_indices):
        # End of this clause is start of next WHEN or end of ops
        next_wi = when_indices[ci + 1] if ci + 1 < len(when_indices) else len(ops)
        clause_tokens = ops[wi + 1:next_wi]
        # Separate value from body: body starts after value tokens
        # For EVALUATE TRUE, entire clause is a condition + body statements
        # For simple cases, value is first token, rest is body
        if not clause_tokens:
            continue
        if clause_tokens[0].upper() == "OTHER":
            clauses.append((["OTHER"], clause_tokens[1:]))
        elif is_true_subject:
            # For EVALUATE TRUE, try to find where condition ends and body begins
            # Heuristic: body starts at first COBOL verb
            _verbs = frozenset({
                'MOVE', 'DISPLAY', 'PERFORM', 'ADD', 'SUBTRACT', 'MULTIPLY',
                'DIVIDE', 'COMPUTE', 'SET', 'CALL', 'GO', 'STOP', 'STRING',
                'UNSTRING', 'INSPECT', 'ACCEPT', 'READ', 'WRITE', 'OPEN',
                'CLOSE', 'INITIALIZE', 'EVALUATE', 'IF', 'CONTINUE',
            })
            split_at = len(clause_tokens)
            for si, st in enumerate(clause_tokens):
                if st.upper() in _verbs:
                    split_at = si
                    break
            clauses.append((clause_tokens[:split_at], clause_tokens[split_at:]))
        else:
            clauses.append(([clause_tokens[0]], clause_tokens[1:]))

    if not clauses:
        return [
            _indent_line(f"# EVALUATE (inline): {stmt.raw_text}", indent),
            _indent_line(f"# TODO(high): could not parse inline EVALUATE clauses", indent),
        ]

    lines: list[str] = []
    for ci, (val_tokens, body_tokens) in enumerate(clauses):
        val_upper = [v.upper() for v in val_tokens]
        if val_upper == ["OTHER"]:
            if ci > 0:
                lines.append(_indent_line("else:", indent))
            else:
                lines.append(_indent_line("if True:  # WHEN OTHER", indent))
        else:
            if is_true_subject:
                cond = translate_cond_fn(" ".join(val_tokens))
            elif subject_expr:
                cond = f"{subject_expr} == {resolve_operand_fn(val_tokens[0])}"
            else:
                cond = "True"
            prefix = "if" if ci == 0 else "elif"
            lines.append(_indent_line(f"{prefix} {cond}:", indent))

        if body_tokens:
            lines.append(_indent_line(f"pass  # {' '.join(body_tokens)}", indent + 1))
        else:
            lines.append(_indent_line("pass", indent + 1))

    return lines
