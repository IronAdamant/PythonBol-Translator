"""Generate Python DB-API 2.0 code from extracted EXEC SQL blocks.

Pipeline position: Parser -> AST (with SqlBlocks) -> Analyzer -> **Mapper** -> Python source

Translates structured SqlBlock metadata into runnable Python code that
uses the DB-API 2.0 interface (PEP 249). Compatible with sqlite3, psycopg2,
cx_Oracle, pyodbc, and any other DB-API compliant driver.
"""

from __future__ import annotations

from .models import SqlBlock


def _cobol_to_python_name(name: str) -> str:
    """Convert a COBOL variable name to a Python-compatible name."""
    return name.strip().replace("-", "_").lower()


def generate_sql_imports() -> list[str]:
    """Return import lines for SQL support."""
    return [
        "import sqlite3  # DB-API 2.0 — swap for psycopg2, cx_Oracle, pyodbc, etc.",
        "",
    ]


def generate_sql_init() -> list[str]:
    """Return __init__ lines for SQL connection setup."""
    return [
        '        # SQL connection — configure for your database',
        '        # Example: self._sql_connection = sqlite3.connect("database.db")',
        '        #          self._sql_connection = psycopg2.connect(dsn)',
        '        self._sql_connection = None  # TODO(high): configure database connection',
        '        self._sql_cursor = None',
        '        self._sqlcode = 0',
    ]


def translate_sql_block(block: SqlBlock) -> list[str]:
    """Translate a single SqlBlock into Python DB-API code lines.

    Returns a list of Python code strings (without leading indentation).
    The caller is responsible for adding the appropriate indentation.
    """
    sql_type = block.sql_type.upper()

    if sql_type == "INCLUDE":
        return [
            "# SQL: INCLUDE SQLCA — SQL Communication Area",
            "self._sqlcode = 0",
        ]

    if sql_type == "WHENEVER":
        cond = block.whenever_condition
        action = block.whenever_action
        return [
            f"# SQL: WHENEVER {cond} {action}",
            f"# (sqlcode checked after each SQL operation)",
        ]

    if sql_type == "DECLARE":
        cursor = _cobol_to_python_name(block.cursor_name)
        sql_body = block.sql_body
        # Replace host variable references (:VAR) with parameter placeholders
        clean_sql = sql_body
        params = []
        for hv in block.host_variables:
            py_var = _cobol_to_python_name(hv)
            clean_sql = clean_sql.replace(f":{hv}", "?")
            params.append(f"self.data.{py_var}.value")
        lines = [
            f"# DECLARE {block.cursor_name} CURSOR",
            f'self._sql_{cursor} = """{clean_sql}"""',
        ]
        if params:
            lines.append(
                f"self._sql_{cursor}_params = "
                f"lambda: ({', '.join(params)},)"
            )
        return lines

    if sql_type == "OPEN":
        cursor = _cobol_to_python_name(block.cursor_name)
        lines = [
            f"# OPEN {block.cursor_name}",
            f"self._sql_cursor_{cursor} = self._sql_connection.cursor()",
        ]
        lines.append(
            f"if hasattr(self, '_sql_{cursor}_params'):"
        )
        lines.append(
            f"    self._sql_cursor_{cursor}.execute("
            f"self._sql_{cursor}, self._sql_{cursor}_params())"
        )
        lines.append(f"else:")
        lines.append(
            f"    self._sql_cursor_{cursor}.execute(self._sql_{cursor})"
        )
        lines.append("self._sqlcode = 0")
        return lines

    if sql_type == "FETCH":
        cursor = _cobol_to_python_name(block.cursor_name)
        lines = [
            f"# FETCH {block.cursor_name}",
            f"_sql_row = self._sql_cursor_{cursor}.fetchone()",
            "if _sql_row is None:",
            "    self._sqlcode = 100  # NOT FOUND",
            "else:",
        ]
        for idx, var in enumerate(block.into_variables):
            py_var = _cobol_to_python_name(var)
            lines.append(f"    self.data.{py_var}.set(_sql_row[{idx}])")
        lines.append("    self._sqlcode = 0")
        return lines

    if sql_type == "CLOSE":
        cursor = _cobol_to_python_name(block.cursor_name)
        return [
            f"# CLOSE {block.cursor_name}",
            f"self._sql_cursor_{cursor}.close()",
            "self._sqlcode = 0",
        ]

    if sql_type == "SELECT":
        sql_body = block.sql_body
        # Replace host variable references with parameter placeholders
        clean_sql = sql_body
        params = []
        for hv in block.host_variables:
            py_var = _cobol_to_python_name(hv)
            clean_sql = clean_sql.replace(f":{hv}", "?")
            params.append(f"self.data.{py_var}.value")

        lines = [
            "# SQL: SELECT",
            "_sql_cur = self._sql_connection.cursor()",
        ]
        if params:
            lines.append(
                f'_sql_cur.execute("""{clean_sql}""", '
                f'({", ".join(params)},))'
            )
        else:
            lines.append(f'_sql_cur.execute("""{clean_sql}""")')

        lines.append("_sql_row = _sql_cur.fetchone()")
        lines.append("if _sql_row is None:")
        lines.append("    self._sqlcode = 100  # NOT FOUND")
        lines.append("else:")
        for idx, var in enumerate(block.into_variables):
            py_var = _cobol_to_python_name(var)
            lines.append(f"    self.data.{py_var}.set(_sql_row[{idx}])")
        lines.append("    self._sqlcode = 0")
        return lines

    if sql_type in ("INSERT", "UPDATE", "DELETE"):
        sql_body = block.sql_body
        clean_sql = sql_body
        params = []
        for hv in block.host_variables:
            py_var = _cobol_to_python_name(hv)
            clean_sql = clean_sql.replace(f":{hv}", "?")
            params.append(f"self.data.{py_var}.value")

        lines = [f"# SQL: {sql_type}"]
        if params:
            lines.append(
                f'self._sql_connection.cursor().execute('
                f'"""{clean_sql}""", ({", ".join(params)},))'
            )
        else:
            lines.append(
                f'self._sql_connection.cursor().execute("""{clean_sql}""")'
            )
        lines.append("self._sqlcode = 0")
        return lines

    if sql_type == "COMMIT":
        return [
            "# SQL: COMMIT",
            "self._sql_connection.commit()",
            "self._sqlcode = 0",
        ]

    if sql_type == "ROLLBACK":
        return [
            "# SQL: ROLLBACK",
            "self._sql_connection.rollback()",
            "self._sqlcode = 0",
        ]

    # Unknown SQL type — emit as comment
    return [
        f"# SQL: (unrecognized type: {sql_type})",
        f"# {block.raw_sql}",
    ]


