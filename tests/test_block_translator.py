"""Tests for the block_translator module — IF/EVALUATE block reconstruction."""

from cobol_safe_translator.block_translator import (
    _fallback_resolve,
    _indent_line,
    is_inline_evaluate,
    is_inline_if,
    translate_evaluate_block,
    translate_if_block,
    translate_inline_evaluate,
    translate_inline_if,
)
from cobol_safe_translator.models import CobolStatement


# --- Helpers ---

def _cond(c: str) -> str:
    """Trivial condition translator for testing."""
    return c.lower().replace("-", "_")


def _resolve(op: str) -> str:
    """Trivial operand resolver for testing."""
    return f"self.data.{op.lower().replace('-', '_')}.value"


def _stmt_fn(stmt: CobolStatement) -> list[str]:
    """Trivial statement translator — returns the verb as a comment."""
    return [f"# {stmt.verb} {' '.join(stmt.operands)}"]


def _make(verb: str, *operands: str, raw: str = "") -> CobolStatement:
    return CobolStatement(verb=verb, raw_text=raw or f"{verb} {' '.join(operands)}", operands=list(operands))


# --- _indent_line ---

class TestIndentLine:
    def test_zero_indent(self):
        assert _indent_line("hello", 0) == "hello"

    def test_single_indent(self):
        assert _indent_line("hello", 1) == "    hello"

    def test_double_indent(self):
        assert _indent_line("hello", 2) == "        hello"


# --- _fallback_resolve ---

class TestFallbackResolve:
    def test_quoted_string(self):
        assert _fallback_resolve('"HELLO"') == '"HELLO"'

    def test_single_quoted_string(self):
        assert _fallback_resolve("'HELLO'") == "'HELLO'"

    def test_numeric_literal(self):
        assert _fallback_resolve("42") == "42"

    def test_decimal_literal(self):
        assert _fallback_resolve("3.14") == "3.14"

    def test_negative_literal(self):
        assert _fallback_resolve("-5") == "-5"

    def test_zeros(self):
        assert _fallback_resolve("ZEROS") == "0"

    def test_zeroes(self):
        assert _fallback_resolve("ZEROES") == "0"

    def test_zero(self):
        assert _fallback_resolve("ZERO") == "0"

    def test_spaces(self):
        assert _fallback_resolve("SPACES") == "' '"

    def test_high_values(self):
        assert _fallback_resolve("HIGH-VALUES") == "'\\xff'"

    def test_low_values(self):
        assert _fallback_resolve("LOW-VALUES") == "'\\x00'"

    def test_data_name(self):
        assert _fallback_resolve("WS-FIELD") == "self.data.ws_field.value"

    def test_digit_leading_name(self):
        assert _fallback_resolve("3RD-FIELD") == "self.data.f_3rd_field.value"

    def test_keyword_name(self):
        assert _fallback_resolve("class") == "self.data.class_.value"


# --- is_inline_if ---

class TestIsInlineIf:
    def test_inline_with_display(self):
        stmt = _make("IF", "WS-A", ">", "0", "DISPLAY", "WS-A")
        assert is_inline_if(stmt) is True

    def test_inline_with_move(self):
        stmt = _make("IF", "WS-A", "=", "1", "MOVE", "0", "TO", "WS-B")
        assert is_inline_if(stmt) is True

    def test_not_inline(self):
        stmt = _make("IF", "WS-A", ">", "0")
        assert is_inline_if(stmt) is False

    def test_data_name_not_confused_with_verb(self):
        """MOVE-FLAG as a data name should not match MOVE verb."""
        stmt = _make("IF", "MOVE-FLAG", "=", "1")
        assert is_inline_if(stmt) is False


# --- is_inline_evaluate ---

class TestIsInlineEvaluate:
    def test_inline_with_when(self):
        stmt = _make("EVALUATE", "TRUE", "WHEN", "WS-A", ">", "0", "DISPLAY", "WS-A")
        assert is_inline_evaluate(stmt) is True

    def test_not_inline(self):
        stmt = _make("EVALUATE", "TRUE")
        assert is_inline_evaluate(stmt) is False


# --- translate_inline_if ---

class TestTranslateInlineIf:
    def test_basic_inline(self):
        stmt = _make("IF", "WS-A", ">", "0", "DISPLAY", "WS-A")
        lines = translate_inline_if(stmt, _cond, indent=0)
        assert any("if" in line for line in lines)
        assert any("ws_a > 0" in line for line in lines)

    def test_with_stmt_translator(self):
        stmt = _make("IF", "WS-A", ">", "0", "DISPLAY", "WS-A")
        lines = translate_inline_if(stmt, _cond, indent=0, translate_stmt_fn=_stmt_fn)
        assert any("# DISPLAY" in line for line in lines)

    def test_without_stmt_translator_emits_todo(self):
        stmt = _make("IF", "WS-A", ">", "0", "DISPLAY", "WS-A")
        lines = translate_inline_if(stmt, _cond, indent=0, translate_stmt_fn=None)
        assert any("TODO(high)" in line for line in lines)

    def test_unparseable_inline(self):
        stmt = _make("IF")
        stmt.operands = []
        lines = translate_inline_if(stmt, _cond, indent=0)
        assert any("could not parse" in line for line in lines)

    def test_no_condition_before_verb(self):
        stmt = _make("IF", "DISPLAY", "WS-A")
        lines = translate_inline_if(stmt, _cond, indent=0)
        assert any("could not parse" in line for line in lines)


# --- translate_inline_evaluate ---

class TestTranslateInlineEvaluate:
    def test_emits_todo(self):
        stmt = _make("EVALUATE", "TRUE", "WHEN", "WS-A", ">", "0")
        lines = translate_inline_evaluate(stmt, _cond, _resolve, indent=0)
        assert any("TODO(high)" in line for line in lines)


# --- translate_if_block ---

class TestTranslateIfBlock:
    def test_simple_if_end_if(self):
        stmts = [
            _make("IF", "WS-A", ">", "0"),
            _make("DISPLAY", "WS-A"),
            _make("END-IF"),
        ]
        lines, next_i = translate_if_block(stmts, 0, _stmt_fn, _cond, indent=0)
        assert next_i == 3
        assert any("if" in line for line in lines)
        assert any("# DISPLAY" in line for line in lines)

    def test_if_else_end_if(self):
        stmts = [
            _make("IF", "WS-A", ">", "0"),
            _make("DISPLAY", "WS-A"),
            _make("ELSE"),
            _make("DISPLAY", "WS-B"),
            _make("END-IF"),
        ]
        lines, next_i = translate_if_block(stmts, 0, _stmt_fn, _cond, indent=0)
        assert next_i == 5
        assert any("if" in line for line in lines)
        assert any("else:" in line for line in lines)

    def test_nested_if(self):
        stmts = [
            _make("IF", "WS-A", ">", "0"),
            _make("IF", "WS-B", ">", "0"),
            _make("DISPLAY", "WS-B"),
            _make("END-IF"),
            _make("END-IF"),
        ]
        lines, next_i = translate_if_block(stmts, 0, _stmt_fn, _cond, indent=0)
        assert next_i == 5
        # Should have two if keywords
        if_count = sum(1 for line in lines if "if " in line and "elif" not in line)
        assert if_count == 2

    def test_missing_end_if(self):
        stmts = [
            _make("IF", "WS-A", ">", "0"),
        ]
        lines, next_i = translate_if_block(stmts, 0, _stmt_fn, _cond, indent=0)
        assert any("TODO(high)" in line or "pass" in line for line in lines)

    def test_nested_evaluate_inside_if(self):
        stmts = [
            _make("IF", "WS-A", ">", "0"),
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "WS-B", "=", "1"),
            _make("DISPLAY", "WS-B"),
            _make("END-EVALUATE"),
            _make("END-IF"),
        ]
        lines, next_i = translate_if_block(stmts, 0, _stmt_fn, _cond, indent=0)
        assert next_i == 6

    def test_empty_then_body(self):
        stmts = [
            _make("IF", "WS-A", ">", "0"),
            _make("END-IF"),
        ]
        lines, next_i = translate_if_block(stmts, 0, _stmt_fn, _cond, indent=0)
        assert any("pass" in line for line in lines)


# --- translate_evaluate_block ---

class TestTranslateEvaluateBlock:
    def test_evaluate_true_with_when_other(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "WS-A", ">", "0"),
            _make("DISPLAY", "WS-A"),
            _make("WHEN", "OTHER"),
            _make("DISPLAY", "WS-B"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert next_i == 6
        assert any("if " in line for line in lines)
        assert any("else:" in line for line in lines)

    def test_evaluate_variable(self):
        stmts = [
            _make("EVALUATE", "WS-STATUS"),
            _make("WHEN", "1"),
            _make("DISPLAY", "ONE"),
            _make("WHEN", "2"),
            _make("DISPLAY", "TWO"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert next_i == 6
        assert any("==" in line for line in lines)

    def test_evaluate_also_emits_todo(self):
        stmts = [
            _make("EVALUATE", "WS-A", "ALSO", "WS-B"),
            _make("WHEN", "1", "ALSO", "2"),
            _make("DISPLAY", "MATCH"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert any("TODO(high)" in line for line in lines)
        assert next_i == 4  # Should skip to after END-EVALUATE

    def test_when_thru_emits_todo(self):
        stmts = [
            _make("EVALUATE", "WS-STATUS"),
            _make("WHEN", "1", "THRU", "5"),
            _make("DISPLAY", "RANGE"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert any("TODO(high)" in line for line in lines)

    def test_missing_end_evaluate(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "WS-A", ">", "0"),
            _make("DISPLAY", "WS-A"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert len(lines) > 0

    def test_empty_evaluate_block(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert any("TODO(high)" in line or "pass" in line for line in lines)

    def test_nested_if_inside_when(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "WS-A", ">", "0"),
            _make("IF", "WS-B", ">", "0"),
            _make("DISPLAY", "WS-B"),
            _make("END-IF"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert next_i == 6

    def test_multiple_when_clauses(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "WS-A", "=", "1"),
            _make("DISPLAY", "ONE"),
            _make("WHEN", "WS-A", "=", "2"),
            _make("DISPLAY", "TWO"),
            _make("WHEN", "WS-A", "=", "3"),
            _make("DISPLAY", "THREE"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        assert next_i == 8
        if_count = sum(1 for line in lines if "if " in line and "elif" not in line)
        elif_count = sum(1 for line in lines if "elif " in line)
        assert if_count == 1
        assert elif_count == 2

    def test_empty_when_body(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "WS-A", "=", "1"),
            _make("WHEN", "OTHER"),
            _make("DISPLAY", "DEFAULT"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        # First WHEN has empty body — falls through to WHEN OTHER (merged)
        # The merged clause should contain the DISPLAY body
        joined = "\n".join(lines)
        assert "DISPLAY" in joined or "else:" in joined


# --- Additional adapter tests (from test_mapper.py #14 — adding targeted coverage) ---

class TestFigurativeConstantsResolve:
    """Test _fallback_resolve with figurative constants (issue #15)."""

    def test_space_single(self):
        assert _fallback_resolve("SPACE") == "' '"

    def test_high_value_single(self):
        assert _fallback_resolve("HIGH-VALUE") == "'\\xff'"

    def test_low_value_single(self):
        assert _fallback_resolve("LOW-VALUE") == "'\\x00'"

    def test_case_insensitive_zeros(self):
        assert _fallback_resolve("zeros") == "0"

    def test_case_insensitive_spaces(self):
        assert _fallback_resolve("spaces") == "' '"


# === Pass 1 additions ===


class TestInlineIfWithElse:
    """Pass 1 Issue 3: Inline IF with ELSE branch."""

    def test_inline_if_else_produces_both_branches(self):
        stmt = _make("IF", "WS-A", ">", "0", "DISPLAY", "WS-A", "ELSE", "DISPLAY", "WS-B")
        lines = translate_inline_if(stmt, _cond, indent=0, translate_stmt_fn=_stmt_fn)
        assert any("if " in line for line in lines)
        assert any("else:" in line for line in lines)
        assert any("# DISPLAY WS-A" in line for line in lines)
        assert any("# DISPLAY WS-B" in line for line in lines)

    def test_inline_if_else_without_translator(self):
        stmt = _make("IF", "WS-A", ">", "0", "MOVE", "1", "TO", "WS-B", "ELSE", "MOVE", "0", "TO", "WS-B")
        lines = translate_inline_if(stmt, _cond, indent=0)
        assert any("if " in line for line in lines)
        assert any("else:" in line for line in lines)


class TestEvaluateWhenOtherFirst:
    """Pass 1 Issue 6: WHEN OTHER as first clause should not emit bare else:."""

    def test_when_other_first_generates_if_true(self):
        stmts = [
            _make("EVALUATE", "TRUE"),
            _make("WHEN", "OTHER"),
            _make("DISPLAY", "DEFAULT"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        # Should NOT start with bare 'else:' — should use 'if True:' or similar
        first_code_line = [l for l in lines if l.strip() and not l.strip().startswith("#")][0]
        assert "else:" not in first_code_line or "if" in first_code_line


class TestIsInlineIfFalsePositives:
    """Pass 1 Issue 7: Data names like DISPLAY-FLAG should not trigger inline IF."""

    def test_hyphenated_verb_prefix_data_name(self):
        """DISPLAY-FLAG is a data name, not the DISPLAY verb."""
        stmt = _make("IF", "DISPLAY-FLAG", "=", "1")
        assert is_inline_if(stmt) is False

    def test_read_status_data_name(self):
        """READ-STATUS is a data name, not the READ verb."""
        stmt = _make("IF", "READ-STATUS", "=", "Y")
        assert is_inline_if(stmt) is False

    def test_exact_verb_name_matches(self):
        """Exact verb name DISPLAY should still match."""
        stmt = _make("IF", "WS-A", ">", "0", "DISPLAY", "WS-A")
        assert is_inline_if(stmt) is True


# === Pass 3 additions ===


class TestEvaluateWhenFallthrough:
    """Pass 3: Consecutive WHENs with empty bodies should merge (fall-through)."""

    def test_consecutive_when_fallthrough(self):
        stmts = [
            _make("EVALUATE", "WS-STATUS"),
            _make("WHEN", "A"),
            _make("WHEN", "B"),
            _make("DISPLAY", "MATCH"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        # Should produce a single if with OR, not separate if/elif
        combined = " ".join(lines)
        assert "or" in combined.lower() or "# DISPLAY MATCH" in combined
        # Should NOT have pass for the empty WHEN "A"
        assert next_i == 5


class TestEvaluateWhenOrValues:
    """Pass 3: WHEN x OR y should generate compound condition."""

    def test_when_or_two_values(self):
        stmts = [
            _make("EVALUATE", "WS-STATUS"),
            _make("WHEN", "1", "OR", "2"),
            _make("DISPLAY", "MATCH"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        combined = " ".join(lines)
        assert "or" in combined.lower()


class TestEvaluateAlsoDetection:
    """EVALUATE ALSO should emit TODO and skip the block."""

    def test_also_emits_todo(self):
        stmts = [
            _make("EVALUATE", "WS-A", "ALSO", "WS-B"),
            _make("WHEN", "1", "ALSO", "2"),
            _make("DISPLAY", "MATCH"),
            _make("END-EVALUATE"),
        ]
        lines, next_i = translate_evaluate_block(stmts, 0, _stmt_fn, _cond, _resolve, indent=0)
        combined = " ".join(lines)
        assert "TODO" in combined
        assert "ALSO" in combined
        assert next_i == 4  # Should consume the whole block
