"""I/O and miscellaneous verb translators.

Split from statement_translators.py to stay within 500 LOC limit.
Handles: ACCEPT, REWRITE, ON SIZE ERROR wrapping.
"""

from __future__ import annotations

from .utils import _to_python_name, _upper_ops


def translate_accept(ops: list[str], raw: str) -> list[str]:
    """Translate ACCEPT verb.

    ACCEPT var → input()
    ACCEPT var FROM DATE → datetime
    ACCEPT var FROM DAY → datetime
    ACCEPT var FROM TIME → datetime
    ACCEPT var FROM ENVIRONMENT-NAME → os.environ
    """
    if not ops:
        return [f"# ACCEPT: no target: {raw}"]

    target = _to_python_name(ops[0])
    upper_ops = _upper_ops(ops)

    if "FROM" in upper_ops:
        from_idx = upper_ops.index("FROM")
        source = upper_ops[from_idx + 1] if from_idx + 1 < len(upper_ops) else ""
        if source == "DATE":
            return [
                "import datetime as _dt",
                f"self.data.{target}.set(_dt.datetime.now().strftime('%y%m%d'))",
            ]
        if source == "DAY":
            return [
                "import datetime as _dt",
                f"self.data.{target}.set(_dt.datetime.now().strftime('%y%j'))",
            ]
        if source == "DAY-OF-WEEK":
            return [
                "import datetime as _dt",
                f"self.data.{target}.set(str(_dt.datetime.now().isoweekday()))",
            ]
        if source == "TIME":
            return [
                "import datetime as _dt",
                f"self.data.{target}.set(_dt.datetime.now().strftime('%H%M%S%f')[:8])",
            ]
        if source in ("ENVIRONMENT-NAME", "ENVIRONMENT-VALUE"):
            env_name = ops[from_idx + 2] if from_idx + 2 < len(ops) else ""
            if env_name:
                return [
                    "import os as _os",
                    f"self.data.{target}.set(_os.environ.get({env_name!r}, ''))",
                ]
            return [
                "import os as _os",
                f"self.data.{target}.set(_os.environ.get('', ''))"
                f"  # TODO(high): specify environment variable name",
            ]
        if source in ("COMMAND-LINE", "ARGUMENT-NUMBER", "ARGUMENT-VALUE"):
            return [
                "import sys as _sys",
                f"self.data.{target}.set(' '.join(_sys.argv[1:]))",
            ]
        return [
            f"# ACCEPT {ops[0]} FROM {source}",
            f"# TODO(high): ACCEPT FROM {source} — unsupported source",
        ]

    # Plain ACCEPT — user input
    return [f"self.data.{target}.set(input())"]


def translate_rewrite(ops: list[str]) -> list[str]:
    """Translate REWRITE verb.

    REWRITE record-name [FROM data-name]
    Since FileAdapter now supports I-O mode, we can write the record back.
    """
    if not ops:
        return ["# REWRITE: no record specified"]

    record_name = ops[0]
    py_record = _to_python_name(record_name)
    upper_ops = _upper_ops(ops)

    # Determine file name from record name
    file_hint = py_record.replace("_record", "").replace("_rec", "")
    if not file_hint or file_hint == py_record:
        file_hint = py_record + "_file"

    # Check for FROM clause
    from_expr = None
    if "FROM" in upper_ops:
        from_idx = upper_ops.index("FROM")
        if from_idx + 1 < len(ops):
            from_expr = f"self.data.{_to_python_name(ops[from_idx + 1])}.value"

    lines = [f"# REWRITE {record_name} — update record in file"]
    if from_expr:
        lines.append(f"self.{file_hint}.write(str({from_expr}))")
    else:
        lines.append(f"self.{file_hint}.write(str(self.data.{py_record}.value))")
    lines.append(f"# Note: REWRITE semantics (in-place update) approximated as write")
    return lines


def wrap_on_size_error(
    arithmetic_lines: list[str],
    ops: list[str],
) -> list[str]:
    """Wrap arithmetic output with ON SIZE ERROR / NOT ON SIZE ERROR handling.

    Detects ON SIZE ERROR ... NOT ON SIZE ERROR ... END-xxx patterns
    in the operand list and wraps the arithmetic with try/except.
    """
    upper_ops = _upper_ops(ops)

    # Find ON SIZE ERROR position
    on_size_idx = None
    for i in range(len(upper_ops) - 2):
        if upper_ops[i] == "ON" and upper_ops[i + 1] == "SIZE" and upper_ops[i + 2] == "ERROR":
            on_size_idx = i
            break

    if on_size_idx is None:
        return arithmetic_lines

    # Find NOT ON SIZE ERROR
    not_on_size_idx = None
    for i in range(on_size_idx + 3, len(upper_ops) - 3):
        if (upper_ops[i] == "NOT" and upper_ops[i + 1] == "ON"
                and upper_ops[i + 2] == "SIZE" and upper_ops[i + 3] == "ERROR"):
            not_on_size_idx = i
            break

    # Extract error action tokens
    if not_on_size_idx:
        error_action = " ".join(ops[on_size_idx + 3:not_on_size_idx])
        success_action = " ".join(ops[not_on_size_idx + 4:])
    else:
        error_action = " ".join(ops[on_size_idx + 3:])
        success_action = ""

    # Clean up END-xxx from actions
    for end_kw in ("END-ADD", "END-SUBTRACT", "END-MULTIPLY", "END-DIVIDE", "END-COMPUTE"):
        error_action = error_action.replace(end_kw, "").strip()
        success_action = success_action.replace(end_kw, "").strip()

    lines = ["try:"]
    for al in arithmetic_lines:
        lines.append(f"    {al}")
    if success_action:
        lines.append(f"    pass  # NOT ON SIZE ERROR: {success_action}")
    lines.append("except (OverflowError, ZeroDivisionError):")
    if error_action:
        lines.append(f"    pass  # ON SIZE ERROR: {error_action}")
    else:
        lines.append(f"    pass  # ON SIZE ERROR")
    return lines
