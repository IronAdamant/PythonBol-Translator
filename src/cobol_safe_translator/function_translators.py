"""COBOL FUNCTION intrinsic translators for COMPUTE expressions.

Extracted from statement_translators.py to comply with the 500 LOC guideline.
Translates common COBOL intrinsic functions (FUNCTION LENGTH, FUNCTION MAX,
etc.) into Python equivalents within COMPUTE expressions.

Handles expression arguments (arithmetic, nested parens, commas) and
nested FUNCTION calls within arguments.
"""

from __future__ import annotations

from collections.abc import Callable

from .utils import _is_numeric_literal


# No-arg intrinsics (FUNCTION CURRENT-DATE, FUNCTION WHEN-COMPILED)
_FUNCTION_INTRINSICS_0: dict[str, str] = {
    "CURRENT-DATE": "datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:21]",
    "WHEN-COMPILED": "'compile_timestamp'",
    "RANDOM": "__import__('random').random()",
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
    "SQRT": "({0}) ** 0.5",
    "LOG": "__import__('math').log({0})",
    "LOG10": "__import__('math').log10({0})",
    "SIN": "__import__('math').sin({0})",
    "COS": "__import__('math').cos({0})",
    "TAN": "__import__('math').tan({0})",
    "ASIN": "__import__('math').asin({0})",
    "ACOS": "__import__('math').acos({0})",
    "ATAN": "__import__('math').atan({0})",
    "EXP": "__import__('math').exp({0})",
    "FACTORIAL": "__import__('math').factorial(int({0}))",
}

# Two-arg intrinsics: template uses {0} and {1} for resolved arguments
_FUNCTION_INTRINSICS_2: dict[str, str] = {
    "MOD": "({0}) % ({1})",
    "REM": "({0}) % ({1})",
    "ANNUITY": "({0}) / (1 - (1 + {0}) ** (-{1}))",
}

# Variadic intrinsics: template uses {args} for comma-separated resolved args
_FUNCTION_INTRINSICS_VAR: dict[str, str] = {
    "MAX": "max({args})",
    "MIN": "min({args})",
    "SUM": "sum([{args}])",
    "MEAN": "sum([{args}]) / {count}",
    "MEDIAN": "__import__('statistics').median([{args}])",
    "RANGE": "max({args}) - min({args})",
    "VARIANCE": "__import__('statistics').variance([{args}])",
    "STANDARD-DEVIATION": "__import__('statistics').stdev([{args}])",
    "PRESENT-VALUE": "sum(_v / (1 + {a0}) ** _i for _i, _v in enumerate([{rest}], 1))",
}

_EXPR_OPERATORS = frozenset({'+', '-', '*', '/', '**', '(', ')'})


def _split_args_by_comma(raw_args: str) -> list[str] | None:
    """Split function arguments by comma at top-level paren depth.

    Respects quoted strings — commas inside "..." or '...' are not delimiters.
    Returns None if no commas are present outside quotes (space-separated args).
    """
    if ',' not in raw_args:
        return None
    args: list[str] = []
    current: list[str] = []
    depth = 0
    in_quote: str | None = None
    for ch in raw_args:
        if in_quote:
            current.append(ch)
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            in_quote = ch
            current.append(ch)
        elif ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    remainder = ''.join(current).strip()
    if remainder:
        args.append(remainder)
    # If all commas were inside quotes, treat as no-comma (single arg)
    if len(args) <= 1:
        return None
    return args


def _has_operators(raw: str) -> bool:
    """Check if a raw arg string contains arithmetic operators."""
    tokens = raw.split()
    return any(t in _EXPR_OPERATORS and t not in ('(', ')') for t in tokens)


def _tokenize_expr(expr: str) -> list[str]:
    """Tokenize a COBOL expression at character level.

    Splits operators (+, -, *, /, **) and standalone parens from identifiers
    while keeping subscripts like IND(M) and ref-mods like WS-F(1:3) intact.
    """
    tokens: list[str] = []
    current = ""
    paren_depth = 0
    in_quote: str | None = None

    for ch in expr:
        # Handle quoted strings
        if in_quote:
            current += ch
            if ch == in_quote:
                in_quote = None
            continue
        if ch in ('"', "'"):
            if current and paren_depth == 0:
                tokens.append(current)
                current = ""
            in_quote = ch
            current += ch
            continue
        if ch in (' ', '\t', ','):
            if paren_depth > 0:
                current += ch
            else:
                if current:
                    tokens.append(current)
                    current = ""
        elif ch == '(':
            if current and (current[-1].isalnum() or current[-1] in ('-', '_')):
                # Subscript/ref-mod: IND(M), WS-F(1:3)
                current += ch
                paren_depth += 1
            elif paren_depth > 0:
                current += ch
                paren_depth += 1
            else:
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append('(')
        elif ch == ')':
            if paren_depth > 0:
                current += ch
                paren_depth -= 1
            else:
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(')')
        elif ch in ('+', '*', '/') and paren_depth == 0:
            if current:
                tokens.append(current)
                current = ""
            tokens.append(ch)
        elif ch == '-' and paren_depth == 0:
            # Hyphen in name (A-B) vs subtraction operator (A - B)
            if current and (current[-1].isalpha() or current[-1] == '-'):
                current += ch  # part of COBOL name
            else:
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(ch)
        else:
            current += ch

    if current:
        tokens.append(current)
    return tokens


def _resolve_expr(expr: str, resolve: Callable[[str], str]) -> str:
    """Resolve a COBOL expression to Python, handling operators and nested FUNCTIONs.

    Walks tokens left-to-right:
    - Operators and parens pass through
    - FUNCTION keyword triggers recursive intrinsic translation
    - Numeric literals pass through
    - Everything else is resolved as a data name
    """
    tokens = _tokenize_expr(expr)
    if not tokens:
        return '0'
    result: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        upper = tok.upper()

        if tok in _EXPR_OPERATORS:
            result.append(tok)
            i += 1
        elif upper in ('OF', 'IN') and i + 1 < len(tokens):
            # OF/IN qualification: skip qualifier and group name
            i += 2
        elif upper == 'FUNCTION' and i + 1 < len(tokens):
            # Nested FUNCTION call
            func_name = tokens[i + 1]
            if i + 2 < len(tokens) and tokens[i + 2] == '(':
                # Space-separated parens: collect until matching )
                arg_parts: list[str] = []
                j = i + 3
                depth = 1
                while j < len(tokens) and depth > 0:
                    if tokens[j] == '(':
                        depth += 1
                    elif tokens[j] == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    arg_parts.append(tokens[j])
                    j += 1
                nested_args = ' '.join(arg_parts)
                translated = translate_function_intrinsic(
                    func_name, nested_args, resolve
                )
                result.append(translated if translated is not None else '0')
                i = j + 1
            else:
                # No-arg function
                translated = translate_function_intrinsic(func_name, '', resolve)
                result.append(translated if translated is not None else '0')
                i += 2
        elif _is_numeric_literal(tok):
            result.append(tok)
            i += 1
        elif tok.startswith('"') or tok.startswith("'"):
            result.append(tok)
            i += 1
        else:
            result.append(resolve(tok))
            i += 1

    return ' '.join(result) if result else '0'


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
            if modifier == "LEADING":
                arg = _resolve_expr(' '.join(parts[:-1]), resolve)
                return f"str({arg}).lstrip()"
            if modifier == "TRAILING":
                arg = _resolve_expr(' '.join(parts[:-1]), resolve)
                return f"str({arg}).rstrip()"

    # No-arg intrinsics
    if upper_name in _FUNCTION_INTRINSICS_0:
        return _FUNCTION_INTRINSICS_0[upper_name]

    # Try comma-separated args first
    comma_args = _split_args_by_comma(raw_args)

    # Single-arg intrinsics
    if upper_name in _FUNCTION_INTRINSICS_1:
        if not raw_args:
            return None
        # Entire raw_args is one expression (ignore commas for single-arg)
        arg = _resolve_expr(raw_args if comma_args is None else comma_args[0], resolve)
        return _FUNCTION_INTRINSICS_1[upper_name].format(arg)

    # Two-arg intrinsics
    if upper_name in _FUNCTION_INTRINSICS_2:
        if comma_args and len(comma_args) >= 2:
            a = _resolve_expr(comma_args[0], resolve)
            b = _resolve_expr(comma_args[1], resolve)
        else:
            # Space-separated — try simple two-token split (no operators)
            parts = raw_args.split()
            if len(parts) < 2:
                return None
            if not _has_operators(raw_args):
                a = resolve(parts[0])
                b = resolve(parts[1])
            else:
                # Has operators but no commas — can't split reliably
                return None
        return _FUNCTION_INTRINSICS_2[upper_name].format(a, b)

    # Variadic intrinsics
    if upper_name in _FUNCTION_INTRINSICS_VAR:
        if comma_args:
            resolved_parts = [_resolve_expr(a, resolve) for a in comma_args]
        else:
            parts = raw_args.split()
            if not parts:
                return None
            if _has_operators(raw_args):
                # Treat entire expression as single arg
                resolved_parts = [_resolve_expr(raw_args, resolve)]
            else:
                resolved_parts = [resolve(p) for p in parts]
        resolved_str = ", ".join(resolved_parts)
        template = _FUNCTION_INTRINSICS_VAR[upper_name]
        # Handle special templates with {a0}, {rest}, {count}
        if '{count}' in template:
            return template.format(args=resolved_str, count=len(resolved_parts))
        if '{a0}' in template and '{rest}' in template and len(resolved_parts) >= 2:
            rest_str = ", ".join(resolved_parts[1:])
            return template.format(
                a0=resolved_parts[0],
                rest=rest_str,
                args=resolved_str,
            )
        return template.format(args=resolved_str)

    return None
