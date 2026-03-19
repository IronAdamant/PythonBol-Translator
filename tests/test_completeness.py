"""Tests for completeness features: ACCEPT, REWRITE, EVALUATE ALSO,
MOVE CORRESPONDING, ON SIZE ERROR, MOVE ALL.
"""

from __future__ import annotations

import ast

from conftest import make_cobol
from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.io_translators import (
    translate_accept,
    translate_rewrite,
    wrap_on_size_error,
)


# ============================================================
# ACCEPT translation
# ============================================================

class TestAcceptTranslation:
    def test_accept_plain_generates_input(self):
        """Plain ACCEPT should generate input() call."""
        src = make_cobol(["ACCEPT WS-A."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "input()" in source

    def test_accept_from_date(self):
        result = translate_accept(["WS-DATE", "FROM", "DATE"], "ACCEPT WS-DATE FROM DATE")
        combined = " ".join(result)
        assert "datetime" in combined
        assert "strftime" in combined

    def test_accept_from_time(self):
        result = translate_accept(["WS-TIME", "FROM", "TIME"], "ACCEPT WS-TIME FROM TIME")
        combined = " ".join(result)
        assert "strftime" in combined

    def test_accept_from_day(self):
        result = translate_accept(["WS-DAY", "FROM", "DAY"], "ACCEPT WS-DAY FROM DAY")
        combined = " ".join(result)
        assert "datetime" in combined

    def test_accept_from_environment(self):
        result = translate_accept(
            ["WS-VAL", "FROM", "ENVIRONMENT-NAME", "PATH"],
            "ACCEPT WS-VAL FROM ENVIRONMENT-NAME PATH",
        )
        combined = " ".join(result)
        assert "environ" in combined

    def test_accept_from_command_line(self):
        result = translate_accept(
            ["WS-ARGS", "FROM", "COMMAND-LINE"],
            "ACCEPT WS-ARGS FROM COMMAND-LINE",
        )
        combined = " ".join(result)
        assert "sys" in combined or "argv" in combined

    def test_accept_no_ops(self):
        result = translate_accept([], "ACCEPT")
        assert any("no target" in r for r in result)

    def test_accept_produces_valid_python(self):
        """Full pipeline: ACCEPT should produce valid Python."""
        src = make_cobol(["ACCEPT WS-A FROM DATE."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        # Check code body (after the module docstring) has no TODO(high)
        # The header disclaimer mentions TODO(high) as guidance, which is expected
        body_start = source.find('class ')
        assert body_start != -1
        assert "TODO(high)" not in source[body_start:]


# ============================================================
# REWRITE translation
# ============================================================

class TestRewriteTranslation:
    def test_rewrite_generates_write(self):
        result = translate_rewrite(["CUSTOMER-RECORD"])
        combined = " ".join(result)
        assert ".write(" in combined

    def test_rewrite_from_clause(self):
        result = translate_rewrite(["CUSTOMER-RECORD", "FROM", "WS-BUFFER"])
        combined = " ".join(result)
        assert "ws_buffer" in combined
        assert ".write(" in combined

    def test_rewrite_no_ops(self):
        result = translate_rewrite([])
        assert any("no record" in r for r in result)

    def test_rewrite_valid_python(self):
        src = make_cobol(["REWRITE WS-A."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert ".write(" in source


# ============================================================
# EVALUATE TRUE ALSO TRUE
# ============================================================

class TestEvaluateAlso:
    def test_evaluate_also_basic(self):
        """EVALUATE subj1 ALSO subj2 should generate AND conditions."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       01 WS-B PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           EVALUATE WS-A ALSO WS-B",
            "           WHEN 1 ALSO 2",
            "              DISPLAY 'MATCH'",
            "           WHEN OTHER",
            "              DISPLAY 'NO MATCH'",
            "           END-EVALUATE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "and" in source  # multi-subject produces AND
        assert "else:" in source  # WHEN OTHER

    def test_evaluate_true_also_true(self):
        """EVALUATE TRUE ALSO TRUE should treat each as condition."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       01 WS-B PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           EVALUATE TRUE ALSO TRUE",
            "           WHEN WS-A = 1 ALSO WS-B = 2",
            "              DISPLAY 'BOTH'",
            "           END-EVALUATE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "if" in source

    def test_evaluate_also_with_any(self):
        """WHEN x ALSO ANY should ignore the ANY subject."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       01 WS-B PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           EVALUATE WS-A ALSO WS-B",
            "           WHEN 1 ALSO ANY",
            "              DISPLAY 'A IS 1'",
            "           END-EVALUATE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        # ANY should not produce an extra condition
        assert "and" not in source or "ANY" not in source


# ============================================================
# MOVE CORRESPONDING
# ============================================================

class TestMoveCorresponding:
    def test_move_corresponding_matching_fields(self):
        """MOVE CORRESPONDING should move fields with matching names."""
        ws_lines = [
            "       01 GROUP-A.",
            "          05 FIELD-X PIC 9(5).",
            "          05 FIELD-Y PIC X(10).",
            "       01 GROUP-B.",
            "          05 FIELD-X PIC 9(5).",
            "          05 FIELD-Z PIC X(10).",
        ]
        src = make_cobol(["MOVE CORRESPONDING GROUP-A TO GROUP-B."], data_lines=ws_lines)
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        # FIELD-X is common, should be moved
        assert "field_x" in source
        assert "CORRESPONDING" in source

    def test_move_corr_abbreviation(self):
        """MOVE CORR should work same as MOVE CORRESPONDING."""
        ws_lines = [
            "       01 GRP-1.",
            "          05 FLD-A PIC 9(5).",
            "       01 GRP-2.",
            "          05 FLD-A PIC 9(5).",
        ]
        src = make_cobol(["MOVE CORR GRP-1 TO GRP-2."], data_lines=ws_lines)
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "fld_a" in source


# ============================================================
# ON SIZE ERROR
# ============================================================

class TestOnSizeError:
    def test_add_with_on_size_error(self):
        """ADD with ON SIZE ERROR should wrap in try/except."""
        src = make_cobol([
            "ADD 1 TO WS-A ON SIZE ERROR DISPLAY 'OVERFLOW' END-ADD.",
        ])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "try:" in source
        assert "except" in source

    def test_compute_with_on_size_error(self):
        src = make_cobol([
            "COMPUTE WS-A = 999999 ON SIZE ERROR DISPLAY 'ERR' END-COMPUTE.",
        ])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "try:" in source

    def test_arithmetic_without_size_error_unchanged(self):
        """ADD without ON SIZE ERROR should not have try/except."""
        src = make_cobol(["ADD 1 TO WS-A."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "try:" not in source

    def test_wrap_on_size_error_unit(self):
        """Unit test for wrap_on_size_error."""
        arith = ["self.data.ws_a.add(1)"]
        ops = ["1", "TO", "WS-A", "ON", "SIZE", "ERROR", "DISPLAY", "'ERR'"]
        result = wrap_on_size_error(arith, ops)
        assert "try:" in result
        assert any("except" in r for r in result)
        assert any("ON SIZE ERROR" in r for r in result)


# ============================================================
# MOVE ALL (character fill)
# ============================================================

class TestMoveAllFill:
    def test_move_all_stars(self):
        """MOVE ALL '*' TO WS-A should fill with asterisks."""
        src = make_cobol(["MOVE ALL '*' TO WS-A."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "'*'" in source
        assert ".set(" in source

    def test_move_all_spaces(self):
        src = make_cobol(["MOVE ALL ' ' TO WS-A."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert ".set(" in source
