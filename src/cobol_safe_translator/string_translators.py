"""COBOL string-manipulation and SET verb translators for the Python mapper.

Extracted to comply with the 500 LOC per file guideline.
Each function translates a specific COBOL verb into Python code line(s).

All translator functions follow this signature:
    def translate_VERB(ops: list[str], resolve: Callable, ...) -> list[str]

where `resolve` is the operand resolver callback (PythonMapper._resolve_operand)
and the return value is a list of Python source lines.
"""

from __future__ import annotations

from typing import Callable

from .utils import _to_python_name


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

    upper_ops = [o.upper() for o in ops]

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
    lines.append(f"self.data.{target}.set({expr})")

    if has_pointer:
        lines.append("# TODO(high): WITH POINTER — pointer arithmetic requires manual implementation")
    if has_overflow:
        lines.append("# TODO(high): ON OVERFLOW — overflow handling requires manual implementation")

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

    upper_ops = [o.upper() for o in ops]

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
    _STOP_KEYWORDS = {"TALLYING", "ON", "OVERFLOW", "END-UNSTRING", "WITH", "COUNT"}
    targets: list[str] = []
    j = into_idx + 1
    while j < len(ops):
        if upper_ops[j] in _STOP_KEYWORDS:
            break
        # Skip DELIMITER IN, COUNT IN sub-clauses
        if upper_ops[j] in ("DELIMITER", "IN"):
            j += 1
            continue
        targets.append(ops[j])
        j += 1

    has_tallying = "TALLYING" in upper_ops
    has_overflow = "OVERFLOW" in upper_ops

    src_expr = resolve(source)
    lines: list[str] = []
    lines.append(f"# UNSTRING {source}")

    if len(delimiters) == 0:
        # No delimiter specified — split by spaces (COBOL default)
        lines.append(f"_parts = str({src_expr}).split()")
    elif len(delimiters) == 1:
        delim_expr = resolve(delimiters[0])
        lines.append(f"_parts = str({src_expr}).split({delim_expr})")
    else:
        # Multiple delimiters — use re.split
        delim_exprs = [resolve(d) for d in delimiters]
        pattern = "|".join(f"{{re.escape(str({d}))}}" for d in delim_exprs)
        lines.append("import re")
        lines.append(f'_parts = re.split(f"{pattern}", str({src_expr}))')

    for idx, tgt in enumerate(targets):
        py_tgt = _to_python_name(tgt)
        lines.append(f"self.data.{py_tgt}.set(_parts[{idx}] if {idx} < len(_parts) else '')")

    if has_tallying:
        lines.append("# TODO(high): TALLYING — count field requires manual implementation")
    if has_overflow:
        lines.append("# TODO(high): ON OVERFLOW — overflow handling requires manual implementation")

    return lines


def translate_inspect(
    ops: list[str],
    resolve: Callable[[str], str],
) -> list[str]:
    """Translate INSPECT verb.

    COBOL: INSPECT field TALLYING counter FOR ALL/LEADING char
           INSPECT field REPLACING ALL/LEADING/FIRST old BY new
           INSPECT field CONVERTING old TO new
    Python: str.count() for TALLYING, str.replace() for REPLACING.
    """
    if not ops:
        return ["# INSPECT: no operands"]

    upper_ops = [o.upper() for o in ops]
    field = ops[0]
    py_field = _to_python_name(field)
    field_expr = f"self.data.{py_field}"

    if "CONVERTING" in upper_ops:
        return [f"# INSPECT {field} CONVERTING",
                "# TODO(high): INSPECT CONVERTING requires manual translation (maketrans)"]

    if "TALLYING" in upper_ops:
        tally_idx = upper_ops.index("TALLYING")
        if tally_idx + 1 >= len(ops):
            return [f"# INSPECT TALLYING: missing counter: {' '.join(ops)}"]
        counter = ops[tally_idx + 1]
        py_counter = _to_python_name(counter)

        # Find FOR keyword and the search character
        search_char = None
        if "FOR" in upper_ops:
            for_idx = upper_ops.index("FOR")
            # Skip ALL/LEADING to find the character
            k = for_idx + 1
            while k < len(ops) and upper_ops[k] in ("ALL", "LEADING", "CHARACTERS"):
                k += 1
            if k < len(ops):
                search_char = ops[k]

        lines = [f"# INSPECT {field} TALLYING {counter}"]
        if search_char:
            char_expr = resolve(search_char)
            lines.append(f"self.data.{py_counter}.set(str({field_expr}.value).count({char_expr}))")
        else:
            lines.append(f"self.data.{py_counter}.set(len(str({field_expr}.value)))")
        return lines

    if "REPLACING" in upper_ops:
        repl_idx = upper_ops.index("REPLACING")
        # Parse: [ALL|LEADING|FIRST] old BY new
        k = repl_idx + 1
        # Skip ALL/LEADING/FIRST
        mode = "ALL"
        if k < len(ops) and upper_ops[k] in ("ALL", "LEADING", "FIRST"):
            mode = upper_ops[k]
            k += 1

        if k >= len(ops):
            return [f"# INSPECT REPLACING: incomplete clause: {' '.join(ops)}"]

        old_val = ops[k]
        k += 1
        # Skip BY
        if k < len(ops) and upper_ops[k] == "BY":
            k += 1
        if k >= len(ops):
            return [f"# INSPECT REPLACING: missing replacement value: {' '.join(ops)}"]
        new_val = ops[k]

        old_expr = resolve(old_val)
        new_expr = resolve(new_val)

        lines = [f"# INSPECT {field} REPLACING {mode}"]
        if mode == "FIRST":
            lines.append(f"{field_expr}.set(str({field_expr}.value).replace({old_expr}, {new_expr}, 1))")
        else:
            # ALL and LEADING both use replace (LEADING is approximate)
            lines.append(f"{field_expr}.set(str({field_expr}.value).replace({old_expr}, {new_expr}))")
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

    upper_ops = [o.upper() for o in ops]

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

    # SET flag TO TRUE/FALSE or SET idx TO value
    if "TO" in upper_ops:
        to_idx = upper_ops.index("TO")
        target = ops[0]
        target_upper = target.upper()

        if to_idx + 1 < len(ops):
            value_tok = ops[to_idx + 1]

            # SET flag TO TRUE — 88-level condition
            if value_tok.upper() == "TRUE":
                lookup_key = target_upper
                if lookup_key in condition_lookup:
                    py_parent, first_val = condition_lookup[lookup_key]
                    return [f"self.data.{py_parent}.set({first_val})"]
                # Fallback — condition not found in lookup
                py_target = _to_python_name(target)
                return [f"# SET {target} TO TRUE — 88-level not found in data division",
                        f"# TODO(high): locate parent field for condition {target}",
                        f"# self.data.{py_target}_parent.set(...)"]

            # SET flag TO FALSE — non-standard
            if value_tok.upper() == "FALSE":
                return [f"# SET {target} TO FALSE",
                        "# TODO(high): SET TO FALSE is non-standard — manual translation required"]

            # SET idx TO value
            py_target = _to_python_name(target)
            val_expr = resolve(value_tok)
            return [f"self.data.{py_target}.set({val_expr})"]

    return [f"# SET: could not parse operands: {' '.join(ops)}",
            "# TODO(high): SET requires manual translation"]
