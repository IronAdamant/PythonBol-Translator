"""Tests for REPORT WRITER (REPORT SECTION) support.

Tests cover:
  - REPORT SECTION parsing (RD entries, report groups, lines, fields)
  - INITIATE, GENERATE, TERMINATE verb recognition and translation
  - End-to-end generation of valid Python from REPORT WRITER COBOL
  - Integration with block translator (verbs inside IF/PERFORM)
"""

from __future__ import annotations

import ast

import pytest

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.procedure_parser import KNOWN_VERBS
from cobol_safe_translator.report_parser import parse_report_section
from cobol_safe_translator.report_translators import (
    translate_generate,
    translate_initiate,
    translate_terminate,
)


def _make_report_cobol(
    report_section: str = "",
    procedure_lines: list[str] | None = None,
    ws_lines: str = "",
) -> str:
    """Build COBOL source with REPORT SECTION."""
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. RPT-TEST.",
        "       ENVIRONMENT DIVISION.",
        "       INPUT-OUTPUT SECTION.",
        "       FILE-CONTROL.",
        "           SELECT PRINT-FILE ASSIGN TO 'report.rpt'.",
        "       DATA DIVISION.",
        "       FILE SECTION.",
        "       FD PRINT-FILE",
        "           REPORT IS SALES-REPORT.",
        "       WORKING-STORAGE SECTION.",
        "       01 WS-EOF PIC X VALUE 'N'.",
        "          88 END-OF-FILE VALUE 'Y'.",
        "       01 WS-STATE PIC 99.",
        "       01 WS-AGENT PIC 999.",
        "       01 WS-SALE PIC 9(5)V99.",
    ]
    if ws_lines:
        for wl in ws_lines.splitlines():
            lines.append(f"       {wl.strip()}")
    if report_section:
        lines.append("       REPORT SECTION.")
        for rl in report_section.splitlines():
            lines.append(f"       {rl.strip()}")
    lines.append("       PROCEDURE DIVISION.")
    lines.append("       MAIN-PARA.")
    if procedure_lines:
        for pl in procedure_lines:
            lines.append(f"           {pl}")
    else:
        lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


# ============================================================
# Parser: REPORT SECTION parsing
# ============================================================

class TestReportSectionParsing:
    def test_rd_entry_basic(self):
        """RD entry should capture report name."""
        report_lines = [
            "REPORT SECTION.",
            "RD SALES-REPORT",
            "   PAGE LIMIT IS 66.",
        ]
        reports = parse_report_section(report_lines)
        assert len(reports) == 1
        assert reports[0].name == "SALES-REPORT"
        assert reports[0].page_limit == 66

    def test_rd_entry_controls(self):
        """CONTROLS ARE should capture control fields."""
        report_lines = [
            "REPORT SECTION.",
            "RD MY-REPORT",
            "   CONTROLS ARE FINAL",
            "               STATE-NUM",
            "               AGENT-NUM",
            "   PAGE LIMIT IS 54",
            "   FIRST DETAIL 3",
            "   LAST DETAIL 46",
            "   FOOTING 48.",
        ]
        reports = parse_report_section(report_lines)
        assert len(reports) == 1
        rd = reports[0]
        assert "FINAL" in rd.controls
        assert "STATE-NUM" in rd.controls
        assert "AGENT-NUM" in rd.controls
        assert rd.first_detail == 3
        assert rd.last_detail == 46
        assert rd.footing == 48

    def test_multiple_rd_entries(self):
        """Multiple RD entries should be parsed separately."""
        report_lines = [
            "REPORT SECTION.",
            "RD REPORT1",
            "   PAGE LIMIT IS 50.",
            "   01 FILLER TYPE IS DETAIL.",
            "      02 LINE 1.",
            "         03 COLUMN 1 PIC X(10) VALUE 'HELLO'.",
            "RD REPORT2",
            "   PAGE LIMIT IS 60.",
            "   01 FILLER TYPE IS DETAIL.",
            "      02 LINE 1.",
            "         03 COLUMN 1 PIC X(10) VALUE 'WORLD'.",
        ]
        reports = parse_report_section(report_lines)
        assert len(reports) == 2
        assert reports[0].name == "REPORT1"
        assert reports[1].name == "REPORT2"

    def test_report_group_types(self):
        """Various TYPE IS clauses should be recognized."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 TYPE IS REPORT HEADING.",
            "   02 LINE 1.",
            "      03 COLUMN 1 PIC X(5) VALUE 'TITLE'.",
            "01 TYPE IS PAGE HEADING.",
            "   02 LINE 1.",
            "      03 COLUMN 1 PIC X(5) VALUE 'HEADS'.",
            "01 DL TYPE IS DETAIL.",
            "   02 LINE IS PLUS 1.",
            "      03 COLUMN 1 PIC X(10) SOURCE WS-A.",
            "01 TYPE IS PAGE FOOTING.",
            "   02 LINE 50.",
            "      03 COLUMN 1 PIC X(5) VALUE 'PGFTR'.",
            "01 TYPE IS REPORT FOOTING.",
            "   02 LINE 55.",
            "      03 COLUMN 1 PIC X(5) VALUE 'END'.",
        ]
        reports = parse_report_section(report_lines)
        types = [g.type_clause for g in reports[0].groups]
        assert any("REPORT HEADING" in t for t in types)
        assert any("PAGE HEADING" in t for t in types)
        assert any("DETAIL" in t for t in types)
        assert any("PAGE FOOTING" in t for t in types)
        assert any("REPORT FOOTING" in t for t in types)

    def test_control_footing_with_qualifier(self):
        """CONTROL FOOTING STATENUM should capture the control field qualifier."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 STATE-GRP TYPE IS CONTROL FOOTING STATE-NUM.",
            "   02 LINE IS PLUS 1.",
            "      03 COLUMN 1 PIC X(10) VALUE 'SUBTOTAL'.",
        ]
        reports = parse_report_section(report_lines)
        group = reports[0].groups[0]
        assert "CONTROL FOOTING" in group.type_clause
        assert "STATE-NUM" in group.type_clause

    def test_source_field_parsed(self):
        """SOURCE clause should capture the data item name."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 DL TYPE IS DETAIL.",
            "   02 LINE IS PLUS 1.",
            "      03 COLUMN 1 PIC X(14) SOURCE WS-NAME.",
            "      03 COLUMN 20 PIC ZZ9 SOURCE WS-QTY.",
        ]
        reports = parse_report_section(report_lines)
        fields = reports[0].groups[0].lines[0].fields
        assert len(fields) == 2
        assert fields[0].source == "WS-NAME"
        assert fields[1].source == "WS-QTY"

    def test_sum_field_parsed(self):
        """SUM clause should capture the accumulated field name."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 CF TYPE IS CONTROL FOOTING FINAL.",
            "   02 LINE IS PLUS 1.",
            "      03 TOTAL COLUMN 10 PIC $$$,$$$.99 SUM WS-SALE.",
        ]
        reports = parse_report_section(report_lines)
        field = reports[0].groups[0].lines[0].fields[0]
        assert field.sum_field == "WS-SALE"
        assert field.name == "TOTAL"

    def test_group_indicate_detected(self):
        """GROUP INDICATE should be flagged on the field."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 DL TYPE IS DETAIL.",
            "   02 LINE IS PLUS 1.",
            "      03 COLUMN 1 PIC X(10) SOURCE WS-NAME GROUP INDICATE.",
        ]
        reports = parse_report_section(report_lines)
        field = reports[0].groups[0].lines[0].fields[0]
        assert field.group_indicate is True

    def test_line_plus_parsed(self):
        """LINE IS PLUS n should be captured."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 DL TYPE IS DETAIL.",
            "   02 LINE IS PLUS 2.",
            "      03 COLUMN 1 PIC X(5) VALUE 'HELLO'.",
        ]
        reports = parse_report_section(report_lines)
        line = reports[0].groups[0].lines[0]
        assert line.line_number == "PLUS 2"

    def test_line_absolute_parsed(self):
        """Absolute LINE n should be captured as an integer."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 TYPE IS PAGE FOOTING.",
            "   02 LINE 49.",
            "      03 COLUMN 1 PIC X(5) VALUE 'FOOT'.",
        ]
        reports = parse_report_section(report_lines)
        line = reports[0].groups[0].lines[0]
        assert line.line_number == 49

    def test_next_group_parsed(self):
        """NEXT GROUP PLUS n should be captured."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 TYPE IS REPORT HEADING NEXT GROUP PLUS 1.",
            "   02 LINE 1.",
            "      03 COLUMN 1 PIC X(5) VALUE 'TITLE'.",
        ]
        reports = parse_report_section(report_lines)
        group = reports[0].groups[0]
        assert group.next_group == "PLUS 1"

    def test_source_with_subscript(self):
        """SOURCE StateName(StateNum) should be captured including the subscript."""
        report_lines = [
            "REPORT SECTION.",
            "RD TEST-RPT PAGE LIMIT IS 66.",
            "01 DL TYPE IS DETAIL.",
            "   02 LINE IS PLUS 1.",
            "      03 COLUMN 1 PIC X(14) SOURCE StateName(StateNum).",
        ]
        reports = parse_report_section(report_lines)
        field = reports[0].groups[0].lines[0].fields[0]
        assert "STATENAME(STATENUM)" == field.source


class TestReportSectionInFullParse:
    def test_report_section_populated(self):
        """Full parse should populate report_section on CobolProgram."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT
    PAGE LIMIT IS 54
    FIRST DETAIL 3
    LAST DETAIL 46
    FOOTING 48.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC X(10) SOURCE WS-STATE.
""",
            procedure_lines=["INITIATE SALES-REPORT.", "STOP RUN."],
        )
        prog = parse_cobol(src)
        assert len(prog.report_section) == 1
        assert prog.report_section[0].name == "SALES-REPORT"

    def test_report_section_does_not_leak_into_working_storage(self):
        """REPORT SECTION items should NOT appear in working_storage."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT PAGE LIMIT IS 54.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC X(10) SOURCE WS-STATE.
""",
            procedure_lines=["STOP RUN."],
        )
        prog = parse_cobol(src)
        ws_names = [item.name for item in prog.working_storage]
        # Report items like DL, COLUMN fields should NOT be in WS
        assert "DL" not in ws_names
        assert len(prog.report_section) == 1


# ============================================================
# Verb recognition
# ============================================================

class TestReportWriterVerbRecognition:
    def test_initiate_in_known_verbs(self):
        assert "INITIATE" in KNOWN_VERBS

    def test_generate_in_known_verbs(self):
        assert "GENERATE" in KNOWN_VERBS

    def test_terminate_in_known_verbs(self):
        assert "TERMINATE" in KNOWN_VERBS

    def test_verbs_parsed_as_statements(self):
        """INITIATE/GENERATE/TERMINATE should appear as verb statements."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT PAGE LIMIT IS 54.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC X(10) SOURCE WS-STATE.
""",
            procedure_lines=[
                "INITIATE SALES-REPORT.",
                "GENERATE DL.",
                "TERMINATE SALES-REPORT.",
                "STOP RUN.",
            ],
        )
        prog = parse_cobol(src)
        verbs = [s.verb for p in prog.paragraphs for s in p.statements]
        assert "INITIATE" in verbs
        assert "GENERATE" in verbs
        assert "TERMINATE" in verbs


# ============================================================
# Translator unit tests
# ============================================================

class TestTranslateInitiate:
    def test_initiate_sets_up_buffers(self):
        """INITIATE should create output buffer and page counter."""
        from cobol_safe_translator.models import ReportDescription
        rd = ReportDescription(name="MY-REPORT")
        result = translate_initiate(["MY-REPORT"], [rd])
        combined = "\n".join(result)
        assert "_rw_output" in combined
        assert "_rw_page_counter" in combined
        assert "_rw_sums" in combined

    def test_initiate_no_report_found(self):
        """INITIATE with unknown report should still produce valid output."""
        result = translate_initiate(["UNKNOWN-RPT"], [])
        combined = "\n".join(result)
        assert "INITIATE" in combined
        assert "_rw_output" in combined

    def test_initiate_no_operands(self):
        result = translate_initiate([], [])
        assert any("no report" in l.lower() for l in result)


class TestTranslateGenerate:
    def test_generate_accumulates_sums(self):
        """GENERATE should accumulate SUM fields."""
        from cobol_safe_translator.models import (
            ReportDescription, ReportGroup, ReportLine, ReportField,
        )
        field = ReportField(
            name="TOTAL-SALES",
            column=10,
            pic="$$$,$$$.99",
            sum_field="WS-SALE",
        )
        line = ReportLine(line_number="PLUS 1", fields=[field])
        group = ReportGroup(
            name="CF-GRP",
            type_clause="CONTROL FOOTING FINAL",
            lines=[line],
        )
        detail_field = ReportField(column=1, pic="X(10)", source="WS-NAME")
        detail_line = ReportLine(line_number="PLUS 1", fields=[detail_field])
        detail = ReportGroup(name="DL", type_clause="DETAIL", lines=[detail_line])
        rd = ReportDescription(name="RPT", groups=[detail, group])

        result = translate_generate(["DL"], [rd])
        combined = "\n".join(result)
        assert "_rw_sums" in combined
        assert "ws_sale" in combined

    def test_generate_detail_not_found(self):
        """GENERATE for unknown detail should produce TODO."""
        result = translate_generate(["UNKNOWN-LINE"], [])
        combined = "\n".join(result)
        assert "TODO" in combined

    def test_generate_no_operands(self):
        result = translate_generate([], [])
        assert any("no detail" in l.lower() for l in result)


class TestTranslateTerminate:
    def test_terminate_writes_output(self):
        """TERMINATE should write accumulated output."""
        from cobol_safe_translator.models import ReportDescription
        rd = ReportDescription(name="MY-REPORT")
        result = translate_terminate(["MY-REPORT"], [rd])
        combined = "\n".join(result)
        assert "_rw_output" in combined
        assert "open(" in combined

    def test_terminate_prints_report_footing(self):
        """TERMINATE should include REPORT FOOTING if present."""
        from cobol_safe_translator.models import (
            ReportDescription, ReportGroup, ReportLine, ReportField,
        )
        field = ReportField(column=1, pic="X(20)", value="*** END ***")
        line = ReportLine(line_number=55, fields=[field])
        group = ReportGroup(type_clause="REPORT FOOTING", lines=[line])
        rd = ReportDescription(name="RPT", groups=[group])

        result = translate_terminate(["RPT"], [rd])
        combined = "\n".join(result)
        assert "Report Footing" in combined
        assert "END" in combined

    def test_terminate_no_operands(self):
        result = translate_terminate([], [])
        assert any("no report" in l.lower() for l in result)


# ============================================================
# End-to-end: full COBOL → valid Python
# ============================================================

class TestReportWriterEndToEnd:
    def test_simple_report_generates_valid_python(self):
        """Simple REPORT WRITER program should generate valid Python."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT
    CONTROLS ARE WS-STATE
    PAGE LIMIT IS 54
    FIRST DETAIL 3
    LAST DETAIL 46
    FOOTING 48.
01 TYPE IS PAGE HEADING.
   02 LINE 1.
      03 COLUMN 1 PIC X(10) VALUE 'State'.
      03 COLUMN 15 PIC X(10) VALUE 'Amount'.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC 99 SOURCE WS-STATE.
      03 COLUMN 15 PIC $$$,$$$.99 SOURCE WS-SALE.
01 CF TYPE IS CONTROL FOOTING WS-STATE.
   02 LINE IS PLUS 1.
      03 COLUMN 10 PIC X(10) VALUE 'Subtotal:'.
      03 TOT-SALE COLUMN 20 PIC $$$,$$$.99 SUM WS-SALE.
01 TYPE IS PAGE FOOTING.
   02 LINE 49.
      03 COLUMN 1 PIC X(10) VALUE 'Page:'.
      03 COLUMN 12 PIC ZZ9 SOURCE PAGE-COUNTER.
""",
            procedure_lines=[
                "OPEN OUTPUT PRINT-FILE.",
                "INITIATE SALES-REPORT.",
                "GENERATE DL.",
                "TERMINATE SALES-REPORT.",
                "CLOSE PRINT-FILE.",
                "STOP RUN.",
            ],
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py = generate_python(smap)
        ast.parse(py)

        # Verify key elements in output
        assert "_rw_output" in py
        assert "_rw_page_counter" in py
        assert "_rw_sums" in py
        assert "GENERATE" in py  # comment reference
        assert "INITIATE" in py  # comment reference
        assert "TERMINATE" in py  # comment reference

    def test_report_with_final_control_footing(self):
        """CONTROL FOOTING FINAL should be emitted during TERMINATE."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT
    CONTROLS ARE FINAL
    PAGE LIMIT IS 66.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC 99 SOURCE WS-STATE.
01 CF TYPE IS CONTROL FOOTING FINAL.
   02 LINE IS PLUS 4.
      03 COLUMN 10 PIC X(11) VALUE 'Total sales'.
""",
            procedure_lines=[
                "INITIATE SALES-REPORT.",
                "GENERATE DL.",
                "TERMINATE SALES-REPORT.",
                "STOP RUN.",
            ],
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py = generate_python(smap)
        ast.parse(py)
        assert "Control Footing FINAL" in py or "Total sales" in py

    def test_generate_inside_perform_loop(self):
        """GENERATE inside a PERFORM UNTIL loop should produce valid Python."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT PAGE LIMIT IS 54.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC 99 SOURCE WS-STATE.
""",
            procedure_lines=[
                "INITIATE SALES-REPORT.",
                "PERFORM PRINT-LOOP UNTIL END-OF-FILE.",
                "TERMINATE SALES-REPORT.",
                "STOP RUN.",
                "",
                "PRINT-LOOP.",
                "    GENERATE DL.",
            ],
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py = generate_python(smap)
        ast.parse(py)

    def test_generate_inside_if_block(self):
        """GENERATE inside an IF block should produce valid Python."""
        src = _make_report_cobol(
            report_section="""
RD SALES-REPORT PAGE LIMIT IS 54.
01 DL TYPE IS DETAIL.
   02 LINE IS PLUS 1.
      03 COLUMN 1 PIC 99 SOURCE WS-STATE.
""",
            procedure_lines=[
                "INITIATE SALES-REPORT.",
                "IF WS-STATE > 0",
                "   GENERATE DL",
                "END-IF.",
                "TERMINATE SALES-REPORT.",
                "STOP RUN.",
            ],
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py = generate_python(smap)
        ast.parse(py)

    def test_no_report_section_still_valid(self):
        """Program without REPORT SECTION should still generate valid Python."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NO-RPT.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC 9(5).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           DISPLAY WS-A.\n"
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        assert prog.report_section == []
        smap = analyze(prog)
        py = generate_python(smap)
        ast.parse(py)


# ============================================================
# Integration with real COBOL files (if available)
# ============================================================

class TestRealReportWriterFiles:
    """Test against real REPORT WRITER files from the test corpus."""

    @pytest.fixture(params=[
        "/home/aron/Documents/coding_projects/sample_projects_for_testing/beg-cobol-for-programmers/978-1-4302-6253-4_Coughlan_Ch18/Listing18-1.cbl",
        "/home/aron/Documents/coding_projects/sample_projects_for_testing/beg-cobol-for-programmers/978-1-4302-6253-4_Coughlan_Ch18/Listing18-2.cbl",
        "/home/aron/Documents/coding_projects/sample_projects_for_testing/beg-cobol-for-programmers/978-1-4302-6253-4_Coughlan_Ch18/Listing18-3.cbl",
    ])
    def report_file(self, request):
        return request.param

    def test_real_file_valid_python(self, report_file):
        """Real REPORT WRITER file should produce valid Python."""
        import pathlib
        path = pathlib.Path(report_file)
        if not path.exists():
            pytest.skip(f"Test file not found: {report_file}")
        source = path.read_text(encoding="utf-8", errors="replace")
        prog = parse_cobol(source, str(path))
        smap = analyze(prog)
        py = generate_python(smap)
        ast.parse(py)

    def test_real_file_has_report_section(self, report_file):
        """Real REPORT WRITER file should have parsed report section."""
        import pathlib
        path = pathlib.Path(report_file)
        if not path.exists():
            pytest.skip(f"Test file not found: {report_file}")
        source = path.read_text(encoding="utf-8", errors="replace")
        prog = parse_cobol(source, str(path))
        assert len(prog.report_section) >= 1
        assert len(prog.report_section[0].groups) >= 1

    def test_real_file_no_unsupported_verb_for_rw(self, report_file):
        """INITIATE/GENERATE/TERMINATE should NOT appear as unsupported verbs."""
        import pathlib
        path = pathlib.Path(report_file)
        if not path.exists():
            pytest.skip(f"Test file not found: {report_file}")
        source = path.read_text(encoding="utf-8", errors="replace")
        prog = parse_cobol(source, str(path))
        smap = analyze(prog)
        py = generate_python(smap)
        assert "unsupported verb INITIATE" not in py
        assert "unsupported verb GENERATE" not in py
        assert "unsupported verb TERMINATE" not in py
