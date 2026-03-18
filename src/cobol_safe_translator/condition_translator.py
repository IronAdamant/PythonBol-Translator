"""Two-pass COBOL condition translator (tokenize then translate).

Handles: basic comparisons, compound (AND/OR), negation, class conditions
(NUMERIC/ALPHABETIC), sign conditions (POSITIVE/NEGATIVE/ZERO), 88-level
condition names, implied subjects, abbreviated combined relations,
figurative constants, reference modification, parenthesized groups,
and quoted string literals.

Pipeline position: Called by mapper.py._translate_condition()
"""

from __future__ import annotations

import re

from .utils import FIGURATIVE_RESOLVE, _is_numeric_literal, _to_python_name

_CMP_OPS = frozenset({">", "<", "==", "!=", ">=", "<="})
_SIGN_WORDS = {"POSITIVE": "> 0", "NEGATIVE": "< 0", "ZERO": "== 0"}

# Multi-word comparison phrases (longest first for greedy matching)
_CMP_PHRASES: list[tuple[list[str], str]] = [
    (["NOT", "GREATER", "THAN", "OR", "EQUAL", "TO"], "<"),
    (["NOT", "LESS", "THAN", "OR", "EQUAL", "TO"], ">"),
    (["GREATER", "THAN", "OR", "EQUAL", "TO"], ">="),
    (["LESS", "THAN", "OR", "EQUAL", "TO"], "<="),
    (["NOT", "GREATER", "THAN"], "<="),
    (["NOT", "LESS", "THAN"], ">="),
    (["NOT", "EQUAL", "TO"], "!="),
    (["NOT", "EQUAL"], "!="),
    (["NOT", "GREATER"], "<="),
    (["NOT", "LESS"], ">="),
    (["GREATER", "THAN"], ">"),
    (["LESS", "THAN"], "<"),
    (["EQUAL", "TO"], "=="),
    (["NOT", ">"], "<="),
    (["NOT", "<"], ">="),
    (["NOT", "="], "!="),
]

_COBOL_KEYWORDS = frozenset({
    'AND', 'OR', 'NOT', 'IS', 'THAN', 'TO', 'GREATER', 'LESS',
    'EQUAL', 'NUMERIC', 'ALPHABETIC', 'POSITIVE', 'NEGATIVE',
    'ZERO', 'ZEROS', 'ZEROES', 'SPACE', 'SPACES',
    'HIGH-VALUE', 'HIGH-VALUES', 'LOW-VALUE', 'LOW-VALUES',
    'OF', 'IN',
})

_OP_KEYWORDS = frozenset({
    'AND', 'OR', 'NOT', '(', ')', 'NUMERIC', 'ALPHABETIC', 'POSITIVE', 'NEGATIVE',
})


def _is_quoted(tok: str) -> bool:
    return tok[:1] in ('"', "'")


def _upper(tok: str) -> str:
    return tok if _is_quoted(tok) else tok.upper()


def tokenize_condition(cond: str) -> list[str]:
    """Pass 1: Extract tokens preserving quoted strings and ref-mod parens."""
    tokens: list[str] = []
    i, n = 0, len(cond)
    while i < n:
        ch = cond[i]
        if ch in (' ', '\t'):
            i += 1
        elif ch in ('"', "'"):
            j = cond.index(ch, i + 1) + 1
            tokens.append(cond[i:j])
            i = j
        elif ch == '(':
            if tokens and _upper(tokens[-1]) not in ('AND', 'OR', 'NOT', '(', ')', *_CMP_OPS):
                depth, j = 1, i + 1
                while j < n and depth > 0:
                    depth += 1 if cond[j] == '(' else (-1 if cond[j] == ')' else 0)
                    j += 1
                tokens[-1] += cond[i:j]
                i = j
            else:
                tokens.append('(')
                i += 1
        elif ch == ')':
            tokens.append(')')
            i += 1
        elif ch == '=':
            tokens.append('=')
            i += 1
        elif ch in ('>', '<'):
            if i + 1 < n and cond[i + 1] == '=':
                tokens.append(ch + '=')
                i += 2
            else:
                tokens.append(ch)
                i += 1
        else:
            j = i
            while j < n and cond[j] not in (' ', '\t', '(', ')', '=', '>', '<', '"', "'"):
                j += 1
            tokens.append(cond[i:j])
            i = j
    return tokens


def resolve_operand(tok: str) -> str:
    """Resolve a single operand token to a Python expression."""
    if _is_quoted(tok):
        return tok
    if _is_numeric_literal(tok):
        return tok
    upper = tok.upper()
    if upper in FIGURATIVE_RESOLVE:
        return FIGURATIVE_RESOLVE[upper]
    rm = re.match(r'^([A-Za-z][\w-]*)\((\d+):(\d+)\)$', tok)
    if rm:
        name, start, length = rm.group(1), int(rm.group(2)), int(rm.group(3))
        py = _to_python_name(name)
        return f"str(self.data.{py}.value)[{start - 1}:{start - 1 + length}]"
    return f"self.data.{_to_python_name(tok)}.value"


def translate_condition(cond: str, condition_lookup: dict[str, tuple[str, str]]) -> str:
    """Two-pass COBOL condition to Python expression translator.

    On unrecoverable parse failure returns "True".
    """
    try:
        return _translate_inner(cond.strip(), condition_lookup)
    except Exception:
        return "True"


def _try_phrase(tokens: list[str], i: int, n: int) -> tuple[str, int] | None:
    """Try to match a multi-word comparison phrase at position i."""
    for phrase, op in _CMP_PHRASES:
        plen = len(phrase)
        if i + plen <= n and [_upper(tokens[j]) for j in range(i, i + plen)] == phrase:
            return op, i + plen
    return None


def _handle_not(tokens: list[str], i: int, n: int, result: list[str],
                condition_lookup: dict[str, tuple[str, str]]) -> int:
    """Handle NOT token: class conditions, 88-level negation, or standalone not."""
    if i + 1 < n:
        nxt = _upper(tokens[i + 1])
        if nxt == 'NUMERIC':
            subj = result.pop() if result else "True"
            result.append(f"not str({subj}).replace('.','').replace('-','').isdigit()")
            return i + 2
        if nxt == 'ALPHABETIC':
            subj = result.pop() if result else "True"
            result.append(f"not str({subj}).isalpha()")
            return i + 2
        if nxt in condition_lookup:
            parent, val = condition_lookup[nxt]
            if val.startswith('(') and ',' in val:
                lo, hi = val.strip('()').split(', ', 1)
                result.append(f"not ({lo} <= self.data.{parent}.value <= {hi})")
            else:
                result.append(f"not (self.data.{parent}.value == {val})")
            return i + 2
    result.append("not")
    return i + 1


def _handle_conjunction(tokens: list[str], i: int, n: int, result: list[str],
                         last_subject: str, last_op: str,
                         condition_lookup: dict[str, tuple[str, str]]) -> int:
    """Handle AND/OR with implied subjects and abbreviated relations."""
    if i >= n:
        return i
    next_upper = _upper(tokens[i])

    # NOT starts a new sub-expression — never insert implied subject before it
    if next_upper == 'NOT':
        return i

    # Abbreviated: AND/OR followed by comparison op (no left operand)
    if next_upper in ('>', '<', '=', '>=', '<=', 'GREATER', 'LESS', 'EQUAL', 'NOT'):
        if last_subject:
            result.append(last_subject)
    else:
        # Implied subject: value without operator follows AND/OR
        is_value = (next_upper not in _OP_KEYWORDS
                    and next_upper not in condition_lookup)
        if is_value and last_subject and last_op:
            has_following_op = False
            if i + 1 < n:
                peek = _upper(tokens[i + 1])
                has_following_op = peek in ('>', '<', '=', '>=', '<=',
                                            'GREATER', 'LESS', 'EQUAL', 'NOT')
            if not has_following_op:
                result.append(last_subject)
                result.append(last_op)
    return i


def _normalize_tokens(raw_tokens: list[str]) -> list[str]:
    """Uppercase keyword tokens, leave others as-is."""
    tokens: list[str] = []
    for t in raw_tokens:
        if _is_quoted(t):
            tokens.append(t)
        elif t.upper() in _COBOL_KEYWORDS or t in ('=', '>', '<', '>=', '<=', '!=', '(', ')'):
            tokens.append(t.upper() if t.upper() in _COBOL_KEYWORDS else t)
        else:
            tokens.append(t)
    return tokens


def _is_lhs_subject(tokens: list[str], i: int, n: int) -> bool:
    """Check if token at i is a left-hand subject (followed by comparison)."""
    if i + 1 >= n:
        return False
    nxt = _upper(tokens[i + 1])
    if nxt in ('>', '<', '=', '>=', '<=', 'GREATER', 'LESS', 'EQUAL',
               'NOT', 'NUMERIC', 'ALPHABETIC', 'POSITIVE', 'NEGATIVE', 'IS'):
        return True
    return any(nxt == p[0] for p, _ in _CMP_PHRASES)


def _translate_inner(cond: str, condition_lookup: dict[str, tuple[str, str]]) -> str:
    """Core translation logic."""
    raw_tokens = tokenize_condition(cond)
    if not raw_tokens:
        return "True"
    tokens = _normalize_tokens(raw_tokens)
    result: list[str] = []
    last_subject = ""
    last_op = ""
    i, n = 0, len(tokens)
    while i < n:
        t = _upper(tokens[i])
        # Multi-word comparison phrases
        phrase_match = _try_phrase(tokens, i, n)
        if phrase_match:
            op, i = phrase_match
            result.append(op)
            last_op = op
            continue
        if t in ('(', ')'):
            result.append(t)
            i += 1
            continue
        if t in ('IS', 'THEN'):
            i += 1
            continue
        if t in ('OF', 'IN'):
            # COBOL qualification: FIELD OF GROUP — skip OF and the group name
            i += 2  # skip OF/IN + group-name
            continue
        if t == 'FUNCTION':
            # COBOL intrinsic function: FUNCTION NUMVAL(x) etc.
            # Can't translate — use 0 as placeholder
            if i + 1 < n:
                i += 2  # skip FUNCTION + function-name
            else:
                i += 1
            result.append("0")
            continue
        if t == 'NOT':
            i = _handle_not(tokens, i, n, result, condition_lookup)
            continue
        if t == 'NUMERIC':
            subj = result.pop() if result else "True"
            result.append(f"str({subj}).replace('.','').replace('-','').isdigit()")
            i += 1
            continue
        if t == 'ALPHABETIC':
            subj = result.pop() if result else "True"
            result.append(f"str({subj}).isalpha()")
            i += 1
            continue
        if t in _SIGN_WORDS and result:
            prev = result[-1]
            if prev not in ('and', 'or', 'not', '(', *_CMP_OPS):
                result.append(_SIGN_WORDS[t])
                i += 1
                continue
        if t in ('AND', 'OR'):
            result.append(t.lower())
            i += 1
            i = _handle_conjunction(tokens, i, n, result, last_subject, last_op,
                                     condition_lookup)
            continue
        if t in ('>', '<', '>=', '<='):
            result.append(t)
            last_op = t
            i += 1
            continue
        if t == '=':
            result.append('==')
            last_op = '=='
            i += 1
            continue
        if t == 'EQUAL':
            result.append('==')
            last_op = '=='
            i += 1
            continue
        if t == 'GREATER':
            result.append('>')
            last_op = '>'
            i += 1
            continue
        if t == 'LESS':
            result.append('<')
            last_op = '<'
            i += 1
            continue
        if t in condition_lookup:
            parent, val = condition_lookup[t]
            if val.startswith('(') and ',' in val:
                lo, hi = val.strip('()').split(', ', 1)
                result.append(f"({lo} <= self.data.{parent}.value <= {hi})")
            else:
                result.append(f"self.data.{parent}.value == {val}")
            i += 1
            continue
        # Regular operand
        resolved = resolve_operand(tokens[i])
        if _is_lhs_subject(tokens, i, n):
            last_subject = resolved
        result.append(resolved)
        i += 1
    # Post-process: wrap "not X op Y" into "not (X op Y)"
    fixed: list[str] = []
    j = 0
    while j < len(result):
        if (result[j] == "not" and j + 3 < len(result)
                and result[j + 2] in _CMP_OPS and result[j + 1] != '('):
            fixed.extend(["not", "(", result[j + 1], result[j + 2], result[j + 3], ")"])
            j += 4
        else:
            fixed.append(result[j])
            j += 1
    joined = " ".join(fixed)
    if joined.count("(") != joined.count(")"):
        return "True"
    return joined if joined else "True"
