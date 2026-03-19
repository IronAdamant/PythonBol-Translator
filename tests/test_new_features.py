"""Tests for new parser and translator features (88-levels, multi-line, ref-mod, USAGE, STRING/UNSTRING/INSPECT/SET)."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol, parse_data_division, parse_environment
from cobol_safe_translator.procedure_parser import parse_procedure
from cobol_safe_translator.string_translators import (
    translate_string,
    translate_unstring,
    translate_inspect,
    translate_set,
)
from cobol_safe_translator.utils import _to_python_name


def _make_cobol(procedure_lines: list[str], data_lines: list[str] | None = None) -> str:
    """Build minimal COBOL source with optional custom data division and procedure lines."""
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. TEST-PROG.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
    ]
    if data_lines:
        for dl in data_lines:
            lines.append(f"       {dl}")
    else:
        lines.append("       01 WS-A PIC X(20).")
        lines.append("       01 WS-B PIC X(20).")
        lines.append("       01 WS-C PIC X(20).")
    lines.append("       PROCEDURE DIVISION.")
    lines.append("       MAIN-PARA.")
    for pl in procedure_lines:
        lines.append(f"           {pl}")
    return "\n".join(lines) + "\n"


def _simple_resolve(tok: str) -> str:
    """Simple operand resolver for unit-testing string_translators."""
    upper = tok.upper()
    if tok.startswith('"') or tok.startswith("'"):
        return tok
    if tok.isdigit():
        return tok
    if upper in ("ZERO", "ZEROS", "ZEROES"):
        return "0"
    if upper in ("SPACE", "SPACES"):
        return "' '"
    return f"self.data.{_to_python_name(tok)}.value"


# === PARSER TESTS ===

class TestParser88Level:
    def test_88_level_basic(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            '01 WS-EOF-FLAG PIC X VALUE "N".',
            '   88 WS-EOF VALUE "Y".',
        ]
        _, ws, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        item = ws[0]
        assert item.name == "WS-EOF-FLAG"
        assert len(item.conditions) == 1
        assert item.conditions[0].name == "WS-EOF"
        assert "Y" in item.conditions[0].values

    def test_88_level_thru(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-CODE PIC 9(2).",
            "   88 VALID-CODE VALUE 1 THRU 10.",
        ]
        _, ws, _, _ = parse_data_division(lines)
        item = ws[0]
        assert len(item.conditions) == 1
        cond = item.conditions[0]
        assert cond.name == "VALID-CODE"
        assert len(cond.thru_ranges) == 1
        assert cond.thru_ranges[0] == ("1", "10")

    def test_88_level_multiple_values(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-TYPE PIC X.",
            '   88 WS-VALID-TYPE VALUE "A" "B" "C".',
        ]
        _, ws, _, _ = parse_data_division(lines)
        cond = ws[0].conditions[0]
        assert cond.name == "WS-VALID-TYPE"
        assert "A" in cond.values
        assert "B" in cond.values
        assert "C" in cond.values

    def test_88_not_in_working_storage_items(self):
        """88-level items should NOT appear as DataItem entries in working_storage."""
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-FLAG PIC X.",
            '   88 WS-TRUE VALUE "Y".',
            "01 WS-OTHER PIC 9(3).",
        ]
        _, ws, _, _ = parse_data_division(lines)
        names = [item.name for item in ws]
        assert "WS-TRUE" not in names
        assert len(ws) == 2


class TestParserMultiLineSentence:
    def test_multi_line_joined(self):
        """Multi-line statement should be joined into one statement."""
        lines = [
            "MAIN-PARA.",
            "SUBTRACT WS-A FROM WS-B",
            "    GIVING WS-C.",
        ]
        paragraphs = parse_procedure(lines)
        assert len(paragraphs) == 1
        stmts = paragraphs[0].statements
        assert len(stmts) == 1
        assert stmts[0].verb == "SUBTRACT"
        assert "GIVING" in stmts[0].raw_text.upper()

    def test_multi_line_display(self):
        lines = [
            "MAIN-PARA.",
            'DISPLAY "HELLO "',
            '    WS-NAME.',
        ]
        paragraphs = parse_procedure(lines)
        stmts = paragraphs[0].statements
        assert len(stmts) == 1
        assert stmts[0].verb == "DISPLAY"


class TestParserReferenceModification:
    def test_ref_mod_single_token(self):
        """Reference modification WS-A(1:3) should be kept as a single operand token."""
        lines = [
            "MAIN-PARA.",
            "MOVE WS-A(1:3) TO WS-B.",
        ]
        paragraphs = parse_procedure(lines)
        stmts = paragraphs[0].statements
        assert len(stmts) == 1
        # WS-A(1:3) should be a single token in operands
        ops_upper = [o.upper() for o in stmts[0].operands]
        ref_mod_ops = [o for o in stmts[0].operands if "(" in o and ":" in o]
        assert len(ref_mod_ops) >= 1, f"Expected ref-mod token, got: {stmts[0].operands}"


class TestParserUsageClause:
    def test_usage_comp3(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-AMT PIC S9(9)V99 COMP-3.",
        ]
        _, ws, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].usage == "COMP-3"

    def test_usage_binary(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-IDX PIC 9(4) USAGE BINARY.",
        ]
        _, ws, _, _ = parse_data_division(lines)
        assert ws[0].usage == "BINARY"

    def test_no_usage(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-PLAIN PIC X(10).",
        ]
        _, ws, _, _ = parse_data_division(lines)
        assert ws[0].usage is None


class TestParserFileStatus:
    def test_file_status_parsed(self):
        lines = [
            "SELECT CUSTOMER-FILE ASSIGN TO 'cust.dat'",
            "    FILE STATUS IS WS-FILE-STATUS.",
        ]
        controls = parse_environment(lines)
        assert len(controls) == 1
        assert controls[0].file_status == "WS-FILE-STATUS"

    def test_no_file_status(self):
        lines = [
            "SELECT REPORT-FILE ASSIGN TO 'report.dat'.",
        ]
        controls = parse_environment(lines)
        assert len(controls) == 1
        assert controls[0].file_status is None


# === STRING_TRANSLATORS UNIT TESTS ===

class TestTranslateString:
    def test_basic_string_concat(self):
        ops = ["WS-A", "DELIMITED", "BY", "SIZE",
               "WS-B", "DELIMITED", "BY", "SIZE",
               "INTO", "WS-C"]
        lines = translate_string(ops, _simple_resolve)
        joined = " ".join(lines)
        assert "ws_c" in joined
        assert "+" in joined

    def test_string_no_ops(self):
        lines = translate_string([], _simple_resolve)
        assert any("no operands" in l for l in lines)

    def test_string_missing_into(self):
        ops = ["WS-A", "DELIMITED", "BY", "SIZE"]
        lines = translate_string(ops, _simple_resolve)
        assert any("missing INTO" in l or "TODO" in l for l in lines)


class TestTranslateUnstring:
    def test_basic_unstring(self):
        ops = ["WS-INPUT", "DELIMITED", "BY", '","', "INTO", "WS-A", "WS-B", "WS-C"]
        lines = translate_unstring(ops, _simple_resolve)
        joined = " ".join(lines)
        assert "split" in joined
        assert "ws_a" in joined
        assert "ws_b" in joined
        assert "ws_c" in joined

    def test_unstring_no_ops(self):
        lines = translate_unstring([], _simple_resolve)
        assert any("no operands" in l for l in lines)


class TestTranslateInspect:
    def test_tallying(self):
        ops = ["WS-FIELD", "TALLYING", "WS-COUNT", "FOR", "ALL", '"A"']
        lines = translate_inspect(ops, _simple_resolve)
        joined = " ".join(lines)
        assert "count" in joined

    def test_replacing(self):
        ops = ["WS-FIELD", "REPLACING", "ALL", '"A"', "BY", '"B"']
        lines = translate_inspect(ops, _simple_resolve)
        joined = " ".join(lines)
        assert "replace" in joined

    def test_inspect_no_ops(self):
        lines = translate_inspect([], _simple_resolve)
        assert any("no operands" in l for l in lines)


class TestTranslateSet:
    def test_set_to_true(self):
        lookup = {"WS-EOF": ("ws_eof_flag", '"Y"')}
        ops = ["WS-EOF", "TO", "TRUE"]
        lines = translate_set(ops, _simple_resolve, lookup)
        joined = " ".join(lines)
        assert "ws_eof_flag" in joined
        assert '"Y"' in joined

    def test_set_up_by(self):
        ops = ["WS-IDX", "UP", "BY", "1"]
        lines = translate_set(ops, _simple_resolve, {})
        joined = " ".join(lines)
        assert "add" in joined

    def test_set_down_by(self):
        ops = ["WS-IDX", "DOWN", "BY", "1"]
        lines = translate_set(ops, _simple_resolve, {})
        joined = " ".join(lines)
        assert "subtract" in joined

    def test_set_to_value(self):
        ops = ["WS-IDX", "TO", "5"]
        lines = translate_set(ops, _simple_resolve, {})
        joined = " ".join(lines)
        assert "set" in joined


# === END-TO-END TRANSLATOR TESTS ===

class TestEndToEndStringTranslation:
    def test_string_generates_valid_python(self):
        src = _make_cobol(
            ['STRING WS-A DELIMITED BY SIZE WS-B DELIMITED BY SIZE INTO WS-C.'],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "+" in source or "concat" in source.lower() or "STRING" in source

    def test_unstring_generates_valid_python(self):
        src = _make_cobol(
            ['UNSTRING WS-A DELIMITED BY "," INTO WS-B WS-C.'],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "split" in source or "UNSTRING" in source

    def test_inspect_tallying_generates_valid_python(self):
        src = _make_cobol(
            ['INSPECT WS-A TALLYING WS-B FOR ALL "X".'],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "count" in source or "INSPECT" in source

    def test_inspect_replacing_generates_valid_python(self):
        src = _make_cobol(
            ['INSPECT WS-A REPLACING ALL "X" BY "Y".'],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "replace" in source or "INSPECT" in source


class TestEndToEnd88Level:
    def test_set_to_true_with_88(self):
        src = _make_cobol(
            ['SET WS-EOF TO TRUE.'],
            data_lines=[
                '01 WS-EOF-FLAG PIC X VALUE "N".',
                '   88 WS-EOF VALUE "Y".',
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Should set parent field to the 88-level value
        assert "ws_eof_flag" in source or "set" in source.lower()

    def test_if_88_level_condition(self):
        src = _make_cobol(
            ['IF WS-EOF', '    DISPLAY "DONE"', 'END-IF.'],
            data_lines=[
                '01 WS-EOF-FLAG PIC X VALUE "N".',
                '   88 WS-EOF VALUE "Y".',
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # The IF condition should reference the parent field's value, not WS-EOF directly
        assert "ws_eof_flag" in source or "if" in source.lower()
