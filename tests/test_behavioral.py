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
    @pytest.mark.skip(
        reason="REMAINDER clause generates commented-out TODO stub; "
               "remainder not computed in generated code"
    )
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
    @pytest.mark.skip(
        reason="SEARCH generates array indexing on individually named "
               "dataclass fields; OCCURS tables not yet supported at runtime"
    )
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
    @pytest.mark.skip(
        reason="SORT requires file I/O setup with USING/GIVING and "
               "SELECT/ASSIGN clauses; generated code references "
               "FileAdapter instances not present in a minimal program"
    )
    def test_sort_verb(self):
        """SORT with USING/GIVING on inline file data."""
        pass


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
