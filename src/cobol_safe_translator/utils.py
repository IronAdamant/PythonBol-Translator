"""Shared utility functions for the COBOL-to-Python translator.

Centralises helpers that are needed by multiple modules (mapper,
statement_translators, block_translator) to avoid circular imports
and code duplication.
"""

from __future__ import annotations

import keyword
import re


def _upper_ops(ops: list[str]) -> list[str]:
    """Uppercase operand list for case-insensitive keyword matching."""
    return [o.upper() for o in ops]


def _is_numeric_literal(s: str) -> bool:
    """Check if a string is a numeric literal (integer or decimal)."""
    if not s:
        return False
    # Handle sign prefix
    check = s[1:] if s[0] in ("-", "+") and len(s) > 1 else s
    # Must have at least one digit and only digits/one decimal point
    parts = check.split(".")
    if len(parts) == 1:
        return parts[0].isdigit()
    if len(parts) == 2:
        return (parts[0].isdigit() or parts[0] == "") and (parts[1].isdigit() or parts[1] == "") and bool(parts[0] or parts[1])
    return False


def _to_python_name(cobol_name: str) -> str:
    """Convert COBOL data name to a valid Python identifier.

    Handles: hyphens -> underscores, digit-leading names, Python keyword collisions.
    """
    name = cobol_name.lower().replace("-", "_")
    # Prefix with underscore if name starts with a digit
    if name and name[0].isdigit():
        name = f"f_{name}"
    # Suffix with underscore if name collides with a Python keyword
    if keyword.iskeyword(name):
        name = f"{name}_"
    # Remove any remaining invalid characters
    name = re.sub(r"[^\w]", "_", name)
    return name or "_unnamed"


_RESERVED_METHOD_NAMES = frozenset({"run", "__init__", "data"})


def _to_method_name(para_name: str) -> str:
    """Convert COBOL paragraph name to Python method name."""
    name = _to_python_name(para_name)
    if name in _RESERVED_METHOD_NAMES:
        name = f"para_{name}"
    return name


# Figurative constants resolved to Python expressions (for code generation)
FIGURATIVE_RESOLVE: dict[str, str] = {
    "ZERO": "0", "ZEROS": "0", "ZEROES": "0",
    "SPACE": "' '", "SPACES": "' '",
    "HIGH-VALUE": "'\\xff'", "HIGH-VALUES": "'\\xff'",
    "LOW-VALUE": "'\\x00'", "LOW-VALUES": "'\\x00'",
}

_REFMOD_RE = re.compile(r'^([A-Za-z][\w-]*)\((\d+):(\d+)\)$')

# Subscript access: TABLE(IDX) or TABLE(1) — no colon
_SUBSCRIPT_RE = re.compile(r'^([A-Za-z][\w-]*)\(([^:]+)\)$')


def _sanitize_numeric(s: str) -> str:
    """Strip leading zeros from COBOL numeric literals for valid Python.

    '01' -> '1', '007' -> '7', '0' -> '0', '3.14' -> '3.14',
    '00.50' -> '0.50', '-01' -> '-1'.
    """
    if not s:
        return s
    sign = ""
    val = s
    if val[0] in ("-", "+") and len(val) > 1:
        sign = val[0]
        val = val[1:]
    if "." in val:
        int_part, dec_part = val.split(".", 1)
        int_part = int_part.lstrip("0") or "0"
        return f"{sign}{int_part}.{dec_part}"
    val = val.lstrip("0") or "0"
    return f"{sign}{val}"


def _resolve_subscript_base(op: str) -> tuple[str, str] | None:
    """Resolve subscript/qualification to (python_name, indices_str) or None.

    Shared by resolve_operand and resolve_target to avoid duplication.
    """
    sm = _SUBSCRIPT_RE.match(op)
    if sm:
        name, idx_str = sm.group(1), sm.group(2).strip()
        py = _to_python_name(name)
        normalised = idx_str.replace(",", " ")
        sub_parts = normalised.split()
        indices: list[str] = []
        for part in sub_parts:
            if _is_numeric_literal(part):
                indices.append(f"[{int(part) - 1}]")
            else:
                py_idx = _to_python_name(part)
                indices.append(f"[int(self.data.{py_idx}.value) - 1]")
        return py, "".join(indices)
    return None


def _file_hint_from_record(py_record: str) -> str:
    """Derive a file adapter name from a COBOL record name."""
    hint = py_record.replace("_record", "").replace("_rec", "")
    return hint if hint and hint != py_record else py_record + "_file"


def resolve_operand(op: str) -> str:
    """Resolve a COBOL operand to a Python expression.

    Handles: quoted strings, numeric literals, figurative constants,
    FUNCTION keyword, reference modification, OF/IN qualification,
    and plain data names.
    """
    # Hex literal: X"FF" / X'FF' / H"FF" / H'FF' → 0xFF
    if (len(op) >= 4 and op[0].upper() in ('X', 'H')
            and op[1] in ('"', "'") and op[-1] == op[1]):
        hex_str = op[2:-1]
        if hex_str and all(c in '0123456789abcdefABCDEF' for c in hex_str):
            return f"0x{hex_str}"
    # Binary literal: B"01010" or B'01010' → 0b01010
    if (len(op) >= 4 and op[0].upper() == 'B'
            and op[1] in ('"', "'") and op[-1] == op[1]):
        bin_str = op[2:-1]
        if bin_str and all(c in '01' for c in bin_str):
            return f"0b{bin_str}"
    # Quoted string (strict: require matching open and close)
    if len(op) >= 2 and op[0] in ('"', "'") and op[-1] == op[0]:
        inner = op[1:-1]
        # Escape backslashes for Python (COBOL has no escape sequences)
        if '\\' in inner:
            inner = inner.replace('\\', '\\\\')
            return f'{op[0]}{inner}{op[0]}'
        return op
    # Numeric literal — sanitize leading zeros for Python 3
    if _is_numeric_literal(op):
        return _sanitize_numeric(op)
    upper = op.upper()
    # Figurative constant
    fig = FIGURATIVE_RESOLVE.get(upper)
    if fig is not None:
        return fig
    # COBOL intrinsic function — can't auto-translate
    if upper == "FUNCTION":
        return "0"
    # Reference modification: WS-FIELD(1:3) → Python slice
    rm = _REFMOD_RE.match(op)
    if rm:
        name, start, length = rm.group(1), int(rm.group(2)), int(rm.group(3))
        py = _to_python_name(name)
        return f"str(self.data.{py}.value)[{start - 1}:{start - 1 + length}]"
    # Subscript access: TABLE(IDX) or TABLE(1) — no colon
    sub = _resolve_subscript_base(op)
    if sub:
        py, indices = sub
        return f"self.data.{py}{indices}.value"
    # OF/IN qualification: FIELD OF GROUP → take field before OF
    if " OF " in upper or " IN " in upper:
        field = op.split()[0]
        return f"self.data.{_to_python_name(field)}.value"
    # Default data name
    return f"self.data.{_to_python_name(op)}.value"


def extract_from_expr(ops: list[str], upper_ops: list[str]) -> str | None:
    """Extract FROM clause value as a Python expression, or None if absent."""
    if "FROM" in upper_ops:
        idx = upper_ops.index("FROM")
        if idx + 1 < len(ops):
            return f"self.data.{_to_python_name(ops[idx + 1])}.value"
    return None


def resolve_target(op: str) -> str:
    """Resolve a COBOL target operand to a Python assignment target.

    Like resolve_operand but returns 'self.data.name[idx]' (no .value),
    suitable for use with .set()/.add()/.subtract() etc.
    """
    sub = _resolve_subscript_base(op)
    if sub:
        py, indices = sub
        return f"self.data.{py}{indices}"
    if " OF " in op.upper() or " IN " in op.upper():
        fld = op.split()[0]
        return f"self.data.{_to_python_name(fld)}"
    return f"self.data.{_to_python_name(op)}"
