"""Two-pass COBOL condition translator (tokenize then translate).

Handles: basic comparisons, compound (AND/OR), negation, class conditions
(NUMERIC/ALPHABETIC), sign conditions (POSITIVE/NEGATIVE/ZERO), 88-level
condition names, implied subjects, abbreviated combined relations,
figurative constants, reference modification, parenthesized groups,
and quoted string literals.

Pipeline position: Called by mapper.py._translate_condition()
"""

from __future__ import annotations

from .function_translators import translate_function_intrinsic
from .utils import resolve_operand

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

_ARITH_OPS = frozenset({'+', '-', '*', '/'})

# Tokens that precede a '(' and indicate it's NOT a reference-modification paren
_NON_REFMOD_TOKENS = frozenset({'AND', 'OR', 'NOT', '(', ')'}) | _CMP_OPS

# Combined set for sign-word subject exclusion check
_NON_SUBJECT_TOKENS = frozenset({'and', 'or', 'not', '('}) | _CMP_OPS

_OP_KEYWORDS = frozenset({
    'AND', 'OR', 'NOT', '(', ')', 'NUMERIC', 'ALPHABETIC', 'POSITIVE', 'NEGATIVE',
})

# Single-token comparison operators → Python equivalents
_SINGLE_OPS: dict[str, str] = {
    '=': '==', 'EQUAL': '==', 'GREATER': '>', 'LESS': '<',
    '>': '>', '<': '<', '>=': '>=', '<=': '<=',
}


def _is_quoted(tok: str) -> bool:
    return tok[:1] in ('"', "'")


def _upper(tok: str) -> str:
    return tok if _is_quoted(tok) else tok.upper()


def _numeric_check_expr(subj: str, negate: bool = False) -> str:
    """Generate a Python NUMERIC class condition expression."""
    expr = f"str({subj}).replace('.','').replace('-','').isdigit()"
    return f"not {expr}" if negate else expr


def _condition_88_expr(parent: str, val: str, negate: bool = False) -> str:
    """Generate a Python expression for an 88-level condition lookup."""
    if val.startswith('(') and ',' in val:
        lo, hi = val.strip('()').split(', ', 1)
        expr = f"({lo} <= self.data.{parent}.value <= {hi})"
    else:
        expr = f"self.data.{parent}.value == {val}"
    return f"not ({expr})" if negate else expr


def tokenize_condition(cond: str) -> list[str]:
    """Pass 1: Extract tokens preserving quoted strings and ref-mod parens."""
    tokens: list[str] = []
    i, n = 0, len(cond)
    while i < n:
        ch = cond[i]
        if ch in (' ', '\t'):
            i += 1
        elif ch in ('"', "'"):
            j = cond.find(ch, i + 1)
            if j == -1:
                tokens.append(cond[i:])
                break
            j += 1
            tokens.append(cond[i:j])
            # Merge hex/binary/national prefix: X"FF" → X"FF", H'0F' → H'0F'
            if (len(tokens) >= 2 and len(tokens[-2]) == 1
                    and tokens[-2].upper() in ('X', 'B', 'Z', 'N', 'H')):
                tokens[-2:] = [tokens[-2] + tokens[-1]]
            i = j
        elif ch == '(':
            if tokens and _upper(tokens[-1]) not in _NON_REFMOD_TOKENS:
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
        elif ch in ('+', '*', '/'):
            # Arithmetic operators in conditions (e.g., "X + Y > Z")
            tokens.append(ch)
            i += 1
        elif ch == '-':
            # Minus as operator vs hyphen in COBOL names
            # If preceded by a word-ending char and followed by space or operator, it's subtraction
            if i > 0 and (cond[i - 1] in (' ', '\t', ')') or cond[i - 1].isdigit()):
                tokens.append(ch)
                i += 1
            else:
                # Part of a COBOL hyphenated name — fall through to word collection
                j = i
                while j < n and cond[j] not in (' ', '\t', '(', ')', '=', '>', '<', '"', "'", '+', '*', '/'):
                    j += 1
                tokens.append(cond[i:j])
                i = j
        else:
            j = i
            while j < n and cond[j] not in (' ', '\t', '(', ')', '=', '>', '<', '"', "'", '+', '*', '/'):
                j += 1
            tokens.append(cond[i:j])
            i = j
    return tokens


def translate_condition(cond: str, condition_lookup: dict[str, tuple[str, str]]) -> str:
    """Two-pass COBOL condition to Python expression translator.

    On unrecoverable parse failure returns "True".
    """
    try:
        return _translate_inner(cond.strip(), condition_lookup)
    except (ValueError, IndexError, KeyError):
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
            result.append(_numeric_check_expr(subj, negate=True))
            return i + 2
        if nxt == 'ALPHABETIC':
            subj = result.pop() if result else "True"
            result.append(f"not str({subj}).isalpha()")
            return i + 2
        if nxt == 'ALPHABETIC-UPPER':
            subj = result.pop() if result else "True"
            result.append(f"not (str({subj}).isupper() and str({subj}).isalpha())")
            return i + 2
        if nxt == 'ALPHABETIC-LOWER':
            subj = result.pop() if result else "True"
            result.append(f"not (str({subj}).islower() and str({subj}).isalpha())")
            return i + 2
        if nxt in condition_lookup:
            parent, val = condition_lookup[nxt]
            result.append(_condition_88_expr(parent, val, negate=True))
            return i + 2
        # NOT followed by a value (no operator) → implied NOT EQUAL
        # e.g., "IF X NOT 0" means "IF X NOT = 0"
        # But only when there IS a preceding subject (result has a data reference).
        # If NOT is at the start or after AND/OR, it's negating a condition name.
        # Also, NOT before a subject with a comparison after it is standalone NOT.
        if (nxt not in ('>', '<', '=', '>=', '<=', 'GREATER', 'LESS', 'EQUAL',
                         'AND', 'OR', '(', ')')
                and nxt not in _SIGN_WORDS and nxt not in _OP_KEYWORDS):
            # Check there's a preceding subject (not at start, not after and/or)
            has_subject = (result and result[-1] not in ('and', 'or', 'not', '('))
            # Check if the token AFTER the value is a comparison → standalone NOT
            peek_after_val = _upper(tokens[i + 2]) if i + 2 < n else ''
            is_followed_by_cmp = peek_after_val in ('>', '<', '=', '>=', '<=',
                                                      'GREATER', 'LESS', 'EQUAL',
                                                      'NOT', '+', '-', '*', '/')
            if has_subject and not is_followed_by_cmp:
                result.append("!=")
                return i + 1  # consume NOT, leave value for next iteration
    result.append("not")
    return i + 1


def _handle_conjunction(tokens: list[str], i: int, n: int, result: list[str],
                         last_subject: str, last_op: str,
                         condition_lookup: dict[str, tuple[str, str]]) -> int:
    """Handle AND/OR with implied subjects and abbreviated relations."""
    if i >= n:
        return i
    next_upper = _upper(tokens[i])

    # NOT: check if followed by comparison op → abbreviated relation
    # e.g., "AND NOT = 'X'" needs implied subject inserted before NOT
    if next_upper == 'NOT':
        if i + 1 < n:
            peek = _upper(tokens[i + 1])
            if peek in ('>', '<', '=', '>=', '<=', 'GREATER', 'LESS', 'EQUAL'):
                if last_subject:
                    result.append(last_subject)
        return i

    # Abbreviated: AND/OR followed by comparison op (no left operand)
    if next_upper in ('>', '<', '=', '>=', '<=', 'GREATER', 'LESS', 'EQUAL'):
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
    tokens = tokenize_condition(cond)
    if not tokens:
        return "True"
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
            if i + 1 < n:
                func_token = tokens[i + 1]
                paren_pos = func_token.find('(')
                consumed = 2
                if paren_pos >= 0:
                    func_name = func_token[:paren_pos]
                    raw_inner = func_token[paren_pos + 1:]
                    if raw_inner.endswith(')'):
                        raw_inner = raw_inner[:-1]
                    raw_args = raw_inner.strip()
                else:
                    func_name = func_token
                    raw_args = ''
                    if i + 2 < n and tokens[i + 2] == '(':
                        arg_parts: list[str] = []
                        j = i + 3
                        depth = 1
                        while j < n and depth > 0:
                            if tokens[j] == '(':
                                depth += 1
                            elif tokens[j] == ')':
                                depth -= 1
                                if depth == 0:
                                    break
                            arg_parts.append(tokens[j])
                            j += 1
                        raw_args = ' '.join(arg_parts)
                        consumed = j + 1 - i
                translated = translate_function_intrinsic(
                    func_name, raw_args, resolve_operand,
                )
                result.append(translated if translated else '0')
                i += consumed
            else:
                result.append('0')
                i += 1
            continue
        if t == 'NOT':
            i = _handle_not(tokens, i, n, result, condition_lookup)
            continue
        if t == 'NUMERIC':
            subj = result.pop() if result else "True"
            result.append(_numeric_check_expr(subj))
            i += 1
            continue
        if t == 'ALPHABETIC':
            subj = result.pop() if result else "True"
            result.append(f"str({subj}).isalpha()")
            i += 1
            continue
        if t == 'ALPHABETIC-UPPER':
            subj = result.pop() if result else "True"
            result.append(f"(str({subj}).isupper() and str({subj}).isalpha())")
            i += 1
            continue
        if t == 'ALPHABETIC-LOWER':
            subj = result.pop() if result else "True"
            result.append(f"(str({subj}).islower() and str({subj}).isalpha())")
            i += 1
            continue
        if t in _SIGN_WORDS and result:
            prev = result[-1]
            if prev not in _NON_SUBJECT_TOKENS:
                result.append(_SIGN_WORDS[t])
                i += 1
                continue
        if t in ('AND', 'OR'):
            result.append(t.lower())
            i += 1
            i = _handle_conjunction(tokens, i, n, result, last_subject, last_op,
                                     condition_lookup)
            continue
        if t in _SINGLE_OPS:
            op = _SINGLE_OPS[t]
            result.append(op)
            last_op = op
            i += 1
            continue
        if t in _ARITH_OPS:
            result.append(t)
            i += 1
            continue
        if t in condition_lookup:
            parent, val = condition_lookup[t]
            result.append(_condition_88_expr(parent, val))
            i += 1
            continue
        # Regular operand
        resolved = resolve_operand(tokens[i])
        if _is_lhs_subject(tokens, i, n):
            last_subject = resolved
        result.append(resolved)
        i += 1
    fixed = _fix_not_grouping(result)
    joined = " ".join(fixed)
    return _validate_condition(joined)


def _fix_not_grouping(tokens: list[str]) -> list[str]:
    """Wrap 'not X op Y ...' patterns into 'not (X op Y ...)' for correct precedence."""
    fixed: list[str] = []
    j = 0
    while j < len(tokens):
        if tokens[j] == "not" and j + 1 < len(tokens) and tokens[j + 1] == '(':
            # Already parenthesized — pass through
            fixed.append(tokens[j])
            j += 1
        elif (tokens[j] == "not" and j + 3 < len(tokens)
                and tokens[j + 2] in _CMP_OPS):
            # Collect RHS: may be multi-token (e.g., not X == Y and Z)
            fixed.extend(["not", "(", tokens[j + 1], tokens[j + 2]])
            k = j + 3
            # Grab tokens until we hit and/or/end
            while k < len(tokens) and tokens[k] not in ('and', 'or'):
                fixed.append(tokens[k])
                k += 1
            fixed.append(")")
            j = k
        else:
            fixed.append(tokens[j])
            j += 1
    return fixed


def _fix_unbalanced_parens(expr: str) -> str:
    """Auto-fix unbalanced parentheses."""
    opens = expr.count('(')
    closes = expr.count(')')
    if opens > closes:
        expr += ')' * (opens - closes)
    elif closes > opens:
        # Strip trailing orphan close parens
        diff = closes - opens
        while diff > 0 and expr.endswith(')'):
            expr = expr[:-1].rstrip()
            diff -= 1
    return expr


def _fix_double_operators(expr: str) -> str:
    """Deduplicate consecutive identical operators (e.g., '== ==' → '==')."""
    import re
    expr = re.sub(r'(==\s*){2,}', '== ', expr)
    expr = re.sub(r'(!=\s*){2,}', '!= ', expr)
    expr = re.sub(r'\band\s+and\b', 'and', expr)
    expr = re.sub(r'\bor\s+or\b', 'or', expr)
    expr = re.sub(r'\bnot\s+not\b', 'not', expr)
    return expr


def _fix_trailing_operator(expr: str) -> str:
    """Strip dangling operator at end of expression."""
    import re
    return re.sub(r'\s+(==|!=|>=|<=|>|<|and|or|not)\s*$', '', expr)


def _validate_condition(joined: str) -> str:
    """Validate translated condition, attempting auto-fixes on SyntaxError."""
    if not joined:
        return "True"
    if joined == "True":
        return joined

    # First attempt: try as-is
    fixed = _fix_unbalanced_parens(joined)
    try:
        compile(fixed, '<cond>', 'eval')
        return fixed
    except SyntaxError:
        pass

    # Second attempt: fix double operators and trailing operators
    fixed = _fix_double_operators(fixed)
    fixed = _fix_trailing_operator(fixed)
    fixed = _fix_unbalanced_parens(fixed)
    try:
        compile(fixed, '<cond>', 'eval')
        return fixed
    except SyntaxError:
        pass

    # All recovery failed
    return "True  # condition could not be translated"
