"""PROCEDURE DIVISION parser for COBOL.

Handles paragraph/section detection, sentence joining, statement splitting,
and verb recognition within the PROCEDURE DIVISION.
"""

from __future__ import annotations

import re

from .models import CobolStatement, Paragraph, UseDeclaration

# --- Regexes ---

_PARAGRAPH_RE = re.compile(r"^([\w-]+)\s*\.\s*$")
_SECTION_RE = re.compile(r"^([\w-]+)\s+SECTION\s*\.\s*$", re.IGNORECASE)
_DECLARATIVES_START_RE = re.compile(r"^DECLARATIVES\s*\.\s*$", re.IGNORECASE)
_DECLARATIVES_END_RE = re.compile(r"^END\s+DECLARATIVES\s*\.\s*$", re.IGNORECASE)

# Verbs we explicitly recognize
KNOWN_VERBS = frozenset({
    "MOVE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
    "DISPLAY", "ACCEPT", "PERFORM", "GO", "GOBACK", "IF", "ELSE", "EVALUATE",
    "WHEN", "READ", "WRITE", "OPEN", "CLOSE", "CALL", "STOP",
    "SET", "STRING", "UNSTRING", "INSPECT", "INITIALIZE",
    "REWRITE", "CONTINUE", "EXIT", "NEXT",
    "SEARCH", "RELEASE", "SORT", "MERGE", "DELETE", "START", "RETURN",
    "INITIATE", "GENERATE", "TERMINATE", "USE",
    "CANCEL", "JSON", "XML",
    "ENABLE", "DISABLE", "SEND", "RECEIVE", "PURGE",
    "END-IF", "END-EVALUATE", "END-PERFORM", "END-READ",
    "END-COMPUTE", "END-SUBTRACT", "END-ADD", "END-MULTIPLY",
    "END-DIVIDE", "END-UNSTRING",
    "END-WRITE", "END-CALL", "END-STRING",
    "END-SEARCH", "END-DELETE", "END-START", "END-RETURN",
})

# Tokens that look like verbs but are actually operands/clauses
_OPERAND_VERBS = frozenset({
    "TO", "FROM", "BY", "GIVING", "INTO", "USING",
    "UNTIL", "VARYING", "THRU", "THROUGH", "TIMES",
    "THAN", "OR", "AND", "NOT", "EQUAL", "GREATER",
    "LESS", "ROUNDED", "REMAINDER", "ALSO", "OTHER",
    "THEN", "TRUE", "FALSE", "AT", "END",
    "WITH", "NO", "ADVANCING", "UPON", "INPUT", "OUTPUT",
    "EXTEND", "I-O", "DELIMITED", "SIZE", "POINTER",
    "TALLYING", "REPLACING", "LEADING", "TRAILING",
    "FIRST", "ALL", "INITIAL", "BEFORE", "AFTER",
    "ON", "ERROR", "OVERFLOW", "CORRESPONDING", "CORR",
    "ASCENDING", "DESCENDING", "KEY", "INDEXED",
    "DEPENDING", "OF", "IN", "FUNCTION",
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


def _parse_paragraphs(lines: list[str]) -> list[Paragraph]:
    """Parse lines into paragraphs and statements (core logic)."""
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


def _split_declaratives(lines: list[str]) -> tuple[list[str], list[str]]:
    """Split PROCEDURE DIVISION lines into declaratives and normal code.

    Returns (declarative_lines, remaining_lines).
    """
    decl_start = -1
    decl_end = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if _DECLARATIVES_START_RE.match(stripped):
            decl_start = i
        elif _DECLARATIVES_END_RE.match(stripped):
            decl_end = i
            break

    if decl_start == -1 or decl_end == -1:
        return [], lines

    decl_lines = lines[decl_start + 1:decl_end]
    remaining = lines[:decl_start] + lines[decl_end + 1:]
    return decl_lines, remaining


_USE_RE = re.compile(
    r"^USE\s+"
    r"(?:(GLOBAL)\s+)?"
    r"(?:(BEFORE|AFTER)\s+(?:STANDARD\s+)?)?"
    r"(ERROR|EXCEPTION|REPORTING|DEBUGGING)\s+"
    r"(?:PROCEDURE\s+(?:ON\s+)?)?"
    r"(.+?)\s*$",
    re.IGNORECASE,
)


def _parse_use_statement(text: str) -> dict | None:
    """Parse a USE statement and return its components, or None if not a USE."""
    stripped = text.strip().rstrip(".")
    m = _USE_RE.match(stripped)
    if not m:
        return None
    global_flag = m.group(1) is not None
    before_after = (m.group(2) or "AFTER").upper()
    use_type = m.group(3).upper()
    targets_str = m.group(4).strip()

    # Parse targets: file names, I/O modes, or "INPUT", "OUTPUT", "EXTEND", "I-O"
    targets = [t.strip().upper() for t in re.split(r"[\s,]+", targets_str) if t.strip()]

    return {
        "use_type": use_type,
        "targets": targets,
        "is_global": global_flag,
        "before_after": before_after,
    }


def _parse_declarative_sections(decl_lines: list[str]) -> list[UseDeclaration]:
    """Parse declarative section lines into UseDeclaration objects.

    Within DECLARATIVES, each section has:
      section-name SECTION.
          USE ...
          <handler paragraphs/statements>
    """
    declarations: list[UseDeclaration] = []

    # Split declarative lines into sections by SECTION headers
    sections: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    for line in decl_lines:
        stripped = line.strip()
        section_m = _SECTION_RE.match(stripped)
        if section_m:
            if current_name is not None:
                sections.append((current_name, current_lines))
            current_name = section_m.group(1).upper()
            current_lines = []
        else:
            current_lines.append(line)

    if current_name is not None:
        sections.append((current_name, current_lines))

    for section_name, sec_lines in sections:
        # Join sentences to find the USE statement
        sentences = _join_sentences(sec_lines)
        use_info: dict | None = None
        handler_lines: list[str] = []
        found_use = False

        for text, stype in sentences:
            if not found_use and stype == "statement":
                stripped = text.strip().rstrip(".")
                if stripped.upper().startswith("USE "):
                    use_info = _parse_use_statement(stripped)
                    found_use = True
                    continue

            # Collect remaining lines for handler body
            if found_use:
                # Re-add line so _parse_paragraphs can process it
                handler_lines.append(text + ("." if not text.endswith(".") else ""))

        if use_info is None:
            continue

        # Parse handler body into paragraphs
        handler_paragraphs = _parse_paragraphs(handler_lines) if handler_lines else []

        declarations.append(UseDeclaration(
            section_name=section_name,
            use_type=use_info["use_type"],
            targets=use_info["targets"],
            is_global=use_info["is_global"],
            before_after=use_info["before_after"],
            paragraphs=handler_paragraphs,
        ))

    return declarations


def parse_procedure(lines: list[str]) -> tuple[list[Paragraph], list[UseDeclaration]]:
    """Parse PROCEDURE DIVISION into paragraphs and declarative sections.

    Returns (paragraphs, declaratives).
    """
    decl_lines, remaining = _split_declaratives(lines)
    declaratives = _parse_declarative_sections(decl_lines) if decl_lines else []
    paragraphs = _parse_paragraphs(remaining)
    return paragraphs, declaratives


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
            if paren_depth > 0:
                # Already inside attached parens — keep nested ( as part of token
                current += ch
                paren_depth += 1
            elif current and (current[-1].isalnum() or current[-1] in ("-", "_")):
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

    # Post-process: split tokens where a closing quote is immediately followed
    # by an identifier (e.g., 'ACCT ID : 'WS-KEY -> two tokens)
    fixed: list[str] = []
    for tok in tokens:
        if len(tok) > 2 and (tok[0] in ('"', "'")) and tok[0] in tok[1:]:
            # Find the closing quote position
            close_idx = tok.index(tok[0], 1)
            if close_idx < len(tok) - 1:
                # There's content after the closing quote
                fixed.append(tok[:close_idx + 1])
                remainder = tok[close_idx + 1:]
                if remainder:
                    fixed.append(remainder)
            else:
                fixed.append(tok)
        else:
            fixed.append(tok)

    # Post-process: merge hex/binary/national prefix with following quoted string
    # e.g., X "FF" → X"FF", H'0F' → H'0F'
    merged: list[str] = []
    for tok in fixed:
        if (merged and len(merged[-1]) == 1
                and merged[-1].upper() in ('X', 'B', 'Z', 'N', 'H')
                and tok and tok[0] in ('"', "'")):
            merged[-1] = merged[-1] + tok
        else:
            merged.append(tok)

    return merged


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
