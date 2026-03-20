"""Shared utility functions for the COBOL-to-Python translator.

Centralises helpers that are needed by multiple modules (mapper,
statement_translators, block_translator) to avoid circular imports
and code duplication.
"""

from __future__ import annotations

import keyword
import re

# Module-level registry: (COBOL_FIELD_UPPER, PARENT_GROUP_UPPER) → python_name
# Set by mapper_codegen during code generation for OF/IN qualification resolution.
_qualified_field_map: dict[tuple[str, str], str] = {}

# Reverse lookup: COBOL_FIELD_UPPER → list of qualified python names
# Built from _qualified_field_map; allows resolving unqualified colliding names.
_collision_reverse_map: dict[str, list[str]] = {}


def coalesce_qualified(ops: list[str]) -> list[str]:
    """Merge OF/IN qualified names into single operands.

    Converts ['WS-NAME', 'OF', 'WS-GROUP-A', 'TO', 'WS-B']
    into     ['WS-NAME OF WS-GROUP-A', 'TO', 'WS-B'].
    Supports multi-level: ['F', 'OF', 'G1', 'OF', 'G2'] → ['F OF G1 OF G2'].
    """
    if not ops:
        return ops
    result: list[str] = []
    i = 0
    while i < len(ops):
        token = ops[i]
        # Check if next token is OF/IN — coalesce into qualified name
        if (i + 2 < len(ops)
                and ops[i + 1].upper() in ("OF", "IN")
                and token.upper() not in ("TO", "FROM", "BY", "GIVING",
                    "INTO", "UNTIL", "DEPENDING", "ON", "REPLACING",
                    "TALLYING", "DELIMITED", "CORRESPONDING", "CORR")):
            parts = [token, ops[i + 1], ops[i + 2]]
            i += 3
            # Continue coalescing chained OF/IN
            while (i + 1 < len(ops)
                   and ops[i].upper() in ("OF", "IN")):
                parts.append(ops[i])
                if i + 1 < len(ops):
                    parts.append(ops[i + 1])
                    i += 2
                else:
                    break
            result.append(" ".join(parts))
        else:
            result.append(token)
            i += 1
    return result


def _indent_line(line: str, indent: int) -> str:
    """Indent a line by *indent* levels (4 spaces each)."""
    return ("    " * indent) + line


def _has_code(body: list[str]) -> bool:
    """Check if body has any non-comment executable lines."""
    return any(ln.strip() and not ln.strip().startswith("#") for ln in body)


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
        left, right = parts
        return (not left or left.isdigit()) and (not right or right.isdigit()) and bool(left or right)
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

# Numeric-context figurative constants (for data item initial values)
_FIGURATIVE_NUMERIC: dict[str, str] = {
    "ZERO": "0", "ZEROS": "0", "ZEROES": "0",
    "SPACE": "", "SPACES": "",
    "HIGH-VALUE": "0", "HIGH-VALUES": "0",
    "LOW-VALUE": "0", "LOW-VALUES": "0",
}


def resolve_figurative(value: str, numeric: bool = True) -> str:
    """Translate COBOL figurative constants to Python values.

    When numeric=True (data init context), SPACE→"", HIGH/LOW-VALUE→"0".
    When numeric=False (string context), uses the string representations.
    """
    upper = value.strip().upper()
    if numeric:
        result = _FIGURATIVE_NUMERIC.get(upper)
        if result is not None:
            return result
    else:
        result = FIGURATIVE_RESOLVE.get(upper)
        if result is not None:
            # Strip surrounding quotes for direct value use
            return result.strip("'")
    return value

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
    # OF/IN qualification: FIELD OF GROUP → resolve via qualified map if available
    if " OF " in upper or " IN " in upper:
        return f"self.data.{_resolve_qualified(op)}.value"
    # Default data name — check collision reverse map for disambiguation
    py = _to_python_name(op)
    variants = _collision_reverse_map.get(upper)
    if variants:
        # Colliding name used without OF/IN — pick the first qualified variant
        return f"self.data.{variants[0]}.value"
    return f"self.data.{py}.value"


def extract_from_expr(ops: list[str], upper_ops: list[str]) -> str | None:
    """Extract FROM clause value as a Python expression, or None if absent."""
    if "FROM" in upper_ops:
        idx = upper_ops.index("FROM")
        if idx + 1 < len(ops):
            return f"self.data.{_to_python_name(ops[idx + 1])}.value"
    return None


def _resolve_qualified(op: str) -> str:
    """Resolve OF/IN qualified COBOL name to a Python field name.

    Supports multi-level qualification: FIELD OF GROUP-1 OF GROUP-2.
    Tries each group name in the chain against the qualified field map.
    """
    parts = op.split()
    field_name = parts[0].upper()
    # Collect all group names in the qualification chain
    group_names: list[str] = []
    for j, p in enumerate(parts):
        if p.upper() in ("OF", "IN") and j + 1 < len(parts):
            group_names.append(parts[j + 1].upper())
    # Try each group name — most specific (immediate parent) first
    for group_name in group_names:
        qualified = _qualified_field_map.get((field_name, group_name))
        if qualified:
            return qualified
    return _to_python_name(parts[0])


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
        return f"self.data.{_resolve_qualified(op)}"
    # Check collision reverse map for unqualified colliding names
    upper = op.upper()
    variants = _collision_reverse_map.get(upper)
    if variants:
        return f"self.data.{variants[0]}"
    return f"self.data.{_to_python_name(op)}"
