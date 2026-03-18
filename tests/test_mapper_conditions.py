"""Tests for condition translation through the mapper pipeline."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from conftest import make_cobol


class TestConditionTranslation:
    def test_not_greater_than(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A NOT GREATER THAN 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "<=" in source
        # Should NOT contain invalid "not >"
        assert "not >" not in source

    def test_greater_than_or_equal_to(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A GREATER THAN OR EQUAL TO 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ">=" in source


class TestConditionIsKeyword:
    def test_is_equal_to_stripped(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A IS EQUAL TO 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "==" in source
        # IS should not appear as a data reference
        assert "is_" not in source

    def test_is_greater_than_stripped(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A IS GREATER THAN 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ">" in source
        assert "is_" not in source


class TestConditionCaseInsensitive:
    def test_mixed_case_greater_than(self):
        """Condition translation should be case-insensitive (issue #1)."""
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A Greater Than 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ">" in source

    def test_mixed_case_equal_to(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A Equal To 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "==" in source


class TestConditionOrdering:
    def test_not_greater_than_or_equal_to(self):
        """NOT GREATER THAN OR EQUAL TO should translate to < (longest match first)."""
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A NOT GREATER THAN OR EQUAL TO 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Find the while line — should contain < and no residual COBOL keywords
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "<" in while_line
        assert "OR" not in while_line
        assert "EQUAL" not in while_line

    def test_not_less_than_or_equal_to(self):
        """NOT LESS THAN OR EQUAL TO should translate to >."""
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A NOT LESS THAN OR EQUAL TO 5."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert ">" in while_line
        assert "OR" not in while_line


class TestConditionFigurativeConstants:
    def test_zero_in_condition(self):
        """ZERO in condition should resolve to 0, not self.data.zero.value."""
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A EQUAL TO ZERO."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "zero.value" not in source
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "== 0" in while_line

    def test_spaces_in_condition(self):
        """SPACES in condition should resolve to ' ', not self.data.spaces.value."""
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A EQUAL TO SPACES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "spaces.value" not in source


class TestConditionParentheses:
    def test_parenthesized_condition(self):
        """Parentheses in conditions should be preserved, not mangled into field names."""
        src = make_cobol(["PERFORM MAIN-PARA UNTIL (WS-A > 0)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "(" in while_line
        assert ")" in while_line
        assert "self.data.ws_a.value" in while_line


class TestConditionIsDataNamePreserved:
    def test_data_name_ending_in_is_not_corrupted(self):
        """Data names like WS-STATUS-IS should not have IS stripped."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-STATUS-IS PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           PERFORM MAIN-PARA UNTIL WS-STATUS-IS EQUAL TO 0.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_status_is" in source


class TestConditionStringLiteral:
    """Pass 1 Issue 1-2: Quoted strings in conditions should not be uppercased or split."""

    def test_quoted_string_preserved_in_condition(self):
        """Quoted string literal in condition should not be uppercased."""
        src = make_cobol(['IF WS-A = "hello" DISPLAY WS-A END-IF.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # The literal should stay lowercase
        assert '"hello"' in source
        assert '"HELLO"' not in source

    def test_quoted_string_with_spaces_not_split(self):
        """Quoted string with spaces should remain one token."""
        src = make_cobol([
            'IF WS-A = "hello world"',
            '    DISPLAY WS-A',
            'END-IF.',
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert '"hello world"' in source


class TestConditionMultipleStringLiterals:
    """Pass 2: Multiple string literals in conditions."""

    def test_two_string_literals(self):
        src = make_cobol([
            'IF WS-A = "hello" OR WS-B = "world"',
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert '"hello"' in source
        assert '"world"' in source


class TestConditionUnbalancedParens:
    def test_unbalanced_open_paren_emits_todo(self):
        """Condition with unmatched ( must not produce invalid Python."""
        src = make_cobol(["IF (WS-A = 1."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)  # must be valid Python

    def test_unbalanced_close_paren_emits_todo(self):
        """Condition with unmatched ) must not produce invalid Python."""
        src = make_cobol(["IF WS-A = 1)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)  # must be valid Python


class TestShortComparisonForms:
    """Pass 3: EQUAL, GREATER, LESS without TO/THAN."""

    def test_equal_short_form(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A EQUAL 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "==" in while_line
        assert "EQUAL" not in while_line

    def test_greater_short_form(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A GREATER 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert ">" in while_line

    def test_less_short_form(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A LESS 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "<" in while_line


class TestNotSymbolOperators:
    """Pass 3: NOT > and NOT < comparison operators."""

    def test_not_greater(self):
        src = make_cobol([
            "IF WS-A NOT > WS-B",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "<=" in source

    def test_not_less(self):
        src = make_cobol([
            "IF WS-A NOT < WS-B",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ">=" in source


class TestClassConditions:
    """Pass 1 Issue 4: IS NUMERIC / IS ALPHABETIC should produce valid Python."""

    def test_is_numeric_condition(self):
        """IS NUMERIC should translate to isdigit() check."""
        src = make_cobol([
            "IF WS-A IS NUMERIC",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "isdigit()" in source

    def test_is_alphabetic_condition(self):
        """IS ALPHABETIC should translate to isalpha() check."""
        src = make_cobol([
            "IF WS-A IS ALPHABETIC",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "isalpha()" in source


class TestNotNumericAlphabetic:
    """Pass 2: IS NOT NUMERIC / IS NOT ALPHABETIC class conditions."""

    def test_is_not_numeric(self):
        src = make_cobol([
            "IF WS-A IS NOT NUMERIC",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "not" in source
        assert "isdigit()" in source

    def test_is_not_alphabetic(self):
        src = make_cobol([
            "IF WS-A IS NOT ALPHABETIC",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "not" in source
        assert "isalpha()" in source


class TestBareNumericAlphabetic:
    """Pass 3: Bare NUMERIC/ALPHABETIC without IS keyword."""

    def test_bare_numeric(self):
        src = make_cobol([
            "IF WS-A NUMERIC",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "isdigit()" in source

    def test_bare_alphabetic(self):
        src = make_cobol([
            "IF WS-A ALPHABETIC",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "isalpha()" in source


class TestInlineIfWithElse:
    """Pass 1 Issue 3: Inline IF with ELSE should produce if/else block."""

    def test_inline_if_else(self):
        src = make_cobol(["IF WS-A > 0 DISPLAY WS-A ELSE DISPLAY WS-B END-IF."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "else:" in source
