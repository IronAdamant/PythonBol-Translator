"""Tests for CICS-to-Flask translation framework.

Validates:
  - has_cics detection
  - Map, transid, and commarea extraction from EXEC CICS blocks
  - Flask template generation produces valid Python (ast.parse)
  - HTML generation from SCREEN SECTION fields
  - Programs without CICS return None
  - Mapper integration (commented CICS section in generated code)
"""

from __future__ import annotations

import ast

from cobol_safe_translator.cics_translator import (
    has_cics,
    generate_cics_template,
    _extract_maps,
    _extract_transids,
    _extract_commareas,
    _generate_html_from_screen,
)
from cobol_safe_translator.models import (
    CobolProgram,
    CobolStatement,
    Paragraph,
    ScreenField,
)
from cobol_safe_translator.parser import parse_cobol
from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python


# ---------------------------------------------------------------------------
# Helper: build a minimal CobolProgram with CICS statements
# ---------------------------------------------------------------------------
def _make_cics_program(
    raw_texts: list[str],
    program_id: str = "TESTPROG",
    screen_section: list[ScreenField] | None = None,
) -> CobolProgram:
    """Build a CobolProgram with statements containing the given raw texts."""
    stmts = [
        CobolStatement(verb="EXEC", raw_text=t, operands=[])
        for t in raw_texts
    ]
    return CobolProgram(
        program_id=program_id,
        paragraphs=[Paragraph(name="MAIN-PARA", statements=stmts)],
        screen_section=screen_section or [],
    )


# ---------------------------------------------------------------------------
# 1. has_cics detection
# ---------------------------------------------------------------------------
class TestHasCics:
    """Test has_cics() detection."""

    def test_detects_cics_in_raw_text(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MENUMAP') END-EXEC",
        ])
        assert has_cics(prog) is True

    def test_false_for_non_cics_program(self):
        prog = CobolProgram(
            program_id="NOCICS",
            paragraphs=[Paragraph(
                name="MAIN",
                statements=[
                    CobolStatement(verb="DISPLAY", raw_text="DISPLAY 'HELLO'", operands=[]),
                ],
            )],
        )
        assert has_cics(prog) is False

    def test_false_for_empty_program(self):
        prog = CobolProgram(program_id="EMPTY")
        assert has_cics(prog) is False

    def test_case_insensitive_detection(self):
        prog = _make_cics_program([
            "exec cics send map('lower') end-exec",
        ])
        assert has_cics(prog) is True


# ---------------------------------------------------------------------------
# 2. Map extraction
# ---------------------------------------------------------------------------
class TestExtractMaps:
    """Test _extract_maps() from SEND MAP / RECEIVE MAP patterns."""

    def test_send_map(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MENUMAP') MAPSET('MENUSET') END-EXEC",
        ])
        maps = _extract_maps(prog)
        assert maps == ["MENUMAP"]

    def test_receive_map(self):
        prog = _make_cics_program([
            "EXEC CICS RECEIVE MAP('INPMAP') END-EXEC",
        ])
        maps = _extract_maps(prog)
        assert maps == ["INPMAP"]

    def test_multiple_maps_deduped(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MAP1') END-EXEC",
            "EXEC CICS RECEIVE MAP('MAP1') END-EXEC",
            "EXEC CICS SEND MAP('MAP2') END-EXEC",
        ])
        maps = _extract_maps(prog)
        assert maps == ["MAP1", "MAP2"]

    def test_no_maps(self):
        prog = _make_cics_program([
            "EXEC CICS RETURN END-EXEC",
        ])
        maps = _extract_maps(prog)
        assert maps == []

    def test_map_without_quotes(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP(MYMAP) END-EXEC",
        ])
        maps = _extract_maps(prog)
        assert maps == ["MYMAP"]


# ---------------------------------------------------------------------------
# 3. Transid extraction
# ---------------------------------------------------------------------------
class TestExtractTransids:
    """Test _extract_transids() from START TRANSID patterns."""

    def test_start_transid(self):
        prog = _make_cics_program([
            "EXEC CICS START TRANSID('MN01') END-EXEC",
        ])
        transids = _extract_transids(prog)
        assert transids == ["MN01"]

    def test_multiple_transids_deduped(self):
        prog = _make_cics_program([
            "EXEC CICS START TRANSID('MN01') END-EXEC",
            "EXEC CICS START TRANSID('MN01') END-EXEC",
            "EXEC CICS START TRANSID('MN02') END-EXEC",
        ])
        transids = _extract_transids(prog)
        assert transids == ["MN01", "MN02"]

    def test_no_transids(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MAP1') END-EXEC",
        ])
        transids = _extract_transids(prog)
        assert transids == []


# ---------------------------------------------------------------------------
# 4. Commarea extraction
# ---------------------------------------------------------------------------
class TestExtractCommareas:
    """Test _extract_commareas() from COMMAREA patterns."""

    def test_commarea_in_link(self):
        prog = _make_cics_program([
            "EXEC CICS LINK PROGRAM('SUBPROG') COMMAREA(WS-COMM) END-EXEC",
        ])
        commareas = _extract_commareas(prog)
        assert commareas == ["WS-COMM"]

    def test_no_commarea(self):
        prog = _make_cics_program([
            "EXEC CICS RETURN END-EXEC",
        ])
        commareas = _extract_commareas(prog)
        assert commareas == []

    def test_multiple_commareas_deduped(self):
        prog = _make_cics_program([
            "EXEC CICS LINK PROGRAM('A') COMMAREA(COMM-A) END-EXEC",
            "EXEC CICS XCTL PROGRAM('B') COMMAREA(COMM-A) END-EXEC",
            "EXEC CICS LINK PROGRAM('C') COMMAREA(COMM-B) END-EXEC",
        ])
        commareas = _extract_commareas(prog)
        assert commareas == ["COMM-A", "COMM-B"]


# ---------------------------------------------------------------------------
# 5. Flask template generation
# ---------------------------------------------------------------------------
class TestGenerateCicsTemplate:
    """Test generate_cics_template() output."""

    def test_returns_none_for_non_cics(self):
        prog = CobolProgram(
            program_id="NOCICS",
            paragraphs=[Paragraph(
                name="MAIN",
                statements=[
                    CobolStatement(verb="DISPLAY", raw_text="DISPLAY X", operands=[]),
                ],
            )],
        )
        result = generate_cics_template(prog)
        assert result is None

    def test_generates_valid_python(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MENUMAP') END-EXEC",
            "EXEC CICS RECEIVE MAP('MENUMAP') END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        # Must be valid Python (assuming flask is importable)
        # We only check ast.parse (syntax), not execution
        ast.parse(template)

    def test_contains_flask_imports(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MAP1') END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        assert "from flask import" in template
        assert "Flask" in template

    def test_route_for_each_map(self):
        prog = _make_cics_program([
            "EXEC CICS SEND MAP('MENUMAP') END-EXEC",
            "EXEC CICS SEND MAP('DETLMAP') END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        assert "/menumap" in template
        assert "/detlmap" in template
        assert "def menumap()" in template
        assert "def detlmap()" in template

    def test_generic_route_without_maps(self):
        prog = _make_cics_program([
            "EXEC CICS RETURN END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        assert "def index()" in template
        assert '@app.route("/", methods=["GET", "POST"])' in template

    def test_commarea_fields_in_comments(self):
        prog = _make_cics_program([
            "EXEC CICS LINK PROGRAM('SUB') COMMAREA(WS-COMM) END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        assert "WS-COMM" in template
        assert "COMMAREA fields" in template

    def test_transid_in_comments(self):
        prog = _make_cics_program([
            "EXEC CICS START TRANSID('MN01') END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        assert "MN01" in template
        assert "Transaction IDs" in template

    def test_main_block_present(self):
        prog = _make_cics_program([
            "EXEC CICS RETURN END-EXEC",
        ])
        template = generate_cics_template(prog)
        assert template is not None
        assert 'if __name__ == "__main__":' in template
        assert "app.run(debug=True)" in template


# ---------------------------------------------------------------------------
# 6. HTML generation from screen fields
# ---------------------------------------------------------------------------
class TestGenerateHtmlFromScreen:
    """Test _generate_html_from_screen() output."""

    def test_value_becomes_label(self):
        screen = ScreenField(
            level=1, name="MAIN-SCREEN",
            children=[
                ScreenField(level=5, value="Name: ", line=1, column=1),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert any("Name: " in line for line in html)
        assert any("<label>" in line for line in html)

    def test_using_becomes_input(self):
        screen = ScreenField(
            level=1, name="MAIN-SCREEN",
            children=[
                ScreenField(
                    level=5, pic="X(20)", using="WS-NAME",
                    line=1, column=10,
                ),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert any("ws_name" in line for line in html)
        assert any('<input type="text"' in line for line in html)
        assert any('maxlength="20"' in line for line in html)

    def test_to_field_becomes_input(self):
        screen = ScreenField(
            level=1, name="INPUT-SCREEN",
            children=[
                ScreenField(
                    level=5, pic="X(10)", to_field="WS-DATA",
                    line=1, column=10,
                ),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert any("ws_data" in line for line in html)
        assert any('<input type="text"' in line for line in html)

    def test_from_field_becomes_span(self):
        screen = ScreenField(
            level=1, name="DISPLAY-SCREEN",
            children=[
                ScreenField(
                    level=5, pic="X(20)", from_field="WS-TITLE",
                    line=1, column=1,
                ),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert any("<span>" in line for line in html)
        assert any("ws_title" in line for line in html)

    def test_empty_screen_returns_empty(self):
        screen = ScreenField(level=1, name="EMPTY-SCREEN")
        html = _generate_html_from_screen(screen)
        assert html == []

    def test_blank_screen_only_returns_empty(self):
        screen = ScreenField(
            level=1, name="BLANK-ONLY",
            children=[
                ScreenField(level=5, blank_screen=True),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert html == []

    def test_nested_children_collected(self):
        screen = ScreenField(
            level=1, name="NESTED",
            children=[
                ScreenField(
                    level=5, name="GROUP",
                    children=[
                        ScreenField(level=10, value="Label: ", line=1, column=1),
                        ScreenField(
                            level=10, pic="X(10)", using="WS-FIELD",
                            line=1, column=10,
                        ),
                    ],
                ),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert any("Label: " in line for line in html)
        assert any("ws_field" in line for line in html)

    def test_html_structure(self):
        screen = ScreenField(
            level=1, name="FORM-SCREEN",
            children=[
                ScreenField(level=5, value="Enter data:", line=1, column=1),
                ScreenField(
                    level=5, pic="X(20)", using="WS-INPUT",
                    line=2, column=1,
                ),
            ],
        )
        html = _generate_html_from_screen(screen)
        assert html[0] == "<!DOCTYPE html>"
        assert any("<form" in line for line in html)
        assert any("</form>" in line for line in html)
        assert any("<button" in line for line in html)
        assert any("</html>" in line for line in html)


# ---------------------------------------------------------------------------
# 7. Mapper integration (CICS comment block in generated Python)
# ---------------------------------------------------------------------------
class TestMapperCicsIntegration:
    """Test that mapper appends CICS template as comments for CICS programs."""

    CICS_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICSDEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC X(20).
       PROCEDURE DIVISION.
       MAIN-PARA.
      * TODO(high): EXEC CICS block -- requires manual translation
      * Original: EXEC CICS SEND MAP('MAINMAP') END-EXEC
      * CICS MAP: MAINMAP
      * Hint: UI output -> print() or template rendering
           DISPLAY WS-NAME.
           STOP RUN.
"""

    NON_CICS_COBOL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SIMPLE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-MSG PIC X(20) VALUE "Hello".
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-MSG.
           STOP RUN.
"""

    def test_cics_program_has_flask_comment_block(self):
        prog = parse_cobol(self.CICS_COBOL)
        smap = analyze(prog)
        code = generate_python(smap)
        assert "CICS TRANSACTION FRAMEWORK" in code
        assert "Flask template" in code
        assert "pip install flask" in code

    def test_non_cics_program_has_no_flask_block(self):
        prog = parse_cobol(self.NON_CICS_COBOL)
        smap = analyze(prog)
        code = generate_python(smap)
        assert "CICS TRANSACTION FRAMEWORK" not in code
        assert "Flask template" not in code

    def test_cics_generated_code_is_valid_python(self):
        prog = parse_cobol(self.CICS_COBOL)
        smap = analyze(prog)
        code = generate_python(smap)
        # The CICS template is commented out, so the whole file
        # should still be valid Python
        ast.parse(code)


# ---------------------------------------------------------------------------
# 8. Screen section integration with CICS template
# ---------------------------------------------------------------------------
class TestCicsWithScreenSection:
    """Test CICS template generation with SCREEN SECTION data."""

    def test_screen_section_generates_html_hints(self):
        prog = _make_cics_program(
            raw_texts=[
                "EXEC CICS SEND MAP('MAINMAP') END-EXEC",
            ],
            screen_section=[
                ScreenField(
                    level=1, name="MAIN-SCREEN",
                    children=[
                        ScreenField(level=5, value="Name: ", line=1, column=1),
                        ScreenField(
                            level=5, pic="X(20)", using="WS-NAME",
                            line=1, column=10,
                        ),
                    ],
                ),
            ],
        )
        template = generate_cics_template(prog)
        assert template is not None
        assert "HTML Template Generation" in template
        assert "templates/" in template
        assert "ws_name" in template
