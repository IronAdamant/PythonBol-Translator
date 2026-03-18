"""Behavioral tests: translate COBOL to Python, execute, verify stdout.

Each test writes a COBOL program with KNOWN expected output, translates it
through the full pipeline (parse -> analyze -> generate), executes the
generated Python in a subprocess, and asserts on stdout.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from conftest import make_cobol
from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol

_PROJECT_SRC = str(Path(__file__).resolve().parent.parent / "src")


def _run_cobol_program(cobol_source: str) -> str:
    """Translate COBOL to Python, execute in subprocess, return stdout."""
    prog = parse_cobol(cobol_source)
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
        if result.returncode != 0:
            pytest.fail(
                f"Generated Python exited with rc={result.returncode}\n"
                f"stderr: {result.stderr}\n"
                f"source:\n{py_source}"
            )
        return result.stdout
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# 1. Hello World — simplest possible DISPLAY
# ---------------------------------------------------------------------------
class TestHelloWorld:
    def test_hello_world(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. HELLO.\n"
            "       DATA DIVISION.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            '           DISPLAY "HELLO WORLD".\n'
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        assert "HELLO WORLD" in stdout


# ---------------------------------------------------------------------------
# 2. Arithmetic — ADD, SUBTRACT, MULTIPLY GIVING
# ---------------------------------------------------------------------------
class TestArithmetic:
    def test_add_subtract_multiply(self):
        src = make_cobol(
            [
                "ADD WS-A TO WS-B.",
                "DISPLAY WS-B.",
                "SUBTRACT 5 FROM WS-A.",
                "DISPLAY WS-A.",
                "MULTIPLY WS-A BY WS-B GIVING WS-C.",
                "DISPLAY WS-C.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
                "       01 WS-B PIC 9(5) VALUE 3.",
                "       01 WS-C PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        # ADD 10 TO 3 -> 13
        assert lines[0].strip() == "13"
        # SUBTRACT 5 FROM 10 -> 5
        assert lines[1].strip() == "5"
        # MULTIPLY 5 BY 13 GIVING WS-C -> 65
        assert lines[2].strip() == "65"


# ---------------------------------------------------------------------------
# 3. MOVE and DISPLAY — field assignments
# ---------------------------------------------------------------------------
class TestMoveAndDisplay:
    def test_move_numeric(self):
        src = make_cobol(
            [
                "MOVE 42 TO WS-A.",
                "DISPLAY WS-A.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "42" in stdout

    def test_move_between_fields(self):
        src = make_cobol(
            [
                "MOVE WS-B TO WS-A.",
                "DISPLAY WS-A.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 0.",
                "       01 WS-B PIC 9(5) VALUE 99.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "99" in stdout

    def test_move_string(self):
        src = make_cobol(
            [
                'MOVE "COBOL" TO WS-NAME.',
                "DISPLAY WS-NAME.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-NAME PIC X(10) VALUE SPACES.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "COBOL" in stdout


# ---------------------------------------------------------------------------
# 4. IF/ELSE — conditional branching
# ---------------------------------------------------------------------------
class TestIfElse:
    def test_if_true_branch(self):
        src = make_cobol(
            [
                "IF WS-A > 5",
                '    DISPLAY "YES"',
                "ELSE",
                '    DISPLAY "NO"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "YES" in stdout
        assert "NO" not in stdout

    def test_if_false_branch(self):
        src = make_cobol(
            [
                "IF WS-A > 5",
                '    DISPLAY "YES"',
                "ELSE",
                '    DISPLAY "NO"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 2.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "NO" in stdout
        assert "YES" not in stdout


# ---------------------------------------------------------------------------
# 5. PERFORM loop — paragraph called N TIMES
# ---------------------------------------------------------------------------
class TestPerformLoop:
    def test_perform_n_times(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-LOOP.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-COUNT PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM COUNT-PARA 5 TIMES.\n"
            "           DISPLAY WS-COUNT.\n"
            "           STOP RUN.\n"
            "       COUNT-PARA.\n"
            "           ADD 1 TO WS-COUNT.\n"
        )
        stdout = _run_cobol_program(src)
        assert "5" in stdout

    def test_perform_displays_each_iteration(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-LOOP2.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-I PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM SHOW-PARA 3 TIMES.\n"
            "           STOP RUN.\n"
            "       SHOW-PARA.\n"
            "           ADD 1 TO WS-I.\n"
            "           DISPLAY WS-I.\n"
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert len(lines) == 3
        assert lines[0].strip() == "1"
        assert lines[1].strip() == "2"
        assert lines[2].strip() == "3"


# ---------------------------------------------------------------------------
# 6. String operations — STRING verb and INSPECT TALLYING
# ---------------------------------------------------------------------------
class TestStringOperations:
    def test_string_concatenation(self):
        src = make_cobol(
            [
                "STRING WS-FIRST DELIMITED BY SIZE",
                "       WS-SECOND DELIMITED BY SIZE",
                "       INTO WS-RESULT",
                "       WITH POINTER WS-PTR.",
                "DISPLAY WS-RESULT.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-FIRST PIC X(5) VALUE "HELLO".',
                '       01 WS-SECOND PIC X(6) VALUE " WORLD".',
                "       01 WS-RESULT PIC X(20) VALUE SPACES.",
                "       01 WS-PTR PIC 9(3) VALUE 1.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "HELLO WORLD" in stdout

    def test_inspect_tallying(self):
        src = make_cobol(
            [
                "INSPECT WS-TEXT TALLYING WS-COUNT",
                '    FOR ALL "LL".',
                "DISPLAY WS-COUNT.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(20) VALUE "HELLO WORLD HELLO".',
                "       01 WS-COUNT PIC 9(3) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        # "HELLO WORLD HELLO" contains "LL" twice (in each HELLO)
        assert "2" in stdout


# ---------------------------------------------------------------------------
# 7. EVALUATE TRUE — case selection
# ---------------------------------------------------------------------------
class TestEvaluate:
    def test_evaluate_true_selects_correct_when(self):
        src = make_cobol(
            [
                "EVALUATE TRUE",
                "    WHEN WS-GRADE >= 90",
                '        DISPLAY "A"',
                "    WHEN WS-GRADE >= 80",
                '        DISPLAY "B"',
                "    WHEN WS-GRADE >= 70",
                '        DISPLAY "C"',
                "    WHEN OTHER",
                '        DISPLAY "F"',
                "END-EVALUATE.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-GRADE PIC 9(3) VALUE 85.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "B"

    def test_evaluate_other_branch(self):
        src = make_cobol(
            [
                "EVALUATE TRUE",
                "    WHEN WS-GRADE >= 90",
                '        DISPLAY "A"',
                "    WHEN WS-GRADE >= 80",
                '        DISPLAY "B"',
                "    WHEN OTHER",
                '        DISPLAY "F"',
                "END-EVALUATE.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-GRADE PIC 9(3) VALUE 50.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "F"

    def test_evaluate_variable_equality(self):
        src = make_cobol(
            [
                "EVALUATE WS-CODE",
                "    WHEN 1",
                '        DISPLAY "ONE"',
                "    WHEN 2",
                '        DISPLAY "TWO"',
                "    WHEN OTHER",
                '        DISPLAY "OTHER"',
                "END-EVALUATE.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-CODE PIC 9(1) VALUE 2.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "TWO"


# ---------------------------------------------------------------------------
# 8. 88-level conditions — condition names in IF
# ---------------------------------------------------------------------------
class TestLevel88Conditions:
    def test_88_active_condition(self):
        src = make_cobol(
            [
                "IF STATUS-ACTIVE",
                '    DISPLAY "ACTIVE"',
                "ELSE",
                '    DISPLAY "INACTIVE"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-STATUS PIC 9(1) VALUE 1.",
                "           88 STATUS-ACTIVE VALUE 1.",
                "           88 STATUS-INACTIVE VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "ACTIVE" in stdout
        # Should NOT contain INACTIVE (only the true branch)
        assert stdout.strip() == "ACTIVE"

    def test_88_inactive_condition(self):
        src = make_cobol(
            [
                "IF STATUS-INACTIVE",
                '    DISPLAY "OFF"',
                "ELSE",
                '    DISPLAY "ON"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-STATUS PIC 9(1) VALUE 0.",
                "           88 STATUS-ACTIVE VALUE 1.",
                "           88 STATUS-INACTIVE VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "OFF"
