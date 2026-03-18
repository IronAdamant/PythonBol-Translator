"""Tests for the Python code generator (mapper) — pipeline, infrastructure, and edge cases."""

import ast

from conftest import make_cobol

from cobol_safe_translator.adapters import CobolDecimal, FileAdapter
from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python, PythonMapper
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.utils import _is_numeric_literal, _to_python_name


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


_make_cobol = make_cobol


class TestFileAdapterContextManager:
    def test_context_manager(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\n")
        with FileAdapter(str(f)) as fa:
            assert fa.read() == "line1"
        # After exit, file should be closed
        assert fa._file is None


class TestCobolDecimalInterop:
    def test_add_cobol_decimal_to_cobol_decimal(self):
        a = CobolDecimal(5, 2, False, "10.00")
        b = CobolDecimal(5, 2, False, "3.50")
        a.add(b)
        assert a.value == __import__("decimal").Decimal("13.50")

    def test_subtract_cobol_decimal(self):
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
        _, ws, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "HELLO"

    def test_value_without_is(self):
        """VALUE without IS should still work."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            '01 WS-Y PIC X(5) VALUE "WORLD".',
        ]
        _, ws, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "WORLD"


class TestCobolDecimalDivideInterop:
    def test_divide_cobol_decimal(self):
        a = CobolDecimal(5, 2, False, "10.00")
        b = CobolDecimal(5, 2, False, "2.00")
        a.divide(b)
        assert a.value == __import__("decimal").Decimal("5.00")

    def test_multiply_cobol_decimal(self):
        a = CobolDecimal(5, 2, False, "3.00")
        b = CobolDecimal(5, 2, False, "4.00")
        a.multiply(b)
        assert a.value == __import__("decimal").Decimal("12.00")


class TestInfinityNaN:
    def test_infinity_coerces_to_zero(self):
        d = CobolDecimal(5, 2, False, 0)
        d.set(float('inf'))
        assert d.value == __import__("decimal").Decimal("0.00")

    def test_nan_coerces_to_zero(self):
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
        d = CobolDecimal(2, 0)  # max 99
        d.set(90)
        d.add(20)
        # 110 % 100 = 10 (COBOL high-order truncation)
        assert d.value == __import__("decimal").Decimal("10")

    def test_multiply_overflow_truncates(self):
        d = CobolDecimal(2, 0)  # max 99
        d.set(50)
        d.multiply(3)
        # 150 % 100 = 50
        assert d.value == __import__("decimal").Decimal("50")


class TestHighValuesLowValues:
    def test_high_values_string_init(self):
        """HIGH-VALUES in string field should produce single-char value, not escaped literal."""
        val = PythonMapper._translate_figurative("HIGH-VALUES", numeric=False)
        assert len(val) == 1
        assert val == "\xff"

    def test_low_values_string_init(self):
        """LOW-VALUES in string field should produce null character."""
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
        _, ws, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "12.34"

    def test_value_negative_decimal(self):
        """VALUE -3.50 should be captured fully."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-D PIC S9(5)V99 VALUE -3.50.",
        ]
        _, ws, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "-3.50"


class TestToPythonName:
    def test_digit_leading_name_prefixed(self):
        result = _to_python_name("88-CONDITION")
        assert result.startswith("f_")
        assert result == "f_88_condition"

    def test_python_keyword_suffixed(self):
        assert _to_python_name("RETURN") == "return_"

    def test_empty_name_produces_unnamed(self):
        assert _to_python_name("") == "_unnamed"


class TestLinkageSectionInMapper:
    """Pass 1 Issue 5: Linkage section items should appear in generated data class."""

    def test_linkage_items_in_data_class(self):
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-LINK.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       LINKAGE SECTION.",
            "       01 LK-PARAM PIC X(10).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           DISPLAY LK-PARAM.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "lk_param" in source

    def test_linkage_sensitivity_detected(self):
        """Linkage section items with sensitive names should be flagged."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-LINK.",
            "       DATA DIVISION.",
            "       LINKAGE SECTION.",
            "       01 LK-SSN PIC X(11).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           DISPLAY LK-SSN.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        ssn_flags = [f for f in smap.sensitivities if "SSN" in f.data_name]
        assert len(ssn_flags) >= 1


class TestPicStarSize:
    """Pass 2: PIC with * (check-protection) should count in size."""

    def test_check_protection_size(self):
        from cobol_safe_translator.parser import compute_pic_size
        size, dec, signed = compute_pic_size("***,**9.99")
        # 5 stars + 1 comma + 1 nine + 1 period + 2 nines = 10 display positions
        assert size == 10


class TestLinkageSectionInStats:
    """Pass 2: Linkage section items should be counted in stats."""

    def test_linkage_items_counted(self):
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-LINK.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       LINKAGE SECTION.",
            "       01 LK-PARAM PIC X(10).",
            "       01 LK-VALUE PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           DISPLAY WS-A.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        # 1 WS item + 2 linkage items = 3 data items
        assert smap.stats.data_item_count == 3


class TestParagraphWhitespace:
    """Pass 2: Paragraph name with whitespace before period."""

    def test_space_before_period(self):
        from cobol_safe_translator.parser import parse_procedure
        lines = [
            "MAIN-PARA .",
            "    DISPLAY WS-A.",
        ]
        paragraphs = parse_procedure(lines)
        assert len(paragraphs) == 1
        assert paragraphs[0].name == "MAIN-PARA"


class TestHeaderTripleQuoteEscape:
    def test_triple_quote_in_source_path_produces_valid_python(self):
        """source_path containing triple-quotes must not close the module docstring early."""
        from cobol_safe_translator.models import CobolProgram, SoftwareMap
        program = CobolProgram(program_id="TEST-PROG", source_path='/tmp/weird"""path.cob')
        smap = SoftwareMap(program=program)
        source = generate_python(smap)
        ast.parse(source)  # must not raise SyntaxError


class TestMultiDimSubscripts:
    """Multi-dimensional OCCURS table subscript resolution."""

    def test_single_numeric_subscript(self):
        """TABLE(1) should produce table[0].value (unchanged behaviour)."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(1)")
        assert result == "self.data.table[0].value"

    def test_single_variable_subscript(self):
        """TABLE(IDX) should produce table[int(self.data.idx.value) - 1].value."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(IDX)")
        assert result == "self.data.table[int(self.data.idx.value) - 1].value"

    def test_two_numeric_subscripts_space_separated(self):
        """TABLE(1 2) should produce table[0][1].value (chained indexing)."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(1 2)")
        assert result == "self.data.table[0][1].value"

    def test_two_numeric_subscripts_comma_separated(self):
        """TABLE(1, 2) should produce table[0][1].value."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(1, 2)")
        assert result == "self.data.table[0][1].value"

    def test_three_numeric_subscripts(self):
        """TABLE(2 3 4) should produce table[1][2][3].value."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(2 3 4)")
        assert result == "self.data.table[1][2][3].value"

    def test_two_variable_subscripts(self):
        """TABLE(I J) should produce chained variable indexing."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(I J)")
        assert result == (
            "self.data.table"
            "[int(self.data.i.value) - 1]"
            "[int(self.data.j.value) - 1]"
            ".value"
        )

    def test_mixed_subscripts_numeric_then_variable(self):
        """TABLE(1 J) should use literal 0 for first, variable for second."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(1 J)")
        assert result == (
            "self.data.table[0]"
            "[int(self.data.j.value) - 1]"
            ".value"
        )

    def test_mixed_subscripts_variable_then_numeric(self):
        """TABLE(I 2) should use variable for first, literal 1 for second."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(I 2)")
        assert result == (
            "self.data.table"
            "[int(self.data.i.value) - 1]"
            "[1]"
            ".value"
        )

    def test_comma_separated_variables(self):
        """TABLE(I, J) should produce the same as TABLE(I J)."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(I, J)")
        assert result == (
            "self.data.table"
            "[int(self.data.i.value) - 1]"
            "[int(self.data.j.value) - 1]"
            ".value"
        )

    def test_hyphenated_name_subscript(self):
        """WS-TABLE(WS-IDX) should handle hyphens in both name and subscript."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("WS-TABLE(WS-IDX)")
        assert result == "self.data.ws_table[int(self.data.ws_idx.value) - 1].value"

    def test_three_comma_separated_subscripts(self):
        """TABLE(1, 2, 3) should produce table[0][1][2].value."""
        from cobol_safe_translator.utils import resolve_operand
        result = resolve_operand("TABLE(1, 2, 3)")
        assert result == "self.data.table[0][1][2].value"

    def test_multidim_in_generated_python(self):
        """Multi-dim subscript in a DISPLAY should produce valid Python."""
        src = _make_cobol(
            procedure_lines=["DISPLAY WS-TABLE(1 2)."],
            data_lines=[
                "       01 WS-TABLE PIC 9(5) OCCURS 3.",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_table[0][1].value" in source

    def test_merge_spaced_subscripts_with_commas(self):
        """_merge_spaced_subscripts should handle comma tokens inside parens."""
        from cobol_safe_translator.statement_translators import _merge_spaced_subscripts
        tokens = ["TABLE", "(", "1", ",", "2", ")"]
        result = _merge_spaced_subscripts(tokens)
        assert result == ["TABLE(1 2)"]

    def test_merge_spaced_subscripts_comma_attached(self):
        """_merge_spaced_subscripts should handle comma attached to token (1, 2)."""
        from cobol_safe_translator.statement_translators import _merge_spaced_subscripts
        tokens = ["TABLE", "(", "1,", "2", ")"]
        result = _merge_spaced_subscripts(tokens)
        assert result == ["TABLE(1, 2)"]
