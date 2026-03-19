"""Tests for arithmetic verb translations through the mapper pipeline."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.utils import _is_numeric_literal
from conftest import make_cobol


class TestGivingClause:
    def test_add_giving(self):
        src = make_cobol(["ADD WS-A TO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "+" in set_lines[0]  # verify addition operator

    def test_subtract_giving(self):
        src = make_cobol(["SUBTRACT WS-A FROM WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "-" in set_lines[0]  # verify subtraction

    def test_multiply_giving(self):
        src = make_cobol(["MULTIPLY WS-A BY WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "*" in set_lines[0]  # verify multiplication

    def test_divide_giving(self):
        src = make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "/" in set_lines[0]  # verify division

    def test_divide_giving_remainder(self):
        src = make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C REMAINDER WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # REMAINDER now generates active modulo code
        rem_lines = [l for l in source.split("\n") if "ws_a.set(" in l and "%" in l and "field(" not in l]
        assert len(rem_lines) >= 1, "Expected ws_a.set(... % ...) for REMAINDER"


class TestFigurativeConstantsInArithmetic:
    def test_add_zeros(self):
        src = make_cobol(["ADD ZEROS TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # ZEROS should resolve to 0, not self.data.zeros.value
        assert "zeros.value" not in source
        assert ".add(0)" in source


class TestDecimalLiterals:
    def test_move_decimal_literal(self):
        src = make_cobol(["MOVE 100.50 TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "100.50" in source
        assert ".set(100.50)" in source

    def test_resolve_decimal_in_add(self):
        src = make_cobol(["ADD 3.14 TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".add(3.14)" in source


class TestComputeResolution:
    def test_compute_resolves_data_names(self):
        src = make_cobol(["COMPUTE WS-C = WS-A + WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Data names should be resolved, not raw COBOL names
        assert "self.data.ws_a.value" in source
        assert "self.data.ws_b.value" in source
        assert "self.data.ws_c.set(" in source

    def test_compute_with_literals(self):
        src = make_cobol(["COMPUTE WS-A = 10 + 5."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "10" in source
        assert "5" in source

    def test_compute_empty_rhs_emits_todo_not_syntax_error(self):
        """COMPUTE with no right-hand side must not generate self.data.x.set() (invalid Python)."""
        from cobol_safe_translator.statement_translators import translate_compute
        result = translate_compute(["WS-A", "="], lambda op: op)
        combined = "\n".join(result)
        assert "TODO(high)" in combined
        # Verify the output is syntactically safe (no bare .set() call)
        assert ".set()" not in combined


class TestComputeParentheses:
    def test_compute_with_parens(self):
        src = make_cobol(["COMPUTE WS-C = WS-A * (WS-B + 1)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_a.value" in source
        assert "self.data.ws_b.value" in source
        # Verify parentheses are preserved in the expression itself
        assert "( self.data.ws_b.value + 1 )" in source


class TestComputeMultipleTargets:
    def test_compute_two_targets(self):
        """COMPUTE A B = expr should store result in both A and B."""
        src = make_cobol(["COMPUTE WS-A WS-B = WS-C + 1."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_a.set(" in source
        assert "ws_b.set(" in source


class TestComputeWithoutEquals:
    """COMPUTE without = operator should emit error comment."""

    def test_compute_no_equals(self):
        src = make_cobol(["COMPUTE WS-A WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        assert "could not parse" in source.lower()


class TestDivideBy:
    def test_divide_by_giving(self):
        src = make_cobol(["DIVIDE WS-A BY WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "/" in set_lines[0]  # verify division operator


class TestDivideByWithoutGiving:
    def test_divide_by_without_giving_emits_todo(self):
        """DIVIDE x BY y without GIVING should emit TODO."""
        src = make_cobol(["DIVIDE WS-A BY WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source


class TestDivideIntoWithoutGiving:
    def test_divide_into_uses_divide_method(self):
        """DIVIDE x INTO y should use y.divide(x)."""
        src = make_cobol(["DIVIDE WS-A INTO WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_b.divide(self.data.ws_a.value)" in source


class TestDivideGivingZeroCheck:
    def test_divide_giving_has_zero_check_comment(self):
        """DIVIDE GIVING should emit a TODO about zero-check."""
        src = make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "verify divisor is non-zero" in source


class TestBasicSubtract:
    def test_subtract_from_without_giving(self):
        src = make_cobol(["SUBTRACT WS-A FROM WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_b.subtract(self.data.ws_a.value)" in source

    def test_multiply_without_giving(self):
        src = make_cobol(["MULTIPLY WS-A BY WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_b.multiply(self.data.ws_a.value)" in source


class TestMultiplyMultipleTargets:
    def test_multiply_two_targets(self):
        """MULTIPLY x BY y z should multiply both y and z by x."""
        src = make_cobol(["MULTIPLY WS-A BY WS-B WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_b.multiply(" in source
        assert "ws_c.multiply(" in source


class TestDivideMultipleTargets:
    def test_divide_into_two_targets(self):
        """DIVIDE x INTO y z should divide both y and z by x."""
        src = make_cobol(["DIVIDE WS-A INTO WS-B WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_b.divide(" in source
        assert "ws_c.divide(" in source


class TestRoundedFiltering:
    def test_add_giving_rounded_passes_through(self):
        src = make_cobol(["ADD WS-A TO WS-B GIVING WS-C ROUNDED."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_c" in source
        # ROUNDED keyword is not kept as a data reference but passed as kwarg
        assert "self.data.rounded" not in source
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1
        assert "rounded=True" in set_lines[0]

    def test_add_giving_without_rounded_omits_kwarg(self):
        src = make_cobol(["ADD WS-A TO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1
        assert "rounded=True" not in set_lines[0]


class TestOnSizeErrorFiltering:
    def test_add_on_size_error_filtered(self):
        src = make_cobol(["ADD WS-A TO WS-B ON SIZE ERROR."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # ON, SIZE, ERROR should not appear as data references
        assert "self.data.on" not in source
        assert "self.data.size" not in source
        assert "self.data.error" not in source


class TestPositiveSignLiteral:
    def test_positive_sign_recognized(self):
        assert _is_numeric_literal("+5")
        assert _is_numeric_literal("+3.14")
        assert _is_numeric_literal("-5")
        assert not _is_numeric_literal("WS-A")


class TestIsNumericLiteralTrailingDotMapper:
    def test_trailing_dot_resolve_is_numeric(self):
        """mapper._is_numeric_literal('5.') must return True (was False before fix)."""
        assert _is_numeric_literal("5.") is True
        assert _is_numeric_literal("123.") is True

    def test_leading_dot_resolve_is_numeric(self):
        assert _is_numeric_literal(".5") is True


class TestMultiplyMissingSource:
    def test_multiply_by_without_source_returns_comment(self):
        """MULTIPLY BY X (no source operand before BY) must not crash."""
        from cobol_safe_translator.statement_translators import translate_multiply
        result = translate_multiply(["BY", "WS-X"], lambda x: x)
        combined = "\n".join(result)
        assert "MULTIPLY" in combined
        assert "missing" in combined

    def test_multiply_by_with_source_works(self):
        """Normal MULTIPLY 2 BY WS-X must still work after guard."""
        from cobol_safe_translator.statement_translators import translate_multiply
        result = translate_multiply(["2", "BY", "WS-X"], lambda x: x)
        combined = "\n".join(result)
        assert "multiply" in combined or "set" in combined


class TestDivideMissingOperand:
    def test_divide_into_without_divisor_returns_comment(self):
        """DIVIDE INTO X (no divisor before INTO) must not crash."""
        from cobol_safe_translator.statement_translators import translate_divide
        result = translate_divide(["INTO", "WS-X"], lambda x: x)
        combined = "\n".join(result)
        assert "DIVIDE" in combined
        assert "missing" in combined

    def test_divide_by_without_dividend_returns_comment(self):
        """DIVIDE BY X (no dividend before BY) must not crash."""
        from cobol_safe_translator.statement_translators import translate_divide
        result = translate_divide(["BY", "WS-X"], lambda x: x)
        combined = "\n".join(result)
        assert "DIVIDE" in combined
        assert "missing" in combined

    def test_divide_into_with_operands_works(self):
        """Normal DIVIDE 2 INTO WS-X must still work after guard."""
        from cobol_safe_translator.statement_translators import translate_divide
        result = translate_divide(["2", "INTO", "WS-X"], lambda x: x)
        combined = "\n".join(result)
        assert "divide" in combined or "set" in combined


class TestGivingEmptyTarget:
    def test_subtract_giving_no_target_returns_comment(self):
        from cobol_safe_translator.statement_translators import translate_subtract
        result = translate_subtract(["A", "FROM", "B", "GIVING"], lambda x: x)
        assert any("SUBTRACT" in r for r in result)
        assert any("missing" in r or "no valid" in r for r in result)

    def test_add_giving_keyword_only_target_returns_comment(self):
        from cobol_safe_translator.statement_translators import translate_add
        result = translate_add(["A", "GIVING", "ON", "SIZE", "ERROR"], lambda x: x)
        assert any("ADD" in r for r in result)
        assert any("missing" in r or "no valid" in r for r in result)

    def test_multiply_giving_no_target_returns_comment(self):
        from cobol_safe_translator.statement_translators import translate_multiply
        result = translate_multiply(["2", "BY", "WS-X", "GIVING"], lambda x: x)
        assert any("MULTIPLY" in r for r in result)
        assert any("missing" in r or "no valid" in r for r in result)


class TestComputeFunctionIntrinsics:
    """Tests for COMPUTE FUNCTION intrinsic translation."""

    def test_function_length(self):
        """FUNCTION LENGTH(field) should translate to len(str(field))."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION LENGTH(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "len(str(" in source
        assert "ws_b" in source

    def test_function_current_date(self):
        """FUNCTION CURRENT-DATE should translate to datetime call."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION CURRENT-DATE."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "datetime" in source
        assert "strftime" in source

    def test_function_upper_case(self):
        """FUNCTION UPPER-CASE(field) should translate to str(field).upper()."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION UPPER-CASE(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".upper()" in source

    def test_function_lower_case(self):
        """FUNCTION LOWER-CASE(field) should translate to str(field).lower()."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION LOWER-CASE(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".lower()" in source

    def test_function_reverse(self):
        """FUNCTION REVERSE(field) should translate to str(field)[::-1]."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION REVERSE(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "[::-1]" in source

    def test_function_trim(self):
        """FUNCTION TRIM(field) should translate to str(field).strip()."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION TRIM(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".strip()" in source

    def test_function_numval(self):
        """FUNCTION NUMVAL(field) should translate to float(field)."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION NUMVAL(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "float(" in source

    def test_function_numval_c(self):
        """FUNCTION NUMVAL-C(field) should strip commas and dollars."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION NUMVAL-C(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "replace(" in source
        assert "float(" in source

    def test_function_abs(self):
        """FUNCTION ABS(x) should translate to abs(x)."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION ABS(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "abs(" in source

    def test_function_sqrt(self):
        """FUNCTION SQRT(x) should translate to x ** 0.5."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION SQRT(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "** 0.5" in source

    def test_function_integer(self):
        """FUNCTION INTEGER(x) should translate to int(x)."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION INTEGER(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "int(" in source

    def test_function_integer_part(self):
        """FUNCTION INTEGER-PART(x) should translate to int(x)."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION INTEGER-PART(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "int(" in source

    def test_function_ord(self):
        """FUNCTION ORD(char) should translate to ord(char)."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION ORD(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ord(" in source

    def test_function_char(self):
        """FUNCTION CHAR(n) should translate to chr(n)."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION CHAR(WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "chr(" in source

    def test_function_mod(self):
        """FUNCTION MOD(a b) should translate to a % b."""
        src = make_cobol(["COMPUTE WS-C = FUNCTION MOD(WS-A WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "%" in source

    def test_function_max(self):
        """FUNCTION MAX(a b c) should translate to max(a, b, c)."""
        src = make_cobol(["COMPUTE WS-C = FUNCTION MAX(WS-A WS-B WS-C)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "max(" in source

    def test_function_min(self):
        """FUNCTION MIN(a b) should translate to min(a, b)."""
        src = make_cobol(["COMPUTE WS-C = FUNCTION MIN(WS-A WS-B)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "min(" in source

    def test_function_when_compiled(self):
        """FUNCTION WHEN-COMPILED should translate to a datetime call."""
        src = make_cobol(["COMPUTE WS-A = FUNCTION WHEN-COMPILED."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "datetime" in source

    def test_unknown_function_emits_todo(self):
        """Unknown FUNCTION intrinsic should emit a TODO comment."""
        from cobol_safe_translator.statement_translators import translate_compute
        result = translate_compute(
            ["WS-A", "=", "FUNCTION", "BOGUS-FUNC(X)"],
            lambda op: f"self.data.{op.lower()}.value",
        )
        combined = "\n".join(result)
        assert "TODO(high)" in combined
        assert "BOGUS-FUNC" in combined

    def test_function_in_expression(self):
        """FUNCTION intrinsic used within a larger COMPUTE expression."""
        src = make_cobol(["COMPUTE WS-C = FUNCTION LENGTH(WS-A) + 1."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "len(str(" in source
        assert "+ 1" in source

    def test_function_trim_leading_direct(self):
        """FUNCTION TRIM(field LEADING) should translate to lstrip."""
        from cobol_safe_translator.statement_translators import translate_compute
        result = translate_compute(
            ["WS-A", "=", "FUNCTION", "TRIM(WS-B LEADING)"],
            lambda op: f"self.data.{op.lower().replace('-','_')}.value",
        )
        combined = "\n".join(result)
        assert ".lstrip()" in combined

    def test_function_trim_trailing_direct(self):
        """FUNCTION TRIM(field TRAILING) should translate to rstrip."""
        from cobol_safe_translator.statement_translators import translate_compute
        result = translate_compute(
            ["WS-A", "=", "FUNCTION", "TRIM(WS-B TRAILING)"],
            lambda op: f"self.data.{op.lower().replace('-','_')}.value",
        )
        combined = "\n".join(result)
        assert ".rstrip()" in combined
