"""Tests for IF/EVALUATE block translation through the mapper pipeline."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from conftest import make_cobol


class TestIfStatement:
    def test_inline_if_translates_condition(self):
        """Inline IF should translate the condition and emit TODO for inline body."""
        src = make_cobol(["IF WS-A > 0 DISPLAY WS-A END-IF."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "print(" in source  # inline body is now translated

    def test_multiline_if_generates_if_block(self):
        """Multi-line IF should generate a proper if block."""
        src = make_cobol([
            "IF WS-A > 0",
            "    DISPLAY WS-A",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "print(self.data.ws_a.value" in source

    def test_if_else_generates_both_branches(self):
        """IF/ELSE should generate if/else Python block."""
        src = make_cobol([
            "IF WS-A > 0",
            "    DISPLAY WS-A",
            "ELSE",
            "    DISPLAY WS-B",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "else:" in source
        assert "print(self.data.ws_a.value" in source
        assert "print(self.data.ws_b.value" in source

    def test_nested_if_valid_indentation(self):
        """Nested IF should generate valid Python (verified by ast.parse)."""
        src = make_cobol([
            "IF WS-A > 0",
            "    IF WS-B > 0",
            "        DISPLAY WS-B",
            "    END-IF",
            "ELSE",
            "    DISPLAY WS-C",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)  # Validates indentation correctness
        assert "if self.data.ws_a.value > 0:" in source
        assert "if self.data.ws_b.value > 0:" in source
        assert "else:" in source

    def test_if_with_perform_body(self):
        """IF with PERFORM in body should generate method call inside if block."""
        src = make_cobol([
            "IF WS-A > 0",
            "    PERFORM MAIN-PARA",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "self.main_para()" in source

    def test_statements_after_end_if_not_in_block(self):
        """Statements after END-IF should not be inside the if block."""
        src = make_cobol([
            "IF WS-A > 0",
            "    DISPLAY WS-A",
            "END-IF.",
            'DISPLAY "AFTER".',
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # "AFTER" print should be at the same indent as the if, not inside it
        lines = source.split("\n")
        after_line = [l for l in lines if '"AFTER"' in l]
        if_line = [l for l in lines if "if self.data.ws_a" in l]
        assert after_line, "Expected AFTER display in output"
        assert if_line, "Expected if statement in output"
        # Both should be at the same indentation level
        after_indent = len(after_line[0]) - len(after_line[0].lstrip())
        if_indent = len(if_line[0]) - len(if_line[0].lstrip())
        assert after_indent == if_indent, "AFTER should be at same indent as IF"


class TestEvaluateStatement:
    def test_evaluate_true_generates_if_elif_else(self):
        """EVALUATE TRUE with multiple WHENs should generate if/elif/else chain."""
        src = make_cobol([
            "EVALUATE TRUE",
            "    WHEN WS-A > 0",
            "        DISPLAY WS-A",
            "    WHEN OTHER",
            "        DISPLAY WS-B",
            "END-EVALUATE.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "else:" in source

    def test_evaluate_true_multiple_whens(self):
        """EVALUATE TRUE with 3 WHENs should generate if/elif/else."""
        src = make_cobol([
            "EVALUATE TRUE",
            "    WHEN WS-A > 10",
            "        DISPLAY WS-A",
            "    WHEN WS-A > 5",
            "        DISPLAY WS-B",
            "    WHEN OTHER",
            "        DISPLAY WS-C",
            "END-EVALUATE.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 10:" in source
        assert "elif self.data.ws_a.value > 5:" in source
        assert "else:" in source

    def test_evaluate_variable_equality(self):
        """EVALUATE variable should generate equality comparisons."""
        src = make_cobol([
            "EVALUATE WS-A",
            "    WHEN 1",
            '        DISPLAY "ONE"',
            "    WHEN 2",
            '        DISPLAY "TWO"',
            "    WHEN OTHER",
            '        DISPLAY "OTHER"',
            "END-EVALUATE.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.data.ws_a.value == 1" in source
        assert "self.data.ws_a.value == 2" in source
        assert "else:" in source

    def test_statements_after_end_evaluate(self):
        """Statements after END-EVALUATE should not be inside the block."""
        src = make_cobol([
            "EVALUATE TRUE",
            "    WHEN WS-A > 0",
            "        DISPLAY WS-A",
            "END-EVALUATE.",
            'DISPLAY "AFTER".',
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        lines = source.split("\n")
        after_line = [l for l in lines if '"AFTER"' in l]
        if_line = [l for l in lines if "if self.data.ws_a" in l]
        assert after_line, "Expected AFTER display in output"
        assert if_line, "Expected if statement in output"
        after_indent = len(after_line[0]) - len(after_line[0].lstrip())
        if_indent = len(if_line[0]) - len(if_line[0].lstrip())
        assert after_indent == if_indent, "AFTER should be at same indent as IF"

    def test_customer_report_evaluate(self):
        """customer-report.cob EVALUATE TRUE should generate valid Python."""
        from pathlib import Path
        cob = Path(__file__).resolve().parent.parent / "samples" / "customer-report.cob"
        program = parse_cobol(cob.read_text())
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Should have actual if/elif/else, not TODO placeholders
        assert "if self.data.cust_balance.value > self.data.cust_credit_limit.value:" in source
        assert "self.handle_over_limit()" in source
        assert "elif self.data.cust_balance.value < 0:" in source
        assert "self.handle_negative_balance()" in source
        assert "else:" in source
        assert "self.write_normal_record()" in source

    def test_inline_evaluate_now_translated(self):
        """Inline EVALUATE is now split and handled by block translator."""
        src = make_cobol(["EVALUATE TRUE WHEN OTHER DISPLAY WS-A END-EVALUATE."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Multi-line sentence joining splits this into proper block statements
        assert "if True:" in source
        assert "print(" in source


class TestSearchStatement:
    def test_serial_search_with_at_end(self):
        """SEARCH with AT END and WHEN should generate for-loop with break."""
        src = make_cobol([
            "SEARCH WS-TABLE",
            "    AT END",
            '        DISPLAY "NOT FOUND"',
            "    WHEN WS-A = 1",
            '        DISPLAY "FOUND"',
            "END-SEARCH.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "_found = False" in source
        assert "for _idx in range(len(self.data.ws_table)):" in source
        assert "if self.data.ws_a.value == 1:" in source
        assert "_found = True" in source
        assert "break" in source
        assert "if not _found:" in source
        assert '"NOT FOUND"' in source
        assert '"FOUND"' in source

    def test_search_all_generates_linear_scan_comment(self):
        """SEARCH ALL should emit a comment noting binary search is approximated."""
        src = make_cobol([
            "SEARCH ALL WS-TABLE",
            "    AT END",
            '        DISPLAY "NOT FOUND"',
            "    WHEN WS-KEY = WS-A",
            '        DISPLAY "FOUND"',
            "END-SEARCH.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "SEARCH ALL WS-TABLE" in source
        assert "binary search approximated as linear" in source
        assert "for _idx in range(" in source

    def test_search_without_at_end(self):
        """SEARCH without AT END should generate loop without the not-found block."""
        src = make_cobol([
            "SEARCH WS-TABLE",
            "    WHEN WS-A = 1",
            '        DISPLAY "FOUND"',
            "END-SEARCH.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "_found = False" in source
        assert "for _idx in range(" in source
        assert "break" in source
        assert "if not _found:" not in source

    def test_search_multiple_when_clauses(self):
        """SEARCH with multiple WHENs should generate multiple if-break blocks."""
        src = make_cobol([
            "SEARCH WS-TABLE",
            "    WHEN WS-A = 1",
            '        DISPLAY "ONE"',
            "    WHEN WS-A = 2",
            '        DISPLAY "TWO"',
            "END-SEARCH.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert source.count("break") == 2
        assert '"ONE"' in source
        assert '"TWO"' in source

    def test_search_multi_statement_when_body(self):
        """WHEN body with multiple statements should all appear inside the if."""
        src = make_cobol([
            "SEARCH WS-TABLE",
            "    WHEN WS-A = 1",
            "        MOVE 1 TO WS-B",
            '        DISPLAY "FOUND"',
            "END-SEARCH.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_b.set(1)" in source
        assert '"FOUND"' in source

    def test_search_inside_if(self):
        """SEARCH nested inside IF should produce valid Python."""
        src = make_cobol([
            "IF WS-A > 0",
            "    SEARCH WS-TABLE",
            "        AT END",
            '            DISPLAY "NOT FOUND"',
            "        WHEN WS-A = 1",
            '            DISPLAY "FOUND"',
            "    END-SEARCH",
            "END-IF.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "if self.data.ws_a.value > 0:" in source
        assert "for _idx in range(" in source

    def test_statements_after_end_search_not_in_block(self):
        """Statements after END-SEARCH should be at the same indent as SEARCH."""
        src = make_cobol([
            "SEARCH WS-TABLE",
            "    AT END",
            '        DISPLAY "NOT FOUND"',
            "    WHEN WS-A = 1",
            '        DISPLAY "FOUND"',
            "END-SEARCH.",
            'DISPLAY "AFTER".',
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        lines = source.split("\n")
        after_line = [l for l in lines if '"AFTER"' in l]
        search_line = [l for l in lines if "# SEARCH WS-TABLE" in l]
        assert after_line, "Expected AFTER display in output"
        assert search_line, "Expected SEARCH comment in output"
        after_indent = len(after_line[0]) - len(after_line[0].lstrip())
        search_indent = len(search_line[0]) - len(search_line[0].lstrip())
        assert after_indent == search_indent, "AFTER should be at same indent as SEARCH"
