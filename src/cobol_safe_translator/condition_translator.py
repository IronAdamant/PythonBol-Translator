"""Recursive descent COBOL condition translator.

Handles: basic comparisons, compound (AND/OR), negation, class conditions
(NUMERIC/ALPHABETIC/ALPHABETIC-UPPER/ALPHABETIC-LOWER), sign conditions
(POSITIVE/NEGATIVE/ZERO), 88-level condition names, implied subjects,
abbreviated combined relations, figurative constants, reference modification,
parenthesized groups, FUNCTION intrinsics, and quoted string literals.

Pipeline position: Called by mapper.py._translate_condition()
"""

from __future__ import annotations

import re

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

# Single-token comparison operators → Python equivalents
_SINGLE_OPS: dict[str, str] = {
    '=': '==', 'EQUAL': '==', 'GREATER': '>', 'LESS': '<',
    '>': '>', '<': '<', '>=': '>=', '<=': '<=',
}

_CLASS_KEYWORDS = frozenset({'NUMERIC', 'ALPHABETIC', 'ALPHABETIC-UPPER', 'ALPHABETIC-LOWER'})


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


def _negate_op(op: str) -> str:
    """Negate a comparison operator."""
    return {'>': '<=', '<': '>=', '==': '!=', '!=': '==',
            '>=': '<', '<=': '>'}.get(op, '!=')


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
            tokens.append(ch)
            i += 1
        elif ch == '-':
            if i > 0 and (cond[i - 1] in (' ', '\t', ')') or cond[i - 1].isdigit()):
                tokens.append(ch)
                i += 1
            else:
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
    """Translate COBOL condition to Python expression.

    On unrecoverable parse failure returns "True".
    """
    try:
        tokens = tokenize_condition(cond.strip())
        if not tokens:
            return "True"
        parser = _CondParser(tokens, condition_lookup)
        result = parser.parse()
        return _validate_condition(result)
    except (ValueError, IndexError, KeyError):
        return "True"


# ---------------------------------------------------------------------------
# Recursive descent parser
# ---------------------------------------------------------------------------

class _CondParser:
    """Recursive descent parser for COBOL conditions.

    Grammar (simplified):
      condition      := or_expr
      or_expr        := and_expr ('OR' (abbreviated | and_expr))*
      and_expr       := not_expr ('AND' (abbreviated | not_expr))*
      not_expr       := 'NOT' not_expr | primary
      primary        := '(' condition ')' [arith_tail]
                      | condition_name
                      | operand [comparison | class_cond | sign_cond]
      abbreviated    := comp_op operand | bare_operand (inherit subj/op)
    """

    __slots__ = ('tokens', 'n', 'pos', 'lookup', 'last_subject', 'last_op')

    def __init__(self, tokens: list[str],
                 condition_lookup: dict[str, tuple[str, str]]):
        self.tokens = tokens
        self.n = len(tokens)
        self.pos = 0
        self.lookup = {k.upper(): v for k, v in condition_lookup.items()}
        self.last_subject = ""
        self.last_op = ""

    # --- Token access ---

    def _peek(self, offset: int = 0) -> str | None:
        p = self.pos + offset
        return _upper(self.tokens[p]) if p < self.n else None

    def _advance(self) -> str:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    # --- Entry ---

    def parse(self) -> str:
        result = self._or_expr()
        return result if result else "True"

    # --- Precedence: OR < AND < NOT < primary ---

    def _or_expr(self) -> str:
        left = self._and_expr()
        while self._peek() == 'OR':
            self._advance()
            right = self._after_conjunction(self._and_expr)
            left = f"{left} or {right}"
        return left

    def _and_expr(self) -> str:
        left = self._not_expr()
        while self._peek() == 'AND':
            self._advance()
            right = self._after_conjunction(self._not_expr)
            left = f"{left} and {right}"
        return left

    def _after_conjunction(self, parse_fn) -> str:
        """After AND/OR, detect abbreviated relations or parse new condition."""
        pk = self._peek()

        # Abbreviated: starts with comparison operator (e.g., AND > 5)
        if self._is_comp_op():
            op = self._comp_op()
            rhs = self._operand()
            return f"{self.last_subject} {op} {rhs}"

        # NOT followed by comparison operator → abbreviated negated
        if pk == 'NOT' and self._is_comp_op_at(self.pos + 1):
            self._advance()
            op = self._comp_op()
            rhs = self._operand()
            return f"{self.last_subject} {_negate_op(op)} {rhs}"

        # Parenthesized group → new condition
        if pk == '(':
            return parse_fn()

        # Condition name → standalone
        if pk and pk in self.lookup:
            return parse_fn()

        # NOT before condition name or parenthesized group → new condition
        if pk == 'NOT':
            pk2 = self._peek(1)
            if pk2 == '(' or (pk2 and pk2 in self.lookup):
                return parse_fn()
            # NOT + value without comp op → abbreviated negated
            if self.last_subject and self.last_op and pk2 is not None:
                if not self._is_comp_op_at(self.pos + 2):
                    self._advance()
                    rhs = self._operand()
                    return f"{self.last_subject} {_negate_op(self.last_op)} {rhs}"
            return parse_fn()

        # Value followed by comparison op → new comparison (new subject)
        if pk is not None and self._is_comp_op_at(self.pos + 1):
            return parse_fn()

        # Value followed by IS or class/sign keyword → new condition
        if pk is not None:
            pk1 = self._peek(1)
            if pk1 in ('IS', 'THEN') or pk1 in _CLASS_KEYWORDS or (pk1 and pk1 in _SIGN_WORDS):
                return parse_fn()

        # Bare value → abbreviated with inherited subject and operator
        if self.last_subject and self.last_op:
            rhs = self._operand()
            return f"{self.last_subject} {self.last_op} {rhs}"

        # Fallback: parse as new condition
        return parse_fn()

    def _not_expr(self) -> str:
        if self._peek() == 'NOT':
            self._advance()
            inner = self._not_expr()
            return f"not ({inner})"
        return self._primary()

    def _primary(self) -> str:
        pk = self._peek()

        # Parenthesized group
        if pk == '(':
            self._advance()
            inner = self._or_expr()
            if self._peek() == ')':
                self._advance()
            paren_expr = f"( {inner} )"
            # If followed by arithmetic, this was arithmetic grouping
            if self._peek() in _ARITH_OPS:
                parts = [paren_expr]
                while self._peek() in _ARITH_OPS:
                    parts.append(self._advance())
                    parts.append(self._simple_operand())
                return self._after_lhs(' '.join(parts))
            return paren_expr

        # Skip leading IS/THEN
        while pk in ('IS', 'THEN'):
            self._advance()
            pk = self._peek()

        # 88-level condition name
        if pk and pk in self.lookup:
            name = _upper(self._advance())
            parent, val = self.lookup[name]
            return _condition_88_expr(parent, val)

        # Parse left operand, then check for comparison/class/sign
        lhs = self._operand()
        return self._after_lhs(lhs)

    def _after_lhs(self, lhs: str) -> str:
        """After parsing LHS, handle comparison, class condition, or sign condition."""
        # Skip IS/THEN
        while self._peek() in ('IS', 'THEN'):
            self._advance()

        pk = self._peek()

        # NOT before class/sign/comparison
        if pk == 'NOT':
            # Peek past optional IS
            off = 1
            if self._peek(off) == 'IS':
                off += 1
            pk_after = self._peek(off)
            if pk_after in _CLASS_KEYWORDS:
                self.pos += off  # skip NOT [IS]
                return self._class_condition(lhs, negate=True)
            if pk_after and pk_after in _SIGN_WORDS:
                self.pos += off
                sign = _upper(self._advance())
                return f"not ({lhs} {_SIGN_WORDS[sign]})"
            # NOT as part of comparison phrase (NOT GREATER, NOT =, etc.)
            if self._is_comp_op():
                op = self._comp_op()
                rhs = self._operand()
                self.last_subject = lhs
                self.last_op = op
                return f"{lhs} {op} {rhs}"

        # Class condition
        if pk in _CLASS_KEYWORDS:
            return self._class_condition(lhs, negate=False)

        # Sign condition
        if pk and pk in _SIGN_WORDS:
            sign = _upper(self._advance())
            return f"{lhs} {_SIGN_WORDS[sign]}"

        # Comparison operator
        if self._is_comp_op():
            op = self._comp_op()
            rhs = self._operand()
            self.last_subject = lhs
            self.last_op = op
            return f"{lhs} {op} {rhs}"

        # Bare operand (no comparison follows)
        return lhs

    def _class_condition(self, subj: str, negate: bool) -> str:
        pk = _upper(self._advance())
        if pk == 'NUMERIC':
            return _numeric_check_expr(subj, negate)
        if pk == 'ALPHABETIC':
            return f"not str({subj}).isalpha()" if negate else f"str({subj}).isalpha()"
        if pk == 'ALPHABETIC-UPPER':
            expr = f"(str({subj}).isupper() and str({subj}).isalpha())"
            return f"not {expr}" if negate else expr
        if pk == 'ALPHABETIC-LOWER':
            expr = f"(str({subj}).islower() and str({subj}).isalpha())"
            return f"not {expr}" if negate else expr
        return subj

    # --- Operand parsing ---

    def _operand(self) -> str:
        """Parse an operand, possibly with arithmetic operators."""
        if self._peek() in ('+', '-'):
            prefix = self._advance()
            first = self._simple_operand()
            parts = [f"{prefix}{first}"]
        else:
            parts = [self._simple_operand()]
        while self._peek() in _ARITH_OPS:
            parts.append(self._advance())
            parts.append(self._simple_operand())
        return ' '.join(parts)

    def _simple_operand(self) -> str:
        """Parse a single operand token."""
        pk = self._peek()
        # Safety: don't consume keywords or operators
        if pk in ('AND', 'OR', 'NOT', ')', None) or pk in _CMP_OPS or pk in _SINGLE_OPS:
            return '0'
        # Arithmetic grouping paren
        if pk == '(':
            self._advance()
            inner = self._operand()
            if self._peek() == ')':
                self._advance()
            return f"( {inner} )"
        # FUNCTION intrinsic
        if pk == 'FUNCTION':
            return self._function_call()
        # Regular token — collect OF/IN qualification before resolving
        raw = self._advance()
        # Append trailing OF/IN qualification to build full qualified name
        while self._peek() in ('OF', 'IN'):
            qualifier_kw = self._advance()  # OF or IN
            if self.pos < self.n:
                group_name = self._advance()
                raw = f"{raw} {qualifier_kw} {group_name}"
        resolved = resolve_operand(raw)
        return resolved

    def _function_call(self) -> str:
        """Parse FUNCTION intrinsic call."""
        self._advance()  # consume FUNCTION
        if self.pos >= self.n:
            return '0'
        func_token = self._advance()
        paren_pos = func_token.find('(')
        if paren_pos >= 0:
            func_name = func_token[:paren_pos]
            raw_inner = func_token[paren_pos + 1:]
            if raw_inner.endswith(')'):
                raw_inner = raw_inner[:-1]
            raw_args = raw_inner.strip()
        else:
            func_name = func_token
            raw_args = ''
            if self._peek() == '(':
                self._advance()
                arg_parts: list[str] = []
                depth = 1
                while self.pos < self.n and depth > 0:
                    if self._peek() == '(':
                        depth += 1
                    elif self._peek() == ')':
                        depth -= 1
                        if depth == 0:
                            self._advance()
                            break
                    arg_parts.append(self._advance())
                raw_args = ' '.join(arg_parts)
        translated = translate_function_intrinsic(func_name, raw_args, resolve_operand)
        return translated if translated else '0'

    # --- Comparison operator handling ---

    def _is_comp_op(self) -> bool:
        return self._is_comp_op_at(self.pos)

    def _is_comp_op_at(self, pos: int) -> bool:
        if pos >= self.n:
            return False
        t = _upper(self.tokens[pos])
        if t in _SINGLE_OPS:
            return True
        for phrase, _ in _CMP_PHRASES:
            plen = len(phrase)
            if pos + plen <= self.n:
                if all(_upper(self.tokens[pos + j]) == phrase[j] for j in range(plen)):
                    return True
        return False

    def _comp_op(self) -> str:
        """Parse and consume a comparison operator."""
        for phrase, op in _CMP_PHRASES:
            plen = len(phrase)
            if self.pos + plen <= self.n:
                if all(_upper(self.tokens[self.pos + j]) == phrase[j] for j in range(plen)):
                    self.pos += plen
                    return op
        t = _upper(self._advance())
        return _SINGLE_OPS.get(t, '==')


# ---------------------------------------------------------------------------
# Validation / recovery
# ---------------------------------------------------------------------------

def _fix_unbalanced_parens(expr: str) -> str:
    """Auto-fix unbalanced parentheses."""
    opens = expr.count('(')
    closes = expr.count(')')
    if opens > closes:
        expr += ')' * (opens - closes)
    elif closes > opens:
        diff = closes - opens
        while diff > 0 and expr.endswith(')'):
            expr = expr[:-1].rstrip()
            diff -= 1
    return expr


def _fix_double_operators(expr: str) -> str:
    """Deduplicate consecutive identical operators (e.g., '== ==' → '==')."""
    expr = re.sub(r'(==\s*){2,}', '== ', expr)
    expr = re.sub(r'(!=\s*){2,}', '!= ', expr)
    expr = re.sub(r'\band\s+and\b', 'and', expr)
    expr = re.sub(r'\bor\s+or\b', 'or', expr)
    expr = re.sub(r'\bnot\s+not\b', 'not', expr)
    return expr


def _fix_trailing_operator(expr: str) -> str:
    """Strip dangling operator at end of expression."""
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
    return "True"
