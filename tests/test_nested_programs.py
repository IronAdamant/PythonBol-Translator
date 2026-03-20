"""Tests for nested/concatenated COBOL program support.

Covers:
  - Parser splitting multi-program sources at IDENTIFICATION DIVISION boundaries
  - END PROGRAM delimiter stripping
  - Nested programs attached to outer program's nested_programs list
  - Mapper generating valid Python with multiple classes
  - Single-program backward compatibility (nested_programs defaults to empty)
  - Behavioral test: nested program DISPLAY output via subprocess
"""

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol, _split_programs, preprocess_lines


_PROJECT_SRC = str(Path(__file__).resolve().parent.parent / "src")


# ---------------------------------------------------------------------------
# Parser: _split_programs
# ---------------------------------------------------------------------------

class TestSplitPrograms:
    """Unit tests for the _split_programs helper."""

    def test_single_program_returns_one_segment(self):
        lines = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. SINGLE.",
            "PROCEDURE DIVISION.",
            "MAIN-PARA.",
            'DISPLAY "HELLO".',
        ]
        segments = _split_programs(lines)
        assert len(segments) == 1
        assert segments[0] == lines

    def test_two_programs_split_at_boundary(self):
        lines = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. FIRST.",
            "PROCEDURE DIVISION.",
            "MAIN-PARA.",
            'DISPLAY "FIRST".',
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. SECOND.",
            "PROCEDURE DIVISION.",
            "MAIN-PARA.",
            'DISPLAY "SECOND".',
        ]
        segments = _split_programs(lines)
        assert len(segments) == 2
        assert any("FIRST" in ln for ln in segments[0])
        assert any("SECOND" in ln for ln in segments[1])

    def test_end_program_lines_stripped(self):
        lines = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. OUTER.",
            "PROCEDURE DIVISION.",
            'DISPLAY "OUTER".',
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. INNER.",
            "PROCEDURE DIVISION.",
            'DISPLAY "INNER".',
            "END PROGRAM INNER.",
            "END PROGRAM OUTER.",
        ]
        segments = _split_programs(lines)
        assert len(segments) == 2
        # No END PROGRAM lines should survive in either segment
        for seg in segments:
            for ln in seg:
                assert not ln.strip().upper().startswith("END PROGRAM"), (
                    f"END PROGRAM not stripped: {ln}"
                )

    def test_empty_input(self):
        assert _split_programs([]) == [[]]

    def test_three_concatenated_programs(self):
        lines = [
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. A.",
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. B.",
            "IDENTIFICATION DIVISION.",
            "PROGRAM-ID. C.",
        ]
        segments = _split_programs(lines)
        assert len(segments) == 3


# ---------------------------------------------------------------------------
# Parser: parse_cobol with multi-program source
# ---------------------------------------------------------------------------

class TestParseCobolMultiProgram:
    """Integration tests for parse_cobol with multiple programs."""

    NESTED_SOURCE = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. OUTER-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X(10).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        '           DISPLAY "OUTER".\n'
        "\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. INNER-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-B PIC 9(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       INNER-PARA.\n"
        '           DISPLAY "INNER".\n'
        "       END PROGRAM INNER-PROG.\n"
        "       END PROGRAM OUTER-PROG.\n"
    )

    def test_outer_program_id(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        assert prog.program_id == "OUTER-PROG"

    def test_nested_programs_populated(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        assert len(prog.nested_programs) == 1

    def test_inner_program_id(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        inner = prog.nested_programs[0]
        assert inner.program_id == "INNER-PROG"

    def test_outer_has_its_own_data(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        ws_names = [item.name for item in prog.working_storage]
        assert "WS-A" in ws_names

    def test_inner_has_its_own_data(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        inner = prog.nested_programs[0]
        ws_names = [item.name for item in inner.working_storage]
        assert "WS-B" in ws_names

    def test_outer_paragraphs(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        para_names = [p.name for p in prog.paragraphs]
        assert "MAIN-PARA" in para_names

    def test_inner_paragraphs(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        inner = prog.nested_programs[0]
        para_names = [p.name for p in inner.paragraphs]
        assert "INNER-PARA" in para_names


class TestSingleProgramBackwardCompat:
    """Verify that single-program sources are unaffected."""

    SINGLE_SOURCE = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SIMPLE.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-X PIC X(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        '           DISPLAY "HELLO".\n'
        "           STOP RUN.\n"
    )

    def test_nested_programs_empty(self):
        prog = parse_cobol(self.SINGLE_SOURCE)
        assert prog.nested_programs == []

    def test_program_id(self):
        prog = parse_cobol(self.SINGLE_SOURCE)
        assert prog.program_id == "SIMPLE"

    def test_working_storage_present(self):
        prog = parse_cobol(self.SINGLE_SOURCE)
        assert len(prog.working_storage) >= 1


# ---------------------------------------------------------------------------
# Mapper: generate_python with nested programs
# ---------------------------------------------------------------------------

class TestMapperNestedPrograms:
    """Verify that generate_python produces valid multi-class Python."""

    NESTED_SOURCE = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. OUTER-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-A PIC X(10).\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        '           DISPLAY "OUTER".\n'
        "           STOP RUN.\n"
        "\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. INNER-PROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-B PIC 9(5).\n"
        "       PROCEDURE DIVISION.\n"
        "       INNER-PARA.\n"
        '           DISPLAY "INNER".\n'
        "           STOP RUN.\n"
        "       END PROGRAM INNER-PROG.\n"
        "       END PROGRAM OUTER-PROG.\n"
    )

    def test_valid_python(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        # Must parse without SyntaxError
        ast.parse(py_source)

    def test_contains_outer_class(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        assert "class OuterProgProgram" in py_source or "class OuterprogProgram" in py_source

    def test_contains_inner_class(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        assert "class InnerProgProgram" in py_source or "class InnerprogProgram" in py_source

    def test_nested_separator_comment(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        assert "Nested/concatenated program: INNER-PROG" in py_source

    def test_single_main_block(self):
        prog = parse_cobol(self.NESTED_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        count = py_source.count('if __name__ == "__main__"')
        assert count == 1, f"Expected 1 main block, found {count}"

    def test_single_program_still_valid(self):
        """Single-program input through generate_python still works."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SOLO.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            '           DISPLAY "SOLO".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)
        assert 'if __name__ == "__main__"' in py_source


class TestMapperGlobalHint:
    """Verify GLOBAL data items produce a TODO hint for nested programs."""

    GLOBAL_SOURCE = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. OUTER.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-SHARED PIC X(10) GLOBAL.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        '           DISPLAY "OUTER".\n'
        "\n"
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. INNER.\n"
        "       PROCEDURE DIVISION.\n"
        "       INNER-PARA.\n"
        '           DISPLAY "INNER".\n'
        "       END PROGRAM INNER.\n"
        "       END PROGRAM OUTER.\n"
    )

    def test_global_todo_emitted(self):
        prog = parse_cobol(self.GLOBAL_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        assert "GLOBAL data items from outer program" in py_source
        assert "WS-SHARED" in py_source

    def test_valid_python(self):
        prog = parse_cobol(self.GLOBAL_SOURCE)
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)


# ---------------------------------------------------------------------------
# Behavioral: execute generated Python in subprocess
# ---------------------------------------------------------------------------

class TestNestedProgramBehavioral:
    """End-to-end: translate, execute, verify stdout."""

    def test_outer_program_runs(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. OUTER.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            '           DISPLAY "HELLO FROM OUTER".\n'
            "           STOP RUN.\n"
            "\n"
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. INNER.\n"
            "       PROCEDURE DIVISION.\n"
            "       INNER-PARA.\n"
            '           DISPLAY "HELLO FROM INNER".\n'
            "           STOP RUN.\n"
            "       END PROGRAM INNER.\n"
            "       END PROGRAM OUTER.\n"
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py_source = generate_python(smap)

        fd, tmp = tempfile.mkstemp(suffix=".py", dir=".")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(py_source)
            result = subprocess.run(
                [sys.executable, tmp],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "PYTHONPATH": _PROJECT_SRC},
            )
            assert result.returncode == 0, (
                f"rc={result.returncode}\nstderr: {result.stderr}\nsource:\n{py_source}"
            )
            # Only the outer program runs via __main__
            assert "HELLO FROM OUTER" in result.stdout
        finally:
            os.unlink(tmp)

    def test_three_concatenated_programs_valid_python(self):
        """Three concatenated programs produce valid Python with three classes."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG-A.\n"
            "       PROCEDURE DIVISION.\n"
            "       A-PARA.\n"
            '           DISPLAY "A".\n'
            "           STOP RUN.\n"
            "\n"
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG-B.\n"
            "       PROCEDURE DIVISION.\n"
            "       B-PARA.\n"
            '           DISPLAY "B".\n'
            "           STOP RUN.\n"
            "\n"
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PROG-C.\n"
            "       PROCEDURE DIVISION.\n"
            "       C-PARA.\n"
            '           DISPLAY "C".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        assert len(prog.nested_programs) == 2
        assert prog.program_id == "PROG-A"
        assert prog.nested_programs[0].program_id == "PROG-B"
        assert prog.nested_programs[1].program_id == "PROG-C"

        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)  # must be syntactically valid

        # Verify all three programs are present as classes
        assert "ProgA" in py_source or "Proga" in py_source
        assert "ProgB" in py_source or "Progb" in py_source
        assert "ProgC" in py_source or "Progc" in py_source
