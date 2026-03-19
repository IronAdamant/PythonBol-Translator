"""Tests for Fixes 1-8: EXEC stripping, leading zeros, subscripts,
PERFORM THRU, recursive COPY, FileAdapter write, EBCDIC, EXEC hints.
"""

from __future__ import annotations

import ast

import pytest

from conftest import make_cobol
from cobol_safe_translator.adapters import CobolString, FileAdapter
from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.ebcdic import ebcdic_key
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.preprocessor import resolve_copies, strip_exec_blocks
from cobol_safe_translator.utils import _sanitize_numeric, resolve_operand


def _code_body(source: str) -> str:
    """Extract code body (after module docstring) for assertion checks."""
    idx = source.find("class ")
    return source[idx:] if idx != -1 else source


# ============================================================
# Fix 1: EXEC CICS/SQL stripping without copybook_paths
# ============================================================

class TestExecStrippingUnconditional:
    def test_exec_stripped_without_copybook_paths(self):
        """EXEC blocks should be stripped even when copybook_paths is None."""
        src = make_cobol([
            "EXEC CICS SEND MAP('MENU') END-EXEC.",
            "DISPLAY 'HELLO'.",
        ])
        program = parse_cobol(src, copybook_paths=None)
        source = generate_python(analyze(program))
        ast.parse(source)
        body = _code_body(source)
        assert "EXEC CICS" not in body
        assert "print(" in body

    def test_exec_sql_stripped_without_copybooks(self):
        """EXEC SQL should also be stripped unconditionally."""
        src = make_cobol(["EXEC SQL SELECT * FROM TABLE END-EXEC."])
        program = parse_cobol(src, copybook_paths=None)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "EXEC SQL" not in _code_body(source)

    def test_exec_stripped_with_copybook_paths(self):
        """EXEC blocks still stripped when copybook_paths is provided."""
        src = make_cobol(["EXEC CICS RETURN END-EXEC."])
        program = parse_cobol(src, copybook_paths=["/nonexistent"])
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "EXEC CICS" not in _code_body(source)

    def test_strip_exec_blocks_public(self):
        """strip_exec_blocks is a public function."""
        raw = "       EXEC CICS SEND MAP('MENU') END-EXEC."
        result = strip_exec_blocks(raw)
        assert "TODO(high)" in result
        assert "Original:" in result  # preserves original text in comment
        assert "Hint:" in result  # provides Python-equivalent hint


# ============================================================
# Fix 2: Leading-zero integer literals
# ============================================================

class TestSanitizeNumeric:
    def test_leading_zeros_stripped(self):
        assert _sanitize_numeric("01") == "1"
        assert _sanitize_numeric("007") == "7"
        assert _sanitize_numeric("0100") == "100"

    def test_zero_preserved(self):
        assert _sanitize_numeric("0") == "0"
        assert _sanitize_numeric("00") == "0"

    def test_decimal_preserved(self):
        assert _sanitize_numeric("3.14") == "3.14"
        assert _sanitize_numeric("00.50") == "0.50"

    def test_signed_number(self):
        assert _sanitize_numeric("-01") == "-1"
        assert _sanitize_numeric("+007") == "+7"

    def test_empty_passthrough(self):
        assert _sanitize_numeric("") == ""


class TestLeadingZerosInResolve:
    def test_resolve_operand_strips_leading_zeros(self):
        result = resolve_operand("01")
        assert result == "1"

    def test_resolve_operand_preserves_zero(self):
        assert resolve_operand("0") == "0"

    def test_move_strips_leading_zeros(self):
        """MOVE 01 TO WS-A should not produce Python '01'."""
        src = make_cobol(["MOVE 01 TO WS-A."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert ".set(01)" not in source
        assert ".set(1)" in source


# ============================================================
# Fix 3: OCCURS subscript handling
# ============================================================

class TestSubscriptAccess:
    def test_numeric_subscript_1based(self):
        """TABLE(1) should become self.data.table[0].value (0-based)."""
        result = resolve_operand("TABLE(1)")
        assert result == "self.data.table[0].value"

    def test_numeric_subscript_3(self):
        result = resolve_operand("WS-ITEM(3)")
        assert result == "self.data.ws_item[2].value"

    def test_variable_subscript(self):
        """TABLE(IDX) should use int(...) - 1."""
        result = resolve_operand("TABLE(IDX)")
        assert "int(self.data.idx.value) - 1" in result
        assert "self.data.table[" in result

    def test_refmod_still_works(self):
        """WS-FIELD(1:3) should still be treated as reference modification."""
        result = resolve_operand("WS-FIELD(1:3)")
        assert "str(self.data.ws_field.value)[0:3]" in result


# ============================================================
# Fix 4: PERFORM THRU paragraph ranges
# ============================================================

class TestPerformThruRange:
    def test_perform_thru_calls_range(self):
        """PERFORM A THRU C should call A, B, C when all exist."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           PERFORM STEP-A THRU STEP-C.",
            "       STEP-A.",
            "           DISPLAY 'A'.",
            "       STEP-B.",
            "           DISPLAY 'B'.",
            "       STEP-C.",
            "           DISPLAY 'C'.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "self.step_a()" in source
        assert "self.step_b()" in source
        assert "self.step_c()" in source

    def test_perform_through_also_works(self):
        """THROUGH keyword should work same as THRU."""
        src = make_cobol(["PERFORM MAIN-PARA THROUGH MAIN-PARA."])
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "self.main_para()" in source


# ============================================================
# Fix 5: Recursive COPY resolution
# ============================================================

class TestRecursiveCopy:
    def test_nested_copy_resolved(self, tmp_path):
        """A copybook that itself contains a COPY should be resolved."""
        inner = tmp_path / "INNER.cpy"
        inner.write_text("       01 WS-INNER PIC X(10).\n")

        outer = tmp_path / "OUTER.cpy"
        outer.write_text("       COPY INNER.\n       01 WS-OUTER PIC X(5).\n")

        raw = "       COPY OUTER.\n"
        result = resolve_copies(raw, copybook_paths=[str(tmp_path)])
        assert "WS-INNER" in result
        assert "WS-OUTER" in result
        # Inner COPY should be resolved, not left as COPY statement
        assert "COPY INNER" not in result

    def test_max_depth_prevents_infinite_loop(self, tmp_path):
        """Self-referencing copybook should not cause infinite loop."""
        selfref = tmp_path / "SELFREF.cpy"
        selfref.write_text("       COPY SELFREF.\n       01 WS-X PIC 9.\n")

        raw = "       COPY SELFREF.\n"
        # Should terminate (max 10 passes) and still contain the data item
        result = resolve_copies(raw, copybook_paths=[str(tmp_path)])
        assert "WS-X" in result


# ============================================================
# Fix 6: FileAdapter write path
# ============================================================

class TestFileAdapterWrite:
    def test_open_output_and_write(self, tmp_path):
        f = tmp_path / "out.dat"
        fa = FileAdapter(str(f))
        fa.open_output()
        fa.write("RECORD ONE")
        fa.write("RECORD TWO")
        fa.close()
        assert f.read_text() == "RECORD ONE\nRECORD TWO\n"

    def test_open_extend_appends(self, tmp_path):
        f = tmp_path / "out.dat"
        f.write_text("EXISTING\n")
        fa = FileAdapter(str(f))
        fa.open_extend()
        fa.write("NEW LINE")
        fa.close()
        assert f.read_text() == "EXISTING\nNEW LINE\n"

    def test_open_io_read_and_write(self, tmp_path):
        f = tmp_path / "io.dat"
        f.write_text("LINE1\n")
        fa = FileAdapter(str(f))
        fa.open_io()
        assert fa.read() == "LINE1"
        fa.write("LINE2")
        fa.close()

    def test_write_to_input_raises(self, tmp_path):
        f = tmp_path / "readonly.dat"
        f.write_text("data\n")
        fa = FileAdapter(str(f))
        fa.open_input()
        with pytest.raises(RuntimeError, match="Cannot write"):
            fa.write("should fail")
        fa.close()

    def test_write_before_open_raises(self):
        fa = FileAdapter("dummy.dat")
        with pytest.raises(RuntimeError, match="File not opened"):
            fa.write("test")

    def test_translate_write_verb(self):
        """WRITE verb should generate .write() call, not TODO."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT RPT-FILE ASSIGN TO 'report.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD RPT-FILE.",
            "       01 RPT-RECORD PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           WRITE RPT-RECORD.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert ".write(" in source

    def test_translate_open_extend(self):
        """OPEN EXTEND should generate .open_extend() call."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT LOG-FILE ASSIGN TO 'log.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD LOG-FILE.",
            "       01 LOG-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           OPEN EXTEND LOG-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        source = generate_python(analyze(program))
        ast.parse(source)
        assert "open_extend()" in source


# ============================================================
# Fix 7: EBCDIC collation
# ============================================================

class TestEbcdic:
    def test_ebcdic_key_returns_bytes(self):
        assert isinstance(ebcdic_key("HELLO"), bytes)

    def test_ebcdic_digits_after_letters(self):
        """In EBCDIC, letters sort before digits (opposite of ASCII)."""
        assert ebcdic_key("A") < ebcdic_key("1")
        assert ebcdic_key("Z") < ebcdic_key("0")

    def test_ebcdic_key_ordering(self):
        assert ebcdic_key("A") < ebcdic_key("B")
        assert ebcdic_key("B") > ebcdic_key("A")
        assert ebcdic_key("A") == ebcdic_key("A")

    def test_cobol_string_ebcdic_comparison(self):
        """CobolString with ebcdic=True should sort differently than ASCII."""
        ascii_a = CobolString(1, "A", ebcdic=False)
        ascii_1 = CobolString(1, "1", ebcdic=False)
        # In ASCII: "1" < "A"
        assert ascii_1 < ascii_a

        ebcdic_a = CobolString(1, "A", ebcdic=True)
        ebcdic_1 = CobolString(1, "1", ebcdic=True)
        # In EBCDIC: "A" < "1" (letters before digits)
        assert ebcdic_a < ebcdic_1

    def test_ebcdic_equality_unaffected(self):
        """Equality should work the same regardless of ebcdic flag."""
        s1 = CobolString(5, "HELLO", ebcdic=True)
        s2 = CobolString(5, "HELLO", ebcdic=True)
        assert s1 == s2


# ============================================================
# Fix 8: Better EXEC hints
# ============================================================

class TestExecHints:
    def test_cics_send_hint(self):
        raw = "       EXEC CICS SEND MAP('MENU') END-EXEC."
        result = strip_exec_blocks(raw)
        assert "Hint:" in result
        assert "print()" in result or "template" in result

    def test_sql_select_hint(self):
        raw = "       EXEC SQL SELECT * FROM CUSTOMER END-EXEC."
        result = strip_exec_blocks(raw)
        assert "Hint:" in result
        assert "cursor.execute" in result

    def test_cics_return_hint(self):
        raw = "       EXEC CICS RETURN END-EXEC."
        result = strip_exec_blocks(raw)
        assert "Hint:" in result
        assert "return" in result

    def test_unknown_verb_no_hint(self):
        """Unknown verbs should not crash, just omit hint."""
        raw = "       EXEC CICS XYZZY END-EXEC."
        result = strip_exec_blocks(raw)
        assert "TODO(high)" in result
        # No hint for unknown verb
        assert "Hint:" not in result

    def test_sql_commit_hint(self):
        raw = "       EXEC SQL COMMIT END-EXEC."
        result = strip_exec_blocks(raw)
        assert "connection.commit()" in result
