"""PROCEDURE DIVISION parser for COBOL.

Handles paragraph/section detection, sentence joining, statement splitting,
and verb recognition within the PROCEDURE DIVISION.
"""

from __future__ import annotations

import re

from .models import CobolStatement, Paragraph

# --- Regexes ---

_PARAGRAPH_RE = re.compile(r"^([\w-]+)\s*\.\s*$")
_SECTION_RE = re.compile(r"^([\w-]+)\s+SECTION\s*\.\s*$", re.IGNORECASE)
_VERB_RE = re.compile(r"^([\w-]+)")

# Verbs we explicitly recognize
KNOWN_VERBS = frozenset({
    "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
    "DISPLAY", "ACCEPT", "PERFORM", "GO", "IF", "ELSE", "EVALUATE",
    "WHEN", "READ", "WRITE", "OPEN", "CLOSE", "CALL", "STOP",
    "SET", "STRING", "UNSTRING", "INSPECT", "INITIALIZE",
    "REWRITE",
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
    "NOT", "END-WRITE", "END-CALL", "END-STRING",
})

# Tokens that look like verbs but are actually operands/clauses
_OPERAND_VERBS = frozenset({
    "TO", "FROM", "BY", "GIVING", "INTO", "USING",
    "UNTIL", "VARYING", "THRU", "THROUGH", "TIMES",
    "THAN", "OR", "AND", "NOT", "EQUAL", "GREATER",
    "LESS", "ROUNDED", "REMAINDER", "ALSO", "OTHER",
    "WHEN", "THEN", "TRUE", "FALSE", "AT", "END",
    "WITH", "NO", "ADVANCING", "UPON", "INPUT", "OUTPUT",
    "EXTEND", "I-O", "DELIMITED", "SIZE", "POINTER",
    "TALLYING", "REPLACING", "LEADING", "TRAILING",
    "FIRST", "ALL", "INITIAL", "BEFORE", "AFTER",
    "ON", "ERROR", "OVERFLOW", "CORRESPONDING", "CORR",
    "ASCENDING", "DESCENDING", "KEY", "INDEXED",
    "DEPENDING",
})


def _join_sentences(lines: list[str]) -> list[tuple[str, str]]:
    """Join multi-line COBOL sentences into complete statements.

    Returns list of (sentence_text, type) where type is 'paragraph', 'section',
    or 'statement'. A sentence is everything up to and including a period.
    Paragraph/section headers are kept separate.
    """
    results: list[tuple[str, str]] = []
    accumulator = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Detect SECTION headers (e.g., MAIN-SECTION SECTION.)
        section_m = _SECTION_RE.match(stripped)
        if section_m:
            candidate = section_m.group(1).upper()
            if candidate not in KNOWN_VERBS:
                if accumulator.strip():
                    results.append((accumulator.strip(), "statement"))
                    accumulator = ""
                results.append((stripped, "section"))
                continue

        # Detect paragraph headers (single name followed by period)
        para_m = _PARAGRAPH_RE.match(stripped)
        if para_m:
            candidate = para_m.group(1).upper()
            if candidate not in KNOWN_VERBS:
                if accumulator.strip():
                    results.append((accumulator.strip(), "statement"))
                    accumulator = ""
                results.append((stripped, "paragraph"))
                continue

        # Accumulate into current sentence
        if accumulator:
            accumulator += " " + stripped
        else:
            accumulator = stripped

        # Check if the sentence ends (period at end of line)
        if accumulator.rstrip().endswith("."):
            results.append((accumulator.strip(), "statement"))
            accumulator = ""

    # Flush any remaining accumulator
    if accumulator.strip():
        results.append((accumulator.strip(), "statement"))

    return results


def parse_procedure(lines: list[str]) -> list[Paragraph]:
    """Parse PROCEDURE DIVISION into paragraphs and statements."""
    paragraphs: list[Paragraph] = []
    current_para: Paragraph | None = None

    sentences = _join_sentences(lines)

    for text, stype in sentences:
        if stype == "section":
            section_m = _SECTION_RE.match(text)
            if section_m:
                current_para = Paragraph(name=section_m.group(1).upper())
                paragraphs.append(current_para)
            continue

        if stype == "paragraph":
            para_m = _PARAGRAPH_RE.match(text)
            if para_m:
                current_para = Paragraph(name=para_m.group(1).upper())
                paragraphs.append(current_para)
            continue

        if current_para is None:
            current_para = Paragraph(name="__MAIN__")
            paragraphs.append(current_para)

        # Parse the joined sentence into statements
        stmts = _parse_statements(text)
        current_para.statements.extend(stmts)

    return paragraphs


def _split_operands(text: str) -> list[str]:
    """Split operand text into tokens, preserving quoted strings as single tokens.

    Reference modifications like ``WS-FIELD(1:3)`` and subscripts like
    ``WS-TABLE(IDX)`` are kept as single tokens. Standalone parentheses in
    COMPUTE expressions are split into separate tokens.
    """
    tokens: list[str] = []
    current = ""
    in_quote: str | None = None
    paren_depth = 0

    for ch in text:
        if in_quote:
            current += ch
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            current += ch
        elif ch in (" ", "\t"):
            if paren_depth > 0:
                # Inside parens attached to a name — keep as part of token
                current += ch
            else:
                if current:
                    tokens.append(current)
                    current = ""
        elif ch == "(":
            if current and (current[-1].isalnum() or current[-1] in ("-", "_")):
                # Paren directly after an identifier — reference mod or subscript
                current += ch
                paren_depth += 1
            else:
                # Standalone paren (COMPUTE expression)
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(ch)
        elif ch == ")":
            if paren_depth > 0:
                current += ch
                paren_depth -= 1
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


def _parse_statements(line: str) -> list[CobolStatement]:
    """Parse a joined sentence into one or more statements.

    Splits on known COBOL verbs to separate multiple statements
    within a single period-terminated sentence.
    """
    stripped = line.strip().rstrip(".")
    if not stripped:
        return []

    # Tokenize the entire sentence
    all_tokens = _split_operands(stripped)
    if not all_tokens:
        return []

    # Find verb positions — tokens that match known verbs
    # but skip verbs that appear as operands (e.g., GIVING after ADD)
    verb_positions: list[int] = []
    for i, tok in enumerate(all_tokens):
        upper = tok.upper()
        if upper in KNOWN_VERBS and upper not in _OPERAND_VERBS:
            verb_positions.append(i)
        elif upper in ("ELSE", "WHEN") and upper in KNOWN_VERBS:
            # ELSE and WHEN are structural — always split
            verb_positions.append(i)

    if not verb_positions:
        # No known verb found — try first token as verb
        verb = all_tokens[0].upper()
        operands = all_tokens[1:]
        return [CobolStatement(verb=verb, raw_text=stripped, operands=operands)]

    # Split into statements at each verb position
    statements: list[CobolStatement] = []
    for idx, vpos in enumerate(verb_positions):
        end = verb_positions[idx + 1] if idx + 1 < len(verb_positions) else len(all_tokens)
        verb = all_tokens[vpos].upper()
        operands = all_tokens[vpos + 1:end]
        raw = " ".join(all_tokens[vpos:end])
        statements.append(CobolStatement(verb=verb, raw_text=raw, operands=operands))

    return statements
