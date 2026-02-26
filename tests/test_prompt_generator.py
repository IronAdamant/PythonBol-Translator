"""Tests for the LLM prompt generator."""

from pathlib import Path

import pytest

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol, parse_cobol_file
from cobol_safe_translator.prompt_generator import generate_prompt, PromptGenerator
from cobol_safe_translator.cli import main


MINIMAL_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       AUTHOR. TEST-AUTHOR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNTER PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY "Hello".
           STOP RUN.
"""


def _make_smap_and_source(cobol: str):
    program = parse_cobol(cobol)
    smap = analyze(program)
    python_source = generate_python(smap)
    return smap, python_source


class TestPromptGeneratorContent:
    def test_metadata_present(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "HELLO-WORLD" in brief
        assert "## Metadata" in brief

    def test_metadata_includes_stats_table(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "Paragraphs" in brief
        assert "Statements" in brief
        assert "| Field | Value |" in brief

    def test_sensitivity_summary_present(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 EMP-SSN PIC X(11).
       01 EMP-SALARY PIC 9(8)V99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY EMP-SSN.
           STOP RUN.
"""
        smap, src = _make_smap_and_source(cobol)
        brief = generate_prompt(smap, src)
        assert "## Sensitive Fields" in brief
        assert "HIGH" in brief or "EMP-SSN" in brief

    def test_no_sensitivities_shows_none(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "## Sensitive Fields" in brief
        # WS-COUNTER is not sensitive
        assert "None detected" in brief

    def test_paragraphs_section_with_verb_counts(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "## Paragraphs" in brief
        assert "MAIN-PARA" in brief
        # Should show verb counts using ×
        assert "\u00d7" in brief or "x" in brief.lower()

    def test_todo_inventory_present(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC X(5).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-A.
           STOP RUN.
"""
        smap, src = _make_smap_and_source(cobol)
        brief = generate_prompt(smap, src)
        assert "## TODO(high) Inventory" in brief
        assert "ACCEPT" in brief

    def test_todo_inventory_empty_when_no_todos(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "## TODO(high) Inventory" in brief
        assert "No TODO(high) items" in brief

    def test_python_skeleton_fenced_block(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "## Python Skeleton" in brief
        assert "```python" in brief
        assert "```" in brief

    def test_dependencies_section_no_calls(self):
        smap, src = _make_smap_and_source(MINIMAL_COBOL)
        brief = generate_prompt(smap, src)
        assert "## External Dependencies" in brief
        assert "None" in brief

    def test_dependencies_section_with_call(self):
        cobol = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALLER-PROG.
       DATA DIVISION.
       PROCEDURE DIVISION.
       MAIN-PARA.
           CALL 'SUBPROG' USING BY REFERENCE.
           STOP RUN.
"""
        smap, src = _make_smap_and_source(cobol)
        brief = generate_prompt(smap, src)
        assert "SUBPROG" in brief


class TestPromptCLI:
    def test_prompt_stdout(self, hello_cob, capsys):
        result = main(["prompt", str(hello_cob)])
        assert result == 0
        captured = capsys.readouterr()
        assert "COBOL Translation Brief" in captured.out
        assert "## Metadata" in captured.out

    def test_prompt_file_output(self, hello_cob, tmp_path):
        out_file = tmp_path / "brief.md"
        result = main(["prompt", str(hello_cob), "--output", str(out_file)])
        assert result == 0
        assert out_file.exists()
        content = out_file.read_text()
        assert "COBOL Translation Brief" in content

    def test_prompt_missing_file_returns_1(self, tmp_path):
        result = main(["prompt", "/nonexistent/prog.cob"])
        assert result == 1

    def test_prompt_customer_report(self, customer_report_cob, tmp_path):
        out_file = tmp_path / "brief.md"
        result = main(["prompt", str(customer_report_cob), "--output", str(out_file)])
        assert result == 0
        content = out_file.read_text()
        assert "CUSTOMER-REPORT" in content
        assert "HIGH" in content  # should have sensitive fields


class TestNonePythonSource:
    def test_none_python_source_does_not_crash(self):
        """PromptGenerator with None python_source must not crash on generate()."""
        from cobol_safe_translator.models import CobolProgram, SoftwareMap
        from cobol_safe_translator.prompt_generator import PromptGenerator

        program = CobolProgram(program_id="TEST")
        smap = SoftwareMap(program=program)
        gen = PromptGenerator(smap, None)  # type: ignore[arg-type]
        result = gen.generate()
        assert isinstance(result, str)
        assert "# COBOL Translation Brief" in result


class TestEmptyParagraphSection:
    def test_empty_paragraph_no_trailing_colon(self):
        """Paragraph with no statements must not produce trailing ': '."""
        from cobol_safe_translator.models import CobolProgram, SoftwareMap, Paragraph
        from cobol_safe_translator.prompt_generator import PromptGenerator

        program = CobolProgram(program_id="TEST", paragraphs=[Paragraph(name="EMPTY-PARA", statements=[])])
        smap = SoftwareMap(program=program)
        gen = PromptGenerator(smap, "")
        section = gen._paragraphs_section()
        assert "EMPTY-PARA" in section
        # Should not end with ': ' (no trailing colon-space with nothing after)
        for line in section.splitlines():
            if "EMPTY-PARA" in line:
                assert not line.endswith(": "), f"Line has trailing ': ' : {line!r}"
