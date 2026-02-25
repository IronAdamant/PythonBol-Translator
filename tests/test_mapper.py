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
        assert "class" in source
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
        assert "ws_c" in source
        assert ".set(" in source

    def test_subtract_giving(self):
        src = _make_cobol(["SUBTRACT WS-A FROM WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_c" in source
        assert ".set(" in source

    def test_multiply_giving(self):
        src = _make_cobol(["MULTIPLY WS-A BY WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_c" in source
        assert ".set(" in source

    def test_divide_giving(self):
        src = _make_cobol(["DIVIDE WS-A INTO WS-B GIVING WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_c" in source
        assert ".set(" in source

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
