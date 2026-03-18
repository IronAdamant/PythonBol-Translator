"""Shared utility functions for the COBOL-to-Python translator.

Centralises helpers that are needed by multiple modules (mapper,
statement_translators, block_translator) to avoid circular imports
and code duplication.
"""

from __future__ import annotations

import keyword
import re


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
        return (parts[0].isdigit() or parts[0] == "") and (parts[1].isdigit() or parts[1] == "")
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


def resolve_operand(op: str) -> str:
    """Resolve a COBOL operand to a Python expression.

    Handles: quoted strings, numeric literals, figurative constants,
    FUNCTION keyword, reference modification, OF/IN qualification,
    and plain data names.
    """
    # Quoted string (strict: require matching open and close)
    if len(op) >= 2 and op[0] in ('"', "'") and op[-1] == op[0]:
        return op
    # Numeric literal
    if _is_numeric_literal(op):
        return op
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
    # OF/IN qualification: FIELD OF GROUP → take field before OF
    if " OF " in upper or " IN " in upper:
        field = op.split()[0]
        return f"self.data.{_to_python_name(field)}.value"
    # Default data name
    return f"self.data.{_to_python_name(op)}.value"
