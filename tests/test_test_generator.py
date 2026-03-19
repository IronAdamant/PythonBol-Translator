"""Tests for the automatic regression test generator."""

import ast

from conftest import make_cobol

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.test_generator import generate_tests


def _build_smap(cobol_source: str):
    """Parse and analyze COBOL source, returning the SoftwareMap."""
    program = parse_cobol(cobol_source)
    return analyze(program)


class TestGenerateTestsProducesValidPython:
    """The generated test file must be syntactically valid Python."""

    def test_hello_world(self, hello_source):
        smap = _build_smap(hello_source)
        result = generate_tests(smap, "hello_world")
        ast.parse(result)

    def test_customer_report(self, customer_report_source):
        smap = _build_smap(customer_report_source)
        result = generate_tests(smap, "customer_report")
        ast.parse(result)

    def test_minimal_program(self):
        src = make_cobol(
            ["DISPLAY 'HELLO'", "STOP RUN."],
            ["       01 WS-A PIC 9(3) VALUE 0."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        ast.parse(result)


class TestInstantiationTests:
    """Verify that instantiation test classes are generated."""

    def test_contains_data_class_test(self, hello_source):
        smap = _build_smap(hello_source)
        result = generate_tests(smap, "hello_world")
        assert "class TestInstantiation:" in result
        assert "test_data_class_instantiation" in result
        assert "HelloWorldData()" in result

    def test_contains_program_class_test(self, hello_source):
        smap = _build_smap(hello_source)
        result = generate_tests(smap, "hello_world")
        assert "test_program_class_instantiation" in result
        assert "HelloWorldProgram()" in result
        assert 'hasattr(program, "data")' in result
        assert 'hasattr(program, "run")' in result


class TestDataItemTypeTests:
    """Verify data item type tests are generated with correct types."""

    def test_numeric_decimal(self):
        src = make_cobol(
            ["DISPLAY WS-A", "STOP RUN."],
            ["       01 WS-A PIC 9(5)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_ws_a_is_decimal" in result
        assert "CobolDecimal" in result

    def test_alphanumeric_string(self):
        src = make_cobol(
            ["DISPLAY WS-MSG", "STOP RUN."],
            ["       01 WS-MSG PIC X(20)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_ws_msg_is_string" in result
        assert "CobolString" in result

    def test_comp1_float(self):
        src = make_cobol(
            ["DISPLAY WS-FLOAT", "STOP RUN."],
            ["       01 WS-FLOAT PIC 9(5) COMP-1."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_ws_float_is_float" in result
        assert "isinstance(data.ws_float, float)" in result

    def test_comp5_int(self):
        src = make_cobol(
            ["DISPLAY WS-INT", "STOP RUN."],
            ["       01 WS-INT PIC 9(5) COMP-5."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_ws_int_is_int" in result
        assert "isinstance(data.ws_int, int)" in result

    def test_numeric_initial_value(self):
        src = make_cobol(
            ["DISPLAY WS-CTR", "STOP RUN."],
            ["       01 WS-CTR PIC 9(3) VALUE 100."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_ws_ctr_initial_value" in result
        assert "100" in result

    def test_filler_skipped(self):
        src = make_cobol(
            ["DISPLAY 'X'", "STOP RUN."],
            [
                "       01 WS-REC.",
                "           05 FILLER PIC X(10).",
                "           05 WS-NAME PIC X(20).",
            ],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_filler" not in result
        assert "test_ws_name_is_string" in result


class TestParagraphTests:
    """Verify paragraph method tests are generated."""

    def test_paragraphs_exist(self, hello_source):
        smap = _build_smap(hello_source)
        result = generate_tests(smap, "hello_world")
        assert "class TestParagraphs:" in result
        assert "test_main_paragraph_exists" in result

    def test_multiple_paragraphs(self):
        src = make_cobol(
            ["PERFORM CALC-PARA", "STOP RUN."],
            ["       01 WS-A PIC 9(5)."],
        )
        # Add a second paragraph manually
        src += "\n       CALC-PARA.\n           ADD 1 TO WS-A.\n"
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "test_main_para_exists" in result
        assert "test_calc_para_exists" in result

    def test_paragraph_callable_assertion(self, hello_source):
        smap = _build_smap(hello_source)
        result = generate_tests(smap, "hello_world")
        assert "callable(getattr(program," in result


class TestDisplayOutputTests:
    """Verify DISPLAY output tests are generated for literal displays."""

    def test_literal_display(self):
        src = make_cobol(
            ['DISPLAY "HELLO WORLD"', "STOP RUN."],
            ["       01 WS-A PIC 9(3)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "class TestDisplayOutput:" in result
        assert "HELLO WORLD" in result

    def test_no_display_no_class(self):
        src = make_cobol(
            ["ADD 1 TO WS-A", "STOP RUN."],
            ["       01 WS-A PIC 9(3)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "class TestDisplayOutput:" not in result

    def test_variable_display_skipped(self):
        src = make_cobol(
            ["DISPLAY WS-A", "STOP RUN."],
            ["       01 WS-A PIC 9(3)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        # Variable-only DISPLAY should not produce output tests
        assert "class TestDisplayOutput:" not in result


class TestEdgeCases:
    """Test edge cases for robust generation."""

    def test_no_paragraphs(self):
        src = "\n".join([
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. EMPTY-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-X PIC X(5).",
            "       PROCEDURE DIVISION.",
        ])
        smap = _build_smap(src)
        result = generate_tests(smap, "empty_prog")
        ast.parse(result)
        # Should still have instantiation and execution tests
        assert "class TestInstantiation:" in result
        assert "class TestExecution:" in result
        # Should not have paragraph tests
        assert "class TestParagraphs:" not in result

    def test_occurs_array(self):
        src = make_cobol(
            ["DISPLAY WS-TABLE(1)", "STOP RUN."],
            [
                "       01 WS-TABLE PIC 9(3) OCCURS 10.",
            ],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        ast.parse(result)
        # OCCURS items have list type, so no individual type test
        # But the file should still be valid
        assert "class TestInstantiation:" in result

    def test_no_data_items(self):
        src = "\n".join([
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. MINIMAL.",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            '           DISPLAY "MINIMAL"',
            "           STOP RUN.",
        ])
        smap = _build_smap(src)
        result = generate_tests(smap, "minimal")
        ast.parse(result)
        assert "class TestInstantiation:" in result

    def test_module_name_in_import(self):
        src = make_cobol(
            ["DISPLAY 'X'", "STOP RUN."],
            ["       01 WS-A PIC 9(3)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "my_module")
        assert "from my_module import" in result

    def test_execution_test_always_present(self):
        src = make_cobol(
            ["DISPLAY 'X'", "STOP RUN."],
            ["       01 WS-A PIC 9(3)."],
        )
        smap = _build_smap(src)
        result = generate_tests(smap, "test_prog")
        assert "class TestExecution:" in result
        assert "test_program_runs" in result
        assert "subprocess.run" in result
