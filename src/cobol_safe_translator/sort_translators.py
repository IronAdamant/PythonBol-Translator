"""COBOL SORT, MERGE, RELEASE, and RETURN verb translators.

Split into a dedicated module for the 500 LOC per file guideline.
Each function translates a specific COBOL verb into Python code line(s).

All translator functions follow this signature:
    def translate_VERB(ops: list[str], ...) -> list[str]

where the return value is a list of Python source lines.
"""

from __future__ import annotations

from .utils import _to_method_name, _to_python_name, _upper_ops

# Clause keywords that terminate field-name collection in KEY clauses
_CLAUSE_STOPS = frozenset((
    "ON", "USING", "GIVING", "INPUT", "OUTPUT",
    "WITH", "DUPLICATES", "COLLATING", "SEQUENCE",
))

# Extended set that also stops on bare ASCENDING/DESCENDING
_KEY_STOPS = _CLAUSE_STOPS | {"ASCENDING", "DESCENDING"}


def _parse_procedure_clause(ops: list[str], upper_ops: list[str], i: int) -> tuple[int, tuple[str, str | None]]:
    """Parse INPUT/OUTPUT PROCEDURE IS para [THRU para]. Returns (new_i, (start, end))."""
    i += 2  # skip PROCEDURE
    if i < len(ops) and upper_ops[i] == "IS":
        i += 1
    start_para = ops[i] if i < len(ops) else ""
    i += 1
    end_para = None
    if i < len(ops) and upper_ops[i] in ("THRU", "THROUGH"):
        i += 1
        if i < len(ops):
            end_para = ops[i]
            i += 1
    return i, (start_para, end_para)


def _parse_sort_merge_clauses(ops: list[str]) -> dict[str, object]:
    """Parse SORT/MERGE operand list into structured clauses.

    Returns a dict with keys: sort_file, keys, using, giving,
    input_procedure, output_procedure.
    """
    result: dict[str, object] = {
        "sort_file": "", "keys": [], "using": [], "giving": [],
        "input_procedure": None, "output_procedure": None,
    }
    if not ops:
        return result

    result["sort_file"] = ops[0]
    upper_ops = _upper_ops(ops)
    keys: list[tuple[str, list[str]]] = []
    i = 1

    while i < len(ops):
        token = upper_ops[i]

        # ON ASCENDING/DESCENDING KEY ...
        if token == "ON" and i + 1 < len(ops) and upper_ops[i + 1] in ("ASCENDING", "DESCENDING"):
            direction = upper_ops[i + 1]
            i += 2
            if i < len(ops) and upper_ops[i] == "KEY":
                i += 1
            fields: list[str] = []
            while i < len(ops) and upper_ops[i] not in _CLAUSE_STOPS:
                fields.append(ops[i])
                i += 1
            if fields:
                keys.append((direction, fields))
            continue

        # Bare ASCENDING/DESCENDING KEY ...
        if token in ("ASCENDING", "DESCENDING"):
            direction = token
            i += 1
            if i < len(ops) and upper_ops[i] == "KEY":
                i += 1
            fields = []
            while i < len(ops) and upper_ops[i] not in _KEY_STOPS:
                fields.append(ops[i])
                i += 1
            if fields:
                keys.append((direction, fields))
            continue

        # USING / GIVING — collect file names until next clause
        if token in ("USING", "GIVING"):
            i += 1
            names: list[str] = []
            stop = _CLAUSE_STOPS | {"USING", "GIVING"}
            while i < len(ops) and upper_ops[i] not in stop:
                names.append(ops[i])
                i += 1
            result[token.lower()] = names
            continue

        # INPUT/OUTPUT PROCEDURE
        if token in ("INPUT", "OUTPUT") and i + 1 < len(ops) and upper_ops[i + 1] == "PROCEDURE":
            i, proc = _parse_procedure_clause(ops, upper_ops, i)
            result[f"{token.lower()}_procedure"] = proc
            continue

        i += 1  # skip unrecognised tokens

    result["keys"] = keys
    return result


def _build_key_lambda(keys: list[tuple[str, list[str]]]) -> str:
    """Build a Python lambda for sorted() key from ASCENDING/DESCENDING keys.

    Records may be strings (from RELEASE/FileAdapter) or dicts, so the
    lambda falls back to str(r) for non-dict records.
    """
    if not keys:
        return ""
    parts: list[str] = []
    for direction, fields in keys:
        for f in fields:
            py = _to_python_name(f)
            accessor = f"(r['{py}'] if isinstance(r, dict) else str(r))"
            parts.append(accessor)
    if len(parts) == 1:
        return f"key=lambda r: {parts[0]}"
    return f"key=lambda r: ({', '.join(parts)})"


def _all_descending(keys: list[tuple[str, list[str]]]) -> bool:
    """True if every key clause is DESCENDING."""
    return bool(keys) and all(d == "DESCENDING" for d, _ in keys)


def _emit_sort_call(keys: list[tuple[str, list[str]]], target: str) -> list[str]:
    """Emit one or two lines that sort *target* in place using *keys*."""
    if not keys:
        return [f"{target}.sort()"]
    if _all_descending(keys):
        asc = [("ASCENDING", fs) for _, fs in keys]
        return [f"{target}.sort({_build_key_lambda(asc)}, reverse=True)"]
    return [
        f"{target}.sort({_build_key_lambda(keys)})",
        f"# TODO: verify key types (negate works for numeric only)",
    ]


def _emit_read_loop(py_file: str, list_var: str) -> list[str]:
    """Emit open/read-loop/close lines that fill *list_var* from *py_file*."""
    return [
        f"self.{py_file}.open_input()",
        f"while True:",
        f"    _rec = self.{py_file}.read()",
        f"    if _rec is None:",
        f"        break",
        f"    {list_var}.append(_rec)",
        f"self.{py_file}.close()",
    ]


def _emit_write_loop(py_file: str, source_var: str) -> list[str]:
    """Emit open/write-loop/close lines that write *source_var* to *py_file*."""
    return [
        f"self.{py_file}.open_output()",
        f"for _rec in {source_var}:",
        f"    self.{py_file}.write(str(_rec))",
        f"self.{py_file}.close()",
    ]


def _emit_proc_call(proc: tuple[str, str | None], label: str) -> list[str]:
    """Emit paragraph call and optional THRU comment for a PROCEDURE clause."""
    start, end = proc
    lines = [f"self.{_to_method_name(start)}()"]
    if end:
        lines.append(f"# {label} THRU {end} — call paragraphs {start} through {end}")
    return lines


# ---- Public translators ------------------------------------------------


def translate_sort(ops: list[str]) -> list[str]:
    """Translate SORT verb to Python."""
    if not ops:
        return ["# SORT: no operands"]

    c = _parse_sort_merge_clauses(ops)
    sf = _to_python_name(c["sort_file"])
    keys: list[tuple[str, list[str]]] = c["keys"]  # type: ignore[assignment]
    using: list[str] = c["using"]  # type: ignore[assignment]
    giving: list[str] = c["giving"]  # type: ignore[assignment]
    in_proc = c["input_procedure"]
    out_proc = c["output_procedure"]

    lines: list[str] = [f"# SORT {c['sort_file']}"]
    for d, fs in keys:
        lines.append(f"#   {d} KEY: {', '.join(fs)}")

    rec_var = f"_{sf}_records"

    # USING / GIVING
    if using and giving:
        lines.append(f"{rec_var} = []")
        for uf in using:
            lines.extend(_emit_read_loop(_to_python_name(uf), rec_var))
        lines.extend(_emit_sort_call(keys, rec_var))
        for gf in giving:
            lines.extend(_emit_write_loop(_to_python_name(gf), rec_var))
        return lines

    # USING + OUTPUT PROCEDURE
    if using and out_proc:
        lines.append(f"{rec_var} = []")
        for uf in using:
            lines.extend(_emit_read_loop(_to_python_name(uf), rec_var))
        lines.extend(_emit_sort_call(keys, rec_var))
        lines.append(f"self._sort_sorted = list({rec_var})")
        lines.extend(_emit_proc_call(out_proc, "OUTPUT PROCEDURE"))  # type: ignore[arg-type]
        return lines

    # INPUT PROCEDURE + GIVING
    if in_proc and giving:
        lines.append(f"self._sort_work = []")
        lines.extend(_emit_proc_call(in_proc, "INPUT PROCEDURE"))  # type: ignore[arg-type]
        lines.extend(_emit_sort_call(keys, f"self._sort_work"))
        for gf in giving:
            lines.extend(_emit_write_loop(_to_python_name(gf), f"self._sort_work"))
        return lines

    # INPUT PROCEDURE + OUTPUT PROCEDURE
    if in_proc and out_proc:
        lines.append(f"self._sort_work = []")
        lines.extend(_emit_proc_call(in_proc, "INPUT PROCEDURE"))  # type: ignore[arg-type]
        lines.extend(_emit_sort_call(keys, f"self._sort_work"))
        lines.append(f"self._sort_sorted = list(self._sort_work)")
        lines.extend(_emit_proc_call(out_proc, "OUTPUT PROCEDURE"))  # type: ignore[arg-type]
        return lines

    # Fallback
    lines.append("# TODO(high): SORT pattern not recognized — manual translation required")
    lines.append(f"# Operands: {' '.join(ops)}")
    return lines


def translate_merge(ops: list[str]) -> list[str]:
    """Translate MERGE verb to Python."""
    if not ops:
        return ["# MERGE: no operands"]

    c = _parse_sort_merge_clauses(ops)
    mf = _to_python_name(c["sort_file"])
    keys: list[tuple[str, list[str]]] = c["keys"]  # type: ignore[assignment]
    using: list[str] = c["using"]  # type: ignore[assignment]
    giving: list[str] = c["giving"]  # type: ignore[assignment]
    out_proc = c["output_procedure"]

    lines: list[str] = [f"# MERGE {c['sort_file']}"]
    for d, fs in keys:
        lines.append(f"#   {d} KEY: {', '.join(fs)}")

    if not using:
        lines.append("# TODO(high): MERGE requires USING clause — manual translation required")
        lines.append(f"# Operands: {' '.join(ops)}")
        return lines

    # Read each input file
    lines.append("import heapq")
    file_lists: list[str] = []
    for uf in using:
        py_uf = _to_python_name(uf)
        lname = f"_{py_uf}_records"
        file_lists.append(lname)
        lines.append(f"{lname} = []")
        lines.extend(_emit_read_loop(py_uf, lname))

    # Pre-sort each input (they should already be sorted)
    if keys:
        for fl in file_lists:
            lines.extend(_emit_sort_call(keys, fl))

    # Merge
    all_lists = ", ".join(file_lists)
    merged_var = f"_{mf}_merged"
    if keys and _all_descending(keys):
        asc = [("ASCENDING", fs) for _, fs in keys]
        lines.append(
            f"{merged_var} = sorted({' + '.join(file_lists)}, "
            f"{_build_key_lambda(asc)}, reverse=True)"
        )
    elif keys:
        lines.append(
            f"{merged_var} = list(heapq.merge({all_lists}, {_build_key_lambda(keys)}))"
        )
    else:
        lines.append(f"{merged_var} = list(heapq.merge({all_lists}))")

    # Output
    if giving:
        for gf in giving:
            lines.extend(_emit_write_loop(_to_python_name(gf), merged_var))
    elif out_proc:
        lines.append(f"self._{mf}_sorted = list({merged_var})")
        lines.extend(_emit_proc_call(out_proc, "OUTPUT PROCEDURE"))  # type: ignore[arg-type]
    else:
        lines.append("# TODO(high): MERGE has no GIVING or OUTPUT PROCEDURE — manual translation required")

    return lines


def translate_release(ops: list[str]) -> list[str]:
    """Translate RELEASE verb (within INPUT PROCEDURE).

    RELEASE sort-record [FROM data-name]
    Appends a record to the sort work list.
    """
    if not ops:
        return ["# RELEASE: no record specified"]

    record = ops[0]
    py_rec = _to_python_name(record)
    upper_ops = _upper_ops(ops)

    from_expr = None
    if "FROM" in upper_ops:
        idx = upper_ops.index("FROM")
        if idx + 1 < len(ops):
            from_expr = f"self.data.{_to_python_name(ops[idx + 1])}.value"

    lines = [f"# RELEASE {record}"]
    if from_expr:
        lines.append(f"self._sort_work.append({from_expr})")
    else:
        lines.append(f"self._sort_work.append(self.data.{py_rec}.value)")
    return lines


def translate_return_verb(ops: list[str], raw: str) -> list[str]:
    """Translate RETURN verb (within OUTPUT PROCEDURE).

    RETURN sort-file INTO data-name [AT END action]
    Pops the next record from the sorted result list.
    """
    if not ops:
        return [f"# RETURN: no operands: {raw}"]

    sf = _to_python_name(ops[0])
    upper_ops = _upper_ops(ops)

    into_target = None
    if "INTO" in upper_ops:
        idx = upper_ops.index("INTO")
        if idx + 1 < len(ops):
            into_target = _to_python_name(ops[idx + 1])

    at_end_stmts: list[str] = []
    if "AT" in upper_ops and "END" in upper_ops:
        end_idx = upper_ops.index("END")
        parts = [p for p in ops[end_idx + 1:] if p.upper() != "END-RETURN"]
        if parts:
            # Reconstruct AT END body as inline statements
            at_end_stmts = parts

    lines = [f"# RETURN {ops[0]}", f"if self._sort_sorted:"]
    if into_target:
        lines.append(f"    self.data.{into_target}.set(self._sort_sorted.pop(0))")
    else:
        lines.append(f"    _record = self._sort_sorted.pop(0)")
    lines.append("else:")
    if at_end_stmts:
        # AT END body — only runs when no more records
        verb = at_end_stmts[0].upper()
        if verb == "DISPLAY":
            disp_args = " ".join(at_end_stmts[1:])
            lines.append(f"    print({disp_args}, sep='')")
        else:
            lines.append(f"    pass  # AT END: {' '.join(at_end_stmts)}")
    else:
        lines.append("    pass  # AT END — no more records")
    return lines
