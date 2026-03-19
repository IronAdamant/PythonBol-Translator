"""Tests for SCREEN SECTION parsing and code generation."""

from cobol_safe_translator.parser import (
    parse_cobol,
    parse_screen_section,
)
from cobol_safe_translator.models import ScreenField, SoftwareMap
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.analyzer import analyze


# --- Parser tests ---


class TestParseScreenSection:
    """Tests for parse_screen_section()."""

    def test_basic_screen_parsing(self):
        lines = [
            '01 MAIN-SCREEN.',
            '   05 BLANK SCREEN.',
            '   05 LINE 1 COL 1 VALUE "Name: ".',
            '   05 LINE 1 COL 10 PIC X(20) USING WS-NAME.',
        ]
        screens = parse_screen_section(lines)
        assert len(screens) == 1
        s = screens[0]
        assert s.name == "MAIN-SCREEN"
        assert s.level == 1
        assert len(s.children) == 3

    def test_blank_screen(self):
        lines = ['05 BLANK SCREEN.']
        screens = parse_screen_section(lines)
        assert len(screens) == 1
        assert screens[0].blank_screen is True

    def test_line_col_parsing(self):
        lines = ['05 LINE 3 COL 10 VALUE "Hello".']
        screens = parse_screen_section(lines)
        assert screens[0].line == 3
        assert screens[0].column == 10
        assert screens[0].value == "Hello"

    def test_column_keyword(self):
        lines = ['05 LINE 2 COLUMN 5 VALUE "Test".']
        screens = parse_screen_section(lines)
        assert screens[0].column == 5

    def test_pic_using(self):
        lines = ['05 LINE 1 COL 10 PIC X(20) USING WS-NAME.']
        screens = parse_screen_section(lines)
        sf = screens[0]
        assert sf.pic == "X(20)"
        assert sf.using == "WS-NAME"

    def test_from_field(self):
        lines = ['05 LINE 1 COL 10 PIC X(20) FROM WS-DISPLAY-NAME.']
        screens = parse_screen_section(lines)
        sf = screens[0]
        assert sf.from_field == "WS-DISPLAY-NAME"

    def test_to_field(self):
        lines = ['05 LINE 1 COL 10 PIC X(20) TO WS-INPUT-NAME.']
        screens = parse_screen_section(lines)
        sf = screens[0]
        assert sf.to_field == "WS-INPUT-NAME"

    def test_display_attributes(self):
        lines = [
            '05 LINE 1 COL 1 VALUE "Error!" BLINK REVERSE-VIDEO.',
        ]
        screens = parse_screen_section(lines)
        sf = screens[0]
        assert "BLINK" in sf.attributes
        assert "REVERSE-VIDEO" in sf.attributes

    def test_highlight_attribute(self):
        lines = [
            '05 LINE 1 COL 10 PIC X(20) USING WS-NAME HIGHLIGHT.',
        ]
        screens = parse_screen_section(lines)
        assert "HIGHLIGHT" in screens[0].attributes

    def test_foreground_color(self):
        lines = [
            '05 LINE 1 COL 10 PIC X(20) USING WS-NAME FOREGROUND-COLOR 7.',
        ]
        screens = parse_screen_section(lines)
        assert "FOREGROUND-COLOR 7" in screens[0].attributes

    def test_background_color(self):
        lines = [
            '05 LINE 1 COL 10 PIC X(20) USING WS-NAME BACKGROUND-COLOR 2.',
        ]
        screens = parse_screen_section(lines)
        assert "BACKGROUND-COLOR 2" in screens[0].attributes

    def test_multiple_screens(self):
        lines = [
            '01 MAIN-SCREEN.',
            '   05 LINE 1 COL 1 VALUE "Main".',
            '01 ERROR-SCREEN.',
            '   05 LINE 24 COL 1 VALUE "Error!" BLINK.',
        ]
        screens = parse_screen_section(lines)
        assert len(screens) == 2
        assert screens[0].name == "MAIN-SCREEN"
        assert screens[1].name == "ERROR-SCREEN"

    def test_hierarchy_nesting(self):
        lines = [
            '01 MAIN-SCREEN.',
            '   05 HEADER-GROUP.',
            '      10 LINE 1 COL 1 VALUE "Title".',
            '      10 LINE 2 COL 1 VALUE "Subtitle".',
            '   05 BODY-GROUP.',
            '      10 LINE 5 COL 1 PIC X(30) USING WS-DATA.',
        ]
        screens = parse_screen_section(lines)
        assert len(screens) == 1
        root = screens[0]
        assert len(root.children) == 2
        assert root.children[0].name == "HEADER-GROUP"
        assert len(root.children[0].children) == 2
        assert root.children[1].name == "BODY-GROUP"
        assert len(root.children[1].children) == 1

    def test_secure_required_full_auto(self):
        lines = [
            '05 LINE 3 COL 1 PIC X(20) USING WS-PASSWORD SECURE REQUIRED.',
        ]
        screens = parse_screen_section(lines)
        assert "SECURE" in screens[0].attributes
        assert "REQUIRED" in screens[0].attributes

    def test_empty_input(self):
        screens = parse_screen_section([])
        assert screens == []

    def test_no_name_field(self):
        """Screen fields can be anonymous (no name, just level + clauses)."""
        lines = ['05 FILLER LINE 1 COL 1 VALUE "Label".']
        screens = parse_screen_section(lines)
        assert len(screens) == 1
        assert screens[0].name == ""
        assert screens[0].value == "Label"

    def test_line_number_is_keyword_variant(self):
        lines = ['05 LINE NUMBER IS 4 COL 1 VALUE "Test".']
        screens = parse_screen_section(lines)
        assert screens[0].line == 4

    def test_column_number_is_keyword_variant(self):
        lines = ['05 LINE 1 COLUMN NUMBER IS 8 VALUE "Test".']
        screens = parse_screen_section(lines)
        assert screens[0].column == 8


# --- Full parse_cobol integration ---


class TestScreenSectionParseCobol:
    """Test that parse_cobol correctly extracts SCREEN SECTION."""

    COBOL_WITH_SCREEN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCREENTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(20).
       01 WS-AGE  PIC 9(3).
       SCREEN SECTION.
       01 MAIN-SCREEN.
          05 BLANK SCREEN.
          05 LINE 1 COL 1 VALUE "Name: ".
          05 LINE 1 COL 10 PIC X(20) USING WS-NAME.
          05 LINE 2 COL 1 VALUE "Age: ".
          05 LINE 2 COL 10 PIC 9(3) USING WS-AGE.
       01 ERROR-SCREEN.
          05 LINE 24 COL 1 VALUE "Error!" BLINK REVERSE-VIDEO.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY MAIN-SCREEN.
           ACCEPT MAIN-SCREEN.
           STOP RUN.
"""

    def test_screen_section_parsed(self):
        prog = parse_cobol(self.COBOL_WITH_SCREEN)
        assert len(prog.screen_section) == 2
        assert prog.screen_section[0].name == "MAIN-SCREEN"
        assert prog.screen_section[1].name == "ERROR-SCREEN"

    def test_screen_fields_correct(self):
        prog = parse_cobol(self.COBOL_WITH_SCREEN)
        main = prog.screen_section[0]
        assert len(main.children) == 5  # BLANK SCREEN + 4 fields
        blank = main.children[0]
        assert blank.blank_screen is True
        name_label = main.children[1]
        assert name_label.value == "Name: "
        assert name_label.line == 1
        assert name_label.column == 1

    def test_working_storage_not_polluted(self):
        """Screen items should not leak into working-storage."""
        prog = parse_cobol(self.COBOL_WITH_SCREEN)
        ws_names = [i.name for i in prog.working_storage]
        assert "MAIN-SCREEN" not in ws_names
        assert "ERROR-SCREEN" not in ws_names
        # Only WS-NAME and WS-AGE should be there
        assert "WS-NAME" in ws_names
        assert "WS-AGE" in ws_names

    def test_no_screen_section_backward_compat(self):
        """Programs without SCREEN SECTION should have empty screen_section."""
        prog = parse_cobol("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOSCREEN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FIELD PIC X(10).
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
""")
        assert prog.screen_section == []


# --- Mapper tests ---


class TestScreenSectionMapper:
    """Test Python code generation for SCREEN SECTION programs."""

    COBOL_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SCRMAP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(20).
       01 WS-AGE  PIC 9(3).
       SCREEN SECTION.
       01 MAIN-SCREEN.
          05 BLANK SCREEN.
          05 LINE 1 COL 1 VALUE "Name: ".
          05 LINE 1 COL 10 PIC X(20) USING WS-NAME.
          05 LINE 2 COL 1 VALUE "Age: ".
          05 LINE 2 COL 10 PIC 9(3) USING WS-AGE.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY MAIN-SCREEN.
           ACCEPT MAIN-SCREEN.
           STOP RUN.
"""

    def _generate(self, source=None):
        prog = parse_cobol(source or self.COBOL_SOURCE)
        smap = analyze(prog)
        return generate_python(smap)

    def test_generates_valid_python(self):
        code = self._generate()
        # Should compile without syntax errors
        compile(code, "<screen_test>", "exec")

    def test_screen_layout_comments(self):
        code = self._generate()
        assert "SCREEN SECTION" in code
        assert "SCREEN: MAIN-SCREEN" in code
        assert "BLANK SCREEN" in code
        assert 'TODO(high): implement screen I/O' in code

    def test_display_screen_generates_print(self):
        code = self._generate()
        assert "# DISPLAY MAIN-SCREEN" in code
        assert "print(" in code

    def test_accept_screen_generates_input(self):
        code = self._generate()
        assert "# ACCEPT MAIN-SCREEN" in code
        assert "input()" in code

    def test_display_uses_using_fields(self):
        code = self._generate()
        assert "ws_name" in code
        assert "ws_age" in code

    def test_accept_sets_using_fields(self):
        code = self._generate()
        # ACCEPT with USING should generate .set(input())
        assert ".set(input())" in code

    def test_display_non_screen_still_works(self):
        """DISPLAY of non-screen items should still use standard translator."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NONSCR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(20) VALUE "Hello".
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-MSG.
           STOP RUN.
"""
        code = self._generate(source)
        assert "print(" in code
        # Should NOT have screen-related comments
        assert "SCREEN SECTION" not in code

    def test_accept_non_screen_still_works(self):
        """ACCEPT of non-screen items should still use standard translator."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NONSCR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-INPUT PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT WS-INPUT.
           STOP RUN.
"""
        code = self._generate(source)
        assert "input()" in code
        assert "SCREEN SECTION" not in code

    def test_from_field_display(self):
        """FROM field in DISPLAY should use print()."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FROMTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TITLE PIC X(20) VALUE "Hello".
       SCREEN SECTION.
       01 TITLE-SCREEN.
          05 LINE 1 COL 1 PIC X(20) FROM WS-TITLE.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY TITLE-SCREEN.
           STOP RUN.
"""
        code = self._generate(source)
        assert "# DISPLAY TITLE-SCREEN" in code
        assert "ws_title" in code
        compile(code, "<from_test>", "exec")

    def test_to_field_accept(self):
        """TO field in ACCEPT should use input()."""
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TOTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-DATA PIC X(20).
       SCREEN SECTION.
       01 INPUT-SCREEN.
          05 LINE 1 COL 1 VALUE "Enter: ".
          05 LINE 1 COL 10 PIC X(20) TO WS-DATA.
       PROCEDURE DIVISION.
       MAIN-PARA.
           ACCEPT INPUT-SCREEN.
           STOP RUN.
"""
        code = self._generate(source)
        assert "# ACCEPT INPUT-SCREEN" in code
        assert "ws_data" in code
        assert ".set(input())" in code
        compile(code, "<to_test>", "exec")


# --- Edge cases ---


class TestScreenEdgeCases:
    """Edge cases and error handling."""

    def test_screen_section_between_ws_and_procedure(self):
        """SCREEN SECTION between WORKING-STORAGE and PROCEDURE."""
        prog = parse_cobol("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. EDGETEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(10).
       SCREEN SECTION.
       01 SCR-1.
          05 LINE 1 COL 1 VALUE "X".
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
""")
        assert len(prog.screen_section) == 1
        assert prog.screen_section[0].name == "SCR-1"
        assert len(prog.working_storage) == 1
        assert prog.working_storage[0].name == "WS-X"

    def test_screen_section_with_colors(self):
        """Foreground and background colors are captured."""
        prog = parse_cobol("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COLORTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(10).
       SCREEN SECTION.
       01 COLOR-SCR.
          05 LINE 1 COL 1 PIC X(10) USING WS-X
             FOREGROUND-COLOR 7 BACKGROUND-COLOR 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
""")
        assert len(prog.screen_section) == 1
        f = prog.screen_section[0].children[0]
        assert "FOREGROUND-COLOR 7" in f.attributes
        assert "BACKGROUND-COLOR 1" in f.attributes

    def test_screen_with_no_procedure_reference(self):
        """Screen section is parsed even if not referenced in PROCEDURE."""
        prog = parse_cobol("""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOREF.
       DATA DIVISION.
       SCREEN SECTION.
       01 UNUSED-SCREEN.
          05 LINE 1 COL 1 VALUE "Unused".
       PROCEDURE DIVISION.
       MAIN-PARA.
           STOP RUN.
""")
        assert len(prog.screen_section) == 1
        assert prog.screen_section[0].name == "UNUSED-SCREEN"
