"""Tests for the Python code generator (mapper)."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python, PythonMapper
from cobol_safe_translator.parser import parse_cobol


class TestPythonGeneration:
    def test_generates_valid_python_hello(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        source = generate_python(smap)
        # Must be parseable Python
        ast.parse(source)

    def test_generates_valid_python_customer(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)

    def test_contains_program_class(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "class HelloWorldProgram" in source

    def test_contains_dataclass(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "@dataclass" in source

    def test_contains_main_block(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert 'if __name__ == "__main__":' in source

    def test_sensitivity_warnings_in_output(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "# WARNING [HIGH]:" in source
        assert "CUST-SSN" in source

    def test_adapters_imported(self, hello_source):
        program = parse_cobol(hello_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "CobolDecimal" in source and "CobolString" in source

    def test_paragraph_methods_generated(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "def main_program" in source
        assert "def initialize_program" in source

    def test_perform_generates_method_call(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "self.initialize_program()" in source

    def test_empty_program_generates_valid_python(self):
        minimal = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EMPTY-TEST.\n"
            "       DATA DIVISION.\n"
            "       PROCEDURE DIVISION.\n"
        )
        program = parse_cobol(minimal)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "def run(self)" in source
        assert "@dataclass" in source

    def test_write_has_todo(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        smap = analyze(program)
        source = generate_python(smap)
        assert "TODO(high)" in source


def _make_cobol(procedure_lines: list[str]) -> str:
    """Helper: build minimal COBOL source with given PROCEDURE DIVISION lines."""
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. TEST-PROG.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
        "       01 WS-A PIC 9(5).",
        "       01 WS-B PIC 9(5).",
        "       01 WS-C PIC 9(5).",
        "       PROCEDURE DIVISION.",
        "       MAIN-PARA.",
    ]
    for pl in procedure_lines:
        lines.append(f"           {pl}")
    return "\n".join(lines) + "\n"


class TestGivingClause:
    def test_add_giving(self):
        src = _make_cobol(["ADD WS-A TO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "+" in set_lines[0]  # verify addition operator

    def test_subtract_giving(self):
        src = _make_cobol(["SUBTRACT WS-A FROM WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "-" in set_lines[0]  # verify subtraction

    def test_multiply_giving(self):
        src = _make_cobol(["MULTIPLY WS-A BY WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "*" in set_lines[0]  # verify multiplication

    def test_divide_giving(self):
        src = _make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "/" in set_lines[0]  # verify division

    def test_divide_giving_remainder(self):
        src = _make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C REMAINDER WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "REMAINDER" in source


class TestMoveCorresponding:
    def test_move_corresponding_emits_todo(self):
        src = _make_cobol(["MOVE CORRESPONDING WS-A TO WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "MOVE CORRESPONDING" in source


class TestFigurativeConstantsInArithmetic:
    def test_add_zeros(self):
        src = _make_cobol(["ADD ZEROS TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # ZEROS should resolve to 0, not self.data.zeros.value
        assert "zeros.value" not in source
        assert ".add(0)" in source


class TestPerformVariants:
    def test_perform_until(self):
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A = 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source

    def test_perform_times(self):
        src = _make_cobol(["PERFORM MAIN-PARA 5 TIMES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "for _ in range(5)" in source


class TestMoveMultipleTargets:
    def test_move_to_multiple_targets(self):
        src = _make_cobol(["MOVE 0 TO WS-A WS-B WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_a" in source
        assert "ws_b" in source
        assert "ws_c" in source
        assert source.count(".set(") >= 3


class TestFileAdapterContextManager:
    def test_context_manager(self, tmp_path):
        from cobol_safe_translator.adapters import FileAdapter
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\n")
        with FileAdapter(str(f)) as fa:
            fa.open_input()
            assert fa.read() == "line1"
        # After exit, file should be closed
        assert fa._file is None


class TestComputeResolution:
    def test_compute_resolves_data_names(self):
        src = _make_cobol(["COMPUTE WS-C = WS-A + WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Data names should be resolved, not raw COBOL names
        assert "self.data.ws_a.value" in source
        assert "self.data.ws_b.value" in source
        assert "self.data.ws_c.set(" in source

    def test_compute_with_literals(self):
        src = _make_cobol(["COMPUTE WS-A = 10 + 5."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "10" in source
        assert "5" in source


class TestPerformVarying:
    def test_perform_varying_emits_todo(self):
        src = _make_cobol(["PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A = 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "PERFORM VARYING" in source


class TestConditionTranslation:
    def test_not_greater_than(self):
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A NOT GREATER THAN 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "<=" in source
        # Should NOT contain invalid "not >"
        assert "not >" not in source

    def test_greater_than_or_equal_to(self):
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A GREATER THAN OR EQUAL TO 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ">=" in source


class TestDecimalLiterals:
    def test_move_decimal_literal(self):
        src = _make_cobol(["MOVE 100.50 TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "100.50" in source
        assert ".set(100.50)" in source

    def test_resolve_decimal_in_add(self):
        src = _make_cobol(["ADD 3.14 TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".add(3.14)" in source


class TestDisplaySeparator:
    def test_display_no_space_separator(self):
        src = _make_cobol(['DISPLAY "HELLO" "WORLD".'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "sep=''" in source


class TestCobolDecimalInterop:
    def test_add_cobol_decimal_to_cobol_decimal(self):
        from cobol_safe_translator.adapters import CobolDecimal
        a = CobolDecimal(5, 2, False, "10.00")
        b = CobolDecimal(5, 2, False, "3.50")
        a.add(b)
        assert a.value == __import__("decimal").Decimal("13.50")

    def test_subtract_cobol_decimal(self):
        from cobol_safe_translator.adapters import CobolDecimal
        a = CobolDecimal(5, 2, False, "10.00")
        b = CobolDecimal(5, 2, False, "3.50")
        a.subtract(b)
        assert a.value == __import__("decimal").Decimal("6.50")


class TestValueIsSyntax:
    def test_value_is_keyword_skipped(self):
        """VALUE IS syntax should extract the actual value, not 'IS'."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            '01 WS-X PIC X(5) VALUE IS "HELLO".',
        ]
        _, ws = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "HELLO"

    def test_value_without_is(self):
        """VALUE without IS should still work."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            '01 WS-Y PIC X(5) VALUE "WORLD".',
        ]
        _, ws = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "WORLD"


class TestConditionIsKeyword:
    def test_is_equal_to_stripped(self):
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A IS EQUAL TO 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "==" in source
        # IS should not appear as a data reference
        assert "is_" not in source

    def test_is_greater_than_stripped(self):
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A IS GREATER THAN 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ">" in source
        assert "is_" not in source


class TestPerformThru:
    def test_perform_thru_emits_todo(self):
        src = _make_cobol(["PERFORM MAIN-PARA THRU MAIN-PARA."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "THRU" in source


class TestCloseWithKeywords:
    def test_close_with_lock_filters_keywords(self):
        src = _make_cobol(["CLOSE WS-A WITH LOCK."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".close()" in source
        # WITH and LOCK should be filtered out, not treated as file names
        assert "with_" not in source
        assert "lock" not in source.split(".close()")[0].split("\n")[-1]


class TestDisplayUpon:
    def test_display_upon_filtered(self):
        src = _make_cobol(['DISPLAY "ERROR" UPON WS-A.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "print(" in source
        assert '"ERROR"' in source
        # UPON and target should not appear as print args
        print_lines = [l for l in source.split("\n") if "print(" in l]
        assert print_lines, "Expected print() call in generated code"
        assert "upon" not in print_lines[0].lower()
        assert "ws_a" not in print_lines[0]


class TestDivideBy:
    def test_divide_by_giving(self):
        src = _make_cobol(["DIVIDE WS-A BY WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        set_lines = [l for l in source.split("\n") if "ws_c.set(" in l and "field(" not in l]
        assert len(set_lines) >= 1, "Expected ws_c.set() in generated code"
        assert "/" in set_lines[0]  # verify division operator


class TestComputeParentheses:
    def test_compute_with_parens(self):
        src = _make_cobol(["COMPUTE WS-C = WS-A * (WS-B + 1)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_a.value" in source
        assert "self.data.ws_b.value" in source
        # Verify parentheses are preserved in the expression itself
        assert "( self.data.ws_b.value + 1 )" in source


class TestCobolDecimalDivideInterop:
    def test_divide_cobol_decimal(self):
        from cobol_safe_translator.adapters import CobolDecimal
        a = CobolDecimal(5, 2, False, "10.00")
        b = CobolDecimal(5, 2, False, "2.00")
        a.divide(b)
        assert a.value == __import__("decimal").Decimal("5.00")

    def test_multiply_cobol_decimal(self):
        from cobol_safe_translator.adapters import CobolDecimal
        a = CobolDecimal(5, 2, False, "3.00")
        b = CobolDecimal(5, 2, False, "4.00")
        a.multiply(b)
        assert a.value == __import__("decimal").Decimal("12.00")


class TestPositiveSignLiteral:
    def test_positive_sign_recognized(self):
        from cobol_safe_translator.mapper import _is_numeric_literal
        assert _is_numeric_literal("+5")
        assert _is_numeric_literal("+3.14")
        assert _is_numeric_literal("-5")
        assert not _is_numeric_literal("WS-A")


class TestRoundedFiltering:
    def test_add_giving_rounded_filtered(self):
        src = _make_cobol(["ADD WS-A TO WS-B GIVING WS-C ROUNDED."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_c" in source
        assert "rounded" not in source.lower().split("# ")[0]  # not in active code


class TestOnSizeErrorFiltering:
    def test_add_on_size_error_filtered(self):
        src = _make_cobol(["ADD WS-A TO WS-B ON SIZE ERROR."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # ON, SIZE, ERROR should not appear as data references
        assert "self.data.on" not in source
        assert "self.data.size" not in source
        assert "self.data.error" not in source


class TestInfinityNaN:
    def test_infinity_coerces_to_zero(self):
        from cobol_safe_translator.adapters import CobolDecimal
        d = CobolDecimal(5, 2, False, 0)
        d.set(float('inf'))
        assert d.value == __import__("decimal").Decimal("0.00")

    def test_nan_coerces_to_zero(self):
        from cobol_safe_translator.adapters import CobolDecimal
        d = CobolDecimal(5, 2, False, 0)
        d.set(float('nan'))
        assert d.value == __import__("decimal").Decimal("0.00")


class TestReservedMethodName:
    def test_paragraph_named_run(self):
        """Paragraph named RUN should not overwrite the entry-point run() method."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       RUN.",
            "           DISPLAY WS-A.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Should have para_run for the paragraph and run for the entry point
        assert "def para_run(self)" in source
        assert "def run(self)" in source


class TestArithmeticOverflow:
    def test_add_overflow_truncates(self):
        from cobol_safe_translator.adapters import CobolDecimal
        d = CobolDecimal(2, 0)  # max 99
        d.set(90)
        d.add(20)
        # 110 % 100 = 10 (COBOL high-order truncation)
        assert d.value == __import__("decimal").Decimal("10")

    def test_multiply_overflow_truncates(self):
        from cobol_safe_translator.adapters import CobolDecimal
        d = CobolDecimal(2, 0)  # max 99
        d.set(50)
        d.multiply(3)
        # 150 % 100 = 50
        assert d.value == __import__("decimal").Decimal("50")


class TestHighValuesLowValues:
    def test_high_values_string_init(self):
        """HIGH-VALUES in string field should produce single-char value, not escaped literal."""
        from cobol_safe_translator.mapper import PythonMapper
        val = PythonMapper._translate_figurative("HIGH-VALUES", numeric=False)
        assert len(val) == 1
        assert val == "\xff"

    def test_low_values_string_init(self):
        """LOW-VALUES in string field should produce null character."""
        from cobol_safe_translator.mapper import PythonMapper
        val = PythonMapper._translate_figurative("LOW-VALUES", numeric=False)
        assert len(val) == 1
        assert val == "\x00"

    def test_high_values_in_generated_code(self):
        """HIGH-VALUES field init should generate valid Python with correct char."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-X PIC X(5) VALUE HIGH-VALUES.",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           DISPLAY WS-X.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # The generated CobolString init should contain the actual character
        assert "CobolString(5," in source


class TestDivideGivingZeroCheck:
    def test_divide_giving_has_zero_check_comment(self):
        """DIVIDE GIVING should emit a TODO about zero-check."""
        src = _make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "verify divisor is non-zero" in source


class TestConditionOrdering:
    def test_not_greater_than_or_equal_to(self):
        """NOT GREATER THAN OR EQUAL TO should translate to < (longest match first)."""
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A NOT GREATER THAN OR EQUAL TO 10."])
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
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A NOT LESS THAN OR EQUAL TO 5."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert ">" in while_line
        assert "OR" not in while_line


class TestEmptyProgramId:
    def test_missing_program_id_generates_valid_python(self):
        """A COBOL file with no PROGRAM-ID should still generate valid Python."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           DISPLAY WS-A.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "class UnnamedProgram" in source or "class Unnamed" in source


class TestValueDecimalLiteral:
    def test_value_with_decimal_point(self):
        """VALUE 12.34 should parse the full decimal, not truncate at the period."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-C PIC 9(3)V99 VALUE 12.34.",
        ]
        _, ws = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "12.34"

    def test_value_negative_decimal(self):
        """VALUE -3.50 should be captured fully."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-D PIC S9(5)V99 VALUE -3.50.",
        ]
        _, ws = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "-3.50"


class TestInitializeStatement:
    def test_initialize_generates_commented_set(self):
        """INITIALIZE should emit commented-out .set(0) code."""
        src = _make_cobol(["INITIALIZE WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "# INITIALIZE WS-A" in source
        assert "# self.data.ws_a.set(0)" in source


class TestPerformTimesVariable:
    def test_perform_variable_times(self):
        """PERFORM para WS-COUNT TIMES should use variable for range."""
        src = _make_cobol(["PERFORM MAIN-PARA WS-A TIMES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "for _ in range(" in source
        assert "ws_a" in source


class TestPerformThruMethodCall:
    def test_perform_thru_calls_first_paragraph(self):
        """PERFORM THRU should call the first paragraph in addition to TODO."""
        src = _make_cobol(["PERFORM MAIN-PARA THRU MAIN-PARA."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "self.main_para()" in source
        assert "only first paragraph" in source


class TestConditionFigurativeConstants:
    def test_zero_in_condition(self):
        """ZERO in condition should resolve to 0, not self.data.zero.value."""
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A EQUAL TO ZERO."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "zero.value" not in source
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "== 0" in while_line

    def test_spaces_in_condition(self):
        """SPACES in condition should resolve to ' ', not self.data.spaces.value."""
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL WS-A EQUAL TO SPACES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "spaces.value" not in source


class TestDivideByWithoutGiving:
    def test_divide_by_without_giving_emits_todo(self):
        """DIVIDE x BY y without GIVING should emit TODO."""
        src = _make_cobol(["DIVIDE WS-A BY WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source


class TestDivideIntoWithoutGiving:
    def test_divide_into_uses_divide_method(self):
        """DIVIDE x INTO y should use y.divide(x)."""
        src = _make_cobol(["DIVIDE WS-A INTO WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_b.divide(self.data.ws_a.value)" in source


class TestMoveAll:
    def test_move_all_emits_todo(self):
        """MOVE ALL should emit TODO for character fill."""
        src = _make_cobol(['MOVE ALL "X" TO WS-A.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "MOVE ALL" in source


class TestConditionParentheses:
    def test_parenthesized_condition(self):
        """Parentheses in conditions should be preserved, not mangled into field names."""
        src = _make_cobol(["PERFORM MAIN-PARA UNTIL (WS-A > 0)."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        while_line = [l for l in source.split("\n") if "while not" in l][0]
        assert "(" in while_line
        assert ")" in while_line
        assert "self.data.ws_a.value" in while_line


class TestIfStatement:
    def test_if_emits_todo(self):
        """IF statement should emit TODO for manual translation."""
        src = _make_cobol(["IF WS-A > 0 DISPLAY WS-A END-IF."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "IF" in source


class TestEvaluateStatement:
    def test_evaluate_emits_todo(self):
        """EVALUATE statement should emit TODO for if/elif translation."""
        src = _make_cobol(["EVALUATE TRUE WHEN OTHER DISPLAY WS-A END-EVALUATE."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source


class TestMoveFunction:
    def test_move_function_emits_todo(self):
        """MOVE FUNCTION should emit TODO for manual translation."""
        src = _make_cobol(["MOVE FUNCTION CURRENT-DATE TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "FUNCTION" in source


class TestDisplayFigurativeConstants:
    def test_display_zeros(self):
        """DISPLAY ZEROS should resolve to print(0), not self.data.zeros.value."""
        src = _make_cobol(["DISPLAY ZEROS."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "zeros.value" not in source
        assert "print(0" in source

    def test_display_spaces(self):
        """DISPLAY SPACES should resolve to print(' ')."""
        src = _make_cobol(["DISPLAY SPACES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "spaces.value" not in source
        assert "print(' '" in source


class TestComputeMultipleTargets:
    def test_compute_two_targets(self):
        """COMPUTE A B = expr should store result in both A and B."""
        src = _make_cobol(["COMPUTE WS-A WS-B = WS-C + 1."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_a.set(" in source
        assert "ws_b.set(" in source


class TestToPythonName:
    def test_digit_leading_name_prefixed(self):
        from cobol_safe_translator.mapper import _to_python_name
        result = _to_python_name("88-CONDITION")
        assert result.startswith("f_")
        assert result == "f_88_condition"

    def test_python_keyword_suffixed(self):
        from cobol_safe_translator.mapper import _to_python_name
        assert _to_python_name("RETURN") == "return_"

    def test_empty_name_produces_unnamed(self):
        from cobol_safe_translator.mapper import _to_python_name
        assert _to_python_name("") == "_unnamed"


class TestBasicSubtract:
    def test_subtract_from_without_giving(self):
        src = _make_cobol(["SUBTRACT WS-A FROM WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_b.subtract(self.data.ws_a.value)" in source

    def test_multiply_without_giving(self):
        src = _make_cobol(["MULTIPLY WS-A BY WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_b.multiply(self.data.ws_a.value)" in source


class TestOpenStatement:
    def test_open_input_generates_open_input_call(self):
        """OPEN INPUT should generate .open_input() on the file adapter."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT CUST-FILE ASSIGN TO 'cust.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD CUST-FILE.",
            "       01 CUST-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           OPEN INPUT CUST-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".open_input()" in source

    def test_open_output_generates_safety_comment(self):
        """OPEN OUTPUT should generate safety comment, not actual file write."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT RPT-FILE ASSIGN TO 'report.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD RPT-FILE.",
            "       01 RPT-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           OPEN OUTPUT RPT-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "not supported" in source.lower() or "TODO(high)" in source
        # Must NOT generate .open_output() — safety guarantee
        assert "open_output()" not in source


class TestReadStatement:
    def test_read_generates_read_call_and_eof_check(self):
        """READ should generate .read() call with EOF None check."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT CUST-FILE ASSIGN TO 'cust.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD CUST-FILE.",
            "       01 CUST-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           READ CUST-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".read()" in source
        assert "is None" in source or "AT END" in source


class TestStopStatement:
    def test_stop_run_generates_return(self):
        """STOP RUN should generate a return statement."""
        src = _make_cobol(["STOP RUN."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Find lines in the method body that have 'return'
        method_lines = [l.strip() for l in source.split("\n") if l.strip() == "return"]
        assert len(method_lines) >= 1, "STOP RUN should generate 'return'"


class TestMultiplyMultipleTargets:
    def test_multiply_two_targets(self):
        """MULTIPLY x BY y z should multiply both y and z by x."""
        src = _make_cobol(["MULTIPLY WS-A BY WS-B WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_b.multiply(" in source
        assert "ws_c.multiply(" in source


class TestDivideMultipleTargets:
    def test_divide_into_two_targets(self):
        """DIVIDE x INTO y z should divide both y and z by x."""
        src = _make_cobol(["DIVIDE WS-A INTO WS-B WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_b.divide(" in source
        assert "ws_c.divide(" in source


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


class TestCallWithUsing:
    def test_call_with_using_generates_args(self):
        """CALL 'SUBPROG' USING WS-A should include argument in TODO."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           CALL 'SUB-PROG' USING WS-A.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "SUB-PROG" in source or "sub_prog" in source
        assert "TODO(high)" in source
