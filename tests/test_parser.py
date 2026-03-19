"""Tests for the COBOL parser."""

from cobol_safe_translator.parser import (
    parse_cobol,
    parse_cobol_file,
    preprocess_lines,
    split_divisions,
)
from cobol_safe_translator.pic_parser import (
    classify_pic,
    compute_pic_size,
    expand_pic,
    parse_pic,
)
from cobol_safe_translator.parser import parse_data_division
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
        assert len(lines) >= 1, "Should have at least 1 non-comment line"
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

    def test_continuation_unclosed_literal(self):
        """Continuation line should merge unclosed string literals correctly."""
        raw = (
            '000100       DISPLAY "HELLO WOR                                          \n'
            '000200-        "LD".                                                      \n'
        )
        lines = preprocess_lines(raw)
        assert len(lines) == 1
        assert '"HELLO WORLD"' in lines[0]

    def test_empty_input(self):
        assert preprocess_lines("") == []

    def test_short_lines_skipped(self):
        # In fixed-format mode, lines shorter than 7 chars have no content area.
        # Use sequence numbers in cols 1-6 to force fixed-format detection.
        raw = "000010 IDENTIFICATION DIVISION.\n000020 PROGRAM-ID. TEST.\nAB\nCD\n"
        lines = preprocess_lines(raw)
        # Short lines "AB" and "CD" should be skipped (no content area)
        assert "AB" not in lines
        assert "CD" not in lines


class TestLevel77:
    def test_level_77_is_root(self):
        """Level 77 items should always be root-level, not nested under 01 groups."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-GROUP.",
            "   05 WS-FIELD-A PIC X(10).",
            "77 WS-STANDALONE PIC 9(5).",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        root_names = [item.name for item in ws]
        assert "WS-GROUP" in root_names
        assert "WS-STANDALONE" in root_names
        assert len(ws) == 2


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

    def test_unknown_category(self):
        """Empty or unrecognizable PIC string should return UNKNOWN."""
        assert classify_pic("V") == PicCategory.UNKNOWN


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
        assert size == 9
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


class TestPositiveSignedDecimalValue:
    def test_value_positive_signed_decimal(self):
        """VALUE +1.50 should capture the full decimal, not truncate at period."""
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-D PIC S9(3)V99 VALUE +1.50.",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].value == "+1.50"


class TestLinkageSection:
    def test_linkage_items_stored(self):
        """LINKAGE SECTION items should now be captured."""
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "LINKAGE SECTION.",
            "01 LK-PARAM PIC X(10).",
            "01 LK-VALUE PIC 9(5).",
        ]
        _, _, linkage, _, _ = parse_data_division(lines)
        assert len(linkage) == 2
        names = [item.name for item in linkage]
        assert "LK-PARAM" in names
        assert "LK-VALUE" in names

    def test_linkage_section_in_full_parse(self):
        """Full parse should populate linkage_section."""
        from cobol_safe_translator.parser import parse_cobol
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. TEST-LINK.\n"
            "       DATA DIVISION.\n"
            "       LINKAGE SECTION.\n"
            "       01 LK-INPUT PIC X(20).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           DISPLAY LK-INPUT.\n"
            "           STOP RUN.\n"
        )
        program = parse_cobol(src)
        assert len(program.linkage_section) == 1
        assert program.linkage_section[0].name == "LK-INPUT"


class TestSectionHeaders:
    def test_section_parsed_as_paragraph(self):
        """SECTION headers should be recognized as paragraphs."""
        from cobol_safe_translator.procedure_parser import parse_procedure
        lines = [
            "MAIN-SECTION SECTION.",
            "DISPLAY WS-A.",
        ]
        paragraphs, _ = parse_procedure(lines)
        assert len(paragraphs) == 1
        assert paragraphs[0].name == "MAIN-SECTION"
        assert len(paragraphs[0].statements) == 1


class TestPicRegexExtended:
    def test_pic_with_asterisk(self):
        """PIC with check-protect character (*) should be captured."""
        from cobol_safe_translator.parser import _PIC_RE
        m = _PIC_RE.search("PIC **,***,**9.99")
        assert m is not None

    def test_pic_with_slash(self):
        """PIC with slash insertion (/) should be captured."""
        from cobol_safe_translator.parser import _PIC_RE
        m = _PIC_RE.search("PIC 99/99/9999")
        assert m is not None

    def test_pic_with_p(self):
        """PIC with scaling position (P) should be captured."""
        from cobol_safe_translator.parser import _PIC_RE
        m = _PIC_RE.search("PIC 9(3)PP")
        assert m is not None


class TestPicIsSyntax:
    """Pass 1 Issue 8: PIC IS / PICTURE IS should be recognized."""

    def test_pic_is_syntax(self):
        from cobol_safe_translator.parser import _PIC_RE
        m = _PIC_RE.search("PIC IS 9(5)")
        assert m is not None
        assert m.group(1).startswith("9")

    def test_picture_is_syntax(self):
        from cobol_safe_translator.parser import _PIC_RE
        m = _PIC_RE.search("PICTURE IS X(10)")
        assert m is not None
        assert m.group(1).startswith("X")

    def test_pic_without_is_still_works(self):
        from cobol_safe_translator.parser import _PIC_RE
        m = _PIC_RE.search("PIC 9(5)")
        assert m is not None

    def test_pic_is_in_data_item(self):
        from cobol_safe_translator.parser import parse_data_division
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-A PIC IS 9(5).",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].pic is not None
        assert ws[0].pic.size == 5


class TestOccursRedefines:
    def test_occurs_count_extracted(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-ARRAY PIC 9(3) OCCURS 5 TIMES.",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert len(ws) == 1
        assert ws[0].occurs == 5

    def test_redefines_name_extracted(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-A PIC 9(3).",
            "01 WS-B REDEFINES WS-A PIC X(3).",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert len(ws) == 2
        assert ws[1].redefines == "WS-A"


class TestValueQuoteStripping:
    """VALUE clause only strips matching outer quotes, not inner ones."""

    def test_double_quoted_value(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            '01 WS-MSG PIC X(10) VALUE "HELLO".',
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert ws[0].value == "HELLO"

    def test_single_quoted_value(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-MSG PIC X(10) VALUE 'WORLD'.",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert ws[0].value == "WORLD"

    def test_numeric_value_no_stripping(self):
        lines = [
            "WORKING-STORAGE SECTION.",
            "01 WS-NUM PIC 9(3) VALUE 123.",
        ]
        _, ws, _, _, _ = parse_data_division(lines)
        assert ws[0].value == "123"


class TestPicRepeatExpansion:
    """PIC repeat notation should expand P and / characters."""

    def test_p_repeat(self):
        assert expand_pic("P(3)999") == "PPP999"

    def test_slash_repeat(self):
        assert expand_pic("99/(2)99") == "99//99"

    def test_p_in_size(self):
        size, _, _ = compute_pic_size("PPP999")
        assert size == 3  # P is implied scaling, not a display position

    def test_slash_in_size(self):
        size, _, _ = compute_pic_size("99/99/9999")
        assert size == 10  # 8 digits + 2 slashes


class TestExtractValueFirstTokenOnly:
    def test_program_id_with_extra_words_takes_first(self):
        """PROGRAM-ID with extra garbage after the id must return only the first token."""
        from cobol_safe_translator.parser import _extract_value
        result = _extract_value("PROGRAM-ID. MY-PROG EXTRA GARBAGE.", "PROGRAM-ID")
        assert result == "MY-PROG"
        assert " " not in result

    def test_author_with_extra_words_takes_first(self):
        from cobol_safe_translator.parser import _extract_value
        result = _extract_value("AUTHOR. JOHN DOE.", "AUTHOR")
        assert result == "JOHN"

    def test_normal_single_word_unchanged(self):
        from cobol_safe_translator.parser import _extract_value
        result = _extract_value("PROGRAM-ID. HELLO-WORLD.", "PROGRAM-ID")
        assert result == "HELLO-WORLD"
