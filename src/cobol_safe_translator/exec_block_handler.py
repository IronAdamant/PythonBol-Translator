"""EXEC block stripper and hint generator.

Handles EXEC CICS, EXEC SQL, EXEC DLI, and other EXEC blocks found in
COBOL source.  Strips them from the source text, replacing each with TODO
comments and Python-equivalent hints.  Also parses EXEC SQL blocks into
structured ``SqlBlock`` metadata for downstream code generation.

Called by the preprocessor as part of the COBOL pre-processing pipeline.
"""

from __future__ import annotations

import re

from .models import SqlBlock

# ── EXEC start / end detection ───────────────────────────────────────────

_EXEC_START_RE = re.compile(
    r"EXEC\s+(\w+)\b",
    re.IGNORECASE,
)
_END_EXEC_RE = re.compile(r"END-EXEC", re.IGNORECASE)

# ── Hint lookup table ────────────────────────────────────────────────────

_EXEC_HINTS: dict[tuple[str, str], str] = {
    ("CICS", "SEND"): "UI output -> print() or template rendering",
    ("CICS", "RECEIVE"): "UI input -> input() or request parsing",
    ("CICS", "READ"): "VSAM read -> db cursor.execute('SELECT ...')",
    ("CICS", "WRITE"): "VSAM write -> db cursor.execute('INSERT ...')",
    ("CICS", "REWRITE"): "VSAM update -> db cursor.execute('UPDATE ...')",
    ("CICS", "DELETE"): "VSAM delete -> db cursor.execute('DELETE ...')",
    ("CICS", "RETURN"): "return control -> return or sys.exit()",
    ("CICS", "XCTL"): "transfer control -> function call or import",
    ("CICS", "LINK"): "call subprogram -> function call",
    ("CICS", "START"): "start transaction -> async task / queue",
    ("CICS", "SYNCPOINT"): "commit -> db connection.commit()",
    ("SQL", "SELECT"): "cursor.execute('SELECT ...')",
    ("SQL", "INSERT"): "cursor.execute('INSERT ...')",
    ("SQL", "UPDATE"): "cursor.execute('UPDATE ...')",
    ("SQL", "DELETE"): "cursor.execute('DELETE ...')",
    ("SQL", "OPEN"): "cursor = connection.cursor()",
    ("SQL", "CLOSE"): "cursor.close()",
    ("SQL", "FETCH"): "row = cursor.fetchone()",
    ("SQL", "COMMIT"): "connection.commit()",
    ("SQL", "ROLLBACK"): "connection.rollback()",
    ("SQL", "DECLARE"): "cursor declaration (prepare SQL)",
    ("DLI", "GU"): "DL/I Get Unique -> db query by key",
    ("DLI", "GN"): "DL/I Get Next -> cursor.fetchone()",
    ("DLI", "ISRT"): "DL/I Insert -> cursor.execute('INSERT ...')",
    ("DLI", "REPL"): "DL/I Replace -> cursor.execute('UPDATE ...')",
    ("DLI", "DLET"): "DL/I Delete -> cursor.execute('DELETE ...')",
}

# Regex to find the first verb/keyword after EXEC TYPE
_EXEC_VERB_RE = re.compile(
    r"EXEC\s+\w+\s+(\w+)", re.IGNORECASE,
)

# Regex to extract host variables (:VAR-NAME) from SQL text
_HOST_VAR_RE = re.compile(r":([A-Za-z][\w-]*)")

# ── CICS enhanced hint regexes ───────────────────────────────────────────

_CICS_MAP_RE = re.compile(r"(?:SEND|RECEIVE)\s+MAP\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_TRANSID_RE = re.compile(r"START\s+TRANSID\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_PROGRAM_RE = re.compile(r"(?:LINK|XCTL)\s+PROGRAM\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_COMMAREA_RE = re.compile(r"COMMAREA\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_RESP_RE = re.compile(r"RESP\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)
_CICS_RESP2_RE = re.compile(r"RESP2\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE)


# ── Helper functions ─────────────────────────────────────────────────────


def _cobol_to_python_name(name: str) -> str:
    """Convert a COBOL variable name to a Python-compatible name."""
    return name.strip().replace("-", "_").lower()


def _parse_sql_block(sql_text: str) -> SqlBlock | None:
    """Parse EXEC SQL text into a structured SqlBlock.

    Returns None if the text cannot be parsed.
    """
    try:
        text = " ".join(sql_text.split())
        text = re.sub(r"^EXEC\s+SQL\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*END-EXEC\.?\s*$", "", text, flags=re.IGNORECASE)
        upper = text.upper().strip()

        if upper.startswith("INCLUDE") and "SQLCA" in upper:
            return SqlBlock(sql_type="INCLUDE", raw_sql=text)

        m = re.match(r"WHENEVER\s+(SQLERROR|NOT\s+FOUND)\s+(.*)", upper)
        if m:
            return SqlBlock(
                sql_type="WHENEVER", raw_sql=text,
                whenever_condition=m.group(1).strip(),
                whenever_action=m.group(2).strip(),
            )

        m = re.match(
            r"DECLARE\s+(\S+)\s+CURSOR\s+FOR\s+(.*)", text, re.IGNORECASE,
        )
        if m:
            cursor_name = m.group(1).strip()
            body = m.group(2).strip()
            return SqlBlock(
                sql_type="DECLARE", raw_sql=text,
                cursor_name=cursor_name,
                host_variables=_HOST_VAR_RE.findall(body),
                sql_body=body,
            )

        m = re.match(r"OPEN\s+(\S+)\s*$", text, re.IGNORECASE)
        if m:
            return SqlBlock(
                sql_type="OPEN", raw_sql=text,
                cursor_name=m.group(1).strip(),
            )

        m = re.match(r"FETCH\s+(\S+)\s+INTO\s+(.*)", text, re.IGNORECASE)
        if m:
            return SqlBlock(
                sql_type="FETCH", raw_sql=text,
                cursor_name=m.group(1).strip(),
                into_variables=_HOST_VAR_RE.findall(m.group(2)),
            )

        m = re.match(r"CLOSE\s+(\S+)\s*$", text, re.IGNORECASE)
        if m:
            return SqlBlock(
                sql_type="CLOSE", raw_sql=text,
                cursor_name=m.group(1).strip(),
            )

        m = re.match(
            r"(SELECT\s+.+?)\s+INTO\s+(.+?)\s+FROM\s+(.*)",
            text, re.IGNORECASE,
        )
        if m:
            select_part = m.group(1).strip()
            from_part = m.group(3).strip()
            table_m = re.match(r"\S+", from_part)
            return SqlBlock(
                sql_type="SELECT", raw_sql=text,
                into_variables=_HOST_VAR_RE.findall(m.group(2)),
                host_variables=_HOST_VAR_RE.findall(from_part),
                sql_body=f"{select_part} FROM {from_part}",
                table_name=table_m.group(0) if table_m else "",
            )

        m = re.match(r"INSERT\s+INTO\s+(\S+)\b(.*)", text, re.IGNORECASE)
        if m:
            return SqlBlock(
                sql_type="INSERT", raw_sql=text,
                table_name=m.group(1).strip(),
                host_variables=_HOST_VAR_RE.findall(text),
                sql_body=text,
            )

        m = re.match(r"UPDATE\s+(\S+)\b(.*)", text, re.IGNORECASE)
        if m:
            return SqlBlock(
                sql_type="UPDATE", raw_sql=text,
                table_name=m.group(1).strip(),
                host_variables=_HOST_VAR_RE.findall(text),
                sql_body=text,
            )

        m = re.match(r"DELETE\s+FROM\s+(\S+)\b(.*)", text, re.IGNORECASE)
        if m:
            return SqlBlock(
                sql_type="DELETE", raw_sql=text,
                table_name=m.group(1).strip(),
                host_variables=_HOST_VAR_RE.findall(text),
                sql_body=text,
            )

        # Bare SELECT (without INTO -- e.g. SELECT * FROM ...)
        m = re.match(r"SELECT\b(.*)", text, re.IGNORECASE)
        if m:
            table_m = re.search(r"FROM\s+(\S+)", text, re.IGNORECASE)
            return SqlBlock(
                sql_type="SELECT", raw_sql=text,
                host_variables=_HOST_VAR_RE.findall(text),
                sql_body=text,
                table_name=table_m.group(1) if table_m else "",
            )

        if upper.startswith("COMMIT"):
            return SqlBlock(sql_type="COMMIT", raw_sql=text)
        if upper.startswith("ROLLBACK"):
            return SqlBlock(sql_type="ROLLBACK", raw_sql=text)

        return None
    except Exception:
        return None


def _sql_hint(sql_text: str) -> list[str]:
    """Parse EXEC SQL text and return enhanced hint lines.

    Returns a list of hint strings (without the '* EXEC SQL hint: ' prefix).
    Falls back to an empty list if parsing fails.
    """
    try:
        # Normalize whitespace for easier parsing
        text = " ".join(sql_text.split())
        # Remove EXEC SQL prefix and END-EXEC suffix
        text = re.sub(r"^EXEC\s+SQL\s+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*END-EXEC\.?\s*$", "", text, flags=re.IGNORECASE)
        upper = text.upper().strip()

        # INCLUDE SQLCA
        if upper.startswith("INCLUDE") and "SQLCA" in upper:
            return ["sqlcode = 0  # SQLCA: check after each SQL operation"]

        # WHENEVER SQLERROR / NOT FOUND
        m = re.match(
            r"WHENEVER\s+(SQLERROR|NOT\s+FOUND)\s+(.*)",
            upper,
        )
        if m:
            condition = m.group(1).strip()
            action = m.group(2).strip()
            return [f"# WHENEVER {condition} {action}"]

        # DECLARE cursor-name CURSOR FOR ...
        m = re.match(
            r"DECLARE\s+(\S+)\s+CURSOR\s+FOR\s+(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            sql_body = m.group(2).strip()
            return [
                f"cursor_{cursor_name} = connection.cursor()",
                f'cursor_{cursor_name}.execute("{sql_body}")',
            ]

        # OPEN cursor-name
        m = re.match(r"OPEN\s+(\S+)\s*$", text, re.IGNORECASE)
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            return [
                f"cursor_{cursor_name}.execute(sql_{cursor_name})"
                f"  # OPEN CURSOR",
            ]

        # FETCH cursor-name INTO :var1, :var2, ...
        m = re.match(
            r"FETCH\s+(\S+)\s+INTO\s+(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            host_vars = _HOST_VAR_RE.findall(m.group(2))
            lines = [f"row = cursor_{cursor_name}.fetchone()  # FETCH"]
            for idx, var in enumerate(host_vars):
                py_var = _cobol_to_python_name(var)
                lines.append(f"self.data.{py_var}.set(row[{idx}])")
            return lines

        # CLOSE cursor-name
        m = re.match(r"CLOSE\s+(\S+)\s*$", text, re.IGNORECASE)
        if m:
            cursor_name = _cobol_to_python_name(m.group(1))
            return [f"cursor_{cursor_name}.close()"]

        # SELECT ... INTO :var1, :var2 FROM ...
        m = re.match(
            r"(SELECT\s+.+?)\s+INTO\s+(.+?)\s+FROM\s+(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            select_part = m.group(1).strip()
            into_part = m.group(2).strip()
            from_part = m.group(3).strip()
            host_vars = _HOST_VAR_RE.findall(into_part)
            sql_stmt = f"{select_part} FROM {from_part}"
            lines = [f'row = cursor.execute("{sql_stmt}").fetchone()']
            for idx, var in enumerate(host_vars):
                py_var = _cobol_to_python_name(var)
                lines.append(f"self.data.{py_var}.set(row[{idx}])")
            return lines

        # INSERT / UPDATE / DELETE / bare SELECT (DML without cursor)
        m = re.match(
            r"(INSERT|UPDATE|DELETE|SELECT)\b(.*)",
            text,
            re.IGNORECASE,
        )
        if m:
            sql_stmt = text.strip()
            return [f'cursor.execute("{sql_stmt}")']

        # COMMIT / ROLLBACK
        if upper.startswith("COMMIT"):
            return ["connection.commit()"]
        if upper.startswith("ROLLBACK"):
            return ["connection.rollback()"]

        return []
    except Exception:
        return []


def _exec_hint(exec_type: str, original_text: str) -> str:
    """Return a Python-equivalent hint for an EXEC block, or empty string."""
    m = _EXEC_VERB_RE.search(original_text)
    if not m:
        return ""
    verb = m.group(1).upper()
    hint = _EXEC_HINTS.get((exec_type, verb), "")
    return hint


def _cics_hint(cics_text: str) -> list[str]:
    """Extract structured CICS hints from an EXEC CICS block.

    Returns a list of hint comment strings with extracted details.
    """
    hints: list[str] = []

    map_m = _CICS_MAP_RE.search(cics_text)
    if map_m:
        hints.append(f"      * CICS MAP: {map_m.group(1).strip()}")

    transid_m = _CICS_TRANSID_RE.search(cics_text)
    if transid_m:
        hints.append(f"      * CICS TRANSID: {transid_m.group(1).strip()}")

    prog_m = _CICS_PROGRAM_RE.search(cics_text)
    if prog_m:
        prog_name = prog_m.group(1).strip()
        comm_m = _CICS_COMMAREA_RE.search(cics_text)
        comm_name = comm_m.group(1).strip() if comm_m else ""
        if comm_name:
            hints.append(f"      * CICS PROGRAM: {prog_name}, COMMAREA: {comm_name}")
        else:
            hints.append(f"      * CICS PROGRAM: {prog_name}")

    resp_m = _CICS_RESP_RE.search(cics_text)
    if resp_m:
        resp_name = resp_m.group(1).strip()
        resp2_m = _CICS_RESP2_RE.search(cics_text)
        resp2_name = resp2_m.group(1).strip() if resp2_m else ""
        if resp2_name:
            hints.append(f"      * CICS RESP: {resp_name}, RESP2: {resp2_name}")
        else:
            hints.append(f"      * CICS RESP: {resp_name}")

    return hints


def strip_exec_blocks(raw_text: str) -> tuple[str, list[SqlBlock]]:
    """Replace EXEC CICS/SQL ... END-EXEC blocks with TODO comments.

    Returns a tuple of (processed_text, sql_blocks) where sql_blocks
    contains structured metadata for each EXEC SQL block found.
    """
    lines = raw_text.splitlines()
    result: list[str] = []
    sql_blocks: list[SqlBlock] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        # Check content area for EXEC start
        content = line[7:72] if len(line) > 7 else line
        m = _EXEC_START_RE.search(content)
        if not m:
            # Also check free-format
            m = _EXEC_START_RE.search(line)
        if not m:
            result.append(line)
            i += 1
            continue

        exec_type = m.group(1).upper()
        # Collect lines until END-EXEC
        block_lines = []
        while i < len(lines):
            block_lines.append(lines[i].rstrip())
            check = lines[i][7:72] if len(lines[i]) > 7 else lines[i]
            if _END_EXEC_RE.search(check) or _END_EXEC_RE.search(lines[i]):
                i += 1
                break
            i += 1

        # Build the original text as a single line for the comment
        original_parts = []
        for bl in block_lines:
            # Extract content area, strip leading/trailing whitespace
            part = bl[7:72].strip() if len(bl) > 7 else bl.strip()
            if part:
                original_parts.append(part)
        original_text = " ".join(original_parts)

        result.append(
            f"      * TODO(high): EXEC {exec_type} block "
            f"— requires manual translation"
        )
        result.append(
            f"      * Original: {original_text}"
        )

        # Enhanced SQL metadata extraction
        if exec_type == "SQL":
            sql_block = _parse_sql_block(original_text)
            if sql_block is not None:
                sql_blocks.append(sql_block)
            sql_hints = _sql_hint(original_text)
            if sql_hints:
                for sh in sql_hints:
                    result.append(f"      * EXEC SQL hint: {sh}")
            else:
                # Fall back to generic hint
                hint = _exec_hint(exec_type, original_text)
                if hint:
                    result.append(f"      * Hint: {hint}")
        elif exec_type == "CICS":
            cics_hints = _cics_hint(original_text)
            if cics_hints:
                for ch in cics_hints:
                    result.append(ch)
            hint = _exec_hint(exec_type, original_text)
            if hint:
                result.append(f"      * Hint: {hint}")
        else:
            hint = _exec_hint(exec_type, original_text)
            if hint:
                result.append(f"      * Hint: {hint}")

    return "\n".join(result), sql_blocks
