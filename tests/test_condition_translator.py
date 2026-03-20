"""Tests for the condition_translator module."""

from cobol_safe_translator.condition_translator import (
    tokenize_condition,
    translate_condition,
)
from cobol_safe_translator.utils import resolve_operand


class TestTokenizeCondition:
    def test_simple_comparison(self):
        tokens = tokenize_condition("WS-A > 10")
        assert tokens == ["WS-A", ">", "10"]

    def test_quoted_string(self):
        tokens = tokenize_condition('WS-A = "HELLO"')
        assert '"HELLO"' in tokens

    def test_reference_modification(self):
        tokens = tokenize_condition("WS-FIELD(1:3) = WS-B")
        assert "WS-FIELD(1:3)" in tokens

    def test_parenthesized_group(self):
        tokens = tokenize_condition("(A > B) AND (C < D)")
        assert "(" in tokens
        assert ")" in tokens

    def test_compound_operators(self):
        tokens = tokenize_condition("WS-A >= 10")
        assert ">=" in tokens

    def test_equals_sign(self):
        tokens = tokenize_condition("WS-A = 5")
        assert "=" in tokens


class TestResolveOperand:
    def test_quoted_literal(self):
        assert resolve_operand('"HELLO"') == '"HELLO"'

    def test_numeric_literal(self):
        assert resolve_operand("42") == "42"

    def test_figurative_zero(self):
        assert resolve_operand("ZERO") == "0"

    def test_figurative_spaces(self):
        assert resolve_operand("SPACES") == "' '"

    def test_reference_modification(self):
        result = resolve_operand("WS-FIELD(1:3)")
        assert "[0:3]" in result
        assert "ws_field" in result

    def test_regular_field(self):
        result = resolve_operand("WS-AMOUNT")
        assert "ws_amount" in result
        assert ".value" in result


class TestBasicComparisons:
    def test_greater_than(self):
        result = translate_condition("WS-A > 10", {})
        assert ">" in result
        assert "ws_a" in result

    def test_less_than(self):
        result = translate_condition("WS-A < 20", {})
        assert "<" in result

    def test_equals(self):
        result = translate_condition("WS-A = 5", {})
        assert "==" in result

    def test_greater_equal(self):
        result = translate_condition("WS-A >= 100", {})
        assert ">=" in result

    def test_not_equal(self):
        result = translate_condition("WS-A NOT = 0", {})
        assert "!=" in result


class TestCompoundConditions:
    def test_and(self):
        result = translate_condition("WS-A > 10 AND WS-B < 20", {})
        assert "and" in result
        assert "ws_a" in result
        assert "ws_b" in result

    def test_or(self):
        result = translate_condition("WS-A = 1 OR WS-B = 2", {})
        assert "or" in result


class TestClassConditions:
    def test_is_numeric(self):
        result = translate_condition("WS-FIELD IS NUMERIC", {})
        assert "isdigit()" in result

    def test_is_not_numeric(self):
        result = translate_condition("WS-FIELD IS NOT NUMERIC", {})
        assert "not" in result
        assert "isdigit()" in result

    def test_is_alphabetic(self):
        result = translate_condition("WS-FIELD IS ALPHABETIC", {})
        assert "isalpha()" in result


class TestSignConditions:
    def test_positive(self):
        result = translate_condition("WS-AMOUNT IS POSITIVE", {})
        assert "> 0" in result

    def test_negative(self):
        result = translate_condition("WS-AMOUNT IS NEGATIVE", {})
        assert "< 0" in result

    def test_zero(self):
        result = translate_condition("WS-AMOUNT IS ZERO", {})
        assert "== 0" in result


class TestCondition88Level:
    def test_88_level_expansion(self):
        lookup = {"WS-EOF": ("ws_eof_flag", '"Y"')}
        result = translate_condition("WS-EOF", lookup)
        assert "ws_eof_flag" in result
        assert '== "Y"' in result

    def test_88_level_thru_range(self):
        lookup = {"VALID-CODE": ("ws_code", "(1, 10)")}
        result = translate_condition("VALID-CODE", lookup)
        assert "<=" in result
        assert "ws_code" in result

    def test_not_88_level(self):
        lookup = {"WS-EOF": ("ws_eof_flag", '"Y"')}
        result = translate_condition("NOT WS-EOF", lookup)
        assert "not" in result
        assert "ws_eof_flag" in result


class TestImpliedSubjects:
    def test_implied_subject_or(self):
        result = translate_condition("WS-CODE = 1 OR 2 OR 3", {})
        # Should repeat ws_code with each value
        assert result.count("ws_code") >= 3 or result.count("==") >= 3


class TestAbbreviatedRelations:
    def test_abbreviated_and(self):
        result = translate_condition("WS-A > 10 AND < 20", {})
        assert "and" in result
        assert ">" in result
        assert "<" in result


class TestFigurativeConstants:
    def test_equal_zero(self):
        result = translate_condition("WS-A = ZERO", {})
        assert "== 0" in result

    def test_equal_spaces(self):
        result = translate_condition("WS-A = SPACES", {})
        assert "' '" in result


class TestParenthesized:
    def test_grouped_conditions(self):
        result = translate_condition("(WS-A > 5) AND (WS-B < 10)", {})
        assert "(" in result
        assert ")" in result
        assert "and" in result


class TestReferenceModInCondition:
    def test_ref_mod_slice(self):
        result = translate_condition("WS-FIELD(1:3) = WS-B", {})
        assert "[0:3]" in result


class TestNotConditions:
    def test_not_greater(self):
        result = translate_condition("NOT WS-A > 10", {})
        assert "not" in result

    def test_not_equal_inline(self):
        result = translate_condition("WS-A NOT = 0", {})
        assert "!=" in result


class TestEdgeCases:
    def test_empty_condition(self):
        assert translate_condition("", {}) == "True"

    def test_unbalanced_parens(self):
        result = translate_condition("(WS-A > 5", {})
        # Auto-fix: appends missing closing paren
        assert "self.data.ws_a.value > 5" in result
        assert result.count("(") == result.count(")")
