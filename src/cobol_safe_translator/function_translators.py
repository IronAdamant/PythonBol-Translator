"""COBOL FUNCTION intrinsic translators for COMPUTE expressions.

Extracted from statement_translators.py to comply with the 500 LOC guideline.
Translates common COBOL intrinsic functions (FUNCTION LENGTH, FUNCTION MAX,
etc.) into Python equivalents within COMPUTE expressions.
"""

from __future__ import annotations

from typing import Callable


# No-arg intrinsics (FUNCTION CURRENT-DATE, FUNCTION WHEN-COMPILED)
_FUNCTION_INTRINSICS_0: dict[str, str] = {
    "CURRENT-DATE": "datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:21]",
    "WHEN-COMPILED": "'compile_timestamp'",
}

# Single-arg intrinsics: template uses {0} for the resolved argument
_FUNCTION_INTRINSICS_1: dict[str, str] = {
    "LENGTH": "len(str({0}))",
    "NUMVAL": "float({0})",
    "NUMVAL-C": "float(str({0}).replace(',','').replace('$','').strip())",
    "UPPER-CASE": "str({0}).upper()",
    "LOWER-CASE": "str({0}).lower()",
    "REVERSE": "str({0})[::-1]",
    "TRIM": "str({0}).strip()",
    "INTEGER": "int({0})",
    "INTEGER-PART": "int({0})",
    "ORD": "ord({0})",
    "CHAR": "chr({0})",
    "ABS": "abs({0})",
    "SQRT": "{0} ** 0.5",
}

# Two-arg intrinsics: template uses {0} and {1} for resolved arguments
_FUNCTION_INTRINSICS_2: dict[str, str] = {
    "MOD": "{0} % {1}",
}

# Variadic intrinsics: template uses {args} for comma-separated resolved args
_FUNCTION_INTRINSICS_VAR: dict[str, str] = {
    "MAX": "max({args})",
    "MIN": "min({args})",
}


def translate_function_intrinsic(
    func_name: str,
    raw_args: str,
    resolve: Callable[[str], str],
) -> str | None:
    """Translate a COBOL FUNCTION intrinsic to a Python expression.

    Args:
        func_name: The COBOL function name (e.g. "LENGTH", "MAX").
        raw_args: The raw argument string from inside parentheses,
                  space-separated. Empty string for no-arg functions.
        resolve: The operand resolver callback.

    Returns:
        Python expression string, or None if the function is unknown.
    """
    upper_name = func_name.upper()

    # Handle TRIM with LEADING/TRAILING modifiers
    if upper_name == "TRIM" and raw_args:
        parts = raw_args.split()
        if len(parts) >= 2:
            modifier = parts[-1].upper()
            field_parts = parts[:-1]
            if modifier == "LEADING":
                arg = resolve(field_parts[0])
                return f"str({arg}).lstrip()"
            if modifier == "TRAILING":
                arg = resolve(field_parts[0])
                return f"str({arg}).rstrip()"

    # No-arg intrinsics
    if upper_name in _FUNCTION_INTRINSICS_0:
        return _FUNCTION_INTRINSICS_0[upper_name]

    # Single-arg intrinsics
    if upper_name in _FUNCTION_INTRINSICS_1:
        if not raw_args:
            return None
        arg = resolve(raw_args.split()[0])
        return _FUNCTION_INTRINSICS_1[upper_name].format(arg)

    # Two-arg intrinsics
    if upper_name in _FUNCTION_INTRINSICS_2:
        parts = raw_args.split()
        if len(parts) < 2:
            return None
        a = resolve(parts[0])
        b = resolve(parts[1])
        return _FUNCTION_INTRINSICS_2[upper_name].format(a, b)

    # Variadic intrinsics
    if upper_name in _FUNCTION_INTRINSICS_VAR:
        parts = raw_args.split()
        if not parts:
            return None
        resolved_args = ", ".join(resolve(p) for p in parts)
        return _FUNCTION_INTRINSICS_VAR[upper_name].format(args=resolved_args)

    return None
