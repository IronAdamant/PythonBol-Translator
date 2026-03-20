"""COBOL string-manipulation and SET verb translators for the Python mapper.

Extracted to comply with the 500 LOC per file guideline.
Each function translates a specific COBOL verb into Python code line(s).

All translator functions follow this signature:
    def translate_VERB(ops: list[str], resolve: Callable, ...) -> list[str]

where `resolve` is the operand resolver callback (PythonMapper._resolve_operand)
and the return value is a list of Python source lines.
"""

from __future__ import annotations

from collections.abc import Callable

from .utils import _to_python_name, _upper_ops

# Keywords that terminate target collection in UNSTRING
_UNSTRING_STOP_KEYWORDS = frozenset({"TALLYING", "ON", "OVERFLOW", "END-UNSTRING", "WITH", "COUNT"})


def translate_string(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate STRING verb.

    COBOL: STRING source-1 DELIMITED BY delim source-2 DELIMITED BY SIZE
           INTO target [WITH POINTER ptr] [ON OVERFLOW ...]
    Python: target.set(source1 + source2) with delimiter handling.
    """
    if not ops:
        return ["# STRING: no operands"]

    upper_ops = _upper_ops(ops)

    # Check for WITH POINTER — emit TODO
    has_pointer = "POINTER" in upper_ops
    # Check for ON OVERFLOW — emit TODO
    has_overflow = "OVERFLOW" in upper_ops

    # Find INTO target
    if "INTO" not in upper_ops:
        return [f"# STRING: missing INTO clause: {' '.join(ops)}",
                "# TODO(high): STRING requires manual translation"]

    into_idx = upper_ops.index("INTO")
    if into_idx + 1 >= len(ops):
        return [f"# STRING: missing target after INTO: {' '.join(ops)}"]

    target = _to_python_name(ops[into_idx + 1])

    # Parse sources and delimiters before INTO
    source_parts = ops[:into_idx]
    # Walk source_parts collecting (source, delim_type) pairs
    # delim_type is either "SIZE" or a literal/field
    concat_exprs: list[str] = []
    i = 0
    while i < len(source_parts):
        src_upper = source_parts[i].upper()
        if src_upper in ("DELIMITED", "BY"):
            i += 1
            continue
        # Check if next tokens are DELIMITED BY ...
        # Look ahead for DELIMITED BY
        src = source_parts[i]
        delim_type = "SIZE"  # default: take whole field
        j = i + 1
        if (j < len(source_parts) and source_parts[j].upper() == "DELIMITED"
                and j + 1 < len(source_parts) and source_parts[j + 1].upper() == "BY"):
            if j + 2 < len(source_parts):
                if source_parts[j + 2].upper() == "SIZE":
                    delim_type = "SIZE"
                    i = j + 3
                else:
                    delim_type = source_parts[j + 2]
                    i = j + 3
            else:
                i = j + 2
        else:
            i += 1

        src_expr = resolve(src)
        if delim_type == "SIZE":
            concat_exprs.append(f"str({src_expr})")
        else:
            delim_expr = resolve(delim_type)
            concat_exprs.append(f"str({src_expr}).split({delim_expr})[0]")

    if not concat_exprs:
        return [f"# STRING: no source operands found: {' '.join(ops)}"]

    lines: list[str] = []
    lines.append(f"# STRING INTO {ops[into_idx + 1]}")
    expr = " + ".join(concat_exprs)

    if has_pointer:
        # Find pointer variable name
        ptr_idx = upper_ops.index("POINTER")
        ptr_name = _to_python_name(ops[ptr_idx + 1]) if ptr_idx + 1 < len(ops) else "string_ptr"
        lines.append(f"_str_concat = {expr}")
        lines.append(f"_ptr_pos = int(self.data.{ptr_name}.value) - 1")
        lines.append(f"_tgt_val = str(self.data.{target}.value)")
        lines.append(f"_result = _tgt_val[:_ptr_pos] + _str_concat + _tgt_val[_ptr_pos + len(_str_concat):]")
        lines.append(f"self.data.{target}.set(_result[:len(_tgt_val)])")
        lines.append(f"self.data.{ptr_name}.set(_ptr_pos + len(_str_concat) + 1)")
        if has_overflow:
            lines.append(f"if _ptr_pos + len(_str_concat) > len(_tgt_val):")
            lines.append(f"    pass  # ON OVERFLOW condition met")
    else:
        lines.append(f"self.data.{target}.set({expr})")

    return lines


def translate_unstring(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate UNSTRING verb.

    COBOL: UNSTRING source DELIMITED BY [ALL] delim [OR [ALL] delim2]
           INTO target-1 target-2 ... [TALLYING IN count] [ON OVERFLOW ...]
    Python: Use str.split() and assign to targets.
    """
    if not ops:
        return ["# UNSTRING: no operands"]

    upper_ops = _upper_ops(ops)

    if "INTO" not in upper_ops:
        return [f"# UNSTRING: missing INTO clause: {' '.join(ops)}",
                "# TODO(high): UNSTRING requires manual translation"]

    into_idx = upper_ops.index("INTO")
    source = ops[0]

    # Parse delimiters between source and INTO
    delimiters: list[str] = []
    i = 1
    while i < into_idx:
        tok = upper_ops[i]
        if tok in ("DELIMITED", "BY", "OR", "ALL"):
            i += 1
            continue
        delimiters.append(ops[i])
        i += 1

    # Parse targets after INTO (stop at TALLYING, ON, END-UNSTRING, WITH)
    targets: list[str] = []
    j = into_idx + 1
    while j < len(ops):
        if upper_ops[j] in _UNSTRING_STOP_KEYWORDS:
            break
        # Skip DELIMITER IN, COUNT IN sub-clauses
        if upper_ops[j] in ("DELIMITER", "IN"):
            j += 1
            continue
        targets.append(ops[j])
        j += 1

    has_tallying = "TALLYING" in upper_ops
    has_pointer = "POINTER" in upper_ops

    src_expr = resolve(source)
    lines: list[str] = []
    lines.append(f"# UNSTRING {source}")

    # If POINTER is present, slice source from pointer position first
    if has_pointer:
        ptr_idx = upper_ops.index("POINTER")
        ptr_name = _to_python_name(ops[ptr_idx + 1]) if ptr_idx + 1 < len(ops) else "unstr_ptr"
        lines.append(f"_ptr_pos = int(self.data.{ptr_name}.value) - 1")
        lines.append(f"_src_val = str({src_expr})[_ptr_pos:]")
    else:
        lines.append(f"_src_val = str({src_expr})")

    if not delimiters:
        lines.append("_parts = _src_val.split()")
    elif len(delimiters) == 1:
        delim_expr = resolve(delimiters[0])
        lines.append(f"_parts = _src_val.split({delim_expr})")
    else:
        delim_exprs = [resolve(d) for d in delimiters]
        pattern = "|".join(f"{{re.escape(str({d}))}}" for d in delim_exprs)
        lines.append("import re")
        lines.append(f'_parts = re.split(f"{pattern}", _src_val)')

    for idx, tgt in enumerate(targets):
        py_tgt = _to_python_name(tgt)
        lines.append(f"self.data.{py_tgt}.set(_parts[{idx}] if {idx} < len(_parts) else '')")

    if has_tallying:
        # Find the TALLYING IN counter field
        tally_idx = upper_ops.index("TALLYING")
        # TALLYING [IN] counter
        k = tally_idx + 1
        if k < len(ops) and upper_ops[k] == "IN":
            k += 1
        if k < len(ops):
            tally_name = _to_python_name(ops[k])
            lines.append(f"self.data.{tally_name}.set(len(_parts))")
        else:
            lines.append("# TALLYING counter not found — review UNSTRING syntax")

    if has_pointer:
        # Update pointer past the consumed portion of source
        n_targets = len(targets)
        lines.append(f"_used = sum(len(str(p)) for p in _parts[:{n_targets}]) + max(len(_parts[:{n_targets}]) - 1, 0)")
        lines.append(f"self.data.{ptr_name}.set(_ptr_pos + _used + 1)")

    return lines


def _parse_before_after(
    ops: list[str],
    upper_ops: list[str],
    start_idx: int,
    resolve: Callable[[str], str],
) -> tuple[str | None, str | None]:
    """Extract BEFORE INITIAL and AFTER INITIAL boundary expressions.

    Returns (before_expr, after_expr) as resolved Python expressions.
    """
    before_expr: str | None = None
    after_expr: str | None = None
    k = start_idx
    while k < len(ops):
        if upper_ops[k] == "BEFORE":
            k += 1
            if k < len(ops) and upper_ops[k] == "INITIAL":
                k += 1
            if k < len(ops):
                before_expr = resolve(ops[k])
            k += 1
        elif upper_ops[k] == "AFTER":
            k += 1
            if k < len(ops) and upper_ops[k] == "INITIAL":
                k += 1
            if k < len(ops):
                after_expr = resolve(ops[k])
            k += 1
        else:
            k += 1
    return before_expr, after_expr


def _emit_bounded_op(
    field_expr: str,
    before_expr: str | None,
    after_expr: str | None,
    operation: str,
    result_var: str = "_val",
) -> list[str]:
    """Wrap a string operation so it only applies within BEFORE/AFTER bounds.

    *operation* should be a Python expression using ``{sub}`` as the
    substring placeholder. The result is assigned to *result_var*.
    """
    lines: list[str] = []
    if before_expr is None and after_expr is None:
        lines.append(f"{result_var} = {operation.format(sub=f'str({field_expr}.value)')}")
        return lines

    lines.append(f"_full = str({field_expr}.value)")
    if after_expr is not None and before_expr is not None:
        lines.append(f"_ai = _full.find(str({after_expr}))")
        lines.append(f"_start = _ai + len(str({after_expr})) if _ai >= 0 else 0")
        lines.append(f"_bi = _full.find(str({before_expr}), _start)")
        lines.append(f"_end = _bi if _bi >= 0 else len(_full)")
    elif after_expr is not None:
        lines.append(f"_ai = _full.find(str({after_expr}))")
        lines.append(f"_start = _ai + len(str({after_expr})) if _ai >= 0 else 0")
        lines.append("_end = len(_full)")
    else:  # before_expr only
        lines.append("_start = 0")
        lines.append(f"_bi = _full.find(str({before_expr}))")
        lines.append(f"_end = _bi if _bi >= 0 else len(_full)")
    lines.append(f"_sub = _full[_start:_end]")
    lines.append(f"{result_var} = _full[:_start] + {operation.format(sub='_sub')} + _full[_end:]")
    return lines


def translate_inspect(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate INSPECT verb.

    COBOL: INSPECT field TALLYING counter FOR ALL/LEADING char [BEFORE/AFTER INITIAL x]
           INSPECT field REPLACING ALL/LEADING/FIRST old BY new [BEFORE/AFTER INITIAL x]
           INSPECT field CONVERTING old TO new [BEFORE/AFTER INITIAL x]
    Python: str.count() for TALLYING, str.replace() for REPLACING,
            str.maketrans/translate for CONVERTING. BEFORE/AFTER bound the region.
    """
    if not ops:
        return ["# INSPECT: no operands"]

    upper_ops = _upper_ops(ops)
    field = ops[0]
    py_field = _to_python_name(field)
    field_expr = f"self.data.{py_field}"

    if "CONVERTING" in upper_ops:
        conv_idx = upper_ops.index("CONVERTING")
        if conv_idx + 1 < len(ops) and "TO" in upper_ops[conv_idx:]:
            to_offset = upper_ops[conv_idx:].index("TO")
            to_abs_idx = conv_idx + to_offset
            old_val = ops[conv_idx + 1]
            new_val = ops[to_abs_idx + 1] if to_abs_idx + 1 < len(ops) else '""'
            old_expr = resolve(old_val)
            new_expr = resolve(new_val)
            before_expr, after_expr = _parse_before_after(
                ops, upper_ops, to_abs_idx + 2, resolve,
            )
            lines = [f"# INSPECT {field} CONVERTING"]
            lines.append(f"_tbl = str.maketrans(str({old_expr}), str({new_expr}))")
            op = "{sub}.translate(_tbl)"
            lines.extend(_emit_bounded_op(field_expr, before_expr, after_expr, op))
            lines.append(f"{field_expr}.set(_val)")
            return lines
        # No TO keyword — emit comment with original COBOL
        return [f"# INSPECT {field} CONVERTING {' '.join(ops[conv_idx + 1:])}",
                f"# INSPECT CONVERTING without TO clause — verify original COBOL"]

    if "TALLYING" in upper_ops:
        tally_idx = upper_ops.index("TALLYING")
        if tally_idx + 1 >= len(ops):
            return [f"# INSPECT TALLYING: missing counter: {' '.join(ops)}"]
        counter = ops[tally_idx + 1]
        py_counter = _to_python_name(counter)

        search_char = None
        search_end_idx = len(ops)
        if "FOR" in upper_ops:
            for_idx = upper_ops.index("FOR")
            k = for_idx + 1
            while k < len(ops) and upper_ops[k] in ("ALL", "LEADING", "CHARACTERS"):
                k += 1
            if k < len(ops) and upper_ops[k] not in ("BEFORE", "AFTER"):
                search_char = ops[k]
                search_end_idx = k + 1
            else:
                search_end_idx = k

        before_expr, after_expr = _parse_before_after(
            ops, upper_ops, search_end_idx, resolve,
        )

        lines = [f"# INSPECT {field} TALLYING {counter}"]
        if before_expr is None and after_expr is None:
            if search_char:
                char_expr = resolve(search_char)
                lines.append(f"self.data.{py_counter}.set(str({field_expr}.value).count({char_expr}))")
            else:
                lines.append(f"self.data.{py_counter}.set(len(str({field_expr}.value)))")
        else:
            # Apply BEFORE/AFTER bounds then count
            lines.extend(_emit_bounded_op(field_expr, before_expr, after_expr, "{sub}", "_region"))
            if search_char:
                char_expr = resolve(search_char)
                lines.append(f"self.data.{py_counter}.set(_region.count({char_expr}))")
            else:
                lines.append(f"self.data.{py_counter}.set(len(_region))")
        return lines

    if "REPLACING" in upper_ops:
        repl_idx = upper_ops.index("REPLACING")
        k = repl_idx + 1
        mode = "ALL"
        if k < len(ops) and upper_ops[k] in ("ALL", "LEADING", "FIRST"):
            mode = upper_ops[k]
            k += 1

        if k >= len(ops):
            return [f"# INSPECT REPLACING: incomplete clause: {' '.join(ops)}"]

        old_val = ops[k]
        k += 1
        if k < len(ops) and upper_ops[k] == "BY":
            k += 1
        if k >= len(ops):
            return [f"# INSPECT REPLACING: missing replacement value: {' '.join(ops)}"]
        new_val = ops[k]
        k += 1

        old_expr = resolve(old_val)
        new_expr = resolve(new_val)
        before_expr, after_expr = _parse_before_after(ops, upper_ops, k, resolve)

        lines = [f"# INSPECT {field} REPLACING {mode}"]
        if mode == "FIRST":
            op = f"{{sub}}.replace({old_expr}, {new_expr}, 1)"
        else:
            op = f"{{sub}}.replace({old_expr}, {new_expr})"
        lines.extend(_emit_bounded_op(field_expr, before_expr, after_expr, op))
        lines.append(f"{field_expr}.set(_val)")
        if mode == "LEADING":
            lines.append("# NOTE: LEADING replacement approximated with str.replace()")
        return lines

    return [f"# INSPECT: unrecognized form: {' '.join(ops)}",
            "# TODO(high): INSPECT requires manual translation"]


def translate_set(
    ops: list[str],
    resolve: Callable[[str], str],
    condition_lookup: dict[str, tuple[str, str]],
) -> list[str]:
    """Translate SET verb.

    COBOL: SET flag TO TRUE      (88-level condition)
           SET flag TO FALSE     (non-standard)
           SET idx UP BY n       (index increment)
           SET idx DOWN BY n     (index decrement)
           SET idx TO value      (index assignment)
    """
    if not ops:
        return ["# SET: no operands"]

    upper_ops = _upper_ops(ops)

    # SET idx UP BY n
    if "UP" in upper_ops and "BY" in upper_ops:
        by_idx = upper_ops.index("BY")
        target = ops[0]
        py_target = _to_python_name(target)
        if by_idx + 1 < len(ops):
            amount = resolve(ops[by_idx + 1])
            return [f"self.data.{py_target}.add({amount})"]
        return [f"# SET {target} UP BY: missing amount"]

    # SET idx DOWN BY n
    if "DOWN" in upper_ops and "BY" in upper_ops:
        by_idx = upper_ops.index("BY")
        target = ops[0]
        py_target = _to_python_name(target)
        if by_idx + 1 < len(ops):
            amount = resolve(ops[by_idx + 1])
            return [f"self.data.{py_target}.subtract({amount})"]
        return [f"# SET {target} DOWN BY: missing amount"]

    # SET flag1 [flag2 ...] TO TRUE/FALSE or SET idx TO value
    if "TO" in upper_ops:
        to_idx = upper_ops.index("TO")
        targets = ops[:to_idx]

        if to_idx + 1 < len(ops):
            value_tok = ops[to_idx + 1]

            # SET flag(s) TO TRUE — 88-level condition
            if value_tok.upper() == "TRUE":
                results: list[str] = []
                for target in targets:
                    lookup_key = target.upper()
                    if lookup_key in condition_lookup:
                        py_parent, first_val = condition_lookup[lookup_key]
                        results.append(f"self.data.{py_parent}.set({first_val})")
                    else:
                        py_target = _to_python_name(target)
                        results.extend([
                            f"# SET {target} TO TRUE — 88-level not found in data division",
                            f"# TODO(high): locate parent field for condition {target}",
                            f"# self.data.{py_target}_parent.set(...)",
                        ])
                return results

            # SET flag TO FALSE — non-standard
            if value_tok.upper() == "FALSE":
                return [f"# SET {' '.join(targets)} TO FALSE",
                        "# TODO(high): SET TO FALSE is non-standard — manual translation required"]

            # SET idx TO value (single target only)
            target = targets[0] if targets else ops[0]
            py_target = _to_python_name(target)
            val_expr = resolve(value_tok)
            return [f"self.data.{py_target}.set({val_expr})"]

    return [f"# SET: could not parse operands: {' '.join(ops)}",
            "# TODO(high): SET requires manual translation"]
