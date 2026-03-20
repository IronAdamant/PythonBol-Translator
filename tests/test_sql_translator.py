"""Tests for EXEC SQL code generation.

Validates:
  - SqlBlock extraction from COBOL EXEC SQL blocks
  - Python DB-API 2.0 code generation from SqlBlock objects
  - Generated code passes ast.parse (valid Python)
  - Integration: full pipeline from COBOL source to valid Python with SQL
"""

from __future__ import annotations

import ast

from cobol_safe_translator.exec_block_handler import _parse_sql_block
from cobol_safe_translator.models import SqlBlock
from cobol_safe_translator.preprocessor import strip_exec_blocks
from cobol_safe_translator.sql_translator import (
    generate_sql_imports,
    generate_sql_init,
    translate_sql_block,
)
from cobol_safe_translator.analyzer import analyze
from cobol_safe_translator.mapper import generate_python
from cobol_safe_translator.parser import parse_cobol


# ---------------------------------------------------------------------------
# 1. SqlBlock extraction from preprocessor
# ---------------------------------------------------------------------------
class TestSqlBlockExtraction:
    """Test _parse_sql_block extracts structured metadata."""

    def test_include_sqlca(self):
        block = _parse_sql_block("EXEC SQL INCLUDE SQLCA END-EXEC")
        assert block is not None
        assert block.sql_type == "INCLUDE"

    def test_declare_cursor(self):
        block = _parse_sql_block(
            "EXEC SQL DECLARE EMP-CURSOR CURSOR FOR "
            "SELECT EMP-NAME, EMP-SALARY FROM EMPLOYEE "
            "WHERE DEPT = :WS-DEPT END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "DECLARE"
        assert block.cursor_name == "EMP-CURSOR"
        assert "WS-DEPT" in block.host_variables
        assert "SELECT" in block.sql_body

    def test_open_cursor(self):
        block = _parse_sql_block("EXEC SQL OPEN EMP-CURSOR END-EXEC")
        assert block is not None
        assert block.sql_type == "OPEN"
        assert block.cursor_name == "EMP-CURSOR"

    def test_fetch_cursor(self):
        block = _parse_sql_block(
            "EXEC SQL FETCH EMP-CURSOR INTO :WS-NAME, :WS-SALARY END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "FETCH"
        assert block.cursor_name == "EMP-CURSOR"
        assert block.into_variables == ["WS-NAME", "WS-SALARY"]

    def test_close_cursor(self):
        block = _parse_sql_block("EXEC SQL CLOSE EMP-CURSOR END-EXEC")
        assert block is not None
        assert block.sql_type == "CLOSE"
        assert block.cursor_name == "EMP-CURSOR"

    def test_select_into(self):
        block = _parse_sql_block(
            "EXEC SQL SELECT CUST-NAME, CUST-ADDR "
            "INTO :WS-NAME, :WS-ADDR "
            "FROM CUSTOMER WHERE CUST-ID = :WS-ID END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "SELECT"
        assert block.into_variables == ["WS-NAME", "WS-ADDR"]
        assert "WS-ID" in block.host_variables
        assert block.table_name == "CUSTOMER"

    def test_insert(self):
        block = _parse_sql_block(
            "EXEC SQL INSERT INTO ORDERS (ORD-ID, CUST-ID) "
            "VALUES (:WS-ORD-ID, :WS-CUST-ID) END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "INSERT"
        assert block.table_name == "ORDERS"
        assert "WS-ORD-ID" in block.host_variables
        assert "WS-CUST-ID" in block.host_variables

    def test_update(self):
        block = _parse_sql_block(
            "EXEC SQL UPDATE EMPLOYEE SET SALARY = :WS-NEW-SAL "
            "WHERE EMP-ID = :WS-EMP-ID END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "UPDATE"
        assert block.table_name == "EMPLOYEE"
        assert "WS-NEW-SAL" in block.host_variables

    def test_delete(self):
        block = _parse_sql_block(
            "EXEC SQL DELETE FROM ORDERS WHERE STATUS = :WS-STATUS END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "DELETE"
        assert block.table_name == "ORDERS"
        assert "WS-STATUS" in block.host_variables

    def test_commit(self):
        block = _parse_sql_block("EXEC SQL COMMIT END-EXEC")
        assert block is not None
        assert block.sql_type == "COMMIT"

    def test_rollback(self):
        block = _parse_sql_block("EXEC SQL ROLLBACK END-EXEC")
        assert block is not None
        assert block.sql_type == "ROLLBACK"

    def test_whenever_sqlerror(self):
        block = _parse_sql_block(
            "EXEC SQL WHENEVER SQLERROR CONTINUE END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "WHENEVER"
        assert block.whenever_condition == "SQLERROR"
        assert block.whenever_action == "CONTINUE"

    def test_whenever_not_found(self):
        block = _parse_sql_block(
            "EXEC SQL WHENEVER NOT FOUND GO TO NOT-FOUND-PARA END-EXEC"
        )
        assert block is not None
        assert block.sql_type == "WHENEVER"
        assert block.whenever_condition == "NOT FOUND"

    def test_unknown_sql_returns_none(self):
        block = _parse_sql_block("EXEC SQL XYZZY SOMETHING END-EXEC")
        assert block is None

    def test_malformed_sql_returns_none(self):
        block = _parse_sql_block("")
        assert block is None


# ---------------------------------------------------------------------------
# 2. strip_exec_blocks returns SqlBlock list
# ---------------------------------------------------------------------------
class TestStripExecBlocksReturnsBlocks:
    """Test that strip_exec_blocks returns both text and SqlBlock list."""

    def test_single_sql_block(self):
        raw = "       EXEC SQL SELECT * FROM TABLE END-EXEC\n"
        text, blocks, *_ = strip_exec_blocks(raw)
        assert "TODO(high)" in text
        assert len(blocks) == 1
        assert blocks[0].sql_type == "SELECT"

    def test_multiple_sql_blocks(self):
        raw = (
            "       EXEC SQL INCLUDE SQLCA END-EXEC\n"
            "       EXEC SQL DECLARE C1 CURSOR FOR SELECT A FROM B END-EXEC\n"
            "       EXEC SQL OPEN C1 END-EXEC\n"
            "       EXEC SQL FETCH C1 INTO :WS-A END-EXEC\n"
            "       EXEC SQL CLOSE C1 END-EXEC\n"
            "       EXEC SQL COMMIT END-EXEC\n"
        )
        text, blocks, *_ = strip_exec_blocks(raw)
        assert len(blocks) == 6
        types = [b.sql_type for b in blocks]
        assert types == ["INCLUDE", "DECLARE", "OPEN", "FETCH", "CLOSE", "COMMIT"]

    def test_cics_blocks_not_in_sql_list(self):
        raw = (
            "       EXEC CICS SEND MAP('MENU') END-EXEC\n"
            "       EXEC SQL COMMIT END-EXEC\n"
        )
        text, blocks, *_ = strip_exec_blocks(raw)
        assert len(blocks) == 1
        assert blocks[0].sql_type == "COMMIT"

    def test_no_exec_blocks_empty_list(self):
        raw = "       MOVE 1 TO WS-A.\n"
        text, blocks, *_ = strip_exec_blocks(raw)
        assert len(blocks) == 0
        assert "MOVE 1 TO WS-A" in text


# ---------------------------------------------------------------------------
# 3. SQL code generation
# ---------------------------------------------------------------------------
class TestSqlCodeGeneration:
    """Test translate_sql_block produces valid Python."""

    def _check_valid_python(self, lines: list[str]) -> None:
        """Verify the generated lines are valid Python when wrapped in a class."""
        code = (
            "class _T:\n"
            "    class _D:\n"
            "        class _F:\n"
            "            value = 0\n"
            "            def set(self, v): pass\n"
            "        ws_a = _F()\n"
            "        ws_b = _F()\n"
            "        ws_name = _F()\n"
            "        ws_salary = _F()\n"
            "        ws_dept = _F()\n"
            "        ws_id = _F()\n"
            "        ws_addr = _F()\n"
            "        ws_ord_id = _F()\n"
            "        ws_cust_id = _F()\n"
            "        ws_new_sal = _F()\n"
            "        ws_emp_id = _F()\n"
            "        ws_status = _F()\n"
            "    data = _D()\n"
            "    _sql_connection = None\n"
            "    _sql_cursor = None\n"
            "    _sqlcode = 0\n"
            "    def _method(self):\n"
        )
        for line in lines:
            code += f"        {line}\n"
        ast.parse(code)

    def test_include_sqlca(self):
        block = SqlBlock(sql_type="INCLUDE", raw_sql="INCLUDE SQLCA")
        lines = translate_sql_block(block)
        assert any("_sqlcode" in l for l in lines)
        self._check_valid_python(lines)

    def test_declare_cursor(self):
        block = SqlBlock(
            sql_type="DECLARE", raw_sql="DECLARE C1 ...",
            cursor_name="C1",
            sql_body="SELECT A FROM B WHERE C = :WS-ID",
            host_variables=["WS-ID"],
        )
        lines = translate_sql_block(block)
        assert any("_sql_c1" in l for l in lines)
        self._check_valid_python(lines)

    def test_open_cursor(self):
        block = SqlBlock(sql_type="OPEN", raw_sql="OPEN C1", cursor_name="C1")
        lines = translate_sql_block(block)
        assert any("cursor" in l.lower() for l in lines)
        self._check_valid_python(lines)

    def test_fetch_cursor(self):
        block = SqlBlock(
            sql_type="FETCH", raw_sql="FETCH C1 INTO ...",
            cursor_name="C1",
            into_variables=["WS-NAME", "WS-SALARY"],
        )
        lines = translate_sql_block(block)
        assert any("fetchone" in l for l in lines)
        assert any("ws_name" in l for l in lines)
        assert any("ws_salary" in l for l in lines)
        assert any("100" in l for l in lines)  # NOT FOUND
        self._check_valid_python(lines)

    def test_close_cursor(self):
        block = SqlBlock(
            sql_type="CLOSE", raw_sql="CLOSE C1", cursor_name="C1",
        )
        lines = translate_sql_block(block)
        assert any("close" in l for l in lines)
        self._check_valid_python(lines)

    def test_select_into(self):
        block = SqlBlock(
            sql_type="SELECT", raw_sql="SELECT ...",
            sql_body="SELECT A, B FROM TABLE WHERE C = :WS-ID",
            into_variables=["WS-A", "WS-B"],
            host_variables=["WS-ID"],
            table_name="TABLE",
        )
        lines = translate_sql_block(block)
        assert any("execute" in l for l in lines)
        assert any("fetchone" in l for l in lines)
        assert any("ws_a" in l for l in lines)
        self._check_valid_python(lines)

    def test_insert(self):
        block = SqlBlock(
            sql_type="INSERT", raw_sql="INSERT INTO T ...",
            sql_body="INSERT INTO T (A) VALUES (:WS-A)",
            table_name="T",
            host_variables=["WS-A"],
        )
        lines = translate_sql_block(block)
        assert any("execute" in l for l in lines)
        self._check_valid_python(lines)

    def test_update(self):
        block = SqlBlock(
            sql_type="UPDATE", raw_sql="UPDATE T ...",
            sql_body="UPDATE T SET A = :WS-A WHERE B = :WS-B",
            table_name="T",
            host_variables=["WS-A", "WS-B"],
        )
        lines = translate_sql_block(block)
        assert any("execute" in l for l in lines)
        self._check_valid_python(lines)

    def test_delete(self):
        block = SqlBlock(
            sql_type="DELETE", raw_sql="DELETE FROM T ...",
            sql_body="DELETE FROM T WHERE A = :WS-A",
            table_name="T",
            host_variables=["WS-A"],
        )
        lines = translate_sql_block(block)
        assert any("execute" in l for l in lines)
        self._check_valid_python(lines)

    def test_commit(self):
        block = SqlBlock(sql_type="COMMIT", raw_sql="COMMIT")
        lines = translate_sql_block(block)
        assert any("commit" in l for l in lines)
        self._check_valid_python(lines)

    def test_rollback(self):
        block = SqlBlock(sql_type="ROLLBACK", raw_sql="ROLLBACK")
        lines = translate_sql_block(block)
        assert any("rollback" in l for l in lines)
        self._check_valid_python(lines)

    def test_whenever(self):
        block = SqlBlock(
            sql_type="WHENEVER", raw_sql="WHENEVER SQLERROR CONTINUE",
            whenever_condition="SQLERROR",
            whenever_action="CONTINUE",
        )
        lines = translate_sql_block(block)
        assert any("SQLERROR" in l for l in lines)

    def test_unknown_type(self):
        block = SqlBlock(sql_type="XYZZY", raw_sql="XYZZY something")
        lines = translate_sql_block(block)
        assert any("unrecognized" in l for l in lines)


# ---------------------------------------------------------------------------
# 4. SQL imports and init helpers
# ---------------------------------------------------------------------------
class TestSqlHelpers:
    def test_generate_sql_imports(self):
        lines = generate_sql_imports()
        assert any("sqlite3" in l for l in lines)

    def test_generate_sql_init(self):
        lines = generate_sql_init()
        assert any("_sql_connection" in l for l in lines)
        assert any("_sqlcode" in l for l in lines)


# ---------------------------------------------------------------------------
# 5. Full pipeline integration: COBOL with EXEC SQL -> valid Python
# ---------------------------------------------------------------------------
class TestFullPipelineIntegration:
    """End-to-end: COBOL with EXEC SQL -> parse -> analyze -> generate -> ast.parse."""

    def test_simple_sql_program(self):
        """A COBOL program with EXEC SQL blocks produces valid Python."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. SQLTEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-NAME PIC X(30).\n"
            "       01 WS-SALARY PIC 9(7)V99.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
            "           EXEC SQL\n"
            "               SELECT EMP-NAME, EMP-SALARY\n"
            "               INTO :WS-NAME, :WS-SALARY\n"
            "               FROM EMPLOYEE\n"
            "               WHERE EMP-ID = 1\n"
            "           END-EXEC.\n"
            '           DISPLAY "DONE".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        assert len(prog.sql_blocks) == 2  # INCLUDE + SELECT
        smap = analyze(prog)
        py_source = generate_python(smap)
        # Must be valid Python
        ast.parse(py_source)
        # Must contain SQL-related code
        assert "sqlite3" in py_source
        assert "_sql_connection" in py_source
        assert "_sqlcode" in py_source

    def test_cursor_workflow(self):
        """DECLARE/OPEN/FETCH/CLOSE cursor produces valid Python."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. CURSTEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EXEC SQL DECLARE C1 CURSOR FOR\n"
            "               SELECT COL1 FROM TABLE1\n"
            "           END-EXEC.\n"
            "           EXEC SQL OPEN C1 END-EXEC.\n"
            "           EXEC SQL FETCH C1 INTO :WS-A END-EXEC.\n"
            "           EXEC SQL CLOSE C1 END-EXEC.\n"
            '           DISPLAY "OK".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        assert len(prog.sql_blocks) == 4
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)
        assert "_sql_declare_c1" in py_source or "_sql_c1" in py_source
        assert "fetchone" in py_source

    def test_dml_operations(self):
        """INSERT, UPDATE, DELETE, COMMIT produce valid Python."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DMLTEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-ID PIC 9(5).\n"
            "       01 WS-NAME PIC X(20).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EXEC SQL INSERT INTO CUSTOMER (ID, NAME)\n"
            "               VALUES (:WS-ID, :WS-NAME)\n"
            "           END-EXEC.\n"
            "           EXEC SQL UPDATE CUSTOMER SET NAME = :WS-NAME\n"
            "               WHERE ID = :WS-ID\n"
            "           END-EXEC.\n"
            "           EXEC SQL DELETE FROM CUSTOMER\n"
            "               WHERE ID = :WS-ID\n"
            "           END-EXEC.\n"
            "           EXEC SQL COMMIT END-EXEC.\n"
            '           DISPLAY "DONE".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        assert len(prog.sql_blocks) == 4
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)
        assert "commit" in py_source
        assert "execute" in py_source

    def test_no_sql_no_sql_imports(self):
        """A program without EXEC SQL does NOT get SQL imports."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NOSQL.\n"
            "       DATA DIVISION.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            '           DISPLAY "NO SQL HERE".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        assert len(prog.sql_blocks) == 0
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)
        assert "sqlite3" not in py_source
        assert "_sql_connection" not in py_source

    def test_sql_with_host_variables_parameterized(self):
        """Host variables (:VAR) become parameterized queries with ?."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. PARAMTEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-DEPT PIC X(10).\n"
            "       01 WS-NAME PIC X(30).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EXEC SQL DECLARE DC CURSOR FOR\n"
            "               SELECT NAME FROM EMP\n"
            "               WHERE DEPT = :WS-DEPT\n"
            "           END-EXEC.\n"
            '           DISPLAY "OK".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)
        # Host variable should be replaced with ? placeholder
        assert "?" in py_source
        assert "ws_dept" in py_source

    def test_mixed_sql_and_cics(self):
        """Programs with both EXEC SQL and EXEC CICS produce valid Python."""
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. MIXTEST.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EXEC CICS SEND MAP('MENU') END-EXEC.\n"
            "           EXEC SQL COMMIT END-EXEC.\n"
            '           DISPLAY "OK".\n'
            "           STOP RUN.\n"
        )
        prog = parse_cobol(src)
        # Only SQL blocks are captured
        assert len(prog.sql_blocks) == 1
        smap = analyze(prog)
        py_source = generate_python(smap)
        ast.parse(py_source)
        assert "commit" in py_source
