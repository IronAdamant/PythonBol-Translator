"""Tests for the COBOL parser."""

from cobol_safe_translator.parser import (
    classify_pic,
    compute_pic_size,
    expand_pic,
    parse_cobol,
    parse_cobol_file,
    parse_pic,
    preprocess_lines,
    split_divisions,
)
from cobol_safe_translator.models import PicCategory


class TestPreprocessing:
    def test_strips_sequence_numbers(self):
        raw = "000100 IDENTIFICATION DIVISION.                                          \n"
        lines = preprocess_lines(raw)
        assert lines
        assert "IDENTIFICATION DIVISION." in lines[0]

    def test_skips_comment_lines(self):
        # Proper COBOL columns: 1-6 seq, 7 indicator, 8+ content
        raw = (
            "000100 IDENTIFICATION DIVISION.\n"
            "000200*THIS IS A COMMENT\n"
            "000300 PROGRAM-ID. TEST.\n"
        )
        lines = preprocess_lines(raw)
        assert not any("COMMENT" in l for l in lines)

    def test_handles_continuation_lines(self):
        # Col 7 = '-' means continuation line
        raw = (
            '000100 DISPLAY "HELLO \n'
            '000200-"WORLD".\n'
        )
        lines = preprocess_lines(raw)
        assert len(lines) == 1
        assert "HELLO" in lines[0]
        assert "WORLD" in lines[0]

    def test_empty_input(self):
        assert preprocess_lines("") == []

    def test_short_lines_skipped(self):
        raw = "AB\nCD\n"
        lines = preprocess_lines(raw)
        assert lines == []


class TestPicExpansion:
    def test_numeric_repeat(self):
        assert expand_pic("9(5)") == "99999"

    def test_alphanumeric_repeat(self):
        assert expand_pic("X(3)") == "XXX"

    def test_mixed(self):
        assert expand_pic("9(5)V99") == "99999V99"

    def test_signed_numeric(self):
        result = expand_pic("S9(7)V99")
        assert result == "S9999999V99"

    def test_no_repeat(self):
        assert expand_pic("99V9") == "99V9"

    def test_edited(self):
        result = expand_pic("-ZZZ,ZZZ,ZZ9.99")
        assert result == "-ZZZ,ZZZ,ZZ9.99"


class TestPicClassification:
    def test_numeric(self):
        assert classify_pic("99999") == PicCategory.NUMERIC

    def test_alphanumeric(self):
        assert classify_pic("XXX") == PicCategory.ALPHANUMERIC

    def test_alphabetic(self):
        assert classify_pic("AAA") == PicCategory.ALPHABETIC

    def test_edited(self):
        assert classify_pic("-ZZZ,ZZZ,ZZ9.99") == PicCategory.EDITED

    def test_signed_numeric(self):
        assert classify_pic("S99999V99") == PicCategory.NUMERIC


class TestPicSize:
    def test_simple_numeric(self):
        size, dec, signed = compute_pic_size("99999")
        assert size == 5
        assert dec == 0
        assert signed is False

    def test_numeric_with_decimal(self):
        size, dec, signed = compute_pic_size("99999V99")
        assert size == 7
        assert dec == 2

    def test_signed(self):
        size, dec, signed = compute_pic_size("S9999999V99")
        assert signed is True
        assert dec == 2

    def test_alphanumeric(self):
        size, dec, signed = compute_pic_size("XXXXXX")
        assert size == 6
        assert dec == 0


class TestParsePic:
    def test_full_parse(self):
        pic = parse_pic("S9(7)V99")
        assert pic.category == PicCategory.NUMERIC
        assert pic.decimals == 2
        assert pic.signed is True
        assert pic.size == 9


class TestDivisionSplitting:
    def test_all_divisions_have_content(self, hello_source):
        lines = preprocess_lines(hello_source)
        divs = split_divisions(lines)
        assert len(divs["IDENTIFICATION"]) > 0
        assert len(divs["DATA"]) > 0
        assert len(divs["PROCEDURE"]) > 0

    def test_identification_contains_program_id(self, hello_source):
        lines = preprocess_lines(hello_source)
        divs = split_divisions(lines)
        combined = " ".join(divs["IDENTIFICATION"])
        assert "HELLO-WORLD" in combined


class TestFullParse:
    def test_hello_world(self, hello_source):
        program = parse_cobol(hello_source, "hello.cob")
        assert program.program_id == "HELLO-WORLD"
        assert len(program.working_storage) > 0
        assert len(program.paragraphs) > 0

    def test_customer_report(self, customer_report_source):
        program = parse_cobol(customer_report_source, "customer-report.cob")
        assert program.program_id == "CUSTOMER-REPORT"
        assert len(program.file_controls) == 2
        assert len(program.file_section) > 0
        assert len(program.working_storage) > 0
        assert len(program.paragraphs) == 9

    def test_parse_file(self, hello_cob):
        program = parse_cobol_file(hello_cob)
        assert program.program_id == "HELLO-WORLD"

    def test_hello_data_items(self, hello_source):
        program = parse_cobol(hello_source)
        ws_names = [item.name for item in program.working_storage]
        assert "WS-MESSAGE" in ws_names
        assert "WS-COUNTER" in ws_names

    def test_hello_paragraphs(self, hello_source):
        program = parse_cobol(hello_source)
        para_names = [p.name for p in program.paragraphs]
        assert "MAIN-PARAGRAPH" in para_names

    def test_customer_file_controls(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        fc_names = [fc.select_name for fc in program.file_controls]
        assert "CUSTOMER-FILE" in fc_names
        assert "REPORT-FILE" in fc_names

    def test_customer_nested_data(self, customer_report_source):
        program = parse_cobol(customer_report_source)
        # File section should have nested items
        customer_rec = None
        for item in program.file_section:
            if item.name == "CUSTOMER-RECORD":
                customer_rec = item
                break
        assert customer_rec is not None
        child_names = [c.name for c in customer_rec.children]
        assert "CUST-ID" in child_names
        assert "CUST-SSN" in child_names
        assert "CUST-BALANCE" in child_names
