"""CICS-to-Flask translation framework.

Generates Flask route templates from CICS EXEC blocks and SCREEN SECTION
definitions. The generated code is a starting point -- not production-ready.

Flask is NOT a dependency of this project. The generated template requires
``pip install flask`` to run. The translator itself remains zero-dep.
"""

from __future__ import annotations

import re

from .models import CobolProgram, ScreenField
from .utils import _to_python_name


# Regex patterns for extracting CICS metadata from raw statement text
_SEND_MAP_RE = re.compile(
    r"SEND\s+MAP\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE,
)
_RECEIVE_MAP_RE = re.compile(
    r"RECEIVE\s+MAP\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE,
)
_START_TRANSID_RE = re.compile(
    r"START\s+TRANSID\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE,
)
_COMMAREA_RE = re.compile(
    r"COMMAREA\s*\(\s*'?([^')]+)'?\s*\)", re.IGNORECASE,
)


def has_cics(program: CobolProgram) -> bool:
    """Check if the program uses CICS constructs.

    Checks both statement raw text (for unparsed EXEC CICS) and
    raw source lines (for preprocessor-generated CICS hints like
    ``* CICS MAP:`` or ``* Original: EXEC CICS ...``).
    """
    return any(
        "CICS" in stmt.raw_text.upper()
        for para in program.paragraphs
        for stmt in para.statements
    ) or any(
        "EXEC CICS" in (upper := line.upper()) or "CICS MAP:" in upper
        for line in program.raw_lines
    )


def _collect_cics_texts(program: CobolProgram) -> list[str]:
    """Collect all statement and raw-line texts for CICS pattern scanning."""
    texts: list[str] = []
    for para in program.paragraphs:
        for stmt in para.statements:
            texts.append(stmt.raw_text)
    texts.extend(program.raw_lines)
    return texts


def _extract_cics_entities(
    texts: list[str],
    patterns: list[re.Pattern[str]],
    hint_pattern: str,
) -> list[str]:
    """Scan texts for CICS patterns and preprocessor hints.

    Returns a deduplicated list of matched names in discovery order.
    *patterns* are compiled regexes whose group(1) captures the name.
    *hint_pattern* is a raw regex string for preprocessor hint lines.
    """
    seen: set[str] = set()
    result: list[str] = []
    hint_re = re.compile(hint_pattern, re.IGNORECASE)
    for text in texts:
        for regex in patterns:
            if m := regex.search(text):
                name = m.group(1).strip()
                if name not in seen:
                    seen.add(name)
                    result.append(name)
        if hint_m := hint_re.search(text):
            name = hint_m.group(1).strip()
            if name not in seen:
                seen.add(name)
                result.append(name)
    return result


def _extract_maps(program: CobolProgram) -> list[str]:
    """Extract SEND MAP / RECEIVE MAP names from program."""
    return _extract_cics_entities(
        _collect_cics_texts(program),
        [_SEND_MAP_RE, _RECEIVE_MAP_RE],
        r"CICS\s+MAP:\s*(\S+)",
    )


def _extract_transids(program: CobolProgram) -> list[str]:
    """Extract START TRANSID names from program."""
    return _extract_cics_entities(
        _collect_cics_texts(program),
        [_START_TRANSID_RE],
        r"CICS\s+TRANSID:\s*(\S+)",
    )


def _extract_commareas(program: CobolProgram) -> list[str]:
    """Extract COMMAREA names from program."""
    return _extract_cics_entities(
        _collect_cics_texts(program),
        [_COMMAREA_RE],
        r"COMMAREA:\s*(\S+)",
    )


def _generate_html_from_screen(screen: ScreenField) -> list[str]:
    """Generate simple HTML form lines from a SCREEN SECTION field tree.

    VALUE fields become labels, USING/TO fields become input elements.
    Returns an empty list if the screen has no meaningful content.
    """
    html: list[str] = []
    html.append("<!DOCTYPE html>")
    html.append("<html>")
    html.append("<head><title>Screen: "
                f"{screen.name or 'unnamed'}</title></head>")
    html.append("<body>")
    html.append(f'<h1>{screen.name or "Transaction"}</h1>')
    html.append('<form method="POST">')

    fields = _collect_leaf_fields(screen)
    has_content = False
    for f in fields:
        if f.blank_screen:
            continue
        if f.value:
            html.append(f"  <label>{f.value}</label>")
            has_content = True
        if f.using or f.to_field:
            field_name = f.using or f.to_field
            py_name = _to_python_name(field_name)
            pic_size = ""
            if f.pic:
                # Extract size from PIC clause (e.g., X(20) -> 20)
                m = re.search(r"\((\d+)\)", f.pic)
                if m:
                    pic_size = f' maxlength="{m.group(1)}"'
            html.append(
                f'  <input type="text" name="{py_name}"'
                f' value="{{{{ {py_name}|default(\'\') }}}}"'
                f"{pic_size}><br>"
            )
            has_content = True
        elif f.from_field:
            py_name = _to_python_name(f.from_field)
            html.append(
                f"  <span>{{{{ {py_name}|default('') }}}}</span>"
            )
            has_content = True

    html.append('  <button type="submit">Submit</button>')
    html.append("</form>")
    html.append("</body>")
    html.append("</html>")

    if not has_content:
        return []
    return html


def _collect_leaf_fields(sf: ScreenField) -> list[ScreenField]:
    """Recursively collect leaf-level screen fields."""
    if not sf.children:
        return [sf]
    leaves: list[ScreenField] = []
    for child in sf.children:
        leaves.extend(_collect_leaf_fields(child))
    return leaves


def generate_cics_template(program: CobolProgram) -> str | None:
    """Generate a Flask application template from CICS patterns.

    Returns None if the program doesn't use CICS.
    """
    if not has_cics(program):
        return None

    pid = _to_python_name(program.program_id or "cics_app")

    # Extract CICS metadata from raw statements
    maps = _extract_maps(program)
    transids = _extract_transids(program)
    commareas = _extract_commareas(program)

    lines = [
        '"""',
        f"Flask application template generated from CICS program:"
        f" {program.program_id}",
        "",
        "This is a STARTING POINT for migrating CICS online transactions"
        " to a web application.",
        "Review and modify before production use.",
        "",
        "Install: pip install flask",
        f"Run: flask --app {pid}_flask run",
        '"""',
        "",
        "from flask import Flask, render_template, request,"
        " session, redirect, url_for",
        "",
        f"app = Flask(__name__)",
        'app.secret_key = "TODO-change-this-secret-key"',
        "",
    ]

    # Generate route for each MAP
    if maps:
        for map_name in maps:
            py_map = _to_python_name(map_name)
            lines.extend([
                "",
                f'@app.route("/{py_map}", methods=["GET", "POST"])',
                f"def {py_map}():",
                f'    """CICS MAP: {map_name}',
                f"",
                f"    SEND MAP -> render template (GET)",
                f"    RECEIVE MAP -> process form (POST)",
                f'    """',
                f"    if request.method == \"POST\":",
                f"        # RECEIVE MAP -- form data",
                f"        form_data = request.form.to_dict()",
                f"        # TODO: process form data, update COMMAREA",
                f'        session["commarea"] = form_data',
                f'        return redirect(url_for("{py_map}"))',
                f"",
                f"    # SEND MAP -- render form",
                f'    commarea = session.get("commarea", {{}})',
                f'    return render_template("{py_map}.html", **commarea)',
            ])
    else:
        # No maps found -- generate a generic route
        lines.extend([
            "",
            '@app.route("/", methods=["GET", "POST"])',
            "def index():",
            '    """Main transaction entry point."""',
            '    if request.method == "POST":',
            "        form_data = request.form.to_dict()",
            '        session["commarea"] = form_data',
            '        return redirect(url_for("index"))',
            '    commarea = session.get("commarea", {})',
            '    return render_template("index.html", **commarea)',
        ])

    # Generate COMMAREA as session state
    if commareas:
        lines.extend([
            "",
            "",
            "# COMMAREA fields (stored in Flask session):",
        ])
        for field in commareas:
            lines.append(f"#   {field}")

    # Generate TRANSID mapping
    if transids:
        lines.extend([
            "",
            "",
            "# CICS Transaction IDs:",
        ])
        for tid in transids:
            lines.append(f"#   {tid} -> /{_to_python_name(tid)}")

    # Generate HTML template hints
    lines.extend([
        "",
        "",
        "# --- HTML Template Generation ---",
        "# Place templates in templates/ directory.",
        "#",
    ])

    # Generate simple HTML from SCREEN SECTION if available
    if program.screen_section:
        for screen in program.screen_section:
            html = _generate_html_from_screen(screen)
            if html:
                py_name = (
                    _to_python_name(screen.name) if screen.name else "index"
                )
                lines.append(f"# Save as templates/{py_name}.html:")
                for html_line in html:
                    lines.append(f"# {html_line}")
                lines.append("#")

    lines.extend([
        "",
        "",
        'if __name__ == "__main__":',
        "    app.run(debug=True)",
        "",
    ])

    return "\n".join(lines)
