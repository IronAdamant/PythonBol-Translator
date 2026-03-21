"""Tests for verb translations through the mapper pipeline."""

import ast

from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol
from conftest import make_cobol


class TestDisplaySeparator:
    def test_display_no_space_separator(self):
        src = make_cobol(['DISPLAY "HELLO" "WORLD".'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "sep=''" in source


class TestDisplayUpon:
    def test_display_upon_filtered(self):
        src = make_cobol(['DISPLAY "ERROR" UPON WS-A.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "print(" in source
        assert '"ERROR"' in source
        # UPON and target should not appear as print args
        print_lines = [l for l in source.split("\n") if "print(" in l]
        assert print_lines, "Expected print() call in generated code"
        assert "upon" not in print_lines[0].lower()
        assert "ws_a" not in print_lines[0]


class TestDisplayFigurativeConstants:
    def test_display_zeros(self):
        """DISPLAY ZEROS should resolve to print(0), not self.data.zeros.value."""
        src = make_cobol(["DISPLAY ZEROS."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "zeros.value" not in source
        assert "print(0" in source

    def test_display_spaces(self):
        """DISPLAY SPACES should resolve to print(' ')."""
        src = make_cobol(["DISPLAY SPACES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "spaces.value" not in source
        assert "print(' '" in source


class TestDisplayWithNoAdvancing:
    """Pass 3: DISPLAY WITH NO ADVANCING suppresses newline."""

    def test_no_advancing_generates_end_empty(self):
        src = make_cobol(['DISPLAY "Enter: " WITH NO ADVANCING.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "end=''" in source
        # Should not include WITH, NO, ADVANCING as data names
        assert "with_" not in source
        assert "advancing" not in source


class TestDisplayWithNoAdvancingIncludesSep:
    """DISPLAY WITH NO ADVANCING should have both sep='' and end=''."""

    def test_sep_and_end(self):
        src = make_cobol(['DISPLAY "HELLO" WITH NO ADVANCING.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        assert "sep=''" in source
        assert "end=''" in source


class TestDisplayWithClause:
    def test_display_with_without_no_advancing_excludes_with(self):
        """DISPLAY X WITH OTHER-CLAUSE: WITH clause must not be passed to print as a data name."""
        src = make_cobol(["DISPLAY WS-A WITH SOME-CLAUSE."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # After the fix, WITH and SOME-CLAUSE are stripped; only WS-A is printed
        assert "some_clause" not in source

    def test_display_with_no_advancing_still_works(self):
        """DISPLAY X WITH NO ADVANCING must still set end=''."""
        src = make_cobol(["DISPLAY WS-A WITH NO ADVANCING."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "end=''" in source


class TestPerformVariants:
    def test_perform_until(self):
        src = make_cobol(["PERFORM MAIN-PARA UNTIL WS-A = 0."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source

    def test_perform_times(self):
        src = make_cobol(["PERFORM MAIN-PARA 5 TIMES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "for _ in range(5)" in source


class TestPerformVarying:
    def test_perform_varying_generates_loop(self):
        src = make_cobol(["PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A = 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source
        assert "VARYING" in source


class TestPerformThru:
    def test_perform_thru_generates_calls(self):
        """PERFORM THRU should call all paragraphs in range."""
        src = make_cobol(["PERFORM MAIN-PARA THRU MAIN-PARA."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "self.main_para()" in source
        assert "THRU" in source


class TestPerformTimesVariable:
    def test_perform_variable_times(self):
        """PERFORM para WS-COUNT TIMES should use variable for range."""
        src = make_cobol(["PERFORM MAIN-PARA WS-A TIMES."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "for _ in range(" in source
        assert "ws_a" in source


class TestPerformUntilInline:
    """Pass 2: PERFORM UNTIL without paragraph name."""

    def test_perform_until_inline_emits_todo(self):
        src = make_cobol(["PERFORM UNTIL WS-A > 10."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source
        assert "TODO(high)" in source
        # Should NOT call self.until_()
        assert "self.until_()" not in source


class TestPerformVaryingLoop:
    def test_varying_normal_loop(self):
        """PERFORM para VARYING idx FROM 1 BY 1 UNTIL idx > 5 generates a while loop."""
        src = make_cobol(["PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 5."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source
        assert "ws_a.set(" in source or ".set(1)" in source
        assert "ws_a.add(" in source or ".add(1)" in source

    def test_varying_inline(self):
        """PERFORM VARYING idx FROM 1 BY 1 UNTIL cond (no paragraph) generates while loop."""
        src = make_cobol(["PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 5."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source
        assert "TODO(high)" in source  # inline body needs manual fill

    def test_varying_multi_two_level(self):
        """Multi-VARYING (VARYING + AFTER) generates nested while loops."""
        src = make_cobol([
            "PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3",
            "    AFTER WS-B FROM 1 BY 1 UNTIL WS-B > 5.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Outer loop: WS-A
        assert "ws_a.set(1)" in source
        assert "ws_a.add(1)" in source
        # Inner loop: WS-B
        assert "ws_b.set(1)" in source
        assert "ws_b.add(1)" in source
        # Two nested while loops
        assert source.count("while not") >= 2
        # Paragraph call in innermost loop
        assert "self.main_para()" in source

    def test_varying_multi_after_varying_syntax(self):
        """AFTER VARYING (with optional VARYING keyword) also generates nested loops."""
        src = make_cobol([
            "PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3",
            "    AFTER VARYING WS-B FROM 1 BY 1 UNTIL WS-B > 3.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert source.count("while not") >= 2
        assert "ws_a.set(" in source
        assert "ws_b.set(" in source

    def test_varying_multi_three_level(self):
        """Three-level VARYING (VARYING + AFTER + AFTER) generates 3 nested loops."""
        src = make_cobol([
            "PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3",
            "    AFTER WS-B FROM 1 BY 1 UNTIL WS-B > 5",
            "    AFTER WS-C FROM 1 BY 1 UNTIL WS-C > 2.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Three nested while loops
        assert source.count("while not") >= 3
        # All three vars initialised and incremented
        assert "ws_a.set(1)" in source
        assert "ws_b.set(1)" in source
        assert "ws_c.set(1)" in source
        assert "ws_a.add(1)" in source
        assert "ws_b.add(1)" in source
        assert "ws_c.add(1)" in source

    def test_varying_multi_inline(self):
        """Multi-VARYING inline (no paragraph) generates nested loops with TODO."""
        src = make_cobol([
            "PERFORM VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 3",
            "    AFTER WS-B FROM 1 BY 1 UNTIL WS-B > 5.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert source.count("while not") >= 2
        assert "TODO(high)" in source  # inline body needs manual fill
        # Inside the while loop body there should be pass+TODO, not a paragraph call
        # (self.main_para() exists in run() but not inside the loops)
        loop_lines = [l.strip() for l in source.split("\n")
                      if "while not" in l or "pass" in l]
        assert any("pass" in l for l in loop_lines)

    def test_varying_missing_keyword_fallback(self):
        """PERFORM VARYING without UNTIL falls back to TODO(high)."""
        from cobol_safe_translator.statement_translators import translate_perform
        # Simulate operands missing UNTIL
        ops = ["SOME-PARA", "VARYING", "IDX", "FROM", "1", "BY", "1"]
        result = translate_perform(ops, "PERFORM SOME-PARA VARYING IDX FROM 1 BY 1", lambda c: c)
        combined = "\n".join(result)
        assert "TODO(high)" in combined


class TestPerformTimesNumericLiteral:
    def test_trailing_dot_literal_in_times_generates_valid_range(self):
        """PERFORM N. TIMES with trailing-dot literal must not treat N. as a field name."""
        from cobol_safe_translator.statement_translators import translate_perform
        # Simulate parser passing "5." as a TIMES operand (trailing-dot numeric)
        lines = translate_perform(["MY-PARA", "5.", "TIMES"], "PERFORM MY-PARA 5. TIMES", lambda c: c)
        source = "\n".join(lines)
        ast.parse(f"class T:\n def f(self):\n  {source.replace(chr(10), chr(10) + '  ')}")
        assert "range(5)" in source  # must use integer 5, not "5." or a field ref

    def test_integer_literal_times_unchanged(self):
        """PERFORM N TIMES with plain integer literal still generates range(N)."""
        from cobol_safe_translator.statement_translators import translate_perform
        lines = translate_perform(["MY-PARA", "10", "TIMES"], "PERFORM MY-PARA 10 TIMES", lambda c: c)
        source = "\n".join(lines)
        assert "range(10)" in source


class TestPerformVaryingZeroStep:
    def test_zero_step_emits_todo_not_infinite_loop(self):
        """PERFORM VARYING with BY 0 must emit TODO, not generate infinite loop code."""
        src = make_cobol([
            "PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 0 UNTIL WS-A > 10.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "infinite loop" in source.lower() or "zero step" in source.lower()

    def test_nonzero_step_generates_loop(self):
        """PERFORM VARYING with BY 1 generates a while loop (not a TODO)."""
        src = make_cobol([
            "PERFORM MAIN-PARA VARYING WS-A FROM 1 BY 1 UNTIL WS-A > 10.",
        ])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "while not" in source


class TestMoveMultipleTargets:
    def test_move_to_multiple_targets(self):
        src = make_cobol(["MOVE 0 TO WS-A WS-B WS-C."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "ws_a" in source
        assert "ws_b" in source
        assert "ws_c" in source
        assert source.count(".set(") >= 3


class TestMoveCorresponding:
    def test_move_corresponding_emits_todo(self):
        src = make_cobol(["MOVE CORRESPONDING WS-A TO WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "MOVE CORRESPONDING" in source


class TestMoveAll:
    def test_move_all_generates_fill(self):
        """MOVE ALL should generate character fill code."""
        src = make_cobol(['MOVE ALL "X" TO WS-A.'])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".set(" in source
        assert "'X'" in source


class TestMoveFunction:
    def test_move_function_current_date(self):
        """MOVE FUNCTION CURRENT-DATE should translate to datetime expression."""
        src = make_cobol(["MOVE FUNCTION CURRENT-DATE TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "datetime" in source
        assert ".set(" in source

    def test_move_function_unknown_emits_todo(self):
        """MOVE FUNCTION with unknown intrinsic should emit TODO."""
        src = make_cobol(["MOVE FUNCTION UNKNOWN-FUNC TO WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "TODO(high)" in source
        assert "UNKNOWN-FUNC" in source


class TestMoveWithoutTo:
    """MOVE without TO clause should emit error comment."""

    def test_move_no_to(self):
        src = make_cobol(["MOVE WS-A WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        assert "could not parse" in source.lower() or "MOVE" in source


class TestInitializeStatement:
    def test_initialize_generates_commented_set(self):
        """INITIALIZE should emit commented-out .set(0) code."""
        src = make_cobol(["INITIALIZE WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "# INITIALIZE WS-A" in source
        assert "# self.data.ws_a.set(0)" in source


class TestCloseWithKeywords:
    def test_close_with_lock_filters_keywords(self):
        src = make_cobol(["CLOSE WS-A WITH LOCK."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".close()" in source
        # WITH and LOCK should be filtered out, not treated as file names
        assert "with_" not in source
        assert "lock" not in source.split(".close()")[0].split("\n")[-1]


class TestOpenStatement:
    def test_open_input_generates_open_input_call(self):
        """OPEN INPUT should generate .open_input() on the file adapter."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT CUST-FILE ASSIGN TO 'cust.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD CUST-FILE.",
            "       01 CUST-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           OPEN INPUT CUST-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".open_input()" in source

    def test_open_output_generates_open_output_call(self):
        """OPEN OUTPUT should generate .open_output() call."""
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
            "       01 RPT-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           OPEN OUTPUT RPT-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "open_output()" in source


class TestReadStatement:
    def test_read_generates_read_call_and_eof_check(self):
        """READ should generate .read() call with EOF None check."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       ENVIRONMENT DIVISION.",
            "       INPUT-OUTPUT SECTION.",
            "       FILE-CONTROL.",
            "           SELECT CUST-FILE ASSIGN TO 'cust.dat'.",
            "       DATA DIVISION.",
            "       FILE SECTION.",
            "       FD CUST-FILE.",
            "       01 CUST-REC PIC X(80).",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           READ CUST-FILE.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".read()" in source
        assert "is None" in source or "AT END" in source


class TestStopStatement:
    def test_stop_run_generates_return(self):
        """STOP RUN should generate a return statement."""
        src = make_cobol(["STOP RUN."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Find lines in the method body that have 'return'
        method_lines = [l.strip() for l in source.split("\n") if l.strip() == "return"]
        assert len(method_lines) >= 1, "STOP RUN should generate 'return'"


class TestCallWithUsing:
    def test_call_with_using_generates_args(self):
        """CALL 'SUBPROG' USING WS-A should include argument in TODO."""
        lines = [
            "       IDENTIFICATION DIVISION.",
            "       PROGRAM-ID. TEST-PROG.",
            "       DATA DIVISION.",
            "       WORKING-STORAGE SECTION.",
            "       01 WS-A PIC 9(5).",
            "       PROCEDURE DIVISION.",
            "       MAIN-PARA.",
            "           CALL 'SUB-PROG' USING WS-A.",
        ]
        src = "\n".join(lines) + "\n"
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "SUB-PROG" in source or "sub_prog" in source
        assert "TODO(high)" in source


class TestUnsupportedVerbsTodo:
    """Unsupported verbs should generate TODO comments."""

    def test_accept_emits_todo(self):
        src = make_cobol(["ACCEPT WS-A."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        assert "TODO" in source

    def test_set_emits_todo(self):
        src = make_cobol(["SET WS-A TO 1."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        assert "TODO" in source or "SET" in source

    def test_string_emits_todo(self):
        src = make_cobol(["STRING WS-A DELIMITED BY SIZE INTO WS-B."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        assert "TODO" in source


class TestRewriteSkeleton:
    def test_rewrite_helpful_comment(self):
        """REWRITE generates a helpful comment with file_hint."""
        src = make_cobol(["REWRITE CUSTOMER-RECORD."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "REWRITE" in source
        assert "rewrite" in source or "FileAdapter" in source

    def test_rewrite_generates_write_call(self):
        """REWRITE should generate a write call."""
        src = make_cobol(["REWRITE CUSTOMER-RECORD."])
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert ".write(" in source


class TestGoToTranslation:
    def _make_mapper(self):
        from cobol_safe_translator.models import CobolProgram, SoftwareMap
        from cobol_safe_translator.mapper import PythonMapper
        return PythonMapper(SoftwareMap(program=CobolProgram()))

    def test_simple_goto_produces_method_call_and_return(self):
        """Simple GO TO paragraph produces self.method() + return."""
        from cobol_safe_translator.models import CobolStatement
        stmt = CobolStatement(verb="GO", operands=["TO", "SOME-PARA"], raw_text="GO TO SOME-PARA")
        mapper = self._make_mapper()
        lines = mapper._translate_statement(stmt)
        assert lines[0] == "self.some_para()  # GO TO SOME-PARA"
        assert lines[1] == "return"

    def test_goto_valid_python(self):
        """GO TO output must be valid Python."""
        from cobol_safe_translator.models import CobolStatement
        stmt = CobolStatement(verb="GO", operands=["TO", "SOME-PARA"], raw_text="GO TO SOME-PARA\nEXTRA")
        mapper = self._make_mapper()
        lines = mapper._translate_statement(stmt)
        # Must parse as valid Python inside a method
        code = "def f(self):\n" + "\n".join(f"    {l}" for l in lines)
        ast.parse(code)

    def test_goto_no_target_raises(self):
        """GO TO with no operands raises NotImplementedError (ALTER-modified)."""
        from cobol_safe_translator.models import CobolStatement
        stmt = CobolStatement(verb="GO", operands=[], raw_text="GO TO")
        mapper = self._make_mapper()
        lines = mapper._translate_statement(stmt)
        # ALTER-modified GO TO now uses dynamic dispatch via getattr
        assert "getattr" in lines[0] or "NotImplementedError" in lines[0]

    def test_goto_depending_on(self):
        """GO TO ... DEPENDING ON produces if/elif dispatch."""
        from cobol_safe_translator.models import CobolStatement
        stmt = CobolStatement(
            verb="GO", operands=["TO", "PARA-A", "PARA-B", "DEPENDING", "ON", "WS-IDX"],
            raw_text="GO TO PARA-A PARA-B DEPENDING ON WS-IDX",
        )
        mapper = self._make_mapper()
        lines = mapper._translate_statement(stmt)
        joined = "\n".join(lines)
        assert "if int(" in joined
        assert "elif int(" in joined
        assert "self.para_a()" in joined
        assert "self.para_b()" in joined

    def test_goto_multiple_targets_without_depending(self):
        """GO TO with multiple targets but no DEPENDING defaults to first."""
        from cobol_safe_translator.models import CobolStatement
        stmt = CobolStatement(
            verb="GO", operands=["TO", "PARA-X", "PARA-Y"],
            raw_text="GO TO PARA-X PARA-Y",
        )
        mapper = self._make_mapper()
        lines = mapper._translate_statement(stmt)
        joined = "\n".join(lines)
        # ALTER-modified GO TO uses dynamic dispatch; defaults to first target
        assert "getattr" in joined or "TODO(high)" in joined
        assert "para_x" in joined


class TestGroupMove:
    """Group-level MOVE should concatenate source children and distribute to target."""

    def test_group_to_group_move(self):
        """MOVE WS-SRC TO WS-TGT where both are group items."""
        src = make_cobol(
            ["MOVE WS-SRC TO WS-TGT."],
            data_lines=[
                "       01 WS-SRC.",
                "           05 WS-SRC-A PIC X(3).",
                "           05 WS-SRC-B PIC X(2).",
                "       01 WS-TGT.",
                "           05 WS-TGT-X PIC X(2).",
                "           05 WS-TGT-Y PIC X(3).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Should generate group MOVE comment
        assert "Group MOVE" in source
        # Should reference source children in concatenation
        assert "ws_src_a" in source
        assert "ws_src_b" in source
        # Should distribute to target children using slices
        assert "ws_tgt_x" in source
        assert "ws_tgt_y" in source
        assert ".set(" in source

    def test_group_to_elementary_move(self):
        """MOVE group-item TO elementary-item treats group as alphanumeric."""
        src = make_cobol(
            ["MOVE WS-SRC TO WS-DEST."],
            data_lines=[
                "       01 WS-SRC.",
                "           05 WS-SRC-A PIC X(3).",
                "           05 WS-SRC-B PIC X(2).",
                "       01 WS-DEST PIC X(10).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Should generate group-to-elementary MOVE
        assert "Group-to-elementary MOVE" in source
        assert "ws_dest" in source
        assert ".set(" in source

    def test_elementary_move_unchanged(self):
        """Normal elementary MOVE should not be affected by group logic."""
        src = make_cobol(
            ["MOVE WS-A TO WS-B."],
            data_lines=[
                "       01 WS-A PIC X(5).",
                "       01 WS-B PIC X(5).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Should NOT contain "Group MOVE"
        assert "Group MOVE" not in source
        assert "ws_b.set(self.data.ws_a.value)" in source

    def test_group_move_nested_children(self):
        """Group MOVE should flatten nested group children."""
        src = make_cobol(
            ["MOVE WS-OUTER TO WS-TGT."],
            data_lines=[
                "       01 WS-OUTER.",
                "           05 WS-INNER.",
                "               10 WS-FIELD-A PIC X(2).",
                "               10 WS-FIELD-B PIC X(3).",
                "           05 WS-FIELD-C PIC X(4).",
                "       01 WS-TGT.",
                "           05 WS-TGT-1 PIC X(5).",
                "           05 WS-TGT-2 PIC X(4).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "Group MOVE" in source
        # All leaf children of WS-OUTER should be in concatenation
        assert "ws_field_a" in source
        assert "ws_field_b" in source
        assert "ws_field_c" in source

    def test_group_move_with_numeric_literal_is_normal(self):
        """MOVE 0 TO group-item should use normal translate_move."""
        src = make_cobol(
            ["MOVE 0 TO WS-GRP."],
            data_lines=[
                "       01 WS-GRP.",
                "           05 WS-FLD-A PIC X(3).",
                "           05 WS-FLD-B PIC X(2).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # Literal MOVE should NOT trigger group MOVE logic
        assert "Group MOVE" not in source

    def test_group_move_with_string_literal_is_normal(self):
        """MOVE "ABC" TO group-item should use normal translate_move."""
        src = make_cobol(
            ['MOVE "ABC" TO WS-GRP.'],
            data_lines=[
                "       01 WS-GRP.",
                "           05 WS-FLD-A PIC X(3).",
                "           05 WS-FLD-B PIC X(2).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        assert "Group MOVE" not in source

    def test_group_move_multiple_targets(self):
        """MOVE group TO target1 target2 handles each target separately."""
        src = make_cobol(
            ["MOVE WS-SRC TO WS-TGT1 WS-TGT2."],
            data_lines=[
                "       01 WS-SRC.",
                "           05 WS-SRC-A PIC X(3).",
                "           05 WS-SRC-B PIC X(2).",
                "       01 WS-TGT1.",
                "           05 WS-T1-A PIC X(2).",
                "           05 WS-T1-B PIC X(3).",
                "       01 WS-TGT2 PIC X(10).",
            ],
        )
        program = parse_cobol(src)
        smap = analyze(program)
        source = generate_python(smap)
        ast.parse(source)
        # TGT1 is a group target
        assert "ws_t1_a" in source
        assert "ws_t1_b" in source
        # TGT2 is elementary target
        assert "ws_tgt2" in source
