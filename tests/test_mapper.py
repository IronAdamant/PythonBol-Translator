"""Tests for the Python code generator (mapper)."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
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
