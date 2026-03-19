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


# ---------------------------------------------------------------------------
# 9. COMPUTE — complex arithmetic expressions
# ---------------------------------------------------------------------------
class TestComputeArithmetic:
    def test_compute_arithmetic_expressions(self):
        """COMPUTE with parenthesized arithmetic: (10 + 5) * 4 / 2 = 30."""
        src = make_cobol(
            [
                "COMPUTE WS-RESULT = (WS-A + WS-B) * WS-C / 2.",
                "DISPLAY WS-RESULT.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
                "       01 WS-B PIC 9(5) VALUE 5.",
                "       01 WS-C PIC 9(5) VALUE 4.",
                "       01 WS-RESULT PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "30"

    def test_compute_subtraction_and_multiply(self):
        """COMPUTE with subtraction and multiplication: (20 - 8) * 3 = 36."""
        src = make_cobol(
            [
                "COMPUTE WS-RESULT = (WS-A - WS-B) * WS-C.",
                "DISPLAY WS-RESULT.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 20.",
                "       01 WS-B PIC 9(5) VALUE 8.",
                "       01 WS-C PIC 9(5) VALUE 3.",
                "       01 WS-RESULT PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "36"


# ---------------------------------------------------------------------------
# 10. PERFORM VARYING — loop with counter
# ---------------------------------------------------------------------------
class TestPerformVarying:
    def test_perform_varying_loop(self):
        """PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5 displays 1..5."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. VARY-TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-I PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM SHOW-PARA VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > 5.\n"
            "           STOP RUN.\n"
            "       SHOW-PARA.\n"
            "           DISPLAY WS-I.\n"
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert len(lines) == 5
        for i, line in enumerate(lines, start=1):
            assert line.strip() == str(i)


# ---------------------------------------------------------------------------
# 11. PERFORM UNTIL — paragraph called until condition met
# ---------------------------------------------------------------------------
class TestPerformUntil:
    def test_perform_until(self):
        """PERFORM ADD-LOOP UNTIL WS-COUNT > 3 displays 1, 2, 3, 4."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. UNTIL-TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-COUNT PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM ADD-LOOP UNTIL WS-COUNT > 3.\n"
            "           STOP RUN.\n"
            "       ADD-LOOP.\n"
            "           ADD 1 TO WS-COUNT.\n"
            "           DISPLAY WS-COUNT.\n"
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        # Loop body executes 4 times: count goes 1, 2, 3, 4
        # After count=4 the condition (WS-COUNT > 3) is true, loop stops
        assert len(lines) == 4
        assert lines[0].strip() == "1"
        assert lines[1].strip() == "2"
        assert lines[2].strip() == "3"
        assert lines[3].strip() == "4"


# ---------------------------------------------------------------------------
# 12. Nested IF — multi-level conditional
# ---------------------------------------------------------------------------
class TestNestedIf:
    def test_nested_if_both_true(self):
        """Nested IF: A>5 and B>10 both true displays BOTH."""
        src = make_cobol(
            [
                "IF WS-A > 5",
                "    IF WS-B > 10",
                '        DISPLAY "BOTH"',
                "    ELSE",
                '        DISPLAY "ONLY-A"',
                "    END-IF",
                "ELSE",
                '    DISPLAY "NEITHER"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
                "       01 WS-B PIC 9(5) VALUE 15.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "BOTH"

    def test_nested_if_only_outer_true(self):
        """Nested IF: A>5 true but B>10 false displays ONLY-A."""
        src = make_cobol(
            [
                "IF WS-A > 5",
                "    IF WS-B > 10",
                '        DISPLAY "BOTH"',
                "    ELSE",
                '        DISPLAY "ONLY-A"',
                "    END-IF",
                "ELSE",
                '    DISPLAY "NEITHER"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
                "       01 WS-B PIC 9(5) VALUE 3.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "ONLY-A"

    def test_nested_if_outer_false(self):
        """Nested IF: A>5 false displays NEITHER (inner never checked)."""
        src = make_cobol(
            [
                "IF WS-A > 5",
                "    IF WS-B > 10",
                '        DISPLAY "BOTH"',
                "    ELSE",
                '        DISPLAY "ONLY-A"',
                "    END-IF",
                "ELSE",
                '    DISPLAY "NEITHER"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 2.",
                "       01 WS-B PIC 9(5) VALUE 99.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "NEITHER"


# ---------------------------------------------------------------------------
# 13. MOVE numeric to alphanumeric — type coercion
# ---------------------------------------------------------------------------
class TestMoveNumericToAlpha:
    def test_move_numeric_to_alphanumeric(self):
        """MOVE a numeric value into a PIC X field, verify it appears."""
        src = make_cobol(
            [
                "MOVE WS-NUM TO WS-STR.",
                "DISPLAY WS-STR.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-NUM PIC 9(5) VALUE 42.",
                "       01 WS-STR PIC X(10) VALUE SPACES.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "42" in stdout


# ---------------------------------------------------------------------------
# 14. SUBTRACT FROM GIVING — verify result placed in third field
# ---------------------------------------------------------------------------
class TestSubtractGiving:
    def test_subtract_from_giving(self):
        """SUBTRACT 3 FROM 10 GIVING WS-C = 7."""
        src = make_cobol(
            [
                "SUBTRACT WS-A FROM WS-B GIVING WS-C.",
                "DISPLAY WS-C.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 3.",
                "       01 WS-B PIC 9(5) VALUE 10.",
                "       01 WS-C PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "7"


# ---------------------------------------------------------------------------
# 15. DIVIDE GIVING REMAINDER — quotient and remainder
# ---------------------------------------------------------------------------
class TestDivideGivingRemainder:
    def test_divide_giving_remainder(self):
        """DIVIDE 17 BY 5 GIVING WS-Q REMAINDER WS-R -> Q=3, R=2."""
        src = make_cobol(
            [
                "DIVIDE WS-A BY WS-B GIVING WS-Q REMAINDER WS-R.",
                "DISPLAY WS-Q.",
                "DISPLAY WS-R.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 17.",
                "       01 WS-B PIC 9(5) VALUE 5.",
                "       01 WS-Q PIC 9(5) VALUE 0.",
                "       01 WS-R PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert lines[0].strip() == "3"
        assert lines[1].strip() == "2"

    def test_divide_giving_no_remainder(self):
        """DIVIDE 20 INTO 4 GIVING WS-C -> 20 / 4 = 5."""
        src = make_cobol(
            [
                "DIVIDE WS-A INTO WS-B GIVING WS-C.",
                "DISPLAY WS-C.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 4.",
                "       01 WS-B PIC 9(5) VALUE 20.",
                "       01 WS-C PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "5"


# ---------------------------------------------------------------------------
# 16. STRING DELIMITED BY — concatenation with delimiter trimming
# ---------------------------------------------------------------------------
class TestStringDelimited:
    def test_string_delimited_by_space(self):
        """STRING with DELIMITED BY SPACE trims source at first space."""
        src = make_cobol(
            [
                "STRING WS-FIRST DELIMITED BY SPACE",
                '       WS-LAST DELIMITED BY SIZE',
                "       INTO WS-RESULT.",
                "DISPLAY WS-RESULT.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-FIRST PIC X(10) VALUE "JOHN      ".',
                '       01 WS-LAST PIC X(10) VALUE "DOE".',
                "       01 WS-RESULT PIC X(20) VALUE SPACES.",
            ],
        )
        stdout = _run_cobol_program(src)
        # DELIMITED BY SPACE takes "JOHN" (before first space),
        # then concatenates "DOE       " (DELIMITED BY SIZE = whole field)
        assert "JOHNDOE" in stdout


# ---------------------------------------------------------------------------
# 17. INSPECT REPLACING ALL — character substitution
# ---------------------------------------------------------------------------
class TestInspectReplacing:
    def test_inspect_replacing_all(self):
        """INSPECT REPLACING ALL 'A' BY 'X' in 'BANANA' -> 'BXNXNX'."""
        src = make_cobol(
            [
                'INSPECT WS-TEXT REPLACING ALL "A" BY "X".',
                "DISPLAY WS-TEXT.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(20) VALUE "BANANA".',
            ],
        )
        stdout = _run_cobol_program(src)
        assert "BXNXNX" in stdout


# ---------------------------------------------------------------------------
# 18. SEARCH table — indexed table lookup
# ---------------------------------------------------------------------------
class TestSearchTable:
    def test_search_table(self):
        """SEARCH an OCCURS table for a matching element."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SEARCH-TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 5 TIMES.\n"
            "               10 WS-ID PIC 9(3).\n"
            "       01 WS-INDEX PIC 9(3) VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 101 TO WS-ID(1).\n"
            "           MOVE 102 TO WS-ID(2).\n"
            "           MOVE 103 TO WS-ID(3).\n"
            "           SEARCH WS-ENTRY\n"
            '               AT END DISPLAY "NOT FOUND"\n'
            "               WHEN WS-ID(WS-INDEX) = 102\n"
            '                   DISPLAY "FOUND"\n'
            "           END-SEARCH.\n"
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        assert "FOUND" in stdout


# ---------------------------------------------------------------------------
# 19. SORT verb — file-based sorting
# ---------------------------------------------------------------------------
class TestSortVerb:
    def test_sort_input_output_procedure(self):
        """SORT with INPUT/OUTPUT PROCEDURE: CHERRY,APPLE,BANANA → sorted."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SORT-TEST.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT SORT-FILE ASSIGN TO SORTWORK.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       SD SORT-FILE.\n"
            "       01 SORT-REC PIC X(10).\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-OUT PIC X(10) VALUE SPACES.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           SORT SORT-FILE ON ASCENDING KEY SORT-REC\n"
            "               INPUT PROCEDURE IS LOAD-DATA\n"
            "               OUTPUT PROCEDURE IS SHOW-DATA.\n"
            "           STOP RUN.\n"
            "       LOAD-DATA.\n"
            '           MOVE "CHERRY" TO SORT-REC.\n'
            "           RELEASE SORT-REC.\n"
            '           MOVE "APPLE" TO SORT-REC.\n'
            "           RELEASE SORT-REC.\n"
            '           MOVE "BANANA" TO SORT-REC.\n'
            "           RELEASE SORT-REC.\n"
            "       SHOW-DATA.\n"
            "           RETURN SORT-FILE INTO WS-OUT.\n"
            "           DISPLAY WS-OUT.\n"
            "           RETURN SORT-FILE INTO WS-OUT.\n"
            "           DISPLAY WS-OUT.\n"
            "           RETURN SORT-FILE INTO WS-OUT.\n"
            "           DISPLAY WS-OUT.\n"
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert len(lines) == 3
        assert "APPLE" in lines[0]
        assert "BANANA" in lines[1]
        assert "CHERRY" in lines[2]


# ---------------------------------------------------------------------------
# 20. FUNCTION LENGTH — string length intrinsic
# ---------------------------------------------------------------------------
class TestFunctionLength:
    def test_function_length(self):
        """COMPUTE using FUNCTION LENGTH returns correct string length.

        WS-TEXT is PIC X(15) with value 'HELLO WORLD', padded to 15 chars.
        FUNCTION LENGTH returns the PIC size (15), not the trimmed length.
        """
        src = make_cobol(
            [
                "COMPUTE WS-LEN = FUNCTION LENGTH(WS-TEXT).",
                "DISPLAY WS-LEN.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(15) VALUE "HELLO WORLD".',
                "       01 WS-LEN PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        # len(str(value)) where value is space-padded to 15 characters
        assert stdout.strip() == "15"


# ---------------------------------------------------------------------------
# 21. FUNCTION UPPER-CASE — case conversion intrinsic
# ---------------------------------------------------------------------------
class TestFunctionUpperCase:
    def test_function_upper_case(self):
        """COMPUTE with FUNCTION UPPER-CASE converts to uppercase."""
        src = make_cobol(
            [
                "COMPUTE WS-RESULT = FUNCTION UPPER-CASE(WS-TEXT).",
                "DISPLAY WS-RESULT.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(10) VALUE "hello".',
                "       01 WS-RESULT PIC X(10) VALUE SPACES.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "HELLO" in stdout


# ---------------------------------------------------------------------------
# 22. Signed arithmetic — S9 field with negative values
# ---------------------------------------------------------------------------
class TestSignedArithmetic:
    def test_signed_add_negative(self):
        """S9(5) field: ADD negative value, verify signed result."""
        src = make_cobol(
            [
                "ADD WS-NEG TO WS-VAL.",
                "DISPLAY WS-VAL.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-VAL PIC S9(5) VALUE 100.",
                "       01 WS-NEG PIC S9(5) VALUE -30.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "70"

    def test_signed_subtract_to_negative(self):
        """Subtract larger value from smaller, result should be negative."""
        src = make_cobol(
            [
                "SUBTRACT WS-B FROM WS-A.",
                "DISPLAY WS-A.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC S9(5) VALUE 10.",
                "       01 WS-B PIC S9(5) VALUE 25.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert "-15" in stdout


# ---------------------------------------------------------------------------
# 23. UNSTRING — split delimited string
# ---------------------------------------------------------------------------
class TestUnstring:
    def test_unstring_delimited(self):
        """UNSTRING with DELIMITED BY splits into multiple targets."""
        src = make_cobol(
            [
                'UNSTRING WS-INPUT DELIMITED BY ","',
                "    INTO WS-FIRST WS-SECOND WS-THIRD.",
                "DISPLAY WS-FIRST.",
                "DISPLAY WS-SECOND.",
                "DISPLAY WS-THIRD.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-INPUT PIC X(20) VALUE "ALPHA,BETA,GAMMA".',
                "       01 WS-FIRST PIC X(10) VALUE SPACES.",
                "       01 WS-SECOND PIC X(10) VALUE SPACES.",
                "       01 WS-THIRD PIC X(10) VALUE SPACES.",
            ],
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert "ALPHA" in lines[0]
        assert "BETA" in lines[1]
        assert "GAMMA" in lines[2]


# ---------------------------------------------------------------------------
# 24. PERFORM VARYING AFTER — nested 2-level loop
# ---------------------------------------------------------------------------
class TestPerformVaryingAfter:
    def test_varying_after_nested_loop(self):
        """2-level nested PERFORM VARYING: outer 1-3, inner 1-2 → 6 iterations."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. VARY-AFTER.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-I PIC 9(5) VALUE 0.\n"
            "       01 WS-J PIC 9(5) VALUE 0.\n"
            "       01 WS-COUNT PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM COUNT-PARA VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > 3\n"
            "               AFTER WS-J FROM 1 BY 1\n"
            "               UNTIL WS-J > 2.\n"
            "           DISPLAY WS-COUNT.\n"
            "           STOP RUN.\n"
            "       COUNT-PARA.\n"
            "           ADD 1 TO WS-COUNT.\n"
        )
        stdout = _run_cobol_program(src)
        # 3 outer * 2 inner = 6 iterations
        assert stdout.strip() == "6"


# ---------------------------------------------------------------------------
# 25. ACCEPT FROM DATE — YYMMDD format
# ---------------------------------------------------------------------------
class TestAcceptFromDate:
    def test_accept_from_date(self):
        """ACCEPT FROM DATE produces 6-digit YYMMDD string."""
        src = make_cobol(
            [
                "ACCEPT WS-DATE FROM DATE.",
                "DISPLAY WS-DATE.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-DATE PIC X(6) VALUE SPACES.",
            ],
        )
        stdout = _run_cobol_program(src)
        date_str = stdout.strip()
        # Should be exactly 6 digits in YYMMDD format
        assert len(date_str) == 6
        assert date_str.isdigit()


# ---------------------------------------------------------------------------
# 26. Decimal COMPUTE — PIC 9(3)V99 multiplication
# ---------------------------------------------------------------------------
class TestDecimalCompute:
    def test_decimal_multiplication(self):
        """COMPUTE with decimal fields: 12.50 * 3 = 37.50."""
        src = make_cobol(
            [
                "COMPUTE WS-RESULT = WS-PRICE * WS-QTY.",
                "DISPLAY WS-RESULT.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-PRICE PIC 9(3)V99 VALUE 12.50.",
                "       01 WS-QTY PIC 9(3) VALUE 3.",
                "       01 WS-RESULT PIC 9(5)V99 VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        # 12.50 * 3 = 37.50
        assert "37.5" in stdout


# ---------------------------------------------------------------------------
# 27. OCCURS table — MOVE to subscript, DISPLAY subscript
# ---------------------------------------------------------------------------
class TestOccursTableAccess:
    def test_occurs_move_and_display(self):
        """MOVE values into OCCURS table slots, then DISPLAY each."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TABLE-ACC.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ITEM OCCURS 3 TIMES.\n"
            "               10 WS-VAL PIC 9(3).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-VAL(1).\n"
            "           MOVE 20 TO WS-VAL(2).\n"
            "           MOVE 30 TO WS-VAL(3).\n"
            "           DISPLAY WS-VAL(1).\n"
            "           DISPLAY WS-VAL(2).\n"
            "           DISPLAY WS-VAL(3).\n"
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert lines[0].strip() == "10"
        assert lines[1].strip() == "20"
        assert lines[2].strip() == "30"

    def test_occurs_variable_subscript(self):
        """Access OCCURS table element via variable subscript."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. VAR-SUB.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ITEM OCCURS 5 TIMES.\n"
            "               10 WS-NUM PIC 9(3).\n"
            "       01 WS-IDX PIC 9(3) VALUE 3.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 100 TO WS-NUM(1).\n"
            "           MOVE 200 TO WS-NUM(2).\n"
            "           MOVE 300 TO WS-NUM(3).\n"
            "           DISPLAY WS-NUM(WS-IDX).\n"
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "300"

    def test_occurs_arithmetic_on_subscript(self):
        """ADD to a subscripted OCCURS element."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. ADD-SUB.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ITEM OCCURS 3 TIMES.\n"
            "               10 WS-AMT PIC 9(5).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 50 TO WS-AMT(2).\n"
            "           ADD 25 TO WS-AMT(2).\n"
            "           DISPLAY WS-AMT(2).\n"
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "75"


# ---------------------------------------------------------------------------
# 28. SEARCH with AT END — table lookup
# ---------------------------------------------------------------------------
class TestSearchWithAtEnd:
    def test_search_finds_element(self):
        """SEARCH finds matching element in OCCURS table."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SEARCH-FIND.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 5 TIMES.\n"
            "               10 WS-CODE PIC 9(3).\n"
            "       01 WS-IDX PIC 9(3) VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-CODE(1).\n"
            "           MOVE 20 TO WS-CODE(2).\n"
            "           MOVE 30 TO WS-CODE(3).\n"
            "           SEARCH WS-ENTRY\n"
            '               AT END DISPLAY "MISS"\n'
            "               WHEN WS-CODE(WS-IDX) = 20\n"
            '                   DISPLAY "HIT"\n'
            "           END-SEARCH.\n"
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        assert "HIT" in stdout
        assert "MISS" not in stdout

    def test_search_at_end_reached(self):
        """SEARCH falls through to AT END when element not found."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SEARCH-MISS.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-TABLE.\n"
            "           05 WS-ENTRY OCCURS 3 TIMES.\n"
            "               10 WS-CODE PIC 9(3).\n"
            "       01 WS-IDX PIC 9(3) VALUE 1.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           MOVE 10 TO WS-CODE(1).\n"
            "           MOVE 20 TO WS-CODE(2).\n"
            "           MOVE 30 TO WS-CODE(3).\n"
            "           SEARCH WS-ENTRY\n"
            '               AT END DISPLAY "MISS"\n'
            "               WHEN WS-CODE(WS-IDX) = 99\n"
            '                   DISPLAY "HIT"\n'
            "           END-SEARCH.\n"
            "           STOP RUN.\n"
        )
        stdout = _run_cobol_program(src)
        assert "MISS" in stdout
        assert "HIT" not in stdout


# ---------------------------------------------------------------------------
# 29. SORT USING/GIVING — file-based sort with real I/O
# ---------------------------------------------------------------------------
class TestSortUsingGiving:
    def test_sort_using_giving_file(self, tmp_path):
        """SORT with USING/GIVING: reads input file, sorts, writes output."""
        (tmp_path / "in.dat").write_text("CHERRY\nAPPLE\nBANANA\n")

        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SORT-FILE.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT INPUT-FILE ASSIGN TO 'in.dat'.\n"
            "           SELECT OUTPUT-FILE ASSIGN TO 'out.dat'.\n"
            "           SELECT SORT-FILE ASSIGN TO SORTWORK.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       FD INPUT-FILE.\n"
            "       01 INPUT-REC PIC X(10).\n"
            "       FD OUTPUT-FILE.\n"
            "       01 OUTPUT-REC PIC X(10).\n"
            "       SD SORT-FILE.\n"
            "       01 SORT-REC PIC X(10).\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-DUMMY PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           SORT SORT-FILE ON ASCENDING KEY SORT-REC\n"
            "               USING INPUT-FILE\n"
            "               GIVING OUTPUT-FILE.\n"
            '           DISPLAY "SORT DONE".\n'
            "           STOP RUN.\n"
        )
        # Run subprocess from tmp_path so relative file paths resolve
        prog = parse_cobol(src)
        smap = analyze(prog)
        py_source = generate_python(smap)
        py_file = tmp_path / "sort_test.py"
        py_file.write_text(py_source)
        result = subprocess.run(
            [sys.executable, str(py_file)],
            capture_output=True, text=True, timeout=10,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": _PROJECT_SRC},
        )
        assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}"
        assert "SORT DONE" in result.stdout
        result_lines = (tmp_path / "out.dat").read_text().strip().splitlines()
        assert len(result_lines) == 3
        assert "APPLE" in result_lines[0]
        assert "BANANA" in result_lines[1]
        assert "CHERRY" in result_lines[2]

    def test_sort_field_based_numeric_key(self, tmp_path):
        """SORT by numeric field within fixed-format records."""
        # Records: 5-char ID + 10-char name + 5-char amount = 20 chars
        (tmp_path / "in.dat").write_text(
            "00001ALICE     00300\n"
            "00002BOB       00100\n"
            "00003CAROL     00200\n"
        )
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. FIELD-SORT.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       INPUT-OUTPUT SECTION.\n"
            "       FILE-CONTROL.\n"
            "           SELECT IN-FILE ASSIGN TO 'in.dat'.\n"
            "           SELECT OUT-FILE ASSIGN TO 'out.dat'.\n"
            "           SELECT SORT-FILE ASSIGN TO SORTWORK.\n"
            "       DATA DIVISION.\n"
            "       FILE SECTION.\n"
            "       FD IN-FILE.\n"
            "       01 IN-REC PIC X(20).\n"
            "       FD OUT-FILE.\n"
            "       01 OUT-REC PIC X(20).\n"
            "       SD SORT-FILE.\n"
            "       01 SORT-REC.\n"
            "           05 S-ID PIC 9(5).\n"
            "           05 S-NAME PIC X(10).\n"
            "           05 S-AMT PIC 9(5).\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC X.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           SORT SORT-FILE ON ASCENDING KEY S-AMT\n"
            "               USING IN-FILE\n"
            "               GIVING OUT-FILE.\n"
            '           DISPLAY "FIELD SORT DONE".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py_source = generate_python(smap)
        py_file = tmp_path / "field_sort.py"
        py_file.write_text(py_source)
        result = subprocess.run(
            [sys.executable, str(py_file)],
            capture_output=True, text=True, timeout=10,
            cwd=str(tmp_path),
            env={**os.environ, "PYTHONPATH": _PROJECT_SRC},
        )
        assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}"
        assert "FIELD SORT DONE" in result.stdout
        out_lines = (tmp_path / "out.dat").read_text().strip().splitlines()
        assert len(out_lines) == 3
        # Sorted by S-AMT ascending: 100, 200, 300
        assert "BOB" in out_lines[0]       # amount 100
        assert "CAROL" in out_lines[1]     # amount 200
        assert "ALICE" in out_lines[2]     # amount 300


# ---------------------------------------------------------------------------
# 30. PERFORM THRU — call paragraph range A through C
# ---------------------------------------------------------------------------
class TestPerformThru:
    def test_perform_thru_calls_range(self):
        """PERFORM A THRU C should call paragraphs A, B, C in sequence."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. THRU-TEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-X PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM STEP-A THRU STEP-C.\n"
            "           STOP RUN.\n"
            "       STEP-A.\n"
            '           DISPLAY "A".\n'
            "       STEP-B.\n"
            '           DISPLAY "B".\n'
            "       STEP-C.\n"
            '           DISPLAY "C".\n'
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert len(lines) == 3
        assert lines[0].strip() == "A"
        assert lines[1].strip() == "B"
        assert lines[2].strip() == "C"


# ---------------------------------------------------------------------------
# 31. DISPLAY WITH NO ADVANCING — suppress newline
# ---------------------------------------------------------------------------
class TestDisplayNoAdvancing:
    def test_no_advancing_suppresses_newline(self):
        """DISPLAY ... WITH NO ADVANCING should not add newline."""
        src = make_cobol(
            [
                'DISPLAY "A" WITH NO ADVANCING.',
                'DISPLAY "B" WITH NO ADVANCING.',
                'DISPLAY "C".',
                "STOP RUN.",
            ],
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        # A, B concatenated on same line, then C on same line
        assert lines[0].strip() == "ABC"


# ---------------------------------------------------------------------------
# 32. Deep nested IF — 3 levels
# ---------------------------------------------------------------------------
class TestDeepNestedIf:
    def test_three_level_nested_if(self):
        """3-level nested IF: all conditions true → innermost branch."""
        src = make_cobol(
            [
                "IF WS-A > 5",
                "    IF WS-B > 10",
                "        IF WS-C > 20",
                '            DISPLAY "DEEP"',
                "        ELSE",
                '            DISPLAY "MID"',
                "        END-IF",
                "    END-IF",
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
                "       01 WS-B PIC 9(5) VALUE 15.",
                "       01 WS-C PIC 9(5) VALUE 25.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "DEEP"

    def test_three_level_nested_if_middle_false(self):
        """3-level nested IF: middle condition false → no output."""
        src = make_cobol(
            [
                "IF WS-A > 5",
                "    IF WS-B > 10",
                "        IF WS-C > 20",
                '            DISPLAY "DEEP"',
                "        ELSE",
                '            DISPLAY "MID"',
                "        END-IF",
                "    ELSE",
                '        DISPLAY "SHALLOW"',
                "    END-IF",
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-A PIC 9(5) VALUE 10.",
                "       01 WS-B PIC 9(5) VALUE 5.",
                "       01 WS-C PIC 9(5) VALUE 25.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "SHALLOW"


# ---------------------------------------------------------------------------
# 33. 3-level PERFORM VARYING AFTER — triple nested loop
# ---------------------------------------------------------------------------
class TestPerformVaryingAfter3Level:
    def test_three_level_varying(self):
        """3-level PERFORM VARYING: 2 * 2 * 2 = 8 iterations."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. VARY3.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-I PIC 9(5) VALUE 0.\n"
            "       01 WS-J PIC 9(5) VALUE 0.\n"
            "       01 WS-K PIC 9(5) VALUE 0.\n"
            "       01 WS-COUNT PIC 9(5) VALUE 0.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           PERFORM COUNT-PARA VARYING WS-I FROM 1 BY 1\n"
            "               UNTIL WS-I > 2\n"
            "               AFTER WS-J FROM 1 BY 1\n"
            "               UNTIL WS-J > 2\n"
            "               AFTER WS-K FROM 1 BY 1\n"
            "               UNTIL WS-K > 2.\n"
            "           DISPLAY WS-COUNT.\n"
            "           STOP RUN.\n"
            "       COUNT-PARA.\n"
            "           ADD 1 TO WS-COUNT.\n"
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "8"


# ---------------------------------------------------------------------------
# 34. DIVIDE INTO — DIVIDE A INTO B means B = B / A
# ---------------------------------------------------------------------------
class TestDivideInto:
    def test_divide_into(self):
        """DIVIDE 5 INTO WS-B: WS-B = WS-B / 5 = 20 / 5 = 4."""
        src = make_cobol(
            [
                "DIVIDE 5 INTO WS-B.",
                "DISPLAY WS-B.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-B PIC 9(5) VALUE 20.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "4"


# ---------------------------------------------------------------------------
# 35. IS NUMERIC / IS ALPHABETIC — class conditions
# ---------------------------------------------------------------------------
class TestClassConditions:
    def test_is_numeric_true(self):
        """IS NUMERIC on digit string → true branch."""
        src = make_cobol(
            [
                "IF WS-TEXT IS NUMERIC",
                '    DISPLAY "YES"',
                "ELSE",
                '    DISPLAY "NO"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(5) VALUE "12345".',
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "YES"

    def test_is_numeric_false(self):
        """IS NUMERIC on alpha string → false branch."""
        src = make_cobol(
            [
                "IF WS-TEXT IS NUMERIC",
                '    DISPLAY "YES"',
                "ELSE",
                '    DISPLAY "NO"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(5) VALUE "HELLO".',
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "NO"

    def test_is_alphabetic_true(self):
        """IS ALPHABETIC on letter string → true branch."""
        src = make_cobol(
            [
                "IF WS-TEXT IS ALPHABETIC",
                '    DISPLAY "ALPHA"',
                "ELSE",
                '    DISPLAY "NOT"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=[
                '       01 WS-TEXT PIC X(5) VALUE "HELLO".',
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "ALPHA"


# ---------------------------------------------------------------------------
# 36. Sign conditions — POSITIVE, NEGATIVE, ZERO
# ---------------------------------------------------------------------------
class TestSignConditions:
    def test_is_positive(self):
        src = make_cobol(
            [
                "IF WS-A IS POSITIVE",
                '    DISPLAY "POS"',
                "ELSE",
                '    DISPLAY "NOT-POS"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=["       01 WS-A PIC S9(5) VALUE 10."],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "POS"

    def test_is_negative(self):
        src = make_cobol(
            [
                "IF WS-A IS NEGATIVE",
                '    DISPLAY "NEG"',
                "ELSE",
                '    DISPLAY "NOT-NEG"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=["       01 WS-A PIC S9(5) VALUE -5."],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "NEG"

    def test_is_zero(self):
        src = make_cobol(
            [
                "IF WS-A IS ZERO",
                '    DISPLAY "ZERO"',
                "ELSE",
                '    DISPLAY "NOT-ZERO"',
                "END-IF.",
                "STOP RUN.",
            ],
            data_lines=["       01 WS-A PIC S9(5) VALUE 0."],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "ZERO"


# ---------------------------------------------------------------------------
# 37. Inline PERFORM VARYING — statements inside the loop
# ---------------------------------------------------------------------------
class TestInlinePerformVarying:
    def test_inline_perform_varying_displays_each(self):
        """Inline PERFORM VARYING ... END-PERFORM should execute body in loop."""
        src = make_cobol(
            [
                "PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5",
                "    DISPLAY WS-I",
                "END-PERFORM.",
                "STOP RUN.",
            ],
            data_lines=["       01 WS-I PIC 9(5) VALUE 0."],
        )
        stdout = _run_cobol_program(src)
        lines = stdout.strip().splitlines()
        assert len(lines) == 5
        for i, line in enumerate(lines, start=1):
            assert line.strip() == str(i)

    def test_inline_perform_varying_nested(self):
        """Inline PERFORM VARYING with AFTER (nested inline loop)."""
        src = make_cobol(
            [
                "PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 2",
                "    AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 2",
                "    ADD 1 TO WS-COUNT",
                "END-PERFORM.",
                "DISPLAY WS-COUNT.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-I PIC 9(5) VALUE 0.",
                "       01 WS-J PIC 9(5) VALUE 0.",
                "       01 WS-COUNT PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        assert stdout.strip() == "4"

    def test_inline_perform_varying_with_arithmetic(self):
        """Inline PERFORM VARYING with ADD inside loop body."""
        src = make_cobol(
            [
                "PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 4",
                "    ADD WS-I TO WS-SUM",
                "END-PERFORM.",
                "DISPLAY WS-SUM.",
                "STOP RUN.",
            ],
            data_lines=[
                "       01 WS-I PIC 9(5) VALUE 0.",
                "       01 WS-SUM PIC 9(5) VALUE 0.",
            ],
        )
        stdout = _run_cobol_program(src)
        # Sum of 1+2+3+4 = 10
        assert stdout.strip() == "10"
